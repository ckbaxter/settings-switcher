"""Host-Prüfung, gemeinsam genutzt von Runner und Recorder.

Erlaubte Hosts kommen immer aus der Umgebung (SWITCHER_ALLOWED_HOSTS), nie aus einem Profil.
"""

from urllib.parse import urljoin, urlparse


def parse_allowed_hosts(env):
    raw = env.get("SWITCHER_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def url_host(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_allowed_url(url, allowed_hosts):
    if url == "about:blank":
        return True
    try:
        scheme = urlparse(url).scheme
    except ValueError:
        return False
    if scheme not in ("http", "https"):
        return False
    return url_host(url) in allowed_hosts


def resolve_url(base_url, value):
    """Pfad (/foo) wird an base_url gehängt, volle URLs bleiben unverändert."""
    if value.startswith("/"):
        return urljoin(base_url, value)
    return value
