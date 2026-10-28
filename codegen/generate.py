#!/usr/bin/env python3
"""Generates the ChurchTools client from the OpenAPI spec.

Outputs:
  core/src/generated/{mod,models,api}.rs      Rust models and endpoints
  python/churchtools_rs/models.py             Pydantic models
  python/churchtools_rs/_resources.py         Python endpoints
  codegen/OPERATIONS.md                       Python method <-> HTTP operation

The ChurchTools spec inlines every schema instead of using `$ref`. Each inline
copy is byte-identical to an entry in `components.schemas`, so we recover the
names by comparing canonical JSON.

Usage: python3 codegen/generate.py [--spec PATH] [--refresh]
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
import textwrap
import typing as _t
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "codegen" / ".cache" / "openapi.json"
SPEC_URL = "https://demo.church.tools/system/runtime/swagger/openapi.json"
INFO_URL = "https://demo.church.tools/api/info"

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
# Naming helpers


def pascal(s: str) -> str:
    parts = re.split(r"[^0-9A-Za-z]+", s)
    out = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return out if out and not out[0].isdigit() else f"T{out}"


def snake(s: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = s.strip("_").lower()
    if not s:
        s = "field"
    if s[0].isdigit():
        s = f"f_{s}"
    return s


PY_RESERVED = set(keyword.kwlist) | set(keyword.softkwlist)
try:
    from pydantic import BaseModel as _BM

    PY_RESERVED |= {n for n in dir(_BM) if not n.startswith("_")}
except ImportError:  # pragma: no cover
    PY_RESERVED |= {"json", "dict", "copy", "schema", "construct", "validate"}
PY_RESERVED |= {"model_config", "model_extra", "model_fields"}

RUST_KEYWORDS = {
    "as", "break", "const", "continue", "crate", "else", "enum", "extern", "false", "fn",
    "for", "if", "impl", "in", "let", "loop", "match", "mod", "move", "mut", "pub", "ref",
    "return", "self", "Self", "static", "struct", "super", "trait", "true", "type", "unsafe",
    "use", "where", "while", "async", "await", "dyn", "abstract", "become", "box", "do",
    "final", "macro", "override", "priv", "typeof", "unsized", "virtual", "yield", "try", "gen",
}
RUST_NOT_RAW = {"self", "Self", "super", "crate"}


def py_ident(s: str) -> str:
    name = snake(s)
    return f"{name}_" if name in PY_RESERVED or keyword.iskeyword(name) else name


def rust_ident(s: str) -> str:
    name = snake(s)
    if name in RUST_NOT_RAW:
        return f"{name}_"
    return f"r#{name}" if name in RUST_KEYWORDS else name


def unique(name: str, taken: set[str]) -> str:
    candidate, i = name, 2
    while candidate in taken:
        candidate = f"{name}_{i}" if name[-1].isdigit() or "_" in name else f"{name}{i}"
        i += 1
    taken.add(candidate)
    return candidate


def clean_doc(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("```", "`` `").strip()


# ---------------------------------------------------------------------------
# Type IR


@dataclass(frozen=True)
class T:
    kind: str  # any str int float bool date datetime list map model union opt
    inner: tuple = ()
    name: str = ""


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
        if t.kind == "union":
            flat.extend(t.inner)
        elif t not in flat:
            flat.append(t)
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
        return [snake(s) for s in path.strip("/").split("/") if s and not s.startswith("{")]

    for op in ops:
        if op.op_id in NAME_OVERRIDES:
            chain, op.name = NAME_OVERRIDES[op.op_id]
            op.chain = tuple(chain.split("."))
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


def keyword_safe(name: str) -> str:
    """Resource and method names are shared by Python and Rust, so avoid both keyword sets."""
    return f"{name}_" if keyword.iskeyword(name) or name in RUST_KEYWORDS else name


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


# ---------------------------------------------------------------------------
# Python output


def py_type(t: T, quote_models: bool = True) -> str:
    k = t.kind
    if k == "any":
        return "_t.Any"
    if k in ("str", "int", "float", "bool"):
        return k
    if k == "date":
        return "_dt.date"
    if k == "datetime":
        return "_dt.datetime"
    if k == "list":
        return f"_t.List[{py_type(t.inner[0], quote_models)}]"
    if k == "map":
        return f"StrMap[{py_type(t.inner[0], quote_models)}]"
    if k == "model":
        return t.name
    if k == "union":
        return f"_t.Union[{', '.join(py_type(i, quote_models) for i in t.inner)}]"
    if k == "opt":
        return f"_t.Optional[{py_type(t.inner[0], quote_models)}]"
    if k == "null":
        return "None"
    raise ValueError(k)


def py_docstring(text: str, indent: str) -> str:
    if not text:
        return ""
    text = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    lines = text.splitlines()
    if len(lines) == 1 and len(text) < 90:
        return f'{indent}"""{text}"""\n'
    body = "\n".join(f"{indent}{line}".rstrip() for line in lines)
    return f'{indent}"""\n{body}\n{indent}"""\n'


def field_names(model: Model, ident, taken: set[str]) -> list[str]:
    """Like `ident` per field, but a field whose JSON name already is that identifier
    keeps it on collision (`event_services` beats the legacy `eventServices`)."""
    names: list[str | None] = [None] * len(model.fields)
    exact = [i for i, f in enumerate(model.fields) if ident(f.json_name).removeprefix("r#") == f.json_name]
    rest = [i for i in range(len(model.fields)) if i not in exact]
    for i in exact + rest:
        names[i] = unique(ident(model.fields[i].json_name), taken)
    return names  # type: ignore[return-value]


def py_field_names(model: Model) -> list[str]:
    return field_names(model, py_ident, set())


def write_python_models(schemas: Schemas, header: str, out: Path) -> None:
    lines = [
        f'"""Pydantic models for the ChurchTools API.\n\n{header}\n"""\n',
        "from __future__ import annotations\n",
        "import datetime as _dt",
        "import typing as _t\n",
        "from pydantic import Field\n",
        "from ._base import CTModel, OptionalDateTime, StrMap\n",
    ]
    names = sorted(schemas.models)
    lines.append(f"__all__ = {names!r}\n")
    for name in names:
        model = schemas.models[name]
        lines.append(f"\nclass {name}(CTModel):")
        lines.append(py_docstring(model.doc, "    ").rstrip("\n") or '    """"""')
        for f, attr in zip(model.fields, py_field_names(model)):
            ann = py_type(f.type)
            required = f.required and f.type.kind not in ("opt", "any")
            if not required and f.type.kind not in ("opt", "any"):
                ann = f"_t.Optional[{ann}]"
            if ann == "_t.Optional[_dt.datetime]":
                ann = "OptionalDateTime"  # tolerates the PHP zero date
            args = []
            if not required:
                args.append("default=None")
            if attr != f.json_name:
                # Not `alias=`: type checkers would then expect the JSON name in constructors.
                args.append(f"validation_alias={f.json_name!r}, serialization_alias={f.json_name!r}")
            if f.deprecated:
                args.append("deprecated=True")
            value = f" = Field({', '.join(args)})" if args else ""
            lines.append(f"    {attr}: {ann}{value}")
            if f.doc:
                lines.append(py_docstring(f.doc, "    ").rstrip("\n"))
    out.write_text("\n".join(lines) + "\n")


def resource_class(chain: tuple[str, ...]) -> str:
    return "".join(pascal(c) for c in chain) + "Resource"


def write_python_resources(ops: list[Op], header: str, out: Path) -> None:
    chains: set[tuple[str, ...]] = set()
    for op in ops:
        for i in range(1, len(op.chain) + 1):
            chains.add(op.chain[:i])
    lines = [
        f'"""Generated endpoint wrappers.\n\n{header}\n"""\n',
        "from __future__ import annotations\n",
        "import datetime as _dt",
        "import typing as _t\n",
        "from . import models",
        "from ._base import UNSET, Paginator, Resource, StrMap, UnsetType, Upload, _body, _query, _seg\n",
    ]
    by_chain: dict[tuple, list[Op]] = {}
    for op in ops:
        by_chain.setdefault(op.chain, []).append(op)

    for chain in sorted(chains, key=lambda c: (-len(c), c)):
        children = sorted(c for c in chains if len(c) == len(chain) + 1 and c[:-1] == chain)
        lines.append(f"\nclass {resource_class(chain)}(Resource):")
        lines.append(f'    """`client.{".".join(chain)}`"""\n')
        if children:
            lines.append("    def __init__(self, core: _t.Any) -> None:")
            lines.append("        super().__init__(core)")
            for c in children:
                lines.append(f"        self.{c[-1]} = {resource_class(c)}(core)")
            lines.append("")
        for op in sorted(by_chain.get(chain, []), key=lambda o: o.name):
            lines.extend(python_method(op))
    roots = sorted(c for c in chains if len(c) == 1)
    lines.append("\nclass Resources:")
    lines.append('    """All generated resources; mixed into `Client`."""\n')
    lines.append("    def __init__(self, core: _t.Any) -> None:")
    for c in roots:
        lines.append(f"        self.{c[0]} = {resource_class(c)}(core)")
    out.write_text("\n".join(lines) + "\n")


def model_type_for_resources(t: T) -> str:
    """Python annotation inside _resources.py, where models live in `models.`."""
    s = py_type(t)
    return re.sub(r"(?<![\w.])([A-Z]\w*)", lambda m: m.group(1) if m.group(1) in ("None", "StrMap") else f"models.{m.group(1)}", s)


@dataclass
class PyParam:
    kind: str  # path | query | field (body property as keyword) | body (whole body)
    wire: str  # name in URL/query/JSON
    py: str  # Python argument name
    type: T
    required: bool
    doc: str
    example: object = None


def python_params(op: Op) -> list[PyParam]:
    """Arguments of the generated Python method, in signature order before sorting."""
    taken: set[str] = {"self"}
    out = []
    for p in op.params:
        if p.location == "query" and op.paginated and p.name == "page":
            continue
        out.append(PyParam(p.location, p.name, unique(py_ident(p.name), taken), p.type, p.required, p.doc, p.example))
    if op.body_model is not None:
        for f, attr in zip(op.body_model.fields, py_field_names(op.body_model)):
            out.append(
                PyParam("field", f.json_name, unique(attr, taken), f.type, f.required and op.body_required, f.doc, f.example)
            )
    elif op.body is not None:
        out.append(PyParam("body", "", "body", op.body, op.body_required, ""))
    if op.upload is not None:
        file_field, form = op.upload
        out.append(PyParam("upload", file_field, unique("files", taken), ANY, True, "Files to upload."))
        for f in form:
            out.append(PyParam("form", f.json_name, unique(py_ident(f.json_name), taken), f.type, False, f.doc, f.example))
    return out


def python_method(op: Op) -> list[str]:
    sig_pos, sig_kw, doc_args = [], [], []
    path_expr = op.path
    query_items = []
    form_items = []
    upload_expr = ""
    pairs = []
    body_expr = "None"
    for p in python_params(op):
        ann = model_type_for_resources(p.type)
        if p.kind == "path":
            sig_pos.append(f"{p.py}: {ann}")
            path_expr = path_expr.replace("{" + p.wire + "}", "{_seg(" + p.py + ")}")
        elif p.kind == "query":
            if p.required:
                sig_kw.append((0, f"{p.py}: {ann}"))
            else:
                base = ann if ann.startswith("_t.Optional[") or ann == "_t.Any" else f"_t.Optional[{ann}]"
                sig_kw.append((1, f"{p.py}: {base} = None"))
            query_items.append(f"({p.wire!r}, {p.py})")
        elif p.kind == "upload":
            sig_kw.append((0, f"{p.py}: _t.Sequence[Upload]"))
            upload_expr = p.py
        elif p.kind == "form":
            sig_kw.append((1, f"{p.py}: {ann if ann.startswith('_t.Optional[') else f'_t.Optional[{ann}]'} = None"))
            form_items.append(f"({p.wire!r}, {p.py})")
        elif p.kind == "field":
            if p.required:
                sig_kw.append((0, f"{p.py}: {ann}"))
            else:
                sig_kw.append((1, f"{p.py}: _t.Union[{ann}, UnsetType] = UNSET"))
            pairs.append(f"{p.wire!r}: {p.py}")
        else:
            if p.required:
                sig_kw.append((0, f"body: {ann}"))
            else:
                sig_kw.append((1, f"body: _t.Optional[{ann}] = None"))
            body_expr = "_body(body)"
        if p.doc:
            doc_args.append((p.py, p.doc))
    if op.body_model is not None:
        sig_kw.append((1, "extra_body: _t.Optional[_t.Dict[str, _t.Any]] = None"))
        body_expr = "_body({" + ", ".join(pairs) + "}, extra_body)"

    kw = [s for _, s in sorted(sig_kw, key=lambda x: x[0])]
    params = ["self", *sig_pos] + (["*", *kw] if kw else [])

    if op.result == "data" or op.result == "json":
        rt = model_type_for_resources(op.result_type)
        ret = f"Paginator[{model_type_for_resources(op.result_type.inner[0])}]" if op.paginated else rt
    elif op.result == "bytes":
        ret = "bytes"
    else:
        ret = "None"

    doc_lines = [op.summary or op.op_id, "", f"`{op.method.upper()} {op.path}`"]
    if op.deprecated:
        doc_lines.append("\nDeprecated.")
    if op.doc and op.doc != op.summary:
        doc_lines += ["", op.doc]
    if doc_args:
        doc_lines += ["", "Args:"]
        for name, d in doc_args:
            first, *rest = d.splitlines() or [""]
            doc_lines.append(f"    {name}: {first}")
            doc_lines += [f"        {r}" for r in rest]
    example = EXAMPLES.get(op.op_id)
    if example is not None:
        doc_lines += ["", "Example::", ""] + [f"    {line}" if line else "" for line in example.python.splitlines()]

    out = [f"    def {op.name}("]
    out += [f"        {p}," for p in params]
    out.append(f"    ) -> {ret}:")
    out.append(py_docstring("\n".join(doc_lines), "        ").rstrip("\n"))
    q = "_query([" + ", ".join(query_items) + "])" if query_items else "[]"
    upload_kw = ""
    if upload_expr:
        form_q = "_query([" + ", ".join(form_items) + "])" if form_items else "[]"
        upload_kw = f", upload=({op.upload[0]!r}, {form_q}, {upload_expr})"
    path_lit = f'f"{path_expr}"' if "{" in path_expr else f'"{path_expr}"'
    if op.paginated:
        item = model_type_for_resources(op.result_type.inner[0])
        out.append(f"        return Paginator(self._core, {path_lit}, {q}, {item})")
    elif op.result in ("data", "json"):
        rt = model_type_for_resources(op.result_type)
        out.append(
            f"        return _t.cast({rt}, self._call({op.method.upper()!r}, {path_lit}, {q}, {body_expr}, "
            f"{rt}, envelope={op.result == 'data'}{upload_kw}))"
        )
    elif op.result == "bytes":
        out.append(f"        return self._raw({op.method.upper()!r}, {path_lit}, {q}, {body_expr}{upload_kw})")
    else:
        out.append(f"        self._raw({op.method.upper()!r}, {path_lit}, {q}, {body_expr}{upload_kw})")
    out.append("")
    return out


# ---------------------------------------------------------------------------
# Rust output


DATE_OR_DATETIME = {T("date"), T("datetime")}


def rust_type(t: T, boxed: bool = False, prefix: str = "") -> str:
    """`prefix` qualifies model names, e.g. `models::` inside api.rs."""
    k = t.kind
    if k == "union" and set(t.inner) == DATE_OR_DATETIME:
        return "crate::DateOrDateTime"
    if k in ("any", "union", "null"):
        return "serde_json::Value"
    if k == "str":
        return "String"
    if k == "int":
        return "i64"
    if k == "float":
        return "f64"
    if k == "bool":
        return "bool"
    if k == "date":
        return "chrono::NaiveDate"
    if k == "datetime":
        return "chrono::DateTime<chrono::Utc>"
    if k == "list":
        return f"Vec<{rust_type(t.inner[0], prefix=prefix)}>"
    if k == "map":
        return f"std::collections::BTreeMap<String, {rust_type(t.inner[0], prefix=prefix)}>"
    if k == "model":
        return f"Box<{prefix}{t.name}>" if boxed else f"{prefix}{t.name}"
    if k == "opt":
        inner = t.inner[0]
        if inner.kind == "any" or (inner.kind == "union" and set(inner.inner) != DATE_OR_DATETIME):
            return "serde_json::Value"
        return f"Option<{rust_type(inner, boxed, prefix)}>"
    raise ValueError(k)


def rust_doc(text: str, indent: str) -> list[str]:
    return [f"{indent}///{(' ' + line) if line else ''}".rstrip() for line in text.splitlines()]


def direct_refs(model: Model) -> set[str]:
    """Models embedded without indirection (not inside Vec/Map)."""
    refs = set()
    for f in model.fields:
        t = f.type.inner[0] if f.type.kind == "opt" else f.type
        if t.kind == "model":
            refs.add(t.name)
    return refs


def write_rust_models(schemas: Schemas, header: str, out: Path) -> None:
    graph = {n: direct_refs(m) for n, m in schemas.models.items()}

    def reaches(start: str, target: str) -> bool:
        stack, seen = [start], set()
        while stack:
            n = stack.pop()
            if n == target:
                return True
            if n not in seen:
                seen.add(n)
                stack.extend(graph.get(n, ()))
        return False

    lines = [f"//! Generated ChurchTools models.\n//!\n//! {header}\n", "#![allow(clippy::all, rustdoc::all, deprecated)]\n",
             "use serde::{Deserialize, Serialize};\n"]
    for name in sorted(schemas.models):
        model = schemas.models[name]
        lines += rust_doc(model.doc, "")
        lines.append("#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]")
        lines.append(f"pub struct {name} {{")
        for f, ident in zip(model.fields, field_names(model, rust_ident, {"extra"})):
            base = f.type.inner[0] if f.type.kind == "opt" else f.type
            boxed = base.kind == "model" and reaches(base.name, name)
            ty = rust_type(f.type, boxed)
            optional = not f.required or f.type.kind == "opt"
            if optional and not ty.startswith("Option<") and ty != "serde_json::Value":
                ty = f"Option<{ty}>"
            lines += rust_doc(f.doc, "    ")
            attrs = []
            if ident.removeprefix("r#") != f.json_name:
                attrs.append(f'rename = "{f.json_name}"')
            if ty == "String":
                attrs.append('deserialize_with = "crate::lenient::string"')
            elif ty == "Option<String>":
                attrs.append('deserialize_with = "crate::lenient::opt_string"')
            elif ty in ("i64", "f64"):
                attrs.append('deserialize_with = "crate::lenient::number"')
            elif ty in ("Option<i64>", "Option<f64>"):
                attrs.append('deserialize_with = "crate::lenient::opt_number"')
            elif ty == "chrono::DateTime<chrono::Utc>":
                attrs.append('serialize_with = "crate::datetime::serialize_utc"')
            elif ty.startswith("std::collections::BTreeMap<"):
                attrs.append('deserialize_with = "crate::lenient::map"')
            elif ty.startswith("Option<std::collections::BTreeMap<"):
                attrs.append('deserialize_with = "crate::lenient::opt_map"')
            elif ty == "Option<chrono::DateTime<chrono::Utc>>":
                attrs.append('deserialize_with = "crate::lenient::opt_datetime"')
                attrs.append('serialize_with = "crate::datetime::serialize_opt_utc"')
            if ty.startswith("Option<"):
                attrs += ["default", 'skip_serializing_if = "Option::is_none"']
            elif ty == "serde_json::Value":
                attrs += ["default", 'skip_serializing_if = "serde_json::Value::is_null"']
            if attrs:
                lines.append(f"    #[serde({', '.join(attrs)})]")
            if f.deprecated:
                lines.append("    #[deprecated]")
            lines.append(f"    pub {ident}: {ty},")
        lines.append("    /// Fields not described by the spec, e.g. instance-specific DB fields.")
        lines.append("    #[serde(flatten)]")
        lines.append("    pub extra: serde_json::Map<String, serde_json::Value>,")
        lines.append("}\n")
    out.write_text("\n".join(lines))


QUERY_SCALARS = ("str", "int", "float", "bool", "date", "datetime")


def rust_param_type(t: T) -> str:
    """Query values must implement ToQuery; anything structured is passed as JSON."""
    base = t.inner[0] if t.kind == "opt" else t
    if base.kind in QUERY_SCALARS or (base.kind == "list" and base.inner[0].kind in QUERY_SCALARS):
        return rust_type(base)
    return "serde_json::Value"


def write_rust_api(ops: list[Op], header: str, out: Path) -> None:
    chains: set[tuple[str, ...]] = set()
    for op in ops:
        for i in range(1, len(op.chain) + 1):
            chains.add(op.chain[:i])
    by_chain: dict[tuple, list[Op]] = {}
    for op in ops:
        by_chain.setdefault(op.chain, []).append(op)

    lines = [
        f"//! Generated ChurchTools endpoints.\n//!\n//! {header}\n",
        "#![allow(clippy::all, rustdoc::all, deprecated, unused_mut)]\n",
        "use std::fmt::Display;\n",
        "use reqwest::Method;\n",
        "use super::models;",
        "use crate::client::{Client, Query, Upload, encode_path_segment as seg};",
        "use crate::error::Result;",
        "use crate::query::ToQuery;\n",
        "impl Client {",
    ]
    for c in sorted(c for c in chains if len(c) == 1):
        lines.append(f"    pub fn {rust_ident(c[0])}(&self) -> {resource_class(c)}<'_> {{")
        lines.append(f"        {resource_class(c)} {{ client: self }}")
        lines.append("    }")
    lines.append("}\n")

    for chain in sorted(chains):
        names = [op.name for op in by_chain.get(chain, [])]
        clash = {f"{n}_with" for n in names} & set(names)
        assert not clash, f"Rust method name clash in {chain}: {clash}"
        cls = resource_class(chain)
        lines.append(f"/// `client.{'().'.join(chain)}()`")
        lines.append("#[derive(Clone, Copy)]")
        lines.append(f"pub struct {cls}<'a> {{\n    client: &'a Client,\n}}\n")
        lines.append(f"impl<'a> {cls}<'a> {{")
        for c in sorted(c for c in chains if len(c) == len(chain) + 1 and c[:-1] == chain):
            lines.append(f"    pub fn {rust_ident(c[-1])}(&self) -> {resource_class(c)}<'a> {{")
            lines.append(f"        {resource_class(c)} {{ client: self.client }}")
            lines.append("    }\n")
        query_structs = []
        for op in sorted(by_chain.get(chain, []), key=lambda o: o.name):
            m, qs = rust_method(op)
            lines += m
            if qs:
                query_structs += qs
        lines.append("}\n")
        lines += query_structs
    out.write_text("\n".join(lines))


def rust_doctest(op: Op) -> list[str]:
    """The documentation example as a doctest: run against the recorded response if
    there is one (`replay` feature), otherwise only compiled."""
    example = EXAMPLES.get(op.op_id)
    if example is None:
        return []
    runs = op.op_id in RECORDED and op.upload is None
    client = (
        f'# let client = churchtools_core::replay::client("{op.op_id}");'
        if runs
        else '# let client = Client::new("https://meinegemeinde.church.tools", None)?;'
    )
    return [
        "",
        "# Example",
        "",
        "```" if runs else "```no_run",
        "# use churchtools_core::*;",
        "# fn main() -> std::result::Result<(), Box<dyn std::error::Error>> {",
        client,
        *example.rust.splitlines(),
        "# Ok(())",
        "# }",
        "```",
    ]


def rust_method(op: Op) -> tuple[list[str], list[str]]:
    args = ["&self"]
    path_fmt = op.path
    path_args = []
    taken: set[str] = set()
    for p in op.params:
        if p.location == "path":
            ident = unique(rust_ident(p.name), taken)
            args.append(f"{ident}: impl Display")
            path_fmt = path_fmt.replace("{" + p.name + "}", "{}")
            path_args.append(f"seg({ident})")
    query_params = [p for p in op.params if p.location == "query" and not (op.paginated and p.name == "page")]
    query_struct = None
    struct_lines: list[str] = []
    forward = [a.split(":")[0] for a in args[1:]]  # path argument names
    if query_params:
        query_struct = pascal(op.op_id) + "Query"
        args.append(f"query: &{query_struct}")
        struct_lines.append(f"/// Query parameters for `{op.method.upper()} {op.path}`.")
        struct_lines.append("#[derive(Debug, Clone, Default)]")
        struct_lines.append(f"pub struct {query_struct} {{")
        qtaken: set[str] = set()
        idents = []
        for p in query_params:
            ident = unique(rust_ident(p.name), qtaken)
            idents.append((ident, p))
            struct_lines += rust_doc(p.doc, "    ")
            struct_lines.append(f"    pub {ident}: Option<{rust_param_type(p.type)}>,")
        struct_lines.append("}\n")
        struct_lines.append(f"impl {query_struct} {{")
        struct_lines.append("    fn to_query(&self) -> Query {")
        struct_lines.append("        let mut q = Query::new();")
        for ident, p in idents:
            struct_lines.append(f'        self.{ident}.push_query("{p.name}", &mut q);')
        struct_lines.append("        q")
        struct_lines.append("    }")
        struct_lines.append("}\n")
    if op.body is not None:
        base = op.body.inner[0] if op.body.kind == "opt" else op.body
        bty = f"models::{base.name}" if base.kind == "model" else "serde_json::Value"
        args.append(f"body: &{bty}")
    form_struct = None
    if op.upload is not None:
        args.append("files: &[Upload]")
        forward.append("files")
        file_field, form = op.upload
        if form:
            form_struct = pascal(op.op_id) + "Form"
            args.append(f"form: &{form_struct}")
            struct_lines.append(f"/// Form fields for `{op.method.upper()} {op.path}` besides the files.")
            struct_lines.append("#[derive(Debug, Clone, Default)]")
            struct_lines.append(f"pub struct {form_struct} {{")
            ftaken: set[str] = set()
            fidents = []
            for f in form:
                ident = unique(rust_ident(snake(f.json_name)), ftaken)
                fidents.append((ident, f))
                struct_lines += rust_doc(f.doc, "    ")
                struct_lines.append(f"    pub {ident}: Option<{rust_param_type(f.type)}>,")
            struct_lines.append("}\n")
            struct_lines.append(f"impl {form_struct} {{")
            struct_lines.append("    fn to_query(&self) -> Query {")
            struct_lines.append("        let mut q = Query::new();")
            for ident, f in fidents:
                struct_lines.append(f'        self.{ident}.push_query("{f.json_name}", &mut q);')
            struct_lines.append("        q")
            struct_lines.append("    }")
            struct_lines.append("}\n")

    if op.result in ("data", "json") and op.result_type is not None:
        rt = rust_type(op.result_type, prefix="models::")
    elif op.result == "bytes":
        rt = "Vec<u8>"
    else:
        rt = "()"

    doc = [op.summary or op.op_id, "", f"`{op.method.upper()} {op.path}`"]
    if op.doc and op.doc != op.summary:
        doc += ["", op.doc]
    example_doc = rust_doctest(op)
    lines = []
    name = rust_ident(op.name)
    options = "form" if form_struct else "query" if query_struct else None
    if options and not any(p.required for p in query_params):
        # All filters optional: `list()` for the common case, `list_with(&query)` for filters.
        simple_args = [a for a in args if not a.startswith(f"{options}:")]
        lines += rust_doc("\n".join(doc + ["", f"Use [`Self::{op.name}_with`] to pass query parameters."] + example_doc), "    ")
        example_doc = []  # the example stays on the short variant
        if op.deprecated:
            lines.append("    #[deprecated]")
        lines.append(f"    pub fn {name}({', '.join(simple_args)}) -> Result<{rt}> {{")
        call_args = [*forward, *(["body"] if op.body is not None else []), "&Default::default()"]
        if options == "query":
            # The query struct comes before body and files.
            call_args = [*[a for a in forward if a != "files"], "&Default::default()",
                         *(["body"] if op.body is not None else []), *(["files"] if "files" in forward else [])]
        lines.append(f"        self.{op.name}_with({', '.join(call_args)})")
        lines.append("    }\n")
        name = f"{op.name}_with"
        doc = doc[:1] + ["", f"Like [`Self::{op.name}`], with {'form fields' if options == 'form' else 'query parameters'}."] + doc[1:]
    lines += rust_doc("\n".join(doc + example_doc), "    ")
    if op.deprecated:
        lines.append("    #[deprecated]")
    lines.append(f"    pub fn {name}({', '.join(args)}) -> Result<{rt}> {{")
    path = f'format!("{path_fmt}", {", ".join(path_args)})' if path_args else f'"{path_fmt}".to_owned()'
    lines.append(f"        let path = {path};")
    lines.append(f"        let query: Query = {'query.to_query()' if query_struct else 'Query::new()'};")
    if op.body is not None:
        lines.append("        let body = serde_json::to_value(body).expect(\"request body serializes\");")
        body = "Some(&body)"
    else:
        body = "None"
    method = f"Method::{op.method.upper()}"
    if op.upload is not None:
        form_expr = "form.to_query()" if form_struct else "Query::new()"
        lines.append(f"        let form: Query = {form_expr};")
        lines.append(
            f'        let bytes = self.client.request_multipart({method}, &path, &query, &form, "{op.upload[0]}", files)?;'
        )
        if op.result == "data":
            lines.append("        crate::decode_data(&bytes)")
        elif op.result == "json":
            lines.append("        crate::decode(&bytes)")
        elif op.result == "bytes":
            lines.append("        Ok(bytes)")
        else:
            lines.append("        Ok(())")
        lines.append("    }\n")
        return lines, struct_lines
    if op.paginated:
        lines.append("        self.client.collect_pages(&path, query)")
    elif op.result == "data":
        lines.append(f"        self.client.request_data({method}, &path, &query, {body})")
    elif op.result == "json":
        lines.append(f"        self.client.request_json({method}, &path, &query, {body})")
    elif op.result == "bytes":
        lines.append(f"        self.client.request({method}, &path, &query, {body})")
    else:
        lines.append(f"        self.client.request({method}, &path, &query, {body}).map(|_| ())")
    lines.append("    }\n")
    return lines, struct_lines


# ---------------------------------------------------------------------------


def write_operations_md(ops: list[Op], header: str, out: Path) -> None:
    lines = [
        "# Generierte Operationen\n",
        f"{header}\n",
        "| Python | HTTP | Beschreibung |",
        "|---|---|---|",
    ]
    for op in sorted(ops, key=lambda o: (o.chain, o.name)):
        path_args = [py_ident(p.name) for p in op.params if p.location == "path"]
        call = f"client.{'.'.join(op.chain)}.{op.name}({', '.join(path_args)})"
        flag = " (paginiert)" if op.paginated else ""
        lines.append(f"| `{call}`{flag} | `{op.method.upper()} {op.path}` | {op.summary.replace('|', '/')} |")
    out.write_text("\n".join(lines) + "\n")


def load_spec(path: str | None, refresh: bool) -> tuple[dict, str]:
    if path:
        return json.loads(Path(path).read_text()), "custom spec"
    if refresh or not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {SPEC_URL} ...", file=sys.stderr)
        urllib.request.urlretrieve(SPEC_URL, CACHE)
        info = json.load(urllib.request.urlopen(INFO_URL))
        (CACHE.parent / "info.json").write_text(json.dumps(info))
    info_path = CACHE.parent / "info.json"
    version = "unknown"
    if info_path.exists():
        info = json.loads(info_path.read_text())
        version = f"ChurchTools {info.get('version')} (build {info.get('build')})"
    return json.loads(CACHE.read_text()), version


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    spec, version = load_spec(args.spec, args.refresh)
    header = f"Generated by codegen/generate.py from the OpenAPI spec of {version}. Do not edit."
    schemas = Schemas(spec["components"]["schemas"])
    ops = collect_ops(spec, schemas)
    problems = check_names(ops)
    if problems:
        print("Name conflicts (add NAME_OVERRIDES):", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1

    import examples as ex

    EXAMPLES.update({op.op_id: ex.example_for(schemas, op) for op in ops})
    RECORDED.update(p.stem for p in (ROOT / "fixtures" / "recorded").glob("*.json"))

    py_pkg = ROOT / "python" / "churchtools_rs"
    rs_gen = ROOT / "core" / "src" / "generated"
    rs_gen.mkdir(parents=True, exist_ok=True)
    write_python_models(schemas, header, py_pkg / "models.py")
    write_python_resources(ops, header, py_pkg / "_resources.py")
    write_rust_models(schemas, header, rs_gen / "models.rs")
    write_rust_api(ops, header, rs_gen / "api.rs")
    (rs_gen / "mod.rs").write_text(f"//! {header}\n\npub mod api;\npub mod models;\n")
    write_operations_md(ops, header, ROOT / "codegen" / "OPERATIONS.md")
    import docs  # imports this module, so only after everything above is defined
    import testgen

    testgen.write(spec, ops, header)

    checked = docs.build(schemas, ops, version)
    print(f"{len(ops)} operations, {len(schemas.models)} models, {len(checked)} doc examples", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
