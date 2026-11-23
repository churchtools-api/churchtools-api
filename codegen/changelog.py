"""Reads CHANGELOG.md, checks its fixed per-version format and renders the page docs/site/aenderungen.html.

Every version has the same structure (described at the top of CHANGELOG.md):

    ## [0.2.0] – 2026-11-22                      or  ## [Unreleased]
    ChurchTools 3.138.3 (Build 32945) · 850 Operationen · 1110 Modelle
    One sentence on what the version is about.
    ### Inkompatibel / ### Neu / ### Geändert / ### Korrigiert   (only non-empty ones, in this order)

`parse` raises `FormatError` on any deviation, so the generator (and with it the CI) fails on a malformed entry.
"""

from __future__ import annotations

import re
import typing as _t
from dataclasses import dataclass, field
from pathlib import Path

SECTIONS = ("Inkompatibel", "Neu", "Geändert", "Korrigiert")
SECTION_IDS = {"Inkompatibel": "inkompatibel", "Neu": "neu", "Geändert": "geaendert", "Korrigiert": "korrigiert"}

_HEADING = re.compile(r"^## \[(?P<version>Unreleased|\d+\.\d+\.\d+)\](?: – (?P<date>\d{4}-\d{2}-\d{2}))?$")
_FACTS = re.compile(
    r"^ChurchTools (?P<ct>\d+\.\d+\.\d+) \(Build (?P<build>\d+)\) · (?P<ops>\d+) Operationen · (?P<models>\d+) Modelle$"
)


class FormatError(ValueError):
    pass


@dataclass
class Release:
    version: str  # "Unreleased" or x.y.z
    date: str  # "" for Unreleased
    churchtools: str
    build: str
    operations: int
    models: int
    summary: str
    sections: dict[str, str] = field(default_factory=dict)  # heading -> Markdown body, in SECTIONS order

    @property
    def anchor(self) -> str:
        return "v-unreleased" if self.version == "Unreleased" else "v" + self.version.replace(".", "-")


def parse(text: str) -> list[Release]:
    """The versions of the changelog, newest first."""
    chunks = re.split(r"(?m)^(?=## \[)", text)
    releases = []
    for chunk in chunks[1:]:
        lines = chunk.rstrip().splitlines()
        m = _HEADING.match(lines[0])
        if not m or (m["version"] == "Unreleased") == bool(m["date"]):
            raise FormatError(f"heading must be '## [x.y.z] – YYYY-MM-DD' or '## [Unreleased]': {lines[0]!r}")
        name = m["version"]
        blocks = re.split(r"(?m)^(?=### )", "\n".join(lines[1:]).strip())
        intro = [b.strip() for b in re.split(r"\n\s*\n", blocks[0].strip()) if b.strip()]
        if len(intro) != 2:
            raise FormatError(f"{name}: expected the facts line and one summary paragraph before the first section")
        facts = _FACTS.match(intro[0])
        if not facts:
            raise FormatError(
                f"{name}: first line must be 'ChurchTools x.y.z (Build n) · n Operationen · n Modelle': {intro[0]!r}"
            )
        sections: dict[str, str] = {}
        for block in blocks[1:]:
            heading, _, body = block.partition("\n")
            title = heading[4:].strip()
            if title not in SECTIONS:
                raise FormatError(f"{name}: unknown section {title!r}; allowed: {', '.join(SECTIONS)}")
            if title in sections or any(SECTIONS.index(t) > SECTIONS.index(title) for t in sections):
                raise FormatError(f"{name}: sections must appear once, in the order {', '.join(SECTIONS)}")
            if not body.strip().startswith("- "):
                raise FormatError(f"{name}: section {title!r} must be a list")
            sections[title] = body.strip()
        if not sections:
            raise FormatError(f"{name}: no section")
        releases.append(
            Release(
                version=name,
                date=m["date"] or "",
                churchtools=facts["ct"],
                build=facts["build"],
                operations=int(facts["ops"]),
                models=int(facts["models"]),
                summary=" ".join(intro[1].split()),
                sections=sections,
            )
        )
    if not releases:
        raise FormatError("no version sections")
    return releases


def _date_de(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(d)}.{int(m)}.{y}"


def link_reference(html: str, links: dict[str, str]) -> str:
    """Links `<code>` spans that name a method (`events.cancel()`), endpoint (`POST /x`) or model (`Person`, also
    `Person.field`) to the reference."""

    def repl(m: re.Match[str]) -> str:
        text = m.group(1)
        owner = re.split(r"\.|::", text)[0]  # `Person.first_name`, `PatchPersonsIdBody::city` -> the model
        target = links.get(text) or (links.get(owner) if owner[:1].isupper() else None)
        return f'<a href="{target}">{m.group(0)}</a>' if target else m.group(0)

    return re.sub(r"<code>([^<]+)</code>", repl, html)


def page(
    releases: list[Release],
    template: str,
    md: _t.Callable[[str], str],
    esc: _t.Callable[[str], str],
    links: dict[str, str] | None = None,
) -> str:
    """The changelog page; `template` is the main page's template, of which only the styles are reused."""
    links = links or {}
    head = template[: template.index("</style>") + len("</style>")].replace(
        "<title>churchtools-api</title>", "<title>churchtools-api: Änderungen</title>"
    )
    badge = ' <span class="badge-break">inkompatibel</span>'
    nav = "".join(
        f'<li><a href="#{r.anchor}">{"Nächste Version" if r.version == "Unreleased" else esc(r.version)}'
        f'{badge if "Inkompatibel" in r.sections else ""}</a></li>'
        for r in releases
    )
    articles = []
    for i, r in enumerate(releases):
        previous = releases[i + 1] if i + 1 < len(releases) else None
        delta = ""
        if previous:
            d = r.operations - previous.operations
            delta = f" ({'+' if d >= 0 else '−'}{abs(d)})" if d else ""
        title = "Nächste Version (noch nicht veröffentlicht)" if r.version == "Unreleased" else f"Version {esc(r.version)}"
        when = f'<li class="date">{_date_de(r.date)}</li>' if r.date else ""
        sections = "".join(
            f'<div class="change change-{SECTION_IDS[t]}"><h3>{t}</h3>{link_reference(md(body), links)}</div>'
            for t, body in r.sections.items()
        )
        articles.append(
            f'<section class="reference release" id="{r.anchor}">'
            f"<h2>{title}</h2>"
            f'<ul class="facts">{when}'
            f"<li>ChurchTools <b>{esc(r.churchtools)}</b> (Build {esc(r.build)})</li>"
            f"<li><b>{r.operations}</b> Endpunkte{delta}</li><li><b>{r.models}</b> Modelle</li></ul>"
            f'<p class="lead">{esc(r.summary)}</p>{sections}</section>'
        )
    return f"""{head}
<style>
.release .facts .date {{ font-weight: 600; margin-right: .5rem; }}
.change {{ border-left: 3px solid var(--line, #ccc); padding: .1rem 0 .1rem 1rem; margin: 1.25rem 0; }}
.change h3 {{ margin: 0 0 .4rem; font-size: 1rem; text-transform: uppercase; letter-spacing: .04em; }}
.change-inkompatibel {{ border-left-color: #d9480f; }}
.change-inkompatibel h3 {{ color: #d9480f; }}
.change-neu {{ border-left-color: #2f9e44; }}
.change-neu h3 {{ color: #2f9e44; }}
.badge-break {{ font-size: .7rem; color: #d9480f; border: 1px solid currentColor; border-radius: 999px;
  padding: 0 .4rem; margin-left: .3rem; }}
</style>
<div id="app">
  <header class="topbar">
    <a class="brand" href="index.html"><b>churchtools-api</b><span>Änderungen</span></a>
    <button type="button" class="theme-toggle" id="theme-toggle"></button>
  </header>
  <div class="shell">
    <nav class="nav" id="nav" aria-label="Versionen">
      <h2><a href="index.html">Zur Dokumentation</a></h2>
      <h2>Versionen</h2>
      <ul class="nav-ref">{nav}</ul>
    </nav>
    <main id="main">
      <div class="inner">
        <section class="hero" id="start">
          <h1>Änderungen je Version</h1>
          <p class="lead">Was sich von Version zu Version an churchtools-api ändert. Jede Version nennt die
          ChurchTools-Version, aus der der Code erzeugt ist, und gliedert die Änderungen immer gleich:
          <b>Inkompatibel</b> (mit dem, was beim Umstieg zu ändern ist), <b>Neu</b>, <b>Geändert</b> und
          <b>Korrigiert</b>. Leere Abschnitte fehlen. Methoden und Modelle führen in die
          <a href="index.html#referenz">Referenz</a> der aktuellen Version.</p>
        </section>
        {"".join(articles)}
      </div>
    </main>
  </div>
</div>
<script>
(() => {{
  const t = document.getElementById("theme-toggle");
  const sys = matchMedia("(prefers-color-scheme: dark)");
  const dark = () => (document.documentElement.dataset.theme || (sys.matches ? "dark" : "light")) === "dark";
  const show = () => {{ t.textContent = dark() ? "☀" : "☾"; t.title = dark() ? "Helles Design" : "Dunkles Design"; }};
  t.addEventListener("click", () => {{
    const next = dark() ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {{ localStorage.setItem("ct-theme", next); }} catch (e) {{}}
    show();
  }});
  show();
}})();
</script>"""


def build(
    root: Path,
    template: str,
    md: _t.Callable[[str], str],
    esc: _t.Callable[[str], str],
    links: dict[str, str] | None = None,
) -> list[Release]:
    """Writes docs/site/aenderungen.html; `links` maps method calls and model names to reference URLs."""
    releases = parse((root / "CHANGELOG.md").read_text())
    out = root / "docs" / "site" / "aenderungen.html"
    out.write_text(
        '<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"</head>\n<body>\n{page(releases, template, md, esc, links)}\n</body>\n</html>\n"
    )
    return releases
