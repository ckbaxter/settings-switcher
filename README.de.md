# Settings Switcher

Schaltet eine Einstellung auf einer Weboberfläche per Skript an oder aus. Du zeichnest einmal einen Klickablauf auf, das Tool spielt ihn später in einem unsichtbaren Browser ab, für Geräte und Dienste, bei denen die Weboberfläche der einzige Zugang ist. Ein typischer Anwendungsfall ist die Portfreigabe einer Fritzbox, wenn die TR-064-Schnittstelle des Routers nicht in Frage kommt.

*English version: [README.md](README.md)*

## So funktioniert es

Du klickst die Änderung einmal in einem eingebauten Browser durch, und das Tool schreibt deine Schritte als **Profil** auf: eine kurze Liste einfacher Aktionen. Danach wiederholt ein einziger Befehl sie in einem frischen Wegwerf-Container mit einem unsichtbaren Browser:

```
./run.sh einstellung-an
./run.sh einstellung-aus
```

Der Exit-Code sagt, ob es geklappt hat. So lässt sich der Aufruf aus einem Zeitplaner oder einer Hausautomatisierung heraus nutzen.

- **Profile** sind kleine JSON-Dateien mit festen Aktionen (Seite öffnen, klicken, ausfüllen, Häkchen setzen, Ergebnis prüfen). Freies Scripting gibt es nicht.
- **Recorder:** eine kleine Webseite mit Live-Browser. Du klickst durch die Weboberfläche wie gewohnt, jede Aktion wird zu einem Schritt.
- **Runner:** `run.sh` startet einen abgeschotteten Container, spielt das Profil ab und entfernt den Container wieder.

## Funktionen

- Funktioniert mit jeder Weboberfläche, die der Docker-Host erreicht; nichts davon ist an ein bestimmtes Gerät gebunden
- Profil durch Klicken aufzeichnen, auch am Tablet (Scrollen per Wischen); ab einer beliebigen Stelle weiter aufzeichnen
- Bedingungen (wenn / sonst): Schritte nur ausführen, wenn ein Text oder Element auf der Seite steht; per Klick im Live-Browser wählbar ([docs/profile.md](docs/profile.md#bedingungen-wenn--sonst))
- Prüfungen nach der Änderung: Ein Lauf gilt nur dann als erfolgreich, wenn die Einstellung wirklich im erwarteten Zustand ist
- Optional automatische Wiederholung des ganzen Laufs, wenn er ab und zu fehlschlägt
- Passwörter stehen nie in einem Profil; der Browser darf nur die Adressen besuchen, die du erlaubst
- Fertige Docker-Images zum Herunterladen (GitHub Container Registry)

## Voraussetzungen

- Ein Linux-Host mit Docker (Compose v2) und Bash
- Eine Weboberfläche, die der Docker-Host erreicht, mit einer Anmeldung über ein einfaches Formular
- Entwickelt und getestet nur mit einer Fritzbox 7590 mit FRITZ!OS 8.25 (Portfreigabe an und aus). Andere Geräte und Weboberflächen sollten grundsätzlich gehen, sind aber ungetestet und können Anpassungen am Profil nötig machen.

## Schnellstart

1. **Zugang:** `cp runner.env.example runner.env && chmod 600 runner.env`, dann Adresse der Weboberfläche und eine Anmeldung eintragen. Am besten einen eigenen Benutzer mit möglichst wenigen Rechten verwenden.
2. **Einstellungen des Editors:** `cp .env.example .env && chmod 600 .env`, dann ein Editor-Token setzen (zum Beispiel `openssl rand -hex 24`) und dieselbe Adresse eintragen.
3. **Aufzeichnen:** `docker compose --profile record up -d --build`, `http://127.0.0.1:8080` öffnen, die Änderung durchklicken und das Profil speichern. Den Editor beendest du mit `docker compose --profile record down`.
4. **Ausführen:** `./run.sh <profil>`

Die Beispieldateien und die Dokumentation verwenden eine Fritzbox als durchgehendes Beispiel (Adresse `192.168.178.1`); ersetze sie durch deine eigene.

Eine ausführlichere Anleitung: [docs/erste-schritte.md](docs/erste-schritte.md)

Mehr: [docs/konfiguration.md](docs/konfiguration.md) · [docs/profile.md](docs/profile.md) · [docs/betrieb.md](docs/betrieb.md) · [docs/fehlersuche.md](docs/fehlersuche.md) · [docs/sicherheit-und-grenzen.md](docs/sicherheit-und-grenzen.md)

## Versionen und Mitarbeit

Die Versionen folgen [Semantic Versioning](https://semver.org/lang/de/), Änderungen stehen im [CHANGELOG](CHANGELOG.md). Wer mitarbeiten oder Releases erstellen will, findet alles in [docs/entwicklung.md](docs/entwicklung.md). Lizenz: MIT.

## Sicherheitshinweis

Der Runner kann sich an der Weboberfläche anmelden, behandle ihn deshalb wie einen Schlüssel. Die Zugangsdaten stehen nur in `runner.env`, nie in einem Profil. Den Editor nicht ins Internet stellen; er ist standardmäßig nur lokal erreichbar und durch ein Token geschützt. Profile enthalten Adressen und Elementnamen deiner eigenen Geräte, deshalb hält die `.gitignore` eigene Profile aus dem Repository heraus. Details: [docs/sicherheit-und-grenzen.md](docs/sicherheit-und-grenzen.md).

## Grenzen (kurz)

Aufgezeichnete Schritte können nach einem Firmware- oder Software-Update brechen und müssen dann neu aufgezeichnet werden. Ein Lauf ohne Prüfung beweist nicht, dass sich die Einstellung geändert hat. Ein Profil kennt nur feste Schritte und eine Anmeldung aus `runner.env`; Seiten mit CAPTCHA oder Einmalcode lassen sich deshalb nicht automatisieren. Die Live-Ansicht ist eine Folge von Bildern, kein Video.

## Haftungsausschluss

Settings Switcher ist ein unabhängiges Projekt und steht in keiner Verbindung zu AVM GmbH oder einem anderen Geräte- oder Softwarehersteller und wird nicht von ihnen unterstützt. Fritzbox und FRITZ!OS sind wie alle anderen genannten Produktnamen Marken ihrer jeweiligen Inhaber.
