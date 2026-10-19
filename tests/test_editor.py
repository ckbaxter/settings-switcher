import json

import pytest
from fastapi.testclient import TestClient

from editor.app import create_app

TOKEN = "t" * 24
H = {"X-Token": TOKEN}

PROFILE = {
    "name": "demo",
    "description": "Demo",
    "base_url": "http://192.168.178.1",
    "timeout_ms": 15000,
    "steps": [{"op": "goto", "value": "/"}, {"op": "click", "selector": "#ok"}],
}


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, TOKEN, ["testserver"])
    return TestClient(app)


def test_short_token_refuses_to_start(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(tmp_path, "kurz", ["localhost"])


def test_static_page_needs_no_token_but_has_security_headers(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "default-src 'self'" in res.headers["content-security-policy"]
    assert res.headers["x-frame-options"] == "DENY"
    assert client.get("/static/app.js").status_code == 200


def test_api_requires_token(client):
    assert client.get("/api/profiles").status_code == 401
    assert client.get("/api/profiles", headers={"X-Token": "falsch"}).status_code == 401
    assert client.get("/api/profiles", headers={"X-Token": b"\xe4\xf6\xfc"}).status_code == 401
    assert client.get("/api/profiles", headers=H).status_code == 200


def test_api_is_not_cacheable(client):
    assert client.get("/api/profiles", headers=H).headers["cache-control"] == "no-store"


def test_bruteforce_is_rate_limited(client):
    codes = [client.get("/api/profiles", headers={"X-Token": f"x{i}"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10
    assert 429 in codes[10:]
    assert client.get("/api/profiles", headers=H).status_code == 429


def test_host_header_is_checked(client):
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/profiles", headers={"host": "evil.example", **H}).status_code == 400


def test_docs_are_disabled(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_crud_roundtrip(client, tmp_path):
    assert client.get("/api/profiles", headers=H).json() == []
    res = client.put("/api/profiles/demo", headers=H, json=PROFILE)
    assert res.status_code == 200 and res.json() == {"ok": True, "warnings": []}
    assert json.loads((tmp_path / "demo.json").read_text(encoding="utf-8")) == PROFILE
    assert client.get("/api/profiles/demo", headers=H).json() == PROFILE
    assert client.get("/api/profiles", headers=H).json() == [{"name": "demo", "description": "Demo", "steps": 2}]
    assert client.delete("/api/profiles/demo", headers=H).json() == {"ok": True}
    assert client.get("/api/profiles/demo", headers=H).status_code == 404
    assert client.delete("/api/profiles/demo", headers=H).status_code == 404
    assert not list(tmp_path.glob(".tmp-*"))


def test_placeholder_profiles_can_be_saved_with_warning(client):
    data = {**PROFILE, "steps": [{"op": "click", "selector": "TODO: Button"}]}
    res = client.put("/api/profiles/demo", headers=H, json=data)
    assert res.status_code == 200 and res.json()["warnings"]


def test_invalid_profile_is_rejected_and_not_written(client, tmp_path):
    data = {**PROFILE, "steps": [{"op": "evaluate", "value": "alert(1)"}]}
    res = client.put("/api/profiles/demo", headers=H, json=data)
    assert res.status_code == 422 and res.json()["errors"]
    assert not (tmp_path / "demo.json").exists()


def test_name_must_match_url(client):
    res = client.put("/api/profiles/other", headers=H, json=PROFILE)
    assert res.status_code == 422


@pytest.mark.parametrize("name", ["..%2Fevil", "%2e%2e%2fevil", "A", "a.b", "-x"])
def test_path_traversal_and_bad_names(client, tmp_path, name):
    res = client.put(f"/api/profiles/{name}", headers=H, json={**PROFILE, "name": "demo"})
    assert res.status_code in (404, 422)
    assert client.get(f"/api/profiles/{name}", headers=H).status_code == 404
    assert client.delete(f"/api/profiles/{name}", headers=H).status_code == 404
    assert not list(tmp_path.parent.glob("evil*"))


def test_validate_endpoint(client):
    good = client.post("/api/validate", headers=H, json=PROFILE).json()
    assert good == {"errors": [], "warnings": []}
    bad = client.post("/api/validate", headers=H, json={"name": "x"}).json()
    assert bad["errors"]


def test_bad_json_and_oversize(client):
    res = client.post("/api/validate", headers={**H, "Content-Type": "application/json"}, content=b"{nope")
    assert res.status_code == 400
    big = b'{"x":"' + b"a" * 250_000 + b'"}'
    res = client.post("/api/validate", headers={**H, "Content-Type": "application/json"}, content=big)
    assert res.status_code == 413


def test_ops_endpoint_lists_no_script_op(client):
    ops = {o["op"] for o in client.get("/api/ops", headers=H).json()}
    assert "click" in ops and "evaluate" not in ops
