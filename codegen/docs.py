"""Builds the documentation page docs/site/index.html.

Called from generate.py after code generation. Structure follows the reader:
introduction -> basics -> projects -> full reference -> models -> errors.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import examples as ex
import generate as g
import guide

# Snippets that are not Python/Rust code (shell, Cargo.toml) are not type-checked.
UNCHECKED_SECTIONS = {"installation", "projekt-tests"}
METHOD_ORDER = {"list": 0, "get": 1, "create": 2, "update": 3, "patch": 4, "delete": 5}


# ---------------------------------------------------------------------------
# Text helpers


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def inline(s: str) -> str:
    """Escapes and renders `code`, **bold** and [links](url)."""
    out = []
    for i, part in enumerate(re.split(r"(`[^`]+`)", s)):
        if i % 2:
            out.append(f"<code>{esc(part[1:-1])}</code>")
            continue
        part = esc(part)
        part = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", part)
        part = re.sub(
            r"\[([^\]]+)\]\(([^)\s]+)\)",
            lambda m: f'<a href="{m.group(2)}"'
            + ("" if m.group(2).startswith("#") else ' target="_blank" rel="noopener"')
            + f">{m.group(1)}</a>",
            part,
        )
        out.append(part)
    return "".join(out)


def md(text: str) -> str:
    """Minimal Markdown: paragraphs, lists (- / 1.), pipe tables."""
    blocks = re.split(r"\n\s*\n", text.strip())
    out = []
    for block in blocks:
        lines = [ln.rstrip() for ln in block.splitlines()]
        if all(ln.lstrip().startswith("|") for ln in lines):
            rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines if not re.match(r"^\|[-|\s:]+\|$", ln.strip())]
            head, *body = rows
            out.append(
                '<div class="table-wrap"><table><thead><tr>'
                + "".join(f"<th>{inline(c)}</th>" for c in head)
                + "</tr></thead><tbody>"
                + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
                + "</tbody></table></div>"
            )
        elif re.match(r"^(- |\d+\. )", lines[0]):
            tag = "ol" if lines[0][0].isdigit() else "ul"
            items: list[str] = []
            for ln in lines:
                if re.match(r"^(- |\d+\. )", ln):
                    items.append(re.sub(r"^(- |\d+\. )", "", ln))
                else:
                    items[-1] += " " + ln.strip()
            out.append(f"<{tag}>" + "".join(f"<li>{inline(i)}</li>" for i in items) + f"</{tag}>")
        else:
            out.append(f"<p>{inline(' '.join(ln.strip() for ln in lines))}</p>")
    return "\n".join(out)


def spec_text(text: str, limit: int = 0) -> str:
    """API descriptions from the spec (English): paragraphs and `code`."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if limit:
        paras = paras[:limit]
    return "".join(f"<p>{inline(' '.join(p.split()))}</p>" for p in paras)


def first_sentence(text: str) -> str:
    text = " ".join(text.split())
    m = re.match(r"(.{20,}?[.!?])(\s|$)", text)
    return m.group(1) if m else text


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ---------------------------------------------------------------------------
# Syntax highlighting (done at build time, so the page needs no library)

PY_KEYWORDS = {
    "import", "from", "as", "for", "in", "if", "else", "elif", "while", "with", "def", "return", "try",
    "except", "finally", "raise", "and", "or", "not", "is", "None", "True", "False", "break", "continue",
    "lambda", "pass", "class", "yield", "async", "await",
}
RS_KEYWORDS = {
    "use", "let", "mut", "fn", "for", "in", "if", "else", "match", "return", "Some", "None", "Ok", "Err",
    "true", "false", "struct", "impl", "pub", "mod", "as", "ref", "while", "loop", "break", "move", "dyn",
}
TOKEN_RE = re.compile(
    r"""(?P<comment>\#[^\n]*|//[^\n]*)
      |(?P<string>[fbr]?"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\\n])*')
      |(?P<number>\b\d+(?:\.\d+)?\b)
      |(?P<macro>\b[a-z_]+!)
      |(?P<word>\b[A-Za-z_][A-Za-z0-9_]*\b)
      |(?P<other>.)""",
    re.X | re.S,
)


def highlight(code: str, lang: str) -> str:
    keywords = PY_KEYWORDS if lang == "python" else RS_KEYWORDS
    out = []
    for m in TOKEN_RE.finditer(code):
        kind, text = m.lastgroup, m.group()
        if kind == "comment" and lang == "rust" and text.startswith("#"):
            if not text.startswith("# "):  # Rust attributes etc.
                out.append(esc(text))
                continue
        if kind == "word":
            if text in keywords:
                kind = "kw"
            elif text[0].isupper():
                kind = "type"
            else:
                out.append(esc(text))
                continue
        if kind == "other":
            out.append(esc(text))
            continue
        out.append(f'<span class="t-{kind}">{esc(text)}</span>')
    return "".join(out)


def code_block(python: str, rust: str) -> str:
    return (
        '<div class="code">'
        '<div class="code-bar" role="tablist" aria-label="Sprache">'
        '<button type="button" class="tab" data-l="python" role="tab">Python</button>'
        '<button type="button" class="tab" data-l="rust" role="tab">Rust</button>'
        '<button type="button" class="copy" aria-label="Code kopieren">Kopieren</button>'
        "</div>"
        f'<pre class="py"><code>{highlight(python, "python")}</code></pre>'
        f'<pre class="rs"><code>{highlight(rust, "rust")}</code></pre>'
        "</div>"
    )


def both(py: str, rs: str) -> str:
    """Language-specific inline text; identical values are shown once."""
    if py == rs:
        return py
    return f'<span class="py">{py}</span><span class="rs">{rs}</span>'


# ---------------------------------------------------------------------------
# Types as HTML (with links to models)


def py_type_html(t: g.T) -> str:
    s = g.py_type(t).replace("_t.", "").replace("_dt.", "")
    return re.sub(r"\b([A-Z]\w*)\b", lambda m: model_link(m.group(1)), esc(s))


def rs_type_html(t: g.T) -> str:
    s = g.rust_type(t).replace("chrono::", "").replace("std::collections::", "").replace("crate::", "")
    return re.sub(r"\b([A-Z]\w*)\b", lambda m: model_link(m.group(1)), esc(s))


KNOWN_MODELS: set[str] = set()


def model_link(name: str) -> str:
    return f'<a href="#m-{name}">{name}</a>' if name in KNOWN_MODELS else name


# ---------------------------------------------------------------------------
# Sections


def guide_html(chapter: guide.Chapter) -> str:
    parts = [f'<section class="chapter" id="{chapter.id}"><h2>{esc(chapter.title)}</h2><p class="lead">{inline(chapter.intro)}</p>']
    for s in chapter.sections:
        has_code = bool(s.python or s.rust)
        parts.append(f'<article class="topic{"" if has_code else " no-code"}" id="{s.id}"><div class="prose"><h3>{esc(s.title)}</h3>{md(s.text)}</div>')
        if has_code:
            aside = f'<p class="aside">{inline(s.aside)}</p>' if s.aside else ""
            parts.append(f'<div class="example">{code_block(s.python, s.rust)}{aside}</div>')
        parts.append("</article>")
    parts.append("</section>")
    return "\n".join(parts)


def param_rows(op: g.Op) -> list[str]:
    rows = []
    rs_query: dict[str, str] = {}
    taken: set[str] = set()
    for p in op.params:
        if p.location == "query" and not (op.paginated and p.name == "page"):
            rs_query[p.name] = g.unique(g.rust_ident(p.name), taken)
    for p in g.python_params(op):
        where = {"path": "Pfad", "query": "Query", "field": "Body", "body": "Body", "upload": "Datei", "form": "Formular"}[p.kind]
        if p.kind == "path":
            rs_name = g.snake(p.wire)
        elif p.kind == "query":
            rs_name = rs_query.get(p.wire, g.snake(p.wire))
        elif p.kind == "field":
            rs_name = f'"{p.wire}"'
        elif p.kind == "upload":
            rs_name = "files"
        elif p.kind == "form":
            rs_name = g.rust_ident(g.snake(p.wire))
        else:
            rs_name = "body"
        if p.kind in ("query", "form"):
            rs_t = g.rust_param_type(p.type).replace("chrono::", "")
        elif p.kind == "path":
            rs_t = "impl Display"
        elif p.kind == "upload":
            rs_t = "&[Upload]"
        else:
            rs_t = g.rust_type(p.type).replace("crate::", "")
        rows.append(
            "<tr>"
            f"<td><code>{both(esc(p.py), esc(rs_name))}</code></td>"
            f'<td class="type"><code>{both("Sequence[Upload]" if p.kind == "upload" else py_type_html(p.type), esc(rs_t) if p.kind != "field" else rs_type_html(p.type))}</code></td>'
            f"<td>{where}</td>"
            f'<td>{"ja" if p.required else ""}</td>'
            f"<td>{inline(first_sentence(p.doc)) if p.doc else ''}</td>"
            "</tr>"
        )
    return rows


def return_html(op: g.Op) -> str:
    if op.result in ("data", "json") and op.result_type is not None:
        if op.paginated:
            item = op.result_type.inner[0]
            py = f"Paginator[{py_type_html(item)}]"
        else:
            py = py_type_html(op.result_type)
        rs = rs_type_html(op.result_type)
    elif op.result == "bytes":
        py, rs = "bytes", "Vec&lt;u8&gt;"
        if op.content_type:
            py += f" ({esc(op.content_type)})"
            rs += f" ({esc(op.content_type)})"
    else:
        py, rs = "None", "()"
    return f'<p class="returns"><span class="label">Rückgabe</span> <code>{both(py, rs)}</code></p>'


LIVE_RESULTS = g.ROOT / "fixtures" / "live-results.json"
TEST_STATUS: dict[str, dict] = {}


def untested_reason(op: g.Op) -> str | None:
    """Why an operation is not (sufficiently) covered by the live tests, or None."""
    r = TEST_STATUS.get(op.op_id)
    if r is None:
        return "noch nicht getestet: kein Testszenario"
    outcome = r.get("outcome", "")
    if outcome == "ok":
        return None
    if outcome in ("unresolved", "skipped"):
        return "noch nicht getestet: keine passenden Daten oder Vorbedingungen auf der Testinstanz"
    if outcome == "expected-error":
        return f"getestet, liefert aber einen Fehler ({r.get('status', '')} {r.get('reason', '')})".replace("( ", "(")
    return f"Test fehlgeschlagen ({outcome})"


UNTESTED_STAR = '<span class="untested">*</span>'


def untested_mark(op: g.Op) -> str:
    reason = untested_reason(op)
    if reason is None:
        return ""
    return f'<a class="untested" href="#testabdeckung" title="{esc(reason)}" aria-label="{esc(reason)}">*</a>'


def coverage_rows(ops: list[g.Op]) -> str:
    labels = {
        "ok": "getestet",
        "expected-error": "getestet, Fehler der API",
        "data": "keine Testdaten",
        "none": "kein Testszenario",
        "failed": "Test fehlgeschlagen",
    }
    counts: dict[str, dict[str, int]] = {}
    for op in ops:
        r = TEST_STATUS.get(op.op_id)
        o = "none" if r is None else r["outcome"]
        o = "data" if o in ("unresolved", "skipped") else "failed" if o.startswith(("http-", "decode")) else o
        counts.setdefault(op.method.upper(), {}).setdefault(o, 0)
        counts[op.method.upper()][o] += 1
    rows = []
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        c = counts.get(method, {})
        rows.append(f"<tr><td>{method}</td>" + "".join(f"<td>{c.get(k, 0) or '–'}</td>" for k in labels) + f"<td>{sum(c.values())}</td></tr>")
    head = "<tr><th>Methode</th>" + "".join(f"<th>{v}</th>" for v in labels.values()) + "<th>gesamt</th></tr>"
    return f"<thead>{head}</thead><tbody>{''.join(rows)}</tbody>"


def op_html(op: g.Op, example: ex.Example) -> str:
    py_call = f"client.{'.'.join(op.chain)}.{op.name}()"
    rs_base = "client" + "".join(f".{g.rust_ident(c)}()" for c in op.chain)
    rs_call = f"{rs_base}.{g.rust_ident(op.name)}()"
    query = [p for p in op.params if p.location == "query" and not (op.paginated and p.name == "page")]
    rs_filter = ""
    if query and not any(p.required for p in query):
        struct = g.pascal(op.op_id) + "Query"
        rs_filter = f'<span class="rs alt">mit Filtern: <code>.{op.name}_with(&amp;{struct})</code></span>'
    elif query:
        rs_filter = f'<span class="rs alt">Query: <code>{g.pascal(op.op_id)}Query</code></span>'
    search = " ".join([py_call, op.path, op.summary, op.method]).lower()
    badges = ""
    if op.paginated:
        badges += '<span class="badge">seitenweise</span>'
    if op.deprecated:
        badges += '<span class="badge warn">veraltet</span>'
    rows = param_rows(op)
    params = ""
    if rows:
        table = (
            '<div class="table-wrap"><table class="params"><thead><tr><th>Parameter</th><th>Typ</th><th>Ort</th>'
            "<th>Pflicht</th><th>Beschreibung</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        )
        if len(rows) > 8:
            params = f"<details><summary>{len(rows)} Parameter anzeigen</summary>{table}</details>"
        else:
            params = table
    desc = spec_text(op.doc) if op.doc and op.doc != op.summary else ""
    return (
        f'<article class="op" id="op-{op.op_id}" data-search="{esc(search)}">'
        '<div class="prose">'
        f'<h4><span class="verb v-{op.method}">{op.method.upper()}</span><code class="path">{esc(op.path)}</code>{untested_mark(op)}</h4>'
        f'<p class="call"><code>{both(esc(py_call), esc(rs_call))}</code>{rs_filter}{badges}</p>'
        f'<p class="summary">{inline(op.summary)}</p>'
        f'<div class="desc">{desc}</div>{params}{return_html(op)}'
        "</div>"
        f'<div class="example">{code_block(example.python, example.rust)}</div>'
        "</article>"
    )


def group_ops(ops: list[g.Op]) -> list[tuple[str, list[g.Op]]]:
    by_tag: dict[str, list[g.Op]] = {}
    for op in ops:
        by_tag.setdefault(op.tags[0] if op.tags else "Sonstige", []).append(op)
    order = [t for t in guide.TAG_ORDER if t in by_tag]
    order += sorted(t for t in by_tag if t not in order and t != "Hidden")
    if "Hidden" in by_tag:
        order.append("Hidden")
    result = []
    for tag in order:
        items = sorted(
            by_tag[tag],
            key=lambda o: (o.chain, METHOD_ORDER.get(o.name.split("_")[0], 6), o.name),
        )
        result.append((tag, items))
    return result


def models_html(schemas: g.Schemas) -> str:
    parts = []
    for name in sorted(schemas.models):
        m = schemas.models[name]
        py_names = g.py_field_names(m)
        rs_names = g.field_names(m, g.rust_ident, {"extra"})
        rows = "".join(
            "<tr>"
            f"<td><code>{both(esc(pn), esc(rn))}</code></td>"
            f'<td class="type"><code>{both(py_type_html(f.type), rs_type_html(f.type))}</code></td>'
            f'<td>{"ja" if f.required and f.type.kind != "opt" else ""}</td>'
            f"<td>{inline(first_sentence(f.doc)) if f.doc else ''}{' <em>veraltet</em>' if f.deprecated else ''}</td>"
            "</tr>"
            for f, pn, rn in zip(m.fields, py_names, rs_names, strict=True)
        )
        doc = f'<p class="model-doc">{inline(first_sentence(m.doc))}</p>' if m.doc else ""
        parts.append(
            f'<details class="model" id="m-{name}" data-search="{esc(name.lower())}"><summary><code>{name}</code>'
            f'<span class="count">{len(m.fields)} Felder</span></summary>{doc}'
            '<div class="table-wrap"><table class="params"><thead><tr><th>Feld</th><th>Typ</th><th>Pflicht</th>'
            f"<th>Beschreibung</th></tr></thead><tbody>{rows}</tbody></table></div></details>"
        )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Page


def build(schemas: g.Schemas, ops: list[g.Op], version: str) -> list[tuple[str, ex.Example]]:
    TEST_STATUS.clear()
    if LIVE_RESULTS.exists():
        TEST_STATUS.update(json.loads(LIVE_RESULTS.read_text()))
    KNOWN_MODELS.clear()
    KNOWN_MODELS.update(schemas.models)
    checks: list[tuple[str, ex.Example]] = []
    for chapter in guide.CHAPTERS:
        for s in chapter.sections:
            if (s.python or s.rust) and s.id not in UNCHECKED_SECTIONS:
                checks.append((f"guide: {s.id}", ex.Example(s.python, s.rust)))

    groups = group_ops(ops)
    nav_ref = []
    ref = []
    for tag, items in groups:
        tid = f"tag-{slug(tag)}"
        nav_ref.append(f'<li><a href="#{tid}">{esc(tag)} <span class="count">{len(items)}</span></a></li>')
        intro = guide.TAG_INTROS.get(tag, "")
        index = "".join(
            f'<li><a href="#op-{o.op_id}"><span class="verb v-{o.method}">{o.method.upper()}</span>'
            f"<code>{esc(o.path)}</code>{UNTESTED_STAR if untested_reason(o) else ''}</a></li>"
            for o in items
        )
        body = []
        for op in items:
            example = g.EXAMPLES.get(op.op_id) or ex.example_for(schemas, op)
            checks.append((op.op_id, example))
            body.append(op_html(op, example))
        ref.append(
            f'<section class="tag" id="{tid}"><div class="tag-head"><h3>{esc(tag)}</h3>'
            f'{f"<p>{inline(intro)}</p>" if intro else ""}'
            f'<details class="tag-index"><summary>{len(items)} Endpunkte im Überblick</summary><ul>{index}</ul></details></div>'
            + "\n".join(body)
            + "</section>"
        )

    nav_guide = "".join(
        f'<li class="nav-chapter"><a href="#{c.id}">{esc(c.title)}</a><ul>'
        + "".join(f'<li><a href="#{s.id}">{esc(s.title)}</a></li>' for s in c.sections)
        + "</ul></li>"
        for c in guide.CHAPTERS
    )
    RUST_ERRORS = {
        "TransportError": "Error::Transport / Read / ResponseTooLarge",
        "DecodeError": "Error::Decode",
        "RedirectError": "Error::Redirect",
        "InvalidArgument": "Error::InvalidBaseUrl / InvalidToken / InvalidPath",
    }
    errors = "".join(
        f"<tr><td>{code}</td><td><code>{both('ct.' + name, rs)}</code></td><td>{inline(text)}</td></tr>"
        for code, name, text in guide.ERRORS
        for rs in [
            RUST_ERRORS.get(name, f"Error::Api (status {code})")
        ]
    )
    page = TEMPLATE
    for key, value in {
        "VERSION": esc(version),
        "OPS": str(len(ops)),
        "MODELS": str(len(schemas.models)),
        "NAV_GUIDE": nav_guide,
        "NAV_REF": "".join(nav_ref),
        "GUIDE": "\n".join(guide_html(c) for c in guide.CHAPTERS),
        "REFERENCE": "\n".join(ref),
        "MODEL_LIST": models_html(schemas),
        "ERRORS": errors,
        "COVERAGE": coverage_rows(ops),
    }.items():
        page = page.replace(f"%%{key}%%", value)
    out = g.ROOT / "docs" / "site" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        '<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"</head>\n<body>\n{page}\n</body>\n</html>\n"
    )
    # Same page without document skeleton, for publishing as a claude.ai artifact.
    g.CACHE.parent.mkdir(parents=True, exist_ok=True)
    (g.CACHE.parent / "docs_fragment.html").write_text(page)
    ex.write_check_files(checks, g.ROOT)
    return checks


TEMPLATE = (Path(__file__).parent / "docs_template.html").read_text()
