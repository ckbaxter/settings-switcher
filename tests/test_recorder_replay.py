"""Stopmarke: Schritte bis zur Marke werden im Recorder abgespielt, danach wird weiter aufgezeichnet."""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from editor.app import create_app
from editor.recorder import Recorder, RecorderError, replay_block_reason, replay_label

TOKEN = "p" * 24
H = {"X-Token": TOKEN}

LOGIN = [
    {"op": "goto", "value": "/"},
    {"op": "fill", "selector": "#user", "value": "${SWITCHER_USER}"},
    {"op": "fill", "selector": 'input[name="pwd"]', "value": "${SWITCHER_PASSWORD}"},
    {"op": "click", "selector": "#login"},
]


# ---------- Hilfen ----------


async def wait_event(s, kind, seen, timeout=20):
    """Wartet auf das nächste Ereignis dieser Art und sammelt alle bis dahin in seen."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        while not s.events.empty():
            event = s.events.get_nowait()
            seen.append(event)
            if event["t"] == kind:
                return event
        await asyncio.sleep(0.05)
    raise AssertionError(f"Kein Ereignis {kind!r} innerhalb von {timeout}s, gesehen: {seen}")


async def wait_running_step(s, index, seen):
    """Wartet, bis der Schritt mit dieser Nummer gerade abgespielt wird."""
    while True:
        event = await wait_event(s, "replay", seen)
        if event["index"] == index:
            return event


def run_replay(base, replay, scenario, page_timeout_ms=None):
    async def main():
        rec = Recorder({"127.0.0.1"}, max_seconds=90, idle_seconds=90)
        result = await rec.start(base, "/", replay)
        assert result["replay"] == {"total": len(replay)} and "step" not in result
        s = rec.session
        if page_timeout_ms:
            s.page.set_default_timeout(page_timeout_ms)
        s.begin_replay()
        try:
            return await scenario(s)
        finally:
            await rec.stop()

    return asyncio.run(main())


def steps_of(events):
    return [e["step"] for e in events if e["t"] == "step"]


def drain_all(s):
    events = []
    while not s.events.empty():
        events.append(s.events.get_nowait())
    return events


# ---------- reine Logik und Prüfung (ohne Browser) ----------


def test_block_reason_for_credentials_and_todo():
    assert "Zugangsdaten" in replay_block_reason({"op": "fill", "selector": "#a", "value": "${SWITCHER_PASSWORD}"})
    assert "Zugangsdaten" in replay_block_reason({"op": "fill", "selector": "#a", "value": "x${SWITCHER_USER}"})
    assert "TODO" in replay_block_reason({"op": "fill", "selector": "#a", "value": "TODO: Wert setzen"})
    assert "TODO" in replay_block_reason({"op": "click", "selector": "todo selector"})
    assert replay_block_reason({"op": "fill", "selector": "#a", "value": "fester Text"}) is None
    assert replay_block_reason({"op": "click", "selector": "#a"}) is None


def test_label_never_contains_the_fill_value():
    assert replay_label({"op": "fill", "selector": "#a", "value": "geheim"}) == "fill #a"
    assert replay_label({"op": "goto", "value": "/x"}) == "goto /x"


@pytest.mark.parametrize(
    "replay",
    [
        [{"op": "if_visible", "selector": "#a"}, {"op": "click", "selector": "#a"}],  # Block nicht geschlossen (Stopmarke im Block)
        [{"op": "else"}],
        [],
        "nicht-liste",
        [{"op": "eval", "value": "alert(1)"}],  # kein freies JavaScript
        [{"op": "click", "selector": "#a", "value": "${SWITCHER_PASSWORD}"}],  # Variablen nur bei fill
        [{"op": "goto", "value": "http://evil.example/"}],  # anderer Host
        [{"op": "goto", "value": "//evil.example"}],
        [{"op": "fill", "selector": "#a", "value": "${HOME}"}],  # nur SWITCHER_...
        ["kein-objekt"],
        [{"op": "click"}],  # Pflichtfeld fehlt
    ],
)
def test_start_rejects_bad_replay_before_any_browser(replay):
    async def main():
        rec = Recorder({"127.0.0.1"})
        with pytest.raises(RecorderError) as exc:
            await rec.start("http://127.0.0.1:1", "/", replay)
        assert exc.value.status == 422
        assert rec.session is None

    asyncio.run(main())


def test_api_rejects_bad_replay(tmp_path):
    client = TestClient(create_app(tmp_path, TOKEN, ["testserver"], recorder=Recorder({"127.0.0.1"})))
    res = client.post(
        "/api/rec/start",
        headers=H,
        json={"base_url": "http://127.0.0.1:1", "path": "/", "replay": [{"op": "eval", "value": "1"}]},
    )
    assert res.status_code == 422
    assert "Wiedergabe" in res.json()["detail"]
    assert client.get("/api/rec/state", headers=H).json()["active"] is False


# ---------- Wiedergabe gegen echten Chromium ----------


def test_replay_runs_up_to_marker_then_records_without_replaying_steps(server):
    replay = [
        {"op": "goto", "value": "/"},
        {"op": "fill", "selector": "#user", "value": "fester Text"},
        {"op": "click", "selector": "#login"},
        {"op": "check", "selector": "#enabled"},
        {"op": "expect_checked", "selector": "#enabled"},
        {"op": "wait_ms", "value": "50"},
    ]

    async def scenario(s):
        seen = []
        done = await wait_event(s, "replay_done", seen)
        assert done["at"] == 6 and done["total"] == 6
        assert [e["index"] for e in seen if e["t"] == "replay"] == [1, 2, 3, 4, 5, 6]
        assert steps_of(seen) == []  # Abspielen zeichnet nichts auf
        assert await s.page.input_value("#user") == "fester Text"
        assert await s.page.is_checked("#enabled")
        assert s.recording

        # ab jetzt wird wieder aufgezeichnet
        await s.handle({"t": "click", "x": 40, "y": 292})  # Link "Hilfe"
        return steps_of(drain_all(s))

    steps = run_replay(server, replay, scenario)
    assert steps == [{"op": "click", "selector": 'role=link[name="Hilfe"]', "comment": "a: Hilfe"}]


def test_replay_pauses_at_credentials_and_manual_input_is_not_recorded(server):
    async def scenario(s):
        seen = []
        first = await wait_event(s, "replay_pause", seen)
        assert first["kind"] == "manual" and first["index"] == 2 and first["can_retry"] is False
        assert "Zugangsdaten" in first["message"]
        assert not s.recording

        # Prüfungen sind während der Wiedergabe nicht möglich, das Tippen schon (ohne Schritt)
        await s.handle({"t": "click", "x": 170, "y": 35, "pick": "expect_visible"})
        await s.handle({"t": "fill", "text": "alice-test", "as": "user"})
        assert await s.page.input_value("#user") == "alice-test"
        await s.handle({"t": "replay_resume"})

        second = await wait_event(s, "replay_pause", seen)
        assert second["index"] == 3
        await s.handle({"t": "fill", "text": "geheim-pw-123", "as": "auto"})
        assert await s.page.input_value('input[name="pwd"]') == "geheim-pw-123"
        await s.handle({"t": "replay_resume"})

        done = await wait_event(s, "replay_done", seen)  # click #login läuft von selbst
        assert done["at"] == 4
        assert await s.page.locator("#enabled").is_visible()
        assert steps_of(seen) == []
        assert any(e["t"] == "error" and "Wiedergabe" in e["message"] for e in seen)
        dump = json.dumps(seen)
        assert "alice-test" not in dump and "geheim-pw-123" not in dump
        return True

    assert run_replay(server, LOGIN, scenario)


def test_replay_pauses_at_todo_and_stop_records_from_there(server):
    replay = [
        {"op": "goto", "value": "/"},
        {"op": "fill", "selector": "#user", "value": "TODO: Wert setzen"},
        {"op": "click", "selector": "#login"},
    ]

    async def scenario(s):
        seen = []
        pause = await wait_event(s, "replay_pause", seen)
        assert pause["kind"] == "manual" and pause["index"] == 2 and "TODO" in pause["message"]
        await s.handle({"t": "replay_stop"})
        done = await wait_event(s, "replay_done", seen)
        assert done["at"] == 1 and done["total"] == 3  # Schritt 2 wurde nicht ausgeführt
        assert s.recording and not await s.page.locator("#enabled").is_visible()
        return True

    assert run_replay(server, replay, scenario)


def test_failed_step_can_be_retried_skipped_or_stopped(server):
    replay = [
        {"op": "goto", "value": "/"},
        {"op": "click", "selector": "#gibt-es-nicht"},
        {"op": "click", "selector": "#login"},
    ]

    async def retry_then_skip(s):
        seen = []
        first = await wait_event(s, "replay_pause", seen)
        assert first["kind"] == "failed" and first["index"] == 2 and first["can_retry"] is True
        assert "fehlgeschlagen" in first["message"]
        await s.handle({"t": "replay_retry"})
        await wait_event(s, "replay_pause", seen)  # schlägt erneut fehl
        await s.handle({"t": "replay_resume"})  # überspringen
        done = await wait_event(s, "replay_done", seen)
        assert done["at"] == 3
        assert await s.page.locator("#enabled").is_visible()  # Schritt 3 lief danach
        return True

    async def stop(s):
        seen = []
        await wait_event(s, "replay_pause", seen)
        await s.handle({"t": "replay_stop"})
        return (await wait_event(s, "replay_done", seen))["at"]

    assert run_replay(server, replay, retry_then_skip, page_timeout_ms=1000)
    assert run_replay(server, replay, stop, page_timeout_ms=1000) == 1


def test_manual_step_has_no_retry_and_control_messages_outside_pause_are_ignored(server):
    async def scenario(s):
        seen = []
        await wait_event(s, "replay_pause", seen)
        await s.handle({"t": "replay_retry"})  # gibt es bei manuellen Schritten nicht
        await asyncio.sleep(0.3)
        assert s.replay.phase == "paused"
        await s.handle({"t": "replay_stop"})
        assert (await wait_event(s, "replay_done", seen))["at"] == 1
        await s.handle({"t": "replay_resume"})  # nach dem Ende wirkungslos
        await s.handle({"t": "replay_stop"})
        return True

    assert run_replay(server, LOGIN, scenario)


def test_user_actions_are_refused_while_replay_runs_and_scrolling_is_ignored(server):
    replay = [{"op": "goto", "value": "/"}, {"op": "wait_ms", "value": "1500"}]

    async def scenario(s):
        seen = []
        await wait_running_step(s, 2, seen)  # mitten im wait_ms
        assert s.replay.phase == "running"
        await asyncio.wait_for(s.handle({"t": "click", "x": 80, "y": 135}), 1)  # wird sofort abgewiesen
        await asyncio.wait_for(s.handle({"t": "scroll", "dy": 50}), 1)  # blockiert nicht und meldet nichts
        done = await wait_event(s, "replay_done", seen)
        assert done["at"] == 2
        errors = [e["message"] for e in seen if e["t"] == "error"]
        assert errors == ["Die Wiedergabe läuft, bitte kurz warten."]
        assert steps_of(seen) == [] and not await s.page.locator("#enabled").is_visible()
        return True

    assert run_replay(server, replay, scenario)


def test_stop_request_while_running_ends_after_current_step(server):
    replay = [{"op": "goto", "value": "/"}, {"op": "wait_ms", "value": "1500"}, {"op": "click", "selector": "#login"}]

    async def scenario(s):
        seen = []
        await wait_running_step(s, 2, seen)
        await asyncio.wait_for(s.handle({"t": "replay_stop"}), 1)  # kommt auch mitten im Schritt sofort an
        done = await wait_event(s, "replay_done", seen)
        assert done["at"] == 2  # der laufende Schritt wird beendet, der nächste nicht mehr gestartet
        assert not await s.page.locator("#enabled").is_visible()
        return True

    assert run_replay(server, replay, scenario)


def test_requests_to_foreign_hosts_stay_blocked_while_replaying(server):
    replay = [{"op": "goto", "value": "/"}]

    async def scenario(s):
        seen = []
        await wait_event(s, "replay_done", seen)
        return [e["host"] for e in seen if e["t"] == "blocked"]

    assert run_replay(server, replay, scenario) == ["10.255.255.1"]  # das Tracker-Bild der Testseite


# ---------- über den WebSocket ----------


def collect_until(ws, kind, limit=400):
    events = []
    for _ in range(limit):
        msg = ws.receive()
        if msg.get("text"):
            event = json.loads(msg["text"])
            events.append(event)
            if event["t"] == kind:
                return events
    raise AssertionError(f"{kind!r} nicht gekommen: {events}")


def test_replay_over_websocket_with_pause_and_stop(tmp_path, server):
    recorder = Recorder({"127.0.0.1"}, max_seconds=60, idle_seconds=60)
    with TestClient(create_app(tmp_path, TOKEN, ["testserver"], recorder=recorder)) as client:
        res = client.post(
            "/api/rec/start", headers=H, json={"base_url": server, "path": "/", "replay": LOGIN[:3]}
        )
        assert res.status_code == 200 and res.json()["replay"] == {"total": 3}
        try:
            with client.websocket_connect("/api/rec/ws") as ws:
                ws.send_json({"t": "auth", "token": TOKEN})
                events = collect_until(ws, "replay_pause")
                assert events[0]["t"] == "hello"
                assert [e["t"] for e in events if e["t"] == "step"] == []
                pause = events[-1]
                assert pause["kind"] == "manual" and pause["index"] == 2
                ws.send_json({"t": "replay_stop"})
                done = collect_until(ws, "replay_done")[-1]
                assert done["at"] == 1 and done["total"] == 3
        finally:
            assert client.post("/api/rec/stop", headers=H).json() == {"ok": True}


def test_reconnecting_viewer_sees_the_paused_replay(tmp_path, server):
    recorder = Recorder({"127.0.0.1"}, max_seconds=60, idle_seconds=60)
    with TestClient(create_app(tmp_path, TOKEN, ["testserver"], recorder=recorder)) as client:
        client.post("/api/rec/start", headers=H, json={"base_url": server, "path": "/", "replay": LOGIN})
        try:
            with client.websocket_connect("/api/rec/ws") as ws:
                ws.send_json({"t": "auth", "token": TOKEN})
                collect_until(ws, "replay_pause")
            # Fenster neu geladen. Der Server räumt die alte Verbindung asynchron auf, daher ein paar Versuche.
            for _ in range(40):
                with client.websocket_connect("/api/rec/ws") as ws:
                    ws.send_json({"t": "auth", "token": TOKEN})
                    first = ws.receive_json()
                    if first["t"] == "hello":
                        events = [first, *collect_until(ws, "replay_pause")]
                        assert events[-1]["index"] == 2 and events[-1]["kind"] == "manual"
                        return
                time.sleep(0.1)
            raise AssertionError("Neu verbundenes Fenster hat den Stand der Wiedergabe nicht bekommen")
        finally:
            client.post("/api/rec/stop", headers=H)


def test_replay_follows_if_else_blocks_like_the_runner(server):
    replay = [
        {"op": "goto", "value": "/"},
        {"op": "if_visible", "selector": "#panel"},  # vor dem Login nicht sichtbar
        {"op": "click", "selector": "#gibt-es-nicht"},
        {"op": "else"},
        {"op": "click", "selector": "#login"},
        {"op": "end_if"},
        {"op": "if_text", "value": "Übernehmen"},  # nach dem Login sichtbar
        {"op": "check", "selector": "#enabled"},
        {"op": "else"},
        {"op": "click", "selector": "#gibt-es-nicht"},
        {"op": "end_if"},
    ]

    async def scenario(s):
        seen = []
        done = await wait_event(s, "replay_done", seen)
        assert done["at"] == len(replay) and done["total"] == len(replay)
        # übersprungen: Schritt 3 (then-Zweig, falsch) und Schritt 10 (else-Zweig nach wahrem then)
        played = [e["index"] for e in seen if e["t"] == "replay"]
        assert 3 not in played and 10 not in played and 5 in played and 8 in played
        assert not any(e["t"] == "replay_pause" for e in seen)
        assert await s.page.is_checked("#enabled")
        return True

    assert run_replay(server, replay, scenario)
