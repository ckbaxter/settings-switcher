"""Kleiner Profil-Editor (nur Profile bearbeiten, führt selbst nichts aus).

Sicherheit:
- Alle /api-Routen brauchen das Header-Token (EDITOR_TOKEN, mind. 16 Zeichen).
- Host-Header wird gegen EDITOR_ALLOWED_HOSTS geprüft (Schutz vor DNS-Rebinding).
- Es gibt keine CORS-Freigabe; das Token liegt nie in Cookies.
- Der Editor hat keinen Zugriff auf Fritzbox-Zugangsdaten und startet keine Container.
"""

import json
import os
import secrets
import tempfile
import time
from collections import deque
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from shared.profile_schema import NAME_RE, OPS, find_placeholders, validate_profile

MAX_BODY = 200_000
STATIC_DIR = Path(__file__).parent / "static"


def _host_of(request):
    host = request.headers.get("host", "").strip().lower()
    if host.startswith("["):  # IPv6-Literal
        return host[1:].split("]", 1)[0]
    return host.split(":", 1)[0]


def create_app(profiles_dir, token, allowed_hosts):
    if not token or len(token) < 16:
        raise RuntimeError("EDITOR_TOKEN fehlt oder ist zu kurz (mindestens 16 Zeichen).")
    profiles_dir = Path(profiles_dir)
    allowed_hosts = {h.strip().lower() for h in allowed_hosts if h.strip()}
    failures = deque()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if _host_of(request) not in allowed_hosts:
            return Response("Host nicht erlaubt.", status_code=400, media_type="text/plain")
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def require_token(x_token: str | None = Header(default=None)):
        now = time.monotonic()
        while failures and now - failures[0] > 60:
            failures.popleft()
        if len(failures) >= 10:
            raise HTTPException(429, "Zu viele Fehlversuche, bitte eine Minute warten.")
        if not x_token or not secrets.compare_digest(x_token.encode(), token.encode()):
            failures.append(now)
            raise HTTPException(401, "Token ungültig.")

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
        fd, tmp = tempfile.mkstemp(dir=profiles_dir, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
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
        return {"ok": True}

    return app


def create_app_from_env():
    hosts = os.environ.get("EDITOR_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    return create_app(
        profiles_dir=os.environ.get("SS_PROFILES_DIR", "/profiles"),
        token=os.environ.get("EDITOR_TOKEN", ""),
        allowed_hosts=hosts,
    )
