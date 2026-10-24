import asyncio
import json
import os
import subprocess
import sys

import pytest

from editor.recorder import Recorder, RecorderError, display_url, selector_candidates

def drain(session):
    events = []
    while not session.events.empty():
        events.append(session.events.get_nowait())
    return events


def steps_of(events):
    return [e["step"] for e in events if e["t"] == "step"]


def run_session(base, scenario, **kwargs):
    async def main():
        rec = Recorder({"127.0.0.1"}, max_seconds=60, idle_seconds=60, **kwargs)
        await rec.start(base, "/")
        try:
            return await scenario(rec.session)
        finally:
            await rec.stop()

    return asyncio.run(main())


async def click(s, x, y, **extra):
    await s.handle({"t": "click", "x": x, "y": y, **extra})


# ---------- reine Logik ----------


def info(**kw):
    base = dict(tag="button", type="", id="", name="", testid="", aria="", role="", title="", hasHref=False,
                value="", text="", labels=[], isCheck=False, cssPath="body > button")
    base.update(kw)
    return base


def test_candidates_prefer_stable_id_then_role_then_name_then_text_then_css():
    c = selector_candidates(info(id="btn_save", text="Speichern", name="s"))
    assert c == ["#btn_save", 'role=button[name="Speichern"]', 'button[name="s"]', 'text="Speichern"', "body > button"]


def test_unstable_ids_and_unsafe_text_are_skipped():
    c = selector_candidates(info(id="uid_123456", text='Sag "Hallo"'))
    assert c[0] == "body > button" or not any(x.startswith("#") for x in c)
    assert not any(x.startswith("#") for x in c)
    assert not any("Hallo" in x for x in c)
    assert c[-1] == "body > button"


def test_display_url_hides_query():
    assert display_url("http://192.168.178.1/index.lua?sid=abcdef") == "http://192.168.178.1/index.lua"


# ---------- Sitzung gegen echten Chromium ----------


def test_start_checks_host_and_path():
    async def main():
        rec = Recorder({"192.168.178.1"})
        with pytest.raises(RecorderError):
            await rec.start("http://evil.example", "/")
        with pytest.raises(RecorderError):
            await rec.start("http://192.168.178.1", "//evil.example")

    asyncio.run(main())


def test_recorder_requires_allowed_hosts():
    with pytest.raises(RuntimeError):
        Recorder(set())


def test_only_one_session(server):
    async def main():
        rec = Recorder({"127.0.0.1"})
        await rec.start(server, "/")
        try:
            with pytest.raises(RecorderError) as exc:
                await rec.start(server, "/")
            assert exc.value.status == 409
        finally:
            await rec.stop()

    asyncio.run(main())


def test_login_flow_records_steps_without_secrets(server):
    async def scenario(s):
        await click(s, 170, 35)  # Benutzerfeld: nur Fokus, kein Schritt
        await s.handle({"t": "fill", "text": "alice", "as": "auto"})
        await click(s, 170, 85)  # Passwortfeld
        await s.handle({"t": "fill", "text": "super-geheim", "as": "auto"})
        await click(s, 80, 135)  # Anmelden
        return drain(s)

    events = run_session(server, scenario)
    assert steps_of(events) == [
        {"op": "fill", "selector": "#user", "value": "TODO: Wert setzen", "comment": "input: user"},
        {"op": "fill", "selector": 'input[name="pwd"]', "value": "${SWITCHER_PASSWORD}", "comment": "input: pwd"},
        {"op": "click", "selector": "#login", "comment": "button: Anmelden"},
    ]
    dump = json.dumps(events)
    assert "super-geheim" not in dump and "alice" not in dump
    assert any(e["t"] == "blocked" and e["host"] == "10.255.255.1" for e in events)


def test_fill_modes(server):
    async def scenario(s):
        await click(s, 170, 35)
        await s.handle({"t": "fill", "text": "alice", "as": "user"})
        await s.handle({"t": "fill", "text": "alice", "as": "literal"})
        await click(s, 170, 85)
        await s.handle({"t": "fill", "text": "pw", "as": "literal"})  # Passwort nie im Klartext
        await s.handle({"t": "fill", "text": "pw", "as": "password"})
        return drain(s)

    events = run_session(server, scenario)
    values = [st["value"] for st in steps_of(events)]
    assert values == ["${SWITCHER_USER}", "alice", "${SWITCHER_PASSWORD}"]
    assert any(e["t"] == "error" and "Klartext" in e["message"] for e in events)


def test_fill_without_focus_is_an_error(server):
    async def scenario(s):
        await s.handle({"t": "fill", "text": "x"})
        return drain(s)

    events = run_session(server, scenario)
    assert steps_of(events) == []
    assert any(e["t"] == "error" for e in events)


def test_panel_controls(server):
    async def scenario(s):
        await click(s, 80, 135)  # Anmelden -> Panel sichtbar
        drain(s)
        await click(s, 30, 210)  # Checkbox an
        await click(s, 30, 210)  # Checkbox aus
        await click(s, 60, 250)  # Label einer versteckten Checkbox
        await click(s, 40, 292)  # Link
        await click(s, 260, 215)  # Übernehmen
        await click(s, 50, 375)  # erstes OK
        await click(s, 50, 415)  # zweites OK
        await s.handle({"t": "key", "key": "Enter"})
        return drain(s)

    steps = steps_of(run_session(server, scenario))
    ops = [(st["op"], st["selector"]) for st in steps]
    assert ops[0] == ("check", "#enabled")
    assert ops[1] == ("uncheck", "#enabled")
    assert ops[2][0] == "check" and "Versteckt" in ops[2][1]
    assert ops[3] == ("click", 'role=link[name="Hilfe"]')
    assert ops[4] == ("click", 'role=button[name="Übernehmen"]')
    ok1, ok2 = ops[5][1], ops[6][1]
    assert ok1 != ok2 and "nth-of-type" in ok1 + ok2  # gleiche Beschriftung: CSS-Pfad
    # Der zuletzt angeklickte Button hat den Fokus, die Taste geht an ihn
    assert steps[7] == {"op": "press", "selector": ok2, "value": "Enter"}


def test_select_box_offers_options_and_records_choice(server):
    async def scenario(s):
        await click(s, 80, 135)
        drain(s)
        await click(s, 60, 335)
        offered = [e for e in drain(s) if e["t"] == "select"]
        await s.handle({"t": "select", "selector": offered[0]["selector"], "value": "b"})
        return offered, drain(s)

    offered, events = run_session(server, scenario)
    assert offered[0]["selector"] == "#mode"
    assert [o["value"] for o in offered[0]["options"]] == ["a", "b"]
    assert steps_of(events) == [{"op": "select_option", "selector": "#mode", "value": "b"}]


def test_pick_checks(server):
    async def scenario(s):
        await click(s, 80, 135)
        await click(s, 260, 215)  # Übernehmen setzt Status
        drain(s)
        await click(s, 250, 250, pick="expect_text")
        await click(s, 30, 210, pick="expect_unchecked")
        await click(s, 250, 250, pick="expect_checked")  # kein Kontrollkästchen
        await click(s, 250, 250, pick="evaluate")  # unbekannt
        await click(s, 250, 250, pick="expect_visible")
        return drain(s)

    events = run_session(server, scenario)
    assert steps_of(events) == [
        {"op": "expect_text", "selector": "#status", "value": "gespeichert", "comment": "span: gespeichert"},
        {"op": "expect_unchecked", "selector": "#enabled", "comment": "input: enabled"},
        {"op": "expect_visible", "selector": "#status", "comment": "span: gespeichert"},
    ]
    assert len([e for e in events if e["t"] == "error"]) == 2


def test_pick_conditions(server):
    async def scenario(s):
        await click(s, 80, 135)
        await click(s, 260, 215)  # Übernehmen setzt Status
        drain(s)
        await click(s, 250, 250, pick="if_text")
        await click(s, 260, 215, pick="if_visible")
        await click(s, 3005, 3005, pick="if_text")  # kein Element im sichtbaren Bild
        return drain(s)

    events = run_session(server, scenario)
    ops = [(st["op"], st.get("selector"), st.get("value")) for st in steps_of(events)]
    assert ops == [
        ("if_text", "#status", "gespeichert"),
        ("if_visible", 'role=button[name="Übernehmen"]', None),
    ]


def test_invalid_input_is_rejected(server):
    async def scenario(s):
        await s.handle({"t": "click", "x": -1, "y": 5})
        await s.handle({"t": "click", "x": 5000, "y": 5})
        await s.handle({"t": "click", "x": "a", "y": 5})
        await s.handle({"t": "key", "key": "F12"})
        await s.handle({"t": "select", "selector": "", "value": "x"})
        await s.handle({"t": "unbekannt"})
        return drain(s)

    events = run_session(server, scenario)
    assert steps_of(events) == []
    assert len([e for e in events if e["t"] == "error"]) == 5


def test_idle_timeout_stops_session(server):
    async def main():
        rec = Recorder({"127.0.0.1"}, max_seconds=60, idle_seconds=1)
        await rec.start(server, "/")
        session = rec.session
        for _ in range(60):
            await asyncio.sleep(0.2)
            if rec.session is None:
                break
        assert rec.session is None
        events = drain(session)
        assert any(e["t"] == "closed" and "Inaktivität" in e["reason"] for e in events)

    asyncio.run(main())


def test_navigation_to_foreign_host_is_blocked(server):
    async def scenario(s):
        with pytest.raises(Exception):
            await s.page.goto("http://example.org/")
        return s.page.url

    url = run_session(server, scenario)
    assert "example.org" not in url


def test_recorded_selectors_replay_in_runner(server, tmp_path):
    """Alle aufgezeichneten Selektor-Arten funktionieren auch beim Abspielen im Runner."""

    async def scenario(s):
        await click(s, 170, 35)
        await s.handle({"t": "fill", "text": "alice", "as": "user"})
        await click(s, 170, 85)
        await s.handle({"t": "fill", "text": "pw", "as": "auto"})
        await click(s, 80, 135)  # Anmelden
        await click(s, 30, 210)  # Checkbox an
        await click(s, 60, 250)  # Label einer versteckten Checkbox
        await click(s, 40, 292)  # Link
        await click(s, 60, 335)  # Auswahlliste
        collected = drain(s)
        offered = [e for e in collected if e["t"] == "select"][0]
        await s.handle({"t": "select", "selector": offered["selector"], "value": "b"})
        await click(s, 260, 215)  # Übernehmen
        await click(s, 50, 375)  # erstes OK
        await click(s, 50, 415)  # zweites OK
        await click(s, 250, 250, pick="expect_text")
        await click(s, 30, 210, pick="expect_checked")
        await click(s, 60, 250, pick="expect_checked")
        return collected + drain(s)

    steps = steps_of(run_session(server, scenario))
    assert [s["op"] for s in steps].count("select_option") == 1
    profile = {
        "name": "replay",
        "base_url": server,
        "timeout_ms": 3000,
        "steps": [{"op": "goto", "value": "/"}] + [{k: v for k, v in s.items() if k != "comment"} for s in steps],
    }
    pdir = tmp_path / "profiles"
    pdir.mkdir()
    (pdir / "replay.json").write_text(json.dumps(profile), encoding="utf-8")
    (tmp_path / "artifacts").mkdir()
    result = subprocess.run(
        [sys.executable, "runner/runner.py", "replay"],
        env={
            **os.environ,
            "PYTHONPATH": ".",
            "SWITCHER_PROFILES_DIR": str(pdir),
            "SWITCHER_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
            "SWITCHER_ALLOWED_HOSTS": "127.0.0.1",
            "SWITCHER_USER": "alice",
            "SWITCHER_PASSWORD": "pw",
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------- Scrollen (Mausrad, Wischen, Pfeilknöpfe) ----------


async def scroll_pos(s, expected=None):
    """Mausrad-Scrollen ist asynchron: kurz warten, bis die erwartete Position erreicht ist."""
    pos = None
    for _ in range(40):
        pos = await s.page.evaluate("[Math.round(scrollX), Math.round(scrollY)]")
        if expected is None or pos == expected:
            break
        await asyncio.sleep(0.05)
    return pos


def test_scroll_moves_page_in_both_directions_without_recording_steps(server):
    async def scenario(s):
        drain(s)
        await s.handle({"t": "scroll", "dx": 0, "dy": 400})
        down = await scroll_pos(s, [0, 400])
        await s.handle({"t": "scroll", "dx": 300, "dy": 0})
        right = await scroll_pos(s, [300, 400])
        await s.handle({"t": "scroll", "dx": -100, "dy": -100, "x": 200, "y": 200})
        back = await scroll_pos(s, [200, 300])
        return down, right, back, drain(s)

    down, right, back, events = run_session(server, scenario)
    assert down == [0, 400]
    assert right == [300, 400]
    assert back == [200, 300]
    assert steps_of(events) == [] and not [e for e in events if e["t"] == "error"]


def test_scroll_values_are_clamped_and_validated(server):
    async def scenario(s):
        drain(s)
        await s.handle({"t": "scroll", "dx": 0, "dy": 10**9})
        clamped = await scroll_pos(s, [0, 2000])
        ok_events = drain(s)
        for bad in (
            {"dx": "5"},
            {"dy": True},
            {"dy": float("nan")},
            {"dy": 10, "x": -1, "y": 10},
            {"dy": 10, "x": 10, "y": 99999},
            {"dy": 10, "x": 10},
        ):
            await s.handle({"t": "scroll", **bad})
        return clamped, ok_events, drain(s), await scroll_pos(s)

    clamped, ok_events, bad_events, final = run_session(server, scenario)
    assert clamped == [0, 2000]
    assert ok_events == []
    assert [e["t"] for e in bad_events] == ["error"] * 6
    assert final == [0, 2000]  # ungültige Angaben scrollen nichts


def test_stable_alternatives_skip_current_and_css_path():
    from editor.recorder import selector_candidates, stable_alternatives

    info = {
        "tag": "button", "type": "", "id": "btn48151623", "name": "", "testid": "", "aria": "", "role": "",
        "title": "", "hasHref": False, "value": "", "text": "Weiter", "labels": [], "isCheck": False,
        "cssPath": "body > button",
    }
    assert selector_candidates(info)[-1] == "body > button"
    alternatives = stable_alternatives(info, "#btn48151623")
    assert 'role=button[name="Weiter"]' in alternatives and 'text="Weiter"' in alternatives
    assert "body > button" not in alternatives and "#btn48151623" not in alternatives
    assert 'text="Weiter"' not in stable_alternatives(info, ' text="Weiter" ')
