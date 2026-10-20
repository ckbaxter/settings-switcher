"""run.sh: Image wird nur bei Bedarf gebaut (fehlend, geänderte Quellen, --build). Docker ist hier ein Attrappen-Skript."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

FAKE_DOCKER = r"""#!/usr/bin/env bash
state="$FAKE_DOCKER_STATE"
case "$1" in
  image)
    [[ -f "$state/hash" ]] || exit 1
    cat "$state/hash"
    ;;
  build)
    echo build >>"$state/calls"
    [[ -z "${FAKE_BUILD_FAIL:-}" ]] || exit 1
    for a in "$@"; do
      if [[ "$a" == ss.source-hash=* ]]; then printf '%s' "${a#ss.source-hash=}" >"$state/hash"; fi
    done
    ;;
  run)
    echo run >>"$state/calls"
    ;;
esac
"""


@pytest.fixture
def repo(tmp_path):
    work = tmp_path / "repo"
    (work / "profiles").mkdir(parents=True)
    (work / "profiles" / "demo.json").write_text("{}")
    shutil.copy(ROOT / "run.sh", work / "run.sh")
    shutil.copytree(ROOT / "runner", work / "runner")
    shutil.copytree(ROOT / "shared", work / "shared", ignore=shutil.ignore_patterns("__pycache__"))
    env_file = work / "runner.env"
    env_file.write_text("SWITCHER_ALLOWED_HOSTS=192.168.178.1\n")
    env_file.chmod(0o600)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    state = tmp_path / "state"
    state.mkdir()
    return work, state, bin_dir


def run_sh(repo, *args, build_fails=False):
    work, state, bin_dir = repo
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DOCKER_STATE": str(state),
    }
    if build_fails:
        env["FAKE_BUILD_FAIL"] = "1"
    return subprocess.run(
        [str(work / "run.sh"), *args, "demo"], env=env, capture_output=True, text=True, timeout=60
    )


def builds(repo):
    calls = repo[1] / "calls"
    return calls.read_text().split().count("build") if calls.exists() else 0


def test_baut_beim_ersten_lauf_dann_nicht_mehr(repo):
    assert run_sh(repo).returncode == 0
    assert builds(repo) == 1
    assert run_sh(repo).returncode == 0
    assert builds(repo) == 1


def test_baut_neu_wenn_sich_quellen_aendern(repo):
    work = repo[0]
    run_sh(repo)
    (work / "shared" / "hosts.py").write_text((work / "shared" / "hosts.py").read_text() + "\n# geändert\n")
    result = run_sh(repo)
    assert result.returncode == 0
    assert "Quellen haben sich geändert" in result.stdout
    assert builds(repo) == 2


@pytest.mark.parametrize("datei", ["runner/runner.py", "runner/requirements.txt", "runner/Dockerfile"])
def test_baut_neu_bei_aenderung_der_runner_dateien(repo, datei):
    work = repo[0]
    run_sh(repo)
    pfad = work / datei
    pfad.write_text(pfad.read_text() + "\n# geändert\n")
    run_sh(repo)
    assert builds(repo) == 2


def test_pycache_loest_keinen_neubau_aus(repo):
    work = repo[0]
    run_sh(repo)
    cache = work / "shared" / "__pycache__"
    cache.mkdir()
    (cache / "hosts.cpython-313.pyc").write_bytes(b"\x00\x01")
    run_sh(repo)
    assert builds(repo) == 1


def test_build_flag_erzwingt_neubau(repo):
    run_sh(repo)
    run_sh(repo, "--build")
    assert builds(repo) == 2


def test_fehlgeschlagener_build_ist_exit_2_und_startet_nichts(repo):
    result = run_sh(repo, build_fails=True)
    assert result.returncode == 2
    assert "Image-Build fehlgeschlagen" in result.stderr
    calls = repo[1] / "calls"
    assert "run" not in calls.read_text().split()
