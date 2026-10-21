# Fehlersuche

| Symptom | Ursache und Abhilfe |
| --- | --- |
| Editor: „Host nicht erlaubt.“ | Der Name aus der Browser-Adresszeile (ohne Port) fehlt in `EDITOR_ALLOWED_HOSTS`. Eintrag in `.env` ergänzen, Zeile nicht auskommentiert lassen, mit `docker compose … up -d` neu anlegen (ein Neustart liest `.env` nicht neu). |
| Speichern: „Keine Schreibrechte …“ / Fehler 500 | Der Container-Benutzer darf nicht in `./profiles` schreiben. `SWITCHER_UID`/`SWITCHER_GID` in `.env` auf `id -u` / `id -g` des Besitzers setzen (oder `chown`), Dienst neu anlegen. |
| `run.sh`: „Profil … nicht lesbar: Permission denied“ | `./profiles` braucht `755`, die Profile `644` (neuere Editor-Versionen speichern so). Der Runner läuft mit `--cap-drop ALL`, daher kann auch root fremde Dateien nur mit passenden Rechten lesen. `run.sh` besser nicht mit `sudo` starten. Nach einem Update `docker compose --profile record up -d --build`. |
| Lauf „ok“, aber nichts geändert | Meist falsche Richtung (`uncheck` statt `check` oder der Zustand war schon so), zu früher Logout oder fehlende Gegenprobe. `./run.sh -s` zeigt Screenshots pro Schritt. |
| Schritt bricht ab | Selektor nicht (mehr) eindeutig, z. B. nach FRITZ!OS-Update, oder Element erscheint erst nach dem Laden (`wait_for` davor). Den Schritt neu aufzeichnen. |
| Lauf klappt nur manchmal | Meist Timing. Vor den betroffenen Schritt ein `wait_for` auf das Element setzen, mit `./run.sh -s` Screenshots ansehen. Als Absicherung `./run.sh -r 2 <profil>` (siehe [Betrieb](betrieb.md#wiederholung-bei-fehlern--r)). |
