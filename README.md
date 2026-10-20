# Settings Switcher

Schaltet Einstellungen auf Weboberflächen per Browser-Automatisierung, gedacht für eine
Fritzbox-Portfreigabe (an/aus), wenn TR-064 nicht in Frage kommt.

- **Profile** beschreiben einen Ablauf als Liste einfacher Schritte (JSON in `profiles/`).
- **`run.sh <profil>`** startet einen frischen Container, führt das Profil aus und entfernt den
  Container wieder. Exit-Code 0 = alles erfolgreich, 1 = Schritt oder Prüfung fehlgeschlagen,
  2 = Aufruf-/Konfigurationsfehler.
- **Editor** (kleine Webseite) zum Anlegen und Ändern der Profile, mit **eingebettetem Live-Browser**:
  du klickst den Ablauf visuell durch, der Editor zeichnet die Schritte auf. Er läuft nur, wenn du ihn startest.

```
./run.sh portfreigabe-an          # Profil ausführen
./run.sh -s portfreigabe-an       # Screenshot nach jedem Schritt (artifacts/)
./run.sh --list                   # Profile anzeigen
```

## Einrichtung

```bash
cp runner.env.example runner.env && chmod 600 runner.env   # Hosts + Zugangsdaten eintragen
cp .env.example .env && chmod 600 .env                     # Editor-Token (openssl rand -hex 24)
./run.sh beispiel                                          # baut beim ersten Aufruf das Runner-Image (Lauf endet mit Exit 2, solange TODO im Profil steht)
docker compose --profile record up -d --build              # Editor mit Live-Browser starten, http://127.0.0.1:8080
docker compose --profile record down                       # und wieder beenden
docker compose --profile editor up -d --build              # Alternative: Editor ohne Browser (nur Profile bearbeiten)
```

In `.env` müssen für den Live-Recorder `EDITOR_TOKEN` und `SS_ALLOWED_HOSTS` (Fritzbox-IP) stehen.
`record` und `editor` benutzen denselben Port, starte nur einen von beiden.
Starte `run.sh` als normaler Benutzer (UID wie `SS_UID`), nicht mit `sudo` (siehe Fehlersuche).

`run.sh` baut das Runner-Image selbst, wenn es fehlt oder sich `runner/Dockerfile`,
`runner/requirements.txt`, `runner/runner.py` oder `shared/` seit dem letzten Bau geändert haben
(Prüfsumme als Image-Label `ss.source-hash`). Nach einem `git pull` genügt also der nächste Aufruf; der
Bau braucht dann Netz für Basis-Image und pip und dauert beim ersten Mal länger. Schlägt er fehl, endet
`run.sh` mit Exit 2 und führt nichts aus. `./run.sh --build <profil>` erzwingt einen Neubau, etwa um
Sicherheitsupdates der Basis-Image-Schicht zu holen, wenn sich der Tag nicht geändert hat.
Editor und Recorder sind eigene Images und werden mit `docker compose … up -d --build` neu gebaut.

### Zwei Host-Listen, nicht verwechseln

| | `EDITOR_ALLOWED_HOSTS` | `SS_ALLOWED_HOSTS` |
| --- | --- | --- |
| Datei | `.env` | `runner.env` und `.env` (gleicher Wert) |
| Wer prüft | der Editor | der Browser im Runner und im Recorder |
| Frage | Unter welchem Namen darf man den **Editor** aufrufen? | Welche Webseiten darf der **Browser** besuchen? |
| Inhalt | Adresse des Docker-Hosts, wie in der Browser-Adresszeile (z. B. `localhost,192.168.1.50`) | Adresse der Fritzbox (z. B. `192.168.178.1`) |
| Schützt vor | fremden Webseiten, die den Editor über einen umgebogenen Domainnamen ansprechen (DNS-Rebinding) | Zugangsdaten oder Klicks, die an einen fremden Host gehen |

- Beide Listen enthalten nur Hostnamen oder IPs, kommagetrennt, ohne `http://`, Port oder Pfad. Es sind reine
  Textvergleiche: Eine IP deckt den Hostnamen dazu nicht ab und umgekehrt.
- `EDITOR_ALLOWED_HOSTS` ist **nicht** die Adresse deines Endgeräts, sondern die des Servers, die du in den
  Browser eintippst. Wer den Editor erreichen darf, steuern `EDITOR_BIND`, die Firewall und das Token.
- `SS_ALLOWED_HOSTS` kommt nur aus der Umgebung, nie aus dem Profil. Nimm die IP statt `fritz.box`, und
  `base_url` im Profil muss dazu passen.

## Sicherheitsmodell

Der Runner hat Zugriff auf die Fritzbox, deshalb gilt:

| Maßnahme | Wirkung |
| --- | --- |
| Erlaubte Hosts nur aus `SS_ALLOWED_HOSTS` (`runner.env`), nie aus dem Profil | Wer Profile ändern kann, kann das Passwort nicht an einen fremden Host schicken |
| Browser blockiert jede Anfrage an andere Hosts (auch Redirects, Bilder, Skripte) | Nur die Fritzbox ist erreichbar |
| Zugangsdaten nur als `${SS_USER}` / `${SS_PASSWORD}` und nur bei `fill` | Passwörter stehen in keinem Profil und im Log nur als „n Zeichen“ |
| Keine Operation für freies JavaScript | Profile können nur die festen Schritte ausführen |
| Container: `--rm`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, Speicher-/Prozesslimit, kein Port nach außen, läuft als dein Benutzer | Kleine Angriffsfläche, nichts bleibt zurück |
| Harte Laufzeitgrenze (`SS_MAX_RUNTIME_S`, Standard 120 s) und nur ein Lauf gleichzeitig | Hängende Läufe bleiben nicht offen |
| Editor: Token-Pflicht, Host-Prüfung, Rate-Limit, strenge CSP, nur lokal gebunden, **keine** Fritzbox-Zugangsdaten, startet keine Container | Selbst ein geknackter Editor kann nur Profile ändern |
| Live-Recorder: gleiche Host-Sperre wie der Runner (`SS_ALLOWED_HOSTS`), WebSocket nur mit Token, Host- und Origin-Prüfung, nur eine Sitzung und ein Betrachter, Zeitgrenzen (180 s Leerlauf, 600 s gesamt), Popups/Dialoge/Downloads aus, Container wie der Runner gehärtet | Der aufgezeichnete Browser kann nur die Fritzbox erreichen und nur mit gültigem Token gesteuert werden |
| Aufgezeichnete Passwörter: Passwortfelder werden immer als `${SS_PASSWORD}` gespeichert, fester Text ist dort abgelehnt; andere Felder speichern nur, was du ausdrücklich als festen Text wählst | Zugangsdaten stehen weder im Profil noch im Editor-Log |
| Wiedergabe bis zur Stopmarke: Die Schritte werden wie ein Profil geprüft (nur feste Operationen, nur erlaubte Hosts), `${SS_…}`-Werte und `TODO`-Schritte spielt der Recorder nie selbst ab | Auch beim Abspielen kommen keine Zugangsdaten in den Recorder, Logins tippst du selbst ein |

Außerdem sinnvoll:

- Eigenen Fritzbox-Benutzer mit minimalen Rechten anlegen, ohne Zugriff aus dem Internet.
- Auf dem Docker-Host zusätzlich per Firewall (`DOCKER-USER`-Kette oder eigenes Docker-Netz über
  `SS_DOCKER_NETWORK`) den Ausgang des Runners auf die Fritzbox-IP beschränken. Die
  Hostprüfung im Browser ersetzt das nicht, sie ergänzt es.
- Screenshots (`artifacts/`) können sensible Seiteninhalte zeigen. Sie bleiben lokal, nicht einchecken.
- Chromium läuft im Container mit `--no-sandbox`, weil der Container selbst die Isolation liefert
  und der Runner nur erlaubte Hosts lädt. Wer die Chromium-Sandbox nutzen will, setzt
  `SS_CHROMIUM_NO_SANDBOX=0` und startet den Container mit einem passenden Seccomp-Profil
  (siehe Playwright-Docker-Dokumentation).
- Profile enthalten keine Geheimnisse und dürfen ins (private) Repo.
- **Restrisiko des Live-Recorders:** Der Recorder-Container erreicht die Fritzbox und wird per
  Token gesteuert. Wer das Token hat, kann darin klicken, aber ohne Zugangsdaten nicht anmelden
  (außer, du tippst sie selbst im Live-Browser ein, dann sieht der Browser sie nur während der
  Sitzung). Deshalb: nur bei Bedarf starten, danach `down`, Token geheim halten, nur lokal binden
  oder hinter einem Reverse Proxy mit TLS betreiben. Beim Aufzeichnen des Logins dieselben
  minimalen Rechte verwenden wie im Betrieb.

## Profil-Format

```json
{
  "name": "portfreigabe-an",
  "description": "Optional",
  "base_url": "http://192.168.178.1",
  "timeout_ms": 15000,
  "steps": [
    { "op": "goto", "value": "/" },
    { "op": "fill", "selector": "…", "value": "${SS_PASSWORD}" },
    { "op": "click", "selector": "…" },
    { "op": "expect_checked", "selector": "…", "comment": "Erfolgsprüfung" }
  ]
}
```

| Operation | Felder | Bedeutung |
| --- | --- | --- |
| `goto` | `value` | Pfad (`/…`) oder volle URL, nur erlaubte Hosts |
| `click` / `click_text` | `selector` / `value` | Element bzw. Element mit exakt diesem Text anklicken |
| `fill` | `selector`, `value` | Text eintragen, `${SS_…}` erlaubt |
| `check` / `uncheck` | `selector` | Checkbox setzen |
| `select_option` / `press` | `selector`, `value` | Auswahlliste / Taste |
| `wait_for` / `wait_ms` | `selector` / `value` | Warten auf Element / feste Zeit (ms, max. 30000) |
| `expect_visible` / `expect_text` / `expect_checked` / `expect_unchecked` | `selector` (, `value`) | Erfolgsprüfung. Schlägt sie fehl, endet der Lauf mit Exit 1 |

Ein Lauf gilt als erfolgreich, wenn alle Schritte durchlaufen. Ohne `expect_*`-Prüfung heißt das nur,
dass nichts abgebrochen ist, nicht dass die Änderung wirksam wurde. Ein Schritt, der fehlschlägt, beendet
den Lauf sofort (Exit 1, Screenshot `…-fehler.png`). Spätere Schritte wie der Logout entfallen dann; die
Sitzung auf der Fritzbox läuft von selbst ab.

- Setze die Prüfung **nach dem Übernehmen** und vor den Logout. Sie darf mitten im Ablauf stehen.
- Ein `expect_*` direkt nach dem Klick prüft nur den Formularzustand im Browser. Verlässlich ist die
  Gegenprobe nach einem Neuladen (Regel oder Seite erneut öffnen, dann prüfen).
- Gib der Seite nach „Übernehmen“ etwas Zeit (`wait_ms` oder `wait_for`), bevor der Logout den Browser schließt.
- `check`/`uncheck` setzen einen festen Zustand und tun nichts, wenn er schon so ist. Die Aufzeichnung
  schreibt, was beim Aufzeichnen passiert ist; ein Profil „an“ braucht `check`, ein Profil „aus“ `uncheck`.
  Beide unterscheiden sich oft nur in diesem einen Schritt.
- Ein Logout ist nicht Pflicht (der Container verschwindet, die Sitzung auf der Box läuft aber noch bis zum
  Timeout), aber sauberer, besonders bei häufigen Läufen.

Schritte mit `TODO` in `selector` oder `value` führt der Runner nicht aus.

## Ablauf aufzeichnen (Live-Browser im Editor)

1. `docker compose --profile record up -d --build`, dann `http://127.0.0.1:8080` öffnen und mit dem Token verbinden.
2. Profil anlegen oder öffnen, `base_url` eintragen (muss zu `SS_ALLOWED_HOSTS` passen) und **Aufnahme starten**.
3. Im Live-Bild klicken wie in einem normalen Browser. Jede Aktion erscheint als Schritt:

| Aktion im Live-Bild | Aufgezeichneter Schritt |
| --- | --- |
| Seite öffnen | `goto` |
| Klick auf Schaltfläche, Link, Element | `click` mit möglichst stabilem Selektor |
| Klick auf Textfeld, dann Text im Feld darunter eingeben und senden | `fill`. Passwortfelder immer mit `${SS_PASSWORD}`. Andere Felder wahlweise `${SS_USER}`, `TODO` (selbst ausfüllen) oder fester Text |
| Klick auf Checkbox | `check` / `uncheck` je nach Ergebnis |
| Klick auf Auswahlliste | Liste erscheint im Editor, die Wahl wird `select_option` |
| Enter, Tab, Escape (Tastenknöpfe) | `press` |
| Scrollen: Mausrad, Wischen im Bild (iPad/Touch) oder die Knöpfe ◀ ▲ ▼ ▶ | kein Schritt, die Seite im Live-Browser scrollt nur |
| „Prüfen“-Knöpfe, dann auf ein Element klicken | `expect_visible` / `expect_text` / `expect_checked` / `expect_unchecked` / `wait_for` |

4. **Aufnahme beenden**, Schritte prüfen (Reihenfolge, Selektoren, `TODO`-Werte), **Speichern**.
5. Mit `./run.sh -s <profil>` testen und in der Fritzbox prüfen, ob die Änderung wirklich da ist. Bau nach
   dem Übernehmen eine `expect_*`-Prüfung ein (siehe oben), sonst meldet der Lauf Erfolg, ohne etwas zu prüfen.

### Ab einer Stelle weiter aufzeichnen (Stopmarke)

Hat sich nur ein Teil des Ablaufs geändert (etwa nach einem FRITZ!OS-Update), musst du nicht alles neu aufnehmen:

1. Profil öffnen und beim letzten unveränderten Schritt auf **⚑** klicken. Das ist die Stopmarke; ein
   zweiter Klick entfernt sie. Die Marke gibt es nur im Browserfenster, sie steht nicht im Profil.
2. **Aufnahme starten.** Der Recorder spielt die Schritte bis zur Marke im Live-Browser ab. Das wird nicht
   erneut aufgezeichnet.
3. Danach zeichnest du wie gewohnt weiter auf. Neue Schritte kommen **hinter die Marke**, die bisherigen
   Folgeschritte bleiben stehen. Veraltete Schritte entfernst du mit ✕.
4. Aufnahme beenden, Schritte prüfen, speichern.

Beim Abspielen hält der Recorder an, wenn er einen Schritt nicht selbst ausführen darf oder nicht kann:

- **Login und TODO:** Ein `fill` mit `${SS_USER}` / `${SS_PASSWORD}` spielt der Recorder nie selbst ab, er kennt
  keine Zugangsdaten. Dasselbe gilt für Schritte mit `TODO`. Du erledigst den Schritt im Live-Bild (bei einem
  Textfeld ist es schon markiert, getippt wird im Eingabefeld unter dem Bild) und klickst **Erledigt, weiter**.
  Das wird nicht aufgezeichnet. Ein Login braucht also bei jeder Aufnahme mit Marke deine Eingabe.
- **Schritt schlägt fehl** (z. B. Selektor passt nicht mehr): **Wiederholen**, **Schritt überspringen**
  (wenn du ihn selbst erledigt hast) oder **Hier aufzeichnen**.
- **Hier aufzeichnen** beendet die Wiedergabe an der aktuellen Stelle, neue Schritte kommen dahinter. Das geht auch
  mitten im Lauf; der gerade laufende Schritt wird noch beendet.

Während die Wiedergabe läuft, sind Klicks im Live-Bild gesperrt (beim Anhalten sind sie erlaubt, aber nicht
aufgezeichnet). Prüfungen („Text“, „Sichtbar“ …) gehen erst danach. Die Zeitgrenzen der Aufnahme (180 s
Leerlauf, 600 s gesamt) gelten auch für die Wiedergabe.

Wichtig:

- Die Schrittliste lebt im Browserfenster und geht beim Neuladen verloren. Vor dem Beenden speichern.
- Selektoren sind eine Heuristik (ID, `data-testid`, Rolle mit Namen, `name`, Text, zuletzt CSS-Pfad)
  und werden vor dem Eintragen auf Eindeutigkeit geprüft. Kontrolliere sie trotzdem und teste mit `run.sh`.
- Nach FRITZ!OS-Updates können einzelne Selektoren brechen, dann den betroffenen Schritt neu aufzeichnen.
- Die Live-Ansicht ist ein Bild (Screenshots, kein Videostream). Das reicht zum Klicken, ist aber nicht flüssig.

**Alternative ohne Live-Browser:** Selektoren mit Playwrights Recorder am eigenen Rechner holen
(`pipx run playwright codegen http://192.168.178.1`) und von Hand in das Profil übertragen:
`locator("#abc")` → `"selector": "#abc"`, `get_by_role("button", name="Anmelden")` →
`"selector": "role=button[name=\"Anmelden\"]"`, `get_by_text("Übernehmen", exact=True)` → Operation `click_text`.

## Fehlersuche

| Symptom | Ursache und Abhilfe |
| --- | --- |
| Editor: „Host nicht erlaubt.“ | Der Name aus der Browser-Adresszeile (ohne Port) fehlt in `EDITOR_ALLOWED_HOSTS`. Eintrag in `.env` ergänzen, Zeile nicht auskommentiert lassen, mit `docker compose … up -d` neu anlegen (ein Neustart liest `.env` nicht neu). |
| Speichern: „Keine Schreibrechte …“ / Fehler 500 | Der Container-Benutzer darf nicht in `./profiles` schreiben. `SS_UID`/`SS_GID` in `.env` auf `id -u` / `id -g` des Besitzers setzen (oder `chown`), Dienst neu anlegen. |
| `run.sh`: „Profil … nicht lesbar: Permission denied“ | `./profiles` braucht `755`, die Profile `644` (neuere Editor-Versionen speichern so). Der Runner läuft mit `--cap-drop ALL`, daher kann auch root fremde Dateien nur mit passenden Rechten lesen. `run.sh` besser nicht mit `sudo` starten. Nach einem Update `docker compose --profile record up -d --build`. |
| Lauf „ok“, aber nichts geändert | Meist falsche Richtung (`uncheck` statt `check` oder der Zustand war schon so), zu früher Logout oder fehlende Gegenprobe. `./run.sh -s` zeigt Screenshots pro Schritt. |
| Schritt bricht ab | Selektor nicht (mehr) eindeutig, z. B. nach FRITZ!OS-Update, oder Element erscheint erst nach dem Laden (`wait_for` davor). Den Schritt neu aufzeichnen. |

## Abhängigkeiten aktuell halten

Dependabot (`.github/dependabot.yml`) prüft montags die pip-Pins und die Docker-Images und öffnet
höchstens einen gemeinsamen Pull Request pro Woche. Gemeinsam deshalb, weil Playwright-Pin
(`runner/requirements.txt`, `requirements-dev.txt`) und Playwright-Image (`FROM` in `runner/Dockerfile`
und `recorder/Dockerfile`) dieselbe Version haben müssen; `tests/test_versions.py` prüft das.
Vor dem Merge: `python3 -m pytest`. Nach dem Merge und `git pull` baut `run.sh` den Runner beim
nächsten Aufruf selbst neu (siehe Einrichtung); Editor und Recorder brauchen
`docker compose --profile record up -d --build`. Neue Releases wartet Dependabot fünf Tage ab
(Cooldown), weil das Playwright-Image nicht immer am selben Tag wie das PyPI-Paket erscheint.

## Status und Grenzen

Automatisch getestet (`python3 -m pytest`): Schema-Validierung, Host-Prüfung, Variablen, Editor-API,
Versionskopplung von Playwright-Pin und -Image, die Neubau-Entscheidung von `run.sh` (mit Docker-Attrappe),
Editor-Oberfläche im echten Browser (inkl. XSS- und CSP-Prüfung), Läufe des Runners in Chromium
gegen eine lokale Testseite, der Live-Recorder (Selektoren, Passwortbehandlung, Scrollen,
WebSocket-Absicherung) und der ganze Weg „im Editor aufzeichnen → speichern → mit dem Runner abspielen“
gegen eine lokale Testseite. Ebenso die Stopmarke (Abspielen bis zur Marke, Anhalten bei Login-, TODO- und
fehlgeschlagenen Schritten, Einfügen hinter der Marke, Bedienung in der Oberfläche), ebenfalls nur gegen die
lokale Testseite.

Manuell getestet (vom Betreiber bestätigt): Docker-Build der Images, `run.sh` mit echtem `docker run`
und Aufzeichnen sowie Abspielen gegen eine echte Fritzbox 7590 mit FRITZ!OS 8.25 (Portfreigabe an/aus).
Der Docker-Teil läuft nicht in den automatischen Tests.

Noch nicht manuell getestet: die Stopmarke gegen eine echte Fritzbox (insbesondere das Abspielen des Logins mit
Anhalten und Selbst-Eintippen im Live-Browser).

Grenzen:

- Selektoren sind eine Heuristik und können nach FRITZ!OS-Updates brechen (siehe Fehlersuche).
- Die Profile sind nur so zuverlässig wie ihre Prüfungen; ein Lauf ohne `expect_*` beweist keine Wirkung.

Bewusst nicht enthalten: Webhook-Endpunkt, Zeitplan, Bearbeiten laufender Aufnahmen. Aufruf aus Home
Assistant oder Cron geht über `run.sh <profil>` auf dem Docker-Host (z. B. per SSH oder
`shell_command`). Eine automatische Rückschaltung nach X Minuten lässt sich so mit einem
zweiten Profil (`…-aus`) und einem Zeitplan lösen.
