# Changelog

Alle nennenswerten Änderungen am Rust-Crate `churchtools-api` und am Python-Paket `churchtools-api-rs`. Die Versionen
folgen [SemVer](https://semver.org/lang/de/): neue Funktionen und inkompatible Änderungen erhöhen die Minor-Version,
reine Fehlerkorrekturen die Patch-Version. Wie Versionen und ChurchTools-Versionen zusammenhängen, steht im README unter
„ChurchTools-Versionen und Kompatibilität“. Die Doku-Seite zeigt diese Datei als „Änderungen je Version“.

Jede Version hat denselben Aufbau, `codegen/changelog.py` prüft ihn:

- Überschrift `## [Version] – JJJJ-MM-TT` (vor der Veröffentlichung `## [Unreleased]`).
- Erste Zeile: `ChurchTools <Version> (Build <Nummer>) · <n> Operationen · <n> Modelle`.
- Ein Satz, was die Version ausmacht.
- Danach nur die Abschnitte, die etwas enthalten, in dieser Reihenfolge: `### Inkompatibel` (jeweils mit dem, was
  beim Umstieg zu ändern ist), `### Neu`, `### Geändert`, `### Korrigiert`.

## [0.3.0] – 2026-11-23

ChurchTools 3.139.0 (Build 32955) · 875 Operationen · 1143 Modelle

Update auf ChurchTools 3.139.0 mit 25 neuen Endpunkten und einigen inkompatiblen Typänderungen.

### Inkompatibel

- Koordinaten in Adressen (`latitude`, `longitude`, `latitudeLoose`, `longitudeLoose`, `geoLat`, `geoLng`) können
  Zahl oder Text sein: Python `float | str | None` statt `str | None`, Rust `serde_json::Value` statt
  `Option<String>`. Wer mit dem Wert rechnet, wandelt ihn selbst um (`float(address.latitude)`). Bei `CheckinPerson`
  sind `latitude`/`longitude` nicht mehr Pflicht.
- `security_levels.create()` und `security_levels.patch()` geben `GetSecuritylevelsIdResponse` zurück (die Stufe
  direkt und zusätzlich unter `data`); `PostSecuritylevelsIdResponse` und `PatchSecuritylevelsIdResponse` entfallen.
  Typangaben im eigenen Code entsprechend umbenennen.
- `ProbeTraversalExpression` (Body von `persons.filter()`) ist aufgeteilt in `ProbeMembershipTraversalExpression`
  und `ProbeRelationshipTraversalExpression`; den passenden Typ wählen.
- Rust: Viele Felder in Bodies zum Ändern sind `null`-fähig und damit `Option<Option<T>>`, z. B. in
  `PatchPersonsIdBody`, `PostPersonsBody` und `PatchGroupsIdBody`: `city: Some(Some("Esslingen".into()))` setzt den
  Wert, `Some(None)` sendet `null`. In Python sind die Argumente nur zusätzlich `None`-fähig.
- `Config.feature_old_group_module` entfällt; `PermissionModification.modified_date` ist Pflicht.

### Neu

- 25 Endpunkte: CCLI (`ccli.authorization()`, `ccli.delete_connection()`, `ccli.songs.list()`, `ccli.songs.get()`,
  `songs.arrangements.files.ccli()`), `events.patch()`, `events.cancel()`, `events.agenda.print()`,
  `events.agenda.items.patch()`, `agenda_templates.items.patch()`, Dienst-Kandidaten (`events.list_candidates()`,
  `events.services.list_candidates()`), Berechtigungen (`permissions.get_overview()`, `permissions.promote()`,
  `permissions.assignment_targets.higher_levels.query()`, `permissions.assignment_targets.person_summary.query()`,
  `permissions.origins.global_.get()`, `permissions.origins.global_.group_roles.get()`), Personen
  (`persons.activate()`, `persons.deactivate()`, `persons.unarchive()`, `persons.get_consentstatus()`),
  `posts.update_seen()`, `reset_password.session()` und `triggers.create()`.
- Optionale Argumente und Felder, z. B. `include=["statistics"]` bei `permissions.list_assignment_targets()`,
  `include=["hasSeen"]` bei `posts.get()`, `include=["usage"]` bei `songs.get()`, `hasSeen`/`imagesMeta` bei
  Beiträgen, `triggerKey` bei Routinen, `statistics` bei `PermissionAssignmentTarget`.
- Doku-Seite „Änderungen je Version“ aus diesem Changelog.

### Geändert

- `PersonPasswordUpdate.old_password` (Argument von `persons.update_password()`) ist optional.
- `permissions.list_assignment_targets()` behält seinen Namen, obwohl es unter `/permissions/assignment-targets` jetzt
  Unterpfade gibt, und `PermissionAssignmentTarget` behält `domain_type` (die Spec führt es nur noch in den Varianten).
- `API_VERSION`/`API_BUILD` sind `3.139.0`/`32955`.

### Korrigiert

- `GroupInformation.note` darf `null` sein: Seit 3.139.0 sendet der Server bei Gruppen ohne Notiz `null` statt `""`.

## [0.2.0] – 2026-11-22

ChurchTools 3.138.3 (Build 32945) · 850 Operationen · 1110 Modelle

Update auf ChurchTools 3.138.3: Sicherheitsstufen neu nummerieren und gegen gleichzeitige Änderungen schützen.

### Neu

- `security_levels.renumber()` (`POST /securitylevels/renumber`) nummeriert die Sicherheitsstufen neu, ohne ihre
  Reihenfolge zu ändern. Danach haben die Stufen andere IDs; gespeicherte IDs müssen neu gelesen werden.
- Optionales Argument `expected_name` bei `security_levels.patch` und `security_levels.delete` (Rust:
  `PatchSecuritylevelsIdBody::expected_name`, `DeleteSecuritylevelsIdQuery::expected_name`). Weicht der Name ab,
  lehnt der Server mit 409 ab (`Conflict`).

### Geändert

- `forcereorder` bei `security_levels.patch` ist veraltet (der Server ignoriert es) und erzeugt eine Warnung.
- `API_VERSION`/`API_BUILD` sind `3.138.3`/`32945`.

## [0.1.0] – 2026-10-30

ChurchTools 3.138.1 (Build 32938) · 849 Operationen · 1110 Modelle

Erste Veröffentlichung.

### Neu

- Rust-Crate `churchtools-api`: `Client`/`ClientBuilder` (`timeout`, `connect_timeout`, `max_response_size`,
  `allow_insecure_http`, `from_env`), generierte Ressourcen (`client.events().list_with(&query)`), Modelle mit
  `Default` und `extra`, lazy Iteratoren `…_iter` und `Client::items`, `Error` mit `is_not_found()`, `status()`,
  `api()`; die HTTP-Bibliothek ist nicht Teil der öffentlichen API (`Method`, `TransportError`).
- Python-Paket `churchtools-api-rs` (Import `churchtools_api`): `Client` mit denselben Optionen, generierte Ressourcen
  (`client.events.list(...)`), Pydantic-Modelle mit `model_extra`, `Paginator`, Ausnahmen `NotFound`,
  `Unauthorized`, `Forbidden`, `UnprocessableEntity`, `ConnectError`, `Timeout`, `ResponseTooLarge`,
  `RedirectError`, `DecodeError`, `InvalidArgument`; Argumente mit fester Werteliste als `Literal[...]`.
- Sicherheit: nur `https://` (Ausnahme `localhost`, sonst `allow_insecure_http`); Token nicht in Debug-Ausgaben
  und Fehlermeldungen; Weiterleitungen 301/302/303 werden nicht verfolgt; leere, `.`- und `..`-Pfadsegmente werden
  abgelehnt; Antwortgröße begrenzt (256 MiB).
- Rate-Limit (`min_interval`) und Wiederholungen: `429` nach `Retry-After` (Sekunden oder Datum), `502`/`503`/`504`
  für idempotente Methoden, Verbindungsfehler einmal.
- Paginierung: ab der zweiten Seite wird die nächste Seite in einem Hintergrund-Thread angefordert, während die
  aktuelle dekodiert und verarbeitet wird; `prefetch(false)` auf `Pages`/`Items` (Rust) und `prefetch(False)` auf
  `Paginator` (Python) schalten das ab.
- Toleranzregeln für Abweichungen der API von der Spec (Zahlen als String, PHP-Nulldatum, `[]` als leeres Objekt,
  Array-Parameter mit `[]`, leere 204-Antworten) und Einzelkorrekturen aus den Live-Tests.
- Datei-Uploads (`Upload`), `login_with_password`, veraltete Endpunkte und Argumente markiert
  (`@deprecated`, `#[deprecated]`), `API_VERSION`/`API_BUILD`, `churchtools_api.__version__`.
- TLS über rustls mit `ring` und dem Trust-Store des Betriebssystems.
- Pakete auf PyPI (Wheels für Linux, macOS und Windows, abi3 ab Python 3.10, dazu ein sdist) und crates.io;
  Mindestversion Rust 1.88.
- Doku-Seite mit Einstieg, Grundlagen, Beispielprojekten und Referenz; alle Beispiele laufen als Tests.
- Lizenz MIT; generierte Dateien zusätzlich CC BY 4.0 (API-Beschreibung von ChurchTools), siehe `NOTICE`.
