"""Handwritten part of the documentation: introduction, basics and projects.

Each section has a short text (a small Markdown subset, see docs.md) and
optionally a Python/Rust example pair. All examples are type-checked together
with the generated reference examples.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Section:
    id: str
    title: str
    text: str
    python: str = ""
    rust: str = ""
    aside: str = ""  # text shown below the code


@dataclass
class Chapter:
    id: str
    title: str
    intro: str
    sections: list[Section] = field(default_factory=list)


START = Chapter(
    "einstieg",
    "Einstieg",
    "Vom Installieren bis zum ersten Aufruf in wenigen Minuten.",
    [
        Section(
            "ueberblick",
            "Worum es geht",
            """
`churchtools-api` ist ein Client für die REST-API von [ChurchTools](https://church.tools): Personen, Gruppen,
Kalender, Events, Dienste, Lieder, Finanzen und alles Weitere, was die API anbietet.

Es gibt ihn für zwei Sprachen. Beide entstehen aus derselben API-Beschreibung und funktionieren gleich:

- **Python**: Rückgaben sind Pydantic-Modelle mit Autovervollständigung in der IDE.
- **Rust**: Rückgaben sind serde-Structs, Fehler sind ein `Result`.

Wähle oben rechts deine Sprache. Alle Beispiele auf dieser Seite wechseln mit.
""",
        ),
        Section(
            "voraussetzungen",
            "Was du brauchst",
            """
- **Die Adresse deiner ChurchTools-Instanz**, z. B. `https://meinegemeinde.church.tools`.
- **Ein Login-Token** für alles, was nicht öffentlich ist. Das Token gehört zu einer Person in ChurchTools,
  und der Client sieht genau das, was diese Person sehen darf. Für Skripte lohnt sich ein eigener
  Benutzer mit passend eingeschränkten Rechten.

Öffentliche Daten wie öffentliche Kalender funktionieren auch ohne Token. Damit kannst du sofort loslegen.
""",
        ),
        Section(
            "installation",
            "Installation",
            """
Die Pakete heißen in beiden Sprachen `churchtools-api`:

- **Python:** `pip install churchtools-api` (ab Python 3.10). Für Linux (x86-64, ARM64, auch musl), macOS
  (Intel und Apple Silicon) und Windows (x86-64) gibt es fertige Wheels; ein Wheel deckt alle Python-Versionen
  ab 3.10 ab. Auf anderen Plattformen baut `pip` das Paket aus dem Quellcode mit
  [maturin](https://www.maturin.rs); dafür braucht es eine [Rust-Toolchain](https://rustup.rs) ab 1.88 und
  einen C-Compiler (für die TLS-Bibliothek; unter Linux `gcc` oder `clang`, unter macOS die
  Xcode-Kommandozeilenwerkzeuge, unter Windows die Visual-Studio-Build-Tools).
- **Rust:** `cargo add churchtools-api` (ab Rust 1.88). Auch hier wird ein C-Compiler gebraucht.

Den neuesten Entwicklungsstand bekommst du direkt aus dem Git-Repository.
""",
            python="""\
pip install churchtools-api

# Entwicklungsstand aus dem Git-Repository (baut aus dem Quellcode)
pip install "churchtools-api @ git+https://github.com/churchtools-api/churchtools-api#subdirectory=python\"""",
            rust="""\
# Cargo.toml
[dependencies]
churchtools-api = "0.1"
# oder der Entwicklungsstand aus dem Git-Repository
churchtools-api = { git = "https://github.com/churchtools-api/churchtools-api" }""",
        ),
        Section(
            "schnellstart",
            "Dein erster Aufruf",
            """
Dieses Programm fragt ab, welche ChurchTools-Version eine Instanz verwendet. Es braucht kein Token und läuft
gegen die öffentliche Demo-Instanz.

Danach bist du startklar. Die folgenden Beispiele zeigen nur noch den Teil, der sich ändert, und
setzen einen fertigen `client` voraus.
""",
            python="""\
import churchtools_api as ct

client = ct.Client("https://demo.church.tools")
info = client.info.get()
print(info.site_name, info.version)""",
            rust="""\
use churchtools_api::Client;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = Client::new("https://demo.church.tools", None)?;
    let info = client.info().get()?;
    println!("{:?} {:?}", info.site_name, info.version);
    Ok(())
}""",
            aside="Ausgabe: `ChuToo Church 3.138.0`",
        ),
    ],
)

BASICS = Chapter(
    "grundlagen",
    "Grundlagen",
    "Die Konzepte, die für jeden Aufruf gelten. Wer sie kennt, findet sich in der ganzen Referenz zurecht.",
    [
        Section(
            "anmeldung",
            "Client und Anmeldung",
            """
Ein Client gehört zu einer Instanz und einem Token. Das Token wird als `Authorization: Login <token>`
mitgeschickt. Du musst dich um nichts weiter kümmern.

Lege das Token nicht in den Quelltext. Am einfachsten liest du es aus den Umgebungsvariablen
`CT_URL` und `CT_TOKEN`.
""",
            python="""\
import churchtools_api as ct

client = ct.Client("https://meinegemeinde.church.tools", token="DEIN_TOKEN")

# besser: CT_URL und CT_TOKEN aus der Umgebung lesen
client = ct.Client.from_env()

me = client.whoami.get()
print(f"Angemeldet als {me.first_name} {me.last_name}")""",
            rust="""\
use churchtools_api::Client;

let client = Client::new("https://meinegemeinde.church.tools", Some("DEIN_TOKEN".into()))?;

// besser: CT_URL und CT_TOKEN aus der Umgebung lesen
let client = Client::from_env()?;

let me = client.whoami().get()?;
println!("Angemeldet als {:?} {:?}", me.first_name, me.last_name);""",
        ),
        Section(
            "drosseln",
            "Anfragen drosseln",
            """
Für Skripte, die viele Anfragen schicken, kannst du einen Mindestabstand zwischen zwei Anfragen
festlegen. So belastest du die Instanz nicht unnötig. Der Abstand gilt auch für Kopien des Clients.

Antwortet der Server mit `429 Too Many Requests`, wartet der Client die verlangte Zeit
(`Retry-After`, höchstens 60 Sekunden) und versucht es bis zu dreimal erneut. Das passiert immer,
auch ohne Mindestabstand. Bei `502`, `503` und `504` wiederholt er lesende und andere idempotente
Anfragen (GET, PUT, DELETE) genauso; ein POST wird nicht wiederholt, weil er sonst doppelt
ausgeführt werden könnte. Kommt keine Verbindung zustande, versucht er es nach einer Sekunde
einmal erneut.

Für Tests gegen eine Demo-Instanz gibt es außerdem `login_with_password`. Es meldet sich mit
Benutzername und Passwort an und holt das Login-Token der Person. In eigenen Skripten ist ein
gespeichertes Token besser.
""",
            python="""\
# höchstens vier Anfragen pro Sekunde
client = ct.Client.from_env(min_interval=0.25)

for person in client.persons.list():
    print(person.id, person.first_name)

# nur für Tests: mit Benutzername und Passwort anmelden
test = ct.Client("https://xyz.church.tools").login_with_password("benutzer", "passwort")""",
            rust="""\
use std::time::Duration;

// höchstens vier Anfragen pro Sekunde
let client = Client::from_env()?.with_min_interval(Duration::from_millis(250));

for person in client.persons().list()? {
    println!("{} {:?}", person.id, person.first_name);
}

// nur für Tests: mit Benutzername und Passwort anmelden
let test = Client::new("https://xyz.church.tools", None)?.login_with_password("benutzer", "passwort")?;""",
        ),
        Section(
            "aufbau",
            "Wie Aufrufe aufgebaut sind",
            """
Jeder Aufruf folgt dem Pfad der API. Aus jedem festen Teil des Pfads wird eine Ressource. Platzhalter
wie `{groupId}` werden zu Argumenten:

| API | Python | Rust |
|---|---|---|
| `GET /groups` | `client.groups.list()` | `client.groups().list()` |
| `GET /groups/{groupId}` | `client.groups.get(42)` | `client.groups().get(42)` |
| `GET /groups/{groupId}/members` | `client.groups.members.list(42)` | `client.groups().members().list(42)` |

Der Methodenname richtet sich nach der HTTP-Methode:

| HTTP | Methode | bedeutet |
|---|---|---|
| GET | `list` / `get` | mehrere lesen / eins lesen |
| POST | `create` | neu anlegen |
| PUT | `update` | ersetzen oder setzen |
| PATCH | `patch` | einzelne Felder ändern |
| DELETE | `delete` | löschen |

Aktionen behalten ihren Namen, z. B. `client.persons.invite(7)` für `POST /persons/{personId}/invite`.
POST-Aufrufe, die nichts anlegen, sondern nur lesen oder berechnen, heißen nach dem, was sie tun:
`client.actions.filter()`, `client.repeat_calculation.calculate()`.

Zusammengeschriebene Pfadteile werden in Wörter getrennt: `/agendatemplates` wird zu `agenda_templates`,
genauso wie `/external-logins` zu `external_logins`.

Einige Bereiche gibt es im Singular und im Plural. Der Plural enthält die Objekte selbst, der Singular die
Stammdaten des Bereichs: `client.groups` sind die Gruppen, `client.group` ihre Gruppentypen, Rollen und
Kategorien. Genauso `persons`/`person`, `events`/`event` und `posts`/`post`.
""",
            python="""\
group = client.groups.get(42)
print(group.name)

for member in client.groups.members.list(42):
    print(member.person.title)""",
            rust="""\
let group = client.groups().get(42)?;
println!("{}", group.name);

for member in client.groups().members().list(42)? {
    println!("{}", member.person.title);
}""",
        ),
        Section(
            "parameter",
            "Parameter übergeben",
            """
Es gibt drei Arten von Parametern:

- **Pfad**: Platzhalter im Pfad. Sie stehen vorne und haben keinen Namen.
- **Query**: Filter und Optionen wie `from`, `to`, `limit`. In Python sind das Schlüsselwort-Argumente.
  In Rust gibt es dafür eine `…Query`-Struktur. Sind alle Filter optional, hat die Methode zwei Varianten:
  `list()` ohne Filter und `list_with(&query)` mit Filtern. `..Default::default()` füllt alles, was du nicht setzt.
- **Body**: Daten zum Anlegen oder Ändern. In Python sind es ebenfalls Schlüsselwort-Argumente, in Rust ein
  Modell als Struct-Literal. Auch hier füllt `..Default::default()` alle Felder, die du nicht setzt.

Die Namen sind in Python im üblichen snake_case geschrieben (`first_name` statt `firstName`). Wo ein Name ein
Python-Schlüsselwort ist, kommt ein Unterstrich dazu: `from_`.

Hat ein Wert eine feste Auswahl (z. B. `group_member_status`: `active`, `requested`, `waiting`, …), steht sie
in der Doku unter „Allowed values“. In Python ist das Argument als `Literal[...]` typisiert: Die IDE schlägt
die Werte vor, und mypy meldet Tippfehler. In Antworten ist zusätzlich jeder `str` erlaubt, damit ein neuer Wert
einer neueren ChurchTools-Version nicht zu einem Fehler führt. In Rust sind solche Werte `String`.
""",
            python="""\
import datetime as dt

persons = client.persons.list(last_name="Müller", is_archived=False)

events = client.events.list(from_=dt.date(2026, 11, 1), to=dt.date(2026, 11, 30))

client.persons.patch(7, city="Esslingen", zip="73728")""",
            rust="""\
let query = GetPersonsQuery {
    last_name: Some("Müller".into()),
    is_archived: Some(false),
    ..Default::default()
};
let persons = client.persons().list_with(&query)?;

let query = GetEventsQuery {
    from: Some("2026-11-01".parse()?),
    to: Some("2026-11-30".parse()?),
    ..Default::default()
};
let events = client.events().list_with(&query)?;

let body = models::PatchPersonsIdBody {
    city: Some("Esslingen".into()),
    zip: Some("73728".into()),
    ..Default::default()
};
client.persons().patch(7, &body)?;""",
        ),
        Section(
            "rueckgaben",
            "Rückgabewerte und Modelle",
            """
Antworten kommen als typisierte Objekte zurück. Die Felder heißen wie in der API, nur in snake_case.

Jede ChurchTools-Instanz kann eigene Datenbankfelder haben, die in keiner Beschreibung stehen. Diese
Felder gehen nicht verloren: In Python liegen sie in `model_extra`, in Rust im Feld `extra`.

Willst du ein Objekt weitergeben oder speichern, wandelst du es in ein Dict oder JSON um.
""",
            python="""\
person = client.persons.get(7)
print(person.first_name, person.birthday)

# eigene Felder der Instanz
print(person.model_extra)

# als dict / JSON (mit den Feldnamen der API)
data = person.model_dump(exclude_none=True)
text = person.model_dump_json()""",
            rust="""\
let person = client.persons().get(7)?;
println!("{:?} {:?}", person.first_name, person.birthday);

// eigene Felder der Instanz
println!("{:?}", person.extra);

// als JSON (mit den Feldnamen der API)
let text = serde_json::to_string(&person)?;""",
        ),
        Section(
            "listen",
            "Listen und Seiten",
            """
Große Listen liefert ChurchTools seitenweise. Der Client blättert für dich:

- In **Python** bekommst du einen `Paginator`. Er lädt Seiten erst, wenn du sie brauchst: `first()`
  holt nur das erste Element, `to_list()` alles. Brichst du die Schleife ab, werden keine weiteren
  Seiten geladen.
- In **Rust** liefert `list()` gleich einen `Vec` mit allen Einträgen. `list_iter(&query)` lädt dagegen
  wie in Python erst beim Iterieren nach; jedes Element ist ein `Result`.

Mit `limit` bestimmst du, wie viele Einträge pro Seite geladen werden (höchstens 100).

Ab der zweiten Seite fordert der Client die jeweils nächste Seite in einem Hintergrund-Thread an,
während du die aktuelle verarbeitest. Die Wartezeit auf den Server überlappt so mit dem Dekodieren
und deiner Verarbeitung. Brichst du eine Schleife mitten in einer späteren Seite ab, kann dadurch
eine Anfrage mehr unterwegs sein; ihre Antwort wird verworfen. Mit `.prefetch(False)` (Python) bzw.
`.prefetch(false)` (Rust) wird jede Seite erst angefordert, wenn sie gebraucht wird.

Die Seiten werden nacheinander abgerufen. Ändert sich die Liste währenddessen, etwa weil
jemand eine Person anlegt oder löscht, kann ein Eintrag doppelt vorkommen oder fehlen. Für
Abgleiche lohnt es sich deshalb, nach `id` zu deduplizieren. Eine leere Seite beendet das
Blättern, auch wenn der Server mehr Seiten ankündigt.

Der Client ist synchron. In Rust darfst du ihn nicht direkt in `async`-Code (Tokio) aufrufen,
sondern nur über `tokio::task::spawn_blocking`.
""",
            python="""\
for person in client.persons.list(limit=100):
    print(person.last_name)
    if person.last_name == "Zimmermann":
        break               # weitere Seiten werden nicht mehr geladen

first = client.groups.list().first()
all_groups = client.groups.list().to_list()""",
            rust="""\
let query = GetPersonsQuery { limit: Some(100), ..Default::default() };
for person in client.persons().list_iter(&query) {
    let person = person?;
    println!("{:?}", person.last_name);
    if person.last_name.as_deref() == Some("Zimmermann") {
        break;              // weitere Seiten werden nicht mehr geladen
    }
}

let all_groups = client.groups().list()?;""",
        ),
        Section(
            "datum",
            "Datum und Uhrzeit",
            """
Datumswerte (Geburtstage, ganztägige Termine) sind reine Kalenderdaten. Zeitpunkte kommen immer in **UTC**
und mit Zeitzone. Für die Anzeige rechnest du sie in die lokale Zeit um.

Termine können beides sein: Ganztägige Termine haben nur ein Datum, alle anderen einen Zeitpunkt.
""",
            python="""\
import datetime as dt
from zoneinfo import ZoneInfo

berlin = ZoneInfo("Europe/Berlin")
event = client.events.get(42)
print(event.start_date.astimezone(berlin))   # 2026-11-01 10:00:00+01:00

# date | datetime: erst prüfen, was es ist
appointment = client.calendars.appointments.get_occurrence(42, dt.date(2026, 11, 1))
start = appointment.appointment.calculated.start_date
if isinstance(start, dt.datetime):
    print("um", start.astimezone(berlin).strftime("%H:%M"))
else:
    print("ganztägig am", start)""",
            rust="""\
use churchtools_api::chrono::Local;

let event = client.events().get(42)?;
println!("{}", event.start_date.with_timezone(&Local));

// DateOrDateTime: erst prüfen, was es ist
let appointment = client.calendars().appointments()
    .get_occurrence(42, "2026-11-01")?;
match appointment.appointment.calculated.start_date {
    DateOrDateTime::DateTime(t) => println!("um {}", t.with_timezone(&Local).format("%H:%M")),
    DateOrDateTime::Date(d) => println!("ganztägig am {d}"),
}""",
        ),
        Section(
            "fehler",
            "Fehler behandeln",
            """
Antwortet ChurchTools mit einem Fehler, bekommst du die Meldung des Servers, auf Wunsch auch in der
übersetzten Fassung (`translated_message`). In Python gibt es für die häufigsten Statuscodes eigene
Ausnahmen, siehe die [Fehlerübersicht](#fehlercodes). In Rust gibt es dafür `is_not_found()`, `is_unauthorized()`,
`is_forbidden()`, `is_timeout()` und `status()`. Weil neue Fehlerarten dazukommen können, braucht ein `match`
über `Error` immer einen Zweig `_` bzw. `Err(e)`.
""",
            python="""\
try:
    person = client.persons.get(999999)
except ct.NotFound:
    print("Diese Person gibt es nicht.")
except ct.Unauthorized:
    print("Token fehlt oder ist abgelaufen.")
except ct.ApiError as e:
    print(e.status, e.translated_message)""",
            rust="""\
use churchtools_api::Error;

match client.persons().get(999999) {
    Ok(person) => println!("{:?}", person.first_name),
    Err(e) if e.is_not_found() => println!("Diese Person gibt es nicht."),
    Err(e) if e.is_unauthorized() => println!("Token fehlt oder ist abgelaufen."),
    Err(Error::Api(e)) => println!("{} {:?}", e.status, e.translated_message),
    Err(e) => return Err(e.into()),
}""",
        ),
        Section(
            "weglassen",
            "Felder weglassen oder leeren",
            """
Beim Ändern macht es einen Unterschied, ob ein Feld fehlt oder leer ist:

- **Weggelassen**: Das Feld bleibt, wie es ist. In Python ist das der Standard (`UNSET`), in Rust
  `None`, das `..Default::default()` setzt.
- **`None` / `null`**: Das Feld wird geleert. In Rust haben Felder, die man leeren kann, den Typ
  `Option<Option<T>>`; `Some(None)` schickt `null`.

Felder, die der Client nicht kennt (z. B. eigene DB-Felder), übergibst du in Python mit `extra_body`, in Rust
über das Feld `extra`.
""",
            python="""\
# nur die Stadt ändern, alles andere bleibt
client.persons.patch(7, city="Esslingen")

# Geburtstag löschen
client.persons.patch(7, birthday=None)

# eigenes Datenbankfeld setzen
client.persons.patch(7, extra_body={"konfession": "evangelisch"})""",
            rust="""\
// nur die Stadt ändern, alles andere bleibt
let body = models::PatchPersonsIdBody { city: Some("Esslingen".into()), ..Default::default() };
client.persons().patch(7, &body)?;

// Geburtstag löschen
let body = models::PatchPersonsIdBody { birthday: Some(None), ..Default::default() };
client.persons().patch(7, &body)?;

// eigenes Datenbankfeld setzen
let mut body = models::PatchPersonsIdBody::default();
body.extra.insert("konfession".into(), "evangelisch".into());
client.persons().patch(7, &body)?;""",
        ),
        Section(
            "uploads",
            "Dateien hochladen und herunterladen",
            """
Endpunkte mit Datei-Upload nehmen eine Liste von `Upload`-Objekten. `Upload.from_path` liest eine Datei und
leitet den Dateityp aus der Endung ab; `Upload(name, inhalt, typ)` nimmt Bytes aus dem Speicher.

Downloads (PDF, CSV, Excel, Bilder) kommen als Bytes zurück, die du direkt speichern kannst.
""",
            python="""\
import churchtools_api as ct

# an eine Person anhängen
client.files.create("person", "7", files=[ct.Upload.from_path("brief.pdf")])

# aus dem Speicher
client.files.create("person", "7", files=[ct.Upload("notiz.txt", b"Hallo", "text/plain")])

# herunterladen
data = client.groups.members.get_export(42)
with open("mitglieder.xlsx", "wb") as f:
    f.write(data)""",
            rust="""\
let file = Upload::from_path("brief.pdf")?;
client.files().create("person", 7, &[file])?;

let note = Upload::new("notiz.txt", b"Hallo".to_vec(), "text/plain");
client.files().create("person", 7, &[note])?;

let data = client.groups().members().get_export(42)?;
std::fs::write("mitglieder.xlsx", &data)?;""",
        ),
        Section(
            "zeitlimits",
            "Zeitlimits und große Antworten",
            """
Ohne weitere Angaben gelten diese Grenzen:

| Einstellung | Standard | bedeutet |
|---|---|---|
| `timeout` | 30 s | die ganze Anfrage inklusive Antwort |
| `connect_timeout` | 10 s | nur der Verbindungsaufbau, höchstens `timeout` |
| `max_response_size` | 256 MiB | größere Antworten brechen mit `ResponseTooLarge` ab |

Für große Exporte und Uploads lohnt ein längeres `timeout`. Ein kurzes `connect_timeout` sorgt dafür,
dass eine nicht erreichbare Instanz schnell auffällt. Zu langsame Anfragen enden mit `Timeout`, fehlende
Verbindungen mit `ConnectError`; in Rust prüfst du `is_timeout()` und `is_connect()`.
""",
            python="""\
client = ct.Client(
    "https://meinegemeinde.church.tools",
    token="DEIN_TOKEN",
    timeout=300,            # große Exporte
    connect_timeout=5,
    max_response_size=1024**3,
)""",
            rust="""\
use std::time::Duration;

let client = Client::builder("https://meinegemeinde.church.tools")
    .token(Some("DEIN_TOKEN".into()))
    .timeout(Duration::from_secs(300))
    .connect_timeout(Duration::from_secs(5))
    .max_response_size(1 << 30)
    .build()?;""",
        ),
        Section(
            "rohzugriff",
            "Endpunkte ohne generierte Methode",
            """
Manche Endpunkte stehen nicht in der API-Beschreibung, etwa ganz neue oder interne. Für sie gibt es
`client.request`: Methode, Pfad unterhalb von `/api`, Query und JSON-Body. Zurück kommen die rohen Bytes,
Fehler sind dieselben Ausnahmen wie sonst. Login, Drosselung und Wiederholungen gelten auch hier.

Die Antwort wandelst du mit `json.loads` oder direkt in ein Modell um.
""",
            python="""\
import json

body = client.request("GET", "/persons/7", query={"include": ["tags"]})
person = ct.models.Person.model_validate(json.loads(body)["data"])

client.request("POST", "/persons", json={"departmentIds": [1], "firstName": "Ben"})""",
            rust="""\
let query = vec![("include[]".to_string(), "tags".to_string())];
let person: models::Person = client.request_data(Method::Get, "/persons/7", &query, None)?;

let body = serde_json::json!({ "departmentIds": [1], "firstName": "Ben" });
client.request(Method::Post, "/persons", &[], Some(&body))?;""",
        ),
        Section(
            "versionen",
            "ChurchTools-Versionen",
            """
Der Client ist aus der API-Beschreibung einer bestimmten ChurchTools-Version erzeugt. Welche das ist, steht in
`API_VERSION` (z. B. `3.138.0`). Gegen andere Versionen funktioniert er, soweit die API gleich ist:

- **Neue Felder** einer neueren Version gehen nicht verloren: Sie landen in `model_extra` bzw. `extra`.
- **Neue Werte** in Feldern mit fester Auswahl führen nicht zu Fehlern, Antworten erlauben jeden `str`.
- **Fehlende Endpunkte** einer älteren Version antworten mit `404`.
- **Geänderte Pflichtfelder** können ein `DecodeError` auslösen. Dann hilft eine neuere Version des Clients.

Die eigene Version (`__version__`, in Rust die Crate-Version) folgt SemVer. Was sich ändert, steht im
`CHANGELOG.md`. Neue ChurchTools-Versionen bringen meist eine neue Minor-Version.
""",
            python="""\
import churchtools_api as ct

info = client.info.get()
if info.version != ct.API_VERSION:
    print(f"Instanz {info.version}, Client erzeugt für {ct.API_VERSION} (Version {ct.__version__})")""",
            rust="""\
let info = client.info().get()?;
if info.version.as_deref() != Some(churchtools_api::API_VERSION) {
    println!("Instanz {:?}, Client erzeugt für {}", info.version, churchtools_api::API_VERSION);
}""",
        ),
    ],
)

TESTING = Chapter(
    "testen",
    "Testen",
    "Skripte ausprobieren, ohne echte Gemeindedaten anzufassen.",
    [
        Section(
            "demo-instanz",
            "Mit einer Demo-Instanz testen",
            """
Für eigene Versuche bietet ChurchTools eine kostenlose [Test-Instanz](https://church.tools/en/test-churchtools/)
an. Sie ist mit erfundenen Beispieldaten einer Gemeinde gefüllt, du bist darin Administrator, und nach drei Tagen
wird sie gelöscht. Dort kannst du auch schreibende Aufrufe ausprobieren, ohne etwas kaputtzumachen.

1. Auf der Seite oben eine Test-Instanz anfordern. Adresse, Benutzername und Passwort kommen per E-Mail.
2. Die Zugangsdaten als Umgebungsvariablen setzen, nicht in den Quelltext schreiben.
3. Im Skript mit `login_with_password` anmelden und `min_interval` setzen, damit die Instanz nicht mit
   Anfragen überflutet wird.

`login_with_password` holt das dauerhafte Login-Token des Benutzers. Für eine Demo-Instanz ist das in Ordnung;
in einer echten Instanz legst du besser einen eigenen Benutzer mit passenden Rechten an und speicherst dessen Token.

Teste nie gegen eine Produktivinstanz, wenn dein Skript Daten anlegt oder löscht.
""",
            python="""\
import os
import churchtools_api as ct

demo = ct.Client(os.environ["CT_URL"], min_interval=0.25)
client = demo.login_with_password(os.environ["CT_USER"], os.environ["CT_PASSWORD"])

me = client.whoami.get()
print(f"Angemeldet als {me.first_name} {me.last_name}")
print(sum(1 for _ in client.persons.list()), "Personen in der Demo")""",
            rust="""\
use std::{env, time::Duration};

let demo = Client::new(&env::var("CT_URL")?, None)?.with_min_interval(Duration::from_millis(250));
let client = demo.login_with_password(&env::var("CT_USER")?, &env::var("CT_PASSWORD")?)?;

let me = client.whoami().get()?;
println!("Angemeldet als {:?} {:?}", me.first_name, me.last_name);
println!("{} Personen in der Demo", client.persons().list()?.len());""",
        ),
        Section(
            "projekt-tests",
            "Die Tests dieses Projekts gegen eine Demo-Instanz",
            """
Das Projekt prüft jeden Endpunkt gegen eine echte Instanz. Diese Live-Tests legen Daten an und löschen sie
wieder, deshalb laufen sie nur gegen eine Demo-Instanz. Sie dauern etwa vier Minuten.

- `pytest tests/live` ruft jeden GET-Endpunkt auf und spielt Schreib-Szenarien durch (anlegen, ändern,
  löschen). Ohne `CT_URL` und Zugangsdaten werden sie übersprungen.
- Die Antworten landen in `fixtures/recorded/`. Zugangsdaten und der Name der Instanz werden dabei ersetzt
  (`gemeinde.example`). Aus den Aufzeichnungen entstehen die Offline-Tests, die ohne Netz laufen.
- `python tests/live/summary.py` fasst das Ergebnis zusammen, `fixtures/live-results.json` hält es pro
  Endpunkt fest. Die [Testabdeckung](#testabdeckung) dieser Seite stammt daraus.

Vor dem Einchecken neuer Aufzeichnungen lohnt ein Blick hinein: Die Demo enthält neben den erfundenen
Personen auch öffentliche Inhalte von ChurchTools, etwa Blog- und News-Beiträge.
""",
            python="""\
# im Ordner python/, mit den Zugangsdaten der Demo
export CT_URL=https://xyz.church.tools CT_USER=... CT_PASSWORD=...
export CT_MIN_INTERVAL=0.25
pytest tests/live
python tests/live/summary.py""",
            rust="""\
# Login, Drosselung und Kalender aus Rust
export CT_URL=https://xyz.church.tools CT_USER=... CT_PASSWORD=...
cargo test -p churchtools-api --test live -- --ignored""",
        ),
    ],
)

PROJECTS = Chapter(
    "projekte",
    "Projekte",
    "Kleine, vollständige Aufgaben aus dem Gemeindealltag. Jedes Projekt verbindet mehrere Aufrufe.",
    [
        Section(
            "projekt-monatsplan",
            "Monatsplan aus öffentlichen Kalendern",
            """
**Ziel:** alle Termine eines Monats aus allen öffentlichen Kalendern, sortiert und in Ortszeit.

1. Kalender laden und ihre IDs sammeln.
2. Die Termine aller Kalender in einem Aufruf holen.
3. Ganztägige Termine und Termine mit Uhrzeit unterschiedlich ausgeben.

Das funktioniert ohne Token, solange die Kalender öffentlich sind.
""",
            python="""\
import datetime as dt
from zoneinfo import ZoneInfo

berlin = ZoneInfo("Europe/Berlin")
calendars = client.calendars.list()

termine = client.calendars.appointments.list(
    calendar_ids=[c.id for c in calendars],
    from_=dt.date(2026, 11, 1),
    to=dt.date(2026, 11, 30),
)
for termin in termine:
    start = termin.appointment.calculated.start_date
    if isinstance(start, dt.datetime):
        wann = start.astimezone(berlin).strftime("%d.%m. %H:%M")
    else:
        wann = start.strftime("%d.%m.") + " ganztags"
    print(wann, termin.appointment.base.title)""",
            rust="""\
use churchtools_api::chrono::Local;

let calendars = client.calendars().list()?;
let query = GetCalendarsAppointmentsQuery {
    calendar_ids: Some(calendars.iter().map(|c| c.id).collect()),
    from: Some("2026-11-01".parse()?),
    to: Some("2026-11-30".parse()?),
    ..Default::default()
};
for termin in client.calendars().appointments().list(&query)? {
    let wann = match termin.appointment.calculated.start_date {
        DateOrDateTime::DateTime(t) => t.with_timezone(&Local).format("%d.%m. %H:%M").to_string(),
        DateOrDateTime::Date(d) => format!("{} ganztags", d.format("%d.%m.")),
    };
    println!("{wann} {}", termin.appointment.base.title);
}""",
        ),
        Section(
            "projekt-dienstplan",
            "Dienstplan für den Gottesdienst",
            """
**Ziel:** für jedes Event im Monat anzeigen, wer welchen Dienst übernimmt und welche Dienste noch offen sind.

1. Die Liste der Dienste laden, um Dienst-IDs in Namen zu übersetzen.
2. Events mit `include="event_services"` laden. Dann hängen die Dienste direkt am Event.
3. Pro Dienst die eingetragene Person ausgeben oder „offen“.

Dafür braucht der Token-Benutzer Leserechte in der Dienstplanung.
""",
            python="""\
import datetime as dt

dienste = {s.id: s.name for s in client.services.list()}

for event in client.events.list(
    from_=dt.date(2026, 11, 1),
    to=dt.date(2026, 11, 30),
    include="event_services",
):
    print(f"{event.start_date:%d.%m.} {event.name}")
    for eintrag in event.event_services or []:
        wer = eintrag.person.title if eintrag.person else "offen"
        print(f"    {dienste.get(eintrag.service_id, '?')}: {wer}")""",
            rust="""\
use std::collections::HashMap;

let dienste: HashMap<i64, String> =
    client.services().list()?.into_iter().map(|s| (s.id, s.name)).collect();

let query = GetEventsQuery {
    from: Some("2026-11-01".parse()?),
    to: Some("2026-11-30".parse()?),
    include: Some("event_services".into()),
    ..Default::default()
};
for event in client.events().list_with(&query)? {
    println!("{} {}", event.start_date.format("%d.%m."), event.name);
    for eintrag in event.event_services.unwrap_or_default() {
        let wer = eintrag.person.map(|p| p.title).unwrap_or("offen".into());
        let dienst = dienste.get(&eintrag.service_id).map_or("?", |s| s.as_str());
        println!("    {dienst}: {wer}");
    }
}""",
        ),
        Section(
            "projekt-geburtstage",
            "Geburtstagsliste der Woche",
            """
**Ziel:** alle Geburtstage der nächsten sieben Tage, z. B. für die Mitteilungen im Gottesdienst.

ChurchTools hat dafür einen eigenen Endpunkt. Er liefert das Datum, das neue Alter und die Person.
""",
            python="""\
import datetime as dt

heute = dt.date.today()
for eintrag in client.persons.list_birthdays(
    start_date=heute,
    end_date=heute + dt.timedelta(days=7),
):
    if eintrag.person:
        print(f"{eintrag.anniversary:%d.%m.}  {eintrag.person.title} wird {eintrag.age}")""",
            rust="""\
use churchtools_api::chrono::{Days, Local};

let heute = Local::now().date_naive();
let query = GetPersonsBirthdaysQuery {
    start_date: Some(heute),
    end_date: heute.checked_add_days(Days::new(7)),
    ..Default::default()
};
for eintrag in client.persons().list_birthdays_with(&query)? {
    if let (Some(person), Some(tag)) = (eintrag.person, eintrag.anniversary) {
        println!("{}  {} wird {}", tag.format("%d.%m."), person.title, eintrag.age);
    }
}""",
        ),
        Section(
            "projekt-csv",
            "Gruppenmitglieder als CSV-Datei",
            """
**Ziel:** die Mitglieder einer Gruppe als Tabelle, die sich in Excel oder LibreOffice öffnen lässt.

Die Mitgliederliste enthält die Person, den Status (`active`, `requested`, `waiting`, …) und das
Eintrittsdatum. Das Semikolon als Trennzeichen erkennt Excel in deutscher Einstellung direkt.
""",
            python="""\
import csv

with open("mitglieder.csv", "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f, delimiter=";")
    writer.writerow(["Name", "Status", "Mitglied seit"])
    for member in client.groups.members.list(42):
        writer.writerow([member.person.title, member.group_member_status, member.member_start_date or ""])""",
            rust="""\
let mut csv = String::from("Name;Status;Mitglied seit\\n");
for member in client.groups().members().list(42)? {
    let seit = member.member_start_date.map(|d| d.to_string()).unwrap_or_default();
    csv += &format!("{};{};{}\\n", member.person.title, member.group_member_status, seit);
}
std::fs::write("mitglieder.csv", csv)?;""",
        ),
        Section(
            "projekt-neue-person",
            "Neue Person anlegen und in eine Gruppe aufnehmen",
            """
**Ziel:** eine Anmeldung aus einem Formular übernehmen: Person anlegen und direkt einer Gruppe zuordnen.

1. Person mit Abteilung (`department_ids`) und Namen anlegen. Die Abteilung ist Pflicht.
2. Mit der neuen ID die Mitgliedschaft in der Gruppe setzen.

ChurchTools prüft beim Anlegen auf Dubletten. Findet es eine ähnliche Person, antwortet es mit einem
Fehler. `force=True` legt die Person trotzdem an.
""",
            python="""\
person = client.persons.create(
    department_ids=[1],
    first_name="Ben",
    last_name="Beispiel",
    email="ben@example.org",
)
client.groups.members.update(42, person.id, group_member_status="active")
print(f"{person.first_name} angelegt (ID {person.id}) und Gruppe 42 zugeordnet")""",
            rust="""\
let body = models::PostPersonsBody {
    department_ids: vec![1],
    first_name: Some("Ben".into()),
    last_name: Some("Beispiel".into()),
    email: Some("ben@example.org".into()),
    ..Default::default()
};
let person = client.persons().create(&body)?;

let membership = models::MembershipCreate {
    group_member_status: Some(Some("active".into())),
    ..Default::default()
};
client.groups().members().update(42, person.id, &membership)?;
println!("{:?} angelegt (ID {})", person.first_name, person.id);""",
        ),
    ],
)

CHAPTERS = [START, BASICS, PROJECTS, TESTING]

ERRORS = [
    ("400", "BadRequest", "Die Anfrage ist ungültig, z. B. ein Pflichtfeld fehlt."),
    ("401", "Unauthorized", "Kein oder ein abgelaufenes Token. Prüfe `CT_TOKEN`."),
    ("403", "Forbidden", "Angemeldet, aber ohne Berechtigung. Die Rechte der Token-Person reichen nicht."),
    ("404", "NotFound", "Das Objekt gibt es nicht, oder die Person darf es nicht sehen."),
    ("409", "Conflict", "Konflikt mit vorhandenen Daten, z. B. eine mögliche Dublette."),
    ("422", "UnprocessableEntity", "Die Daten sind formal falsch. Details stehen in `errors`."),
    ("5xx", "ServerError", "Fehler auf dem Server. Später erneut versuchen."),
    ("–", "TransportError", "Die Verbindung ist fehlgeschlagen. Genauer: `ConnectError` (Instanz nicht erreichbar, falsche Adresse, Netzwerk), `Timeout` (Anfrage dauerte länger als `timeout`), `ResponseTooLarge` (Antwort größer als `max_response_size`)."),
    ("–", "InvalidArgument", "Ein Argument ist ungültig, bevor etwas gesendet wird: Adresse der Instanz, Token, Timeout oder eine leere bzw. `..`-ID. Ist auch ein `ValueError`."),
    ("–", "DecodeError", "Die Antwort passt nicht zur API-Beschreibung. Bitte als Fehler melden."),
    ("3xx", "RedirectError", "Der Server leitet um (301, 302, 303). Der Client folgt nicht, weil die Anfrage sonst als GET ohne Body wiederholt würde. Meist stimmt die Adresse der Instanz nicht."),
]

# Short German introductions for the most used API areas.
TAG_INTROS = {
    "General": "Allgemeine Informationen zur Instanz und zur angemeldeten Person.",
    "Person": "Personen, ihre Daten, Beziehungen, Einstellungen und Dienstanfragen.",
    "Group": "Gruppen, Mitgliedschaften, Rollen, Treffen und Gruppen-Stammdaten.",
    "Calendar": "Kalender und Termine, inklusive Serien und einzelner Vorkommen.",
    "Event": "Events der Dienstplanung, ihre Dienste, Abläufe und Fakten.",
    "Service & Service Groups": "Dienste (z. B. Technik, Lobpreis) und Dienstgruppen.",
    "Agenda": "Abläufe von Gottesdiensten und Vorlagen dafür.",
    "Song": "Liederdatenbank mit Arrangements.",
    "Resource": "Räume und Ressourcen und deren Buchungen.",
    "Absence": "Abwesenheiten von Personen.",
    "Finance": "Buchhaltung: Konten, Buchungen, Spenden und Belege.",
    "Hidden": "Interne Endpunkte, die ChurchTools nicht offiziell dokumentiert. Sie können sich ohne Ankündigung ändern.",
}

TAG_ORDER = [
    "General", "Person", "Group", "Calendar", "Event", "Service & Service Groups", "Agenda", "Song",
    "Resource", "Absence", "Tag", "File", "Wiki", "Post", "Chat", "Checkin", "Follow-Up", "Note",
    "Address", "Campus", "Contact Label", "Relationship Type", "Status", "Department", "Profile",
    "Subscription", "Fact", "DB Fields", "DynamicGroups", "GroupHomepage", "MasterData", "Bulkletter",
    "Email", "Finance", "Permission", "Admin", "Sync", "Job", "Queue", "Routine", "HtmlTemplate",
    "Placeholder", "Translation", "Language", "Widgets", "FurtherLink", "EvangelischeTermine", "Bulk",
    "DomainObjects", "Field",
]
