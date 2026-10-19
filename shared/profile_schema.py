"""Profil-Schema, gemeinsam genutzt von Runner und Editor.

Ein Profil ist eine JSON-Datei mit einer festen Liste erlaubter Schritte.
Es gibt bewusst keinen Schritt zum Ausführen von freiem JavaScript.
"""

import re

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
VAR_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")
VAR_NAME_RE = re.compile(r"^SS_[A-Z0-9_]+$")

MAX_STEPS = 100
MAX_STRING = 500
MAX_WAIT_MS = 30_000
DEFAULT_TIMEOUT_MS = 15_000
TIMEOUT_RANGE = (1_000, 60_000)

# op -> (Pflichtfelder, Beschreibung)
OPS = {
    "goto": (("value",), "Seite öffnen (Pfad wie /  oder volle URL)"),
    "click": (("selector",), "Element anklicken"),
    "click_text": (("value",), "Element mit exakt diesem Text anklicken"),
    "fill": (("selector", "value"), "Text eintragen (${SS_...} erlaubt)"),
    "check": (("selector",), "Checkbox aktivieren"),
    "uncheck": (("selector",), "Checkbox deaktivieren"),
    "select_option": (("selector", "value"), "Eintrag aus Auswahlliste wählen"),
    "press": (("selector", "value"), "Taste drücken (z. B. Enter)"),
    "wait_for": (("selector",), "Warten, bis Element sichtbar ist"),
    "wait_ms": (("value",), "Feste Wartezeit in Millisekunden"),
    "expect_visible": (("selector",), "Prüfen: Element ist sichtbar"),
    "expect_text": (("selector", "value"), "Prüfen: Element enthält Text"),
    "expect_checked": (("selector",), "Prüfen: Checkbox ist aktiv"),
    "expect_unchecked": (("selector",), "Prüfen: Checkbox ist nicht aktiv"),
}

TOP_KEYS = {"name", "description", "base_url", "timeout_ms", "steps"}
STEP_KEYS = {"op", "selector", "value", "comment"}


def _is_http_url(value):
    return isinstance(value, str) and re.match(r"^https?://[^\s/]+", value) is not None


def _is_plain_path(value):
    """Pfad auf demselben Host. '//host' und Backslashes würden einen anderen Host ansprechen."""
    return (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and not any(ord(c) < 32 for c in value)
    )


def validate_profile(data):
    """Gibt eine Liste von Fehlertexten zurück (leer = gültig)."""
    errors = []
    if not isinstance(data, dict):
        return ["Profil muss ein JSON-Objekt sein."]

    for key in data:
        if key not in TOP_KEYS:
            errors.append(f"Unbekanntes Feld: {key}")

    name = data.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        errors.append("name: nur a-z, 0-9, _ und -, 1-64 Zeichen, nicht mit - oder _ beginnen.")

    desc = data.get("description", "")
    if not isinstance(desc, str) or len(desc) > MAX_STRING:
        errors.append(f"description: Text bis {MAX_STRING} Zeichen.")

    if not _is_http_url(data.get("base_url")) or len(data["base_url"]) > MAX_STRING:
        errors.append("base_url: muss mit http:// oder https:// beginnen.")

    timeout = data.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    if (
        not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or not TIMEOUT_RANGE[0] <= timeout <= TIMEOUT_RANGE[1]
    ):
        errors.append(f"timeout_ms: ganze Zahl zwischen {TIMEOUT_RANGE[0]} und {TIMEOUT_RANGE[1]}.")

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps: mindestens ein Schritt erforderlich.")
        return errors
    if len(steps) > MAX_STEPS:
        errors.append(f"steps: höchstens {MAX_STEPS} Schritte.")
        return errors

    for i, step in enumerate(steps, 1):
        errors.extend(_validate_step(i, step))
    return errors


def _validate_step(i, step):
    where = f"Schritt {i}"
    if not isinstance(step, dict):
        return [f"{where}: muss ein Objekt sein."]
    errors = []
    for key in step:
        if key not in STEP_KEYS:
            errors.append(f"{where}: unbekanntes Feld {key}")
    op = step.get("op")
    if op not in OPS:
        errors.append(f"{where}: unbekannte Operation {op!r}.")
        return errors

    required = OPS[op][0]
    for field in ("selector", "value", "comment"):
        v = step.get(field)
        if v is not None and (not isinstance(v, str) or len(v) > MAX_STRING):
            errors.append(f"{where}: {field} muss Text bis {MAX_STRING} Zeichen sein.")
    for field in required:
        v = step.get(field)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"{where} ({op}): {field} fehlt.")
    for field in ("selector", "value"):
        if field not in required and step.get(field):
            errors.append(f"{where} ({op}): {field} wird bei dieser Operation nicht benutzt.")

    value = step.get("value")
    if isinstance(value, str):
        if op == "wait_ms":
            if not value.isdigit() or not 0 < int(value) <= MAX_WAIT_MS:
                errors.append(f"{where}: wait_ms braucht eine Zahl von 1 bis {MAX_WAIT_MS}.")
        if op == "goto" and not (_is_plain_path(value) or _is_http_url(value)):
            errors.append(f"{where}: goto braucht einen Pfad mit / am Anfang (nicht //) oder eine http(s)-URL.")
        variables = VAR_RE.findall(value)
        if variables and op != "fill":
            errors.append(f"{where}: Variablen sind nur bei fill erlaubt.")
        for var in variables:
            if not VAR_NAME_RE.match(var):
                errors.append(f"{where}: Variable {var} ist nicht erlaubt (nur SS_...).")
    selector = step.get("selector")
    if isinstance(selector, str) and VAR_RE.search(selector):
        errors.append(f"{where}: Variablen im Selektor sind nicht erlaubt.")
    return errors


def find_placeholders(data):
    """Schritte, die noch ein TODO-Platzhalter-Feld enthalten (Runner führt sie nicht aus)."""
    found = []
    for i, step in enumerate(data.get("steps", []), 1):
        if not isinstance(step, dict):
            continue
        for field in ("selector", "value"):
            v = step.get(field)
            if isinstance(v, str) and v.strip().upper().startswith("TODO"):
                found.append(f"Schritt {i}: {field} ist noch ein TODO-Platzhalter.")
    return found


def uses_variable(value):
    return isinstance(value, str) and VAR_RE.search(value) is not None


def substitute(value, env):
    """Ersetzt ${SS_...} durch Werte aus env. Fehlende Variable -> KeyError."""

    def repl(match):
        var = match.group(1)
        if not VAR_NAME_RE.match(var):
            raise KeyError(var)
        if var not in env or env[var] == "":
            raise KeyError(var)
        return env[var]

    return VAR_RE.sub(repl, value)
