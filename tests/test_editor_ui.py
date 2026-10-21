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
    page.click("#add-step-end")
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


def test_overview_shows_cards_and_opens_profile(live, page):
    url, profiles = live
    good = {"name": "fertig", "description": "Alles da", "base_url": "http://192.168.178.1",
            "steps": [{"op": "goto", "value": "/"}, {"op": "expect_visible", "selector": "#ok"}]}
    todo = {"name": "offen", "description": "", "base_url": "http://192.168.178.1",
            "steps": [{"op": "click", "selector": "TODO: Button"}]}
    for data in (good, todo):
        assert httpx.put(f"{url}/api/profiles/{data['name']}", headers={"X-Token": TOKEN}, json=data).status_code == 200
    page.goto(url)
    page.fill("#token", TOKEN)
    page.click("text=Verbinden")
    expect(page.locator("#overview")).to_be_visible()
    expect(page.locator("#editor")).to_be_hidden()
    expect(page.locator("#overview-sub")).to_contain_text("2 Profile")
    cards = page.locator(".pcard:not(.pcard-new)")
    expect(cards).to_have_count(2)
    fertig = cards.filter(has_text="fertig")
    expect(fertig.locator(".badge")).to_have_text("Bereit")
    expect(fertig).to_contain_text("2 Schritte")
    expect(fertig).to_contain_text("Prüft Ergebnis")
    offen = cards.filter(has_text="offen")
    expect(offen.locator(".badge")).to_have_text("TODO offen")
    expect(offen).to_contain_text("Keine Prüfung")
    expect(offen).to_contain_text("Keine Beschreibung")
    expect(page.get_by_role("button", name="Aufnehmen")).to_have_count(0)  # ohne Recorder kein Aufnahme-Knopf

    fertig.get_by_role("button", name="Bearbeiten").click()
    expect(page.locator("#editor")).to_be_visible()
    expect(page.locator("#overview")).to_be_hidden()
    assert page.input_value("#f-name") == "fertig"
    page.click("#to-overview")
    expect(page.locator("#overview")).to_be_visible()
    page.locator(".pcard-new").click()
    expect(page.locator("#editor-title")).to_have_text("Neues Profil")


def test_theme_toggle_cycles_and_is_remembered(live, page):
    url, _ = live
    page.goto(url)
    root = page.locator("html")
    toggle = page.locator("#theme-toggle")
    expect(root).not_to_have_attribute("data-theme", "light")  # automatisch: nichts gesetzt
    assert page.evaluate("document.documentElement.hasAttribute('data-theme')") is False
    toggle.click()
    expect(root).to_have_attribute("data-theme", "light")
    page.reload()  # bleibt nach dem Neuladen, ohne Aufblitzen (Skript im head)
    expect(root).to_have_attribute("data-theme", "light")
    toggle.click()
    expect(root).to_have_attribute("data-theme", "dark")
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(14, 17, 22)"
    toggle.click()
    assert page.evaluate("document.documentElement.hasAttribute('data-theme')") is False
    assert page.evaluate("localStorage.getItem('ss-theme')") is None


def test_add_step_at_start_and_at_end(live, page):
    url, _ = live
    page.goto(url)
    page.fill("#token", TOKEN)
    page.click("text=Verbinden")
    expect(page.locator("#new-profile")).to_be_enabled()
    page.click("#new-profile")  # beginnt mit einem goto
    page.click("#add-step")  # oben: ganz an den Anfang
    page.locator(".step").nth(0).locator("select").select_option("press")
    page.click("#add-step-end")  # unten: ans Ende
    page.locator(".step").nth(2).locator("select").select_option("check")
    ops = [page.locator(".step").nth(i).locator("select").input_value() for i in range(3)]
    assert ops == ["press", "goto", "check"]


def test_unsaved_changes_are_warned_before_switching(live, page):
    url, _ = live
    for name in ("eins", "zwei"):
        profile = {"name": name, "description": name, "base_url": "http://192.168.178.1", "steps": [{"op": "goto", "value": "/"}]}
        assert httpx.put(f"{url}/api/profiles/{name}", headers={"X-Token": TOKEN}, json=profile).status_code == 200
    asked = []
    answer = {"accept": False}

    def on_dialog(dialog):
        asked.append(dialog.message)
        dialog.accept() if answer["accept"] else dialog.dismiss()

    page.on("dialog", on_dialog)
    page.goto(url)
    page.fill("#token", TOKEN)
    page.click("text=Verbinden")
    page.locator("#profile-list button", has_text="eins").click()
    expect(page.locator("#editor-title")).to_have_text("Profil: eins")
    expect(page.locator("#dirty-pill")).to_be_hidden()

    # Ohne Änderung wechselt man ohne Rückfrage
    page.locator("#profile-list button", has_text="zwei").click()
    expect(page.locator("#editor-title")).to_have_text("Profil: zwei")
    assert asked == []

    probe = "() => { const e = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented; }"
    assert page.evaluate(probe) is False  # ohne Änderung kein Hinweis beim Schließen des Tabs

    # Änderung: Hinweis erscheint, Wechsel fragt nach und bleibt bei "Abbrechen" im aktuellen Profil
    page.fill("#f-desc", "geändert")
    expect(page.locator("#dirty-pill")).to_be_visible()
    assert page.evaluate(probe) is True  # Tab schließen oder neu laden: der Browser fragt nach
    for trigger in (
        lambda: page.locator("#profile-list button", has_text="eins").click(),
        lambda: page.click("#new-profile"),
        lambda: page.click("#to-overview"),
    ):
        trigger()
    assert len(asked) == 3 and "ungespeicherte" in asked[0]
    expect(page.locator("#editor-title")).to_have_text("Profil: zwei")
    assert page.input_value("#f-desc") == "geändert"

    # Zurücksetzen auf den alten Wert zählt nicht als Änderung
    page.fill("#f-desc", "zwei")
    expect(page.locator("#dirty-pill")).to_be_hidden()

    # Nach dem Speichern keine Rückfrage mehr
    page.fill("#f-desc", "gespeichert")
    page.click("#save")
    expect(page.locator("#messages")).to_contain_text("Gespeichert")
    expect(page.locator("#dirty-pill")).to_be_hidden()
    asked.clear()
    page.locator("#profile-list button", has_text="eins").click()
    expect(page.locator("#editor-title")).to_have_text("Profil: eins")
    assert asked == []

    # Bei "OK" wird verworfen und gewechselt
    page.fill("#f-desc", "weg damit")
    answer["accept"] = True
    page.locator("#profile-list button", has_text="zwei").click()
    expect(page.locator("#editor-title")).to_have_text("Profil: zwei")
    assert page.input_value("#f-desc") == "gespeichert"
    assert len(asked) == 1
