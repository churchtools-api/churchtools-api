# Changelog

Alle nennenswerten Änderungen an `churchtools-core` (Rust) und `churchtools-rs` (Python). Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen [SemVer](https://semver.org/lang/de/);
vor 1.0 kann jede Minor-Version inkompatible Änderungen enthalten. Wie Versionen und ChurchTools-Versionen
zusammenhängen, steht im README unter „Versionen“.

## [Unreleased]

Generiert aus der API-Beschreibung von ChurchTools 3.138.0 (Build 32935).

### Inkompatible Änderungen

- `http://` ist nur noch für `localhost`/Loopback erlaubt, sonst mit `allow_insecure_http`.
- Weiterleitungen 301/302/303 werden nicht mehr verfolgt (`RedirectError` / `Error::Redirect`).
- Rust: `Error` hat neue Varianten und ist `#[non_exhaustive]`; ein `match` braucht einen `_`-Zweig.
- Rust: `Upload::content` ist `Arc<[u8]>`.
- Rust: `…Query`/`…Form`-Structs liegen in `churchtools_core::queries`, die Ressourcen in
  `churchtools_core::resources`; die Crate-Wurzel re-exportiert sie nicht mehr.
- Rust: nullbare optionale Felder von Modellen, die nur in Request-Bodies vorkommen, sind `Option<Option<T>>`.
- Rust: Map-, Listen- und String-Bodies sind typisiert statt `serde_json::Value`.
- Namen: zusammengeschriebene Pfadteile werden getrennt (`agendatemplates` → `agenda_templates`,
  `get_masterdata` → `get_master_data`, …); lesende POST-Aufrufe heißen `actions.filter`, `probes.filter`,
  `domain_objects.resolve`, `finance.accounting_periods.statements.preview`, `repeat_calculation.calculate`.
- Python: Argumente mit fester Werteliste sind `Literal[...]`; mypy meldet andere Werte.
- Python: `DecodeError` hängt die `ValidationError` nicht mehr an (sie enthielte die Eingabewerte).

### Neu

- `ClientBuilder` mit `timeout`, `connect_timeout` (Standard 10 s), `max_response_size` (Standard 256 MiB) und
  `allow_insecure_http`; in Python als Argumente von `Client`.
- Wiederholung bei `502`/`503`/`504` für idempotente Methoden, einmal bei Verbindungsfehlern; `Retry-After`
  auch als Datum.
- Python-Ausnahmen `InvalidArgument` (auch `ValueError`), `ConnectError`, `Timeout`, `ResponseTooLarge`,
  `RedirectError`.
- Rust: `Error::is_not_found()`, `is_unauthorized()`, `is_forbidden()`, `is_timeout()`, `is_connect()`,
  `status()`, `api()`.
- Rust: `Default` für alle Modelle, Bodies als Struct-Literal; lazy Iteratoren `…_iter` und `Client::items`.
- Erlaubte Werte (Enums) in der Doku, `Literal[...] | str` in Python-Antworten.
- Veraltete Endpunkte und Argumente sind markiert (`@deprecated` nach PEP 702, `#[deprecated]`).
- `API_VERSION`/`API_BUILD` in beiden Sprachen, `churchtools_rs.__version__`.
- Lizenzdatei (MIT) und `NOTICE` mit der Namensnennung der API-Beschreibung (CC BY 4.0).

### Behoben

- Leere, `.`- und `..`-IDs konnten den Pfad einer Anfrage verändern; sie werden jetzt abgelehnt.
- Ungültige Zeitwerte führten in Python zu einem Panic statt zu einem `ValueError`.
- Token, Response-Bodies und Eingabewerte tauchen nicht mehr in `Debug`-Ausgaben und Fehlermeldungen auf.
- Eine leere Seite beendet das Blättern.
- Aufgezeichnete Antworten enthielten Zugangsdaten und den Namen der Testinstanz.

### Veraltet

- Rust: `Client::with_timeout`, stattdessen `Client::builder(url).timeout(..)`.
- Python: `ApiError.args_`, stattdessen `ApiError.message_args`.
