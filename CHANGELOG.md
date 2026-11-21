# Changelog

Alle nennenswerten Änderungen am Rust-Crate `churchtools-api` und am Python-Paket `churchtools-api-rs`. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen [SemVer](https://semver.org/lang/de/);
vor 1.0 kann jede Minor-Version inkompatible Änderungen enthalten. Wie Versionen und ChurchTools-Versionen
zusammenhängen, steht im README unter „ChurchTools-Versionen und Kompatibilität“.

## [Unreleased]

Generiert aus der API-Beschreibung von ChurchTools 3.138.3 (Build 32945): 850 Operationen, 1110 Modelle. Keine
inkompatiblen Änderungen.

- Neu: `security_levels.renumber()` (`POST /securitylevels/renumber`) nummeriert die Sicherheitsstufen neu, ohne ihre
  Reihenfolge zu ändern. Danach haben die Stufen andere IDs; gespeicherte IDs müssen neu gelesen werden.
- Neu: optionales Argument `expected_name` bei `security_levels.patch` und `security_levels.delete` (Rust:
  `PatchSecuritylevelsIdBody::expected_name`, `DeleteSecuritylevelsIdQuery::expected_name`). Weicht der Name ab,
  lehnt der Server mit 409 ab (`Conflict`).
- `forcereorder` bei `security_levels.patch` ist veraltet (der Server ignoriert es) und erzeugt eine Warnung.
- `API_VERSION`/`API_BUILD` sind jetzt `3.138.3`/`32945`.
- Live-Tests: neues Szenario für Sicherheitsstufen; Testbericht um „Änderungen in 3.138.3“ ergänzt.
- Live-Tests hängen nicht mehr von instanzspezifischen IDs ab: Sicherheitsstufe und Datenschutz-Auswahlwerte werden
  nachgeschlagen (Fixture `ids`), `renumber()` läuft als eigenes Szenario, `seed.py` legt einen Termin im ersten
  Kalender und einen Fakt an einer Veranstaltung an.

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
