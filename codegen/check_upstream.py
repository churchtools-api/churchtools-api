"""Checks whether the ChurchTools demo instance runs a new version with a changed API description.

Compares version and build of https://demo.church.tools with `codegen/spec/info.json` and the OpenAPI
description it serves with the stored one (`codegen/spec/openapi.json.xz`, compared as parsed JSON). Only a new
version whose description differs needs attention; a new version with an identical description (as 3.138.0 to
3.138.1) does not.

    python3 codegen/check_upstream.py [--summary FILE] [--github-output FILE]

Writes a German Markdown summary of the differences to `--summary` and `needs_update`, `version`, `build`,
`version_changed`, `spec_changed` to `--github-output` (the GitHub Actions output file). Uses only the standard
library, so it runs without the project's venv. Exit code 0 in all regular cases; network errors fail.
"""

from __future__ import annotations

import argparse
import json
import lzma
import sys
import typing as _t
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = ROOT / "codegen" / "spec" / "openapi.json.xz"
INFO_FILE = ROOT / "codegen" / "spec" / "info.json"
SPEC_URL = "https://demo.church.tools/system/runtime/swagger/openapi.json"
INFO_URL = "https://demo.church.tools/api/info"
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
# Longer lists are cut in the summary; the full picture comes from the generator diff.
LIST_LIMIT = 40


def fetch_json(url: str) -> _t.Any:
    request = urllib.request.Request(url, headers={"User-Agent": "churchtools-api upstream check"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def operations(spec: dict) -> dict[str, dict]:
    """Operations by `METHOD /path`."""
    out = {}
    for path, item in (spec.get("paths") or {}).items():
        for method in METHODS:
            if isinstance(item, dict) and isinstance(item.get(method), dict):
                out[f"{method.upper()} {path}"] = item[method]
    return out


def required_parameters(op: dict) -> set[str]:
    return {
        f"{p.get('in')}:{p.get('name')}"
        for p in op.get("parameters") or []
        if isinstance(p, dict) and p.get("required")
    }


def required_body_fields(op: dict) -> set[str]:
    content = ((op.get("requestBody") or {}).get("content") or {}).values()
    fields: set[str] = set()
    for media in content:
        schema = (media or {}).get("schema") or {}
        fields.update(schema.get("required") or [])
    return fields


class Diff(_t.NamedTuple):
    added: list[str]
    removed: list[str]
    changed: list[str]
    # Changes that can break existing calls: removed operations, new required parameters or body fields.
    breaking: list[str]
    schemas_added: list[str]
    schemas_removed: list[str]
    schemas_changed: list[str]


def diff(old: dict, new: dict) -> Diff:
    old_ops, new_ops = operations(old), operations(new)
    added = sorted(new_ops.keys() - old_ops.keys())
    removed = sorted(old_ops.keys() - new_ops.keys())
    changed = sorted(k for k in old_ops.keys() & new_ops.keys() if old_ops[k] != new_ops[k])
    breaking = [f"`{k}` entfällt" for k in removed]
    for k in changed:
        for p in sorted(required_parameters(new_ops[k]) - required_parameters(old_ops[k])):
            breaking.append(f"`{k}`: neuer Pflichtparameter `{p}`")
        for f in sorted(required_body_fields(new_ops[k]) - required_body_fields(old_ops[k])):
            breaking.append(f"`{k}`: neues Pflichtfeld `{f}` im Body")
    old_s = (old.get("components") or {}).get("schemas") or {}
    new_s = (new.get("components") or {}).get("schemas") or {}
    return Diff(
        added,
        removed,
        changed,
        breaking,
        sorted(new_s.keys() - old_s.keys()),
        sorted(old_s.keys() - new_s.keys()),
        sorted(k for k in old_s.keys() & new_s.keys() if old_s[k] != new_s[k]),
    )


def bullet_list(items: list[str], code: bool = True) -> list[str]:
    lines = [f"- `{i}`" if code else f"- {i}" for i in items[:LIST_LIMIT]]
    if len(items) > LIST_LIMIT:
        lines.append(f"- … und {len(items) - LIST_LIMIT} weitere")
    return lines


def summary(old_version: tuple[str, str], new_version: tuple[str, str], d: Diff) -> str:
    lines = [
        f"Die Demo-Instanz läuft mit ChurchTools **{new_version[0]}** (Build {new_version[1]}); der Code ist aus "
        f"{old_version[0]} (Build {old_version[1]}) erzeugt. Die API-Beschreibung hat sich geändert.",
        "",
        "| | Anzahl |",
        "|---|---:|",
        f"| Neue Operationen | {len(d.added)} |",
        f"| Entfallene Operationen | {len(d.removed)} |",
        f"| Geänderte Operationen | {len(d.changed)} |",
        f"| Neue / entfallene / geänderte benannte Schemas | {len(d.schemas_added)} / {len(d.schemas_removed)} / "
        f"{len(d.schemas_changed)} |",
        "",
    ]
    if d.breaking:
        lines += ["### Möglicherweise inkompatibel", "", *bullet_list(d.breaking, code=False), ""]
    else:
        lines += ["Keine entfallenen Operationen und keine neuen Pflichtparameter oder -felder in Bodies gefunden.", ""]
    for title, items in (("Neue Operationen", d.added), ("Entfallene Operationen", d.removed),
                         ("Geänderte Operationen", d.changed)):
        if items:
            lines += [f"### {title}", "", *bullet_list(items), ""]
    lines += [
        "Die Einordnung ist eine statische Vorprüfung der Spec. Was sich an Modellen, Feldern und Typen ändert, zeigt "
        "der Generator-Diff.",
        "",
        "### Vorgehen",
        "",
        "- [ ] `python3 codegen/generate.py --refresh`, Diff durchsehen (`git diff --stat`, `codegen/OPERATIONS.md`)",
        "- [ ] Offline-Prüfung aus `AGENTS.md` (Regel 5)",
        "- [ ] Test-Instanz mit der neuen Version anfordern, Live-Tests laufen lassen (`docs/entwicklung.md`, "
        "„Tests gegen eine echte Instanz“)",
        "- [ ] Abweichungen im Generator ausgleichen, `docs/testbericht.md` und `CHANGELOG.md` ergänzen",
        "- [ ] Inkompatible Änderungen → Minor-Version",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--summary", type=Path, help="write the Markdown summary here")
    ap.add_argument("--github-output", type=Path, help="append step outputs here")
    args = ap.parse_args()

    stored_info = json.loads(INFO_FILE.read_text())
    old_version = (str(stored_info.get("version")), str(stored_info.get("build")))
    info = fetch_json(INFO_URL)
    new_version = (str(info.get("version")), str(info.get("build")))
    version_changed = new_version != old_version

    spec_changed = False
    d = None
    if version_changed:
        old_spec = json.loads(lzma.decompress(SPEC_FILE.read_bytes()))
        new_spec = fetch_json(SPEC_URL)
        spec_changed = old_spec != new_spec
        if spec_changed:
            d = diff(old_spec, new_spec)

    needs_update = version_changed and spec_changed
    print(
        f"stored {old_version[0]} (build {old_version[1]}), demo {new_version[0]} (build {new_version[1]}); "
        f"version changed: {version_changed}, spec changed: {spec_changed}",
        file=sys.stderr,
    )
    if args.summary and d is not None:
        args.summary.write_text(summary(old_version, new_version, d))
    if args.github_output:
        with args.github_output.open("a") as out:
            out.write(f"needs_update={str(needs_update).lower()}\n")
            out.write(f"version_changed={str(version_changed).lower()}\n")
            out.write(f"spec_changed={str(spec_changed).lower()}\n")
            out.write(f"version={new_version[0]}\nbuild={new_version[1]}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
