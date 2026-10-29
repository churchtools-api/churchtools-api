"""Calls every GET operation once through the generated Python API.

Each call checks that the request is accepted and that the response matches the
Pydantic models. Fields the API sends but the spec does not document are noted
in `fixtures/live-results.json`.
"""

from __future__ import annotations

import json
import operator
import typing as _t

import churchtools_rs as ct
import pytest
from conftest import CATALOG, ROOT, LiveClient, Results, record
from expectations import EXPECTED_ERRORS, SKIP
from resolve import Resolver, Unresolved

GETS = [e for e in CATALOG if e["method"] == "GET"]
SEED_RESULTS = ROOT / "fixtures" / "live-seed.json"


@pytest.fixture(scope="session")
def seed(client: LiveClient) -> _t.Iterator[_t.Any]:
    """Creates data for endpoints a fresh demo has nothing for, and removes it afterwards."""
    import seed as seeding

    data = seeding.create(client)
    yield data
    undo_errors = data.remove()
    SEED_RESULTS.write_text(
        json.dumps({"failed": data.failed, "undo_failed": undo_errors}, indent=1, ensure_ascii=False) + "\n"
    )


@pytest.fixture(scope="session")
def resolver(client: LiveClient, seed: _t.Any) -> Resolver:
    return Resolver(client, seed)


def undocumented(value: _t.Any, out: dict[str, set[str]]) -> None:
    if isinstance(value, ct.CTModel):
        if value.model_extra:
            out.setdefault(type(value).__name__, set()).update(value.model_extra)
        for name in type(value).model_fields:
            undocumented(getattr(value, name), out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            undocumented(v, out)
    elif isinstance(value, dict):
        for v in value.values():
            undocumented(v, out)


@pytest.mark.parametrize("entry", GETS, ids=[e["op_id"] for e in GETS])
def test_get(entry: dict[str, _t.Any], client: LiveClient, resolver: Resolver, results: Results) -> None:
    op = entry["op_id"]
    if op in SKIP:
        results.add(op, "skipped", reason=SKIP[op])
        pytest.skip(SKIP[op])
    try:
        args, kwargs = resolver.arguments(entry)
    except Unresolved as e:
        results.add(op, "unresolved", reason=str(e))
        pytest.skip(f"unresolved: {e}")
    method = operator.attrgetter(entry["call"])(client)
    call = f"{entry['call']}({', '.join([*map(repr, args), *(f'{k}={v!r}' for k, v in kwargs.items())])})"
    try:
        value = method(*args, **kwargs)
        if entry["paginated"]:
            value = next(value.pages(), [])
    except ct.DecodeError as e:
        record(op, client.recorder)
        results.add(op, "decode-error", call=call, error=str(e)[:2000])
        raise
    except ct.ApiError as e:
        failure = {"call": call, "status": e.status, "message": str(e), "request": client.recorder.last_request}
        expected = EXPECTED_ERRORS.get(op)
        if expected and expected[0] == e.status:
            results.add(op, "expected-error", reason=expected[1], **failure)
            pytest.xfail(f"HTTP {e.status}: {expected[1]}")
        results.add(op, f"http-{e.status}", **failure)
        raise
    record(op, client.recorder)
    extra: dict[str, set[str]] = {}
    undocumented(value, extra)
    info: dict[str, _t.Any] = {"call": call, "undocumented": {k: sorted(v) for k, v in sorted(extra.items())}}
    body = client.recorder.last_body
    if entry["result"] == "none" and body and body.strip() not in (b"", b"{}", b"[]", b"null"):
        # The method returns None, but the server sends data the spec does not describe.
        info["undocumented_response"] = body[:300].decode(errors="replace")
    results.add(op, "ok", **info)
