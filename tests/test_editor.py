import json

import pytest
from fastapi.testclient import TestClient

from editor.app import _ip_allowed, create_app, parse_allowed_ips

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


def test_save_without_write_permission_gives_clear_error(client, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("editor.app.tempfile.mkstemp", denied)
    res = client.put("/api/profiles/demo", headers=H, json=PROFILE)
    assert res.status_code == 500
    assert "SWITCHER_UID" in res.json()["detail"] and "Schreibrechte" in res.json()["detail"]


def test_save_fails_cleanly_when_replace_fails(client, monkeypatch, tmp_path):
    def broken(*args, **kwargs):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr("editor.app.os.replace", broken)
    res = client.put("/api/profiles/demo", headers=H, json=PROFILE)
    assert res.status_code == 500
    assert "OSError" in res.json()["detail"]
    assert list(tmp_path.glob(".tmp-*")) == []  # keine Reste


def test_delete_without_write_permission_gives_clear_error(client, monkeypatch):
    assert client.put("/api/profiles/demo", headers=H, json=PROFILE).status_code == 200

    def denied(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("editor.app.Path.unlink", denied)
    res = client.delete("/api/profiles/demo", headers=H)
    assert res.status_code == 500 and "Schreibrechte" in res.json()["detail"]


def test_saved_profile_is_readable_by_other_users(client, tmp_path):
    import os
    import stat

    old = os.umask(0o077)  # auch bei strenger Umask muss der Runner (andere UID) die Datei lesen können
    try:
        assert client.put("/api/profiles/demo", headers=H, json=PROFILE).status_code == 200
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "demo.json").stat().st_mode) == 0o644


def ip_client(tmp_path, allowed_ips, peer):
    return TestClient(create_app(tmp_path, TOKEN, ["testserver"], allowed_ips=allowed_ips), client=(peer, 50000))


def test_without_ip_list_everyone_is_allowed(tmp_path):
    assert ip_client(tmp_path, "", "203.0.113.9").get("/api/profiles", headers=H).status_code == 200
    assert ip_client(tmp_path, None, "203.0.113.9").get("/").status_code == 200


def test_ip_list_allows_listed_address_and_network(tmp_path):
    assert ip_client(tmp_path, "172.18.0.5", "172.18.0.5").get("/api/profiles", headers=H).status_code == 200
    assert ip_client(tmp_path, "10.0.0.1, 192.168.1.0/24", "192.168.1.77").get("/").status_code == 200


def test_ip_list_blocks_other_addresses_everywhere(tmp_path):
    client = ip_client(tmp_path, "172.18.0.5", "172.18.0.6")
    for path in ("/", "/static/app.js", "/api/profiles"):
        res = client.get(path, headers=H)
        assert res.status_code == 403
        assert "content-security-policy" not in res.headers or res.text.startswith("Zugriff")
    assert client.put("/api/profiles/demo", headers=H, json=PROFILE).status_code == 403
    assert not list(tmp_path.glob("*.json"))


def test_forwarded_for_header_is_ignored(tmp_path):
    client = ip_client(tmp_path, "172.18.0.5", "203.0.113.9")
    res = client.get("/api/profiles", headers={**H, "X-Forwarded-For": "172.18.0.5", "X-Real-IP": "172.18.0.5"})
    assert res.status_code == 403


def test_invalid_ip_entry_refuses_to_start(tmp_path):
    with pytest.raises(RuntimeError, match="EDITOR_ALLOWED_IPS"):
        create_app(tmp_path, TOKEN, ["localhost"], allowed_ips="172.18.0.5,kein-netz")


@pytest.mark.parametrize(
    "client_host, expected",
    [
        ("172.18.0.5", True),
        ("::ffff:172.18.0.5", True),  # IPv4 als IPv6-Adresse (Dual-Stack-Socket)
        ("172.18.0.6", False),
        ("::1", False),
        ("testclient", False),
        ("", False),
        (None, False),
    ],
)
def test_ip_allowed_matching(client_host, expected):
    assert _ip_allowed(client_host, parse_allowed_ips("172.18.0.5")) is expected


def test_parse_allowed_ips_mixed_families():
    nets = parse_allowed_ips("10.0.0.0/8, fd00::/8,,")
    assert _ip_allowed("10.1.2.3", nets) and _ip_allowed("fd00::1", nets)
    assert not _ip_allowed("11.0.0.1", nets) and not _ip_allowed("fe80::1", nets)
    assert parse_allowed_ips("") == [] and parse_allowed_ips(None) == []
