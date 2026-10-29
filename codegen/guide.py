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
`churchtools-rs` ist ein Client für die REST-API von [ChurchTools](https://church.tools): Personen, Gruppen,
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
Das Python-Paket enthält einen kompilierten Rust-Kern und wird mit [maturin](https://www.maturin.rs) gebaut.
In Rust bindest du die Crate `churchtools-core` als Abhängigkeit ein.
""",
            python="""\
# im Ordner python/ des Projekts
pip install maturin
maturin develop          # baut und installiert churchtools-rs ins aktive venv""",
            rust="""\
# Cargo.toml
[dependencies]
churchtools-core = { path = "../churchtools-rs/core" }""",
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
import churchtools_rs as ct

client = ct.Client("https://demo.church.tools")
info = client.info.get()
print(info.site_name, info.version)""",
            rust="""\
use churchtools_core::Client;

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
import churchtools_rs as ct

client = ct.Client("https://meinegemeinde.church.tools", token="DEIN_TOKEN")

# besser: CT_URL und CT_TOKEN aus der Umgebung lesen
client = ct.Client.from_env()

me = client.whoami.get()
print(f"Angemeldet als {me.first_name} {me.last_name}")""",
            rust="""\
use churchtools_core::Client;

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
  Modell, das du am einfachsten aus JSON erzeugst.

Die Namen sind in Python im üblichen snake_case geschrieben (`first_name` statt `firstName`). Wo ein Name ein
Python-Schlüsselwort ist, kommt ein Unterstrich dazu: `from_`.
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

let body: models::PatchPersonsIdBody = serde_json::from_value(serde_json::json!({
    "city": "Esslingen",
    "zip": "73728"
}))?;
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

- In **Python** bekommst du einen `Paginator`. Er lädt die nächste Seite erst, wenn du sie brauchst.
  Brichst du die Schleife ab, werden keine weiteren Seiten geladen. `first()` holt nur das erste
  Element, `to_list()` alles.
- In **Rust** bekommst du gleich einen `Vec` mit allen Einträgen.

Mit `limit` bestimmst du, wie viele Einträge pro Seite geladen werden (höchstens 100).
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
for person in client.persons().list_with(&query)? {
    println!("{:?}", person.last_name);
}""",
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
use churchtools_core::chrono::Local;

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
Ausnahmen, siehe die [Fehlerübersicht](#fehlercodes). In Rust prüfst du den `status`.
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
use churchtools_core::Error;

match client.persons().get(999999) {
    Ok(person) => println!("{:?}", person.first_name),
    Err(Error::Api(e)) if e.status == 404 => println!("Diese Person gibt es nicht."),
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
  lässt du den Schlüssel im JSON weg.
- **`None` / `null`**: Das Feld wird geleert.

Felder, die der Client nicht kennt (z. B. eigene DB-Felder), übergibst du in Python mit `extra_body`.
""",
            python="""\
# nur die Stadt ändern, alles andere bleibt
client.persons.patch(7, city="Esslingen")

# Geburtstag löschen
client.persons.patch(7, birthday=None)

# eigenes Datenbankfeld setzen
client.persons.patch(7, extra_body={"konfession": "evangelisch"})""",
            rust="""\
let body: models::PatchPersonsIdBody = serde_json::from_value(serde_json::json!({
    "birthday": null,
    "konfession": "evangelisch"
}))?;
client.persons().patch(7, &body)?;""",
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
use churchtools_core::chrono::Local;

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
use churchtools_core::chrono::{Days, Local};

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
let body: models::PostPersonsBody = serde_json::from_value(serde_json::json!({
    "departmentIds": [1],
    "firstName": "Ben",
    "lastName": "Beispiel",
    "email": "ben@example.org"
}))?;
let person = client.persons().create(&body)?;

let membership: models::MembershipCreate =
    serde_json::from_value(serde_json::json!({ "groupMemberStatus": "active" }))?;
client.groups().members().update(42, person.id, &membership)?;
println!("{:?} angelegt (ID {})", person.first_name, person.id);""",
        ),
    ],
)

CHAPTERS = [START, BASICS, PROJECTS]

ERRORS = [
    ("400", "BadRequest", "Die Anfrage ist ungültig, z. B. ein Pflichtfeld fehlt."),
    ("401", "Unauthorized", "Kein oder ein abgelaufenes Token. Prüfe `CT_TOKEN`."),
    ("403", "Forbidden", "Angemeldet, aber ohne Berechtigung. Die Rechte der Token-Person reichen nicht."),
    ("404", "NotFound", "Das Objekt gibt es nicht, oder die Person darf es nicht sehen."),
    ("409", "Conflict", "Konflikt mit vorhandenen Daten, z. B. eine mögliche Dublette."),
    ("422", "UnprocessableEntity", "Die Daten sind formal falsch. Details stehen in `errors`."),
    ("5xx", "ServerError", "Fehler auf dem Server. Später erneut versuchen."),
    ("–", "TransportError", "Die Instanz war nicht erreichbar (Netzwerk, falsche Adresse, Timeout)."),
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
