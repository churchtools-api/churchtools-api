# churchtools-rs

Ein synchroner Client für die ChurchTools-REST-API. Der Kern ist in Rust geschrieben, dazu gibt es ein Python-Paket mit Pydantic-Modellen.
Das Projekt ist experimentell und deckt die gesamte API ab: 849 Operationen und 1110 Modelle (ChurchTools 3.138.0).
Es ist ein inoffizielles Projekt und gehört nicht zu ChurchTools.

**Dokumentation:** [`docs/site/index.html`](docs/site/index.html) mit Einstieg, Grundlagen, Projekten und der
vollständigen Referenz. Jedes Beispiel gibt es für Python und Rust.

```python
import datetime as dt
import churchtools_rs as ct

client = ct.Client("https://meinegemeinde.church.tools", token="...")   # oder ct.Client.from_env()

for event in client.events.list(from_=dt.date(2026, 11, 1), to=dt.date(2026, 11, 30), include="event_services"):
    print(event.start_date, event.name, [s.name for s in event.event_services or []])

for person in client.persons.list(last_name="Müller"):        # paginiert, Seiten werden bei Bedarf nachgeladen
    print(person.first_name, person.model_extra)              # model_extra: eigene DB-Felder der Instanz

client.groups.members.list(42)                                 # Unterressourcen
client.persons.create(department_ids=[1], first_name="Ben")   # Body als Keyword-Argumente
client.files.create("person", "7", files=[ct.Upload.from_path("brief.pdf")])   # Datei hochladen
```

Alle Aufrufe stehen in [`codegen/OPERATIONS.md`](codegen/OPERATIONS.md).

Für Skripte mit vielen Anfragen lässt sich ein Mindestabstand setzen: `ct.Client(..., min_interval=0.25)` bzw.
`Client::new(..)?.with_min_interval(Duration::from_millis(250))`. Antwortet der Server mit `429`, wartet der Client
die verlangte Zeit und versucht es erneut, ebenso bei `502`/`503`/`504` für idempotente Methoden (nicht bei POST). Für Tests gibt es `login_with_password(user, password)`.

Der Client verlangt `https://`, damit der Token nicht unverschlüsselt übertragen wird. `http://` ist nur für `localhost`
und Loopback-Adressen erlaubt, für andere Hosts nur ausdrücklich mit `allow_insecure_http=True` bzw.
`Client::builder(url).allow_insecure_http(true)`.

## Installation

Fertige Pakete gibt es noch nicht. Python (ab 3.10, mit [Rust-Toolchain](https://rustup.rs) ab 1.88):
`pip install ./python` aus einem Checkout. Rust: `churchtools-core = { git = "…" }` oder als Pfad-Abhängigkeit.
Details stehen in der Doku unter „Installation“.

## Versionen

Der Code ist aus der API-Beschreibung von ChurchTools 3.138.0 erzeugt (`API_VERSION`). Gegen andere Versionen
funktioniert er, soweit die API gleich ist: Neue Felder landen in `model_extra`/`extra`, neue Enum-Werte in
Antworten sind erlaubt, fehlende Endpunkte antworten mit `404`. Die Paketversion folgt SemVer, vor 1.0 kann jede
Minor-Version inkompatibel sein. Änderungen stehen in [`CHANGELOG.md`](CHANGELOG.md). Für eine neue ChurchTools-Version
lädt `python3 codegen/generate.py --refresh` die Spec neu; danach zeigen die Tests, was sich geändert hat.

## Aufbau

```
core/      churchtools-core: Rust-Crate (reqwest blocking + serde)
python/    churchtools-rs:  PyO3-Erweiterung `_core` + Python-Paket `churchtools_rs`
codegen/   generate.py:     openapi.json -> Rust- und Python-Code, OPERATIONS.md, Doku
           guide.py:        handgeschriebene Doku-Texte und Projekt-Beispiele
           examples.py:     erzeugt die Referenz-Beispiele
docs/      site/index.html: generierte Doku-Seite; entwurf.md: ursprüngliche Entscheidungen
```

Die Aufgaben sind so aufgeteilt:

| | Rust (`core`) | Python (`churchtools_rs`) |
|---|---|---|
| HTTP, Login-Token, Timeouts | ✔ (auch für Python) | |
| Rate-Limit (`min_interval`), Retry bei `429`/`5xx` | ✔ (auch für Python) | |
| Paginierung (`meta.pagination`) | ✔ (auch für Python) | Iterator darüber |
| Fehler aus dem Response-Body | `ApiError` | `NotFound`, `Unauthorized`, ... |
| Typen | serde-Structs (generiert) | Pydantic-Modelle (generiert) |
| Endpunkte | `client.events().list(&query)` (generiert) | `client.events.list(...)` (generiert) |

Die Python-Seite verwendet die Rust-Structs nicht. Rust liefert die rohen JSON-Bytes, Pydantic validiert sie direkt
(`validate_json`, ebenfalls in Rust implementiert). Beide Typsysteme entstehen aus derselben Spec.

## Die Spec und wie der Generator damit umgeht

- Quelle: `https://<instanz>/system/runtime/swagger/openapi.json`, öffentlich und ohne Login abrufbar. Die Spec hängt nur an der
  ChurchTools-Version: Bei 3.138.0 ist sie auf demo.church.tools und einer weiteren Instanz byte-identisch.
- Die Spec setzt jedes Schema direkt ein, statt per `$ref` zu verweisen. Jede eingesetzte Kopie ist aber identisch mit einem
  Eintrag in `components.schemas`. Der Generator gleicht das kanonische JSON ab und findet so die Namen (`Event`, `Person`, ...).
  Schemas ohne Gegenstück bekommen einen Namen aus ihrer Position, z. B. `ImageImageOptionCrop`.
- Die echte API weicht an einigen Stellen von der Spec ab. Die Live-Tests gegen eine Demo-Instanz haben diese Stellen
  gefunden. Der Generator gleicht sie aus, Details stehen in [`docs/testbericht.md`](docs/testbericht.md):
  - allgemeine Regeln: `deprecated`-Felder sind nie Pflicht; Zahlen werden als String akzeptiert und umgekehrt;
    `[]` gilt als leeres Objekt (PHP); das PHP-Nulldatum `-0001-11-30…` wird zu `None`; Array-Parameter bekommen `[]`
    im Namen; eine leere 204-Antwort ergibt `None`
  - Einzelkorrekturen in `FIELD_FIXES` und `RESULT_FIXES` in `generate.py`, jeweils mit Beleg
- Zeitstempel schickt der Client immer als `2026-11-01T10:00:00Z`. Der Server lehnt `+00:00` und Sekundenbruchteile ab.
- Felder, die nicht in der Spec stehen, gehen nicht verloren: In Python landen sie in `model_extra`, in Rust in `extra`.

## Bauen und testen

```bash
python3 codegen/generate.py              # generiert Code, Doku und Tests aus codegen/spec/openapi.json.xz
python3 codegen/generate.py --refresh    # Spec der aktuellen ChurchTools-Version herunterladen und ersetzen
pytest codegen/tests                     # Unit-Tests des Generators

cargo test --workspace                   # Unit-Tests, Replay, Doku-Beispiele (Doctests); ohne Netz
cd python
uv venv && uv pip install --group dev     # Entwicklungswerkzeuge aus [dependency-groups] in pyproject.toml
maturin develop                          # baut _core und installiert das Paket editierbar
pytest tests                             # ohne Netz: Fake-Server, Replay, alle Doku-Beispiele ausgeführt
mypy --strict churchtools_rs tests       # inkl. aller Python-Beispiele der Doku
```

### Doku-Beispiele werden ausgeführt

Jedes Beispiel steht nur einmal im Generator (`codegen/examples.py`, `codegen/guide.py`). Daraus entstehen die
Doku-Seite und die Tests:

- **Rust:** Jede generierte Methode trägt ihr Beispiel als Doctest im `///`-Kommentar; RustRover zeigt es beim
  Überfahren an. `cargo test --doc` führt es gegen die aufgezeichnete Antwort aus (`replay`-Feature, nur für die
  eigenen Tests) oder kompiliert es nur (`no_run`), wenn es keine Aufzeichnung gibt.
- **Python:** Das Beispiel steht im Docstring. `tests/test_doc_examples.py` führt alle Beispiele gegen einen lokalen
  Replay-Server aus (`tests/replay.py`); `mypy --strict` prüft zusätzlich alle Beispiele statisch.
- Beispiele aus Einstieg, Grundlagen und Projekten laufen genauso, außer sie sprechen bewusst einen festen Server an.

### Benchmarks

[`benchmarks/`](benchmarks/README.md) misst einige typische Aufrufe offline gegen einen lokalen Server, in Rust und
Python, und vergleicht das Python-Paket mit reinen Python-Clients (requests, httpx, urllib3).

### Tests gegen eine echte Instanz

ChurchTools bietet eine kostenlose [Test-Instanz](https://church.tools/en/test-churchtools/) an, die nach drei Tagen
gelöscht wird. Wie man sie anfordert und damit testet, beschreibt die Doku im Kapitel „Testen“. Die Live-Tests legen dort Daten an
und löschen sie wieder; eine Produktivinstanz ist dafür nicht geeignet.

```bash
export CT_URL=https://xyz.church.tools CT_USER=... CT_PASSWORD=...
export CT_MIN_INTERVAL=0.25              # Abstand zwischen Anfragen (Standard 0,25 s = 4 pro Sekunde)
pytest tests/live                        # alle GET-Endpunkte + Schreib-Szenarien, ca. 4 Minuten
python tests/live/summary.py             # Übersicht als Markdown
cargo test -p churchtools-core --test live -- --ignored   # Login, Rate-Limit und Kalender aus Rust
```

- `tests/live/test_read.py` ruft jeden GET-Endpunkt einmal über die generierte API auf. Die IDs dafür sucht ein
  Resolver über die passende Listen-Route (`resolve.py`).
- `tests/live/test_write*.py` sind Szenarien wie „Person anlegen, ändern, archivieren, löschen“. Jedes räumt hinterher auf.
- Erfolgreiche Antworten landen in `fixtures/recorded/`, aus den Szenarien auch die der Schreib-Endpunkte. Daraus werden **Offline-Unit-Tests**: `tests/test_recorded.py`
  validiert sie mit Pydantic, `core/tests/recorded.rs` dekodiert sie in die Rust-Typen. Beide laufen ohne Netz.
- `tests/live/seed.py` legt vor dem Lesetest Daten an, die eine frische Demo nicht hat (Treffen, Tickets, Kontoauszug,
  Sync-Verbindung, …), und entfernt sie danach wieder.
- Die Doku markiert Endpunkte, die noch nicht oder nicht ausreichend getestet sind, mit einem roten Sternchen.
- `fixtures/live-results.json` hält das Ergebnis jedes Endpunkts fest; `tests/live/expectations.py` listet die
  erwarteten Fehler mit Begründung.

## Sync und Async

Eine Python-Methode ist entweder normal (`def`) oder eine Coroutine (`async def`). `client.events.list()` kann also nicht
beides sein. Man braucht zwei Klassen, etwa `Client` und `AsyncClient`. In Rust gilt dasselbe:
`reqwest::blocking` und das asynchrone `reqwest` sind zwei APIs. Der Mehraufwand ist hier trotzdem klein:

- Die Endpunkte sind generiert. Der Generator erzeugt dann jede Methode zweimal, einmal mit `async`/`await`.
- Modelle, Fehler und Query-Aufbau sind für beide Varianten gleich.
- Handgeschrieben wäre nur der Transport: in Rust ein async-Client, in Python die Brücke über `pyo3-async-runtimes`.

Ein späterer Async-Client lässt sich also ergänzen, ohne die synchrone API zu verändern.

## Bekannte Grenzen

- **Pflichtfelder:** Die Modelle übernehmen `required` aus der Spec. Fehlt einem echten Objekt ein Pflichtfeld,
  schlägt der Aufruf mit `DecodeError` fehl. Nach den Korrekturen aus den Live-Tests dekodieren alle
  aufgezeichneten Antworten; für Daten, die die Demo nicht hat, bleibt ein Restrisiko.
- **Unions in Rust:** Bodies und Felder, die mehrere Typen haben können, sind in Rust `serde_json::Value`;
  in Python sind sie typisiert.
- **Pfadparameter in Rust** sind `impl Display`, die IDE zeigt also keinen ID-Typ.
- **Doppelte Parameter:** Einige Endpunkte nehmen denselben Wert in Query und Body (`groups.duplicate`: `new_name`
  und `new_name_2`) oder in Pfad und Body (`posts.comments.create`: `post_id` und `post_id_2`).
- **Namen aus der Position:** Schemas ohne Namen in der Spec heißen nach ihrer Stelle, z. B. `PostPersonsBody`.
- **Größe:** `models.py` und `_resources.py` haben je über 20 000 Zeilen; `import churchtools_rs` dauert etwa 0,3 s.
- **Sprache:** Die Doku ist deutsch, die Beschreibungen aus der Spec (Hover-Texte, Referenz) sind englisch.

## Lizenz

Der Code steht unter der [MIT-Lizenz](LICENSE). Die generierten Dateien beruhen auf der API-Beschreibung
„ChurchTools REST API“ von ChurchTools, die unter [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
steht; für sie gilt zusätzlich diese Lizenz. Welche Dateien das sind und was geändert wurde, steht in
[`NOTICE`](NOTICE). Lizenzangabe der Pakete: `MIT AND CC-BY-4.0`.

churchtools-rs ist kein offizielles Produkt der ChurchTools Innovations GmbH.
