#!/usr/bin/env python3
"""Führt ein Profil mit Playwright aus und beendet sich mit Exit-Code.

Exit-Codes: 0 = alles erfolgreich, 1 = Schritt oder Prüfung fehlgeschlagen,
            2 = Konfigurations-/Profilfehler (es wurde kein Browser gestartet).

Sicherheitsregeln (bewusst nicht über das Profil änderbar):
- Erlaubte Hosts kommen aus SS_ALLOWED_HOSTS (Umgebung), nicht aus dem Profil.
- Jede Browser-Anfrage zu einem anderen Host wird blockiert.
- Zugangsdaten kommen aus SS_*-Variablen und nur in fill-Schritte.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path

from shared.hosts import is_allowed_url, parse_allowed_hosts, resolve_url, url_host
from shared.profile_schema import (
    DEFAULT_TIMEOUT_MS,
    NAME_RE,
    find_placeholders,
    substitute,
    uses_variable,
    validate_profile,
)

EXIT_OK, EXIT_FAILED, EXIT_CONFIG = 0, 1, 2


def log(message):
    print(message, flush=True)


def load_profile(name, profiles_dir):
    path = Path(profiles_dir) / f"{name}.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def describe_step(step):
    op = step["op"]
    selector = step.get("selector")
    value = step.get("value")
    parts = [op]
    if selector:
        parts.append(selector)
    if op == "fill":
        parts.append(f"({len(value)} Zeichen)")
    elif value:
        parts.append(value)
    return " ".join(parts)


def preflight(profile, env):
    """Alles prüfen, was ohne Browser prüfbar ist. Gibt Fehlerliste zurück."""
    errors = validate_profile(profile)
    errors.extend(find_placeholders(profile) if not errors else [])
    allowed = parse_allowed_hosts(env)
    if not allowed:
        errors.append("SS_ALLOWED_HOSTS ist leer (z. B. SS_ALLOWED_HOSTS=192.168.178.1).")
    if not errors:
        base_host = url_host(profile["base_url"])
        if base_host not in allowed:
            errors.append(f"base_url-Host {base_host!r} steht nicht in SS_ALLOWED_HOSTS.")
        for i, step in enumerate(profile["steps"], 1):
            value = step.get("value")
            if uses_variable(value):
                try:
                    substitute(value, env)
                except KeyError as exc:
                    errors.append(f"Schritt {i}: Variable {exc.args[0]} ist nicht gesetzt.")
            if step["op"] == "goto":
                target = resolve_url(profile["base_url"], value)
                if not is_allowed_url(target, allowed):
                    errors.append(f"Schritt {i}: goto-Ziel liegt außerhalb der erlaubten Hosts.")
    return errors


def execute(page, step, profile, env, timeout):
    from playwright.sync_api import expect

    op = step["op"]
    selector = step.get("selector")
    value = step.get("value")
    loc = page.locator(selector) if selector else None

    if op == "goto":
        page.goto(resolve_url(profile["base_url"], value), wait_until="domcontentloaded")
    elif op == "click":
        loc.click()
    elif op == "click_text":
        page.get_by_text(value, exact=True).click()
    elif op == "fill":
        loc.fill(substitute(value, env) if uses_variable(value) else value)
    elif op == "check":
        loc.check()
    elif op == "uncheck":
        loc.uncheck()
    elif op == "select_option":
        loc.select_option(value)
    elif op == "press":
        loc.press(value)
    elif op == "wait_for":
        loc.wait_for(state="visible")
    elif op == "wait_ms":
        page.wait_for_timeout(int(value))
    elif op == "expect_visible":
        expect(loc).to_be_visible(timeout=timeout)
    elif op == "expect_text":
        expect(loc).to_contain_text(value, timeout=timeout)
    elif op == "expect_checked":
        expect(loc).to_be_checked(timeout=timeout)
    elif op == "expect_unchecked":
        expect(loc).not_to_be_checked(timeout=timeout)
    else:  # durch Validierung ausgeschlossen
        raise ValueError(f"Unbekannte Operation {op}")


def short_error(exc):
    text = str(exc).strip().splitlines()
    return (text[0] if text else exc.__class__.__name__)[:300]


def save_screenshot(page, path):
    try:
        page.screenshot(path=str(path))
        log(f"    Screenshot: {path.name}")
    except Exception as exc:  # noqa: BLE001 - Screenshot darf den Lauf nicht überdecken
        log(f"    Screenshot fehlgeschlagen: {short_error(exc)}")


def run_profile(profile, env, artifacts_dir):
    from playwright.sync_api import sync_playwright

    allowed = parse_allowed_hosts(env)
    timeout = profile.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    steps = profile["steps"]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    all_shots = env.get("SS_SCREENSHOTS", "") == "all"
    artifacts_dir = Path(artifacts_dir)
    blocked = set()

    launch_args = ["--disable-dev-shm-usage"]
    if env.get("SS_CHROMIUM_NO_SANDBOX", "1") != "0":
        launch_args.append("--no-sandbox")

    started = time.monotonic()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=launch_args)
        context = browser.new_context(
            ignore_https_errors=env.get("SS_IGNORE_HTTPS_ERRORS", "0") == "1",
            service_workers="block",
            accept_downloads=False,
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
        )

        def guard(route):
            url = route.request.url
            if is_allowed_url(url, allowed):
                route.continue_()
            else:
                blocked.add(url_host(url) or url.split(":", 1)[0])
                route.abort("blockedbyclient")

        context.route("**/*", guard)
        page = context.new_page()
        page.set_default_timeout(timeout)
        page.set_default_navigation_timeout(timeout)

        try:
            for i, step in enumerate(steps, 1):
                label = f"[{i}/{len(steps)}] {describe_step(step)}"
                t0 = time.monotonic()
                try:
                    execute(page, step, profile, env, timeout)
                except Exception as exc:  # noqa: BLE001
                    log(f"{label} ... FEHLER: {short_error(exc)}")
                    save_screenshot(page, artifacts_dir / f"{profile['name']}-{stamp}-fehler.png")
                    return EXIT_FAILED
                log(f"{label} ... ok ({time.monotonic() - t0:.1f}s)")
                if all_shots:
                    save_screenshot(page, artifacts_dir / f"{profile['name']}-{stamp}-{i:02d}.png")
        finally:
            if blocked:
                log(f"Hinweis: Anfragen an nicht erlaubte Hosts blockiert: {', '.join(sorted(blocked))}")
            context.close()
            browser.close()

    log(f"OK: Profil {profile['name']} ({len(steps)} Schritte, {time.monotonic() - started:.1f}s)")
    return EXIT_OK


def _watchdog(_signum, _frame):
    log("FEHLER: maximale Laufzeit überschritten, Abbruch.")
    os._exit(EXIT_FAILED)


def main(argv=None, env=None):
    argv = sys.argv[1:] if argv is None else argv
    env = dict(os.environ) if env is None else env
    if len(argv) != 1 or not NAME_RE.match(argv[0]):
        log("Aufruf: runner.py <profilname>   (a-z, 0-9, _ und -)")
        return EXIT_CONFIG
    name = argv[0]

    profiles_dir = env.get("SS_PROFILES_DIR", "/profiles")
    artifacts_dir = env.get("SS_ARTIFACTS_DIR", "/artifacts")
    try:
        profile = load_profile(name, profiles_dir)
    except FileNotFoundError:
        log(f"FEHLER: Profil {name} nicht gefunden.")
        return EXIT_CONFIG
    except (OSError, json.JSONDecodeError) as exc:
        log(f"FEHLER: Profil {name} nicht lesbar: {short_error(exc)}")
        return EXIT_CONFIG
    if isinstance(profile, dict) and profile.get("name") != name:
        log(f"FEHLER: Feld name im Profil ({profile.get('name')!r}) passt nicht zum Dateinamen.")
        return EXIT_CONFIG

    errors = preflight(profile, env)
    if errors:
        log(f"FEHLER: Profil {name} kann nicht ausgeführt werden:")
        for err in errors:
            log(f"  - {err}")
        return EXIT_CONFIG

    max_runtime = int(env.get("SS_MAX_RUNTIME_S", "120"))
    signal.signal(signal.SIGALRM, _watchdog)
    signal.alarm(max_runtime)
    log(f"Starte Profil {name}")
    return run_profile(profile, env, artifacts_dir)


if __name__ == "__main__":
    sys.exit(main())
