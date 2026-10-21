"""Ganzer Weg: im Editor aufnehmen, speichern und das Profil mit dem Runner ausführen."""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from editor.app import create_app
from editor.recorder import Recorder

TOKEN = "r" * 24


@pytest.fixture
def live(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    recorder = Recorder({"127.0.0.1"}, max_seconds=120, idle_seconds=120)
    app = create_app(tmp_path / "profiles", TOKEN, ["127.0.0.1"], recorder=recorder)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    (tmp_path / "profiles").mkdir()
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", tmp_path / "profiles"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        pg = browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
        pg.set_default_timeout(8000)
        yield pg
        browser.close()


def connect(page, url):
    page.goto(url)
    page.fill("#token", TOKEN)
    page.click("text=Verbinden")
    expect(page.locator("#new-profile")).to_be_enabled()


def live_click(page, x, y):
    box = page.locator("#live").bounding_box()
    scale = box["width"] / 1280
    page.locator("#live").click(position={"x": x * scale, "y": y * scale})


def wait_steps(page, count):
    expect(page.locator("#steps .step")).to_have_count(count)


def test_record_save_and_replay_with_runner(live, server, page, tmp_path):
    url, profiles = live
    connect(page, url)
    page.click("#new-profile")
    expect(page.locator("#recorder")).to_be_visible()
    page.fill("#f-name", "aufnahme")
    page.fill("#f-base", server)
    page.click("#rec-start")
    expect(page.locator("#rec-live")).to_be_visible()
    expect(page.locator("#live")).to_have_attribute("src", re.compile("^blob:"))
    wait_steps(page, 1)  # goto /

    live_click(page, 170, 35)  # Benutzerfeld
    page.select_option("#rec-as", "user")
    page.fill("#rec-text", "alice")
    page.click("#rec-text-form button[type=submit]")
    wait_steps(page, 2)

    live_click(page, 170, 85)  # Passwortfeld
    page.select_option("#rec-as", "auto")
    page.fill("#rec-text", "super-geheim")
    page.click("#rec-text-form button[type=submit]")
    wait_steps(page, 3)

    live_click(page, 80, 135)  # Anmelden
    wait_steps(page, 4)
    live_click(page, 30, 210)  # Freigabe aktivieren
    wait_steps(page, 5)
    live_click(page, 260, 215)  # Übernehmen
    wait_steps(page, 6)

    page.click('#rec-picks [data-kind="expect_text"]')
    live_click(page, 250, 250)  # Statustext prüfen
    wait_steps(page, 7)
    page.click('#rec-picks [data-kind="expect_checked"]')
    live_click(page, 30, 210)  # Freigabe ist aktiv
    wait_steps(page, 8)

    page.click("#rec-stop")
    expect(page.locator("#rec-live")).to_be_hidden()

    page.click("#save")
    expect(page.locator("#messages")).to_contain_text("Gespeichert")

    text = (profiles / "aufnahme.json").read_text(encoding="utf-8")
    saved = json.loads(text)
    assert "super-geheim" not in text and "alice" not in text
    assert [(s["op"], s.get("selector"), s.get("value")) for s in saved["steps"]] == [
        ("goto", None, "/"),
        ("fill", "#user", "${SWITCHER_USER}"),
        ("fill", 'input[name="pwd"]', "${SWITCHER_PASSWORD}"),
        ("click", "#login", None),
        ("check", "#enabled", None),
        ("click", 'role=button[name="Übernehmen"]', None),
        ("expect_text", "#status", "gespeichert"),
        ("expect_checked", "#enabled", None),
    ]

    # Das aufgezeichnete Profil läuft im echten Runner durch
    (tmp_path / "artifacts").mkdir()
    env = {
        "SWITCHER_PROFILES_DIR": str(profiles),
        "SWITCHER_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
        "SWITCHER_ALLOWED_HOSTS": "127.0.0.1",
        "SWITCHER_USER": "alice",
        "SWITCHER_PASSWORD": "super-geheim",
    }
    # als eigener Prozess: genau so startet ihn auch der Container
    result = subprocess.run(
        [sys.executable, "runner/runner.py", "aufnahme"],
        env={**os.environ, **env, "PYTHONPATH": "."},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: Profil aufnahme" in result.stdout
    assert "super-geheim" not in result.stdout


def test_second_viewer_is_rejected_and_recorder_stops_on_demand(live, server, page):
    url, _ = live
    connect(page, url)
    page.click("#new-profile")
    page.fill("#f-base", server)
    page.click("#rec-start")
    expect(page.locator("#rec-live")).to_be_visible()

    second = page.context.new_page()
    second.goto(url)
    second.fill("#token", TOKEN)
    second.click("text=Verbinden")
    expect(second.locator("#messages")).to_contain_text("anderen Fenster")

    page.click("#rec-stop")
    expect(page.locator("#rec-live")).to_be_hidden()


def test_start_outside_allowed_hosts_is_refused(live, page):
    url, _ = live
    connect(page, url)
    page.click("#new-profile")
    page.fill("#f-base", "http://192.168.178.99")
    page.click("#rec-start")
    expect(page.locator("#messages")).to_contain_text("SWITCHER_ALLOWED_HOSTS")
    expect(page.locator("#rec-live")).to_be_hidden()


# ---------- Scrollen im Live-Browser (Knöpfe, Mausrad, Wischen auf dem iPad) ----------


def read_scroll_position(page):
    """Liest den Scrollstand der Testseite über eine Prüfung (expect_text auf #pos) im Editor."""
    before = page.locator("#steps .step").count()
    page.click('#rec-picks [data-kind="expect_text"]')
    live_click(page, 905, 25)
    wait_steps(page, before + 1)
    value = page.locator("#steps .step").nth(before).locator("input").nth(1).input_value()
    page.locator("#steps .step").nth(before).get_by_role("button").last.click()  # Schritt wieder entfernen
    wait_steps(page, before)
    return value


def wait_for_position(page, expected, timeout=6):
    end = time.time() + timeout
    value = None
    while time.time() < end:
        value = read_scroll_position(page)
        if value == expected:
            return
        time.sleep(0.2)
    raise AssertionError(f"Scrollstand {value!r}, erwartet {expected!r}")


def start_recording(page, url, server):
    connect(page, url)
    page.click("#new-profile")
    page.fill("#f-base", server)
    page.click("#rec-start")
    expect(page.locator("#rec-live")).to_be_visible()
    expect(page.locator("#live")).to_have_attribute("src", re.compile("^blob:"))
    wait_steps(page, 1)


def test_scroll_buttons_move_the_live_page(live, server, page):
    url, _ = live
    start_recording(page, url, server)
    expect(page.locator("#rec-scroll button")).to_have_count(4)

    page.click('#rec-scroll [data-scroll="down"]')
    wait_for_position(page, "0,400")
    page.click('#rec-scroll [data-scroll="right"]')
    wait_for_position(page, "400,400")
    page.click('#rec-scroll [data-scroll="up"]')
    wait_for_position(page, "400,0")
    page.click('#rec-scroll [data-scroll="left"]')
    wait_for_position(page, "0,0")
    wait_steps(page, 1)  # Scrollen erzeugt keine Schritte


def test_touch_swipe_scrolls_and_does_not_click(live, server):
    url, _ = live
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1000, "height": 1100}, has_touch=True, is_mobile=False)
        page = context.new_page()
        page.set_default_timeout(8000)
        try:
            start_recording(page, url, server)
            box = page.locator("#live").bounding_box()
            scale = 1280 / box["width"]
            cdp = context.new_cdp_session(page)
            x = box["x"] + box["width"] / 2
            y0 = box["y"] + box["height"] * 0.8

            def touch(kind, yy=None):
                points = [] if yy is None else [{"x": x, "y": yy}]
                cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

            # Finger nach oben wischen = Seite im Live-Browser läuft nach unten
            touch("touchStart", y0)
            for i in range(1, 9):
                touch("touchMove", y0 - i * 20)
                time.sleep(0.03)
            touch("touchEnd")
            swiped = 160 * scale
            deadline = time.time() + 6
            value = ""
            while time.time() < deadline:
                value = read_scroll_position(page)
                if value.startswith("0,") and abs(int(value.split(",")[1]) - swiped) < swiped * 0.25:
                    break
                time.sleep(0.2)
            assert value.startswith("0,"), value
            assert abs(int(value.split(",")[1]) - swiped) < swiped * 0.25, (value, swiped)
            wait_steps(page, 1)  # kein Klick-Schritt durch das Wischen
        finally:
            browser.close()


# ---------- Stopmarke: bis hierher abspielen, ab hier weiter aufzeichnen ----------


def write_profile(profiles, server, steps, name="ablauf"):
    data = {"name": name, "description": "", "base_url": server, "timeout_ms": 15000, "steps": steps}
    (profiles / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def open_profile(page, url):
    connect(page, url)
    page.click("#profile-list button")


def step_field(page, index, field):
    """field: 0 = Selektor, 1 = Wert"""
    return page.locator("#steps .step").nth(index).locator("input").nth(field).input_value()


LOGIN_STEPS = [
    {"op": "goto", "value": "/"},
    {"op": "fill", "selector": "#user", "value": "${SWITCHER_USER}"},
    {"op": "fill", "selector": 'input[name="pwd"]', "value": "${SWITCHER_PASSWORD}"},
    {"op": "click", "selector": "#login"},
]


def test_stopmarke_spielt_bis_zur_marke_ab_und_zeichnet_dahinter_weiter(live, server, page):
    url, profiles = live
    write_profile(profiles, server, [
        {"op": "goto", "value": "/"},
        {"op": "click", "selector": "#login"},
        {"op": "check", "selector": "#enabled"},
        {"op": "click", "selector": 'role=button[name="Übernehmen"]'},
        {"op": "expect_text", "selector": "#status", "value": "gespeichert"},
    ])
    open_profile(page, url)
    wait_steps(page, 5)

    # Marke nach Schritt 3 setzen, wieder entfernen, wieder setzen
    flag = page.locator("#steps .step").nth(2).locator(".flag")
    flag.click()
    expect(page.locator("#steps .marker-line")).to_have_count(1)
    expect(flag).to_have_attribute("aria-pressed", "true")
    flag.click()
    expect(page.locator("#steps .marker-line")).to_have_count(0)
    flag.click()
    expect(page.locator("#steps .marker-line")).to_have_count(1)

    page.click("#rec-start")
    expect(page.locator("#rec-note")).to_contain_text("Wiedergabe beendet")
    expect(page.locator("#rec-replay")).to_be_hidden()
    wait_steps(page, 5)  # Abspielen zeichnet nichts auf, auch kein zusätzliches goto

    # Der Link "Hilfe" ist nur sichtbar, wenn die Wiedergabe den Login geklickt hat
    live_click(page, 40, 292)
    wait_steps(page, 6)
    assert [step_field(page, i, 0) for i in range(6)] == [
        "", "#login", "#enabled", 'role=link[name="Hilfe"]', 'role=button[name="Übernehmen"]', "#status",
    ]  # der neue Schritt steht hinter der Marke, die alten Folgeschritte bleiben

    page.click("#rec-stop")
    expect(page.locator("#rec-live")).to_be_hidden()
    expect(page.locator("#steps .marker-line")).to_have_count(0)  # die Marke gehörte zu dieser Aufnahme
    wait_steps(page, 6)


def test_stopmarke_haelt_bei_login_schritten_an_und_zeichnet_das_tippen_nicht_auf(live, server, page):
    url, profiles = live
    write_profile(profiles, server, LOGIN_STEPS)
    open_profile(page, url)
    wait_steps(page, 4)
    page.locator("#steps .step").nth(3).locator(".flag").click()  # Marke nach dem Login-Klick
    page.click("#rec-start")

    expect(page.locator("#rec-replay")).to_contain_text("Zugangsdaten")
    expect(page.locator("#rp-resume")).to_have_text("Erledigt, weiter")
    page.fill("#rec-text", "alice")
    page.click("#rec-text-form button[type=submit]")
    page.click("#rp-resume")
    expect(page.locator("#rec-replay")).to_contain_text("Schritt 3")
    page.fill("#rec-text", "geheim-pw-123")
    page.click("#rec-text-form button[type=submit]")
    page.click("#rp-resume")
    expect(page.locator("#rec-note")).to_contain_text("Wiedergabe beendet")
    wait_steps(page, 4)  # das eigene Tippen wurde nicht als Schritt aufgezeichnet

    live_click(page, 30, 210)  # Freigabe aktivieren, nur nach dem Login (Klick wurde abgespielt) möglich
    wait_steps(page, 5)
    values = [step_field(page, i, 1) for i in range(5)]
    assert values[1:3] == ["${SWITCHER_USER}", "${SWITCHER_PASSWORD}"]
    assert "alice" not in values and "geheim-pw-123" not in values
    assert page.locator("#steps .step").nth(4).locator("select").input_value() == "check"


def test_hier_aufzeichnen_beendet_die_wiedergabe_und_fuegt_dort_ein(live, server, page):
    url, profiles = live
    write_profile(profiles, server, LOGIN_STEPS)
    open_profile(page, url)
    wait_steps(page, 4)
    page.locator("#steps .step").nth(3).locator(".flag").click()
    page.click("#rec-start")
    expect(page.locator("#rec-replay")).to_contain_text("Zugangsdaten")  # hält vor Schritt 2

    page.click("#rp-stop")
    expect(page.locator("#rec-note")).to_contain_text("hinter Schritt 1")
    expect(page.locator("#rec-replay")).to_be_hidden()
    live_click(page, 80, 135)  # Anmelden
    wait_steps(page, 5)
    assert [step_field(page, i, 0) for i in range(5)] == [
        "", "#login", "#user", 'input[name="pwd"]', "#login",
    ]  # hinter Schritt 1 eingefügt, der Rest blieb stehen


def test_stopmarke_entfaellt_mit_dem_schritt(live, server, page):
    url, profiles = live
    write_profile(profiles, server, LOGIN_STEPS)
    open_profile(page, url)
    wait_steps(page, 4)
    page.locator("#steps .step").nth(2).locator(".flag").click()
    expect(page.locator("#steps .marker-line")).to_have_count(1)
    page.locator("#steps .step").nth(2).get_by_role("button").last.click()  # Schritt entfernen
    wait_steps(page, 3)
    expect(page.locator("#steps .marker-line")).to_have_count(0)


def test_aufnahme_ohne_marke_verhaelt_sich_wie_vorher(live, server, page):
    url, profiles = live
    write_profile(profiles, server, LOGIN_STEPS[:1])
    open_profile(page, url)
    wait_steps(page, 1)
    page.click("#rec-start")
    expect(page.locator("#rec-live")).to_be_visible()
    expect(page.locator("#rec-replay")).to_be_hidden()
    wait_steps(page, 1)
    live_click(page, 80, 135)
    wait_steps(page, 2)  # am Ende angehängt
    assert page.locator("#steps .step").nth(1).locator("select").input_value() == "click"


# ---------- Selektor-Vorschlag ----------


def test_suggest_stable_selector_for_fragile_step(live, server, page):
    url, profiles = live
    write_profile(profiles, server, [{"op": "goto", "value": "/"}, {"op": "click", "selector": "#btn48151623"}])
    connect(page, url)
    page.click("#profile-list button")
    step = page.locator("#steps .step").nth(1)
    expect(step.locator(".pill.q-bad")).to_have_text("fragil · generierte ID")

    # Ohne Live-Browser: Hinweis statt Vorschlag
    step.get_by_role("button", name="Stabileren Selektor vorschlagen").click()
    expect(step.locator(".suggest")).to_contain_text("Live-Browser")
    step.get_by_role("button", name="Vorschläge schließen").click()
    expect(step.locator(".suggest")).to_have_count(0)

    # Mit Live-Browser: Vorschläge treffen genau dieses Element, Übernehmen ersetzt den Selektor
    page.click("#rec-start")
    expect(page.locator("#rec-live")).to_be_visible()
    step = page.locator("#steps .step").nth(1)
    step.get_by_role("button", name="Stabileren Selektor vorschlagen").click()
    option = step.locator(".suggest-option", has_text='role=button[name="Weiter"]')
    expect(option).to_be_visible()
    expect(option.locator(".pill")).to_have_text("stabil · Text oder Rolle")
    option.click()
    expect(step.locator('input[aria-label="Selektor"]')).to_have_value('role=button[name="Weiter"]')
    expect(step.get_by_role("button", name="Stabileren Selektor vorschlagen")).to_have_count(0)  # nicht mehr fragil
    page.click("#rec-stop")


def test_suggest_reports_selector_that_does_not_match(live, server, page):
    url, profiles = live
    write_profile(profiles, server, [{"op": "goto", "value": "/"}, {"op": "click", "selector": "#gibt-es-nicht2024"}])
    connect(page, url)
    page.click("#profile-list button")
    page.click("#rec-start")
    expect(page.locator("#rec-live")).to_be_visible()
    step = page.locator("#steps .step").nth(1)
    step.get_by_role("button", name="Stabileren Selektor vorschlagen").click()
    expect(step.locator(".suggest")).to_contain_text("nicht vor")
    page.click("#rec-stop")


# ---------- Beschriftung des Aufnahme-Knopfs ----------


def test_record_button_says_what_it_does_for_existing_profile(live, server, page):
    url, profiles = live
    write_profile(profiles, server, [{"op": "goto", "value": "/"}, {"op": "click", "selector": "#ok"}, {"op": "click", "selector": "#b"}])
    connect(page, url)
    # Übersicht: die Karte eines Profils mit Schritten verspricht kein „Aufnehmen von vorn“
    expect(page.locator(".pcard-actions .rec-btn")).to_have_text("Schritte anhängen")
    page.click("#profile-list button")
    expect(page.locator("#rec-start")).to_have_text("Schritte anhängen")
    expect(page.locator("#rec-mode")).to_contain_text("3 Schritte")
    page.locator("#steps .step").nth(1).locator(".flag").click()
    expect(page.locator("#rec-start")).to_have_text("Ab Stopmarke aufnehmen")
    expect(page.locator("#rec-mode")).to_contain_text("ersten 2 Schritte")
    page.locator("#steps .step").nth(1).locator(".flag").click()
    expect(page.locator("#rec-start")).to_have_text("Schritte anhängen")
    page.click("#new-profile")
    expect(page.locator("#rec-start")).to_have_text("Aufnahme starten")
