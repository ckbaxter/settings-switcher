# Sicherheit und Grenzen

## Das solltest du tun

Der Runner kann sich an der Weboberfläche anmelden, behandle ihn deshalb wie einen Schlüssel.

1. **Eigenen Benutzer mit minimalen Rechten** auf dem Gerät anlegen (bei der Fritzbox: ohne Zugriff aus dem Internet) und
   nur dessen Zugangsdaten in `runner.env` eintragen (`chmod 600`).
2. **Editor und Recorder nicht ins Internet stellen.** Sie sind standardmäßig nur lokal erreichbar und durch ein Token
   geschützt. Für Zugriff aus dem LAN lieber einen Reverse Proxy mit TLS davorsetzen, sonst geht das Token im Klartext
   über das Netz. Token geheim halten.
3. **Den Recorder nur bei Bedarf starten** und danach beenden (`make stop recorder`). Er erreicht das Gerät.
4. **Eigene Profile nicht veröffentlichen.** Sie enthalten keine Zugangsdaten, wohl aber Adressen und Selektoren deiner
   Geräte; die `.gitignore` schließt sie aus (`profiles/*.json`, außer `beispiel.json`).
5. **Screenshots (`artifacts/`) nicht einchecken.** Sie können sensible Seiteninhalte zeigen und bleiben lokal.
6. **Optional:** Auf dem Docker-Host per Firewall (`DOCKER-USER`-Kette oder eigenes Docker-Netz über
   `SWITCHER_DOCKER_NETWORK`) den Ausgang des Runners auf die Adresse des Geräts beschränken. Die Hostprüfung im Browser
   ersetzt das nicht, sie ergänzt es.

## Wie das Tool abgesichert ist

Der Runner hat Zugriff auf das Gerät, deshalb gilt:

| Maßnahme | Wirkung |
| --- | --- |
| Erlaubte Hosts nur aus `SWITCHER_ALLOWED_HOSTS` (`runner.env`), nie aus dem Profil | Wer Profile ändern kann, kann das Passwort nicht an einen fremden Host schicken |
| Browser blockiert jede Anfrage an andere Hosts (auch Redirects, Bilder, Skripte) | Nur das Gerät ist erreichbar |
| Zugangsdaten nur als `${SWITCHER_USER}` / `${SWITCHER_PASSWORD}` und nur bei `fill` | Passwörter stehen in keinem Profil und im Log nur als „n Zeichen“ |
| Keine Operation für freies JavaScript | Profile können nur die festen Schritte ausführen |
| Wenn-Blöcke (`if_text`, `if_visible`) prüfen nur Text oder Sichtbarkeit, enthalten keine Variablen, und die `goto`-Ziele beider Zweige werden vor dem Lauf auf erlaubte Hosts geprüft | Eine Bedingung wählt nur zwischen festen Schritten, sie bringt weder Zugangsdaten noch andere Hosts ins Spiel |
| Container: `--rm`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, Speicher-/Prozesslimit, kein Port nach außen, läuft als dein Benutzer | Kleine Angriffsfläche, nichts bleibt zurück |
| Harte Laufzeitgrenze (`SWITCHER_MAX_RUNTIME_S`, Standard 120 s) und nur ein Lauf gleichzeitig | Hängende Läufe bleiben nicht offen |
| Editor: Token-Pflicht, Host-Prüfung, optionale IP-Freigabe (`EDITOR_ALLOWED_IPS`), Rate-Limit, strenge CSP, nur lokal gebunden, **keine** Zugangsdaten, startet keine Container | Selbst ein geknackter Editor kann nur Profile ändern |
| Live-Recorder: gleiche Host-Sperre wie der Runner (`SWITCHER_ALLOWED_HOSTS`), WebSocket nur mit Token, Host- und Origin-Prüfung, nur eine Sitzung und ein Betrachter, Zeitgrenzen (180 s Leerlauf, 600 s gesamt), Popups/Dialoge/Downloads aus, Container wie der Runner gehärtet | Der aufgezeichnete Browser kann nur das Gerät erreichen und nur mit gültigem Token gesteuert werden |
| Aufgezeichnete Passwörter: Passwortfelder werden immer als `${SWITCHER_PASSWORD}` gespeichert, fester Text ist dort abgelehnt; andere Felder speichern nur, was du ausdrücklich als festen Text wählst | Zugangsdaten stehen weder im Profil noch im Editor-Log |
| Wiedergabe bis zur Stopmarke: Die Schritte werden wie ein Profil geprüft (nur feste Operationen, nur erlaubte Hosts), `${SWITCHER_…}`-Werte und `TODO`-Schritte spielt der Recorder nie selbst ab | Auch beim Abspielen kommen keine Zugangsdaten in den Recorder, Logins tippst du selbst ein |

**Restrisiko des Live-Recorders:** Der Recorder-Container erreicht das Gerät und wird per Token gesteuert. Wer das Token
hat, kann darin klicken, aber ohne Zugangsdaten nicht anmelden (außer, du tippst sie selbst im Live-Browser ein, dann sieht
der Browser sie nur während der Sitzung). Deshalb: nur bei Bedarf starten, danach beenden, Token geheim halten, nur lokal
binden oder hinter einem Reverse Proxy mit TLS betreiben. Beim Aufzeichnen des Logins dieselben minimalen Rechte
verwenden wie im Betrieb.

### Für Fortgeschrittene: Chromium-Sandbox

Chromium läuft im Container mit `--no-sandbox`, weil der Container selbst die Isolation liefert und der Runner nur erlaubte
Hosts lädt. Wer die Chromium-Sandbox nutzen will, setzt `SWITCHER_CHROMIUM_NO_SANDBOX=0` und startet den Container mit
einem passenden Seccomp-Profil (siehe Playwright-Docker-Dokumentation).

## Getestet mit

Entwickelt und getestet ist Settings Switcher mit einer Fritzbox 7590 mit FRITZ!OS 8.25 (Portfreigabe an und aus,
Aufzeichnen und Abspielen). Andere Geräte und Weboberflächen sollten grundsätzlich gehen, sind aber ungetestet und können
Anpassungen am Profil nötig machen. Noch nicht an einer echten Fritzbox ausprobiert ist die Stopmarke, insbesondere das
Abspielen des Logins mit Anhalten und Selbst-Eintippen im Live-Browser. Was automatisch getestet wird:
[Entwicklung](entwicklung.md#tests).

## Grenzen

- Selektoren sind eine Heuristik und können nach einem Firmware- oder Software-Update des Geräts brechen. Dann den
  betroffenen Schritt neu aufzeichnen (siehe [Fehlersuche](fehlersuche.md)).
- Die Profile sind nur so zuverlässig wie ihre Prüfungen; ein Lauf ohne `expect_*` beweist keine Wirkung.
- Ein Profil kennt nur feste Schritte und eine Anmeldung aus `runner.env`. Seiten mit CAPTCHA oder Einmalcode lassen sich
  nicht automatisieren.
- Bedingungen prüfen nur, ob ein Text oder Element sichtbar ist, und zwar sofort ohne Warten. Wenn-Blöcke lassen sich nicht
  verschachteln, Schleifen oder Berechnungen gibt es nicht (siehe [Profile](profile.md#bedingungen-wenn--sonst)).
- Die Live-Ansicht im Recorder ist eine Folge von Bildern, kein Video.

Bewusst nicht enthalten: Webhook-Endpunkt, Zeitplan, Bearbeiten laufender Aufnahmen. Wie du Profile aus Cron oder einer
Hausautomatisierung startest: [Betrieb](betrieb.md#aus-zeitplaner-oder-hausautomatisierung-aufrufen).
