# Erste Schritte

Von der Installation bis zum ersten Lauf, am Beispiel einer Portfreigabe, die du an- und ausschaltest. Als Gerät dient
eine Fritzbox mit der Adresse `192.168.178.1`; ersetze sie durch die Adresse deines Geräts. Die Kurzfassung steht in der
[README](../README.de.md), die Einzelheiten in [Konfiguration](konfiguration.md) und [Profile](profile.md).

## 1. Voraussetzungen

Ein Linux-Host mit Docker (Compose v2) und Bash, der die Weboberfläche des Geräts erreicht. Das Gerät braucht eine
Anmeldung über ein einfaches Formular.

## 2. Zugang einrichten

```bash
cp runner.env.example runner.env && chmod 600 runner.env
cp .env.example .env && chmod 600 .env
```

- In `runner.env`: die Adresse des Geräts bei `SWITCHER_ALLOWED_HOSTS` und die Zugangsdaten (`SWITCHER_USER`,
  `SWITCHER_PASSWORD`). Am besten einen eigenen Benutzer mit möglichst wenigen Rechten verwenden.
- In `.env`: ein Editor-Token (z. B. mit `openssl rand -hex 24` erzeugen) und dieselbe Adresse bei
  `SWITCHER_ALLOWED_HOSTS`.

## 3. Profil „an“ aufzeichnen

1. Recorder starten: `make start recorder` (vorher einmal `make build recorder`) oder
   `docker compose --profile record up -d --build`. Dann `http://127.0.0.1:8080` öffnen und mit dem Token verbinden.
2. Neues Profil anlegen, zum Beispiel `portfreigabe-an`, `base_url` eintragen (`http://192.168.178.1`) und
   **Aufnahme starten**.
3. Im Live-Bild anmelden und die Einstellung wie gewohnt ändern, bis sie übernommen ist. Bei Passwortfeldern wählst du
   `${SWITCHER_PASSWORD}`, das Passwort selbst steht nie im Profil.
4. Eine **Prüfung** hinzufügen (zum Beispiel „Checkbox ist gesetzt“), damit ein Lauf nur dann als erfolgreich gilt, wenn
   die Einstellung wirklich gesetzt ist. Sie gehört nach dem Übernehmen (und vor einen Logout, falls du dich abmeldest).
5. **Aufnahme beenden**, die Schritte ansehen und **Speichern**.

Mehr dazu, auch zum Weiterzeichnen ab einer Stelle: [Profile und Aufzeichnen](profile.md#ablauf-aufzeichnen-live-browser-im-editor).

## 4. Ausprobieren

```bash
./run.sh -s portfreigabe-an
```

Beim ersten Aufruf baut `run.sh` das Runner-Image, das dauert etwas. Mit `-s` entstehen Screenshots der einzelnen Schritte
in `artifacts/`. Prüfe in der Weboberfläche des Geräts, ob die Änderung wirklich angekommen ist. Exit-Code 0 heißt
erfolgreich, 1 heißt Lauf fehlgeschlagen, 2 heißt Aufruf- oder Konfigurationsfehler (siehe auch
[Fehlersuche](fehlersuche.md)).

## 5. Profil „aus“ anlegen

Das Profil zum Ausschalten sieht meist fast gleich aus: statt `check` steht `uncheck`, dazu eine passende Prüfung
(`expect_unchecked`). Zeichne es auf demselben Weg auf wie das Profil „an“.

## 6. Automatisieren

Ab jetzt reicht `./run.sh portfreigabe-an` und `./run.sh portfreigabe-aus`, auch aus Cron oder einer Hausautomatisierung:
[Betrieb](betrieb.md#aus-zeitplaner-oder-hausautomatisierung-aufrufen). Den Recorder beendest du, wenn du ihn nicht mehr
brauchst, mit `make stop recorder`.
