# Sicherheit

## Eine Sicherheitslücke melden

Bitte melde Sicherheitslücken **nicht** als öffentliches Issue, sondern vertraulich über GitHub:
auf der Seite des Repositories unter **Security → Report a vulnerability** („Private vulnerability reporting“).
Die Meldung sieht nur der Betreuer des Projekts; über denselben Weg bekommst du Rückmeldung.

Hilfreich sind: betroffene Version (`churchtools_api.__version__` bzw. die Crate-Version), was passiert, und wie
man es nachstellt. Bitte keine echten Token, Passwörter oder Personendaten mitschicken.

Das Projekt wird in der Freizeit gepflegt. Ich bemühe mich, innerhalb von zwei Wochen zu antworten.

## Unterstützte Versionen

Sicherheitskorrekturen gibt es für die jeweils neueste veröffentlichte Version.

## Was im Rahmen des Clients liegt

Relevant sind vor allem der Umgang mit dem Login-Token und mit Antwortdaten:

- Der Client verlangt `https://`; `http://` ist nur für `localhost` und ausdrücklich mit `allow_insecure_http` erlaubt.
- Das Token wird als sensibler Header gesetzt und erscheint nicht in Debug-Ausgaben, Fehlermeldungen oder Logs
  des Clients.
- Antwort-Bodies werden in Fehlermeldungen nur gekürzt angezeigt; vollständige Bodies liegen in
  `DecodeError.body`/`ApiError.body` und sollten nicht ungeprüft geloggt werden.
- Weiterleitungen, die eine schreibende Anfrage als `GET` wiederholen würden (301, 302, 303), werden nicht verfolgt.
- Pfadparameter werden kodiert; leere, `.`- und `..`-Segmente werden abgelehnt.

Fehler in ChurchTools selbst (dem Server) gehören an ChurchTools, nicht an dieses Projekt.
