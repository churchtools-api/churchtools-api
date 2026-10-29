"""Live tests against a ChurchTools test instance.

Run only when credentials are set; they are meant for throwaway demo instances
(https://church.tools/en/test-churchtools/), because the write tests create and delete data:

    CT_URL=https://xyz.church.tools CT_USER=... CT_PASSWORD=... pytest tests/live

`CT_MIN_INTERVAL` (seconds, default 0.25) spaces the requests so the instance
is not flooded. Successful responses are recorded to `fixtures/recorded/` and
replayed offline by `tests/test_recorded.py` and `core/tests/recorded.rs`.
A summary of all outcomes goes to `fixtures/live-results.json`.
"""

from __future__ import annotations

import json
import os
import re
import typing as _t
from pathlib import Path

import churchtools_rs as ct
import pytest
from churchtools_rs._resources import Resources
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

    def pages(self, path: str, query: list[tuple[str, str]]) -> _t.Iterator[bytes]:
        self._remember("GET", path, query, None)
        for page in self.core.pages(path, query):
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


def record(op_id: str, recorder: Recorder) -> None:
    """Stores the last successful JSON response of `op_id` as a fixture."""
    if recorder.last_body is None:
        return
    try:
        body = json.loads(recorder.last_body)
    except ValueError:
        return  # binary or text download
    body = _shorten(redact(op_id, body))
    RECORDED.mkdir(parents=True, exist_ok=True)
    fixture = {"operation": op_id, "request": scrub(recorder.last_request), "body": body}
    (RECORDED / f"{op_id}.json").write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n")


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

    def write(self) -> None:
        old = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
        old.update(self.items)  # keep results of operations not run this time
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

