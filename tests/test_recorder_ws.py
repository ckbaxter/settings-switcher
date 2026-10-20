"""Sicherheitsprüfungen am WebSocket des Live-Browsers (ohne Browser-Oberfläche)."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from editor.app import create_app
from editor.recorder import Recorder

TOKEN = "w" * 24
H = {"X-Token": TOKEN}


def make_client(tmp_path, recorder=None):
    return TestClient(create_app(tmp_path, TOKEN, ["testserver"], recorder=recorder))


def test_api_without_recorder_reports_it(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/config", headers=H).json()["recorder"] is False
    assert client.post("/api/rec/start", headers=H, json={"base_url": "http://x", "path": "/"}).status_code == 404
    assert client.post("/api/rec/stop", headers=H).status_code == 404
    assert client.get("/api/rec/state", headers=H).status_code == 404


def test_rec_api_requires_token(tmp_path):
    client = make_client(tmp_path, Recorder({"127.0.0.1"}))
    for method, path in (("get", "/api/config"), ("post", "/api/rec/start"), ("post", "/api/rec/stop"), ("get", "/api/rec/state")):
        assert getattr(client, method)(path).status_code == 401


def test_start_rejects_foreign_host_and_bad_path(tmp_path):
    client = make_client(tmp_path, Recorder({"127.0.0.1"}))
    res = client.post("/api/rec/start", headers=H, json={"base_url": "http://evil.example", "path": "/"})
    assert res.status_code == 422
    res = client.post("/api/rec/start", headers=H, json={"base_url": "http://127.0.0.1:1", "path": "//evil.example"})
    assert res.status_code == 422
    assert client.post("/api/rec/start", headers=H, json=["x"]).status_code == 400


@pytest.mark.parametrize("first", [{"t": "auth", "token": "falsch"}, {"t": "auth"}, {"t": "click"}, ["x"]])
def test_ws_rejects_bad_first_message(tmp_path, first):
    client = make_client(tmp_path, Recorder({"127.0.0.1"}))
    with client.websocket_connect("/api/rec/ws") as ws:
        ws.send_json(first)
        assert ws.receive_json()["t"] == "error"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_ws_rejects_foreign_host_and_origin(tmp_path):
    client = make_client(tmp_path, Recorder({"127.0.0.1"}))
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/rec/ws", headers={"host": "evil.example"}):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/rec/ws", headers={"origin": "http://evil.example"}):
            pass


def test_ws_with_valid_token_but_no_session(tmp_path):
    client = make_client(tmp_path, Recorder({"127.0.0.1"}))
    with client.websocket_connect("/api/rec/ws", headers={"origin": "http://testserver"}) as ws:
        ws.send_json({"t": "auth", "token": TOKEN})
        assert ws.receive_json()["t"] == "closed"


def test_ws_without_recorder_service(tmp_path):
    client = make_client(tmp_path)
    with client.websocket_connect("/api/rec/ws") as ws:
        ws.send_json({"t": "auth", "token": TOKEN})
        assert ws.receive_json()["t"] == "closed"


def test_ws_failed_logins_count_towards_rate_limit(tmp_path):
    client = make_client(tmp_path, Recorder({"127.0.0.1"}))
    for _ in range(10):
        with client.websocket_connect("/api/rec/ws") as ws:
            ws.send_json({"t": "auth", "token": "falsch"})
            ws.receive_json()
    # Jetzt ist auch das richtige Token für eine Minute gesperrt
    with client.websocket_connect("/api/rec/ws") as ws:
        ws.send_json({"t": "auth", "token": TOKEN})
        assert ws.receive_json()["t"] == "error"
    assert client.get("/api/profiles", headers=H).status_code == 429


def test_live_session_over_websocket(tmp_path, server):
    """Mit echter Sitzung: hello, Live-Bild als Binärnachricht, Klick liefert Schritt."""
    recorder = Recorder({"127.0.0.1"}, max_seconds=60, idle_seconds=60)
    with TestClient(create_app(tmp_path, TOKEN, ["testserver"], recorder=recorder)) as client:
        res = client.post("/api/rec/start", headers=H, json={"base_url": server, "path": "/"})
        assert res.status_code == 200 and res.json()["step"] == {"op": "goto", "value": "/"}
        assert client.get("/api/rec/state", headers=H).json()["active"] is True
        try:
            with client.websocket_connect("/api/rec/ws") as ws:
                ws.send_json({"t": "auth", "token": TOKEN})
                assert ws.receive_json()["t"] == "hello"
                got_frame = got_step = False
                ws.send_json({"t": "click", "x": 80, "y": 135})
                for _ in range(40):
                    msg = ws.receive()
                    if msg.get("bytes"):
                        got_frame = got_frame or msg["bytes"][:2] == b"\xff\xd8"  # JPEG
                    elif msg.get("text") and '"step"' in msg["text"]:
                        got_step = True
                    if got_frame and got_step:
                        break
                assert got_frame and got_step
        finally:
            assert client.post("/api/rec/stop", headers=H).json() == {"ok": True}
        assert client.get("/api/rec/state", headers=H).json()["active"] is False


def test_ws_rejects_address_outside_ip_list(tmp_path):
    app = create_app(tmp_path, TOKEN, ["testserver"], recorder=Recorder({"127.0.0.1"}), allowed_ips="172.18.0.5")
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app, client=("203.0.113.9", 50000)).websocket_connect("/api/rec/ws"):
            pass
    assert exc.value.code == 1008
    # Eine erlaubte Adresse kommt bis zur Token-Prüfung (und scheitert dort an der falschen Anmeldung).
    with TestClient(app, client=("172.18.0.5", 50000)).websocket_connect("/api/rec/ws") as ws:
        ws.send_json({"t": "auth", "token": "falsch"})
        assert ws.receive_json()["t"] == "error"
