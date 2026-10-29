# Changelog

Alle nennenswerten Änderungen am Rust-Crate und am Python-Paket `churchtools-api`. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen [SemVer](https://semver.org/lang/de/);
vor 1.0 kann jede Minor-Version inkompatible Änderungen enthalten. Wie Versionen und ChurchTools-Versionen
zusammenhängen, steht im README unter „ChurchTools-Versionen und Kompatibilität“.

## [0.1.0] – unveröffentlicht

Erste Veröffentlichung. Generiert aus der API-Beschreibung von ChurchTools 3.138.0 (Build 32935): 849 Operationen,
1110 Modelle.

- Rust-Crate `churchtools-api`: `Client`/`ClientBuilder` (`timeout`, `connect_timeout`, `max_response_size`,
  `allow_insecure_http`, `from_env`), generierte Ressourcen (`client.events().list_with(&query)`), Modelle mit
  `Default` und `extra`, lazy Iteratoren `…_iter` und `Client::items`, `Error` mit `is_not_found()`, `status()`,
  `api()`; die HTTP-Bibliothek ist nicht Teil der öffentlichen API (`Method`, `TransportError`).
- Python-Paket `churchtools-api`: `Client` mit denselben Optionen, generierte Ressourcen
  (`client.events.list(...)`), Pydantic-Modelle mit `model_extra`, `Paginator`, Ausnahmen `NotFound`,
  `Unauthorized`, `Forbidden`, `UnprocessableEntity`, `ConnectError`, `Timeout`, `ResponseTooLarge`,
  `RedirectError`, `DecodeError`, `InvalidArgument`; Argumente mit fester Werteliste als `Literal[...]`.
- Sicherheit: nur `https://` (Ausnahme `localhost`, sonst `allow_insecure_http`); Token nicht in Debug-Ausgaben
  und Fehlermeldungen; Weiterleitungen 301/302/303 werden nicht verfolgt; leere, `.`- und `..`-Pfadsegmente werden
  abgelehnt; Antwortgröße begrenzt (256 MiB).
- Rate-Limit (`min_interval`) und Wiederholungen: `429` nach `Retry-After` (Sekunden oder Datum), `502`/`503`/`504`
  für idempotente Methoden, Verbindungsfehler einmal.
- Toleranzregeln für Abweichungen der API von der Spec (Zahlen als String, PHP-Nulldatum, `[]` als leeres Objekt,
  Array-Parameter mit `[]`, leere 204-Antworten) und Einzelkorrekturen aus den Live-Tests.
- Datei-Uploads (`Upload`), `login_with_password`, veraltete Endpunkte und Argumente markiert
  (`@deprecated`, `#[deprecated]`), `API_VERSION`/`API_BUILD`, `churchtools_api.__version__`.
- TLS über rustls mit `ring` und dem Trust-Store des Betriebssystems.
- Doku-Seite mit Einstieg, Grundlagen, Beispielprojekten und Referenz; alle Beispiele laufen als Tests.
- Lizenz MIT; generierte Dateien zusätzlich CC BY 4.0 (API-Beschreibung von ChurchTools), siehe `NOTICE`.
