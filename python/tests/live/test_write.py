"""Create, read, change and delete data through the generated Python API.

Every scenario cleans up after itself, also when an assertion fails. Names
start with `ctrs-test` so leftovers are easy to spot on the instance.
"""

from __future__ import annotations

import datetime as dt
import typing as _t
import uuid

import churchtools_rs as ct
import pytest
from conftest import LiveClient
from scenario import NOW, PREFIX, Cleanup, name, required_person_fields

pytestmark = pytest.mark.usefixtures("scenario")


# --- people and groups --------------------------------------------------------


def test_person_lifecycle(client: LiveClient, masterdata: _t.Any, cleanup: Cleanup) -> None:
    person = client.persons.create(
        **required_person_fields(masterdata),
        first_name=PREFIX,
        last_name=uuid.uuid4().hex[:8],
        email=f"{uuid.uuid4().hex[:8]}@example.invalid",
        force=True,
    )
    cleanup(lambda: client.persons.delete(person.id))
    assert client.persons.get(person.id).first_name == PREFIX

    patched = client.persons.patch(person.id, nickname="Testi", city="Teststadt")
    assert (patched.nickname, patched.city) == ("Testi", "Teststadt")

    client.persons.archive(person.id, archived=True)
    client.persons.archive(person.id, archived=False)
    client.persons.delete(person.id)
    with pytest.raises(ct.NotFound):
        client.persons.get(person.id)


def test_person_details(client: LiveClient, me: int, masterdata: _t.Any, cleanup: Cleanup) -> None:
    other = client.persons.create(**required_person_fields(masterdata), first_name=PREFIX, last_name="Partner", force=True)
    cleanup(lambda: client.persons.delete(other.id))

    note = client.notes.create("person", other.id, text="erste Notiz")
    cleanup(lambda: client.notes.delete(note.id))
    assert client.notes.update("person", other.id, note.id, text="geändert").text == "geändert"
    client.notes.delete_for_object("person", str(other.id), note.id)
    second = client.notes.create("person", other.id, text="zweite Notiz")
    cleanup(lambda: client.notes.delete(second.id))
    client.notes.delete(second.id)

    rel_type = masterdata.relationship_types[0].id
    rel = client.persons.relationships.create(me, other_person_id=other.id, relationship_type_id=rel_type)
    assert rel.id is not None
    rel_id = rel.id
    cleanup(lambda: client.persons.relationships.delete(me, rel_id))
    assert any(r.id == rel_id for r in client.persons.relationships.list(me))
    client.persons.relationships.delete(me, rel_id)

    reason = client.event.get_master_data().absence_reasons[0].id
    absence = client.persons.absences.create(
        other.id, absence_reason_id=reason, start_date=dt.date.today(), end_date=dt.date.today(), comment="Urlaub"
    )
    cleanup(lambda: client.persons.absences.delete(other.id, absence.id))
    client.persons.absences.update(
        other.id, absence.id, absence_reason_id=reason, start_date=dt.date.today(), end_date=dt.date.today(), comment="x"
    )
    client.persons.absences.delete(other.id, absence.id)

    # Only allowlisted settings can be written (see PersonSettingUpdate); restore afterwards.
    try:
        original: _t.Any = client.persons.settings.get(me, "churchdb", "signature").value
    except ct.NotFound:
        original = None
    if original is None:
        cleanup(lambda: client.persons.settings.delete(me, "churchdb", "signature"))
    else:
        cleanup(lambda: client.persons.settings.update(me, "churchdb", "signature", value=original))
    client.persons.settings.update(me, "churchdb", "signature", value="Viele Grüße (ctrs-test)")
    assert client.persons.settings.get(me, "churchdb", "signature").value == "Viele Grüße (ctrs-test)"


def test_group_lifecycle(client: LiveClient, me: int, masterdata: _t.Any, cleanup: Cleanup) -> None:
    group = client.groups.create(
        name=name("Gruppe"), group_type_id=masterdata.group_types[0].id, group_status_id=masterdata.group_statuses[0].id
    )
    cleanup(lambda: client.groups.delete(group.id))
    assert client.groups.get(group.id).name == group.name

    client.groups.patch(group.id, extra_body={"information": {"note": "Testgruppe"}})

    member = client.groups.members.update(group.id, me, comment="hinzugefügt")
    assert member.person_id == me
    assert me in client.groups.list_member_ids(group.id)
    client.groups.members.patch(group.id, me, comment="geändert")
    client.groups.members.delete(group.id, me)

    meeting = client.groups.meetings.create(group.id, start_date=NOW + dt.timedelta(days=1))
    cleanup(lambda: client.groups.meetings.delete(group.id, meeting.id))
    client.groups.meetings.update(
        group.id, meeting.id, start_date=NOW + dt.timedelta(days=2), is_canceled=False, is_completed=False
    )
    client.groups.meetings.delete(group.id, meeting.id)

    client.groups.delete(group.id)


def test_tags(client: LiveClient, me: int, cleanup: Cleanup) -> None:
    tag = client.tags.create("person", name=name("Tag"))
    cleanup(lambda: client.tags.delete(tag.id))
    assert client.tags.get(tag.id).name == tag.name
    assert client.tags.update(tag.id, name=tag.name + " neu").name == tag.name + " neu"

    client.tags.attach("person", me, tag.id)
    cleanup(lambda: client.tags.detach("person", me, tag.id))
    assert any(t.id == tag.id for t in client.tags.list_for_object("person", me))
    client.tags.detach("person", me, tag.id)
    client.tags.delete(tag.id)


# --- calendar, events, resources ------------------------------------------------


def test_appointment_lifecycle(client: LiveClient, cleanup: Cleanup) -> None:
    calendar = client.calendars.create(name=name("Kalender"), sort_key=999, type_="church", color="#336699")
    cleanup(lambda: client.calendars.delete(calendar.id))
    client.calendars.update(calendar.id, name=calendar.name + " neu", sort_key=998)

    start = NOW + dt.timedelta(days=3)
    appointment = client.calendars.appointments.create(
        calendar.id, title=name("Termin"), start_date=start, end_date=start + dt.timedelta(hours=1), is_internal=False
    )
    created = appointment.appointment if hasattr(appointment, "appointment") else appointment
    appointment_id = created.base.id if hasattr(created, "base") else created.id
    cleanup(lambda: client.calendars.appointments.delete(calendar.id, appointment_id))
    client.calendars.appointments.get(calendar.id, appointment_id)
    client.calendars.appointments.update(
        calendar.id,
        appointment_id,
        title="verschoben",
        start_date=start + dt.timedelta(hours=2),
        end_date=start + dt.timedelta(hours=3),
        is_internal=False,
    )
    client.calendars.appointments.delete(calendar.id, appointment_id)
    client.calendars.delete(calendar.id)


def test_resource_booking(client: LiveClient, cleanup: Cleanup) -> None:
    resource_type = client.resource_types.list()[0].id
    resource = client.resources.create(name=name("Raum"), resource_type_id=resource_type, sort_key=999)
    cleanup(lambda: client.resources.delete(resource.id))
    client.resources.update(resource.id, name=resource.name + " neu", resource_type_id=resource_type, sort_key=998)

    start = NOW + dt.timedelta(days=4)
    booking = client.bookings.create(
        resource_id=resource.id,
        title=name("Buchung"),
        start_date=start,
        end_date=start + dt.timedelta(hours=1),
        show_in_cal=False,
        status_id=2,
    )
    booking_id = booking.base.id if hasattr(booking, "base") else booking.id
    cleanup(lambda: client.bookings.delete(booking_id))
    client.bookings.get(booking_id)
    client.bookings.delete(booking_id)
    client.resources.delete(resource.id)


def test_services(client: LiveClient, cleanup: Cleanup) -> None:
    group = client.service_groups.create(name=name("Dienstgruppe"))
    cleanup(lambda: client.service_groups.delete(group.id))
    client.service_groups.update(group.id, name=group.name + " neu")
    service = client.services.create(name=name("Dienst"), service_group_id=group.id)
    cleanup(lambda: client.services.delete(service.id))
    assert client.services.get(service.id).service_group_id == group.id
    client.services.update(service.id, name=service.name + " neu", service_group_id=group.id)
    client.services.delete(service.id)
    client.service_groups.delete(group.id)


# --- songs, wiki, posts ---------------------------------------------------------


def test_song_with_arrangement(client: LiveClient, cleanup: Cleanup) -> None:
    category = client.song.categories.list()[0].id
    song = client.songs.create(name=name("Lied"), category_id=category, author="Test")
    cleanup(lambda: client.songs.delete(song.id))
    client.songs.update(song.id, name=song.name + " neu", category_id=category)

    arrangement = client.songs.arrangements.create(song.id, name="Gitarre", key="G")
    cleanup(lambda: client.songs.arrangements.delete(song.id, arrangement.id))
    client.songs.arrangements.update(song.id, arrangement.id, name="Gitarre (Capo 2)", key="A")
    assert client.songs.arrangements.get(song.id, arrangement.id).key == "A"
    client.songs.arrangements.delete(song.id, arrangement.id)
    client.songs.delete(song.id)


def test_wiki(client: LiveClient, cleanup: Cleanup) -> None:
    category = client.wiki.categories.create(
        name=name("Wiki"), sort_key=999, in_menu=False, file_access_without_permission=False
    )
    cleanup(lambda: client.wiki.categories.delete(category.id))
    client.wiki.categories.update(
        category.id, name=category.name + " neu", sort_key=998, in_menu=False, file_access_without_permission=False
    )
    page = client.wiki.categories.pages.create(category.id, title="Startseite", text="Hallo", is_markdown=True)
    identifier = page.guid
    cleanup(lambda: client.wiki.categories.pages.delete(category.id, identifier))
    client.wiki.categories.pages.patch(category.id, identifier, text="Hallo Welt")
    assert client.wiki.categories.pages.get(category.id, identifier).text == "Hallo Welt"
    client.wiki.categories.pages.delete(category.id, identifier)
    client.wiki.categories.delete(category.id)


def test_post_with_comment(client: LiveClient, me: int, cleanup: Cleanup) -> None:
    group = next(g for g in client.persons.list_groups(me) if g.group is not None)
    post = client.posts.create(group_id=int(group.group.domain_identifier), title=name("Beitrag"), content="Inhalt", visibility="group_intern")
    cleanup(lambda: client.posts.delete(post.id, dry_run=False))
    client.posts.patch(post.id, title=post.title + " neu")
    comment = client.posts.comments.create(post.id, post_id_2=post.id, content="Kommentar")
    client.posts.comments.delete(post.id, comment.id)
    client.posts.delete(post.id, dry_run=False)


# --- master data -----------------------------------------------------------------

MASTERDATA: dict[str, tuple[dict[str, _t.Any], dict[str, _t.Any], dict[str, _t.Any]]] = {
    "campuses": ({"shorty": "T"}, {"shorty": "T2"}, {}),
    "contactlabels": ({"is_default": False, "sort_key": 999}, {"is_default": False, "sort_key": 998}, {}),
    "statuses": ({"security_level_id": 1, "shorty": "T"}, {"security_level_id": 1, "shorty": "T2"}, {}),
    "person.sexes": ({}, {}, {}),
    "person.grow_paths": ({"color": "red"}, {"color": "blue"}, {}),
    "person.comment_viewers": ({}, {}, {}),
    "person.relationship_types": (
        {"degree_name_a": "Pate", "degree_name_b": "Patenkind", "security_level_id": 1},
        {"degree_name_a": "Patin", "degree_name_b": "Patenkind", "security_level_id": 1},
        {},
    ),
    "group.target_groups": ({"sort_key": 999}, {"sort_key": 998}, {"dry_run": False}),
    "group.age_groups": ({"sort_key": 999, "start": 10, "end": 12}, {"sort_key": 998, "start": 10, "end": 13}, {"dry_run": False}),
    "group.group_categories": ({"sort_key": 999, "color": "red"}, {"sort_key": 998, "color": "blue"}, {"dry_run": False}),
}


@pytest.mark.parametrize("call", list(MASTERDATA))
def test_masterdata_lifecycle(client: LiveClient, call: str, cleanup: Cleanup) -> None:
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
    with pytest.raises(ct.NotFound):
        resource.get(created.id)
