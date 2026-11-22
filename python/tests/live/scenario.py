"""Helpers for the write scenarios (`test_write*.py`)."""

from __future__ import annotations

import datetime as dt
import typing as _t
import uuid

import churchtools_api as ct
from conftest import Recorder

PREFIX = "ctrs-test"
NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0, second=0, minute=0)


def name(kind: str) -> str:
    return f"{PREFIX} {kind} {uuid.uuid4().hex[:6]}"


class Cleanup:
    """Runs registered undo steps in reverse order.

    Steps whose object is already gone are fine: the API answers 404, or 403
    when the parent is gone too (e.g. a wiki page of a deleted category).
    """

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder
        self.steps: list[_t.Callable[[], object]] = []

    def __call__(self, step: _t.Callable[[], object]) -> None:
        self.steps.append(step)

    def run(self) -> None:
        self.recorder.context = ""  # undo steps do not count as tested calls
        errors: list[Exception] = []
        for step in reversed(self.steps):
            try:
                step()
            except (ct.NotFound, ct.Forbidden):
                pass
            except Exception as e:  # keep undoing the rest, report afterwards
                errors.append(e)
        if errors:
            raise errors[0]


class InstanceIds(_t.NamedTuple):
    """IDs that differ between instances, looked up once instead of being hard-coded.

    Security levels, for example, get new IDs after `security_levels.renumber()`.
    """

    security_level: int  # the lowest level
    privacy_type: int  # option of the field "Einwilligung wodurch"
    privacy_who: int  # option of the field "Einwilligung durch wen", preferably "own"


def lookup_privacy_options(client: ct.Client) -> tuple[int, int]:
    """Options for "Einwilligung wodurch" and "durch wen" (preferably "own") of the privacy-policy fields."""
    fields = {f.key: f.id for f in client.db_fields.list()}

    def options(key: str) -> list[_t.Any]:
        return sorted(client.db_fields.options.list(fields[key]), key=lambda o: o.id)

    who = options("privacyPolicyAgreementWhoId")
    own = [o for o in who if str(o.name).endswith(".who.own")]
    return options("privacyPolicyAgreementTypeId")[0].id, (own or who)[0].id


def lookup_ids(client: ct.Client, privacy: tuple[int, int]) -> InstanceIds:
    return InstanceIds(min(level.id for level in client.security_levels.list()), *privacy)


def required_person_fields(masterdata: _t.Any, ids: InstanceIds) -> dict[str, _t.Any]:
    """Fields the server requires for a new person although the spec marks them optional."""
    return {
        "department_ids": [masterdata.departments[0].id],
        "status_id": masterdata.statuses[0].id,
        "campus_id": masterdata.campuses[0].id,
        "privacy_policy_agreement_type_id": ids.privacy_type,
        "privacy_policy_agreement_who_id": ids.privacy_who,
        "privacy_policy_agreement_date": dt.date.today(),
    }
