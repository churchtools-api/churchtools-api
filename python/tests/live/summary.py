"""Prints an overview of `fixtures/live-results.json` as Markdown.

    python tests/live/summary.py > ../docs/live-ergebnisse.md
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CATALOG = {e["op_id"]: e for e in json.loads((Path(__file__).parent / "operations.json").read_text())}


def main() -> None:
    results = json.loads((ROOT / "fixtures" / "live-results.json").read_text())
    by_method: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for op, entry in CATALOG.items():
        outcome = results.get(op, {}).get("outcome", "not called")
        by_method[entry["method"]][outcome] += 1
    outcomes = sorted({o for c in by_method.values() for o in c})
    print("| Methode | " + " | ".join(outcomes) + " | gesamt |")
    print("|---|" + "---:|" * (len(outcomes) + 1))
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        c = by_method[method]
        print(f"| {method} | " + " | ".join(str(c[o] or "") for o in outcomes) + f" | {sum(c.values())} |")
    print()

    for title, wanted in (
        ("Fehler", lambda o: o.startswith("http-") or o == "decode-error"),
        ("Erwartete Fehler", lambda o: o == "expected-error"),
        ("Nicht auflösbar (keine passenden Daten)", lambda o: o in ("unresolved", "skipped")),
    ):
        rows = [(op, r) for op, r in sorted(results.items()) if wanted(r["outcome"])]
        if not rows:
            continue
        print(f"### {title} ({len(rows)})\n")
        print("| Endpunkt | Ergebnis | Meldung |")
        print("|---|---|---|")
        for op, r in rows:
            e = CATALOG[op]
            msg = r.get("reason") or r.get("message") or r.get("error", "").splitlines()[0:2]
            msg = " ".join(msg) if isinstance(msg, list) else msg
            print(f"| `{e['method']} {e['path']}` | {r['outcome']} | {str(msg or '').replace('|', '/')[:160]} |")
        print()

    undocumented: dict[str, set[str]] = collections.defaultdict(set)
    for r in results.values():
        for model, fields in (r.get("undocumented") or {}).items():
            undocumented[model].update(fields)
    if undocumented:
        print(f"### Undokumentierte Felder in Antworten ({len(undocumented)} Modelle)\n")
        print("| Modell | Felder |")
        print("|---|---|")
        for model, fields in sorted(undocumented.items()):
            print(f"| `{model}` | {', '.join(f'`{f}`' for f in sorted(fields))} |")


if __name__ == "__main__":
    main()
