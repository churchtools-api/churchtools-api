"""Test support files derived from the spec.

* `python/tests/live/operations.json`: catalog of all operations with the
  information the live tests need to call them through the generated Python API.
* `core/tests/recorded.rs`: one offline test per operation that decodes the
  response recorded by the live tests (`fixtures/recorded/<operationId>.json`)
  into the generated Rust type.
"""

from __future__ import annotations

import json

import generate as g


def raw_params(spec: dict, op: g.Op) -> dict[tuple[str, str], dict]:
    item = spec["paths"][op.path]
    out = {}
    for p in [*item[op.method].get("parameters", []), *item.get("parameters", [])]:
        out.setdefault((p.get("in"), p.get("name")), p)
    return out


def type_str(t: g.T) -> str:
    return g.py_type(t).replace("_t.", "").replace("_dt.", "")


def catalog(spec: dict, ops: list[g.Op]) -> list[dict]:
    entries = []
    for op in ops:
        raw = raw_params(spec, op)
        params = []
        for p in g.python_params(op):
            schema = raw.get((p.kind, p.wire), {}).get("schema", {}) if p.kind in ("path", "query") else {}
            items = schema.get("items", {}) if isinstance(schema, dict) else {}
            params.append(
                {
                    "kind": p.kind,
                    "wire": p.wire,
                    "py": p.py,
                    "type": type_str(p.type),
                    "required": p.required,
                    "enum": schema.get("enum") or items.get("enum"),
                    "default": schema.get("default"),
                    "example": p.example,
                }
            )
        entries.append(
            {
                "op_id": op.op_id,
                "method": op.method.upper(),
                "path": op.path,
                "call": ".".join([*op.chain, op.name]),
                "tags": op.tags,
                "deprecated": op.deprecated,
                "paginated": op.paginated,
                "result": op.result,
                "result_type": type_str(op.result_type) if op.result_type else None,
                "params": params,
            }
        )
    return entries


def rust_recorded_tests(ops: list[g.Op], header: str) -> str:
    lines = [
        f"//! {header}",
        "//!",
        "//! Decodes the responses recorded by `python/tests/live` (in `fixtures/recorded`)",
        "//! into the generated Rust types. Operations without a recording pass without",
        "//! checking anything; `cargo test --test recorded -- --nocapture` lists them.",
        "",
        "#![allow(non_snake_case)]",
        "",
        "use churchtools_api::models;",
        "use serde::de::DeserializeOwned;",
        "",
        "/// Loads the recorded body of `op_id`; `None` if nothing was recorded.",
        "fn recorded(op_id: &str) -> Option<serde_json::Value> {",
        '    let path = format!("{}/../fixtures/recorded/{op_id}.json", env!("CARGO_MANIFEST_DIR"));',
        "    let text = std::fs::read_to_string(&path).ok()?;",
        "    let fixture: serde_json::Value = serde_json::from_str(&text).expect(\"fixture is JSON\");",
        '    Some(fixture["body"].clone())',
        "}",
        "",
        "fn check<T: DeserializeOwned>(op_id: &str, envelope: bool) {",
        "    let Some(body) = recorded(op_id) else {",
        '        println!("{op_id}: not recorded");',
        "        return;",
        "    };",
        '    let value = if envelope { body["data"].clone() } else { body };',
        "    // Round-trip through text so errors carry serde_json's path and position.",
        "    let text = serde_json::to_string(&value).unwrap();",
        "    let mut de = serde_json::Deserializer::from_str(&text);",
        "    if let Err(e) = serde_path_to_error::deserialize::<_, T>(&mut de) {",
        '        panic!("{op_id}: {} at `{}`", e.inner(), e.path());',
        "    }",
        "}",
        "",
    ]
    for op in ops:
        if op.result not in ("data", "json") or op.result_type is None:
            continue
        rt = g.rust_type(op.result_type, prefix="models::")
        lines += [
            "#[test]",
            f"fn {op.op_id.replace('-', '_')}() {{",
            f'    check::<{rt}>("{op.op_id}", {"true" if op.result == "data" else "false"});',
            "}",
            "",
        ]
    return "\n".join(lines)


def write(spec: dict, ops: list[g.Op], header: str) -> None:
    live = g.ROOT / "python" / "tests" / "live"
    live.mkdir(parents=True, exist_ok=True)
    (live / "operations.json").write_text(json.dumps(catalog(spec, ops), indent=1, ensure_ascii=False) + "\n")
    (g.ROOT / "core" / "tests" / "recorded.rs").write_text(rust_recorded_tests(ops, header))
