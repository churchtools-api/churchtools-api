"""More write scenarios: master data, follow-ups, group and post extras, templates.

Not covered on purpose (see docs/testbericht.md): operations that send emails or
push messages, change logins, passwords, 2FA or permissions, change the global
configuration, or talk to external systems (sync, SAML/OIDC, newsletters).
"""

from __future__ import annotations

import datetime as dt
import itertools
import typing as _t

import pytest

import churchtools_rs as ct
from churchtools_rs import models as m

from conftest import LiveClient
from scenario import NOW, Cleanup, name, required_person_fields

pytestmark = pytest.mark.usefixtures("scenario")


# --- simple master data ---------------------------------------------------------

MASTERDATA: dict[str, tuple[dict[str, _t.Any], dict[str, _t.Any], dict[str, _t.Any]]] = {
    "song.categories": ({}, {}, {}),
    "song.sources": ({}, {}, {}),
    "resourcetypes": ({"name_plural": "Testräume", "sort_key": 999}, {"name_plural": "Testräume 2", "sort_key": 998}, {}),
    "furtherlinks": (
        {"description": None, "image_url": None, "sort_key": 999, "url": "https://example.org"},
        {"description": "Beschreibung", "image_url": None, "sort_key": 998, "url": "https://example.org/neu"},
        {},
    ),
    "group.meeting_templates": (
        {"template": [m.MeetingTemplateField(label="Thema", type_="input")]},
        {"template": [m.MeetingTemplateField(label="Thema", type_="input"), m.MeetingTemplateField(label="Notiz", type_="textarea")]},
        {"dry_run": False},
    ),
}


@pytest.mark.parametrize("call", list(MASTERDATA))
def test_more_masterdata(client: LiveClient, call: str, cleanup: Cleanup) -> None:
    create_kw, update_kw, delete_kw = MASTERDATA[call]
    resource: _t.Any = client
    for part in call.split("."):
        resource = getattr(resource, part)
    created = resource.create(name=name(call.split(".")[-1]), **create_kw)
    cleanup(lambda: resource.delete(created.id, **delete_kw))
    resource.get(created.id)
    resource.update(created.id, name=created.name + " neu", **update_kw)
    assert resource.get(created.id).name == created.name + " neu"
    resource.delete(created.id, **delete_kw)


def test_status_patch(client: LiveClient, cleanup: Cleanup) -> None:
    status = client.statuses.create(name=name("Status"), security_level_id=1, shorty="T")
    cleanup(lambda: client.statuses.delete(status.id))
    assert client.statuses.patch(status.id, shorty="T2").shorty == "T2"
    client.statuses.delete(status.id)


def test_group_type_with_role(client: LiveClient, cleanup: Cleanup) -> None:
    group_type = client.group.group_types.create(
        name=name("GT")[-14:],  # at most 30 characters
        name_plural="Testgruppen",
        shorty="TG",
        color="sky",
        sort_key=999,
        permission_depth=1,
        is_leader_necessary=False,
        available_for_new_person=False,
        posts_enabled=False,
    )
    cleanup(lambda: client.group.group_types.delete(group_type.id))
    client.group.group_types.update(
        group_type.id,
        name=group_type.name + " 2",
        name_plural="Testgruppen",
        shorty="TG",
        color="lime",
        sort_key=998,
        permission_depth=1,
        is_leader_necessary=False,
        available_for_new_person=False,
        posts_enabled=False,
    )
    role = client.group.roles.create(
        group_type_id=group_type.id,
        name=name("Rolle"),
        shorty="TR",
        type_="participant",
        sort_key=99,
        is_default=False,
        is_hidden=False,
        grow_path_id=None,
    )
    cleanup(lambda: client.group.roles.delete(role.id))
    client.group.roles.update(
        role.id,
        group_type_id=group_type.id,
        name=role.name + " neu",
        shorty="TR",
        type_="participant",
        sort_key=98,
        is_default=False,
        is_hidden=False,
        grow_path_id=None,
    )
    assert client.group.roles.get(role.id).name == role.name + " neu"
    client.group.roles.delete(role.id)
    client.group.group_types.delete(group_type.id)


def test_oauth_client(client: LiveClient, cleanup: Cleanup) -> None:
    created = client.oauth_clients.create(name=name("OAuth"), redirect_uri="https://example.org/callback")
    identifier = created.identifier
    cleanup(lambda: client.oauth_clients.delete(identifier))
    client.oauth_clients.update(identifier, name=created.name + " neu", redirect_uri="https://example.org/cb2")
    client.oauth_clients.delete(identifier)


def test_facts(client: LiveClient, cleanup: Cleanup) -> None:
    fact = client.facts.create(body=m.FactNumberCreate(name=name("Fakt"), type_="number", unit="Pers."))
    cleanup(lambda: client.facts.delete(fact.id))
    client.facts.update(fact.id, body=m.FactNumberCreate(name=fact.name + " neu", type_="number", unit="Pers."))
    client.facts.get(fact.id)
    client.facts.delete(fact.id)


def test_html_template(client: LiveClient, cleanup: Cleanup) -> None:
    template = client.html_templates.create(domain_type="bulkletter", name=name("Vorlage"))
    cleanup(lambda: client.html_templates.delete(template.id, dry_run=False))
    client.html_templates.patch(template.id, name=template.name + " neu")
    client.html_templates.get_html(template.id)
    # A dry run answers 409 Conflict with what would be deleted.
    with pytest.raises(ct.Conflict):
        client.html_templates.delete(template.id, dry_run=True)
    client.html_templates.delete(template.id, dry_run=False)


# --- calendar templates ------------------------------------------------------------


def test_appointment_template(client: LiveClient, cleanup: Cleanup) -> None:
    calendar_id = client.calendars.list()[0].id
    template = client.calendars.appointments.templates.create(
        calendar_id=calendar_id, title=name("Vorlage"), start_time="10:00", duration=3600
    )
    cleanup(lambda: client.calendars.appointments.templates.delete(template.id))
    client.calendars.appointments.templates.update(
        template.id, calendar_id=calendar_id, title="Gottesdienst (Test)", start_time="10:30", duration=5400
    )
    client.calendars.appointments.templates.get(template.id)
    client.calendars.appointments.templates.delete(template.id)


def test_agenda_template(client: LiveClient, cleanup: Cleanup) -> None:
    calendar_id = client.calendars.list()[0].id
    agenda = client.agenda_templates.create(calendar_id=calendar_id, name=name("Ablauf"))
    cleanup(lambda: client.agenda_templates.delete(agenda.id))
    client.agenda_templates.update(agenda.id, calendar_id=calendar_id, name=f"{agenda.name} neu")

    item = client.agenda_templates.items.create(agenda.id, body=m.AgendaItemInputHeader(type_="header", title="Begrüßung"))
    cleanup(lambda: client.agenda_templates.items.delete(agenda.id, item.id))
    client.agenda_templates.items.update(
        agenda.id, item.id, body=m.AgendaItemInputHeader(type_="header", title="Begrüßung und Ankündigungen")
    )
    client.agenda_templates.items.delete(agenda.id, item.id)
    client.agenda_templates.delete(agenda.id)


# --- groups -----------------------------------------------------------------------


def test_group_extras(client: LiveClient, me: int, masterdata: _t.Any, cleanup: Cleanup) -> None:
    group = client.groups.create(
        name=name("Gruppe"), group_type_id=masterdata.group_types[0].id, group_status_id=masterdata.group_statuses[0].id
    )
    cleanup(lambda: client.groups.delete(group.id))
    parent = client.groups.create(
        name=name("Bereich"), group_type_id=masterdata.group_types[0].id, group_status_id=masterdata.group_statuses[0].id
    )
    cleanup(lambda: client.groups.delete(parent.id))

    client.groups.parents.update(group.id, parent.id)
    assert any(p.domain_identifier == str(parent.id) for p in client.groups.parents.list(str(group.id)))
    client.groups.parents.delete(group.id, parent.id)

    address = client.addresses.create("group", str(group.id), name="Gemeindehaus", street="Kirchweg 1", zip="20354", city="Hamburg")
    cleanup(lambda: client.addresses.delete("group", str(group.id), address.id))
    client.addresses.update("group", str(group.id), address.id, name="Gemeindehaus", city="Hamburg-Mitte")
    client.addresses.delete("group", str(group.id), address.id)

    field = client.groups.member_fields.group.create(
        group.id,
        name="T-Shirt-Größe",
        field_type_code="text",
        security_level=1,
        use_in_registration_form=False,
        required_in_registration_form=False,
    )
    cleanup(lambda: client.groups.member_fields.group.delete(group.id, field.id))
    client.groups.member_fields.group.update(
        group.id,
        field.id,
        name="Größe",
        reference_name=field.reference_name or "groesse",
        security_level=1,
        use_in_registration_form=False,
        required_in_registration_form=False,
    )
    client.groups.member_fields.group.patch(group.id, field.id, name="Shirt")
    client.groups.member_fields.group.delete(group.id, field.id)

    client.groups.update_group_homepage(
        group.id, is_enabled=True, show_filters=False, show_group_images=False, show_leaders=True, show_map=False
    )
    client.groups.delete_group_homepage(group.id)

    tag = client.tags.attach_new("group", group.id, name=name("Tag"))
    cleanup(lambda: client.tags.delete(tag.id))

    copy = client.groups.duplicate(group.id, new_name=group.name + " Kopie")
    cleanup(lambda: client.groups.delete(copy.id))
    client.groups.delete(copy.id)

    assert client.groups.export(ids=[group.id])
    client.groups.members.create_export(group.id)


def test_follow_up(client: LiveClient, me: int, masterdata: _t.Any, cleanup: Cleanup) -> None:
    person = client.persons.create(**required_person_fields(masterdata), first_name="ctrs-test", last_name="Nachsorge", force=True)
    cleanup(lambda: client.persons.delete(person.id))

    follow_up = client.persons.followups.create(person.id, title="Nachfragen, wie es geht", owner_id=me)
    cleanup(lambda: client.followups.delete(follow_up.id))
    client.followups.update(follow_up.id, body=m.FollowUpUpdate(title="Nachfragen", description="Anruf nach dem Gottesdienst"))
    client.followups.notes(follow_up.id, comment="Nicht erreicht")
    client.followups.postpone(follow_up.id, due_date=dt.date.today() + dt.timedelta(days=7))
    client.followups.complete(follow_up.id)
    client.followups.reset(follow_up.id)
    client.followups.dismiss(follow_up.id)
    client.followups.delete(follow_up.id)

    # Group follow-ups: the administrator may create them, but changing one needs the
    # "+do followup" permission in that group (403 otherwise).
    group = client.groups.create(
        name=name("Gruppe"), group_type_id=masterdata.group_types[0].id, group_status_id=masterdata.group_statuses[0].id
    )
    cleanup(lambda: client.groups.delete(group.id))
    client.groups.members.update(group.id, person.id)
    in_group = client.groups.members.followups.create(group.id, person.id, title=name("Wiedervorlage"))
    cleanup(lambda: client.followups.delete(in_group.id))
    client.followups.delete(in_group.id)
    client.groups.delete(group.id)
    client.persons.delete(person.id)


def test_meeting_attendance(client: LiveClient, me: int, masterdata: _t.Any, cleanup: Cleanup) -> None:
    group = client.groups.create(
        name=name("Gruppe"), group_type_id=masterdata.group_types[0].id, group_status_id=masterdata.group_statuses[0].id
    )
    cleanup(lambda: client.groups.delete(group.id))
    client.groups.members.update(group.id, me)
    meeting = client.groups.meetings.create(group.id, start_date=NOW - dt.timedelta(days=1))
    cleanup(lambda: client.groups.meetings.delete(group.id, meeting.id))
    client.groups.meetings.members.missing(group.id, meeting.id, status="absent")
    client.groups.meetings.members.reset(group.id, meeting.id)
    client.groups.meetings.members.delete(group.id, meeting.id, me)
    client.groups.meetings.delete(group.id, meeting.id)


# --- persons ----------------------------------------------------------------------


def test_person_agreements(client: LiveClient, masterdata: _t.Any, cleanup: Cleanup) -> None:
    person = client.persons.create(
        **required_person_fields(masterdata),
        first_name="ctrs-test",
        last_name="Vereinbarung",
        birthday=dt.date(1990, 5, 17),  # the privacy policy needs it to tell adults from children
        force=True,
    )
    cleanup(lambda: client.persons.delete(person.id))
    # Only the person can accept; an administrator can revoke.
    with pytest.raises(ct.Forbidden):
        client.persons.update_confidentiality_agreement(person.id)
    client.persons.delete_confidentiality_agreement(person.id)
    client.persons.update_privacy_policy(person.id, own_accepted=True, children_accepted=False, persons=[], type_id=1, who_id=1)
    client.persons.get_privacy_policy(person.id)
    client.persons.delete_privacy_policy(person.id)
    client.persons.delete(person.id)


def test_lookups(client: LiveClient, me: int) -> None:
    """POST operations that only compute or look something up."""
    assert str(me) in client.persons.properties(ids=[me])
    resolved = client.domain_objects.resolve(domain_types=["person"], domain_identifiers=[str(me)])
    # title, domainType and domainIdentifier are sent but missing in the spec model.
    assert (resolved[0].model_extra or {}).get("domainIdentifier") == str(me)
    client.labels.totals(person_ids=[me])
    client.emails.preview(content=["Hallo [Vorname]"], person_id=me)
    client.markdown.check(input_scope="description", markdown="**fett** und _kursiv_")
    start = dt.date.today()
    occurrences = client.repeat_calculation.calculate(start_date=start, end_date=start, repeat_id=7, repeat_frequency=1, repeat_until=start + dt.timedelta(days=21))
    assert len(occurrences) >= 3


# --- posts, songs, bookings, appointments -------------------------------------------


def test_post_reactions(client: LiveClient, me: int, cleanup: Cleanup) -> None:
    group = next(g for g in client.persons.list_groups(me) if g.group is not None)
    assert group.group is not None
    post = client.posts.create(
        group_id=int(group.group.domain_identifier), title=name("Beitrag"), content="Inhalt", visibility="group_intern"
    )
    cleanup(lambda: client.posts.delete(post.id, dry_run=False))
    comment = client.posts.comments.create(post.id, post_id_2=post.id, content="Kommentar")
    client.posts.comments.reactions.update(post.id, comment.id, emoji="👍")
    client.posts.comments.reactions.delete(post.id, comment.id, emoji="👍")
    client.posts.reactions.persons.update(post.id, "🙏", str(me))
    client.posts.reactions.persons.delete(post.id, "🙏", str(me))
    client.posts.update_expire(post.id)
    client.posts.hidden.update(post.id, "post")
    client.post.hidden.delete("post", post.id)
    client.posts.delete(post.id, dry_run=False)


def test_song_default_arrangement(client: LiveClient, cleanup: Cleanup) -> None:
    category = client.song.categories.list()[0].id
    song = client.songs.create(name=name("Lied"), category_id=category)
    cleanup(lambda: client.songs.delete(song.id))
    first = client.songs.arrangements.create(song.id, name="Gitarre")  # the first one becomes the default
    second = client.songs.arrangements.create(song.id, name="Klavier")
    client.songs.arrangements.patch_default(song.id, second.id)
    defaults = {a.id: a.is_default for a in client.songs.arrangements.list(song.id)}
    assert defaults == {first.id: False, second.id: True}
    client.songs.delete(song.id)


@pytest.mark.xfail(strict=True, reason="ChurchTools 3.138 bug: a second call clears the default instead of keeping it")
def test_song_default_arrangement_is_idempotent(client: LiveClient, cleanup: Cleanup) -> None:
    category = client.song.categories.list()[0].id
    song = client.songs.create(name=name("Lied"), category_id=category)
    cleanup(lambda: client.songs.delete(song.id))
    arrangement = client.songs.arrangements.create(song.id, name="Gitarre")
    client.songs.arrangements.patch_default(song.id, arrangement.id)  # documented: "already the default also returns 204"
    assert client.songs.arrangements.get(song.id, arrangement.id).is_default


def test_booking_conflicts(client: LiveClient, cleanup: Cleanup) -> None:
    resource_type = client.resource_types.list()[0].id
    resource = client.resources.create(name=name("Raum"), resource_type_id=resource_type, sort_key=999)
    cleanup(lambda: client.resources.delete(resource.id))
    start = NOW + dt.timedelta(days=5)
    booking = client.bookings.create(
        resource_id=resource.id, title=name("Buchung"), start_date=start, end_date=start + dt.timedelta(hours=1), show_in_cal=False, status_id=2
    )
    booking_id = booking.base.id if hasattr(booking, "base") else booking.id
    cleanup(lambda: client.bookings.delete(booking_id))

    conflicts = client.bookings.preview_conflicts(resource_id=resource.id, start_date=start, end_date=start + dt.timedelta(minutes=30))
    assert conflicts, "the new booking should conflict with an overlapping one"
    client.bookings.preview_conflicts_for(booking_id, start_date=start, end_date=start + dt.timedelta(hours=2))
    client.bookings.update(
        booking_id,
        body=m.BookingStandaloneUpdate(
            resource_id=resource.id,
            title="verlängert", start_date=start, end_date=start + dt.timedelta(hours=2), show_in_cal=False, status_id=2
        ),
    )
    client.bookings.delete(booking_id)
    client.resources.delete(resource.id)


def test_appointment_change_impact(client: LiveClient, cleanup: Cleanup) -> None:
    calendar = client.calendars.create(name=name("Kalender"), sort_key=999, type_="church")
    cleanup(lambda: client.calendars.delete(calendar.id))
    start = NOW + dt.timedelta(days=6)
    created = client.calendars.appointments.create(
        calendar.id, title=name("Termin"), start_date=start, end_date=start + dt.timedelta(hours=1), is_internal=False
    )
    appointment = created.appointment if hasattr(created, "appointment") else created
    appointment_id = appointment.base.id if hasattr(appointment, "base") else appointment.id
    client.calendars.appointments.change_impact(
        calendar.id, appointment_id, start_date=start + dt.timedelta(days=1), end_date=start + dt.timedelta(days=1, hours=1)
    )
    client.calendars.delete(calendar.id)


def test_event_agenda(client: LiveClient, cleanup: Cleanup) -> None:
    """Changes the agenda of an existing event and removes the changes again."""
    event_id = next((e.id for e in itertools.islice(client.events.list(), 20) if _has_agenda(client, e.id)), None)
    if event_id is None:
        pytest.skip("no upcoming event with an agenda")
    client.events.agenda.lock(event_id)
    cleanup(lambda: client.events.agenda.unlock(event_id))
    client.events.agenda.unlock(event_id)

    item = client.events.agenda.items.create(event_id, body=m.AgendaItemInputHeader(type_="header", title="ctrs-test"))
    cleanup(lambda: client.events.agenda.items.delete(event_id, item.id))
    client.events.agenda.items.update(event_id, item.id, body=m.AgendaItemInputHeader(type_="header", title="ctrs-test 2"))
    client.events.agenda.items.hide(event_id, item.id)
    client.events.agenda.items.unhide(event_id, item.id)
    client.events.agenda.items.delete(event_id, item.id)


def _has_agenda(client: LiveClient, event_id: int) -> bool:
    try:
        client.events.agenda.get(event_id)
    except ct.NotFound:
        return False
    return True
