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
        ("fill", "#user", "${SS_USER}"),
        ("fill", 'input[name="pwd"]', "${SS_PASSWORD}"),
        ("click", "#login", None),
        ("check", "#enabled", None),
        ("click", 'role=button[name="Übernehmen"]', None),
        ("expect_text", "#status", "gespeichert"),
        ("expect_checked", "#enabled", None),
    ]

    # Das aufgezeichnete Profil läuft im echten Runner durch
    (tmp_path / "artifacts").mkdir()
    env = {
        "SS_PROFILES_DIR": str(profiles),
        "SS_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
        "SS_ALLOWED_HOSTS": "127.0.0.1",
        "SS_USER": "alice",
        "SS_PASSWORD": "super-geheim",
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
    expect(page.locator("#messages")).to_contain_text("SS_ALLOWED_HOSTS")
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
