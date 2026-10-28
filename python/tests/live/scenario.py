"""Helpers for the write scenarios (`test_write*.py`)."""

from __future__ import annotations

import datetime as dt
import typing as _t
import uuid

import churchtools_rs as ct

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


def required_person_fields(masterdata: _t.Any) -> dict[str, _t.Any]:
    """Fields the server requires for a new person although the spec marks them optional."""
    return {
        "department_ids": [masterdata.departments[0].id],
        "status_id": masterdata.statuses[0].id,
        "campus_id": masterdata.campuses[0].id,
        "privacy_policy_agreement_type_id": 1,
        "privacy_policy_agreement_who_id": 1,
        "privacy_policy_agreement_date": dt.date.today(),
    }
