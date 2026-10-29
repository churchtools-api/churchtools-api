"""Python output: Pydantic models and resource classes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from naming import (
    py_ident,
    unique,
)
from spec import (
    ANY,
    EXAMPLES,
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

# ---------------------------------------------------------------------------
# Python output


def py_type(t: T, quote_models: bool = True, enums: str = "") -> str:
    """`enums`: "" plain `str`/`int`, "strict" `Literal[...]` for arguments, "open"
    `Literal[...] | str` for responses, where the server may send new values."""
    k = t.kind
    if k == "any":
        return "_t.Any"
    if k in ("str", "int") and t.values and enums:
        literal = f"_t.Literal[{', '.join(repr(v) for v in t.values)}]"
        return literal if enums == "strict" else f"_t.Union[{literal}, {k}]"
    if k in ("str", "int", "float", "bool"):
        return k
    if k == "date":
        return "_dt.date"
    if k == "datetime":
        return "_dt.datetime"
    if k == "list":
        return f"_t.List[{py_type(t.inner[0], quote_models, enums)}]"
    if k == "map":
        return f"StrMap[{py_type(t.inner[0], quote_models, enums)}]"
    if k == "model":
        return t.name
    if k == "union":
        return f"_t.Union[{', '.join(py_type(i, quote_models, enums) for i in t.inner)}]"
    if k == "opt":
        return f"_t.Optional[{py_type(t.inner[0], quote_models, enums)}]"
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
        for f, attr in zip(model.fields, py_field_names(model), strict=True):
            ann = py_type(f.type, enums="open")
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
            doc = with_allowed(f.doc, f.type)
            if doc:
                lines.append(py_docstring(doc, "    ").rstrip("\n"))
    out.write_text("\n".join(lines) + "\n")


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
        "from typing_extensions import deprecated as _deprecated\n",
        "from . import models",
        "from ._base import UNSET, Paginator, Resource, StrMap, UnsetType, Upload, _body, _query, _seg, _warn_deprecated\n",
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


def model_type_for_resources(t: T, enums: str = "") -> str:
    """Python annotation inside _resources.py, where models live in `models.`."""
    parts = re.split(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", py_type(t, enums=enums))
    return "".join(
        part if i % 2 else re.sub(
            r"(?<![\w.])([A-Z]\w*)", lambda m: m.group(1) if m.group(1) in ("None", "StrMap") else f"models.{m.group(1)}", part
        )
        for i, part in enumerate(parts)
    )


@dataclass
class PyParam:
    kind: str  # path | query | field (body property as keyword) | body (whole body)
    wire: str  # name in URL/query/JSON
    py: str  # Python argument name
    type: T
    required: bool
    doc: str
    example: object = None
    deprecated: bool = False


def python_params(op: Op) -> list[PyParam]:
    """Arguments of the generated Python method, in signature order before sorting."""
    taken: set[str] = {"self"}
    out = []
    for p in op.params:
        if p.location == "query" and op.paginated and p.name == "page":
            continue
        out.append(
            PyParam(p.location, p.name, unique(py_ident(p.name), taken), p.type, p.required, p.doc, p.example, p.deprecated)
        )
    if op.body_model is not None:
        for f, attr in zip(op.body_model.fields, py_field_names(op.body_model), strict=True):
            out.append(
                PyParam(
                    "field", f.json_name, unique(attr, taken), f.type, f.required and op.body_required, f.doc, f.example,
                    f.deprecated,
                )
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
    warn_lines = []
    for p in python_params(op):
        ann = model_type_for_resources(p.type, "strict")
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
        doc = deprecated_doc(with_allowed(p.doc, p.type), p.deprecated)
        if doc:
            doc_args.append((p.py, doc))
        if p.deprecated and not p.required and p.kind in ("query", "field"):
            unset = "UNSET" if p.kind == "field" else "None"
            warn_lines.append(f"        if {p.py} is not {unset}:")
            warn_lines.append(f"            _warn_deprecated({p.py!r}, {deprecation_hint(p.doc)!r})")
    if op.body_model is not None:
        sig_kw.append((1, "extra_body: _t.Optional[_t.Dict[str, _t.Any]] = None"))
        body_expr = "_body({" + ", ".join(pairs) + "}, extra_body)"

    kw = [s for _, s in sorted(sig_kw, key=lambda x: x[0])]
    params = ["self", *sig_pos] + (["*", *kw] if kw else [])

    if op.result == "data" or op.result == "json":
        rt = model_type_for_resources(op.result_type, "open")
        ret = f"Paginator[{model_type_for_resources(op.result_type.inner[0], 'open')}]" if op.paginated else rt
    elif op.result == "bytes":
        ret = "bytes"
    else:
        ret = "None"

    doc_lines = ([op.summary, ""] if op.summary else []) + [f"`{op.method.upper()} {op.path}`"]
    if op.deprecated:
        hint = deprecation_hint(op.doc)
        doc_lines.append(f"\nDeprecated.{' ' + hint if hint else ''}")
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

    out = [f"    @_deprecated({deprecation_message(op)!r})"] if op.deprecated else []
    out.append(f"    def {op.name}(")
    out += [f"        {p}," for p in params]
    out.append(f"    ) -> {ret}:")
    out.append(py_docstring("\n".join(doc_lines), "        ").rstrip("\n"))
    out += warn_lines
    q = "_query([" + ", ".join(query_items) + "])" if query_items else "[]"
    upload_kw = ""
    if upload_expr:
        form_q = "_query([" + ", ".join(form_items) + "])" if form_items else "[]"
        upload_kw = f", upload=({op.upload[0]!r}, {form_q}, {upload_expr})"
    path_lit = f'f"{path_expr}"' if "{" in path_expr else f'"{path_expr}"'
    if op.paginated:
        item = model_type_for_resources(op.result_type.inner[0], "open")
        out.append(f"        return Paginator(self._core, {path_lit}, {q}, {item})")
    elif op.result in ("data", "json"):
        rt = model_type_for_resources(op.result_type, "open")
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
