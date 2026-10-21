# Changelog

Alle nennenswerten Änderungen stehen hier. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionierung
[Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefügt
- `make start` und `make stop` starten und beenden den Recorder (Editor mit Live-Browser) oder den Editor ohne Browser:
  `make start recorder`, `make stop recorder`, `make start editor`. Ohne Angabe gilt der Recorder.

### Geändert
- `make build` und `make pull` nehmen den Dienst jetzt wie `start` und `stop` hinter dem Ziel (`make pull editor`
  statt `make pull P=editor`); der Parameter `P` entfällt.

## [1.0.0] - 2026-10-21

Erste veröffentlichte Version unter dem Namen Settings Switcher.

### Funktionen
- Profile: Ein Ablauf auf einer Weboberfläche besteht aus einer Liste fester Schritte (JSON in `profiles/`,
  Operationen wie `goto`, `click`, `fill`, `check`/`uncheck`, `wait_for`, `expect_*`). Es gibt bewusst keine
  Operation für freies JavaScript. Profile enthalten keine Zugangsdaten, diese stehen nur in `runner.env`.
- `run.sh <profil>`: startet einen frischen, gehärteten Container, führt das Profil im Browser (Playwright/Chromium)
  aus und entfernt den Container wieder. Exit-Codes: 0 erfolgreich, 1 Lauf fehlgeschlagen, 2 Aufruf- oder
  Konfigurationsfehler. Optional Screenshots (`-s`) und Wiederholung des ganzen Laufs bei Exit 1 (`-r <n>`).
- `run.sh` baut das Runner-Image selbst neu, wenn es fehlt oder sich die Quellen geändert haben.
- Erlaubte Webseiten kommen nur aus `SWITCHER_ALLOWED_HOSTS`, nie aus einem Profil; der Browser blockiert alles andere.
- Editor: kleine Webseite zum Anlegen und Ändern der Profile, mit Token, Host-Prüfung und optionaler Begrenzung
  auf bestimmte IP-Adressen (`EDITOR_ALLOWED_IPS`).
- Live-Recorder: Der Editor mit eingebettetem Browser zeichnet einen Ablauf beim Durchklicken als Schritte auf
  (auch per Touch bedienbar). Passwörter werden nie im Klartext gespeichert. Mit Stopmarke lässt sich ab einer
  Stelle weiter aufzeichnen.
- Dependabot prüft wöchentlich die Abhängigkeiten, in einem gemeinsamen Pull Request, damit Playwright-Pin und
  Playwright-Image zusammenpassen (`tests/test_versions.py`).

### Hinzugefügt
- GitHub-Actions-Workflow `.github/workflows/docker-image.yml`: baut die Images `settings-switcher-runner`,
  `settings-switcher-recorder` und `settings-switcher-editor` und veröffentlicht sie in der GitHub Container
  Registry (`ghcr.io/<owner>/…`). Push auf `main` ergibt `latest` und `sha-<kurz>`, ein Tag `vX.Y.Z` ergibt `X.Y.Z`,
  `X.Y` und `latest`. Pull Requests bauen nur zur Prüfung. Vorher prüft der Workflow, dass der Tag zur Datei
  `VERSION` passt und der Playwright-Pin zum Playwright-Image.
- `Makefile` mit Hilfe (`make` ohne Ziel) und den Zielen `version`, `test`, `build`, `pull` (je für den Recorder oder den Editor, `P=record|editor`) und `release`.
  `make release` prüft die Voraussetzungen, übernimmt den Abschnitt „Unreleased“ in den neuen Versionsabschnitt, setzt
  den Tag `vX.Y.Z` und pusht ihn; den Rest übernimmt der Workflow.
- `CHANGELOG.md` und die Datei `VERSION` als einzige Quelle der Version.
- Dokumentation in `docs/` (Konfiguration, Profile und Aufzeichnen, Betrieb, Fehlersuche, Sicherheit und Grenzen).
- `README.de.md` (deutsch) neben der englischen `README.md`.
- Dependabot beobachtet jetzt auch die GitHub Actions im Workflow.

### Geändert
- `README.md` ist kurz und allgemeinverständlich; die technischen Teile stehen in `docs/`.
- `docker-compose.yml`: Die Image-Namen von Editor und Recorder sind über `SWITCHER_EDITOR_IMAGE` und
  `SWITCHER_RECORDER_IMAGE` einstellbar, damit sich die veröffentlichten Images nutzen lassen. Ohne die Variablen
  ändert sich nichts (lokal gebaute Images wie bisher).
- `.gitignore`: Eigene Profile (`profiles/*.json`, außer `beispiel.json`) werden nicht versehentlich eingecheckt,
  weil sie Adressen und Selektoren der eigenen Geräte enthalten.

### Hinweise
- Getestet mit einer Fritzbox 7590 (FRITZ!OS 8.25): Aufzeichnen und Abspielen einer Portfreigabe (an/aus).
  Die Stopmarke ist noch nicht gegen ein echtes Gerät getestet.
