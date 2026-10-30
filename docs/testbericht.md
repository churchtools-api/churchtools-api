# Testbericht: churchtools-api gegen eine echte Instanz

Getestet am 28.10.2026 gegen eine 3-Tage-Demo-Instanz (ChurchTools 3.138.0, Build 32935) und am 30.10.2026 erneut
gegen eine frische Instanz mit ChurchTools 3.138.1 (Build 32938), jeweils dieselbe Spec wie demo.church.tools. Die
Spec von 3.138.1 ist byte-identisch mit der von 3.138.0; der zweite Lauf hatte dieselben Ergebnisse. Angemeldet war
der Demo-Admin (Person 1, Sicherheitsstufe 99999). Alle Anfragen liefen mit höchstens 4 Anfragen pro Sekunde
(`CT_MIN_INTERVAL=0.25`).

## Was getestet wird

| Ebene | Datei | Was | braucht Netz |
|---|---|---|---|
| Unit | `core/src/*.rs` (`#[cfg(test)]`) | URL, Paginierung, Rate-Limit, Retry-After, Toleranzregeln, Datumsformat | nein |
| Unit | `python/tests/test_client.py` | Client gegen lokalen Fake-Server: Auth, Query, Body, Fehler, Paginierung | nein |
| Replay | `python/tests/test_recorded.py` | jede aufgezeichnete Antwort gegen das Pydantic-Modell ihrer Methode | nein |
| Replay | `core/tests/recorded.rs` | dieselben Antworten gegen die Rust-Typen (eine Test-Funktion pro Endpunkt) | nein |
| Doku | Doctests in `core/src/generated/api.rs`, `core/tests/doc_examples.rs`, `python/tests/test_doc_examples.py` | alle Beispiele der Doku kompilieren bzw. bestehen `mypy --strict`; die mit aufgezeichneter Antwort werden ausgeführt (Rust 444 + 12, Python 444 + 12) | nein |
| Live | `python/tests/live/test_read.py` | jeder GET-Endpunkt einmal über die generierte API | ja |
| Live | `python/tests/live/test_write*.py` | Szenarien: anlegen → lesen → ändern → löschen | ja |
| Live | `core/tests/live.rs` | Passwort-Login, Rate-Limit, Kalender aus Rust | ja |

Die Live-Tests zeichnen jede erfolgreiche Antwort in `fixtures/recorded/` auf. Daraus entstehen die Replay-Tests:
Sie prüfen Python und Rust gegen echte Daten, ohne die Instanz erneut zu belasten.

## Ergebnis

Alle 849 Operationen, Stand des letzten Laufs (`fixtures/live-results.json`):

| | ok | erwartet | keine Daten | nicht aufgerufen | gesamt |
|---|---:|---:|---:|---:|---:|
| GET | 348 | 11 | 6 | – | 365 |
| POST | 72 | – | – | 144 | 216 |
| PUT | 49 | 1 | – | 68 | 118 |
| PATCH | 9 | – | – | 15 | 24 |
| DELETE | 57 | – | – | 69 | 126 |
| **gesamt** | **535** | **12** | **6** | **296** | **849** |

pytest: 390 bestanden, 12 erwartete Fehler (`xfail`), 6 übersprungen, 0 fehlgeschlagen; Laufzeit etwa 4 Minuten.
Mit den Testdaten aus `seed.py` sind von den 365 GET-Endpunkten 348 erfolgreich getestet; vorher waren es 298.
Von den 484 schreibenden ruft die Suite 188 auf, verteilt auf 43 Szenario-Tests. In der Doku-Seite tragen alle
Endpunkte, die nicht „ok“ sind, ein rotes Sternchen.

- **ok:** Aufruf erfolgreich, Antwort passt zu den Modellen.
- **erwartet:** Fehler mit bekannter Ursache (siehe unten und `tests/live/expectations.py`).
- **keine Daten:** Die Demo hat nichts, worauf sich der Endpunkt anwenden ließe, z. B. keine externen Logins, keine
  dynamischen Gruppen oder keine Sync-Berechtigung.
- **nicht aufgerufen:** Schreibende Endpunkte ohne Szenario, siehe „Bewusst nicht getestet“.

Alle 331 aufgezeichneten Antworten dekodieren in Python und in Rust. Eine davon, `GET /website/starttest`, liefert `{}`
ohne dokumentierten Typ und wird nur in Python übersprungen.

## Auffälligkeiten

### 1. Spec und Server passen nicht zusammen, im Client ausgeglichen

Diese Fälle hätten Aufrufe scheitern lassen. Der Generator gleicht sie jetzt aus (Regeln in `generate.py`,
Einzelfälle in `FIELD_FIXES` und `RESULT_FIXES`):

| Fund | Beispiel | Ausgleich |
|---|---|---|
| 35 Array-Parameter sind ohne `[]` benannt. PHP liest dann nur den letzten Wert oder lehnt ab („muss ein Array sein“). | `GET /finance/transactions/summary?account_ids=2` → 400; `account_ids[]=2` → 200 | Generator hängt `[]` an |
| Zeitstempel nur als `Y-m-d\TH:i:s\Z`. `+00:00` und Sekundenbruchteile werden abgelehnt. | `POST /groups/{id}/meetings` mit `2026-10-29T11:00:00+00:00` → 400 | Python und Rust formatieren immer `…Z` |
| `meta.createdDate`/`createdPerson` fehlen bei alten Datensätzen. | Song-Dateien von 2019 (`GET /songs`) | in `MetaDataEntity*` optional |
| PHP-Nulldatum `-0001-11-29T23:06:32Z` | `GET /agendatemplates`, `GET /events/{id}/agenda` | wird zu `None` |
| Zahl als String | `categoryId: "3"` in `GET /calendars/appointments/templates` (Pydantic war tolerant, Rust nicht) | Rust akzeptiert numerische Strings |
| Leeres Objekt kommt als `[]` (PHP) | `POST /persons/properties` ohne `ids` | `[]` gilt als `{}` (Python `StrMap`, Rust `lenient::map`) |
| Antwort mit Hülle `{"data": …}`, obwohl ohne dokumentiert | `GET /finance/templates/export` | korrigiert |
| Antwort ohne Hülle, obwohl die Liste eine hat | `GET /securitylevels/{id}` | korrigiert |
| Antwort gar nicht dokumentiert (Methode gab `None` zurück) | `GET /churchquery/metadata`, `/persons/search_old`, `/securitylevels/{id}` | Typ ergänzt |
| Einzelobjekt statt Liste | `GET /persons/{id}/poststatistics` | korrigiert |
| Andere Struktur als dokumentiert | `GET /post/linkings` (Hülle `{postGuid, postId, linkings}`), `POST /persons/{id}/relationships` (Form von `GET /persons/relationships`) | korrigiert |
| `null`, wo die Spec einen Wert verlangt | `PossiblePostGroup.roleName`, `GET /csrftoken` mit Token-Login | als optional markiert |
| Pflichtfeld fehlt | `PostReaction.meta` bei `PUT /posts/{id}/reactions/{emoji}/persons/{personId}` | als optional markiert |
| 204 ohne Body, obwohl 200 mit Body dokumentiert | `PUT /persons/{id}/privacypolicy` (5 Endpunkte mit 200/204) | Ergebnis `None` |

### 2. Der Server verlangt Parameter, die die Spec als optional führt

Die Tests übergeben sie. Der Client ändert daran nichts, weil die Spec das Feld als optional führt:

| Endpunkt | verlangt zusätzlich |
|---|---|
| `POST /persons` | `statusId` (der Server-Standard existiert auf der Demo nicht), `campusId`, `privacyPolicyAgreementTypeId`, `…WhoId`, `…Date`. Das gilt auch mit `without_privacy_policy_agreement=true`, obwohl die DB-Felder `nullable` sind. |
| `PUT /persons/{id}/privacypolicy` | ein Geburtsdatum bei der Person |
| `POST /groups/{id}/duplicate` | `newName` |
| `GET /churchquery/metadata` | `entity_to_search_for` |
| `GET /post/reports` | `domain_type` |
| `GET /post/linkings` | `post_ids` oder `post_guid` |
| `GET /finance/transactions/summary` | mindestens einen Filter (Konto, Kostenstelle oder Spender) |
| `GET /profiles/slugcheck/{slug}` | `guid` |

### 3. Fehler in ChurchTools 3.138.0

Alle Fehler bestehen in 3.138.1 unverändert.

| Endpunkt | Verhalten |
|---|---|
| `GET /calendars/{c}/appointments/{a}/ical` | 500 „is no valid URI“, bei jedem getesteten Termin |
| `GET /dbfields/{id}/options/metadata` | 500, PHP-TypeError `quote_identifier(null)` in `DbFieldOptionsService` (Feld 132) |
| `GET /domainobjects` mit nicht existierenden IDs | 500 `InvalidArgumentException` statt 404 |
| `POST /markdown/check` mit ungültigem `inputScope` | 500 TypeError statt 400 |
| `GET /evangelischetermine/eventtypes` ohne Konfiguration | 500 `SoapFault` statt 4xx |
| `PATCH /songs/{s}/arrangements/{a}/default` | schaltet um statt zu setzen: Ein zweiter Aufruf entfernt die Standard-Markierung wieder. Laut Doku soll er nichts ändern. Als `xfail(strict=True)` festgehalten, damit der Test anschlägt, sobald der Fehler behoben ist. |
| Sync-Endpunkte | 401 statt 403 für einen angemeldeten Admin ohne Sync-Recht |
| Wiki-Seite in gelöschter Kategorie löschen | 403 statt 404 |

### Hinweis zu Personenfeldern (geprüft, kein Datenleck)

```
GET /api/persons/{personId}/events/{eventId}/services/{eventServiceId}/exchangerequests/candidates
```

liefert für jeden Tauschkandidaten einen sehr großen Personen-Datensatz (69 Felder), in dem auch `password`,
`loginString` und `lastLogin` vorkommen. Nachgeprüft mit dem Demo-Admin als Kandidat, der ein Passwort hat und sich
regelmäßig anmeldet: `password` = `null`, `loginString` = `0`, `lastLogin` = `null`. Der Server leert diese Felder also;
es werden keine Zugangsdaten ausgeliefert. Es bleibt eine Spec-Abweichung: `ServiceExchangePerson` beschreibt nur
wenige der gelieferten Felder.

Zum Aufruf: `eventServiceId` ist die `id` eines Eintrags aus `GET /persons/{personId}/events/{eventId}/services`
(die Dienstzuteilung), nicht die Dienst-ID. Laut Spec muss der angemeldete Benutzer dieser Zuteilung zugeordnet sein.
Ob die Zuteilung zugesagt ist, spielt keine Rolle (auf der Demo ging es mit `agreed: false`). Der Admin durfte
die Liste auch mit fremder `personId` abrufen.

### Testdaten für Endpunkte ohne Daten (`tests/live/seed.py`)

Eine frische Demo hat für viele Lese-Endpunkte nichts, worauf sie sich anwenden ließen. `seed.py` legt die Daten vor
dem Lesetest an und entfernt sie danach wieder:

- eine Gruppe mit Treffen, QR-Check-in-Tickets, Regeln einer dynamischen Gruppe und einer Dokumentvorlage für die
  Leiterrolle
- eine öffentliche Gruppe mit offener Anmeldung und Anmelde-Token
- für die angemeldete Person eine hochgeladene Datei, eine Abwesenheit und ein App-Gerät
- einen weiteren Link und einen Kommentar mit Reaktion
- Finanzen: Skonto, Splitbuchung mit Beleg, importierter Kontoauszug (CAMT.053), euBP-Meldung
- Sync: Das Modul wird vorübergehend eingeschaltet, dazu eine Verbindung, ein Job und eine Zuordnung
- je einen versteckten OIDC- und SAML-Login-Anbieter

Dabei aufgefallen:

| Fund | Details |
|---|---|
| Dateiuploads fehlten im Client | Drei Endpunkte erwarten `multipart/form-data` (Dateien anhängen, Kontoauszug, Vorlagen-Assets). Neu: `ct.Upload` / `Upload` |
| `PATCH /groups/{id}` ignoriert unbekannte Felder stillschweigend | z. B. `isOpenForMembers` → 200, ohne Wirkung. „Offen für Anmeldungen“ ergibt sich aus `signUpOpeningDate`/`signUpClosingDate` |
| QR-Check-in einschalten erzeugt sofort Tickets mit `sentDate` | vermutlich mit E-Mail an die Mitglieder |
| `POST /externallogins` (OIDC) verlangt `clientSecret` | laut Spec nur `issuer` und `clientId` |
| `POST /publicgroups/{id}/token` | `group` enthält nur `{id, cloneWithoutChanging, customFields}`, nicht das dokumentierte `Group` (korrigiert) |
| Kontoauszüge | nur CAMT.053 Version 001.02 angenommen, .04/.08 „File format not supported“; Import über `POST /files/statement/{accountId}` |
| euBP | braucht eine gültige Betriebsnummer am Mandanten (mit Prüfziffer) |
| Dokumentvorlagen für Gruppenmitglieder | nur als `isGlobal=true`, und nur für Leiter einer Rolle, der die Vorlage zugeordnet ist |
| Rechte-Endpunkte | `…/auths/{authId}/persons` verlangt für Rechte mit Auswahlwerten eine `data_id` |

Weiterhin ohne Daten: Zuwendungsbestätigungen (auf der Demo fehlt die konfigurierte Vorlage `HtmlTemplate 14`),
Sync-Konflikte und -Ausführungen (brauchen einen echten Sync-Lauf), externe Beiträge, Bestätigungs-Token aus E-Mails.

### 4. Im Client gefunden und behoben

- Zeitstempel wurden mit `+00:00` gesendet (siehe oben). Das betraf alle Schreibaufrufe mit Datum und Uhrzeit.
- Modelle mit `alias=` erzwangen für Typprüfer die JSON-Namen im Konstruktor (`Booking(startDate=…)`). Jetzt gelten
  auch statisch die Python-Namen (`start_date=…`).
- Fehlermeldungen enthalten jetzt die Feldfehler des Servers.

## Bewusst nicht getestet

Diese Endpunkte rufen die Tests nicht auf, auch nicht auf einer Demo:

- **verschickt etwas:** E-Mails, Einladungen, Push-Nachrichten, Ablaufpläne senden, QR-Codes senden, Opt-in erneut senden
- **Zugang und Rechte:** Login/Logout, Passwort, 2FA, Login-Token löschen (würde die Testsitzung beenden),
  Berechtigungen, „Als Person anmelden“
- **globale Konfiguration:** `PUT /config`, Gemeindeprofil, Übersetzungen, Lizenz
- **externe Systeme:** Sync (keine Berechtigung), SAML/OIDC, Newsletter, evangelische-termine.de
- **Finanzen** (81 schreibende Endpunkte): mit Buchungsperioden, Konten und Belegen der umfangreichste Bereich. Er
  lohnt sich als eigenes Szenario-Paket, wenn das Modul gebraucht wird.
- **Registrierung, öffentliche Gruppenanmeldung, Check-in:** brauchen Tokens aus E-Mails oder Geräte

## Panne während der Tests

Ein früher Testentwurf hat auf der Demo die Personeneinstellung `churchcal/fav-menu` von Person 1 gelöscht.
Wiederherstellen ging nicht, weil `PUT` für diese Einstellung nicht erlaubt ist (siehe oben). Sie steuert nur ein
Favoritenmenü in der Oberfläche. Der Test nutzt jetzt `churchdb/signature` und stellt den alten Wert wieder her.
