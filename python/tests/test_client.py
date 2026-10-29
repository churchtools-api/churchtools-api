"""Offline tests against a local fake ChurchTools server."""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
import typing as _t
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

import churchtools_rs as ct


def person(id: int, first_name: str) -> dict:
    return {
        "id": id,
        "guid": f"guid-{id}",
        "firstName": first_name,
        "lastName": "X",
        "securityLevelForPerson": 1,
        "editSecurityLevelForPerson": 1,
    }


class FakeServer(BaseHTTPRequestHandler):
    requests: list[dict] = []
    busy_calls = 0

    def log_message(self, *args) -> None:
        pass

    def _reply(self, status: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method: str) -> None:
        url = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        content_type = self.headers.get("Content-Type") or ""
        body = json.loads(raw) if raw and content_type.startswith("application/json") else raw or None
        query = parse_qs(url.query)
        FakeServer.requests.append(
            {
                "method": method,
                "path": url.path,
                "query": query,
                "body": body,
                "content_type": content_type,
                "auth": self.headers.get("Authorization"),
            }
        )
        if url.path == "/api/persons" and method == "GET":
            page = int(query["page"][0])
            persons = [person(page * 10 + i, f"P{page}{i}") for i in range(2)]
            self._reply(200, {"data": persons, "meta": {"count": 2, "pagination": {"current": page, "lastPage": 3, "limit": 2, "total": 6}}})
        elif url.path == "/api/persons/7":
            self._reply(200, {"data": {**person(7, "Anna"), "birthday": "1990-05-17", "customField": 7}})
        elif url.path == "/api/groups/404":
            self._reply(404, {"message": "Group not found", "translatedMessage": "Gruppe nicht gefunden", "messageKey": "group.not_found", "args": [], "errors": []})
        elif url.path == "/api/persons" and method == "POST":
            self._reply(201, {"data": person(5, body["firstName"])})
        elif url.path == "/api/files/person/7" and method == "POST":
            self._reply(200, {"data": []})
        elif url.path == "/api/groups/7/meetings" and method == "POST":
            self._reply(400, {"message": "There are validation errors", "errors": [
                {"fieldId": "startDate", "message": "Bitte das Datum in folgendem Format eingeben", "args": {}}]})
        elif url.path == "/api/persons/8":
            self._reply(200, {"data": {**person(8, "Anna"), "id": "geheim@example.org"}})
        elif url.path == "/api/groups" and method == "POST":
            self.send_response(302)
            self.send_header("Location", "/api/groups/1")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif url.path == "/api/flaky":
            FakeServer.busy_calls += 1
            if FakeServer.busy_calls == 1 or method == "POST":
                self.send_response(503)
                self.send_header("Retry-After", "0")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._reply(200, {"data": 1})
        elif url.path == "/api/busy":
            FakeServer.busy_calls += 1
            if FakeServer.busy_calls == 1:
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._reply(200, {"data": {"build": "1", "version": "3.138.0"}})
        else:
            self._reply(500, {"message": "unexpected"})

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")


@pytest.fixture
def client():
    server = HTTPServer(("127.0.0.1", 0), FakeServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    FakeServer.requests = []
    FakeServer.busy_calls = 0
    yield ct.Client(f"http://127.0.0.1:{server.server_port}", token="secret")
    server.shutdown()


def test_pagination_fetches_all_pages_lazily(client):
    persons = client.persons.list(limit=2, ids=[1, 2])
    assert FakeServer.requests == []  # nothing sent before iterating

    first = persons.first()
    assert first is not None and first.first_name == "P10"
    assert len(FakeServer.requests) == 1

    FakeServer.requests.clear()
    assert [p.id for p in persons] == [10, 11, 20, 21, 30, 31]
    assert [r["query"]["page"] for r in FakeServer.requests] == [["1"], ["2"], ["3"]]
    assert FakeServer.requests[0]["query"]["ids[]"] == ["1", "2"]
    assert FakeServer.requests[0]["auth"] == "Login secret"


def test_typed_fields_and_unknown_fields(client):
    person = client.persons.get(7)
    assert isinstance(person, ct.models.Person)
    assert person.first_name == "Anna"
    assert person.birthday == dt.date(1990, 5, 17)
    assert person.model_extra == {"customField": 7}


def test_api_errors_map_to_exceptions(client):
    with pytest.raises(ct.NotFound) as info:
        client.groups.get(404)
    assert info.value.status == 404
    assert info.value.message_key == "group.not_found"
    assert info.value.translated_message == "Gruppe nicht gefunden"


def test_body_omits_unset_and_uses_api_names(client):
    person = client.persons.create(
        department_ids=[1], first_name="Ben", birthday=None, extra_body={"customField": "x"}, force=True
    )
    assert person.id == 5
    request = FakeServer.requests[-1]
    # birthday=None is sent as null, unset fields are left out
    assert request["body"] == {"departmentIds": [1], "firstName": "Ben", "birthday": None, "customField": "x"}
    assert request["query"] == {"force": ["true"]}


def test_query_values_are_formatted(client):
    events = client.events.list(from_=dt.date(2026, 11, 1), canceled=True)
    with pytest.raises(ct.ServerError):
        events.to_list()
    query = FakeServer.requests[-1]["query"]
    assert query == {"from": ["2026-11-01"], "canceled": ["true"], "page": ["1"]}


def test_transport_error():
    with pytest.raises(ct.ConnectError) as info:
        ct.Client("http://127.0.0.1:1", timeout=2).persons.get(1)
    assert isinstance(info.value, ct.TransportError)


def test_timeout_is_its_own_error() -> None:
    import socket

    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen()  # accepts connections, never answers
    try:
        with pytest.raises(ct.Timeout):
            ct.Client(f"http://127.0.0.1:{silent.getsockname()[1]}", timeout=0.3).persons.get(1)
    finally:
        silent.close()


def test_invalid_arguments_are_value_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ct.InvalidArgument):
        ct.Client("meinegemeinde.church.tools")
    monkeypatch.delenv("CT_URL", raising=False)
    with pytest.raises(ct.InvalidArgument, match="CT_URL is not set"):
        ct.Client.from_env()
    assert issubclass(ct.InvalidArgument, ValueError) and issubclass(ct.InvalidArgument, ct.ChurchToolsError)


def test_upload_sends_multipart(client):
    client.files.create("person", 7, files=[ct.Upload("brief.txt", b"Hallo Gemeinde")], sort_key=3)
    request = FakeServer.requests[-1]
    assert request["content_type"].startswith("multipart/form-data; boundary=")
    assert b'name="files[]"; filename="brief.txt"' in request["body"]
    assert b"Content-Type: text/plain" in request["body"]
    assert b"Hallo Gemeinde" in request["body"]
    assert b'name="sortKey"' in request["body"]


def test_datetimes_are_sent_as_utc_with_z(client):
    berlin = dt.timezone(dt.timedelta(hours=1))
    with pytest.raises(ct.BadRequest) as info:
        client.groups.meetings.create(7, start_date=dt.datetime(2026, 11, 1, 10, 30, 15, 123456, tzinfo=berlin))
    assert FakeServer.requests[-1]["body"] == {"startDate": "2026-11-01T09:30:15Z"}
    # field errors of the server are part of the message
    assert "startDate: Bitte das Datum" in str(info.value)


def test_too_many_requests_is_retried(client):
    start = time.monotonic()
    assert client._core.request("GET", "/busy", []) == b'{"data": {"build": "1", "version": "3.138.0"}}'
    assert FakeServer.busy_calls == 2
    assert time.monotonic() - start >= 1.0  # waited for Retry-After


def test_min_interval_spaces_requests():
    server = HTTPServer(("127.0.0.1", 0), FakeServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = ct.Client(f"http://127.0.0.1:{server.server_port}", min_interval=0.2)
    start = time.monotonic()
    for _ in range(3):
        client.persons.get(7)
    assert time.monotonic() - start >= 0.4
    server.shutdown()



@pytest.mark.parametrize("member_id", ["..", ".", ""])
def test_dot_segments_in_ids_are_rejected(client: ct.Client, member_id: str) -> None:
    # `..` would turn DELETE /groups/7/members/.. into DELETE /groups/7
    with pytest.raises(ValueError, match="invalid path"):
        client.groups.members.delete(7, member_id)  # type: ignore[arg-type]  # IDs from user input
    assert FakeServer.requests == []


def test_percent_encoded_dot_segments_in_raw_paths_are_rejected(client: ct.Client) -> None:
    with pytest.raises(ValueError, match="invalid path"):
        client._core.request("DELETE", "/groups/7/members/%2e%2E", [])


def test_token_is_not_part_of_repr(client: ct.Client) -> None:
    assert "secret" not in repr(client) and "secret" not in repr(client._core)


def test_token_with_line_break_is_rejected(client: ct.Client) -> None:
    broken = ct.Client(client.api_url, token="abc\r\nX-Injected: 1")
    with pytest.raises(ValueError, match="invalid token"):
        broken.persons.get(7)


def test_plain_http_needs_opt_in_outside_localhost() -> None:
    with pytest.raises(ct.InvalidArgument, match="unencrypted"):
        ct.Client("http://ct.example.org", token="secret")
    assert ct.Client("http://ct.example.org", allow_insecure_http=True).api_url == "http://ct.example.org/api"


def test_decode_error_message_omits_input_values(client: ct.Client) -> None:
    with pytest.raises(ct.DecodeError) as info:
        client.persons.get(8)
    assert "data.id" in str(info.value)
    assert "geheim@example.org" not in str(info.value)
    assert info.value.__cause__ is None  # the ValidationError would repeat the input
    assert b"geheim@example.org" in info.value.body


def test_redirect_of_a_write_is_an_error(client: ct.Client) -> None:
    with pytest.raises(ct.RedirectError) as info:
        client._core.request("POST", "/groups", [], '{"name": "x"}')
    assert (info.value.status, info.value.location) == (302, "/api/groups/1")
    assert [r["method"] for r in FakeServer.requests] == ["POST"]


@pytest.mark.parametrize("option", ["timeout", "min_interval", "connect_timeout"])
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), 1e30])
def test_invalid_durations_raise_value_error(option: str, value: float) -> None:
    with pytest.raises(ct.InvalidArgument, match=f"{option} must be a non-negative number"):
        options: dict[str, _t.Any] = {option: value}
        ct.Client("https://x.church.tools", **options)


def test_responses_above_the_size_limit_raise(client: ct.Client) -> None:
    limited = ct.Client(client.api_url, max_response_size=50)
    with pytest.raises(ct.ResponseTooLarge, match="larger than the limit of 50 bytes") as info:
        limited.persons.get(7)
    assert info.value.limit == 50


def test_unavailable_server_is_retried_for_get_but_not_post(client: ct.Client) -> None:
    assert client._core.request("GET", "/flaky", []) == b'{"data": 1}'
    with pytest.raises(ct.ServerError):
        client._core.request("POST", "/flaky", [])
    assert [r["method"] for r in FakeServer.requests] == ["GET", "GET", "POST"]


def test_deprecated_operations_and_arguments_warn(client: ct.Client) -> None:
    with pytest.warns(DeprecationWarning, match="GET /persons/search_old is deprecated"):
        with pytest.raises(ct.ServerError):
            client.persons.list_search_old()
    with pytest.warns(DeprecationWarning, match="argument .type_. is deprecated in the ChurchTools API. Use `format`"):
        with pytest.raises(ct.ServerError):
            client.groups.members.create_export(7, type_="csv")


def test_raw_request_reaches_any_endpoint(client: ct.Client) -> None:
    body = client.request("POST", "/persons", query={"force": True, "ids[]": [1, 2]}, json={"firstName": "Ben"})
    assert json.loads(body)["data"]["firstName"] == "Ben"
    request = FakeServer.requests[-1]
    assert request["query"] == {"force": ["true"], "ids[]": ["1", "2"]}
    assert request["body"] == {"firstName": "Ben"}
    with pytest.raises(ct.NotFound):
        client.request("GET", "/groups/404")
