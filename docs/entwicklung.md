# Entwicklung

Diese Seite ist für alle, die an Settings Switcher mitarbeiten oder das Repository selbst pflegen (Images veröffentlichen,
Releases erstellen). Wer das Tool nur benutzt, braucht sie nicht: siehe [README](../README.de.md) und
[Betrieb](betrieb.md).

## Tests

```bash
make test               # oder: python3 -m pytest
```

Die Tests brauchen Chromium für Playwright.

Automatisch getestet: Schema-Validierung, Host-Prüfung, Variablen, Editor-API, Versionskopplung von Playwright-Pin und
-Image, die Neubau-Entscheidung von `run.sh` (mit Docker-Attrappe), die Wiederholung bei Exit 1 (ebenfalls mit
Docker-Attrappe), Editor-Oberfläche im echten Browser (inkl. XSS- und CSP-Prüfung), Läufe des Runners in Chromium
gegen eine lokale Testseite, der Live-Recorder (Selektoren, Passwortbehandlung, Scrollen, WebSocket-Absicherung) und der
ganze Weg „im Editor aufzeichnen → speichern → mit dem Runner abspielen“ gegen eine lokale Testseite. Ebenso die
Stopmarke (Abspielen bis zur Marke, Anhalten bei Login-, TODO- und fehlgeschlagenen Schritten, Einfügen hinter der
Marke, Bedienung in der Oberfläche), ebenfalls nur gegen die lokale Testseite. Ebenso die Wenn-Blöcke (Schema und
Strukturprüfung, Läufe des Runners in Chromium mit beiden Zweigen, Wiedergabe bis zur Stopmarke, Aufnahme eines Blocks
per Klick im Editor mit anschließendem Runner-Lauf) und die Aufzeichnungspause. Die Prüfung von `EDITOR_ALLOWED_IPS`
steckt in `tests/test_editor.py` und `tests/test_recorder_ws.py`.

Manuell getestet: Docker-Build der Images, `run.sh` mit echtem `docker run` und Aufzeichnen sowie Abspielen gegen eine
echte Fritzbox 7590 mit FRITZ!OS 8.25 (Portfreigabe an/aus). Die Wenn-Blöcke (Version 1.2.0) und die Aufzeichnungspause
(Version 1.3.0) sind zusätzlich im Editor mit dem Live-Browser von Hand ausprobiert. Der Docker-Teil läuft nicht in den
automatischen Tests.

Noch nicht gegen echtes Docker oder Gerät getestet:

- `make start` und `make stop`; ob `docker compose` ein fehlendes Image selbst baut oder holt
- die Wiederholung (`-r`) auf einer echten Fritzbox
- die Stopmarke gegen eine echte Fritzbox (insbesondere das Abspielen des Logins mit Anhalten und Selbst-Eintippen im
  Live-Browser)
- `EDITOR_ALLOWED_IPS` mit echtem Docker-Netz und einem Reverse Proxy (Nginx Proxy Manager)

## Runner-Image und `run.sh`

`run.sh` baut das Runner-Image selbst, wenn es fehlt oder sich `runner/Dockerfile`, `runner/requirements.txt`,
`runner/runner.py` oder `shared/` seit dem letzten Bau geändert haben. Die Prüfsumme dieser Quellen steht als Image-Label
`ss.source-hash`. Bauen vor Ort ist bewusst der Standard: Es passt immer zum Checkout, funktioniert auch auf ARM-Hosts,
und es braucht kein Vertrauen in ein fertiges Image. Das veröffentlichte Runner-Image benutzt `run.sh` nicht; der
Workflow baut es mit, damit ein kaputter Build auffällt. Ein optionaler Schalter zum Holen aus der Registry wäre möglich,
ist aber nicht umgesetzt.

## Image-Workflow und Registry

Der Workflow [`docker-image.yml`](../.github/workflows/docker-image.yml) baut bei Änderungen an `runner/`, `editor/`,
`recorder/`, `shared/`, `requirements-dev.txt`, `VERSION` oder am Workflow selbst drei Images und veröffentlicht sie in
der GitHub Container Registry (`<owner>` ist der GitHub-Benutzer oder die Organisation, der das Repo gehört):

| Image | Inhalt |
| --- | --- |
| `ghcr.io/<owner>/settings-switcher-runner` | Runner, führt ein Profil aus |
| `ghcr.io/<owner>/settings-switcher-recorder` | Editor mit Live-Browser |
| `ghcr.io/<owner>/settings-switcher-editor` | Editor ohne Browser |

| Auslöser | Tags |
| --- | --- |
| Push auf `main` | `latest`, `sha-<kurz>` |
| Git-Tag `vX.Y.Z` (muss zur Datei `VERSION` passen, sonst bricht der Lauf ab) | `X.Y.Z`, `X.Y`, `latest` |
| Pull Request | nur Bauen, keine Veröffentlichung |
| Manuell (Actions → Run workflow) | wie Push auf `main` |

Vor dem Bauen prüft der Workflow, dass der Playwright-Pin zum Playwright-Image in den Dockerfiles passt
(`tests/test_versions.py`). Gebaut wird für `linux/amd64`. Änderungen an der Doku, am Makefile, an den READMEs oder an
`tests/` lösen keinen Build aus.

Ein neu angelegtes Paket ist zunächst **privat**, auch bei einem öffentlichen Repo. Soll es ohne Anmeldung ladbar sein,
die Sichtbarkeit in den Paket-Einstellungen auf GitHub ändern.

## Abhängigkeiten aktuell halten

Dependabot (`.github/dependabot.yml`) prüft montags die pip-Pins, die Docker-Images und die GitHub Actions im Workflow und
öffnet höchstens einen gemeinsamen Pull Request pro Woche. Gemeinsam deshalb, weil Playwright-Pin
(`runner/requirements.txt`, `requirements-dev.txt`) und Playwright-Image (`FROM` in `runner/Dockerfile` und
`recorder/Dockerfile`) dieselbe Version haben müssen; `tests/test_versions.py` prüft das. Neue Releases wartet Dependabot
fünf Tage ab (Cooldown), weil das Playwright-Image nicht immer am selben Tag wie das PyPI-Paket erscheint.

Vor dem Merge: `python3 -m pytest`. Pull Requests, die Quellen oder die Dockerfiles berühren, bauen die Images zur Prüfung
(ohne Veröffentlichung). Nach dem Zusammenführen veröffentlicht der Workflow das neue `latest`. Dependabot ändert den
`CHANGELOG.md` nicht; wer einen Eintrag will, ergänzt ihn von Hand unter „Unreleased“.

## Versionierung und Releases

- [Semantic Versioning](https://semver.org/lang/de/): `MAJOR.MINOR.PATCH`. MAJOR bei inkompatiblen Änderungen (z. B.
  umbenannte Umgebungsvariablen oder geändertes Profil-Format), MINOR bei neuen Funktionen, PATCH bei Fehlerkorrekturen.
- Einzige Quelle der Version ist die Datei `VERSION`. Der Workflow setzt sie als Image-Label
  `org.opencontainers.image.version` und nutzt sie für den Abgleich mit dem Git-Tag.
- Jede Änderung, die Anwender betrifft, kommt unter `## [Unreleased]` in den [CHANGELOG](../CHANGELOG.md).
- Release-Ablauf:
  1. Änderungen unter `## [Unreleased]` sammeln, committen und nach `main` pushen.
  2. Release auslösen, auf eine von zwei Arten (`make` ohne Ziel zeigt die Hilfe mit allen Zielen und Parametern):
     - `make release V=X.Y.Z`: Version als Parameter; das Ziel setzt `VERSION` selbst.
     - `make release` (ohne `V`): Die Version kommt aus der Datei `VERSION`, die du vorher erhöht und committet hast. Der
       Tag `vX.Y.Z` wird daraus gebaut.
  3. Den Workflow-Lauf zum Tag abwarten (er veröffentlicht `X.Y.Z`), dann auf dem Host `make pull` und neu starten.

  `make release` prüft zuerst, dass der Branch `main` ist und der Arbeitsbaum sauber, und holt dann selbst mit
  `git pull --ff-only origin main` den Stand von `origin` (ein `git pull` vorher ist nicht nötig; der Pull bricht ab, wenn
  lokale Commits nicht auf `origin/main` liegen). Erst danach liest es die Datei `VERSION` und prüft vor jeder Änderung:
  die Version (`V`, sonst der Inhalt von `VERSION`) ist eine gültige Version `X.Y.Z`, nicht niedriger als die Datei
  `VERSION` und höher als der letzte Tag; der Tag `vX.Y.Z` existiert noch nicht; und im CHANGELOG gibt es entweder schon
  einen Abschnitt `## [X.Y.Z]` oder unter `## [Unreleased]` mindestens einen Eintrag (`- …`).

  Danach setzt es `VERSION` (nur relevant bei `V`), benennt den Abschnitt `## [Unreleased]` in `## [X.Y.Z] - JJJJ-MM-TT`
  um (darüber entsteht ein neuer leerer Abschnitt; entfällt, wenn der Abschnitt `## [X.Y.Z]` schon von Hand angelegt ist)
  und committet („Settings Switcher X.Y.Z“), sofern sich Dateien geändert haben. Dann setzt es den annotierten Tag
  `vX.Y.Z` und führt `git push --follow-tags origin main` aus. Schlägt der Push fehl, bleiben Tag und gegebenenfalls
  Commit lokal; die Meldung nennt den Befehl zum Zurücknehmen.

  Ohne `make` von Hand: `VERSION` erhöhen, Abschnitt umbenennen, committen,
  `git tag -a vX.Y.Z -m "Settings Switcher X.Y.Z"`, `git push --follow-tags`.

## Regeln für Änderungen

- Erlaubte Hosts kommen nur aus `SWITCHER_ALLOWED_HOSTS`, nie aus einem Profil.
- Zugangsdaten stehen nur in `runner.env`, nie in Profilen, Editor oder Recorder. Im Profil sind sie nur als
  `${SWITCHER_USER}` / `${SWITCHER_PASSWORD}` bei `fill` erlaubt.
- Keine Operation für freies JavaScript im Profil-Schema.
- Die Container bleiben gehärtet (`--rm`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, Limits).
- Gepinnte Versionen (Playwright, fastapi, uvicorn, websockets) und das Playwright-Image müssen zusammenpassen
  (`tests/test_versions.py`).
- Keine privaten Daten in Dateien, Doku, Beispielen oder Commits (nur die Fritzbox-Standardadresse `192.168.178.1` und
  Beispiel-IPs).
- Commit-Nachrichten auf Deutsch: kurzer Betreff, bei Bedarf Liste der Änderungen.
