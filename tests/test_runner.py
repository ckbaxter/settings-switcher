import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from runner import runner

PAGE = """<!doctype html><meta charset="utf-8"><title>Testbox</title>
<input id="pw" type="password">
<button id="login" onclick="document.getElementById('panel').hidden=false">Anmelden</button>
<div id="panel" hidden>
  <label><input id="enabled" type="checkbox"> Freigabe</label>
  <button id="apply" onclick="document.getElementById('status').textContent='gespeichert'">Übernehmen</button>
  <span id="status"></span>
</div>
<img src="http://10.255.255.1/tracker.png" alt="">
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def make_profile(base_url, steps, name="testlauf"):
    return {"name": name, "base_url": base_url, "timeout_ms": 2000, "steps": steps}


GOOD_STEPS = [
    {"op": "goto", "value": "/"},
    {"op": "fill", "selector": "#pw", "value": "${SWITCHER_PASSWORD}"},
    {"op": "click", "selector": "#login"},
    {"op": "wait_for", "selector": "#panel"},
    {"op": "check", "selector": "#enabled"},
    {"op": "click", "selector": "#apply"},
    {"op": "expect_text", "selector": "#status", "value": "gespeichert"},
    {"op": "expect_checked", "selector": "#enabled"},
]


def write_profile(tmp_path, profile):
    pdir = tmp_path / "profiles"
    pdir.mkdir(exist_ok=True)
    (pdir / f"{profile['name']}.json").write_text(json.dumps(profile), encoding="utf-8")
    return pdir


def env_for(tmp_path, **extra):
    env = {
        "SWITCHER_PROFILES_DIR": str(tmp_path / "profiles"),
        "SWITCHER_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
        "SWITCHER_ALLOWED_HOSTS": "127.0.0.1",
        "SWITCHER_PASSWORD": "sehr-geheim-123",
        "SWITCHER_USER": "tester",
    }
    env.update(extra)
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    return env


# ---------- Unit-Tests ohne Browser ----------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://192.168.178.1/", True),
        ("https://192.168.178.1:443/x?y=1", True),
        ("http://192.168.178.2/", False),
        ("http://192.168.178.1.evil.example/", False),
        ("http://192.168.178.1@evil.example/", False),
        ("http://evil.example/?h=192.168.178.1", False),
        ("data:text/html,hi", False),
        ("file:///etc/passwd", False),
        ("ftp://192.168.178.1/", False),
        ("about:blank", True),
        ("http://[::1]/", False),
    ],
)
def test_is_allowed_url(url, expected):
    assert runner.is_allowed_url(url, {"192.168.178.1"}) is expected


def test_resolve_url():
    assert runner.resolve_url("http://h:81", "/a/b") == "http://h:81/a/b"
    assert runner.resolve_url("http://h", "http://h/x") == "http://h/x"


def test_describe_step_hides_fill_value():
    text = runner.describe_step({"op": "fill", "selector": "#pw", "value": "${SWITCHER_PASSWORD}"})
    assert "SWITCHER_PASSWORD" not in text and "Zeichen" in text


def test_preflight_ok(tmp_path):
    profile = make_profile("http://127.0.0.1:1", GOOD_STEPS)
    assert runner.preflight(profile, env_for(tmp_path)) == []


def test_preflight_requires_allowed_hosts(tmp_path):
    profile = make_profile("http://127.0.0.1:1", GOOD_STEPS)
    errors = runner.preflight(profile, env_for(tmp_path, SWITCHER_ALLOWED_HOSTS=""))
    assert any("SWITCHER_ALLOWED_HOSTS" in e for e in errors)


def test_preflight_base_url_host_must_be_allowed(tmp_path):
    profile = make_profile("http://evil.example", GOOD_STEPS)
    assert any("nicht in SWITCHER_ALLOWED_HOSTS" in e for e in runner.preflight(profile, env_for(tmp_path)))


def test_preflight_missing_variable(tmp_path):
    profile = make_profile("http://127.0.0.1:1", GOOD_STEPS)
    env = env_for(tmp_path)
    del env["SWITCHER_PASSWORD"]
    assert any("SWITCHER_PASSWORD" in e for e in runner.preflight(profile, env))


def test_preflight_goto_to_other_host(tmp_path):
    steps = [{"op": "goto", "value": "http://evil.example/steal"}]
    errors = runner.preflight(make_profile("http://127.0.0.1:1", steps), env_for(tmp_path))
    assert any("außerhalb" in e for e in errors)


def test_preflight_rejects_placeholders(tmp_path):
    steps = [{"op": "click", "selector": "TODO: noch aufzeichnen"}]
    errors = runner.preflight(make_profile("http://127.0.0.1:1", steps), env_for(tmp_path))
    assert any("TODO" in e for e in errors)


def test_main_usage_and_missing_profile(tmp_path):
    env = env_for(tmp_path)
    assert runner.main([], env) == 2
    assert runner.main(["../etc/passwd"], env) == 2
    assert runner.main(["gibtsnicht"], env) == 2


def test_main_name_must_match_filename(tmp_path):
    profile = make_profile("http://127.0.0.1:1", GOOD_STEPS, name="andere")
    pdir = write_profile(tmp_path, profile)
    (pdir / "datei.json").write_text((pdir / "andere.json").read_text(), encoding="utf-8")
    assert runner.main(["datei"], env_for(tmp_path)) == 2


def test_main_does_not_start_browser_on_config_error(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("Browser darf nicht gestartet werden")

    monkeypatch.setattr(runner, "run_profile", boom)
    profile = make_profile("http://127.0.0.1:1", [{"op": "click", "selector": "TODO: x"}])
    write_profile(tmp_path, profile)
    assert runner.main(["testlauf"], env_for(tmp_path)) == 2


# ---------- Integrationstests mit echtem Chromium gegen lokale Testseite ----------


def test_successful_run(server, tmp_path, capsys):
    write_profile(tmp_path, make_profile(server, GOOD_STEPS))
    env = env_for(tmp_path)
    assert runner.main(["testlauf"], env) == 0
    out = capsys.readouterr().out
    assert "OK: Profil testlauf" in out
    assert "sehr-geheim-123" not in out
    assert "10.255.255.1" in out and "blockiert" in out


def test_failed_expectation_exits_1_and_saves_screenshot(server, tmp_path, capsys):
    steps = copy.deepcopy(GOOD_STEPS)[:4] + [{"op": "expect_text", "selector": "#status", "value": "nie"}]
    write_profile(tmp_path, make_profile(server, steps))
    env = env_for(tmp_path)
    assert runner.main(["testlauf"], env) == 1
    out = capsys.readouterr().out
    assert "FEHLER" in out
    assert "sehr-geheim-123" not in out
    assert list((tmp_path / "artifacts").glob("testlauf-*-fehler.png"))


def test_missing_element_fails(server, tmp_path):
    steps = [{"op": "goto", "value": "/"}, {"op": "click", "selector": "#gibt-es-nicht"}]
    write_profile(tmp_path, make_profile(server, steps))
    assert runner.main(["testlauf"], env_for(tmp_path)) == 1


def test_screenshots_for_every_step(server, tmp_path):
    write_profile(tmp_path, make_profile(server, GOOD_STEPS))
    assert runner.main(["testlauf"], env_for(tmp_path, SWITCHER_SCREENSHOTS="all")) == 0
    assert len(list((tmp_path / "artifacts").glob("testlauf-*.png"))) == len(GOOD_STEPS)


def test_selectors_from_codegen_style_engines(server, tmp_path):
    """role=- und text=-Selektoren (so übersetzt die Doku get_by_role/get_by_text) funktionieren."""
    steps = [
        {"op": "goto", "value": "/"},
        {"op": "click", "selector": 'role=button[name="Anmelden"]'},
        {"op": "wait_for", "selector": "#panel"},
        {"op": "click_text", "value": "Übernehmen"},
        {"op": "expect_text", "selector": "#status", "value": "gespeichert"},
        {"op": "click", "selector": "text=Freigabe"},
        {"op": "expect_checked", "selector": "#enabled"},
    ]
    write_profile(tmp_path, make_profile(server, steps))
    assert runner.main(["testlauf"], env_for(tmp_path)) == 0


def test_hinweis_wenn_profil_keine_pruefung_hat(tmp_path, monkeypatch, capsys):
    steps = [{"op": "goto", "value": "/"}, {"op": "click", "selector": "#apply"}]
    write_profile(tmp_path, make_profile("http://127.0.0.1", steps))
    monkeypatch.setattr(runner, "run_profile", lambda *a, **k: runner.EXIT_OK)
    assert runner.main(["testlauf"], env_for(tmp_path)) == runner.EXIT_OK
    assert "keine expect_*-Prüfung" in capsys.readouterr().out


def test_kein_hinweis_wenn_profil_eine_pruefung_hat(tmp_path, monkeypatch, capsys):
    write_profile(tmp_path, make_profile("http://127.0.0.1", GOOD_STEPS))
    monkeypatch.setattr(runner, "run_profile", lambda *a, **k: runner.EXIT_OK)
    assert runner.main(["testlauf"], env_for(tmp_path)) == runner.EXIT_OK
    assert "keine expect_*-Prüfung" not in capsys.readouterr().out


# ---------- Wenn-Blöcke ----------

LOGIN_STEPS = [
    {"op": "goto", "value": "/"},
    {"op": "fill", "selector": "#pw", "value": "${SWITCHER_PASSWORD}"},
]


def run_blocks(server, tmp_path, capsys, steps):
    write_profile(tmp_path, make_profile(server, steps))
    code = runner.main(["testlauf"], env_for(tmp_path))
    return code, capsys.readouterr().out


def test_if_visible_then_branch_and_else_is_skipped(server, tmp_path, capsys):
    steps = [
        {"op": "goto", "value": "/"},
        {"op": "if_visible", "selector": "#login"},
        {"op": "click", "selector": "#login"},
        {"op": "else"},
        {"op": "click", "selector": "#gibt-es-nicht"},
        {"op": "end_if"},
        {"op": "expect_visible", "selector": "#panel"},
    ]
    code, out = run_blocks(server, tmp_path, capsys, steps)
    assert code == 0, out
    assert "zutreffend" in out and "überspringe den else-Teil" in out
    assert "[5/7] click #gibt-es-nicht" not in out


def test_if_visible_else_branch(server, tmp_path, capsys):
    steps = [
        {"op": "goto", "value": "/"},
        {"op": "if_visible", "selector": "#panel"},  # vor dem Login nicht sichtbar
        {"op": "click", "selector": "#gibt-es-nicht"},
        {"op": "else"},
        {"op": "click", "selector": "#login"},
        {"op": "end_if"},
        {"op": "expect_visible", "selector": "#panel"},
    ]
    code, out = run_blocks(server, tmp_path, capsys, steps)
    assert code == 0, out
    assert "nicht zutreffend" in out
    assert "[3/7] click #gibt-es-nicht" not in out


def test_if_without_else_skips_the_block_when_false(server, tmp_path, capsys):
    steps = [
        {"op": "goto", "value": "/"},
        {"op": "if_visible", "selector": "#panel"},
        {"op": "click", "selector": "#gibt-es-nicht"},
        {"op": "end_if"},
        {"op": "click", "selector": "#login"},
        {"op": "expect_visible", "selector": "#panel"},
    ]
    code, out = run_blocks(server, tmp_path, capsys, steps)
    assert code == 0, out
    assert "[3/6] click" not in out


def test_if_text_matches_visible_text_and_respects_scope(server, tmp_path, capsys):
    steps = [
        {"op": "goto", "value": "/"},
        {"op": "click", "selector": "#login"},
        {"op": "if_text", "value": "freigabe"},  # Groß-/Kleinschreibung egal
        {"op": "check", "selector": "#enabled"},
        {"op": "end_if"},
        {"op": "if_text", "selector": "#status", "value": "Freigabe"},  # steht nicht im Bereich #status
        {"op": "click", "selector": "#gibt-es-nicht"},
        {"op": "else"},
        {"op": "click", "selector": "#apply"},
        {"op": "end_if"},
        {"op": "expect_checked", "selector": "#enabled"},
        {"op": "expect_text", "selector": "#status", "value": "gespeichert"},
    ]
    code, out = run_blocks(server, tmp_path, capsys, steps)
    assert code == 0, out


def test_hidden_text_does_not_count(server, tmp_path, capsys):
    # Vor dem Login ist #panel versteckt, "Freigabe" steht aber schon im HTML
    steps = [
        {"op": "goto", "value": "/"},
        {"op": "if_text", "value": "Freigabe"},
        {"op": "click", "selector": "#gibt-es-nicht"},
        {"op": "end_if"},
        {"op": "expect_visible", "selector": "#login"},
    ]
    code, out = run_blocks(server, tmp_path, capsys, steps)
    assert code == 0, out
    assert "nicht zutreffend" in out


def test_failure_inside_chosen_branch_exits_1(server, tmp_path, capsys):
    steps = [
        {"op": "goto", "value": "/"},
        {"op": "if_visible", "selector": "#login"},
        {"op": "click", "selector": "#gibt-es-nicht"},
        {"op": "end_if"},
    ]
    code, out = run_blocks(server, tmp_path, capsys, steps)
    assert code == 1
    assert "FEHLER" in out and list((tmp_path / "artifacts").glob("testlauf-*-fehler.png"))


def test_preflight_rejects_broken_block_before_browser(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("Browser darf nicht gestartet werden")

    monkeypatch.setattr(runner, "run_profile", boom)
    steps = [{"op": "goto", "value": "/"}, {"op": "if_visible", "selector": "#a"}]
    write_profile(tmp_path, make_profile("http://127.0.0.1:1", steps))
    assert runner.main(["testlauf"], env_for(tmp_path)) == 2


def test_preflight_checks_goto_hosts_in_both_branches(tmp_path):
    steps = [
        {"op": "if_visible", "selector": "#a"},
        {"op": "goto", "value": "/ok"},
        {"op": "else"},
        {"op": "goto", "value": "http://evil.example/x"},
        {"op": "end_if"},
    ]
    errors = runner.preflight(make_profile("http://127.0.0.1:1", steps), env_for(tmp_path))
    assert any("außerhalb" in e for e in errors)
