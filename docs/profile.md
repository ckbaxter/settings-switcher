# Profile und Aufzeichnen

Ein Profil beschreibt einen Ablauf auf einer Weboberfläche als Liste fester Schritte. Man kann es von Hand schreiben oder
im Editor mit dem Live-Browser aufzeichnen. Ablauf einer Aufzeichnung und das Abspielen mit `run.sh`:
siehe unten und [Betrieb](betrieb.md).

## Profil-Format

```json
{
  "name": "portfreigabe-an",
  "description": "Optional",
  "base_url": "http://192.168.178.1",
  "timeout_ms": 15000,
  "steps": [
    { "op": "goto", "value": "/" },
    { "op": "fill", "selector": "…", "value": "${SWITCHER_PASSWORD}" },
    { "op": "click", "selector": "…" },
    { "op": "expect_checked", "selector": "…", "comment": "Erfolgsprüfung" }
  ]
}
```

| Operation | Felder | Bedeutung |
| --- | --- | --- |
| `goto` | `value` | Pfad (`/…`) oder volle URL, nur erlaubte Hosts |
| `click` / `click_text` | `selector` / `value` | Element bzw. Element mit exakt diesem Text anklicken |
| `fill` | `selector`, `value` | Text eintragen, `${SWITCHER_…}` erlaubt |
| `check` / `uncheck` | `selector` | Checkbox setzen |
| `select_option` / `press` | `selector`, `value` | Auswahlliste / Taste |
| `wait_for` / `wait_ms` | `selector` / `value` | Warten auf Element / feste Zeit (ms, max. 30000) |
| `expect_visible` / `expect_text` / `expect_checked` / `expect_unchecked` | `selector` (, `value`) | Erfolgsprüfung. Schlägt sie fehl, endet der Lauf mit Exit 1 |

Ein Lauf gilt als erfolgreich, wenn alle Schritte durchlaufen. Ohne `expect_*`-Prüfung heißt das nur,
dass nichts abgebrochen ist, nicht dass die Änderung wirksam wurde. Ein Schritt, der fehlschlägt, beendet
den Lauf sofort (Exit 1, Screenshot `…-fehler.png`). Spätere Schritte wie der Logout entfallen dann; die
Sitzung auf der Fritzbox läuft von selbst ab.

- Setze die Prüfung **nach dem Übernehmen** und vor den Logout. Sie darf mitten im Ablauf stehen.
- Ein `expect_*` direkt nach dem Klick prüft nur den Formularzustand im Browser. Verlässlich ist die
  Gegenprobe nach einem Neuladen (Regel oder Seite erneut öffnen, dann prüfen).
- Gib der Seite nach „Übernehmen“ etwas Zeit (`wait_ms` oder `wait_for`), bevor der Logout den Browser schließt.
- `check`/`uncheck` setzen einen festen Zustand und tun nichts, wenn er schon so ist. Die Aufzeichnung
  schreibt, was beim Aufzeichnen passiert ist; ein Profil „an“ braucht `check`, ein Profil „aus“ `uncheck`.
  Beide unterscheiden sich oft nur in diesem einen Schritt.
- Ein Logout ist nicht Pflicht (der Container verschwindet, die Sitzung auf der Box läuft aber noch bis zum
  Timeout), aber sauberer, besonders bei häufigen Läufen.

Schritte mit `TODO` in `selector` oder `value` führt der Runner nicht aus.

## Ablauf aufzeichnen (Live-Browser im Editor)

1. `docker compose --profile record up -d --build`, dann `http://127.0.0.1:8080` öffnen und mit dem Token verbinden.
2. Profil anlegen oder öffnen, `base_url` eintragen (muss zu `SWITCHER_ALLOWED_HOSTS` passen) und **Aufnahme starten**.
3. Im Live-Bild klicken wie in einem normalen Browser. Jede Aktion erscheint als Schritt:

| Aktion im Live-Bild | Aufgezeichneter Schritt |
| --- | --- |
| Seite öffnen | `goto` |
| Klick auf Schaltfläche, Link, Element | `click` mit möglichst stabilem Selektor |
| Klick auf Textfeld, dann Text im Feld darunter eingeben und senden | `fill`. Passwortfelder immer mit `${SWITCHER_PASSWORD}`. Andere Felder wahlweise `${SWITCHER_USER}`, `TODO` (selbst ausfüllen) oder fester Text |
| Klick auf Checkbox | `check` / `uncheck` je nach Ergebnis |
| Klick auf Auswahlliste | Liste erscheint im Editor, die Wahl wird `select_option` |
| Enter, Tab, Escape (Tastenknöpfe) | `press` |
| Scrollen: Mausrad, Wischen im Bild (iPad/Touch) oder die Knöpfe ◀ ▲ ▼ ▶ | kein Schritt, die Seite im Live-Browser scrollt nur |
| „Prüfen“-Knöpfe, dann auf ein Element klicken | `expect_visible` / `expect_text` / `expect_checked` / `expect_unchecked` / `wait_for` |

4. **Aufnahme beenden**, Schritte prüfen (Reihenfolge, Selektoren, `TODO`-Werte), **Speichern**.
5. Mit `./run.sh -s <profil>` testen und in der Fritzbox prüfen, ob die Änderung wirklich da ist. Bau nach
   dem Übernehmen eine `expect_*`-Prüfung ein (siehe oben), sonst meldet der Lauf Erfolg, ohne etwas zu prüfen.

### Ab einer Stelle weiter aufzeichnen (Stopmarke)

Hat sich nur ein Teil des Ablaufs geändert (etwa nach einem FRITZ!OS-Update), musst du nicht alles neu aufnehmen:

1. Profil öffnen und beim letzten unveränderten Schritt auf **⚑** klicken. Das ist die Stopmarke; ein
   zweiter Klick entfernt sie. Die Marke gibt es nur im Browserfenster, sie steht nicht im Profil.
2. **Aufnahme starten.** Der Recorder spielt die Schritte bis zur Marke im Live-Browser ab. Das wird nicht
   erneut aufgezeichnet.
3. Danach zeichnest du wie gewohnt weiter auf. Neue Schritte kommen **hinter die Marke**, die bisherigen
   Folgeschritte bleiben stehen. Veraltete Schritte entfernst du mit ✕.
4. Aufnahme beenden, Schritte prüfen, speichern.

Beim Abspielen hält der Recorder an, wenn er einen Schritt nicht selbst ausführen darf oder nicht kann:

- **Login und TODO:** Ein `fill` mit `${SWITCHER_USER}` / `${SWITCHER_PASSWORD}` spielt der Recorder nie selbst ab, er kennt
  keine Zugangsdaten. Dasselbe gilt für Schritte mit `TODO`. Du erledigst den Schritt im Live-Bild (bei einem
  Textfeld ist es schon markiert, getippt wird im Eingabefeld unter dem Bild) und klickst **Erledigt, weiter**.
  Das wird nicht aufgezeichnet. Ein Login braucht also bei jeder Aufnahme mit Marke deine Eingabe.
- **Schritt schlägt fehl** (z. B. Selektor passt nicht mehr): **Wiederholen**, **Schritt überspringen**
  (wenn du ihn selbst erledigt hast) oder **Hier aufzeichnen**.
- **Hier aufzeichnen** beendet die Wiedergabe an der aktuellen Stelle, neue Schritte kommen dahinter. Das geht auch
  mitten im Lauf; der gerade laufende Schritt wird noch beendet.

Während die Wiedergabe läuft, sind Klicks im Live-Bild gesperrt (beim Anhalten sind sie erlaubt, aber nicht
aufgezeichnet). Prüfungen („Text“, „Sichtbar“ …) gehen erst danach. Die Zeitgrenzen der Aufnahme (180 s
Leerlauf, 600 s gesamt) gelten auch für die Wiedergabe.

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
