"""Kleiner Profil-Editor (nur Profile bearbeiten, führt selbst nichts aus).

Sicherheit:
- Alle /api-Routen brauchen das Header-Token (EDITOR_TOKEN, mind. 16 Zeichen).
- Host-Header wird gegen EDITOR_ALLOWED_HOSTS geprüft (Schutz vor DNS-Rebinding).
- Optional: EDITOR_ALLOWED_IPS (IPs/CIDR-Netze) begrenzt, von welcher Adresse aus der Editor
  erreichbar ist. Geprüft wird nur die direkte Gegenstelle der Verbindung, nie X-Forwarded-For.
- Es gibt keine CORS-Freigabe; das Token liegt nie in Cookies.
- Der Editor hat keinen Zugriff auf Fritzbox-Zugangsdaten und startet keine Container.
- Der Aufnahme-Modus (Live-Browser) ist nur aktiv, wenn ein Recorder übergeben wird
  (RECORDER_ENABLED=1 im Recorder-Image). Der WebSocket prüft Host, Origin und Token.
"""

import asyncio
import ipaddress
import json
import logging
import os
import secrets
import tempfile
import time
from collections import deque
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from editor.recorder import VIEWPORT, Recorder, RecorderError, stream_frames
from shared.hosts import parse_allowed_hosts
from shared.profile_schema import NAME_RE, OPS, find_placeholders, validate_profile

log = logging.getLogger("uvicorn.error")

MAX_BODY = 200_000
STATIC_DIR = Path(__file__).parent / "static"


def _host_of(request):
    return _host_from_headers(request.headers)


def _host_from_headers(headers):
    host = headers.get("host", "").strip().lower()
    if host.startswith("["):  # IPv6-Literal
        return host[1:].split("]", 1)[0]
    return host.split(":", 1)[0]


def parse_allowed_ips(value):
    """Liest eine kommagetrennte Liste aus IPs und CIDR-Netzen (z. B. "172.18.0.5,192.168.1.0/24").

    Leer oder None = keine Einschränkung. Ein ungültiger Eintrag stoppt den Start (fail closed),
    damit ein Tippfehler nicht still den Schutz abschaltet.
    """
    if value is None:
        return []
    items = value.split(",") if isinstance(value, str) else list(value)
    networks = []
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            raise RuntimeError(f"EDITOR_ALLOWED_IPS: ungültiger Eintrag {item!r} (erwartet IP oder CIDR-Netz).")
    return networks


def _ip_allowed(client_host, networks):
    if not networks:
        return True
    try:
        ip = ipaddress.ip_address(client_host or "")
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip.version == net.version and ip in net for net in networks)


def _write_error(exc):
    """Verständliche Meldung statt nacktem 500 (meist: der Container-Benutzer darf in profiles/ nicht schreiben)."""
    log.error("Profil konnte nicht geschrieben werden: %s", exc)
    if isinstance(exc, PermissionError):
        return (
            "Keine Schreibrechte auf das Profilverzeichnis. SWITCHER_UID/SWITCHER_GID in .env müssen zum Besitzer von "
            "./profiles passen (id -u, id -g; ggf. chown), danach docker compose neu starten."
        )
    return f"Profil konnte nicht gespeichert werden ({exc.__class__.__name__}). Details im Container-Log."


def create_app(profiles_dir, token, allowed_hosts, recorder=None, allowed_ips=None):
    if not token or len(token) < 16:
        raise RuntimeError("EDITOR_TOKEN fehlt oder ist zu kurz (mindestens 16 Zeichen).")
    profiles_dir = Path(profiles_dir)
    allowed_hosts = {h.strip().lower() for h in allowed_hosts if h.strip()}
    ip_networks = parse_allowed_ips(allowed_ips)
    failures = deque()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def peer_ip(conn):
        return conn.client.host if conn.client else None

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not _ip_allowed(peer_ip(request), ip_networks):
            log.warning("Zugriff von %s abgelehnt (nicht in EDITOR_ALLOWED_IPS).", peer_ip(request))
            return Response("Zugriff von dieser Adresse nicht erlaubt.", status_code=403, media_type="text/plain")
        if _host_of(request) not in allowed_hosts:
            return Response("Host nicht erlaubt.", status_code=400, media_type="text/plain")
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def check_token(value):
        now = time.monotonic()
        while failures and now - failures[0] > 60:
            failures.popleft()
        if len(failures) >= 10:
            raise HTTPException(429, "Zu viele Fehlversuche, bitte eine Minute warten.")
        if not isinstance(value, str) or not value or not secrets.compare_digest(value.encode(), token.encode()):
            failures.append(now)
            raise HTTPException(401, "Token ungültig.")

    def require_token(x_token: str | None = Header(default=None)):
        check_token(x_token)
        if recorder is not None and recorder.session is not None:
            recorder.session.touch()

    def profile_path(name):
        if not NAME_RE.match(name):
            raise HTTPException(404, "Profil nicht gefunden.")
        return profiles_dir / f"{name}.json"

    async def read_json(request):
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "Profil ist zu groß.")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Kein gültiges JSON.")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/ops", dependencies=[Depends(require_token)])
    def ops():
        return [
            {"op": op, "required": list(spec[0]), "description": spec[1]}
            for op, spec in OPS.items()
        ]

    @app.get("/api/profiles", dependencies=[Depends(require_token)])
    def list_profiles():
        result = []
        for path in sorted(profiles_dir.glob("*.json")):
            if not NAME_RE.match(path.stem):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result.append(
                    {
                        "name": path.stem,
                        "description": str(data.get("description", "")),
                        "steps": len(data.get("steps", [])),
                    }
                )
            except (OSError, ValueError, AttributeError):
                result.append({"name": path.stem, "description": "(nicht lesbar)", "steps": 0})
        return result

    @app.get("/api/profiles/{name}", dependencies=[Depends(require_token)])
    def get_profile(name: str):
        path = profile_path(name)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise HTTPException(404, "Profil nicht gefunden.")
        except (OSError, ValueError):
            raise HTTPException(500, "Profil nicht lesbar.")

    @app.post("/api/validate", dependencies=[Depends(require_token)])
    async def validate(request: Request):
        data = await read_json(request)
        errors = validate_profile(data)
        warnings = [] if errors else find_placeholders(data)
        return {"errors": errors, "warnings": warnings}

    @app.put("/api/profiles/{name}", dependencies=[Depends(require_token)])
    async def put_profile(name: str, request: Request):
        if not NAME_RE.match(name):
            return JSONResponse(
                {"errors": ["name: nur a-z, 0-9, _ und -, 1-64 Zeichen, nicht mit - oder _ beginnen."]},
                status_code=422,
            )
        path = profile_path(name)
        data = await read_json(request)
        errors = validate_profile(data)
        if not errors and data.get("name") != name:
            errors.append("name im Profil muss zum Namen in der URL passen.")
        if errors:
            return JSONResponse({"errors": errors}, status_code=422)
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        try:
            fd, tmp = tempfile.mkstemp(dir=profiles_dir, prefix=".tmp-", suffix=".json")
        except OSError as exc:
            raise HTTPException(500, _write_error(exc))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                os.fchmod(fh.fileno(), 0o644)  # mkstemp legt 0600 an; der Runner läuft evtl. mit anderer UID. Profile sind nicht geheim.
                fh.write(text)
            os.replace(tmp, path)
        except OSError as exc:
            Path(tmp).unlink(missing_ok=True)
            raise HTTPException(500, _write_error(exc))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return {"ok": True, "warnings": find_placeholders(data)}

    @app.delete("/api/profiles/{name}", dependencies=[Depends(require_token)])
    def delete_profile(name: str):
        path = profile_path(name)
        try:
            path.unlink()
        except FileNotFoundError:
            raise HTTPException(404, "Profil nicht gefunden.")
        except OSError as exc:
            raise HTTPException(500, _write_error(exc))
        return {"ok": True}

    # ---------- Aufnahme-Modus ----------

    def need_recorder():
        if recorder is None:
            raise HTTPException(404, "Der Aufnahme-Modus ist in diesem Dienst nicht aktiv.")
        return recorder

    @app.get("/api/config", dependencies=[Depends(require_token)])
    def config():
        return {"recorder": recorder is not None, "viewport": VIEWPORT}

    @app.post("/api/rec/start", dependencies=[Depends(require_token)])
    async def rec_start(request: Request):
        rec = need_recorder()
        data = await read_json(request)
        if not isinstance(data, dict):
            raise HTTPException(400, "Ungültige Anfrage.")
        try:
            return await rec.start(data.get("base_url"), data.get("path", "/"), data.get("replay"))
        except RecorderError as exc:
            raise HTTPException(exc.status, str(exc))

    @app.post("/api/rec/stop", dependencies=[Depends(require_token)])
    async def rec_stop():
        await need_recorder().stop("Aufnahme beendet.")
        return {"ok": True}

    @app.get("/api/rec/state", dependencies=[Depends(require_token)])
    def rec_state():
        return need_recorder().state()

    async def pump(ws, session):
        while True:
            event = await session.events.get()
            await ws.send_json(event)
            if event.get("t") == "closed":
                await ws.close(code=1000)
                return

    @app.websocket("/api/rec/ws")
    async def rec_ws(ws: WebSocket):
        origin = ws.headers.get("origin")
        origin_host = (urlparse(origin).hostname or "").lower() if origin else None
        if not _ip_allowed(peer_ip(ws), ip_networks):
            log.warning("WebSocket von %s abgelehnt (nicht in EDITOR_ALLOWED_IPS).", peer_ip(ws))
            await ws.close(code=1008)
            return
        if _host_from_headers(ws.headers) not in allowed_hosts or (origin and origin_host not in allowed_hosts):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=5))
            if not isinstance(first, dict) or first.get("t") != "auth":
                raise ValueError
            check_token(first.get("token"))
        except (HTTPException, asyncio.TimeoutError, ValueError, WebSocketDisconnect, RuntimeError):
            with suppress(Exception):
                await ws.send_json({"t": "error", "message": "Anmeldung fehlgeschlagen."})
                await ws.close(code=4401)
            return

        session = recorder.session if recorder is not None else None
        if session is None:
            with suppress(Exception):
                await ws.send_json({"t": "closed", "reason": "Es läuft keine Aufnahme."})
                await ws.close(code=1000)
            return
        if recorder.viewer is not None:
            with suppress(Exception):
                await ws.send_json({"t": "error", "message": "Die Aufnahme wird schon in einem anderen Fenster angezeigt."})
                await ws.close(code=4409)
            return

        recorder.viewer = ws
        await ws.send_json({"t": "hello", "viewport": VIEWPORT, "url": session.current_url()})
        snapshot = session.replay_snapshot()  # wer sich neu verbindet, sieht den Stand der Wiedergabe
        if snapshot is not None:
            await ws.send_json(snapshot)
        session.begin_replay()
        pump_task = asyncio.ensure_future(pump(ws, session))
        frames_task = asyncio.ensure_future(stream_frames(ws.send_bytes, session))
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > 4096:
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    session.touch()
                    await session.handle(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            pump_task.cancel()
            frames_task.cancel()
            if recorder.viewer is ws:
                recorder.viewer = None

    return app


def create_app_from_env():
    hosts = os.environ.get("EDITOR_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    recorder = None
    if os.environ.get("RECORDER_ENABLED") == "1":
        recorder = Recorder(
            parse_allowed_hosts(os.environ),
            ignore_https_errors=os.environ.get("SWITCHER_IGNORE_HTTPS_ERRORS", "0") == "1",
            no_sandbox=os.environ.get("SWITCHER_CHROMIUM_NO_SANDBOX", "1") != "0",
            max_seconds=int(os.environ.get("REC_MAX_SECONDS", "600")),
            idle_seconds=int(os.environ.get("REC_IDLE_SECONDS", "180")),
        )
    return create_app(
        profiles_dir=os.environ.get("SWITCHER_PROFILES_DIR", "/profiles"),
        token=os.environ.get("EDITOR_TOKEN", ""),
        allowed_hosts=hosts,
        recorder=recorder,
        allowed_ips=os.environ.get("EDITOR_ALLOWED_IPS", ""),
    )
