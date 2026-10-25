# Fehlersuche

| Symptom | Ursache und Abhilfe |
| --- | --- |
| Editor: „Host nicht erlaubt.“ | Der Name aus der Browser-Adresszeile (ohne Port) fehlt in `EDITOR_ALLOWED_HOSTS`. Eintrag in `.env` ergänzen, Zeile nicht auskommentiert lassen, mit `docker compose … up -d` neu anlegen (ein Neustart liest `.env` nicht neu). |
| Editor lässt sich nicht starten, Port 8080 ist belegt | Ein anderer Dienst oder der jeweils andere von Recorder und Editor belegt den Port. Den anderen beenden oder in `.env` einen anderen `EDITOR_PORT` setzen und mit `docker compose … up -d` neu anlegen. |
| Docker: „permission denied“ beim Zugriff auf den Docker-Dienst | Der Benutzer darf Docker nicht verwenden. In die Gruppe `docker` aufnehmen und neu anmelden, statt `run.sh` mit `sudo` zu starten (siehe „Profil … nicht lesbar“ weiter unten). |
| Speichern: „Keine Schreibrechte …“ / Fehler 500 | Der Container-Benutzer darf nicht in `./profiles` schreiben. `SWITCHER_UID`/`SWITCHER_GID` in `.env` auf `id -u` / `id -g` des Besitzers setzen (oder `chown`), Dienst neu anlegen. |
| `run.sh`: „Profil … nicht lesbar: Permission denied“ | `./profiles` braucht `755`, die Profile `644` (neuere Editor-Versionen speichern so). Der Runner läuft mit `--cap-drop ALL`, daher kann auch root fremde Dateien nur mit passenden Rechten lesen. `run.sh` besser nicht mit `sudo` starten. Nach einem Update `docker compose --profile record up -d --build`. |
| Seite lässt sich nicht öffnen, Name wie `fritz.box` wird nicht gefunden | Im Container wird der Gerätename oft nicht aufgelöst. Die IP-Adresse verwenden, in `SWITCHER_ALLOWED_HOSTS` und in `base_url` des Profils. |
| Anmeldung klappt nach mehreren Läufen nicht mehr | Das Gerät sperrt die Anmeldung womöglich nach mehreren Fehlversuchen (bei der Fritzbox der Fall). Kurz warten, Zugangsdaten in `runner.env` prüfen. Bei Wiederholungen mit `-r` die Pause (`SWITCHER_RETRY_DELAY_S`) nicht zu kurz wählen. |
| Lauf „ok“, aber nichts geändert | Meist falsche Richtung (`uncheck` statt `check` oder der Zustand war schon so), zu früher Logout oder fehlende Gegenprobe. `./run.sh -s` zeigt Screenshots pro Schritt. |
| Schritt bricht ab | Selektor nicht (mehr) eindeutig, z. B. nach einem Firmware-Update des Geräts, oder Element erscheint erst nach dem Laden (`wait_for` davor). Den Schritt neu aufzeichnen. |
| Wenn-Block nimmt den falschen Zweig | Die Bedingung wird sofort ausgewertet. Lädt die Seite noch, davor ein `wait_for` oder `wait_ms` setzen. Bei `if_text` zählt nur sichtbarer Text im angegebenen Bereich (Groß-/Kleinschreibung egal), ein zu enger `selector` lässt die Bedingung ins Leere laufen. Das Log nennt den gewählten Zweig, `./run.sh -s` liefert Screenshots pro Schritt. |
| Lauf klappt nur manchmal | Meist Timing. Vor den betroffenen Schritt ein `wait_for` auf das Element setzen, mit `./run.sh -s` Screenshots ansehen. Als Absicherung `./run.sh -r 2 <profil>` (siehe [Betrieb](betrieb.md#wiederholung-bei-fehlern--r)). |
