"""Prüft, dass Playwright-Pin und Playwright-Image zusammenpassen (braucht keinen Browser)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE_RE = re.compile(r"^FROM\s+mcr\.microsoft\.com/playwright/python:v(\d+\.\d+\.\d+)-\S+", re.M)


def _pins(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    return re.findall(r"^playwright==(\S+)\s*$", text, re.M)


def _image_version(path):
    match = IMAGE_RE.search((ROOT / path).read_text(encoding="utf-8"))
    assert match, f"{path}: kein Playwright-Image in FROM gefunden"
    return match.group(1)


def test_playwright_pin_ist_in_allen_requirements_gleich():
    runner = _pins("runner/requirements.txt")
    dev = _pins("requirements-dev.txt")
    assert len(runner) == 1 and len(dev) == 1
    assert runner == dev


def test_playwright_image_passt_zum_pin():
    (pin,) = _pins("runner/requirements.txt")
    assert _image_version("runner/Dockerfile") == pin
    assert _image_version("recorder/Dockerfile") == pin


def test_recorder_installiert_playwright_nur_ueber_requirements():
    text = (ROOT / "recorder/Dockerfile").read_text(encoding="utf-8")
    assert "playwright==" not in text
