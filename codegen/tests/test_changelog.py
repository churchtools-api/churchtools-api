"""CHANGELOG.md follows the fixed per-version format that the page "Änderungen je Version" relies on."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import changelog  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
GOOD = """# Changelog

## [0.2.0] – 2026-11-22

ChurchTools 3.138.3 (Build 32945) · 850 Operationen · 1110 Modelle

Ein Satz.

### Neu

- etwas
  über zwei Zeilen

### Korrigiert

- ein Fehler
"""


def test_repository_changelog_has_the_format() -> None:
    releases = changelog.parse((ROOT / "CHANGELOG.md").read_text())
    assert releases[-1].version == "0.1.0"


def test_parses_a_release() -> None:
    (r,) = changelog.parse(GOOD)
    assert (r.version, r.date, r.churchtools, r.build, r.operations, r.models) == (
        "0.2.0", "2026-11-22", "3.138.3", "32945", 850, 1110,
    )
    assert list(r.sections) == ["Neu", "Korrigiert"]
    assert r.summary == "Ein Satz."


@pytest.mark.parametrize(
    "old, new",
    [
        ("### Korrigiert", "### Fixed"),  # unknown section
        ("### Neu\n\n- etwas\n  über zwei Zeilen\n\n### Korrigiert\n\n- ein Fehler",
         "### Korrigiert\n\n- ein Fehler\n\n### Neu\n\n- etwas"),  # wrong order
        ("ChurchTools 3.138.3 (Build 32945) · ", "ChurchTools 3.138.3 · "),  # facts line
        ("Ein Satz.\n", ""),  # no summary
        (" – 2026-11-22", ""),  # released version without date
        ("- ein Fehler", "ein Fehler"),  # not a list
    ],
)
def test_rejects_deviations(old: str, new: str) -> None:
    with pytest.raises(changelog.FormatError):
        changelog.parse(GOOD.replace(old, new))
