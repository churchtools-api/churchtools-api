"""Benchmarks of the Python package against pure-Python clients doing the same work.

Every variant talks to the same local server (`churchtools-bench serve`, built
from recorded responses), reuses one connection and decodes into the same
generated Pydantic models. See README.md for the scenarios.

    python benchmarks/bench.py [--rounds 15] [--json] [--only get_person,...]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import subprocess
import sys
import time
import typing as _t
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import orjson
import requests
import urllib3
from pydantic import BaseModel, TypeAdapter

import churchtools_rs as ct
from churchtools_rs import models
from churchtools_rs._base import _parse

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks"
PERSONS = 5000  # must match server.rs
PAGE_SIZE = 500
WARMUP = 0.3  # seconds of warm-up before measuring
ROUND = 0.1  # target seconds per measured round
HEADERS = {"Authorization": "Login bench", "Accept": "application/json"}

# Body of the recorded `POST /persons`, as a pure-Python client would build it.
CREATE_BODY: dict[str, _t.Any] = {
    "birthday": "1990-05-17",
    "campusId": 0,
    "departmentIds": [1],
    "firstName": "ctrs-test",
    "lastName": "Vereinbarung",
    "privacyPolicyAgreementDate": "2026-10-29",
    "privacyPolicyAgreementTypeId": 1,
    "privacyPolicyAgreementWhoId": 1,
    "statusId": 0,
}


class Pagination(BaseModel):
    current: int
    lastPage: int


class Meta(BaseModel):
    pagination: _t.Optional[Pagination] = None


class PersonPage(BaseModel):
    data: list[models.Person]
    meta: Meta


class PersonEnvelope(BaseModel):
    data: models.Person


PERSON_LIST = TypeAdapter(list[models.Person])


class Stats(_t.NamedTuple):
    median: float
    min: float
    max: float


def measure(rounds: int, f: _t.Callable[[], object]) -> Stats:
    """Time per call in microseconds: warm-up, then `rounds` rounds of ~ROUND seconds."""
    start, calls = time.perf_counter(), 0
    while calls < 3 or time.perf_counter() - start < WARMUP:
        f()
        calls += 1
    n = max(1, round(ROUND / ((time.perf_counter() - start) / calls)))
    times = []
    for _ in range(rounds):
        t = time.perf_counter()
        for _ in range(n):
            f()
        times.append((time.perf_counter() - t) * 1e6 / n)
    return Stats(statistics.median(times), min(times), max(times))


def start_server() -> tuple[subprocess.Popen[str], str]:
    subprocess.run(["cargo", "build", "--release", "--quiet", "--manifest-path", str(BENCH / "Cargo.toml")], check=True)
    exe = BENCH / "target" / "release" / "churchtools-bench"
    proc = subprocess.Popen([str(exe), "serve"], stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    return proc, proc.stdout.readline().strip()


# --- pure-Python clients --------------------------------------------------------


class Typical:
    """What one would write by hand: `requests.Session`, `.json()`, `model_validate`."""

    def __init__(self, api: str) -> None:
        self.api = api
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get_person(self) -> models.Person:
        r = self.session.get(f"{self.api}/persons/1")
        r.raise_for_status()
        return models.Person.model_validate(r.json()["data"])

    def list_persons(self) -> _t.Iterator[models.Person]:
        page = 1
        while True:
            r = self.session.get(f"{self.api}/persons", params={"page": page, "limit": PAGE_SIZE})
            r.raise_for_status()
            body = r.json()
            for item in body["data"]:
                yield models.Person.model_validate(item)
            pagination = body.get("meta", {}).get("pagination")
            if not body["data"] or not pagination or pagination["current"] >= pagination["lastPage"]:
                return
            page += 1

    def create_person(self) -> models.Person:
        r = self.session.post(f"{self.api}/persons", params={"force": "true"}, json=CREATE_BODY)
        r.raise_for_status()
        return models.Person.model_validate(r.json()["data"])


class Httpx:
    """`httpx.Client` with Pydantic decoding straight from the bytes (`validate_json`)."""

    def __init__(self, api: str) -> None:
        self.api = api
        self.http = httpx.Client(base_url=api, headers=HEADERS)

    def get_person(self) -> models.Person:
        r = self.http.get("/persons/1")
        r.raise_for_status()
        return PersonEnvelope.model_validate_json(r.content).data

    def list_persons(self) -> _t.Iterator[models.Person]:
        page = 1
        while True:
            r = self.http.get("/persons", params={"page": page, "limit": PAGE_SIZE})
            r.raise_for_status()
            body = PersonPage.model_validate_json(r.content)
            yield from body.data
            p = body.meta.pagination
            if not body.data or not p or p.current >= p.lastPage:
                return
            page += 1

    def create_person(self) -> models.Person:
        r = self.http.post("/persons", params={"force": "true"}, content=orjson.dumps(CREATE_BODY),
                           headers={"Content-Type": "application/json"})
        r.raise_for_status()
        return PersonEnvelope.model_validate_json(r.content).data


class Efficient:
    """A lean pure-Python client: urllib3 connection pool, orjson for the body, `validate_json`."""

    def __init__(self, api: str) -> None:
        url = urlsplit(api)
        self.prefix = url.path
        self.pool = urllib3.HTTPConnectionPool(url.hostname, url.port, maxsize=1, headers=HEADERS)

    def _request(self, method: str, path: str, body: _t.Optional[bytes] = None) -> bytes:
        headers = {**HEADERS, "Content-Type": "application/json"} if body is not None else None
        r = self.pool.request(method, self.prefix + path, body=body, headers=headers)
        if r.status >= 400:
            raise RuntimeError(f"HTTP {r.status}")
        return r.data

    def get_person(self) -> models.Person:
        return PersonEnvelope.model_validate_json(self._request("GET", "/persons/1")).data

    def list_persons(self) -> _t.Iterator[models.Person]:
        page = 1
        while True:
            body = PersonPage.model_validate_json(self._request("GET", f"/persons?page={page}&limit={PAGE_SIZE}"))
            yield from body.data
            p = body.meta.pagination
            if not body.data or not p or p.current >= p.lastPage:
                return
            page += 1

    def create_person(self) -> models.Person:
        body = self._request("POST", "/persons?force=true", orjson.dumps(CREATE_BODY))
        return PersonEnvelope.model_validate_json(body).data


# --- scenarios -------------------------------------------------------------------


def count(items: _t.Iterable[object]) -> None:
    n = sum(1 for _ in items)
    assert n == PERSONS, n


def scenarios(url: str) -> dict[str, dict[str, _t.Callable[[], object]]]:
    api = url + "/api"
    client = ct.Client(url, token="bench")

    def create() -> models.Person:
        return client.persons.create(
            force=True, department_ids=[1], first_name="ctrs-test", last_name="Vereinbarung",
            birthday=dt.date(1990, 5, 17), campus_id=0, status_id=0,
            privacy_policy_agreement_date=dt.date(2026, 10, 29), privacy_policy_agreement_type_id=1,
            privacy_policy_agreement_who_id=1,
        )

    efficient = Efficient(api)
    clients: dict[str, Typical | Httpx | Efficient] = {
        "requests + model_validate": Typical(api), "httpx + validate_json": Httpx(api),
        "urllib3 + validate_json": efficient,
    }
    page = efficient._request("GET", f"/persons?page=1&limit={PAGE_SIZE}")

    def json_model_validate() -> None:
        for item in json.loads(page)["data"]:
            models.Person.model_validate(item)

    return {
        "get_person": {
            "churchtools_rs": lambda: client.persons.get(1),
            **{name: c.get_person for name, c in clients.items()},
            # Transport only, without decoding: the floor of each stack.
            "churchtools_rs (nur HTTP)": lambda: client._core.request("GET", "/persons/1", [], None),
            "urllib3 (nur HTTP)": lambda: efficient._request("GET", "/persons/1"),
        },
        "list_persons": {
            "churchtools_rs": lambda: count(client.persons.list(limit=PAGE_SIZE)),
            **{name: (lambda c=c: count(c.list_persons())) for name, c in clients.items()},
        },
        "create_person": {
            "churchtools_rs": create,
            **{name: c.create_person for name, c in clients.items()},
        },
        "decode_page": {
            "json.loads + model_validate": json_model_validate,
            "orjson.loads + validate_python": lambda: PERSON_LIST.validate_python(orjson.loads(page)["data"]),
            "validate_json (wie churchtools_rs)": lambda: _parse(page, _t.List[models.Person], True),
            # Untyped, for reference: parsing alone, no models.
            "json.loads (nur Parsen)": lambda: json.loads(page),
            "orjson.loads (nur Parsen)": lambda: orjson.loads(page),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=15)
    parser.add_argument("--json", action="store_true", help="one JSON object per line")
    parser.add_argument("--only", help="comma-separated scenarios")
    args = parser.parse_args()
    server, url = start_server()
    try:
        for scenario, variants in scenarios(url).items():
            if args.only and scenario not in args.only.split(","):
                continue
            for variant, f in variants.items():
                s = measure(args.rounds, f)
                if args.json:
                    print(json.dumps({"scenario": scenario, "variant": variant, "median_us": s.median,
                                      "min_us": s.min, "max_us": s.max}), flush=True)
                else:
                    print(f"{scenario:<18} {variant:<34} {s.median:>12.1f} µs  ({s.min:.1f} – {s.max:.1f})", flush=True)
    finally:
        server.kill()


if __name__ == "__main__":
    sys.exit(main())
