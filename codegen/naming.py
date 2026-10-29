"""Identifiers: Python/Rust names, keywords, word splitting, cleaned spec text."""

from __future__ import annotations

import keyword
import re

# Many path segments are written as one word (`/agendatemplates`, `/externallogins`),
# others with separators (`/external-logins`). Names split joined words into these
# words, so both become `external_logins`. A segment is only split if it consists
# entirely of known words (singular or plural); everything else stays as is.
WORDS = set("""
account accounting adapter age agenda agreement assets available bulk by cash category change check checkin church
class client comment confidentiality config contact cost center create csrf data datev db discount document domain
dynamic entity evangelische event exchange export external factor feature field for further group grow homepage html
ids impact job key label letter link log login mapping master meeting member news next no number oauth object open
page path period person placeholder policy poll possible post preview privacy proxy public purpose qrcode query rate
registration relationship repeat calculation request requester resource rule security level service settings signout
slug split start statistics status string target template termine test text token tax transaction translation two
type upload usage user validate viewer
""".split())


def _word_forms() -> dict[str, str]:
    forms: dict[str, str] = {}
    for w in WORDS:
        for f in (w, w + "s", w + "es", w[:-1] + "ies" if w.endswith("y") else w):
            forms.setdefault(f, w)
    return forms


WORD_FORMS = _word_forms()


def split_words(segment: str) -> str:
    """`agendatemplates` -> `agenda_templates`; unknown words leave the segment unchanged."""

    def best(rest: str) -> tuple[str, ...] | None:
        if not rest:
            return ()
        found = None
        for i in range(len(rest), 0, -1):
            if rest[:i] in WORD_FORMS and (tail := best(rest[i:])) is not None:
                candidate = (rest[:i], *tail)
                if found is None or len(candidate) < len(found):
                    found = candidate
        return found

    return "_".join(
        "_".join(best(part) or (part,)) if part.isalpha() else part for part in segment.split("_")
    )


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


# Python keywords, soft keywords (as of 3.14) and public attributes of Pydantic's
# BaseModel. Fixed here instead of read from the running interpreter, so the
# output does not depend on the installed Python or Pydantic version.
PY_RESERVED = set(keyword.kwlist) | {"_", "case", "match", "type"} | {
    "construct", "copy", "dict", "from_orm", "json", "model_computed_fields", "model_config", "model_construct",
    "model_copy", "model_dump", "model_dump_json", "model_extra", "model_fields", "model_fields_set",
    "model_json_schema", "model_parametrized_name", "model_post_init", "model_rebuild", "model_validate",
    "model_validate_json", "model_validate_strings", "parse_file", "parse_obj", "parse_raw", "schema", "schema_json",
    "update_forward_refs", "validate",
}

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


# Summaries the spec has not filled in yet, e.g. "TODO 200".
PLACEHOLDER_DOC = re.compile(r"\s*(TODO|FIXME|TBD)\b[\s\d]*", re.IGNORECASE)


def clean_doc(text: str | None) -> str:
    if not text or PLACEHOLDER_DOC.fullmatch(text):
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("```", "`` `").strip()


def keyword_safe(name: str) -> str:
    """Resource and method names are shared by Python and Rust, so avoid both keyword sets."""
    return f"{name}_" if keyword.iskeyword(name) or name in RUST_KEYWORDS else name
