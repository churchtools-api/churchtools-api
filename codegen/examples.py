"""Builds small Python and Rust usage examples for generated operations.

Used by docs.py. Every example is also written to a check file
(core/tests/doc_examples.rs, python/tests/doc_examples.py) so that the
compiler and mypy verify each snippet shown in the documentation.
"""

from __future__ import annotations

import datetime as dt
import json
import keyword
from dataclasses import dataclass

import generate as g

EXAMPLE_DATE = "2026-11-01"
EXAMPLE_DATETIME = "2026-11-01T10:00:00Z"
PREFERRED_FIELDS = ("name", "title", "first_name", "id")
FILE_EXTENSIONS = {
    "application/pdf": "pdf",
    "text/csv": "csv",
    "text/calendar": "ics",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/zip": "zip",
    "image/png": "png",
    "image/jpeg": "jpg",
}


@dataclass
class Example:
    python: str
    rust: str


def unwrap(t: g.T) -> g.T:
    return t.inner[0] if t.kind == "opt" else t


# ---------------------------------------------------------------------------
# Example values (as JSON)


def valid_example(t: g.T, example: object) -> bool:
    k = unwrap(t).kind
    if example is None:
        return False
    if k == "int":
        return isinstance(example, int) and not isinstance(example, bool)
    if k == "float":
        return isinstance(example, (int, float)) and not isinstance(example, bool)
    if k == "bool":
        return isinstance(example, bool)
    if k == "str":
        return isinstance(example, str) and len(example) < 60 and "\n" not in example
    if k == "date":
        return isinstance(example, str) and _parses(example, dt.date.fromisoformat)
    if k == "datetime":
        return isinstance(example, str) and _parses(example.replace("Z", "+00:00"), dt.datetime.fromisoformat)
    if k == "list":
        return isinstance(example, list) and bool(example) and all(valid_example(unwrap(t).inner[0], e) for e in example)
    return False


def _parses(value: str, parse) -> bool:
    try:
        parse(value)
        return True
    except ValueError:
        return False


def default_str(name: str) -> str:
    n = name.lower()
    if "mail" in n:
        return "anna@example.org"
    if n in ("name", "title") or n.endswith("name"):
        return "Hauskreis Nord"
    if "color" in n:
        return "blue"
    return "beispiel"


def json_example(schemas: g.Schemas, t: g.T, name: str, example: object = None, depth: int = 0) -> object:
    """A small, valid-looking JSON value for type `t`."""
    if valid_example(t, example):
        return example
    t = unwrap(t)
    k = t.kind
    if k == "int":
        return 42
    if k == "float":
        return 1.5
    if k == "bool":
        return True
    if k == "str":
        return default_str(name)
    if k == "date":
        return EXAMPLE_DATE
    if k == "datetime":
        return EXAMPLE_DATETIME
    if k == "list":
        return [json_example(schemas, t.inner[0], name, None, depth + 1)]
    if k == "map":
        return {}
    if k == "union":
        return json_example(schemas, t.inner[0], name, example, depth)
    if k == "model":
        if depth > 2:
            return {}
        model = schemas.models[t.name]
        return {
            f.json_name: json_example(schemas, f.type, f.json_name, f.example, depth + 1)
            for f in model.fields
            if f.required and not f.deprecated
        }
    return "beispiel"


# ---------------------------------------------------------------------------
# Python


def py_literal(value: object) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(py_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(k)}: {py_literal(v)}" for k, v in value.items()) + "}"
    return repr(value)


def py_value(t: g.T, value: object) -> str:
    t = unwrap(t)
    if t.kind == "union":
        member = next((m for m in t.inner if valid_example(m, value)), None)
        if member is None and isinstance(value, dict):
            member = next((m for m in t.inner if unwrap(m).kind == "model"), None)
        return py_value(member, value) if member else py_literal(value)
    if t.kind == "date" and isinstance(value, str):
        d = dt.date.fromisoformat(value)
        return f"dt.date({d.year}, {d.month}, {d.day})"
    if t.kind == "datetime" and isinstance(value, str):
        d = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return f"dt.datetime({d.year}, {d.month}, {d.day}, {d.hour}, {d.minute}, tzinfo=dt.timezone.utc)"
    if t.kind == "model":
        return f"ct.models.{t.name}.model_validate({py_literal(value)})"
    if t.kind == "list" and isinstance(value, list):
        return "[" + ", ".join(py_value(t.inner[0], v) for v in value) + "]"
    return py_literal(value)


def item_var(op: g.Op) -> str:
    word = op.name.split("_", 1)[1] if op.name.startswith(("list_", "get_")) else (op.chain[-1] if op.chain else "item")
    word = word.rstrip("_")
    if word.endswith("ies"):
        word = word[:-3] + "y"
    elif word.endswith(("sses", "uses", "xes")):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if not word.isidentifier() or keyword.iskeyword(word) or word in ("client", "ct", "dt", "data", "result", "body"):
        return "item"
    return word


def display_field(schemas: g.Schemas, t: g.T | None) -> g.Field_ | None:
    """Picks the field an example prints for a model, if any."""
    if t is None:
        return None
    t = unwrap(t)
    if t.kind == "list":
        t = unwrap(t.inner[0])
    if t.kind != "model":
        return None
    model = schemas.models[t.name]
    fields = [f for f in model.fields if not f.deprecated and unwrap(f.type).kind in g.QUERY_SCALARS]
    for preferred in PREFERRED_FIELDS:
        for f in fields:
            if g.snake(f.json_name) == preferred:
                return f
    return fields[0] if fields else None


def attr_name(schemas: g.Schemas, t: g.T, f: g.Field_, ident) -> str:
    t = unwrap(t)
    if t.kind == "list":
        t = unwrap(t.inner[0])
    model = schemas.models[t.name]
    names = g.field_names(model, ident, {"extra"} if ident is g.rust_ident else set())
    return names[model.fields.index(f)]


def chosen_body_fields(op: g.Op) -> list[g.Field_]:
    """Required body fields, or one representative optional field."""
    if op.body_model is None:
        return []
    required = [f for f in op.body_model.fields if f.required and not f.deprecated and op.body_required]
    if required:
        return required
    candidates = [f for f in op.body_model.fields if not f.deprecated]
    for preferred in ("name", "title", "description", "comment"):
        for f in candidates:
            if f.json_name == preferred:
                return [f]
    scalars = [f for f in candidates if unwrap(f.type).kind in g.QUERY_SCALARS]
    return scalars[:1]


def python_example(schemas: g.Schemas, op: g.Op) -> str:
    params = g.python_params(op)
    args = []
    chosen = {f.json_name for f in chosen_body_fields(op)}
    for p in params:
        if p.kind == "path":
            args.append(py_value(p.type, json_example(schemas, p.type, p.wire, p.example)))
        elif p.kind == "query" and p.required:
            args.append(f"{p.py}={py_value(p.type, json_example(schemas, p.type, p.wire, p.example))}")
        elif p.kind == "field" and p.wire in chosen:
            args.append(f"{p.py}={py_value(p.type, json_example(schemas, p.type, p.wire, p.example))}")
        elif p.kind == "body" and p.required:
            args.append(f"body={py_value(p.type, json_example(schemas, p.type, 'body'))}")
        elif p.kind == "upload":
            args.append(f'{p.py}=[ct.Upload.from_path("{upload_example(op)}")]')
    call = f"client.{'.'.join(op.chain)}.{op.name}({', '.join(args)})"
    if len(call) > 88 and args:
        call = f"client.{'.'.join(op.chain)}.{op.name}(\n" + "".join(f"    {a},\n" for a in args) + ")"

    rt = op.result_type
    field = display_field(schemas, rt)
    if op.result in ("data", "json") and rt is not None:
        if rt.kind == "list" or op.paginated:
            var = item_var(op)
            shown = f"{var}.{attr_name(schemas, rt, field, g.py_ident)}" if field else var
            return f"for {var} in {call}:\n    print({shown})"
        if rt.kind == "model" or (rt.kind == "opt" and unwrap(rt).kind == "model"):
            var = item_var(op) if not op.name.startswith(("create", "update", "patch")) else "result"
            if field and rt.kind == "model":
                return f"{var} = {call}\nprint({var}.{attr_name(schemas, rt, field, g.py_ident)})"
            return f"{var} = {call}\nprint({var})"
        return f"result = {call}\nprint(result)"
    if op.result == "bytes":
        ext = FILE_EXTENSIONS.get(op.content_type, "bin")
        return f'data = {call}\nwith open("ergebnis.{ext}", "wb") as f:\n    f.write(data)'
    return call


# ---------------------------------------------------------------------------
# Rust


def rs_value(t: g.T, value: object, *, display: bool = False) -> str:
    """Rust expression for `value`; `display` for `impl Display` path arguments."""
    base = unwrap(t)
    k = base.kind
    if k == "int":
        return str(value)
    if k == "float":
        return repr(float(value))
    if k == "bool":
        return "true" if value else "false"
    if k == "str":
        return json.dumps(value, ensure_ascii=False) + ("" if display else ".into()")
    if k in ("date", "datetime"):
        return f"{json.dumps(value)}{'' if display else '.parse()?'}"
    if k == "list" and unwrap(base.inner[0]).kind in g.QUERY_SCALARS and isinstance(value, list):
        return "vec![" + ", ".join(rs_value(base.inner[0], v) for v in value) + "]"
    return f"serde_json::json!({json.dumps(value, ensure_ascii=False)})"


def rust_example(schemas: g.Schemas, op: g.Op) -> str:
    lines: list[str] = []
    args: list[str] = []
    for p in op.params:
        if p.location == "path":
            args.append(rs_value(p.type, json_example(schemas, p.type, p.name, p.example), display=True))
    query_params = [p for p in op.params if p.location == "query" and not (op.paginated and p.name == "page")]
    if query_params:
        struct = g.pascal(op.op_id) + "Query"
        taken: set[str] = set()
        idents = {p.name: g.unique(g.rust_ident(p.name), taken) for p in query_params}
        required = [p for p in query_params if p.required]
        if required:  # otherwise the method has a variant without query
            fields = "".join(
                f"    {idents[p.name]}: Some({rs_value(p.type, json_example(schemas, p.type, p.name, p.example))}),\n"
                for p in required
            )
            lines.append(f"let query = {struct} {{\n{fields}    ..Default::default()\n}};")
            args.append("&query")
    if op.body is not None:
        base = unwrap(op.body)
        if op.body_model is not None:
            chosen = chosen_body_fields(op)
            value = {f.json_name: json_example(schemas, f.type, f.json_name, f.example) for f in chosen}
            if op.body_required:
                value = {**json_example(schemas, base, "body"), **value}  # type: ignore[dict-item]
            pretty = json.dumps(value, ensure_ascii=False, indent=4)
            lines.append(f"let body: models::{base.name} = serde_json::from_value(serde_json::json!({pretty}))?;")
        else:
            value = json_example(schemas, base, "body")
            lines.append(f"let body = serde_json::json!({json.dumps(value, ensure_ascii=False, indent=4)});")
        args.append("&body")
    if op.upload is not None:
        lines.append(f'let file = Upload::from_path("{upload_example(op)}")?;')
        args.append("&[file]")

    accessor = "".join(f".{g.rust_ident(c)}()" for c in op.chain)
    call = f"client{accessor}.{g.rust_ident(op.name)}({', '.join(args)})?"
    rt = op.result_type
    field = display_field(schemas, rt)
    if op.result in ("data", "json") and rt is not None:
        if rt.kind == "list":
            var = item_var(op)
            lines.append(f"for {var} in {call} {{")
            lines.append(f"    {rust_print(schemas, rt, field, var)}")
            lines.append("}")
        elif rt.kind == "model":
            var = item_var(op) if not op.name.startswith(("create", "update", "patch")) else "result"
            lines.append(f"let {var} = {call};")
            lines.append(rust_print(schemas, rt, field, var))
        else:
            lines.append(f"let result = {call};")
            lines.append('println!("{:?}", result);')
    elif op.result == "bytes":
        ext = FILE_EXTENSIONS.get(op.content_type, "bin")
        lines.append(f"let data = {call};")
        lines.append(f'std::fs::write("ergebnis.{ext}", &data)?;')
    else:
        lines.append(f"{call};")
    return "\n".join(lines)


def upload_example(op: g.Op) -> str:
    """A plausible file name for an upload endpoint."""
    if "statements" in op.path:
        return "kontoauszug.xml"
    if "htmltemplates" in op.path:
        return "logo.png"
    return "gemeindebrief.pdf"


def rust_print(schemas: g.Schemas, t: g.T, field: g.Field_ | None, var: str) -> str:
    if field is None:
        return f'println!("{{:?}}", {var});'
    ident = attr_name(schemas, t, field, g.rust_ident)
    plain = field.required and field.type.kind != "opt" and unwrap(field.type).kind in g.QUERY_SCALARS
    return f'println!("{{{"" if plain else ":?"}}}", {var}.{ident});'


def example_for(schemas: g.Schemas, op: g.Op) -> Example:
    return Example(python_example(schemas, op), rust_example(schemas, op))


# ---------------------------------------------------------------------------
# Check files


# Guide snippets that talk to a fixed server or log in with a password are only
# compiled / type-checked; all others also run against recorded responses.
FIXED_SERVER = ("Client::new(", "ct.Client(", "login_with_password")


def runs_offline(code: str) -> bool:
    return not any(marker in code for marker in FIXED_SERVER)


def write_check_files(examples: list[tuple[str, Example]], root) -> None:
    """Writes the examples as tests.

    Rust: the reference examples are doctests in the generated api.rs; this file
    holds the guide snippets, compiled and (where possible) run against the
    replay server. Python: every snippet is type-checked with mypy and run by
    tests/test_doc_examples.py; REFERENCE and GUIDE map them to their origin.
    """
    rs = [
        "//! Generated by codegen/docs.py: the guide snippets of the documentation.",
        "//! The reference examples are doctests in `src/generated/api.rs`.",
        "//! Snippets that do not contact a fixed server run against recorded responses.\n",
        "#![allow(unused, deprecated, clippy::all)]\n",
        "use churchtools_core::*;",
        "use std::result::Result;\n",
        "/// A client for the replay server; `CT_URL` points there too, for `Client::from_env()`.",
        "fn replay_client() -> Client {",
        "    static SETUP: std::sync::Once = std::sync::Once::new();",
        "    SETUP.call_once(|| {",
        "        // SAFETY: set once, before any test reads the environment.",
        "        unsafe {",
        '            std::env::set_var("CT_URL", replay::routing_url());',
        '            std::env::set_var("CT_TOKEN", "replay");',
        "        }",
        "        // Snippets that write files (e.g. CSV exports) do so in a temporary directory.",
        '        let dir = std::env::temp_dir().join("churchtools-rs-doc-examples");',
        "        std::fs::create_dir_all(&dir).unwrap();",
        "        std::env::set_current_dir(&dir).unwrap();",
        "    });",
        '    Client::new(replay::routing_url(), Some("replay".into())).unwrap()',
        "}\n",
    ]
    py = [
        '"""Generated by codegen/docs.py: every Python snippet from the documentation.',
        "",
        "Type-checked with `mypy --strict tests/doc_examples.py` and run against recorded",
        "responses by `tests/test_doc_examples.py`.",
        '"""\n',
        "import datetime as dt\n",
        "import churchtools_rs as ct\n",
    ]
    reference, guide_map = [], []
    for i, (key, ex) in enumerate(examples):
        py.append(f"\n# {key}")
        py.append(f"def example_{i}(client: ct.Client) -> None:")
        py += [f"    {line}".rstrip() for line in ex.python.splitlines()]
        if key.startswith("guide: "):
            gid = key.removeprefix("guide: ")
            guide_map.append(f"    {gid!r}: example_{i},")
            rs.append(f"// {key}")
            rs.append(f"fn example_{i}(client: &Client) -> std::result::Result<(), Box<dyn std::error::Error>> {{")
            rs += [f"    {line}".rstrip() for line in ex.rust.splitlines()]
            rs.append("    Ok(())\n}\n")
            if runs_offline(ex.rust):
                rs.append("#[test]")
                rs.append(f"fn guide_{gid.replace('-', '_')}() {{")
                rs.append(f"    example_{i}(&replay_client()).unwrap();")
                rs.append("}\n")
        else:
            reference.append(f"    {key!r}: example_{i},")
    py.append("\n\n# operationId -> example of the API reference")
    py.append("REFERENCE = {\n" + "\n".join(reference) + "\n}")
    py.append("\n# section id -> example of the guide")
    py.append("GUIDE = {\n" + "\n".join(guide_map) + "\n}")
    (root / "core" / "tests" / "doc_examples.rs").write_text("\n".join(rs) + "\n")
    (root / "python" / "tests" / "doc_examples.py").write_text("\n".join(py) + "\n")
