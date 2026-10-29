# Entwurf: ChurchTools-Client (Rust-Kern, Python-Paket)

Stand: 2026-10-28. Grundlage ist die OpenAPI-Spec von
`https://demo.church.tools/system/runtime/swagger/openapi.json`
(OpenAPI 3.1, 548 Pfade, 849 Operationen, 1131 Schemas).

Dieses Dokument zeigt mögliche Python-APIs. Die Entscheidungen am Ende legen fest,
was danach generiert wird.

## Geplante Struktur

```
churchtools/            Cargo-Workspace
├── churchtools-core/   reiner Rust-Client (reqwest, serde); Monatsplan nutzt diesen
├── churchtools-py/     PyO3-Bindings, gebaut mit maturin -> `pip install churchtools-rs`
└── codegen/            Generator: openapi.json -> Rust-Typen + Endpunkte
```

Monatsplan würde dann `churchtools-core` statt `src/api.rs` verwenden.

---

## Variante A: Ressourcen-orientiert (empfohlen)

Gruppiert nach den Tags der Spec (`Event`, `Calendar`, `Person`, ...).

```python
from datetime import date
import churchtools as ct

client = ct.Client("https://meinegemeinde.church.tools", token="...")
# alternativ: ct.Client.from_env()  -> CT_URL / CT_TOKEN

# Einfache Liste
for service in client.services.list():
    print(service.id, service.name)

# Paginierung passiert automatisch: der Iterator lädt Seiten bei Bedarf nach
events = client.events.list(
    from_=date(2026, 11, 1),
    to=date(2026, 11, 30),
    include=["event_services"],
)
for event in events:
    print(event.start_date, event.name)
    for es in event.event_services or []:
        print("   ", es.name, es.person.title if es.person else "—")

# Termine aus mehreren Kalendern
appointments = client.calendars.appointments(
    calendar_ids=[2, 3],
    from_=date(2026, 11, 1),
    to=date(2026, 11, 30),
    include=["event", "tags"],
)

# Einzelobjekt, Anlegen, Ändern
person = client.persons.get(42)
group = client.groups.create(name="Hauskreis Nord", group_type_id=1, group_status_id=1)
client.groups.update(group.id, name="Hauskreis Nord-West")
client.groups.delete(group.id)
```

**Vorteile:** Mit Autovervollständigung gut zu entdecken und nah an der Struktur der Spec.
**Nachteil:** Die Namen müssen aus `operationId` + Tag abgeleitet werden. Bei
Sonderfällen wie `post-calendars-calendarId-appointments-appointmentId-changeimpact`
braucht es eine Mapping-Tabelle.

## Variante B: 1:1 nach operationId (rein generiert)

```python
r = client.get_events(from_="2026-11-01", to="2026-11-30", include="event_services")
r.data   # list[GetEventsResponseItem]
r.meta   # {"count": 17}

client.get_calendars_appointments(calendar_ids=[2, 3], from_="2026-11-01")
client.put_calendars_calendar_id_appointments_appointment_id(calendar_id=2, appointment_id=7, body={...})
```

**Vorteile:** Vollständig automatisch generiert, ohne Pflegeaufwand.
**Nachteile:** Lange, technische Namen; die Paginierung muss man selbst bauen.

Man kann auch beides haben: B als `client.raw.*` und A darüber.

---

## Rückgabetypen

**1. Typisierte Klassen (PyO3 `#[pyclass]`), mit `.pyi`-Stubs für IDE und mypy**

```python
event.name            # str
event.start_date      # datetime.datetime (tz-aware, UTC)
event.calendar.color  # verschachtelte Objekte, ebenfalls typisiert
event.to_dict()       # Rohdaten als dict
event.extra           # dict mit Feldern, die die Spec nicht kennt
```

**2. Nur dicts:** `event["name"]`, `event["startDate"]`. Das ist am einfachsten, aber ohne Typen.

**3. Pydantic-Modelle in Python, Rust nur für den HTTP-Teil:** Diese Lösung ist in Python
am idiomatischsten, aber die Typen gibt es dann doppelt.

`.extra` ist nötig, weil z. B. Personen admin-definierte DB-Felder enthalten, die
in keiner Spec stehen.

## Fehler

```python
try:
    client.persons.get(999999)
except ct.NotFound as e:
    print(e.status, e.message_key, e.translated_message)
except ct.Unauthorized:        # Token ungültig oder Session abgelaufen
    ...
except ct.ApiError as e:       # Basisklasse für alle HTTP-Fehler
    print(e.errors)            # Validierungsfehler pro Feld
```

ChurchTools liefert `message`, `translatedMessage`, `messageKey`, `args` und `errors`.
Diese Felder lassen sich direkt abbilden.

## Sync oder Async

```python
# synchron (Standard)
client = ct.Client(url, token=...)

# asynchron
async with ct.AsyncClient(url, token=...) as client:
    async for event in client.events.list(from_=date(2026, 11, 1)):
        ...
```

Im Rust-Kern ist Async (tokio) die natürliche Basis. Sync würde darauf aufbauen.
Monatsplan selbst verwendet bisher `reqwest::blocking`.

## Optional: Cache und Logging

Monatsplan hat bereits einen Datei-Cache und ein strukturiertes API-Logging. In der
Bibliothek könnte beides als Option eingebaut sein:

```python
client = ct.Client(url, token=..., cache=ct.FileCache(ttl_minutes=30))
```

oder es bleibt bewusst außerhalb und gehört nur zu Monatsplan.

---

## Entscheidungen (2026-10-28)

1. **API-Stil:** A (Ressourcen)
2. **Rückgabetypen:** Pydantic
3. **Sync/Async:** erst sync; Async später als zweite generierte Variante
4. **Umfang:** zunächst Event, Calendar, Service & Service Groups, Person, Group. Später auf die
   ganze API erweitert (849 Operationen, siehe README).
5. **Spec-Version:** Die Spec hängt nur an der ChurchTools-Version (Demo und eigene
   Instanz sind bei 3.138.0 identisch). Der Generator schreibt die Version in die
   Kopfzeile des generierten Codes.
6. **Paketname:** `churchtools-rs`
7. **Cache/Logging:** vorerst nicht in der Bibliothek

Umsetzung und offene Review-Punkte: [`README.md`](../README.md).
