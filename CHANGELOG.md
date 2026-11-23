# Changelog

Alle nennenswerten Änderungen am Rust-Crate `churchtools-api` und am Python-Paket `churchtools-api-rs`. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen [SemVer](https://semver.org/lang/de/);
vor 1.0 kann jede Minor-Version inkompatible Änderungen enthalten. Wie Versionen und ChurchTools-Versionen
zusammenhängen, steht im README unter „ChurchTools-Versionen und Kompatibilität“.

## [Unreleased]

Generiert aus der API-Beschreibung von ChurchTools 3.139.0 (Build 32955): 875 Operationen, 1143 Modelle. Enthält
inkompatible Änderungen, daher als nächste Version 0.3.0.

- Neu: 25 Operationen, unter anderem CCLI (`ccli.authorization()`, `ccli.delete_connection()`, `ccli.songs.list()`,
  `ccli.songs.get()`, `songs.arrangements.files.ccli()`), `events.patch()`, `events.cancel()`,
  `events.agenda.print()`, `events.agenda.items.patch()`, `agenda_templates.items.patch()`, Dienst-Kandidaten
  (`events.list_candidates()`, `events.services.list_candidates()`), Berechtigungen (`permissions.get_overview()`,
  `permissions.promote()`, `permissions.assignment_targets.higher_levels.query()`,
  `permissions.assignment_targets.person_summary.query()`, `permissions.origins.global_.get()`,
  `permissions.origins.global_.group_roles.get()`), Personen (`persons.activate()`, `persons.deactivate()`,
  `persons.unarchive()`, `persons.get_consentstatus()`), `posts.update_seen()`, `reset_password.session()` und
  `triggers.create()`.
- Neu: optionale Argumente und Felder, z. B. `include=["statistics"]` bei `permissions.list_assignment_targets()`,
  `include=["hasSeen"]` bei `posts.get()`, `include=["usage"]` bei `songs.get()`, `hasSeen`/`imagesMeta` bei Beiträgen,
  `triggerKey` bei Routinen.
- Inkompatibel: Koordinaten in Adressen (`latitude`, `longitude`, `latitudeLoose`, `longitudeLoose`, `geoLat`,
  `geoLng`) können jetzt Zahl oder Text sein: Python `float | str | None` statt `str | None`, Rust `serde_json::Value`
  statt `Option<String>`. Bei `CheckinPerson` sind `latitude`/`longitude` nicht mehr Pflicht.
- Inkompatibel: `security_levels.create()` und `security_levels.patch()` geben `GetSecuritylevelsIdResponse` zurück
  (die Stufe direkt und zusätzlich unter `data`); `PostSecuritylevelsIdResponse` und `PatchSecuritylevelsIdResponse`
  entfallen.
- Inkompatibel: `ProbeTraversalExpression` (Body von `persons.filter()`) ist aufgeteilt in
  `ProbeMembershipTraversalExpression` und `ProbeRelationshipTraversalExpression`.
- Inkompatibel (Rust): Viele Felder in Bodies zum Ändern sind jetzt `null`-fähig und damit `Option<Option<T>>`, z. B.
  in `PatchPersonsIdBody`, `PostPersonsBody` und `PatchGroupsIdBody` (`Some(None)` sendet `null`). In Python sind die
  Argumente nur zusätzlich `None`-fähig.
- Inkompatibel: `Config.feature_old_group_module` entfällt; `PermissionModification.modified_date` ist Pflicht.
  `PersonPasswordUpdate.old_password` (Argument von `persons.update_password()`) ist optional.
- `GroupInformation.note` darf `null` sein: Seit 3.139.0 sendet der Server bei Gruppen ohne Notiz `null` statt `""`
  (Live-Test, `GET /groups`).
- Der Name `permissions.list_assignment_targets()` bleibt, obwohl es unter `/permissions/assignment-targets` jetzt
  Unterpfade gibt; der Generator hätte daraus `permissions.assignment_targets.list()` gemacht.
- Generator: Felder, die alle Varianten eines `oneOf` neben den Properties eines Objekts haben, kommen ins Modell.
  Dadurch behält `PermissionAssignmentTarget` sein Feld `domain_type` (die Spec führt es jetzt nur noch in den
  Varianten) und bekommt `statistics`.
- `API_VERSION`/`API_BUILD` sind jetzt `3.139.0`/`32955`.

## [0.2.0] – 2026-11-22

Generiert aus der API-Beschreibung von ChurchTools 3.138.3 (Build 32945): 850 Operationen, 1110 Modelle. Keine
inkompatiblen Änderungen.

- Neu: `security_levels.renumber()` (`POST /securitylevels/renumber`) nummeriert die Sicherheitsstufen neu, ohne ihre
  Reihenfolge zu ändern. Danach haben die Stufen andere IDs; gespeicherte IDs müssen neu gelesen werden.
- Neu: optionales Argument `expected_name` bei `security_levels.patch` und `security_levels.delete` (Rust:
  `PatchSecuritylevelsIdBody::expected_name`, `DeleteSecuritylevelsIdQuery::expected_name`). Weicht der Name ab,
  lehnt der Server mit 409 ab (`Conflict`).
- `forcereorder` bei `security_levels.patch` ist veraltet (der Server ignoriert es) und erzeugt eine Warnung.
- `API_VERSION`/`API_BUILD` sind jetzt `3.138.3`/`32945`.

## [0.1.0] – 2026-10-30

Erste Veröffentlichung. Generiert aus der API-Beschreibung von ChurchTools 3.138.1 (Build 32938): 849 Operationen,
1110 Modelle.

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
