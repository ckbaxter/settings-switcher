# Konfiguration

Hier steht, wie Settings Switcher eingerichtet wird und welche Einstellungen es gibt. Die Kurzfassung steht in der
[README](../README.de.md).

## Einrichtung

```bash
cp runner.env.example runner.env && chmod 600 runner.env   # Hosts + Zugangsdaten eintragen
cp .env.example .env && chmod 600 .env                     # Editor-Token (openssl rand -hex 24)
./run.sh beispiel                                          # baut beim ersten Aufruf das Runner-Image (Lauf endet mit Exit 2, solange TODO im Profil steht)
docker compose --profile record up -d --build              # Editor mit Live-Browser starten, http://127.0.0.1:8080
docker compose --profile record down                       # und wieder beenden
docker compose --profile editor up -d --build              # Alternative: Editor ohne Browser (nur Profile bearbeiten)
```

In `.env` müssen für den Live-Recorder `EDITOR_TOKEN` und `SWITCHER_ALLOWED_HOSTS` (Fritzbox-IP) stehen.
`record` und `editor` benutzen denselben Port, starte nur einen von beiden.
Starte `run.sh` als normaler Benutzer (UID wie `SWITCHER_UID`), nicht mit `sudo` (siehe [Fehlersuche](fehlersuche.md)).

`run.sh` baut das Runner-Image selbst, wenn es fehlt oder sich `runner/Dockerfile`,
`runner/requirements.txt`, `runner/runner.py` oder `shared/` seit dem letzten Bau geändert haben
(Prüfsumme als Image-Label `ss.source-hash`). Nach einem `git pull` genügt also der nächste Aufruf; der
Bau braucht dann Netz für Basis-Image und pip und dauert beim ersten Mal länger. Schlägt er fehl, endet
`run.sh` mit Exit 2 und führt nichts aus. `./run.sh --build <profil>` erzwingt einen Neubau, etwa um
Sicherheitsupdates der Basis-Image-Schicht zu holen, wenn sich der Tag nicht geändert hat.
Editor und Recorder sind eigene Images und werden mit `docker compose … up -d --build` neu gebaut.

### Zwei Host-Listen, nicht verwechseln

| | `EDITOR_ALLOWED_HOSTS` | `SWITCHER_ALLOWED_HOSTS` |
| --- | --- | --- |
| Datei | `.env` | `runner.env` und `.env` (gleicher Wert) |
| Wer prüft | der Editor | der Browser im Runner und im Recorder |
| Frage | Unter welchem Namen darf man den **Editor** aufrufen? | Welche Webseiten darf der **Browser** besuchen? |
| Inhalt | Adresse des Docker-Hosts, wie in der Browser-Adresszeile (z. B. `localhost,192.168.1.50`) | Adresse der Fritzbox (z. B. `192.168.178.1`) |
| Schützt vor | fremden Webseiten, die den Editor über einen umgebogenen Domainnamen ansprechen (DNS-Rebinding) | Zugangsdaten oder Klicks, die an einen fremden Host gehen |

- Beide Listen enthalten nur Hostnamen oder IPs, kommagetrennt, ohne `http://`, Port oder Pfad. Es sind reine
  Textvergleiche: Eine IP deckt den Hostnamen dazu nicht ab und umgekehrt.
- `EDITOR_ALLOWED_HOSTS` ist **nicht** die Adresse deines Endgeräts, sondern die des Servers, die du in den
  Browser eintippst. Wer den Editor erreichen darf, steuern `EDITOR_BIND`, `EDITOR_ALLOWED_IPS`, die Firewall
  und das Token.
- `SWITCHER_ALLOWED_HOSTS` kommt nur aus der Umgebung, nie aus dem Profil. Nimm die IP statt `fritz.box`, und
  `base_url` im Profil muss dazu passen.

### Zugriff auf bestimmte IPs begrenzen (`EDITOR_ALLOWED_IPS`)

Optional in `.env`: kommagetrennte IPs oder CIDR-Netze (z. B. `172.18.0.5` oder `192.168.1.0/24`), von denen
aus Editor und Recorder erreichbar sind. Alle anderen bekommen `403` (WebSocket: Abbruch). Leer = keine
Einschränkung. Ein ungültiger Eintrag lässt den Dienst nicht starten.

- Geprüft wird die direkte Gegenstelle der TCP-Verbindung, nicht `X-Forwarded-For` (uvicorn läuft mit
  `--no-proxy-headers`). Hinter einem Reverse Proxy (z. B. Nginx Proxy Manager) trägst du also die Adresse des
  **Proxys** ein, nicht die der Endgeräte.
- Welche Adresse beim Editor ankommt, hängt vom Docker-Netz ab. Am eindeutigsten: Editor und Proxy in dasselbe
  Docker-Netz legen und im Proxy auf `settings-switcher-editor:8080` zeigen. Dann ist die Quelle die feste
  Container-IP des Proxys (`docker inspect`). Spricht der Proxy den veröffentlichten Port über die Host-IP an,
  sieht der Editor je nach Docker-Setup meist die Gateway-Adresse der Bridge (oft `172.x.0.1`), nicht die des
  Proxys. Im Zweifel `docker compose logs`: abgelehnte Zugriffe stehen dort mit der gesehenen Adresse.
- Das ersetzt weder das Token noch `EDITOR_BIND` oder eine Firewall, es ergänzt sie.
- Nicht getestet: Das Verhalten mit echtem Docker-Netz und Nginx Proxy Manager. Die Prüfung selbst ist durch
  Tests abgedeckt (`tests/test_editor.py`, `tests/test_recorder_ws.py`).

## Veröffentlichte Images statt lokalem Bau (optional)

Standardmäßig baut `docker compose … up -d --build` Editor und Recorder lokal. Alternativ lassen sich die vom
GitHub-Workflow veröffentlichten Images nutzen. Dafür stehen in der `.env` (Vorlage `.env.example`):

| Variable | Bedeutung |
| --- | --- |
| `SWITCHER_EDITOR_IMAGE` | Image des Editors ohne Browser, z. B. `ghcr.io/<owner>/settings-switcher-editor:latest` |
| `SWITCHER_RECORDER_IMAGE` | Image des Recorders (Editor mit Live-Browser), z. B. `ghcr.io/<owner>/settings-switcher-recorder:latest` |

Ohne diese Variablen gelten die lokal gebauten Images `settings-switcher-editor` und `settings-switcher-recorder`.
Ablauf und Anmeldung bei der Registry: [Betrieb](betrieb.md#image-workflow-und-registry). Das Runner-Image
(`SWITCHER_IMAGE`, nur für `run.sh`) baut `run.sh` weiterhin selbst.
