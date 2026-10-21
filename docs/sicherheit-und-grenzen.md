# Sicherheit und Grenzen

## Sicherheitsmodell

Der Runner hat Zugriff auf die Fritzbox, deshalb gilt:

| Maßnahme | Wirkung |
| --- | --- |
| Erlaubte Hosts nur aus `SWITCHER_ALLOWED_HOSTS` (`runner.env`), nie aus dem Profil | Wer Profile ändern kann, kann das Passwort nicht an einen fremden Host schicken |
| Browser blockiert jede Anfrage an andere Hosts (auch Redirects, Bilder, Skripte) | Nur die Fritzbox ist erreichbar |
| Zugangsdaten nur als `${SWITCHER_USER}` / `${SWITCHER_PASSWORD}` und nur bei `fill` | Passwörter stehen in keinem Profil und im Log nur als „n Zeichen“ |
| Keine Operation für freies JavaScript | Profile können nur die festen Schritte ausführen |
| Container: `--rm`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, Speicher-/Prozesslimit, kein Port nach außen, läuft als dein Benutzer | Kleine Angriffsfläche, nichts bleibt zurück |
| Harte Laufzeitgrenze (`SWITCHER_MAX_RUNTIME_S`, Standard 120 s) und nur ein Lauf gleichzeitig | Hängende Läufe bleiben nicht offen |
| Editor: Token-Pflicht, Host-Prüfung, optionale IP-Freigabe (`EDITOR_ALLOWED_IPS`), Rate-Limit, strenge CSP, nur lokal gebunden, **keine** Fritzbox-Zugangsdaten, startet keine Container | Selbst ein geknackter Editor kann nur Profile ändern |
| Live-Recorder: gleiche Host-Sperre wie der Runner (`SWITCHER_ALLOWED_HOSTS`), WebSocket nur mit Token, Host- und Origin-Prüfung, nur eine Sitzung und ein Betrachter, Zeitgrenzen (180 s Leerlauf, 600 s gesamt), Popups/Dialoge/Downloads aus, Container wie der Runner gehärtet | Der aufgezeichnete Browser kann nur die Fritzbox erreichen und nur mit gültigem Token gesteuert werden |
| Aufgezeichnete Passwörter: Passwortfelder werden immer als `${SWITCHER_PASSWORD}` gespeichert, fester Text ist dort abgelehnt; andere Felder speichern nur, was du ausdrücklich als festen Text wählst | Zugangsdaten stehen weder im Profil noch im Editor-Log |
| Wiedergabe bis zur Stopmarke: Die Schritte werden wie ein Profil geprüft (nur feste Operationen, nur erlaubte Hosts), `${SWITCHER_…}`-Werte und `TODO`-Schritte spielt der Recorder nie selbst ab | Auch beim Abspielen kommen keine Zugangsdaten in den Recorder, Logins tippst du selbst ein |

Außerdem sinnvoll:

- Eigenen Fritzbox-Benutzer mit minimalen Rechten anlegen, ohne Zugriff aus dem Internet.
- Auf dem Docker-Host zusätzlich per Firewall (`DOCKER-USER`-Kette oder eigenes Docker-Netz über
  `SWITCHER_DOCKER_NETWORK`) den Ausgang des Runners auf die Fritzbox-IP beschränken. Die
  Hostprüfung im Browser ersetzt das nicht, sie ergänzt es.
- Screenshots (`artifacts/`) können sensible Seiteninhalte zeigen. Sie bleiben lokal, nicht einchecken.
- Chromium läuft im Container mit `--no-sandbox`, weil der Container selbst die Isolation liefert
  und der Runner nur erlaubte Hosts lädt. Wer die Chromium-Sandbox nutzen will, setzt
  `SWITCHER_CHROMIUM_NO_SANDBOX=0` und startet den Container mit einem passenden Seccomp-Profil
  (siehe Playwright-Docker-Dokumentation).
- Profile enthalten keine Zugangsdaten, wohl aber Adressen und Selektoren deiner Geräte. Sie gehören nicht in ein
  öffentliches Repo; die `.gitignore` schließt eigene Profile (`profiles/*.json`, außer `beispiel.json`) aus.
- **Restrisiko des Live-Recorders:** Der Recorder-Container erreicht die Fritzbox und wird per
  Token gesteuert. Wer das Token hat, kann darin klicken, aber ohne Zugangsdaten nicht anmelden
  (außer, du tippst sie selbst im Live-Browser ein, dann sieht der Browser sie nur während der
  Sitzung). Deshalb: nur bei Bedarf starten, danach `down`, Token geheim halten, nur lokal binden
  oder hinter einem Reverse Proxy mit TLS betreiben. Beim Aufzeichnen des Logins dieselben
  minimalen Rechte verwenden wie im Betrieb.

## Status und Grenzen

Automatisch getestet (`python3 -m pytest`): Schema-Validierung, Host-Prüfung, Variablen, Editor-API,
Versionskopplung von Playwright-Pin und -Image, die Neubau-Entscheidung von `run.sh` (mit Docker-Attrappe),
Editor-Oberfläche im echten Browser (inkl. XSS- und CSP-Prüfung), Läufe des Runners in Chromium
gegen eine lokale Testseite, der Live-Recorder (Selektoren, Passwortbehandlung, Scrollen,
WebSocket-Absicherung) und der ganze Weg „im Editor aufzeichnen → speichern → mit dem Runner abspielen“
gegen eine lokale Testseite. Ebenso die Stopmarke (Abspielen bis zur Marke, Anhalten bei Login-, TODO- und
fehlgeschlagenen Schritten, Einfügen hinter der Marke, Bedienung in der Oberfläche), ebenfalls nur gegen die
lokale Testseite.

Manuell getestet: Docker-Build der Images, `run.sh` mit echtem `docker run`
und Aufzeichnen sowie Abspielen gegen eine echte Fritzbox 7590 mit FRITZ!OS 8.25 (Portfreigabe an/aus).
Der Docker-Teil läuft nicht in den automatischen Tests.

Noch nicht manuell getestet: die Stopmarke gegen eine echte Fritzbox (insbesondere das Abspielen des Logins mit
Anhalten und Selbst-Eintippen im Live-Browser).

Grenzen:

- Selektoren sind eine Heuristik und können nach FRITZ!OS-Updates brechen (siehe [Fehlersuche](fehlersuche.md)).
- Die Profile sind nur so zuverlässig wie ihre Prüfungen; ein Lauf ohne `expect_*` beweist keine Wirkung.

Bewusst nicht enthalten: Webhook-Endpunkt, Zeitplan, Bearbeiten laufender Aufnahmen. Aufruf aus Home
Assistant oder Cron geht über `run.sh <profil>` auf dem Docker-Host (z. B. per SSH oder
`shell_command`). Eine automatische Rückschaltung nach X Minuten lässt sich so mit einem
zweiten Profil (`…-aus`) und einem Zeitplan lösen.
