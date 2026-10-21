# Betrieb

## Profile ausführen

```
./run.sh portfreigabe-an          # Profil ausführen
./run.sh -s portfreigabe-an       # Screenshot nach jedem Schritt (artifacts/)
./run.sh -r 2 portfreigabe-an     # bei Exit 1 den ganzen Lauf bis zu 2-mal wiederholen
./run.sh --list                   # Profile anzeigen
```

Einrichtung (Zugangsdaten, erlaubte Hosts): [Konfiguration](konfiguration.md). Exit-Codes: 0 = erfolgreich, 1 = Lauf
fehlgeschlagen, 2 = Aufruf- oder Konfigurationsfehler.

## Aus Zeitplaner oder Hausautomatisierung aufrufen

Settings Switcher bringt keinen eigenen Zeitplan und keinen Webhook mit. Der Aufruf ist immer `./run.sh <profil>` auf dem
Docker-Host. Das lässt sich aus jedem Werkzeug starten, das einen Befehl ausführen kann, etwa Cron oder eine
Hausautomatisierung (z. B. Home Assistant per SSH oder `shell_command`).

- Auswerten lässt sich der **Exit-Code**: 0 = erfolgreich, 1 = Lauf fehlgeschlagen, 2 = Aufruf- oder Konfigurationsfehler.
- `run.sh` als normaler Benutzer starten, nicht mit `sudo` (siehe [Fehlersuche](fehlersuche.md)).
- Beispiel für Cron (Pfad und Profilname anpassen), schaltet jeden Tag um 22:00 Uhr aus:

```
0 22 * * * cd /pfad/zu/settings-switcher && ./run.sh -r 1 portfreigabe-aus
```

- Eine automatische Rückschaltung nach einer bestimmten Zeit geht mit einem zweiten Profil (`…-aus`) und einem Zeitplan,
  der es später aufruft.

## Wiederholung bei Fehlern (`-r`)

Läuft ein Profil manchmal nicht durch (meist Timing: die Weboberfläche lädt Inhalte nach), kann `run.sh` den **ganzen
Lauf** neu starten, nicht nur den letzten Schritt. Jeder Versuch ist ein frischer Container mit neuem Browser und neuem
Login, ein halb erledigter Zustand aus dem Versuch davor bleibt nicht hängen.

- `-r <n>` (oder `SWITCHER_RETRIES=<n>` in der Shell) erlaubt bis zu `n` zusätzliche Versuche, 0 bis 5.
  Standard ist 0, ohne die Option ändert sich nichts. Die Option steht nicht in `runner.env`, weil `run.sh`
  diese Datei nur an den Container weiterreicht.
- Wiederholt wird **nur bei Exit 1** (Schritt oder Prüfung fehlgeschlagen, auch Zeitgrenze). Exit 2
  (Konfiguration, `TODO` im Profil) und Docker-Fehler (Exit 125 und höher) werden nie wiederholt.
- Zwischen den Versuchen wartet `run.sh` `SWITCHER_RETRY_DELAY_S` Sekunden (Standard 15, höchstens 300).
  Die Pause schützt vor einer Anmeldesperre der Fritzbox nach mehreren Fehlversuchen. Lieber wenige
  Versuche (`-r 1` oder `-r 2`) als viele.
- Nach dem letzten Fehlversuch endet `run.sh` mit Exit 1. Jeder Versuch legt bei einem Fehler seinen
  eigenen Screenshot `…-fehler.png` in `artifacts/` ab.
- **Sicher ist das nur, wenn ein zweiter Lauf harmlos ist.** `check`/`uncheck` setzen einen festen Zustand und
  vertragen das. Ein `click`, der einen Zustand umschaltet, kann beim Wiederholen die Änderung wieder zurückdrehen.
  Setze deshalb `check`/`uncheck` statt `click` auf Checkboxen und eine `expect_*`-Prüfung nach dem Übernehmen
  (siehe [Profile](profile.md)). Der Runner weist im Log darauf hin, wenn ein Profil keine `expect_*`-Prüfung hat.

## Editor und Recorder starten und beenden

Der **Recorder** ist der Editor mit Live-Browser, mit dem du Profile aufzeichnest. Der **Editor** ohne Browser bearbeitet
nur vorhandene Profile.

```bash
make start recorder       # Recorder starten, Standard-Adresse http://127.0.0.1:8080
make stop recorder        # beenden und den Container entfernen
make start editor         # Editor ohne Browser (stop, build und pull ebenso)
```

Ohne `make` geht dasselbe mit Docker Compose: `docker compose --profile record up -d` und
`docker compose --profile record down` (für den Editor ohne Browser `--profile editor`).

- `recorder` ist die Vorgabe, `make start` allein startet also den Recorder.
- Recorder und Editor teilen sich Port und Containernamen, es läuft immer nur einer von beiden. Deshalb nimmt jedes
  dieser Ziele genau einen Dienst.
- Vor dem ersten Start das Image bereitstellen: `make build recorder` baut es lokal, mit eingetragenem Registry-Image in
  der `.env` holt `make pull recorder` es (siehe unten). `make start` aktualisiert ein vorhandenes Image nie.
- `start` benutzt das Image, das die `.env` vorgibt: ohne `SWITCHER_RECORDER_IMAGE` / `SWITCHER_EDITOR_IMAGE` das lokal
  gebaute (`settings-switcher-recorder`, `settings-switcher-editor`), sonst das dort eingetragene Registry-Image.
- Das Runner-Image braucht dafür nichts: `run.sh` baut es selbst.
- Der Recorder erreicht das Gerät, deshalb nur bei Bedarf starten und danach `make stop recorder`.

## Veröffentlichte Images nutzen

Statt Recorder und Editor selbst zu bauen, lassen sich fertige Images aus der GitHub Container Registry verwenden:

1. In der `.env` die Variablen `SWITCHER_EDITOR_IMAGE` und/oder `SWITCHER_RECORDER_IMAGE` auf das Image samt Tag setzen
   (siehe [Konfiguration](konfiguration.md#veröffentlichte-images-statt-lokalem-bau-optional)). Die Namen lauten
   `ghcr.io/<owner>/settings-switcher-recorder` und `ghcr.io/<owner>/settings-switcher-editor`; `<owner>` ist der
   GitHub-Benutzer oder die Organisation, der das Repository gehört.
2. Holen und starten, ohne `--build`:

```bash
make pull recorder        # oder: docker compose --profile record pull
make start recorder       # oder: docker compose --profile record up -d
```

Lässt sich ein Image nicht ohne Anmeldung laden (privates Paket), einmalig auf dem Docker-Host anmelden, mit einem Token
mit dem Recht `read:packages`:

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u <benutzer> --password-stdin
```

`run.sh` baut sein Runner-Image weiterhin selbst aus den lokalen Quellen (siehe [Konfiguration](konfiguration.md)).
Wie die Images entstehen: [Entwicklung](entwicklung.md).

## Aktualisieren

1. Neuen Stand holen: `git pull`. Was sich geändert hat, steht im [CHANGELOG](../CHANGELOG.md).
2. **Runner:** nichts weiter tun. `run.sh` baut ihn beim nächsten Aufruf selbst neu, wenn sich die Quellen geändert haben
   (braucht Netz, dauert beim ersten Mal länger).
3. **Recorder und Editor:** neu bauen und neu starten, mit `make build recorder` und `make start recorder` (oder
   `docker compose --profile record up -d --build`). Mit Registry-Images stattdessen `make pull recorder`, dann
   `make start recorder`.
4. Danach ein Profil mit `./run.sh -s <profil>` probeweise ausführen.
