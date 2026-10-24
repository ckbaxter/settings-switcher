# Changelog

Alle nennenswerten Änderungen stehen hier. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionierung
[Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

## [1.3.0] - 2026-10-24

### Hinzugefügt
- Recorder: **Aufzeichnung pausieren**. Im pausierten Zustand laufen Klicks, Eingaben und Tasten im Live-Browser,
  werden aber nicht als Schritte eingetragen. So lässt sich die Seite in einen anderen Zustand bringen, ohne dass die
  Bedienung im Profil landet. **Sonst-Zweig** pausiert dafür automatisch, **Weiter aufzeichnen** setzt fort.

### Behoben
- Doku und Hinweis im Editor zum Sonst-Zweig behaupteten, das Herstellen des Gegenzustands werde nicht aufgezeichnet.
  Das stimmte bisher nicht, jeder Klick im Live-Bild wurde als Schritt eingetragen. Mit der Pause stimmt die Aussage.

## [1.2.1] - 2026-10-24

### Behoben
- Editor: Bei der Wiedergabe bis zur Stopmarke zeigen Schritte, die ein Wenn-Block überspringt, jetzt „übersprungen“
  statt „abgespielt“. Abgespielt wurde nur, was der Recorder tatsächlich ausgeführt hat. Die Wiedergabe selbst war
  nie betroffen, es ging nur um die Anzeige.

## [1.2.0] - 2026-10-24

### Hinzugefügt
- Bedingungen in Profilen: `if_text` (Seite enthält Text, optional nur in einem Bereich) und `if_visible` (Element ist
  sichtbar) leiten einen Block ein, der mit `end_if` endet. Ein optionales `else` enthält die Schritte für den
  anderen Fall. Die Bedingung wird sofort ausgewertet (ohne Warten), Blöcke lassen sich nicht verschachteln, und ein
  unvollständiger Block ist ein Profilfehler (Exit 2). Der Runner zeigt im Log, welcher Zweig lief. Beschrieben in
  `docs/profile.md`.
- Recorder: Bedingungen lassen sich per Klick aufnehmen. **Wenn sichtbar** und **Wenn Text** legen die Bedingung samt
  `end_if` an, danach kommen die aufgezeichneten Schritte in den Wenn-Zweig. **Sonst-Zweig** legt das `else` an,
  **Block beenden** setzt dahinter fort.
- Editor: Schritte im Wenn-Block sind eingerückt, **Wenn-Block am Ende** legt `if_text`, `else` und `end_if` zusammen
  an, und die Stopmarke lässt sich nur außerhalb eines Blocks setzen. Die Wiedergabe bis zur Stopmarke wertet
  Bedingungen wie der Runner aus. `GET /api/ops` nennt zusätzlich die optionalen Felder (`optional`).

### Geändert
- Dokumentation für Anwender überarbeitet: Neu ist `docs/erste-schritte.md` (Anleitung von der Einrichtung bis zum
  ersten Lauf). `docs/betrieb.md` hat neue Abschnitte „Aus Zeitplaner oder Hausautomatisierung aufrufen“ und
  „Aktualisieren“. `docs/sicherheit-und-grenzen.md` beginnt mit einer kurzen Liste „Das solltest du tun“, die
  Maßnahmentabelle steht als Hintergrund dahinter. `docs/fehlersuche.md` nennt weitere häufige Probleme, und
  `docs/konfiguration.md` erklärt die beiden Host-Listen vorab in zwei Sätzen. Die Texte sprechen allgemein vom „Gerät“,
  die Fritzbox bleibt das Beispiel.
- Der Teil für Entwickler (Image-Workflow, Registry, Dependabot, Releases, Teststand) steht jetzt in
  `docs/entwicklung.md` und nicht mehr in den Anwenderseiten. Das Makefile verweist dafür auf die neue Seite.
- README: Abschnitt „Versionierung“ gekürzt, Verweis auf die neuen Seiten.

## [1.1.1] - 2026-10-21

### Hinzugefügt
- Editor: Die Version steht in der Kopfzeile (neben „Recorder“), gelesen aus der Datei `VERSION`. Die Images enthalten die
  Datei dafür jetzt. Die Version erscheint erst nach dem Verbinden mit dem Token (`GET /api/config` liefert `version`).

## [1.1.0] - 2026-10-21

### Hinzugefügt
- `make start` und `make stop` starten und beenden den Recorder (Editor mit Live-Browser) oder den Editor ohne Browser:
  `make start recorder`, `make stop recorder`, `make start editor`. Ohne Angabe gilt der Recorder.
- Editor: Hinweis „Keine Prüfung im Profil“ mit Knopf zum Hinzufügen einer Prüfung (während der Aufnahme direkt ins
  Bild klicken). Strg+S speichert das Profil.
- Editor: Schrittkarten zeigen eine Einschätzung des Selektors (stabil, mittel, fragil; nach Muster, keine Garantie)
  und `${SWITCHER_…}`-Variablen als Chip. Bei der Wiedergabe bis zur Stopmarke erscheinen die Schritte als
  „abgespielt“, „läuft“ oder „angehalten“, neu aufgezeichnete Schritte als „neu“.
- Editor: Profilübersicht als Startansicht mit einer Karte je Profil (Name, Beschreibung, Schritte, „Prüft Ergebnis“ oder
  „Keine Prüfung“, „Bereit“ oder „TODO offen“, Änderungsdatum) und den Knöpfen „Bearbeiten“ und „Aufnehmen“.
  `GET /api/profiles` liefert dafür zusätzlich `check`, `todo` und `modified`. Zurück zur Übersicht geht es mit dem Pfeil
  links neben dem Profilnamen.
- Editor/Recorder: „Stabileren Selektor vorschlagen“ bei Schritten mit fragilem Selektor. Der Live-Browser sucht
  Selektoren über Text, Rolle, Name oder `data-testid`, die genau dasselbe Element treffen (höchstens drei), und
  übernimmt den gewählten mit einem Klick. Dafür muss die Aufnahme laufen und die passende Seite offen sein; es wird
  nichts im Browser verändert und nichts aufgezeichnet (neue Nachricht `suggest` am WebSocket).
- Recorder: Aufnahmeanzeige mit Zeit, Adressleiste mit Hinweis auf erlaubte Hosts und Banner, wenn eine Prüfung
  gewählt ist.

### Geändert
- Editor: Ungespeicherte Änderungen werden angezeigt (Punkt im Speichern-Knopf). Beim Wechsel zu einem
  anderen Profil, zu „Neues Profil“ oder zur Übersicht fragt der Editor nach, ebenso beim Schließen oder Neuladen des
  Tabs. Nach dem Speichern oder bei unveränderten Werten kommt keine Rückfrage.
- Editor: Bei zwei Spalten (ab 901 px Breite, z. B. iPad quer) stehen Profilkopf, Profilfelder und Live-Browser links in
  der Breite des Live-Fensters, die Schritte rechts über die ganze Höhe vom oberen Rand an. Die Schrittliste bleibt im Bild
  und scrollt für sich. Beim Abspielen bis zur Stopmarke und beim Aufzeichnen scrollt sie zum aktuellen Schritt.
- Editor: Neue Schritte lassen sich oben („Schritt am Anfang“) und unten („Schritt am Ende“) einfügen. Vorher gab es nur
  einen Knopf, der ans Ende anhängte.
- Editor: Knopf oben rechts schaltet die Darstellung zwischen automatisch (Systemeinstellung), hell und dunkel um. Die
  Wahl bleibt im Browser gespeichert.
- Editor: Der Aufnahme-Knopf sagt, was er tut. Bei einem Profil mit Schritten heißt er „Schritte anhängen“, mit gesetzter
  Stopmarke „Ab Stopmarke aufnehmen“, nur bei einem leeren Profil „Aufnahme starten“. Eine Zeile darunter erklärt,
  was passiert. Die Karte in der Profilübersicht beschriftet ihren Knopf genauso.
- Neue Oberfläche für Editor und Recorder: Live-Browser links, Schritte rechts (auf dem Handy als Tabs), Meldungen als
  Toasts, Dunkelmodus nach Systemeinstellung. Die Seite lädt weiterhin nichts von außen (Systemschrift, eigene Symbole).

### Behoben
- Nach einem Update konnte der Browser neues HTML mit altem CSS und JavaScript aus dem Zwischenspeicher mischen und die
  Oberfläche dadurch falsch darstellen. Der Editor liefert die Seite jetzt mit `Cache-Control: no-cache` aus, der
  Browser fragt bei jedem Aufruf nach (bei unveränderten Dateien nur eine kurze 304-Antwort).
- `README.md` und `README.de.md` beschreiben das Tool allgemein als Werkzeug für beliebige Weboberflächen; die Fritzbox
  steht als Anwendungsfall und als getestetes Gerät darin. Neu: Hinweis auf nicht automatisierbare Seiten (CAPTCHA,
  Einmalcode).
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
