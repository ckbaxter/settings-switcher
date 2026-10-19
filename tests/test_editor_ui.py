"""Bedient den Editor im echten Browser: Token, Anlegen, Speichern, XSS-Check, CSP."""

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from editor.app import create_app

TOKEN = "u" * 24


@pytest.fixture
def live(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(tmp_path, TOKEN, ["127.0.0.1"])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", tmp_path
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context()
        pg = ctx.new_page()
        pg.set_default_timeout(5000)
        pg.console_errors = []
        pg.on("console", lambda m: pg.console_errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: pg.console_errors.append(str(e)))
        yield pg
        browser.close()


def test_wrong_token_shows_error(live, page):
    url, _ = live
    page.goto(url)
    page.fill("#token", "falsch")
    page.click("text=Verbinden")
    page.wait_for_selector(".msg.error")
    assert "Token ungültig" in page.inner_text("#messages")
    assert page.is_disabled("#new-profile")


def test_create_save_reload_and_open(live, page):
    url, profiles = live
    page.goto(url)
    page.fill("#token", TOKEN)
    page.click("text=Verbinden")
    expect(page.locator("#new-profile")).to_be_enabled()

    page.click("#new-profile")
    page.fill("#f-name", "ui-test")
    page.fill("#f-desc", "per UI angelegt")
    page.fill("#f-base", "http://192.168.178.1")
    page.click("#add-step")
    step = page.locator(".step").nth(1)
    step.locator("select").select_option("click")
    step.locator('input[aria-label="Selektor"]').fill("#ok")
    step.locator('input[aria-label="Notiz"]').fill("Button")

    page.click("#validate")
    page.wait_for_selector(".msg.ok")
    page.click("#save")
    expect(page.locator("#messages")).to_contain_text("Gespeichert")

    saved = json.loads((profiles / "ui-test.json").read_text(encoding="utf-8"))
    assert saved["steps"] == [
        {"op": "goto", "value": "/"},
        {"op": "click", "selector": "#ok", "comment": "Button"},
    ]
    assert saved["timeout_ms"] == 15000

    page.reload()  # Token liegt in sessionStorage, Liste lädt automatisch
    page.wait_for_selector("#profile-list button")
    page.click("#profile-list button")
    page.wait_for_selector(".step")
    assert page.locator(".step").count() == 2
    assert page.input_value("#f-name") == "ui-test"
    assert page.is_visible("#delete")
    assert page.console_errors == []


def test_invalid_save_shows_server_errors(live, page):
    url, profiles = live
    page.goto(url)
    page.fill("#token", TOKEN)
    page.click("text=Verbinden")
    expect(page.locator("#new-profile")).to_be_enabled()
    page.click("#new-profile")
    page.fill("#f-name", "kaputt")
    page.fill("#f-base", "keine-url")
    page.click("#save")
    page.wait_for_selector(".msg.error")
    assert "base_url" in page.inner_text("#messages")
    assert not (profiles / "kaputt.json").exists()


def test_profile_text_is_never_rendered_as_html(live, page):
    url, _ = live
    evil = "<img src=x onerror=\"document.title='gehackt'\">"
    profile = {
        "name": "xss",
        "description": evil,
        "base_url": "http://192.168.178.1",
        "steps": [{"op": "click", "selector": evil, "comment": evil}],
    }
    res = httpx.put(f"{url}/api/profiles/xss", headers={"X-Token": TOKEN}, json=profile)
    assert res.status_code == 200

    page.goto(url)
    page.fill("#token", TOKEN)
    page.click("text=Verbinden")
    page.wait_for_selector("#profile-list button")
    page.click("#profile-list button")
    page.wait_for_selector(".step")
    page.wait_for_timeout(300)
    assert page.title() == "Settings Switcher"
    assert page.locator("#profile-list img, #steps img").count() == 0
    assert "<img" in page.inner_text("#profile-list")
    assert page.input_value('.step input[aria-label="Selektor"]') == evil


def test_delete_via_ui(live, page):
    url, profiles = live
    profile = {"name": "weg", "base_url": "http://192.168.178.1", "steps": [{"op": "goto", "value": "/"}]}
    httpx.put(f"{url}/api/profiles/weg", headers={"X-Token": TOKEN}, json=profile)
    page.on("dialog", lambda d: d.accept())
    page.goto(url)
    page.fill("#token", TOKEN)
    page.click("text=Verbinden")
    page.wait_for_selector("#profile-list button")
    page.click("#profile-list button")
    page.click("#delete")
    expect(page.locator("#profile-list button")).to_have_count(0)
    assert not (profiles / "weg.json").exists()
