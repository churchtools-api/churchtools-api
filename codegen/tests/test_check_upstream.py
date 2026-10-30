"""Unit tests of the upstream check (static comparison of two API descriptions)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_upstream as cu  # noqa: E402

OLD = {
    "paths": {
        "/persons": {
            "get": {"parameters": [{"in": "query", "name": "limit"}]},
            "post": {
                "requestBody": {"content": {"application/json": {"schema": {"required": ["firstName"]}}}},
            },
        },
        "/groups/{id}": {"get": {"parameters": [{"in": "path", "name": "id", "required": True}]}},
    },
    "components": {"schemas": {"Person": {"type": "object"}, "Old": {"type": "object"}}},
}


def test_identical_specs_have_no_differences() -> None:
    d = cu.diff(OLD, copy.deepcopy(OLD))
    assert d == cu.Diff([], [], [], [], [], [], [])


def test_added_removed_and_breaking_changes() -> None:
    new = copy.deepcopy(OLD)
    del new["paths"]["/groups/{id}"]
    new["paths"]["/events"] = {"get": {}}
    new["paths"]["/persons"]["get"]["parameters"].append({"in": "query", "name": "campus", "required": True})
    new["paths"]["/persons"]["post"]["requestBody"]["content"]["application/json"]["schema"]["required"].append(
        "lastName"
    )
    new["components"]["schemas"]["Person"]["description"] = "changed"
    del new["components"]["schemas"]["Old"]
    new["components"]["schemas"]["Event"] = {"type": "object"}

    d = cu.diff(OLD, new)
    assert d.added == ["GET /events"]
    assert d.removed == ["GET /groups/{id}"]
    assert d.changed == ["GET /persons", "POST /persons"]
    assert d.breaking == [
        "`GET /groups/{id}` entfällt",
        "`GET /persons`: neuer Pflichtparameter `query:campus`",
        "`POST /persons`: neues Pflichtfeld `lastName` im Body",
    ]
    assert (d.schemas_added, d.schemas_removed, d.schemas_changed) == (["Event"], ["Old"], ["Person"])
    text = cu.summary(("3.138.1", "1"), ("3.139.0", "2"), d)
    assert "**3.139.0** (Build 2)" in text and "Möglicherweise inkompatibel" in text


def test_long_lists_are_cut() -> None:
    lines = cu.bullet_list([str(i) for i in range(cu.LIST_LIMIT + 5)])
    assert len(lines) == cu.LIST_LIMIT + 1
    assert lines[-1] == "- … und 5 weitere"
