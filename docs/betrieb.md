# Betrieb

## Profile ausführen

```
./run.sh portfreigabe-an          # Profil ausführen
./run.sh -s portfreigabe-an       # Screenshot nach jedem Schritt (artifacts/)
./run.sh -r 2 portfreigabe-an     # bei Exit 1 den ganzen Lauf bis zu 2-mal wiederholen
./run.sh --list                   # Profile anzeigen
```

Einrichtung (Zugangsdaten, erlaubte Hosts): [Konfiguration](konfiguration.md). Exit-Codes: 0 = erfolgreich, 1 = Lauf
fehlgeschlagen, 2 = Aufruf- oder Konfigurationsfehler.

## Wiederholung bei Fehlern (`-r`)

Läuft ein Profil manchmal nicht durch (meist Timing: die Fritzbox-Oberfläche lädt Inhalte nach), kann
`run.sh` den **ganzen Lauf** neu starten, nicht nur den letzten Schritt. Jeder Versuch ist ein frischer
Container mit neuem Browser und neuem Login, ein halb erledigter Zustand aus dem Versuch davor bleibt nicht hängen.

- `-r <n>` (oder `SWITCHER_RETRIES=<n>` in der Shell) erlaubt bis zu `n` zusätzliche Versuche, 0 bis 5.
  Standard ist 0, ohne die Option ändert sich nichts. Die Option steht nicht in `runner.env`, weil `run.sh`
  diese Datei nur an den Container weiterreicht.
- Wiederholt wird **nur bei Exit 1** (Schritt oder Prüfung fehlgeschlagen, auch Zeitgrenze). Exit 2
  (Konfiguration, `TODO` im Profil) und Docker-Fehler (Exit 125 und höher) werden nie wiederholt.
- Zwischen den Versuchen wartet `run.sh` `SWITCHER_RETRY_DELAY_S` Sekunden (Standard 15, höchstens 300).
  Die Pause schützt vor einer Anmeldesperre der Fritzbox nach mehreren Fehlversuchen. Lieber wenige
  Versuche (`-r 1` oder `-r 2`) als viele.
- Nach dem letzten Fehlversuch endet `run.sh` mit Exit 1. Jeder Versuch legt bei einem Fehler seinen
  eigenen Screenshot `…-fehler.png` in `artifacts/` ab.
- **Sicher ist das nur, wenn ein zweiter Lauf harmlos ist.** `check`/`uncheck` setzen einen festen Zustand und
  vertragen das. Ein `click`, der einen Zustand umschaltet, kann beim Wiederholen die Änderung wieder zurückdrehen.
  Setze deshalb `check`/`uncheck` statt `click` auf Checkboxen und eine `expect_*`-Prüfung nach dem Übernehmen
  (siehe [Profile](profile.md)). Der Runner weist im Log darauf hin, wenn ein Profil keine `expect_*`-Prüfung hat.
- Nicht auf einer echten Fritzbox getestet. Die Wiederholung ist durch Tests mit der Docker-Attrappe abgedeckt.

## Editor und Recorder starten und beenden

```bash
make start recorder       # Editor mit Live-Browser starten, Standard-Adresse http://127.0.0.1:8080
make stop recorder        # beenden und den Container entfernen
make start editor         # Editor ohne Browser (stop, build und pull ebenso)
```

- `recorder` ist die Vorgabe, `make start` allein startet also den Recorder. `make start` entspricht
  `docker compose --profile record up -d`, `make stop` entspricht `docker compose --profile record down`.
- Editor und Recorder teilen sich Port und Containernamen, es läuft immer nur einer von beiden. Deshalb nimmt jedes
  dieser Ziele genau einen Dienst.
- `start` benutzt das Image, das die `.env` vorgibt: ohne `SWITCHER_RECORDER_IMAGE` / `SWITCHER_EDITOR_IMAGE` das lokal
  gebaute (`settings-switcher-recorder`, `settings-switcher-editor`), sonst das dort eingetragene Registry-Image. Ein
  vorhandenes Image wird nicht aktualisiert: nach einem Update vorher `make build recorder` (lokal neu bauen) oder, mit
  Registry-Namen in der `.env`, `make pull recorder`. Ob `docker compose` ein fehlendes Image selbst baut oder holt, ist hier
  nicht geprüft; wer sicher gehen will, ruft vorher `build` bzw. `pull` auf.
  Das Runner-Image braucht dafür nichts: `run.sh` baut es selbst.
- Der Recorder erreicht den Router, deshalb nur bei Bedarf starten und danach `make stop recorder`.

## Image-Workflow und Registry

Der Workflow [`docker-image.yml`](../.github/workflows/docker-image.yml) baut bei Änderungen an `runner/`, `editor/`,
`recorder/`, `shared/`, `requirements-dev.txt` oder `VERSION` drei Images und veröffentlicht sie in der GitHub Container
Registry (`<owner>` ist der GitHub-Benutzer oder die Organisation, der das Repo gehört):

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
(`tests/test_versions.py`). Gebaut wird für `linux/amd64`. Änderungen an der Doku oder an `tests/` lösen keinen Build aus.

### Veröffentlichte Images nutzen

1. In der `.env` die Variablen `SWITCHER_EDITOR_IMAGE` und/oder `SWITCHER_RECORDER_IMAGE` auf das Image samt Tag setzen
   (siehe [Konfiguration](konfiguration.md#veröffentlichte-images-statt-lokalem-bau-optional)).
2. Holen und starten, ohne `--build`:

```bash
make pull recorder        # oder: docker compose --profile record pull
make start recorder       # oder: docker compose --profile record up -d
```

- Ein neu angelegtes Paket ist zunächst **privat**, auch bei einem öffentlichen Repo. Soll es ohne Anmeldung ladbar sein,
  die Sichtbarkeit in den Paket-Einstellungen auf GitHub ändern. Bei einem privaten Paket einmalig auf dem Docker-Host
  anmelden (Token mit dem Recht `read:packages`):

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u <benutzer> --password-stdin
```

- `run.sh` baut sein Runner-Image weiterhin selbst aus den lokalen Quellen (siehe [Konfiguration](konfiguration.md)).
  Das veröffentlichte Runner-Image benutzt `run.sh` nicht; der Workflow baut es mit, damit ein kaputter Build
  auffällt.

## Abhängigkeiten aktuell halten

Dependabot (`.github/dependabot.yml`) prüft montags die pip-Pins, die Docker-Images und die GitHub Actions im Workflow und öffnet
höchstens einen gemeinsamen Pull Request pro Woche. Gemeinsam deshalb, weil Playwright-Pin
(`runner/requirements.txt`, `requirements-dev.txt`) und Playwright-Image (`FROM` in `runner/Dockerfile`
und `recorder/Dockerfile`) dieselbe Version haben müssen; `tests/test_versions.py` prüft das.
Vor dem Merge: `python3 -m pytest`. Nach dem Merge und `git pull` baut `run.sh` den Runner beim
nächsten Aufruf selbst neu (siehe [Konfiguration](konfiguration.md)); Editor und Recorder brauchen
`docker compose --profile record up -d --build`. Neue Releases wartet Dependabot fünf Tage ab
(Cooldown), weil das Playwright-Image nicht immer am selben Tag wie das PyPI-Paket erscheint.

Pull Requests, die Quellen oder die Dockerfiles berühren, bauen die Images zur Prüfung (ohne Veröffentlichung). Nach dem
Zusammenführen veröffentlicht der Workflow das neue `latest`. Dependabot ändert den `CHANGELOG.md` nicht; wer einen Eintrag
will, ergänzt ihn von Hand unter „Unreleased“.

## Versionierung und Releases

- [Semantic Versioning](https://semver.org/lang/de/): `MAJOR.MINOR.PATCH`. MAJOR bei inkompatiblen Änderungen (z. B.
  umbenannte Umgebungsvariablen oder geändertes Profil-Format), MINOR bei neuen Funktionen, PATCH bei Fehlerkorrekturen.
- Einzige Quelle der Version ist die Datei `VERSION`. Der Workflow setzt sie als Image-Label
  `org.opencontainers.image.version` und nutzt sie für den Abgleich mit dem Git-Tag.
- Release-Ablauf:
  1. Änderungen unter `## [Unreleased]` im [CHANGELOG](../CHANGELOG.md) sammeln, committen und nach `main` pushen.
  2. Release auslösen, auf eine von zwei Arten (`make` ohne Ziel zeigt die Hilfe mit allen Zielen und Parametern):
     - `make release V=X.Y.Z`: Version als Parameter; das Ziel setzt `VERSION` selbst.
     - `make release` (ohne `V`): Die Version kommt aus der Datei `VERSION`, die du vorher erhöht und committet hast. Der Tag `vX.Y.Z` wird daraus gebaut.
  3. Den Workflow-Lauf zum Tag abwarten (er veröffentlicht `X.Y.Z`), dann auf dem Host `make pull` und neu starten.

  `make release` prüft zuerst, dass der Branch `main` ist und der Arbeitsbaum sauber, und holt dann selbst mit
  `git pull --ff-only origin main` den Stand von `origin` (ein `git pull` vorher ist nicht nötig; der Pull bricht ab, wenn
  lokale Commits nicht auf `origin/main` liegen). Erst danach liest es die Datei `VERSION` und prüft vor jeder Änderung: die
  Version (`V`, sonst der Inhalt von `VERSION`) ist eine gültige Version `X.Y.Z`, nicht niedriger als die Datei `VERSION` und
  höher als der letzte Tag; der Tag `vX.Y.Z` existiert noch nicht; und im CHANGELOG gibt es entweder schon einen Abschnitt
  `## [X.Y.Z]` oder unter `## [Unreleased]` mindestens einen Eintrag (`- …`).

  Danach setzt es `VERSION` (nur relevant bei `V`), benennt den Abschnitt `## [Unreleased]` in `## [X.Y.Z] - JJJJ-MM-TT` um
  (darüber entsteht ein neuer leerer Abschnitt; entfällt, wenn der Abschnitt `## [X.Y.Z]` schon von Hand angelegt ist) und
  committet („Settings Switcher X.Y.Z“), sofern sich Dateien geändert haben. Dann setzt es den annotierten Tag `vX.Y.Z` und
  führt `git push --follow-tags origin main` aus. Schlägt der Push fehl, bleiben Tag und gegebenenfalls Commit lokal; die
  Meldung nennt den Befehl zum Zurücknehmen.

  Ohne `make` von Hand: `VERSION` erhöhen, Abschnitt umbenennen, committen,
  `git tag -a vX.Y.Z -m "Settings Switcher X.Y.Z"`, `git push --follow-tags`.
