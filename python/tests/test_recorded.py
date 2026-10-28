"""Replays responses recorded from a real instance (`fixtures/recorded`) offline.

Every recording must decode into the return type of its generated method. The
live tests in `tests/live` refresh the recordings.
"""

from __future__ import annotations

import json
import operator
import typing as _t
from pathlib import Path

import pytest

import churchtools_rs as ct
from churchtools_rs._base import _parse

ROOT = Path(__file__).resolve().parents[2]
CATALOG = {e["op_id"]: e for e in json.loads((ROOT / "python" / "tests" / "live" / "operations.json").read_text())}
FIXTURES = sorted((ROOT / "fixtures" / "recorded").glob("*.json"))


def return_type(entry: dict[str, _t.Any]) -> _t.Any:
    method = operator.attrgetter(entry["call"])(ct.Client("https://example.church.tools"))
    tp = _t.get_type_hints(method)["return"]
    if _t.get_origin(tp) is ct.Paginator:
        return _t.cast(_t.Any, list)[_t.get_args(tp)[0]]
    return tp


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_recorded_response_decodes(path: Path) -> None:
    fixture = json.loads(path.read_text())
    entry = CATALOG[fixture["operation"]]
    if entry["result"] not in ("data", "json"):
        pytest.skip("the spec documents no response body (see docs/testbericht.md)")
    _parse(json.dumps(fixture["body"]).encode(), return_type(entry), envelope=entry["result"] == "data")
