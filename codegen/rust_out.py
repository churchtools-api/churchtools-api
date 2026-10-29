"""Rust output: serde models, resources with one method per endpoint, query structs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from naming import (
    pascal,
    rust_ident,
    snake,
    unique,
)
from spec import (
    EXAMPLES,
    QUERY_SCALARS,
    RECORDED,
    Field_,
    Model,
    Op,
    Schemas,
    T,
    deprecated_doc,
    deprecation_hint,
    deprecation_message,
    field_names,
    resource_class,
    with_allowed,
)

# Filled by main(): models that only occur in request bodies. Their nullable
# optional fields are `Option<Option<T>>` in Rust, to tell "send null" from "leave out".
BODY_ONLY: set[str] = set()


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


def rustdoc_safe(line: str) -> str:
    """Keeps spec text from turning into rustdoc links: `[eventId]` is escaped and
    bare URLs are wrapped in `<...>`. Code spans and intra-doc links stay."""
    # `startTimes`[`eventId`]: indexing, not an intra-doc link
    line = re.sub(r"`\[(`[^`]*`)\]", r"`\\[\1\\]", line)
    parts = re.split(r"(`[^`]*`)", line)
    for i in range(0, len(parts), 2):
        part = re.sub(r"\[([^\]`]*)\](?!\()", r"\\[\1\\]", parts[i])
        parts[i] = re.sub(r"(?<![<(])\b(https?://[^\s<>)\]]*[^\s<>)\].,;:])", r"<\1>", part)
    return "".join(parts)


def rust_doc(text: str, indent: str) -> list[str]:
    out, in_code = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code:
            line = rustdoc_safe(line)
        out.append(f"{indent}///{(' ' + line) if line else ''}".rstrip())
    return out


def direct_refs(model: Model) -> set[str]:
    """Models embedded without indirection (not inside Vec/Map)."""
    refs = set()
    for f in model.fields:
        t = f.type.inner[0] if f.type.kind == "opt" else f.type
        if t.kind == "model":
            refs.add(t.name)
    return refs


def type_refs(schemas: Schemas, t: T | None, acc: set[str]) -> set[str]:
    """All models reachable from `t`."""
    if t is not None:
        if t.kind == "model" and t.name not in acc:
            acc.add(t.name)
            for f in schemas.models[t.name].fields:
                type_refs(schemas, f.type, acc)
        for i in t.inner:
            type_refs(schemas, i, acc)
    return acc


def body_only_models(schemas: Schemas, ops: list[Op]) -> set[str]:
    in_bodies: set[str] = set()
    in_responses: set[str] = set()
    for op in ops:
        type_refs(schemas, op.body, in_bodies)
        type_refs(schemas, op.result_type, in_responses)
    return in_bodies - in_responses


@dataclass
class RustField:
    field: Field_
    ident: str
    ty: str
    double: bool  # Option<Option<T>>: None leaves out, Some(None) sends null


_rust_fields: dict[str, list[RustField]] = {}
_model_graph: dict[str, set[str]] = {}


def rust_fields(schemas: Schemas, name: str) -> list[RustField]:
    """Field names and types of a generated Rust model."""
    if name in _rust_fields:
        return _rust_fields[name]
    if not _model_graph:
        _model_graph.update({n: direct_refs(m) for n, m in schemas.models.items()})
    graph = _model_graph

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

    model = schemas.models[name]
    out = []
    for f, ident in zip(model.fields, field_names(model, rust_ident, {"extra"}), strict=True):
        base = f.type.inner[0] if f.type.kind == "opt" else f.type
        boxed = base.kind == "model" and reaches(base.name, name)
        ty = rust_type(f.type, boxed)
        optional = not f.required or f.type.kind == "opt"
        if optional and not ty.startswith("Option<") and ty != "serde_json::Value":
            ty = f"Option<{ty}>"
        double = name in BODY_ONLY and not f.required and f.type.kind == "opt" and ty.startswith("Option<")
        if double:
            ty = f"Option<{ty}>"
        out.append(RustField(f, ident, ty, double))
    _rust_fields[name] = out
    return out


def write_rust_models(schemas: Schemas, header: str, out: Path) -> None:
    lines = [f"//! Generated ChurchTools models.\n//!\n//! {header}\n", "#![allow(clippy::all, deprecated)]\n",
             "use serde::{Deserialize, Serialize};\n"]
    for name in sorted(schemas.models):
        model = schemas.models[name]
        lines += rust_doc(model.doc, "")
        lines.append("#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]")
        lines.append(f"pub struct {name} {{")
        for rf in rust_fields(schemas, name):
            f, ident, ty = rf.field, rf.ident, rf.ty
            doc = with_allowed(f.doc, f.type)
            if rf.double:
                doc = f"{doc}\n\n`None` leaves the field out, `Some(None)` sends `null`.".lstrip()
            lines += rust_doc(doc, "    ")
            attrs = []
            if ident.removeprefix("r#") != f.json_name:
                attrs.append(f'rename = "{f.json_name}"')
            if rf.double:
                attrs.append('deserialize_with = "crate::lenient::double_option"')
                if ty == "Option<Option<chrono::DateTime<chrono::Utc>>>":
                    attrs.append('serialize_with = "crate::datetime::serialize_double_opt_utc"')
            elif ty == "String":
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
                lines.append(f"    #[deprecated = {json.dumps(deprecation_hint(f.doc) or 'deprecated in the ChurchTools API')}]")
            lines.append(f"    pub {ident}: {ty},")
        lines.append("    /// Fields not described by the spec, e.g. instance-specific DB fields.")
        lines.append("    #[serde(flatten)]")
        lines.append("    pub extra: serde_json::Map<String, serde_json::Value>,")
        lines.append("}\n")
    out.write_text("\n".join(lines))


def rust_body_type(t: T) -> str:
    """Type of the `body` argument; unions stay JSON (`serde_json::Value`)."""
    base = t.inner[0] if t.kind == "opt" else t
    return rust_type(base, prefix="models::")


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
        "//! Resource handles returned by the accessors of [`Client`](crate::Client), e.g.",
        "//! `client.persons()`, with one method per endpoint.",
        f"//!\n//! {header}\n",
        "#![allow(clippy::all, deprecated, unused_mut)]\n",
        "use std::fmt::Display;\n",
        "use reqwest::Method;\n",
        "use super::models;",
        "use super::queries::*;",
        "use crate::client::{Client, Items, Query, Upload, encode_path_segment as seg};",
        "use crate::error::Result;\n",
        "impl Client {",
    ]
    for c in sorted(c for c in chains if len(c) == 1):
        count = sum(1 for op in ops if op.chain[:1] == c)
        lines.append(f"    /// Endpoints under `/{c[0]}` ({count} operations), see [`{resource_class(c)}`].")
        lines.append(f"    pub fn {rust_ident(c[0])}(&self) -> {resource_class(c)}<'_> {{")
        lines.append(f"        {resource_class(c)} {{ client: self }}")
        lines.append("    }")
    lines.append("}\n")
    queries = [
        "//! Query parameters (`…Query`) and form fields (`…Form`) of the generated methods.",
        "//! Unset fields are left out of the request; fill them with `..Default::default()`.",
        f"//!\n//! {header}\n",
        "#![allow(clippy::all, deprecated)]\n",
        "use crate::client::Query;",
        "use crate::query::ToQuery;\n",
    ]

    for chain in sorted(chains):
        names = [op.name for op in by_chain.get(chain, [])]
        clash = {f"{n}{suffix}" for n in names for suffix in ("_with", "_iter")} & set(names)
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
        queries += query_structs
    out.write_text("\n".join(lines))
    (out.parent / "queries.rs").write_text("\n".join(queries))


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
        "# use churchtools_core::queries::*;",
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
            struct_lines += rust_doc(deprecated_doc(with_allowed(p.doc, p.type), p.deprecated), "    ")
            if p.deprecated:
                struct_lines.append(f"    #[deprecated = {json.dumps(deprecation_hint(p.doc) or 'deprecated in the ChurchTools API')}]")
            struct_lines.append(f"    pub {ident}: Option<{rust_param_type(p.type)}>,")
        struct_lines.append("}\n")
        struct_lines.append(f"impl {query_struct} {{")
        struct_lines.append("    pub(crate) fn to_query(&self) -> Query {")
        struct_lines.append("        let mut q = Query::new();")
        for ident, p in idents:
            struct_lines.append(f'        self.{ident}.push_query("{p.name}", &mut q);')
        struct_lines.append("        q")
        struct_lines.append("    }")
        struct_lines.append("}\n")
    if op.body is not None:
        args.append(f"body: &{rust_body_type(op.body)}")
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
                struct_lines += rust_doc(with_allowed(f.doc, f.type), "    ")
                struct_lines.append(f"    pub {ident}: Option<{rust_param_type(f.type)}>,")
            struct_lines.append("}\n")
            struct_lines.append(f"impl {form_struct} {{")
            struct_lines.append("    pub(crate) fn to_query(&self) -> Query {")
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

    doc = ([op.summary, ""] if op.summary else []) + [f"`{op.method.upper()} {op.path}`"]
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
            lines.append(f"    #[deprecated = {json.dumps(deprecation_message(op))}]")
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
        lines.append(f"    #[deprecated = {json.dumps(deprecation_message(op))}]")
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
        lines.append("    }\n")
        item = rust_type(op.result_type.inner[0], prefix="models::")
        iter_args = [a for a in args if not a.startswith("body:")]
        lines += rust_doc(
            "\n".join(doc[:1] + ["", f"Like [`Self::{name}`], but lazy: each page is fetched only when the iteration reaches it.",
                                 "Breaking off early saves the remaining requests."]),
            "    ",
        )
        if op.deprecated:
            lines.append(f"    #[deprecated = {json.dumps(deprecation_message(op))}]")
        lines.append(f"    pub fn {op.name}_iter({', '.join(iter_args)}) -> Items<{item}> {{")
        lines.append(f"        let path = {path};")
        lines.append(f"        self.client.items(&path, {'query.to_query()' if query_struct else 'Query::new()'})")
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
