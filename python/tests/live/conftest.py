"""Live tests against a ChurchTools test instance.

Run only when credentials are set; they are meant for throwaway demo instances
(https://church.tools/en/test-churchtools/), because the write tests create and delete data:

    CT_URL=https://xyz.church.tools CT_USER=... CT_PASSWORD=... pytest tests/live

`CT_MIN_INTERVAL` (seconds, default 0.25) spaces the requests so the instance
is not flooded. Successful responses are recorded to `fixtures/recorded/` and
replayed offline by `tests/test_recorded.py` and `core/tests/recorded.rs`.
A summary of all outcomes goes to `fixtures/live-results.json`.

Every demo instance has other data (IDs, GUIDs, dates, names), so an existing
recording is kept and only extended where a new response shows something it does
not: a field, a list item or a type of value at a path (`merge`). Results keep
their old entry if only IDs in paths and calls changed. `CT_RECORD_ALL=1` rewrites
everything.
"""

from __future__ import annotations

import json
import os
import re
import typing as _t
from pathlib import Path

import churchtools_api as ct
import pytest
from churchtools_api._resources import Resources
from redact import add_instance, clean_text, redact, scrub

ROOT = Path(__file__).resolve().parents[3]
RECORDED = ROOT / "fixtures" / "recorded"
RESULTS = ROOT / "fixtures" / "live-results.json"
CATALOG = json.loads((Path(__file__).parent / "operations.json").read_text())


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("CT_URL") and (os.environ.get("CT_TOKEN") or os.environ.get("CT_USER")):
        return
    skip = pytest.mark.skip(reason="set CT_URL and CT_USER/CT_PASSWORD (or CT_TOKEN) for live tests")
    for item in items:
        if "live" in item.nodeid.split("/"):
            item.add_marker(skip)


class Recorder:
    """Wraps the native client and remembers the last request and response."""

    def __init__(self, core: _t.Any) -> None:
        self.core = core
        self.last_request: dict[str, _t.Any] = {}
        self.last_body: bytes | None = None
        self.context = ""  # name of the running test
        self.log: list[tuple[str, str, int, str]] = []  # method, path, status, test

    @property
    def api_url(self) -> str:
        return _t.cast(str, self.core.api_url)

    def _remember(self, method: str, path: str, query: list[tuple[str, str]], body: str | None) -> None:
        self.last_request = {"method": method, "path": path, "query": query, "body": json.loads(body) if body else None}
        self.last_body = None

    def request(self, method: str, path: str, query: list[tuple[str, str]], body: str | None = None) -> bytes:
        self._remember(method, path, query, body)
        try:
            data = _t.cast(bytes, self.core.request(method, path, query, body))
        except ct.ApiError as e:
            self.log.append((method, path, e.status, self.context))
            raise
        self.log.append((method, path, 200, self.context))
        self.last_body = data
        self._record_scenario_call(method, path)
        return data

    def _record_scenario_call(self, method: str, path: str) -> None:
        """Write scenarios record their responses too, so their examples can be replayed.

        Reads are only recorded here if the read tests have nothing for them yet.
        """
        if not self.context:
            return
        op = operation_for(method, path)
        if op is not None and (method != "GET" or not (RECORDED / f"{op}.json").exists()):
            record(op, self)

    def request_multipart(
        self,
        method: str,
        path: str,
        query: list[tuple[str, str]],
        form: list[tuple[str, str]],
        file_field: str,
        files: list[tuple[str, bytes, str]],
    ) -> bytes:
        self._remember(method, path, query, None)
        try:
            data = _t.cast(bytes, self.core.request_multipart(method, path, query, form, file_field, files))
        except ct.ApiError as e:
            self.log.append((method, path, e.status, self.context))
            raise
        self.log.append((method, path, 200, self.context))
        self.last_body = data
        self._record_scenario_call(method, path)
        return data

    def pages(self, path: str, query: list[tuple[str, str]], prefetch: bool = True) -> _t.Iterator[bytes]:
        self._remember("GET", path, query, None)
        for page in self.core.pages(path, query, prefetch):
            self.last_body = page
            yield page


class LiveClient(ct.Client):
    recorder: Recorder


@pytest.fixture(scope="session")
def client() -> LiveClient:
    interval = float(os.environ.get("CT_MIN_INTERVAL", "0.25"))
    base = ct.Client(os.environ["CT_URL"], os.environ.get("CT_TOKEN"), min_interval=interval)
    add_instance(os.environ["CT_URL"])
    if os.environ.get("CT_USER"):
        base = base.login_with_password(os.environ["CT_USER"], os.environ.get("CT_PASSWORD", ""))
    live = LiveClient.__new__(LiveClient)
    live.recorder = Recorder(base._core)
    live._core = live.recorder  # type: ignore[assignment]
    Resources.__init__(live, live.recorder)
    return live


MAX_RECORDED_ITEMS = 200


def _shorten(body: _t.Any) -> _t.Any:
    """Keeps fixtures small: long `data` lists and maps are cut to MAX_RECORDED_ITEMS entries."""
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return {**body, "data": body["data"][:MAX_RECORDED_ITEMS]}
    if isinstance(body, dict) and isinstance(body.get("data"), dict) and len(body["data"]) > MAX_RECORDED_ITEMS:
        return {**body, "data": dict(list(body["data"].items())[:MAX_RECORDED_ITEMS])}
    return body


RECORD_ALL = os.environ.get("CT_RECORD_ALL") == "1"

# Keys that are data rather than field names: IDs, dates or GUIDs as in `{"795": {...}}`, `{"2026-11-03": {...}}`,
# `{"appointment-1437331-2026-11-22": {...}}`.
_DATA_KEY = re.compile(r"^-?\d+$|\d{4}-\d{2}|\d{3,}|^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-")


def _kind(value: _t.Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "string"
    return "object" if isinstance(value, dict) else "array"


def structure(value: _t.Any, path: str = "", out: set[tuple[str, str]] | None = None) -> set[tuple[str, str]]:
    """All (path, kind of value) pairs of a JSON value; list items share a path, data keys become `*`."""
    out = set() if out is None else out
    out.add((path, _kind(value)))
    if isinstance(value, dict):
        for k, v in value.items():
            structure(v, f"{path}/{'*' if _DATA_KEY.search(k) else k}", out)
    elif isinstance(value, list):
        for v in value:
            structure(v, f"{path}[]", out)
    return out


def _covered(new: set[tuple[str, str]], known: set[tuple[str, str]]) -> bool:
    """Whether `known` has every (path, kind) of `new`; `null` counts as covered where the path has a value."""
    paths = {p for p, _ in known}
    return all(entry in known or (entry[1] == "null" and entry[0] in paths) for entry in new)


def adds_structure(new: _t.Any, old: _t.Any) -> bool:
    """Whether `new` has a field or kind of value that `old` lacks."""
    return not _covered(structure(new), structure(old))


def _merge_items(items: list[tuple[_t.Any, _t.Any]], new: list[tuple[_t.Any, _t.Any]]) -> list[tuple[_t.Any, _t.Any]]:
    """(key, item) pairs of a list or data map, extended by what the new items add."""
    out = list(items)
    for key, item in new:
        known: set[tuple[str, str]] = set().union(*(structure(x) for _, x in out))
        if _covered(structure(item), known):
            continue
        target = next((i for i, (_, x) in enumerate(out) if isinstance(x, dict)), None)
        if target is not None and isinstance(item, dict):
            out[target] = (out[target][0], merge(out[target][1], item))  # new fields go into an existing item
            known = set().union(*(structure(x) for _, x in out))
        if not _covered(structure(item), known) and (key is None or key not in dict(out)):
            out.append((key, item))  # e.g. `null` where the existing items have an object
    return out


def merge(old: _t.Any, new: _t.Any) -> _t.Any:
    """`old` extended by the fields, list items and kinds of value of `new` that it lacks; otherwise unchanged.

    Keeps recordings stable between instances: a new field adds a few lines instead of a new file.
    """
    if isinstance(old, dict) and isinstance(new, dict):
        if old and new and all(_DATA_KEY.search(k) for k in (*old, *new)):  # a map like {"795": ..., "796": ...}
            return dict(_merge_items(list(old.items()), list(new.items())))
        out = dict(old)
        for k, v in new.items():
            out[k] = v if k not in old or (old[k] is None and v is not None) else merge(old[k], v)
        return out
    if isinstance(old, list) and isinstance(new, list):
        return [x for _, x in _merge_items([(None, x) for x in old], [(None, x) for x in new])]
    return old


# Recordings as they stand in this run: the first response of an operation is merged into the file from disk,
# later ones into the result, so several calls of one operation do not overwrite each other.
_fixtures: dict[str, dict[str, _t.Any]] = {}


def record(op_id: str, recorder: Recorder) -> None:
    """Stores the last successful JSON response of `op_id` as a fixture, unless the existing one covers it."""
    if recorder.last_body is None:
        return
    try:
        body = json.loads(recorder.last_body)
    except ValueError:
        return  # binary or text download
    body = _shorten(redact(op_id, body))
    RECORDED.mkdir(parents=True, exist_ok=True)
    fixture = {"operation": op_id, "request": scrub(recorder.last_request), "body": body}
    path = RECORDED / f"{op_id}.json"
    current = _fixtures.get(op_id) or (json.loads(path.read_text()) if path.exists() and not RECORD_ALL else None)
    if current is not None:
        merged = merge(current.get("body"), body)
        if merged == current.get("body"):
            _fixtures[op_id] = current
            return
        fixture = {**current, "body": merged}
    _fixtures[op_id] = fixture
    path.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n")


def _template_regex(path: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\\{[^}]+\\}", "[^/]+", re.escape(path)) + "$")


# Most specific first, so /persons/birthdays wins over /persons/{personId}.
TEMPLATES = sorted(
    ((e["method"], _template_regex(e["path"]), e["op_id"]) for e in CATALOG),
    key=lambda t: (t[1].pattern.count("[^/]+"), -len(t[1].pattern)),
)


def operation_for(method: str, path: str) -> str | None:
    return next((op for m, rx, op in TEMPLATES if m == method and rx.match(path)), None)


class Results:
    """Collects one outcome per operation and writes them at the end of the session."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, _t.Any]] = {}

    def add(self, op_id: str, outcome: str, **info: _t.Any) -> None:
        self.items[op_id] = {"outcome": outcome, **info}

    def add_scenario_calls(self, log: list[tuple[str, str, int, str]]) -> None:
        """Outcomes of operations called by the scenario tests (best result wins)."""
        for method, path, status, test in log:
            op = operation_for(method, path)
            if op is None or not test:
                continue
            known = self.items.get(op, {})
            if known and "scenario" not in known and known["outcome"] != "unresolved":
                continue
            current = self.items.get(op)
            if current is None or (current["outcome"] != "ok" and status < 300):
                from expectations import EXPECTED_ERRORS

                expected = EXPECTED_ERRORS.get(op)
                if status < 300:
                    self.items[op] = {"outcome": "ok", "scenario": test, "path": path}
                elif expected and expected[0] == status:
                    self.items[op] = {"outcome": "expected-error", "reason": expected[1], "scenario": test, "path": path}
                else:
                    self.items[op] = {"outcome": f"http-{status}", "scenario": test, "path": path}

    # Fields with IDs or content of the instance; an entry that differs only in these keeps its old version.
    VOLATILE = {"path", "call", "request", "message", "undocumented_response"}

    def write(self) -> None:
        old = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
        for op, new in self.items.items():
            known = old.get(op, {})
            stable = {k: v for k, v in new.items() if k not in self.VOLATILE}
            if RECORD_ALL or stable != {k: v for k, v in known.items() if k not in self.VOLATILE}:
                old[op] = new  # operations not run this time keep their result
        text = json.dumps(dict(sorted(old.items())), indent=1, ensure_ascii=False) + "\n"
        RESULTS.write_text(clean_text(text))  # calls can carry tokens, e.g. get_form(id, token=...)


@pytest.fixture(scope="session")
def results(client: LiveClient) -> _t.Iterator[Results]:
    r = Results()
    yield r
    r.add_scenario_calls(client.recorder.log)
    r.write()


# --- fixtures for the write scenarios ------------------------------------------


@pytest.fixture
def scenario(request: pytest.FixtureRequest, client: LiveClient, results: Results) -> _t.Iterator[None]:
    """Tags the requests of a write scenario, so they count for its operations."""
    client.recorder.context = request.node.name
    yield
    client.recorder.context = ""


@pytest.fixture
def cleanup(client: LiveClient) -> _t.Iterator[_t.Any]:
    from scenario import Cleanup

    c = Cleanup(client.recorder)
    yield c
    c.run()


@pytest.fixture(scope="session")
def me(client: LiveClient) -> int:
    return client.whoami.get().id


@pytest.fixture(scope="session")
def masterdata(client: LiveClient) -> ct.models.PersonMasterData:
    return client.person.get_master_data()


@pytest.fixture(scope="session")
def privacy_options(client: LiveClient) -> tuple[int, int]:
    from scenario import lookup_privacy_options

    return lookup_privacy_options(client)


@pytest.fixture
def ids(client: LiveClient, privacy_options: tuple[int, int]) -> _t.Any:
    """Instance-specific IDs (`scenario.InstanceIds`); per test, because security levels can be renumbered."""
    from scenario import lookup_ids

    return lookup_ids(client, privacy_options)

