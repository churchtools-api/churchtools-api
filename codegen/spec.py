"""Reads the OpenAPI spec into a small IR (types, models, operations) and names
the operations. Corrections where the real API contradicts the spec live here too.

The ChurchTools spec inlines every schema instead of using `$ref`. Each inline
copy is byte-identical to an entry in `components.schemas`, so the names are
recovered by comparing canonical JSON.
"""

from __future__ import annotations

import json
import re
import typing as _t
from dataclasses import dataclass, field

from naming import (
    clean_doc,
    keyword_safe,
    pascal,
    snake,
    split_words,
    unique,
)

TAGS: set[str] | None = None  # None = all tags

# Corrections where real responses contradict the spec, found by the live tests
# (python/tests/live). Each entry names the evidence; see docs/testbericht.md.
#
# (model, JSON field) -> changes to the field
FIELD_FIXES: dict[tuple[str, str], dict[str, bool]] = {  # required / nullable / any (untyped)
    # Old records (e.g. song files from 2019) carry only modifiedDate/modifiedPerson,
    # and agenda templates send the PHP zero date "-0001-11-29T23:06:32Z".
    **{(m, f): {"required": False, "nullable": True}
       for m in ("MetaDataEntityId", "MetaDataEntityPerson")
       for f in ("createdDate", "createdPerson", "modifiedDate", "modifiedPerson")},
    # GET /post/groups: roleName is null for groups where the user has no role.
    ("PossiblePostGroup", "roleName"): {"nullable": True},
    # POST /publicgroups/{id}/token sends only {id, cloneWithoutChanging, customFields} as group.
    ("PublicGroupToken", "group"): {"any": True},
    # PUT /posts/{id}/reactions/{emoji}/persons/{personId} answers without meta.
    ("PostReaction", "meta"): {"required": False},
}
# operationId -> changes to the response description. `result`/`type` describe a
# response body the spec does not document at all.
RESULT_FIXES: dict[str, dict[str, _t.Any]] = {
    # Returns {"data": null} when authenticated with a login token instead of a session.
    "get-csrftoken": {"nullable": True},
    # Documented without the {"data": ...} envelope, but sent with it.
    "get-finance-templates-export": {"envelope": True},
    # Undocumented bodies: the single level comes without envelope, unlike the list.
    "get-securitylevels-id": {"result": "json", "type": "SecurityLevel"},
    "get-persons-search_old": {"result": "data", "type": "List[int]"},
    "get-churchquery-metadata": {"result": "data", "type": "any"},
    # Documented as a list, but a single statistics object is sent.
    "get-persons-personId-poststatistics": {"type": "item"},
    # Documented as a list of linkings, but each item wraps them:
    # {"postGuid", "postId", "linkings": [...]}.
    "get-post-linkings": {"type": "any"},
    # Documented like GET /persons/{id}/relationships (relative, relationshipName...),
    # but answers like GET /persons/relationships (personAId, personBId, relationshipType).
    "post-persons-personId-relationships": {"type": "GetPersonsRelationshipsDataItem"},
}

# Filled by main(): the documentation example of every operation (examples.Example)
# and the operations with a recorded response (fixtures/recorded), so examples can
# go into doc comments and run as doctests.
EXAMPLES: dict[str, _t.Any] = {}
RECORDED: set[str] = set()

# operationId -> (resource chain, method name) for cases the naming rules get wrong.
NAME_OVERRIDES: dict[str, tuple[str, str]] = {
    # Appointments are addressed with or without a calendar and as series or occurrence.
    "get-calendars-appointments": ("calendars.appointments", "list"),
    "get-calendars-calendarId-appointments": ("calendars.appointments", "list_in_calendar"),
    "get-calendars-calendarId-appointments-appointmentId": ("calendars.appointments", "get"),
    "get-calendars-appointments-appointmentId-startDate": ("calendars.appointments", "get_occurrence"),
    "get-calendars-calendarId-appointments-appointmentId-startDate": (
        "calendars.appointments",
        "get_occurrence_in_calendar",
    ),
    "post-calendars-calendarId-appointments-appointmentId": ("calendars.appointments", "split"),
    "post-calendars-calendarId-appointments-appointmentId-meetingrequests-meetingRequestId-answer": (
        "calendars.appointments.meetingrequests",
        "answer",
    ),
    "get-events-facts": ("events.facts", "list_all"),
    "put-events-id-eventservices": ("events.eventservices", "update_all"),
    "put-events-eventId-servicerequests": ("events.servicerequests", "update_all"),
    "get-group-roles": ("group.roles", "list"),
    "get-persons-id-settings-module": ("persons.settings", "get_module"),
    # POST requests that only read or compute something
    "post-actions": ("actions", "filter"),
    "post-probes": ("probes", "filter"),
    "post-domainobjects": ("domainobjects", "resolve"),
    "post-finance-accountingperiods-id-statements": ("finance.accountingperiods.statements", "preview"),
    "post-repeatcalculation": ("repeatcalculation", "calculate"),
    # Bookings
    "post-bookings-id": ("bookings", "split"),
    "post-bookings-conflicts": ("bookings", "preview_conflicts"),
    "post-bookings-id-conflicts": ("bookings", "preview_conflicts_for"),
    "put-bookings-bookingId-answer": ("bookings", "answer"),
    # Dynamic groups
    "post-dynamicgroups": ("dynamicgroups", "refresh_all"),
    "post-dynamicgroups-id-refresh": ("dynamicgroups", "refresh"),
    # External logins
    "get-externallogins-oidc-callback": ("externallogins.oidc", "callback"),
    "get-externallogins-id-oidc-callback": ("externallogins.oidc", "callback_for"),
    # Files: by domain object or by file ID
    "get-files-domainType": ("files", "list_for_type"),
    "get-files-domainType-domainIdentifier": ("files", "list"),
    "patch-files-domainType-domainIdentifier": ("files", "update_for_object"),
    "patch-files-id": ("files", "patch"),
    "delete-files-domainType-domainIdentifier": ("files", "delete_for_object"),
    "delete-files-id": ("files", "delete"),
    # Donation receipts: all donors or one donor couple
    "get-finance-donators-receipts": ("finance.donators", "get_receipts"),
    "get-finance-donators-donatorCoupleId": ("finance.donators", "get_receipts_for"),
    "post-finance-donators-receipts": ("finance.donators", "create_receipts"),
    "post-finance-donators-donatorCoupleId": ("finance.donators", "create_receipts_for"),
    "delete-finance-donators-receipts": ("finance.donators", "delete_receipts"),
    "delete-finance-donators-donatorCoupleId": ("finance.donators", "delete_latest_receipt_for"),
    # Images
    "get-images-fileId-hash": ("images", "get"),
    "get-images-fileId-hash-queryParams": ("images", "get_with_params"),
    # Notes
    "delete-notes-domainType-domainId-id": ("notes", "delete_for_object"),
    "delete-notes-noteId": ("notes", "delete"),
    # Permissions
    "get-permissions-internal-groups": ("permissions.internal.groups", "list"),
    "get-permissions-internal-groups-groupId": ("permissions.internal.groups", "get"),
    "get-permissions-permissionDomainType": ("permissions", "list_for_type"),
    "get-permissions-permissionDomainType-permissionDomainId": ("permissions", "list"),
    # Public groups
    "get-publicgroups-id": ("publicgroups", "get"),
    "get-publicgroups-id-hash": ("publicgroups", "get_with_hash"),
    "post-publicgroups-groupId-signup": ("publicgroups", "submit_signup"),
    # Subscriptions
    "get-subscriptions-personId": ("subscriptions", "list"),
    "get-subscriptions-personId-subject": ("subscriptions", "list_for_subject"),
    "get-subscriptions-personId-subject-subjectIdentifier": ("subscriptions", "get"),
    # Sync
    "post-sync-externalsystems-test": ("sync.externalsystems", "test_settings"),
    "post-sync-externalsystems-id-test": ("sync.externalsystems", "test"),
    # Tags: definitions (by tag ID) and tags attached to objects
    "get-tags-domainType": ("tags", "list"),
    "get-tags-domainType-domainId": ("tags", "list_for_object"),
    "get-tags-tagId": ("tags", "get"),
    "post-tags-domainType": ("tags", "create"),
    "post-tags-domainType-domainId": ("tags", "attach_new"),
    "put-tags-domainType-domainId-tagId": ("tags", "attach"),
    "put-tags-tagId": ("tags", "update"),
    "delete-tags-domainType-domainId-tagId": ("tags", "detach"),
    "delete-tags-tagId": ("tags", "delete"),
}


HTTP_METHODS = ("get", "post", "put", "patch", "delete")


# ---------------------------------------------------------------------------
# Type IR


@dataclass(frozen=True)
class T:
    kind: str  # any str int float bool date datetime list map model union opt
    inner: tuple = ()
    name: str = ""
    values: tuple = ()  # allowed values of a str or int enum


def enum_values(t: T) -> tuple:
    """Allowed values of `t`, also through Optional and List; empty if not an enum."""
    while t.kind in ("opt", "list"):
        t = t.inner[0]
    if t.kind == "union":
        return tuple(dict.fromkeys(v for m in t.inner for v in enum_values(m)))
    return t.values


def allowed_doc(t: T, limit: int = 30) -> str:
    """`Allowed values: ...` for docs, or empty."""
    values = enum_values(t)
    if not values:
        return ""
    shown = ", ".join(f"`{v}`" for v in values[:limit])
    return f"Allowed values: {shown}{', …' if len(values) > limit else ''}."


def with_allowed(doc: str, t: T) -> str:
    allowed = allowed_doc(t)
    return f"{doc}\n{allowed}" if doc and allowed else doc or allowed


ANY = T("any")


def opt(t: T) -> T:
    return t if t.kind in ("opt", "any") else T("opt", (t,))


def union(ts: list[T]) -> T:
    flat: list[T] = []
    nullable = False
    for t in ts:
        if t.kind == "opt":
            nullable, t = True, t.inner[0]
        if t.kind == "null":
            nullable = True
            continue
        for member in t.inner if t.kind == "union" else (t,):
            if member not in flat:
                flat.append(member)
    if any(t.kind == "any" for t in flat) or not flat:
        return ANY
    out = flat[0] if len(flat) == 1 else T("union", tuple(flat))
    return opt(out) if nullable else out


@dataclass
class Field_:
    json_name: str
    type: T
    required: bool
    doc: str
    deprecated: bool
    example: object = None


@dataclass
class Model:
    name: str
    doc: str
    fields: list[Field_] = field(default_factory=list)


class Schemas:
    def __init__(self, components: dict):
        self.component_by_canon: dict[str, str] = {}
        for name in sorted(components, key=lambda n: (len(n), n)):
            self.component_by_canon.setdefault(canon(components[name]), name)
        self.taken: set[str] = {pascal(n) for n in components}
        self.models: dict[str, Model] = {}
        self.model_by_canon: dict[str, str] = {}

    def type_of(self, s: dict | None, hint: str) -> T:
        if not s or not isinstance(s, dict):
            return ANY
        if is_object(s):
            return self.object_type(s, hint)

        nullable = s.get("nullable") is True
        types = s.get("type")
        if isinstance(types, list):
            nullable |= "null" in types
            types = [t for t in types if t != "null"]
            if len(types) != 1:
                return opt(union([prim(t, s) for t in types])) if nullable else union([prim(t, s) for t in types])
            types = types[0]

        for key in ("oneOf", "anyOf"):
            if key in s:
                members = [self.type_of(m, f"{hint}Variant{i + 1}") for i, m in enumerate(s[key])]
                t = union(members)
                return opt(t) if nullable else t
        if "allOf" in s:
            t = union([self.type_of(m, hint) for m in s["allOf"] if m.get("type") or m.get("enum")] or [ANY])
            return opt(t) if nullable else t
        if types is None and "enum" in s:
            values = [v for v in s["enum"] if v is not None]
            nullable |= None in s["enum"]
            types = "integer" if values and all(isinstance(v, int) for v in values) else "string"
        if types is None and "const" in s:
            types = {bool: "boolean", int: "integer", float: "number"}.get(type(s["const"]), "string")
        if types == "array":
            t = T("list", (self.type_of(s.get("items"), f"{hint}Item"),))
        elif types == "null":
            return T("null")
        else:
            t = prim(types, s)
            if isinstance(s.get("enum"), list) and t.kind in ("str", "int"):
                py = str if t.kind == "str" else int
                values = tuple(v for v in s["enum"] if type(v) is py)
                if values:
                    t = T(t.kind, values=tuple(dict.fromkeys(values)))
        if "enum" in s and None in s["enum"]:
            nullable = True
        return opt(t) if nullable else t

    def object_type(self, s: dict, hint: str) -> T:
        props, required, additional, doc, nullable = merge_object(s)
        if not props:
            value = self.type_of(additional, f"{hint}Value") if isinstance(additional, dict) else ANY
            t = T("map", (value,))
            return opt(t) if nullable else t
        key = canon(s)
        name = self.model_by_canon.get(key)
        if name is None:
            component = self.component_by_canon.get(key)
            name = pascal(component) if component else unique(pascal(hint), self.taken)
            self.model_by_canon[key] = name
            model = Model(name, clean_doc(doc))
            self.models[name] = model
            for prop, ps in props.items():
                ps = ps if isinstance(ps, dict) else {}
                fix = FIELD_FIXES.get((name, prop), {})
                ftype = ANY if fix.get("any") else self.type_of(ps, f"{name}{pascal(prop)}")
                model.fields.append(
                    Field_(
                        json_name=prop,
                        type=opt(ftype) if fix.get("nullable") else ftype,
                        # Deprecated fields are often listed as required but no longer sent.
                        required=prop in required and not ps.get("deprecated") and fix.get("required", True),
                        doc=clean_doc(ps.get("description")),
                        deprecated=bool(ps.get("deprecated")),
                        example=ps.get("example"),
                    )
                )
        t = T("model", name=name)
        return opt(t) if nullable else t


_canon_cache: dict[int, str] = {}


def canon(s) -> str:
    key = id(s)
    if key not in _canon_cache:
        _canon_cache[key] = json.dumps(s, sort_keys=True)
    return _canon_cache[key]


def prim(t: str | None, s: dict) -> T:
    if t == "string":
        fmt = s.get("format")
        return T("date") if fmt == "date" else T("datetime") if fmt == "date-time" else T("str")
    return {"integer": T("int"), "number": T("float"), "boolean": T("bool")}.get(t or "", ANY)


def is_object(s: dict) -> bool:
    t = s.get("type")
    if "properties" in s or t == "object" or (isinstance(t, list) and "object" in t):
        return True
    return "allOf" in s and any(isinstance(m, dict) and is_object(m) for m in s["allOf"])


def merge_object(s: dict):
    """Flattens allOf and returns (properties, required, additionalProperties, doc, nullable)."""
    props: dict = {}
    required: set = set()
    additional = s.get("additionalProperties")
    doc = s.get("description")
    t = s.get("type")
    nullable = isinstance(t, list) and "null" in t
    for member in s.get("allOf", []):
        if isinstance(member, dict) and is_object(member):
            p, r, a, d, _ = merge_object(member)
            props.update(p)
            required |= r
            additional = additional if additional is not None else a
            doc = doc or d
    props.update(s.get("properties", {}))
    required |= set(s.get("required", []))
    return props, required, additional, doc, nullable


# ---------------------------------------------------------------------------
# Operations


@dataclass
class Param:
    name: str  # wire name
    location: str  # path | query
    type: T
    required: bool
    doc: str
    example: object = None
    deprecated: bool = False


@dataclass
class Op:
    op_id: str
    method: str
    path: str
    summary: str
    doc: str
    params: list[Param]
    body: T | None
    body_model: Model | None  # body expanded into keyword arguments
    body_required: bool
    result: str  # data | json | bytes | none
    result_type: T | None
    paginated: bool
    deprecated: bool
    tags: list[str] = field(default_factory=list)
    content_type: str = ""  # for result == "bytes"
    # multipart/form-data upload: (name of the file field, other form fields)
    upload: tuple[str, list[Field_]] | None = None
    chain: tuple[str, ...] = ()
    name: str = ""


def collect_ops(spec: dict, schemas: Schemas) -> list[Op]:
    ops = []
    for path, item in spec["paths"].items():
        common = item.get("parameters", [])
        for method in HTTP_METHODS:
            o = item.get(method)
            if not o or (TAGS is not None and not TAGS & set(o.get("tags", []))):
                continue
            op_name = pascal(o["operationId"])
            params = []
            seen = set()
            for p in [*o.get("parameters", []), *common]:
                if p.get("in") not in ("path", "query") or (p["in"], p["name"]) in seen:
                    continue
                seen.add((p["in"], p["name"]))
                wire = p["name"]
                if p["in"] == "query" and p.get("schema", {}).get("type") == "array" and not wire.endswith("[]"):
                    # PHP only reads repeated keys as a list with brackets; without them
                    # it keeps the last value or rejects the request ("must be an array").
                    # 35 array parameters are documented without brackets.
                    wire += "[]"
                params.append(
                    Param(
                        name=wire,
                        location=p["in"],
                        type=schemas.type_of(p.get("schema"), f"{op_name}{pascal(p['name'])}"),
                        required=p.get("required", False) or p["in"] == "path",
                        doc=clean_doc(p.get("description") or p.get("schema", {}).get("description")),
                        example=p.get("example", p.get("schema", {}).get("example")),
                        deprecated=bool(p.get("deprecated")),
                    )
                )
            path_order = re.findall(r"{([^}]+)}", path)
            params.sort(key=lambda p: (p.location != "path", path_order.index(p.name) if p.name in path_order else 0))

            body = body_model = None
            body_required = False
            rb = o.get("requestBody", {})
            if "application/json" in rb.get("content", {}):
                bs = rb["content"]["application/json"].get("schema", {})
                body = schemas.type_of(bs, f"{op_name}Body")
                body_required = rb.get("required", False)
                base = body.inner[0] if body.kind == "opt" else body
                if base.kind == "model":
                    body_model = schemas.models[base.name]
            upload = None
            if "multipart/form-data" in rb.get("content", {}):
                props = rb["content"]["multipart/form-data"].get("schema", {}).get("properties", {})
                file_field = next(
                    k for k, v in props.items() if v.get("type") == "array" and v.get("items", {}).get("format") == "binary"
                )
                form = [
                    Field_(k, schemas.type_of(v, f"{op_name}Form{pascal(k)}"), False, clean_doc(v.get("description")), False, v.get("example"))
                    for k, v in props.items()
                    if k != file_field and not v.get("deprecated")
                ]
                upload = (file_field, form)

            result, result_type, content_type = "none", None, ""
            for code in ("200", "201", "202", "204"):
                resp = o.get("responses", {}).get(code)
                if resp is None:
                    continue
                content = resp.get("content", {})
                if "application/json" in content:
                    rs = content["application/json"].get("schema", {})
                    if "data" in rs.get("properties", {}):
                        result = "data"
                        result_type = schemas.type_of(rs["properties"]["data"], f"{op_name}Data")
                    else:
                        result = "json"
                        result_type = schemas.type_of(rs, f"{op_name}Response")
                elif content:
                    result = "bytes"
                    content_type = next(iter(content))
                break
            if "204" in o.get("responses", {}) and result in ("data", "json") and result_type is not None:
                # 200 with a body or 204 without one: the result can be absent.
                result_type = opt(result_type)
            fix = RESULT_FIXES.get(o["operationId"], {})
            if "result" in fix and result == "none":
                result = fix["result"]
            if fix.get("type") == "item" and result_type is not None and result_type.kind == "list":
                result_type = result_type.inner[0]
            elif "type" in fix:
                result_type = {"any": ANY, "List[int]": T("list", (T("int"),))}.get(fix["type"]) or T("model", name=fix["type"])
            if fix.get("envelope") and result == "json":
                result = "data"
            if fix.get("nullable") and result_type is not None:
                result_type = opt(result_type)

            query_names = {p.name for p in params if p.location == "query"}
            paginated = (
                method == "get"
                and "page" in query_names
                and result == "data"
                and result_type is not None
                and result_type.kind == "list"
            )
            ops.append(
                Op(
                    op_id=o["operationId"],
                    method=method,
                    path=path,
                    summary=clean_doc(o.get("summary")),
                    doc=clean_doc(o.get("description")),
                    params=params,
                    body=body,
                    body_model=body_model,
                    upload=upload,
                    body_required=body_required,
                    result=result,
                    result_type=result_type,
                    paginated=paginated,
                    deprecated=bool(o.get("deprecated")),
                    tags=o.get("tags", []),
                    content_type=content_type,
                )
            )
    assign_names(ops)
    return ops


def assign_names(ops: list[Op]) -> None:
    """Derives `client.<chain>.<name>` from the URL structure.

    Rules:
      * every static path segment becomes a resource (`/groups/{id}/meetings` ->
        groups.meetings); path parameters become method arguments
      * GET returns `list` for arrays, otherwise `get`; POST -> create,
        PUT -> update, PATCH -> patch, DELETE -> delete
      * a trailing segment without deeper paths is a leaf and becomes a method on
        its parent: GET /persons/{id}/groups -> persons.list_groups(id);
        a POST-only leaf is an action: POST /persons/{id}/invite -> persons.invite(id)
    """
    paths = {op.path for op in ops}
    methods_by_path: dict[str, set[str]] = {}
    for op in ops:
        methods_by_path.setdefault(op.path, set()).add(op.method)

    def static(path: str) -> list[str]:
        return [split_words(snake(s)) for s in path.strip("/").split("/") if s and not s.startswith("{")]

    for op in ops:
        if op.op_id in NAME_OVERRIDES:
            chain, op.name = NAME_OVERRIDES[op.op_id]
            op.chain = tuple(split_words(c) for c in chain.split("."))
            op.name = split_words(op.name)
            continue
        statics = static(op.path)
        last_is_param = op.path.rstrip("/").endswith("}")
        is_array = op.result_type is not None and (
            op.result_type.kind == "list" or (op.result_type.kind == "opt" and op.result_type.inner[0].kind == "list")
        )
        verb = {
            "get": "list" if is_array and not last_is_param else "get",
            "post": "create",
            "put": "update",
            "patch": "patch",
            "delete": "delete",
        }[op.method]
        prefix = op.path.rstrip("/")
        has_children = any(p != op.path and p.startswith(prefix + "/") for p in paths)
        if len(statics) >= 2 and not last_is_param and not has_children:
            leaf = statics[-1]
            op.chain = tuple(statics[:-1])
            if op.method == "post" and methods_by_path[op.path] == {"post"}:
                op.name = leaf
            else:
                op.name = f"{verb}_{leaf}"
        else:
            op.chain = tuple(statics)
            op.name = verb
    for op in ops:
        op.chain = tuple(keyword_safe(c) for c in op.chain)
        op.name = keyword_safe(op.name)


def check_names(ops: list[Op]) -> list[str]:
    problems = []
    by_key: dict[tuple, list[Op]] = {}
    for op in ops:
        by_key.setdefault((op.chain, op.name), []).append(op)
    for (chain, name), group in by_key.items():
        if len(group) > 1:
            problems.append(
                f"{'.'.join(chain)}.{name}: " + ", ".join(f"{o.method.upper()} {o.path} ({o.op_id})" for o in group)
            )
    chains = {op.chain[:i] for op in ops for i in range(1, len(op.chain) + 1)}
    for op in ops:
        if (*op.chain, op.name) in chains:
            problems.append(f"{'.'.join(op.chain)}.{op.name} is both a method and a sub-resource")
    return problems


def field_names(model: Model, ident, taken: set[str]) -> list[str]:
    """Like `ident` per field, but a field whose JSON name already is that identifier
    keeps it on collision (`event_services` beats the legacy `eventServices`)."""
    names: list[str | None] = [None] * len(model.fields)
    exact = [i for i, f in enumerate(model.fields) if ident(f.json_name).removeprefix("r#") == f.json_name]
    rest = [i for i in range(len(model.fields)) if i not in exact]
    for i in exact + rest:
        names[i] = unique(ident(model.fields[i].json_name), taken)
    return names  # type: ignore[return-value]


def resource_class(chain: tuple[str, ...]) -> str:
    return "".join(pascal(c) for c in chain) + "Resource"


def deprecation_hint(doc: str) -> str:
    """The sentence of a description that names the replacement, e.g. "Use `format`"."""
    m = re.search(r"(?:^|(?<=[.!?]\s))((?:Use|Please use|Replaced by)\b[^.!?]*[.!?]?)", " ".join(doc.split()))
    return m.group(1) if m else ""


def deprecation_message(op: Op) -> str:
    hint = deprecation_hint(op.doc)
    return f"{op.method.upper()} {op.path} is deprecated in the ChurchTools API." + (f" {hint}" if hint else "")


def deprecated_doc(doc: str, deprecated: bool) -> str:
    return f"Deprecated. {doc}".rstrip() if deprecated else doc


QUERY_SCALARS = ("str", "int", "float", "bool", "date", "datetime")
