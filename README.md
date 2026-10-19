# Settings Switcher

Schaltet Einstellungen auf Weboberflächen per Browser-Automatisierung, gedacht für eine
Fritzbox-Portfreigabe (an/aus), wenn TR-064 nicht in Frage kommt.

- **Profile** beschreiben einen Ablauf als Liste einfacher Schritte (JSON in `profiles/`).
- **`run.sh <profil>`** startet einen frischen Container, führt das Profil aus und entfernt den
  Container wieder. Exit-Code 0 = alles erfolgreich, 1 = Schritt oder Prüfung fehlgeschlagen,
  2 = Aufruf-/Konfigurationsfehler.
- **Editor** (kleine Webseite) zum Anlegen und Ändern der Profile. Er läuft nur, wenn du ihn startest.

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
docker compose --profile editor up -d --build              # Editor starten, http://127.0.0.1:8080
docker compose --profile editor down                       # Editor beenden
```

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

## Selektoren aufzeichnen (einmalig am eigenen Rechner)

Der Editor zeichnet nicht live auf. Die Selektoren holst du dir mit Playwrights Recorder:

```bash
pipx run playwright install chromium        # einmalig
pipx run playwright codegen http://192.168.178.1
```

Klicke den Ablauf durch (Login, Freigabe öffnen, Haken setzen, Übernehmen). Der Recorder zeigt
zu jedem Klick den Selektor. Übersetzung in das Profil:

| Recorder | Profil |
| --- | --- |
| `locator("#abc")` | `"selector": "#abc"` |
| `get_by_role("button", name="Anmelden")` | `"selector": "role=button[name=\"Anmelden\"]"` |
| `get_by_text("Übernehmen", exact=True).click()` | Operation `click_text` mit `value` |
| `get_by_text("Freigabe")` | `"selector": "text=Freigabe"` |

Für andere Varianten (z. B. `get_by_label`) nimm den CSS-Selektor aus dem Inspector. Nimm
stabile Selektoren (IDs, Rollen, Text) statt langer XPath-Ketten. Nach FRITZ!OS-Updates können
einzelne Selektoren brechen, dann den betroffenen Schritt neu aufzeichnen.

## Status und Grenzen

Getestet (`python3 -m pytest`): Schema-Validierung, Host-Prüfung, Variablen, Editor-API,
Editor-Oberfläche im echten Browser (inkl. XSS- und CSP-Prüfung) sowie Läufe des Runners in
Chromium gegen eine lokale Testseite.

**Noch nicht getestet:**

- Der Docker-Build der Images und `run.sh` mit echtem `docker run` (im Entwicklungsumfeld war
  keine Registry erreichbar). Das Image `mcr.microsoft.com/playwright/python:v1.56.0-noble` und die
  Härtungs-Flags solltest du beim ersten Lauf prüfen. Falls Chromium im Container wegen
  `--read-only` oder `--cap-drop` nicht startet, steht der Fehler direkt in der Ausgabe.
- Ein Lauf gegen eine echte Fritzbox. Die Profile enthalten bewusst keine geratenen Selektoren.
- Ob bei deiner FRITZ!OS-Version für Portfreigaben eine zusätzliche Bestätigung verlangt wird
  (laut deiner Angabe nicht).

Bewusst nicht enthalten: Aufzeichnen im Editor, Webhook-Endpunkt, Zeitplan. Aufruf aus Home
Assistant oder Cron geht über `run.sh <profil>` auf dem Docker-Host (z. B. per SSH oder
`shell_command`). Eine automatische Rückschaltung nach X Minuten lässt sich so mit einem
zweiten Profil (`…-aus`) und einem Zeitplan lösen.
