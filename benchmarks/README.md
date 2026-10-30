# Benchmarks

Wenige, bewusst ausgewählte Szenarien (nicht ein Benchmark pro Endpunkt). Sie liefern Vergleichszahlen für den Client
selbst (Rust und Python-Paket) und vergleichen das Python-Paket mit reinen Python-Implementierungen derselben Aufrufe.

Alles läuft offline gegen einen lokalen Server, nie gegen eine echte ChurchTools-Instanz.

## Was gemessen wird

**Server** (`src/server.rs`): ein kleiner HTTP/1.1-Server auf `127.0.0.1` mit Keep-alive, der aufgezeichnete Antworten
aus `fixtures/recorded/` ausliefert. Die Antworten sind vorab kodiert, jede geht mit einem einzigen `write` raus. Für die
Liste wiederholt er die 10 aufgezeichneten Personen aus `get-persons` mit neuen IDs zu 5000 Personen. Alle Varianten
sprechen denselben Server-Prozess an, mit denselben Daten.

| Szenario | Aufruf | Antwort |
|---|---|---|
| `get_person` | `GET /persons/1` → `Person` | 1,7 KB |
| `list_persons` | `GET /persons?limit=500`, alle Seiten lazy durchlaufen → 5000 × `Person` | 10 Seiten à 813 KB |
| `create_person` | `POST /persons?force=true` mit JSON-Body (wie die Aufzeichnung) → `Person` | 1,4 KB |
| `decode_page` | nur Dekodieren einer Listenseite (500 Personen, 813 KB), ohne HTTP | – |

**Varianten**

- **Rust** (`src/main.rs`): `churchtools-api` mit den generierten Methoden (`persons().get`, `persons().list_iter`,
  `persons().create_with`) bzw. `decode_data::<Vec<Person>>`.
- **churchtools_api**: das Python-Paket (`client.persons.get/list/create`), Release-Build.
- **requests + model_validate**: wie man es typischerweise von Hand schreibt: `requests.Session`, `r.json()`,
  `Person.model_validate(...)` pro Objekt.
- **httpx + validate_json**: `httpx.Client`, Pydantic dekodiert direkt aus den Bytes (`model_validate_json`).
- **urllib3 + validate_json**: eine schlanke, effiziente Variante: `urllib3.HTTPConnectionPool`, Body mit `orjson`,
  Antwort mit `model_validate_json`.
- **nur HTTP**: dieselbe Anfrage ohne Dekodieren, als Untergrenze des jeweiligen HTTP-Stacks.
- Bei `decode_page` zusätzlich `orjson.loads` + `TypeAdapter.validate_python` und, ungetypt zum Vergleich, nur
  `json.loads` bzw. `orjson.loads`.

Alle Python-Varianten dekodieren in dieselben generierten Pydantic-Modelle (`churchtools_api.models.Person`) und halten
eine Verbindung offen. Jede Variante läuft erst mindestens 0,3 s zum Aufwärmen (dabei werden auch die Pydantic-Validatoren
gebaut, die Modelle nutzen `defer_build`), dann 15 Runden à etwa 0,1 s. Angegeben ist die Zeit pro Aufruf: Median der
Runden, in Klammern die schnellste und die langsamste Runde.

## Ausführen

Aus dem Wurzelverzeichnis des Repositories:

```bash
# Rust
cargo run --release --manifest-path benchmarks/Cargo.toml            # Optionen: -- --rounds 15 --json

# Python (einmalig einrichten, Release-Build!)
cd python
uv venv && uv pip install maturin pydantic typing_extensions -r ../benchmarks/requirements.txt
maturin develop --release
cd ..
python/.venv/bin/python benchmarks/bench.py                           # Optionen: --rounds 15 --json --only get_person
```

`benchmarks/` ist ein eigener Cargo-Workspace: `cargo test --workspace` baut ihn nicht mit, und die Bibliothek bekommt
keine zusätzlichen Abhängigkeiten. `bench.py` baut und startet den Server selbst (`churchtools-bench serve`). Die
Python-Pakete nur für die Benchmarks stehen in `requirements.txt`, nicht in den Paket-Abhängigkeiten.

## Ergebnisse

Gemessen am 29.10.2026 auf AMD Ryzen 7 7800X3D (8 Kerne, 16 Threads), 62 GB RAM, Linux 7.3.0 (CachyOS);
rustc 1.99.0, Python 3.12.13, pydantic 2.14.2 (pydantic-core 2.50.2), requests 2.34.2, httpx 0.28.1, urllib3 2.8.0,
orjson 3.13.0. Normaler Desktop, ohne CPU-Pinning; zwei Durchläufe wichen um wenige Prozent voneinander ab.

Faktor = Median geteilt durch den Median von `churchtools_api` (Python) im selben Szenario.

| Szenario | Variante | Median | min – max | Faktor |
|---|---|---:|---:|---:|
| `get_person` | Rust | 37 µs | 37 – 39 | 0,8 |
| | Rust, nur HTTP | 29 µs | 28 – 30 | |
| | **churchtools_api** | **47 µs** | 45 – 51 | 1,0 |
| | churchtools_api, nur HTTP | 31 µs | 30 – 33 | |
| | requests + model_validate | 266 µs | 257 – 274 | 5,7 |
| | httpx + validate_json | 184 µs | 181 – 190 | 3,9 |
| | urllib3 + validate_json | 97 µs | 94 – 101 | 2,1 |
| | urllib3, nur HTTP | 77 µs | 72 – 80 | |
| `list_persons` (5000) | Rust | 25,4 ms | 24,3 – 26,3 | 0,4 |
| | **churchtools_api** | **66,1 ms** | 64,2 – 81,4 | 1,0 |
| | requests + model_validate | 82,7 ms | 82,2 – 100,2 | 1,25 |
| | httpx + validate_json | 68,6 ms | 66,5 – 82,1 | 1,04 |
| | urllib3 + validate_json | 65,8 ms | 62,5 – 76,7 | 1,0 |
| `create_person` | Rust | 39 µs | 37 – 45 | 0,7 |
| | **churchtools_api** | **59 µs** | 56 – 63 | 1,0 |
| | requests + model_validate | 278 µs | 269 – 286 | 4,7 |
| | httpx + validate_json | 256 µs | 239 – 272 | 4,4 |
| | urllib3 + validate_json | 111 µs | 104 – 116 | 1,9 |
| `decode_page` (500) | Rust serde | 2,08 ms | 2,07 – 2,13 | 0,35 |
| | **validate_json (wie churchtools_api)** | **5,99 ms** | 5,93 – 6,63 | 1,0 |
| | json.loads + model_validate | 7,48 ms | 7,44 – 8,72 | 1,25 |
| | orjson.loads + validate_python | 8,05 ms | 7,87 – 8,22 | 1,34 |
| | json.loads, nur Parsen (ungetypt) | 3,64 ms | 3,54 – 4,88 | |
| | orjson.loads, nur Parsen (ungetypt) | 1,58 ms | 1,57 – 1,92 | |

## Einordnung

**Kleine Anfragen: Der Rust-Kern spart den Python-HTTP-Stack.** Eine Anfrage über `reqwest` kostet hier rund 30 µs,
aus Python fast genauso viel (31 µs); der Übergang Python → Rust fällt kaum ins Gewicht. Der reine Python-Stack braucht
für dieselbe Anfrage 77 µs (urllib3) bis gut 200 µs (requests, httpx). Das Dekodieren einer Person mit Pydantic kostet
etwa 16–20 µs und ist bei allen Python-Varianten gleich. Deshalb ist `churchtools_api` bei einzelnen Anfragen 2× schneller
als eine sorgfältige urllib3-Lösung und 4–6× schneller als requests oder httpx. Der POST ist etwas teurer als der GET,
weil das Paket den Body in Python aus den Keyword-Argumenten zusammensetzt (`_jsonable`, `json.dumps`), etwa 10 µs.

**Aber: Das ist der Unterschied auf Loopback.** Gegen eine echte Instanz kommen Netzwerk-Latenz, TLS und die
Antwortzeit des PHP-Servers dazu, typischerweise Millisekunden bis zig Millisekunden pro Anfrage (hier nicht gemessen,
die Benchmarks laufen bewusst offline). Gegenüber 0,05–0,2 ms Ersparnis ist das um Größenordnungen mehr. Bei normaler
Nutzung ist der Client netzwerkgebunden, und die Wahl des HTTP-Stacks ist für die Laufzeit praktisch egal.
Mit einem `min_interval` wie 0,25 s erst recht.

**Große Listen: Pydantic bestimmt die Zeit, nicht der Transport.** Beim Durchlaufen von 5000 Personen (8 MB JSON) sind
`churchtools_api`, urllib3 und httpx gleich schnell (66–69 ms), denn alle drei dekodieren mit Pydantic `validate_json`
(10 Seiten × 6 ms = 60 ms). Der Rust-Transport bringt hier nichts Messbares. Nur der typische Ansatz mit `r.json()` und
`model_validate` pro Objekt ist 25 % langsamer, weil er die Daten erst in Python-Dicts und dann in Modelle wandelt.
Auch `orjson` hilft dabei nicht: Es parst zwar 2,3× schneller als `json`, aber der Umweg über Python-Objekte kostet
mehr, als `validate_json` direkt aus den Bytes braucht.

**Rust selbst dekodiert etwa 3× schneller als Pydantic** (2,1 ms gegenüber 6,0 ms pro Seite), obwohl die Rust-Typen
unbekannte Felder in `extra` sammeln und Zahlen/Strings tolerant annehmen. Davon profitieren nur Rust-Nutzer: Das
Python-Paket gibt bewusst die rohen Bytes an Pydantic weiter (siehe Haupt-README), damit die Python-Seite echte
Pydantic-Modelle bekommt. Wer in Python große Datenmengen verarbeitet, spart mit dem Paket also gegenüber einer guten
reinen Python-Lösung nichts beim Dekodieren.

**Kurz:** Der Rust-Kern macht einzelne Anfragen auf Python-Seite deutlich billiger an CPU, was bei lokalen oder sehr
vielen Anfragen sichtbar wird, bei echten Instanzen aber in der Netzwerkzeit verschwindet. Bei großen Antworten ist das
Paket so schnell wie die beste reine Python-Variante, nicht schneller. Die eigentlichen Vorteile des Kerns für Python
sind Retry, Rate-Limit, Paginierung und Fehlerbehandlung an einer Stelle, weniger die Geschwindigkeit.

### Warum das Dekodieren in Pydantic bleibt

Naheliegend wäre, die Antworten im Rust-Kern zu dekodieren (3× schneller als Pydantic) und Python fertige Objekte zu
geben. Eine Aufschlüsselung der Dekodierzeit einer Listenseite (500 Personen, 866 KB; Python 3.14.8, pydantic 2.14.1,
Messung vom 30.10.2026 auf derselben Maschine) zeigt, dass das nicht viel brächte:

| Variante | Zeit |
|---|---:|
| Pydantic `validate_json` in die generierten Modelle (so macht es das Paket) | 5,0 ms |
| dasselbe ohne `extra="allow"`, ohne `coerce_numbers_to_str`, ohne die `BeforeValidator` für Nulldatum und `[]`, ohne `Literal`-Unions | je 4,8 ms |
| Pydantic-Modelle, alle Felder `Any` (keine Typprüfung, nur Objekte bauen) | 3,5 ms |
| Modelle ohne Validierung aus `orjson`-Dicts zusammensetzen (`__new__` + `__dict__`, ohne Datumstypen) | 2,2 ms |
| `orjson.loads`, nur Dicts und Listen | 1,7 ms |
| Rust `serde` (keine Python-Objekte) | 2,1 ms |

Die Toleranzregeln und die Modellkonfiguration kosten zusammen unter 5 %. Rund 3,5 ms der 5 ms gehen dafür drauf,
die Python-Objekte überhaupt zu erzeugen, und das muss jeder Ansatz tun, der Pydantic-Modelle liefert; pydantic-core
ist selbst in Rust geschrieben und dabei schon nahe am Minimum. Ein eigener Weg Rust → Python-Objekte würde bestenfalls
bei 2,5–3 ms landen (höchstens 1,7× beim Dekodieren, etwa 1,3× bei `list_persons`), müsste dafür die Validierung
umgehen und für alle 1110 Modelle eine Abbildung Rust-Struct → Pydantic-Modell pflegen, bei der Unions in Rust
untypisiert sind. Deutlich schneller würde Python nur, wenn das Paket keine Pydantic-Modelle mehr liefert, sondern
Rust-Objekte mit Attributzugriff (etwa 2 ms je Seite). Das wäre eine andere Python-API.

### Vorausladen der nächsten Seite

Was der Rust-Kern Python stattdessen bringt: Ab der zweiten Seite fordert er die jeweils nächste Seite in einem
Thread an, während Python die aktuelle dekodiert und verarbeitet. Die Netzwerkzeit überlappt so mit der Python-Zeit;
das geht nur vom Kern aus, weil ein Python-Thread dafür erst den GIL bekommen müsste, den Pydantic während des
Dekodierens hält. Gemessen gegen einen lokalen Server mit künstlicher Latenz (10 Seiten à 500 Personen, Python 3.14.8;
„Arbeit“ ist eine Warteschleife pro Element im Nutzercode):

| Latenz je Anfrage | Arbeit je Element | ohne Vorausladen | mit Vorausladen | Ersparnis |
|---:|---:|---:|---:|---:|
| 20 ms | 0 µs | 256 ms | 219 ms | 15 % |
| 20 ms | 10 µs | 307 ms | 228 ms | 25 % |
| 20 ms | 50 µs | 509 ms | 343 ms | 33 % |
| 200 ms | 0 µs | 2061 ms | 2018 ms | 2 % |
| 200 ms | 10 µs | 2108 ms | 2028 ms | 4 % |
| 200 ms | 50 µs | 2310 ms | 2068 ms | 10 % |

Die Gesamtzeit nähert sich dem Maximum aus Netzwerkzeit und Python-Zeit je Seite statt ihrer Summe. Bei einer echten
Instanz, die für eine Seite mehrere hundert Millisekunden braucht, bleibt die Ersparnis klein, solange der Nutzercode
wenig pro Element tut; sie wächst mit der Verarbeitung pro Element. Auf Loopback ändert sich nichts Messbares
(`list_persons`: 56 ms). `prefetch(False)` schaltet das Vorausladen ab.

## Grenzen

- Nur Loopback, ohne TLS. Mit HTTPS kämen Handshake (einmal je Verbindung) und Verschlüsselung dazu, für rustls und
  Pythons `ssl` unterschiedlich; das ist hier nicht gemessen.
- Ein Thread, keine parallelen Anfragen; der Speicherverbrauch ist nicht gemessen.
- Die Liste wiederholt 10 aufgezeichnete Personen. Echte Daten sind vielfältiger (mehr verschiedene Strings, eigene
  DB-Felder) und können Caches weniger gut treffen.
- `requests` ohne `Session` (eine neue Verbindung pro Anfrage) wäre langsamer als hier gemessen; verglichen ist die
  faire Variante mit wiederverwendeter Verbindung.
