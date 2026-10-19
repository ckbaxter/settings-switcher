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
./run.sh --build beispiel                                  # baut das Runner-Image (Lauf endet mit Exit 2, solange TODO im Profil steht)
docker compose --profile record up -d --build              # Editor mit Live-Browser starten, http://127.0.0.1:8080
docker compose --profile record down                       # und wieder beenden
docker compose --profile editor up -d --build              # Alternative: Editor ohne Browser (nur Profile bearbeiten)
```

In `.env` müssen für den Live-Recorder `EDITOR_TOKEN` und `SS_ALLOWED_HOSTS` (Fritzbox-IP) stehen.
`record` und `editor` benutzen denselben Port, starte nur einen von beiden.

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

Ein Lauf gilt nur als erfolgreich, wenn alle Schritte durchlaufen. Beende jedes Profil deshalb
mit einer `expect_*`-Prüfung, die den gewünschten Zustand bestätigt.
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
5. Mit `./run.sh -s <profil>` testen. Beende jeden Ablauf mit einer `expect_*`-Prüfung, die den
   gewünschten Zustand bestätigt, sonst meldet der Lauf Erfolg, ohne etwas zu prüfen.

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

## Status und Grenzen

Getestet (`python3 -m pytest`): Schema-Validierung, Host-Prüfung, Variablen, Editor-API,
Editor-Oberfläche im echten Browser (inkl. XSS- und CSP-Prüfung), Läufe des Runners in Chromium
gegen eine lokale Testseite, der Live-Recorder (Selektoren, Passwortbehandlung, WebSocket-Absicherung)
und der ganze Weg „im Editor aufzeichnen → speichern → mit dem Runner abspielen“ gegen eine lokale Testseite.

**Noch nicht getestet:**

- Der Docker-Build der Images und `run.sh` mit echtem `docker run` (im Entwicklungsumfeld war
  keine Registry erreichbar). Das Image `mcr.microsoft.com/playwright/python:v1.56.0-noble` und die
  Härtungs-Flags solltest du beim ersten Lauf prüfen. Falls Chromium im Container wegen
  `--read-only` oder `--cap-drop` nicht startet, steht der Fehler direkt in der Ausgabe.
- Aufzeichnen und Abspielen gegen eine echte Fritzbox. Die Profile enthalten bewusst keine geratenen
  Selektoren. Ob die Heuristik auf der FRITZ!OS-8.25-Oberfläche (die viel dynamisch nachlädt)
  überall eindeutige Selektoren findet, zeigt erst die erste Aufnahme.
- Ob bei deiner FRITZ!OS-Version für Portfreigaben eine zusätzliche Bestätigung verlangt wird
  (laut deiner Angabe nicht).

Bewusst nicht enthalten: Webhook-Endpunkt, Zeitplan, Bearbeiten laufender Aufnahmen. Aufruf aus Home
Assistant oder Cron geht über `run.sh <profil>` auf dem Docker-Host (z. B. per SSH oder
`shell_command`). Eine automatische Rückschaltung nach X Minuten lässt sich so mit einem
zweiten Profil (`…-aus`) und einem Zeitplan lösen.
