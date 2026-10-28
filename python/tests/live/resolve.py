"""Finds argument values for calling an operation on a live instance.

Path parameters are taken from the matching list endpoint: for
`/groups/{groupId}/meetings/{meetingId}` the first group of `GET /groups`, then
the first meeting of `GET /groups/<id>/meetings`. Where the URL structure does
not lead to a list, `PATH_VALUES` and `QUERY_VALUES` say where to look.
"""

from __future__ import annotations

import datetime as dt
import json
import typing as _t

import churchtools_rs as ct

from conftest import CATALOG

GETS = {e["path"]: e for e in CATALOG if e["method"] == "GET"}
TODAY = dt.date.today()


class Unresolved(Exception):
    """No sensible value exists on this instance (e.g. no data of that kind)."""


Values = dict[str, _t.Any]  # wire name -> value, for the current operation
Rule = _t.Union[_t.Any, _t.Callable[["Resolver", Values], _t.Any]]


def first_of(path: str, *keys: str, query: tuple[tuple[str, str], ...] = ()) -> Rule:
    return lambda r, v: r.pick(r.first(path.format(**v), query), *keys)


def me(r: "Resolver", v: Values) -> int:
    return r.me()


def image_part(index: int) -> Rule:
    """File id or hash from the avatar URL of the current user (`.../images/<id>/<hash>`)."""
    return lambda r, v: r.data("/whoami")["imageUrl"].split("/images/")[1].split("/")[index]


# Keys are the wire name, or (path template, wire name) for a single endpoint.
# Wire-name rules are fallbacks; the URL structure (see `Resolver.path_value`) wins.
PATH_VALUES: dict[_t.Any, Rule] = {
    "personId": me,
    "domainType": "person",
    "domainIdentifier": me,
    "domainId": me,
    "eventId": first_of("/events", "id"),
    "serviceId": first_of("/services", "id"),
    "calendarId": first_of("/calendars", "id"),
    "groupId": first_of("/groups", "id"),
    "songId": first_of("/songs", "id"),
    "resourceId": first_of("/resources", "id"),
    "wikiCategoryId": first_of("/wiki/categories", "id"),
    "accountId": first_of("/finance/accounts", "id"),
    "memberId": lambda r, v: r.pick(r.first(f"/groups/{v['groupId']}/members"), "personId"),
    "module": lambda r, v: r.pick(r.first(f"/persons/{r.me()}/settings"), "module"),
    "attribute": lambda r, v: r.pick(r.first(f"/persons/{r.me()}/settings"), "attribute"),
    "startDate": lambda r, v: r.appointment_start(v),
    "fileId": image_part(0),
    "hash": image_part(1),
    ("/files/{id}/meta", "id"): image_part(0),
    ("/tags/{domainType}", "domainType"): "person",
    ("/tags/{domainType}/{domainId}", "domainType"): "person",
    ("/addresses/{domainType}/{domainIdentifier}", "domainType"): "group",
    ("/addresses/{domainType}/{domainIdentifier}", "domainIdentifier"): first_of("/groups", "id"),
    ("/placeholders/group/{id}", "id"): first_of("/groups", "id"),
    ("/profiles/slugcheck/{slug}", "slug"): "ctrs-test-slug",
    ("/grouphomepages/{hash}", "hash"): lambda r, v: r.first("/grouphomepages")["apiUrl"].rsplit("/", 1)[1],
    ("/publicgroups/{groupId}/{hash}", "groupId"): lambda r, v: r.first("/grouphomepages")["domainAttributes"]["childGroupIds"][0],
    ("/publicgroups/{groupId}/{hash}", "hash"): lambda r, v: r.first("/grouphomepages")["apiUrl"].rsplit("/", 1)[1],
    ("/htmltemplates/{templateId}", "templateId"): first_of("/htmltemplates", "id", query=(("domain_type", "bulkletter"),)),
    "htmlTemplateId": first_of("/htmltemplates", "id", query=(("domain_type", "groupmember-document"),)),
    ("/persons/{personId}/merge/{duplicateId}", "personId"): lambda r, v: r.first("/persons/duplicates")["relationships"][0]["p1"]["id"],
    ("/persons/{personId}/merge/{duplicateId}", "duplicateId"): lambda r, v: r.first("/persons/duplicates")["relationships"][0]["p2"]["id"],
}
PATH_VALUES["tagId"] = first_of("/tags/person", "id")
PATH_VALUES["authId"] = lambda r, v: r.data("/permissions/definitions")["modules"][0]["permissions"][0]["authId"]
PATH_VALUES[("/permissions/internal/groups/{groupId}/auths/{authId}/persons", "authId")] = (
    # a yes/no permission; others need a data id
    lambda r, v: next(
        p["authId"]
        for m in r.data("/permissions/definitions", (("scope", "internal"),))["modules"]
        for p in m["permissions"]
        if p["valueType"] == "boolean"
    )
)
PATH_VALUES[("/queues/{queue}/jobgroups/{jobGroup}", "queue")] = "default"
PATH_VALUES[("/queues/{queue}/jobgroups/{jobGroup}", "jobGroup")] = "default"
PATH_VALUES[("/registrationconfig/{id}", "id")] = 1
PATH_VALUES[("/images/{fileId}/{hash}/{queryParams}", "queryParams")] = "w=100"
# The appointment and its start date must come from the same list entry.
PATH_VALUES[("/calendars/appointments/{appointmentId}/{startDate}", "appointmentId")] = lambda r, v: r.pick(r.upcoming_appointment(), "id")

# Occurrence paths want the start date of the appointment (Y-m-d), not the timestamp.
for _t_path in ("/calendars/appointments/{appointmentId}/{startDate}",
                "/calendars/{calendarId}/appointments/{appointmentId}/{startDate}"):
    PATH_VALUES[(_t_path, "startDate")] = lambda r, v: r.appointment_start(v)
# `serviceId` here is the id of the event service (assignment), not of the service.
for _t_path in ("/persons/{personId}/events/{eventId}/services/{serviceId}/exchangerequests",
                "/persons/{personId}/events/{eventId}/services/{serviceId}/exchangerequests/candidates"):
    PATH_VALUES[(_t_path, "serviceId")] = lambda r, v: r.pick(
        r.first(f"/persons/{v['personId']}/events/{v['eventId']}/services"), "id")
# Despite the URL, this is a service id, not an event id.
PATH_VALUES[("/events/{serviceId}/possiblepersonsforservice", "serviceId")] = first_of("/services", "id")
for _t_path in ("/htmltemplates/{templateId}/export", "/htmltemplates/{templateId}/html", "/htmltemplates/{templateId}/mjml"):
    PATH_VALUES[(_t_path, "templateId")] = PATH_VALUES[("/htmltemplates/{templateId}", "templateId")]

# URL prefixes whose `{personId}` should be the logged-in user, not the first person.
OWN_PERSON_PREFIXES = {"/persons", "/subscriptions", "/permissions/internal/persons", "/permissions/origins/global/persons",
                       "/permissions/origins/internal/persons"}

# Required query parameters, by Python name or (path template, Python name).
QUERY_VALUES: dict[_t.Any, Rule] = {
    "from_": TODAY - dt.timedelta(days=30),
    "to": TODAY + dt.timedelta(days=60),
    "calendar_ids": lambda r, v: [c["id"] for c in r.data("/calendars")],
    "resource_ids": lambda r, v: [x["id"] for x in r.data("/resources")][:5],
    "accounting_period_id": first_of("/finance/accountingperiods", "id"),
    "person_id": me,
    "query": "Go",
    "domain_types": ["person"],
    "domain_identifiers": lambda r, v: [str(r.me())],
    "since": dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(days=7),
    "group_type_role_ids": lambda r, v: [r.pick(r.first(f"/groups/{v['groupId']}/roles"), "groupTypeRoleId")],
    ("/htmltemplates", "domain_type"): "bulkletter",
}

# Optional parameters the server nevertheless requires, by operationId (Python names).
CALL_EXTRAS: dict[str, Rule] = {
    "get-churchquery-metadata": {"entity_to_search_for": "person"},
    "get-profiles-slugcheck-slug": {"guid": "00000000-0000-0000-0000-000000000000"},
    "get-post-reports": {"domain_type": "post"},
    "get-post-linkings": lambda r, v: {"post_ids": [r.pick(r.first("/posts"), "id")]},
    "get-finance-transactions-summary": lambda r, v: {"account_ids": [r.pick(r.first("/finance/accounts"), "id")]},
}


class Resolver:
    def __init__(self, client: _t.Any, seed: _t.Any = None) -> None:
        self.core = client.recorder.core  # unrecorded, so fixtures only hold the call under test
        # Values for data created by seed.py, keyed like PATH_VALUES / QUERY_VALUES.
        self.seed_paths: dict[tuple[str, str], _t.Any] = seed.paths if seed else {}
        self.seed_queries: dict[tuple[str, str], _t.Any] = seed.queries if seed else {}
        self.cache: dict[tuple[str, tuple[tuple[str, str], ...]], _t.Any] = {}

    def body(self, path: str, query: tuple[tuple[str, str], ...] = ()) -> _t.Any:
        key = (path, query)
        if key not in self.cache:
            try:
                self.cache[key] = json.loads(self.core.request("GET", path, list(query)))
            except ct.ApiError as e:
                self.cache[key] = e
        value = self.cache[key]
        if isinstance(value, ct.ApiError):
            raise Unresolved(f"GET {path} failed: {value}")
        return value

    def data(self, path: str, query: tuple[tuple[str, str], ...] = ()) -> _t.Any:
        body = self.body(path, query)
        return body.get("data", body) if isinstance(body, dict) else body

    def first(self, path: str, query: tuple[tuple[str, str], ...] = ()) -> _t.Any:
        data = self.data(path, query)
        if isinstance(data, dict):
            # Some lists come keyed by id.
            data = list(data.values()) if data and all(isinstance(x, dict) for x in data.values()) else [data]
        if not data:
            raise Unresolved(f"GET {path} returned no items")
        return data[0]

    @staticmethod
    def pick(item: _t.Any, *keys: str) -> _t.Any:
        if not isinstance(item, dict):
            return item
        # Appointments and bookings nest their id: {"appointment": {"base": {"id": ...}}}.
        candidates = [item, item.get("base"), item.get("appointment"), (item.get("appointment") or {}).get("base")]
        for key in (*keys, "id", "guid", "hash", "identifier"):
            for c in candidates:
                if isinstance(c, dict) and c.get(key) not in (None, ""):
                    return c[key]
        raise Unresolved(f"none of {keys} in item")

    def me(self) -> int:
        return _t.cast(int, self.data("/whoami")["id"])

    def upcoming_appointment(self) -> _t.Any:
        q = (("from", str(TODAY - dt.timedelta(days=30))), ("to", str(TODAY + dt.timedelta(days=60))))
        return self.first(f"/calendars/{self.pick(self.first('/calendars'), 'id')}/appointments", q)

    def appointment_start(self, values: Values) -> str:
        cal = values.get("calendarId") or self.pick(self.first("/calendars"), "id")
        q = (("from", str(TODAY - dt.timedelta(days=30))), ("to", str(TODAY + dt.timedelta(days=60))))
        app = self.first(f"/calendars/{cal}/appointments", q)
        if values.get("appointmentId") not in (None, self.pick(app, "id")):
            raise Unresolved("appointment is not in the first calendar")
        app = app.get("appointment", app)
        return str(app.get("calculated", app)["startDate"])[:10]

    def rule(self, table: dict[_t.Any, Rule], path: str, name: str, values: Values) -> _t.Any:
        rule = table.get((path, name), table.get(name, Unresolved))
        if rule is Unresolved:
            return Unresolved
        return rule(self, values) if callable(rule) else rule

    def path_value(self, entry: dict[str, _t.Any], name: str, values: Values) -> _t.Any:
        path = entry["path"]
        if (path, name) in self.seed_paths:
            return self.seed_paths[(path, name)]
        prefix = path.split("{" + name + "}")[0].rstrip("/")
        if (path, name) in PATH_VALUES or (name == "personId" and prefix in OWN_PERSON_PREFIXES):
            return self.rule(PATH_VALUES, path, name, values)
        # Prefer the structure of the URL: /x/{a}/y/{b} -> first item of GET /x/<a>/y.
        listing = GETS.get(prefix)
        if listing is not None and listing is not entry:
            concrete = prefix.format(**values)
            query = tuple((k, str(x)) for k, v in self.query_args(listing, values).items() for x in _as_list(v))
            item = self.first(concrete, query)  # an empty list means: no such data here
            try:
                return self.pick(item, name)
            except Unresolved:
                pass
        value = self.rule(PATH_VALUES, path, name, values)
        if value is Unresolved:
            raise Unresolved(f"no value for path parameter {name}")
        return value

    def query_args(self, entry: dict[str, _t.Any], values: Values) -> dict[str, _t.Any]:
        """Required query parameters by wire name."""
        out = {}
        for p in entry["params"]:
            if p["kind"] != "query" or not p["required"]:
                continue
            value = self.seed_queries.get((entry["path"], p["py"]), Unresolved)
            if value is Unresolved:
                value = self.rule(QUERY_VALUES, entry["path"], p["py"], values)
            if value is Unresolved:
                value = default_value(p)
            if p["type"].startswith("List[") and not isinstance(value, list):
                value = [value]
            out[p["wire"]] = value
        return out

    def arguments(self, entry: dict[str, _t.Any]) -> tuple[list[_t.Any], dict[str, _t.Any]]:
        values: Values = {}
        args = []
        for p in entry["params"]:
            if p["kind"] == "path":
                value = self.path_value(entry, p["wire"], values)
                value = int(value) if p["type"] == "int" else value
                values[p["wire"]] = value
                args.append(value)
        by_wire = {p["wire"]: p["py"] for p in entry["params"]}
        kwargs = {by_wire[k]: v for k, v in self.query_args(entry, values).items()}
        extras = CALL_EXTRAS.get(entry["op_id"], {})
        kwargs.update(extras(self, values) if callable(extras) else extras)
        return args, kwargs


def _as_list(value: _t.Any) -> list[_t.Any]:
    return value if isinstance(value, list) else [value]


def default_value(p: dict[str, _t.Any]) -> _t.Any:
    if p["enum"]:
        return p["enum"][0]
    if p["default"] is not None:
        return p["default"]
    if p["example"] is not None:
        return p["example"]
    base = p["type"].removeprefix("List[").removesuffix("]").removeprefix("Optional[").removesuffix("]")
    if base == "date":
        return TODAY
    if base == "datetime":
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    if base == "bool":
        return False
    raise Unresolved(f"no value for required query parameter {p['py']}")
