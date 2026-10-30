# churchtools-api

Ein Client für die REST-API von [ChurchTools](https://church.tools), für **Python** und **Rust**. Der Kern ist in
Rust geschrieben; das Python-Paket nutzt ihn für HTTP, Login-Token, Rate-Limit, Wiederholungen und Paginierung und
liefert Pydantic-Modelle. Beide Varianten entstehen aus derselben API-Beschreibung und decken die gesamte API ab:
849 Operationen und 1110 Modelle (ChurchTools 3.138.1).

*A ChurchTools REST API client for Python and Rust, generated from the official OpenAPI description. The
documentation is in German.*

churchtools-api ist ein inoffizielles Projekt und gehört nicht zu ChurchTools. Es ist nicht verwandt mit dem
PyPI-Paket `churchtools`.

**Dokumentation:** [churchtools-api.github.io/churchtools-api](https://churchtools-api.github.io/churchtools-api/)
mit Einstieg, Grundlagen, Beispielprojekten und der vollständigen Referenz. Jedes Beispiel gibt es für Python und
Rust. Alle Aufrufe stehen in
[`codegen/OPERATIONS.md`](https://github.com/churchtools-api/churchtools-api/blob/main/codegen/OPERATIONS.md),
die Rust-API zusätzlich auf [docs.rs](https://docs.rs/churchtools-api).

## Beispiel

```python
import datetime as dt
import churchtools_api as ct

client = ct.Client("https://meinegemeinde.church.tools", token="...")   # oder ct.Client.from_env()

for event in client.events.list(from_=dt.date(2026, 11, 1), to=dt.date(2026, 11, 30), include="event_services"):
    print(event.start_date, event.name, [s.name for s in event.event_services or []])

for person in client.persons.list(last_name="Müller"):        # paginiert, Seiten werden bei Bedarf nachgeladen
    print(person.first_name, person.model_extra)              # model_extra: eigene DB-Felder der Instanz

client.groups.members.list(42)                                 # Unterressourcen
client.persons.create(department_ids=[1], first_name="Ben")   # Body als Keyword-Argumente
client.files.create("person", "7", files=[ct.Upload.from_path("brief.pdf")])   # Datei hochladen
```

```rust
use churchtools_api::{Client, queries::GetEventsQuery};

let client = Client::new("https://meinegemeinde.church.tools", Some("...".into()))?;
let query = GetEventsQuery { from: Some("2026-11-01".parse()?), to: Some("2026-11-30".parse()?), ..Default::default() };
for event in client.events().list_with(&query)? {
    println!("{} {}", event.start_date, event.name);
}
```

## Installation

```bash
pip install churchtools-api        # Python ab 3.10
cargo add churchtools-api          # Rust ab 1.88
```

Für Linux, macOS und Windows gibt es fertige Python-Wheels. Wo keins passt, und für Rust immer, wird aus dem
Quellcode gebaut; dafür braucht es eine [Rust-Toolchain](https://rustup.rs) und einen C-Compiler (für die
TLS-Bibliothek). Details stehen in der Doku unter „Installation“.

## Was der Client übernimmt

| | |
|---|---|
| HTTP und Anmeldung | Login-Token als `Authorization: Login <token>`; `login_with_password` für Tests und interaktive Werkzeuge |
| Sicherheit | nur `https://` (Ausnahme: `localhost`); Token erscheint nicht in Debug-Ausgaben oder Fehlermeldungen; Weiterleitungen, die ein POST in ein GET verwandeln würden, werden nicht verfolgt |
| Rate-Limit und Wiederholungen | `min_interval` als Mindestabstand zwischen Anfragen; `429` wird nach `Retry-After` wiederholt, `502`/`503`/`504` für idempotente Methoden |
| Zeitlimits | `timeout` (30 s), `connect_timeout` (10 s), `max_response_size` (256 MiB) |
| Paginierung | Listen werden seitenweise nachgeladen, sobald man sie durchläuft; ab der zweiten Seite wird die nächste im Hintergrund angefordert (`prefetch(False)` schaltet das ab) |
| Fehler | Python: `NotFound`, `Unauthorized`, `Forbidden`, `UnprocessableEntity`, … mit `message`, `message_key`, `errors`; Rust: `Error` mit `is_not_found()`, `status()`, `api()` |
| Typen | Python: Pydantic-Modelle, unbekannte Felder in `model_extra`; Rust: serde-Structs mit `extra` |
| Abweichungen der API von der Spec | werden ausgeglichen, z. B. Zahlen als String, PHP-Nulldatum, `[]` für ein leeres Objekt, Array-Parameter mit `[]` |

## ChurchTools-Versionen und Kompatibilität

Der Code ist aus der API-Beschreibung von ChurchTools 3.138.1 erzeugt (`API_VERSION`). Gegen andere Versionen
funktioniert er, soweit die API gleich ist: Neue Felder landen in `model_extra`/`extra`, neue Enum-Werte in
Antworten sind erlaubt, fehlende Endpunkte antworten mit `404`.

Die Paketversion folgt [SemVer](https://semver.org/lang/de/). Das Projekt startet mit 0.1.0; vor 1.0 kann jede
Minor-Version inkompatible Änderungen enthalten, insbesondere wenn der Code für eine neue ChurchTools-Version neu
erzeugt wird. Änderungen stehen in [`CHANGELOG.md`](https://github.com/churchtools-api/churchtools-api/blob/main/CHANGELOG.md).

## Stand und Vorgehen

Das Projekt ist jung und experimentell. Was bisher geschehen ist und was geplant ist:

- **Eigener Generator statt eines fertigen:** Der Code entsteht mit einem projekteigenen Generator
  (`codegen/`) aus der OpenAPI-Beschreibung von ChurchTools, nicht mit `openapi-generator` o. Ä. Der Grund:
  Die Spec setzt Schemas ohne `$ref` ein (der Generator gewinnt die Namen wie `Person` oder `Event` zurück),
  die API weicht an einigen Stellen vom Server ab (der Generator gleicht das aus), und Python und Rust sollen
  dieselbe Form haben. Aus derselben Zwischendarstellung entstehen auch Doku und Tests. Das ist bei gepflegten
  SDKs üblich, bedeutet aber auch, dass der Generator selbst gepflegt werden muss.
- **Getestet und durchgesehen, aber nicht in der Breite erprobt:** Alle Lese-Endpunkte und 188
  Schreib-Endpunkte sind gegen eine ChurchTools-Demo-Instanz getestet; die aufgezeichneten Antworten dienen als
  Offline-Tests für Python und Rust ([`docs/testbericht.md`](https://github.com/churchtools-api/churchtools-api/blob/main/docs/testbericht.md)). Der Code wurde zu API-Form,
  Fehlerbehandlung und Umgang mit Zugangsdaten durchgesehen. Das ersetzt aber keine Erfahrung mit echten
  Instanzen und echten Daten: Vor einer produktiven Verwendung solltest du die Aufrufe, die du brauchst, selbst
  gegen eine [Demo-Instanz](https://church.tools/en/test-churchtools/) oder eine Testkopie deiner Instanz prüfen,
  insbesondere alles, was schreibt.
- Mit jeder neuen ChurchTools-Version soll die Kompatibilität erneut geprüft werden. Eine Möglichkeit, eine
  Version vor ihrer Veröffentlichung zu testen, gibt es derzeit nicht; die Prüfung geschieht also, sobald die
  Demo-Instanz die neue Version hat.
- Die Abhängigkeiten (reqwest, rustls, pydantic, …) werden gelegentlich aktualisiert.
- Bei der Entwicklung wurde [Claude Code](https://claude.com/claude-code) eingesetzt, unter anderem für den
  Generator, die Tests und die Dokumentation. Entwurf, Entscheidungen und Prüfung liegen beim Autor.

## Bekannte Grenzen

- **Pflichtfelder:** Die Modelle übernehmen `required` aus der Spec. Fehlt einem echten Objekt ein Pflichtfeld,
  schlägt der Aufruf mit `DecodeError` fehl. Alle aufgezeichneten Antworten dekodieren; für Daten, die die Demo
  nicht hat, bleibt ein Restrisiko.
- **Unions in Rust:** Bodies und Felder mit mehreren möglichen Typen sind in Rust `serde_json::Value`;
  in Python sind sie typisiert.
- **Pfadparameter in Rust** sind `impl Display`, die IDE zeigt also keinen ID-Typ.
- **Doppelte Parameter:** Einige Endpunkte nehmen denselben Wert in Query und Body (`groups.duplicate`: `new_name`
  und `new_name_2`) oder in Pfad und Body (`posts.comments.create`: `post_id` und `post_id_2`).
- **Namen aus der Position:** Schemas ohne Namen in der Spec heißen nach ihrer Stelle, z. B. `PostPersonsBody`.
- **Größe:** `models.py` und `_resources.py` haben je über 20 000 Zeilen; `import churchtools_api` dauert etwa 0,3 s.
- **Sprache:** Die Doku ist deutsch, die Beschreibungen aus der Spec (Hover-Texte, Referenz) sind englisch.
- **Nur synchron:** Einen Async-Client gibt es noch nicht; er ließe sich ergänzen, ohne die synchrone API zu ändern.
- **Geschwindigkeit in Python:** Einzelne Anfragen sind durch den Rust-Transport 2–6× billiger als mit requests oder
  httpx; bei großen Listen bestimmt das Dekodieren in Pydantic-Modelle die Zeit, und das Paket ist dort so schnell wie
  eine gute reine Python-Lösung, nicht schneller. Rust kann daran nichts ändern, solange Python echte Pydantic-Modelle
  bekommt (der größte Posten ist das Erzeugen der Python-Objekte, nicht die Validierung); das ist eine bewusste
  Entscheidung. Gegen eine echte Instanz verschwindet beides ohnehin in der Netzwerkzeit, siehe
  [`benchmarks/README.md`](https://github.com/churchtools-api/churchtools-api/blob/main/benchmarks/README.md).

## Mitmachen

Fehlermeldungen und Vorschläge sind willkommen, siehe [`CONTRIBUTING.md`](https://github.com/churchtools-api/churchtools-api/blob/main/CONTRIBUTING.md). Wie man das Projekt
baut, testet und den Generator benutzt, steht in [`docs/entwicklung.md`](https://github.com/churchtools-api/churchtools-api/blob/main/docs/entwicklung.md). Sicherheitslücken
bitte nicht öffentlich melden, sondern wie in [`SECURITY.md`](https://github.com/churchtools-api/churchtools-api/blob/main/SECURITY.md) beschrieben.

## Lizenz

Der Code steht unter der [MIT-Lizenz](https://github.com/churchtools-api/churchtools-api/blob/main/LICENSE). Die generierten Dateien beruhen auf der API-Beschreibung
„ChurchTools REST API“ von ChurchTools, die unter [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
steht; für sie gilt zusätzlich diese Lizenz. Welche Dateien das sind und was geändert wurde, steht in
[`NOTICE`](https://github.com/churchtools-api/churchtools-api/blob/main/NOTICE). Lizenzangabe der Pakete: `MIT AND CC-BY-4.0`.

churchtools-api ist kein offizielles Produkt der ChurchTools Innovations GmbH.
