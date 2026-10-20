"""Aufnahme-Modus: ein Chromium im Container, dessen Live-Bild der Editor anzeigt.

Klicks und Eingaben aus der Oberfläche werden an den echten Browser weitergegeben und
gleichzeitig als Profil-Schritte gemeldet.

Sicherheit:
- Nur Hosts aus SS_ALLOWED_HOSTS sind erreichbar (alles andere wird blockiert).
- Der Recorder kennt keine Zugangsdaten. Passwörter werden nie gespeichert: bei
  Passwortfeldern steht im Schritt ${SS_PASSWORD}, sonst ein TODO-Platzhalter.
- Eine Sitzung gleichzeitig, mit Idle- und Gesamt-Zeitlimit. Popups werden geschlossen,
  Downloads und Service-Worker sind aus.

Wiedergabe bis zur Stopmarke (optional beim Start):
- Die Schritte bis zur Marke werden vor dem Aufzeichnen im Live-Browser abgespielt,
  mit denselben Host-Sperren wie sonst. Sie werden dabei nicht erneut aufgezeichnet.
- Der Recorder kennt keine Zugangsdaten. Ein fill mit ${SS_...} (und alles mit TODO) spielt er
  deshalb nie selbst ab, sondern hält an: Du erledigst den Schritt im Live-Bild, das wird
  nicht aufgezeichnet, danach geht es weiter. Genauso bei einem Schritt, der fehlschlägt.
"""

import asyncio
import hashlib
import re
import time
from urllib.parse import urlparse

from shared.hosts import is_allowed_url, resolve_url, url_host
from shared.profile_schema import MAX_STRING, is_plain_path, uses_variable, validate_profile

VIEWPORT = {"width": 1280, "height": 800}
PICK_KINDS = {"expect_visible", "wait_for", "expect_text", "expect_checked", "expect_unchecked"}
TEXT_MODES = {"auto", "user", "password", "literal"}
KEYS = {"Enter", "Tab", "Escape"}
PLACEHOLDER_VALUE = "TODO: Wert setzen"
REPLAY_TIMEOUT_MS = 10_000
REPLAY_CONTROLS = {"replay_resume", "replay_retry", "replay_stop"}

DESCRIBE_JS = """
(arg) => {
  const interactive = 'a,button,input,select,textarea,label,summary,[role=button],[role=link],' +
    '[role=checkbox],[role=radio],[role=menuitem],[role=tab],[onclick]';
  let el;
  if (arg.focused) {
    el = document.activeElement;
    if (!el || el === document.body || el === document.documentElement) return { none: true };
  } else {
    el = document.elementFromPoint(arg.x, arg.y);
    if (!el) return { none: true };
    el = el.closest(interactive) || el;
  }
  const visible = (n) => {
    const r = n.getBoundingClientRect();
    const s = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const text = (n) => clean(n.innerText || n.textContent).slice(0, 80);
  const cssPath = (n) => {
    const parts = [];
    while (n && n.nodeType === 1 && n !== document.documentElement) {
      if (n.id && /^[A-Za-z][\\w-]*$/.test(n.id) &&
          document.querySelectorAll('[id="' + n.id + '"]').length === 1) {
        parts.unshift('#' + n.id);
        break;
      }
      let part = n.tagName.toLowerCase();
      const parent = n.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter((c) => c.tagName === n.tagName);
        if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(n) + 1) + ')';
      }
      parts.unshift(part);
      n = parent;
    }
    return parts.join(' > ');
  };
  let control = null;
  if (el.tagName === 'LABEL' && el.control) control = el.control;
  const state = control || el;
  const isCheck = state.tagName === 'INPUT' && (state.type === 'checkbox' || state.type === 'radio');
  const t = control && visible(control) ? control : el;
  const tag = t.tagName.toLowerCase();
  const type = (t.getAttribute('type') || '').toLowerCase();
  const labels = state.labels ? Array.from(state.labels).map((l) => text(l)).filter(Boolean) : [];
  return {
    tag, type,
    id: t.id || '',
    name: t.getAttribute('name') || '',
    testid: t.getAttribute('data-testid') || '',
    aria: clean(t.getAttribute('aria-label')),
    role: (t.getAttribute('role') || '').toLowerCase(),
    title: clean(t.getAttribute('title')),
    hasHref: t.hasAttribute('href'),
    value: ['button', 'submit', 'reset'].includes(type) ? clean(t.value) : '',
    text: tag === 'input' ? '' : text(t),
    labels,
    isCheck, checked: isCheck ? !!state.checked : null,
    isSelect: tag === 'select',
    options: tag === 'select'
      ? Array.from(t.options).slice(0, 200).map((o) => ({ value: o.value, label: clean(o.label || o.text) }))
      : [],
    isText: tag === 'textarea' || (tag === 'input' &&
      !['button', 'submit', 'reset', 'checkbox', 'radio', 'image', 'file', 'range', 'color', 'hidden'].includes(type)),
    isPassword: tag === 'input' && type === 'password',
    cssPath: cssPath(t),
  };
}
"""

ID_OK = re.compile(r"^[A-Za-z][\w-]*$")
ID_UNSTABLE = re.compile(r"\d{4,}|^[a-f0-9]{8,}$", re.IGNORECASE)
ROLE_WORDS = {"button", "link", "checkbox", "radio", "menuitem", "tab"}


class RecorderError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _safe(text):
    return bool(text) and not any(c in text for c in '"\\\n\r')


def _role_of(info):
    if info["role"] in ROLE_WORDS:
        return info["role"]
    tag, kind = info["tag"], info["type"]
    if tag == "button":
        return "button"
    if tag == "a" and info["hasHref"]:
        return "link"
    if tag == "input":
        if kind in ("button", "submit", "reset", "image"):
            return "button"
        if kind in ("checkbox", "radio"):
            return kind
    return None


def _accessible_name(info):
    for candidate in (info["aria"], *(info["labels"][:1] if info["isCheck"] else ()), info["value"], info["text"], info["title"]):
        if candidate:
            return candidate
    return ""


def selector_candidates(info):
    """Mögliche Selektoren, stabilste zuerst. Der letzte (CSS-Pfad) ist der Notnagel."""
    out = []
    if info["id"] and ID_OK.match(info["id"]) and not ID_UNSTABLE.search(info["id"]):
        out.append("#" + info["id"])
    if _safe(info["testid"]):
        out.append(f'[data-testid="{info["testid"]}"]')
    role, name = _role_of(info), _accessible_name(info)
    if role and _safe(name):
        out.append(f'role={role}[name="{name}"]')
    if _safe(info["name"]) and info["tag"] in ("input", "select", "textarea", "button"):
        out.append(f'{info["tag"]}[name="{info["name"]}"]')
    if info["tag"] != "input" and _safe(info["text"]) and len(info["text"]) <= 60:
        out.append(f'text="{info["text"]}"')
    out.append(info["cssPath"])
    return out


async def pick_selector(page, info):
    """Nimmt den ersten Kandidaten, der genau ein Element trifft."""
    candidates = selector_candidates(info)
    for candidate in candidates[:-1]:
        try:
            if await page.locator(candidate).count() == 1:
                return candidate
        except Exception:  # noqa: BLE001 - ungültiger Kandidat, nächsten probieren
            continue
    return candidates[-1]


def _label_of(info):
    name = _accessible_name(info) or info["name"] or info["id"]
    return f"{info['tag']}: {name}"[:100] if name else info["tag"]


def display_url(url):
    """Nur Ursprung und Pfad anzeigen, Query-Parameter (z. B. Session-IDs) nie."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:200]


def replay_block_reason(step):
    """Warum der Recorder einen Schritt nicht selbst abspielt (None = er darf es)."""
    if step["op"] == "fill" and uses_variable(step.get("value")):
        return "Zugangsdaten kennt der Recorder nicht. Bitte im Live-Bild selbst eintippen (wird nicht aufgezeichnet)."
    for field in ("selector", "value"):
        value = step.get(field)
        if isinstance(value, str) and value.strip().upper().startswith("TODO"):
            return "Dieser Schritt hat noch ein TODO. Bitte im Live-Bild selbst erledigen (wird nicht aufgezeichnet)."
    return None


def replay_label(step):
    """Kurzbeschreibung für die Anzeige. Der Wert eines fill steht nie darin."""
    parts = [step["op"]]
    if step.get("selector"):
        parts.append(step["selector"])
    elif step.get("value") and step["op"] != "fill":
        parts.append(step["value"])
    return " ".join(parts)[:120]


async def replay_step(page, step, base_url):
    """Führt einen Schritt aus, wie es der Runner tut (hier mit der async-API)."""
    from playwright.async_api import expect

    op, selector, value = step["op"], step.get("selector"), step.get("value")
    if op == "fill" and uses_variable(value):  # schon vorher abgefangen, hier nur als Sicherung
        raise RecorderError("Zugangsdaten gibt der Recorder nie selbst ein.")
    loc = page.locator(selector) if selector else None
    if op == "goto":
        await page.goto(resolve_url(base_url, value), wait_until="domcontentloaded")
    elif op == "click":
        await loc.click()
    elif op == "click_text":
        await page.get_by_text(value, exact=True).click()
    elif op == "fill":
        await loc.fill(value)
    elif op == "check":
        await loc.check()
    elif op == "uncheck":
        await loc.uncheck()
    elif op == "select_option":
        await loc.select_option(value)
    elif op == "press":
        await loc.press(value)
    elif op == "wait_for":
        await loc.wait_for(state="visible")
    elif op == "wait_ms":
        await page.wait_for_timeout(int(value))
    elif op == "expect_visible":
        await expect(loc).to_be_visible(timeout=REPLAY_TIMEOUT_MS)
    elif op == "expect_text":
        await expect(loc).to_contain_text(value, timeout=REPLAY_TIMEOUT_MS)
    elif op == "expect_checked":
        await expect(loc).to_be_checked(timeout=REPLAY_TIMEOUT_MS)
    elif op == "expect_unchecked":
        await expect(loc).not_to_be_checked(timeout=REPLAY_TIMEOUT_MS)
    else:  # durch die Validierung ausgeschlossen
        raise RecorderError(f"Unbekannte Operation {op}.")


class Replay:
    """Zustand der Wiedergabe bis zur Stopmarke: pending -> running <-> paused -> done."""

    def __init__(self, steps, base_url):
        self.steps = steps
        self.base_url = base_url
        self.pos = 0  # Index des nächsten Schritts. Bei "done": so viele Schritte sind erledigt.
        self.phase = "pending"
        self.action = None  # vom Betrachter gewählt: skip, retry oder stop
        self.wake = asyncio.Event()
        self.last_event = None
        self.task = None


class Session:
    def __init__(self, pw, browser, context, page, allowed_hosts):
        self.pw, self.browser, self.context, self.page = pw, browser, context, page
        self.allowed_hosts = allowed_hosts
        self.events = asyncio.Queue(maxsize=500)
        self.started = self.last_activity = time.monotonic()
        self._lock = asyncio.Lock()
        self._blocked = set()
        self.replay = None

    def emit(self, event):
        try:
            self.events.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def touch(self):
        self.last_activity = time.monotonic()

    def current_url(self):
        return display_url(self.page.url) if self.page.url != "about:blank" else ""

    # ---------- Browser-Ereignisse ----------

    async def guard(self, route):
        url = route.request.url
        if is_allowed_url(url, self.allowed_hosts):
            await route.continue_()
            return
        host = url_host(url) or url.split(":", 1)[0]
        if host not in self._blocked:
            self._blocked.add(host)
            self.emit({"t": "blocked", "host": host})
        await route.abort("blockedbyclient")

    def on_navigated(self, frame):
        if frame == self.page.main_frame:
            self.emit({"t": "url", "url": display_url(frame.url)})

    def on_dialog(self, dialog):
        # Wie im Runner: Dialoge werden verworfen. Die Meldung zeigen wir nur an.
        self.emit({"t": "dialog", "message": dialog.message[:200]})
        asyncio.ensure_future(dialog.dismiss())

    def on_popup(self, page):
        if page is not self.page:
            self.emit({"t": "popup"})
            asyncio.ensure_future(page.close())

    # ---------- Beschreibung von Elementen ----------

    async def describe(self, x=None, y=None, focused=False):
        info = await self.page.evaluate(DESCRIBE_JS, {"x": x, "y": y, "focused": focused})
        return None if info.get("none") else info

    @property
    def recording(self):
        """Schritte werden nur aufgezeichnet, solange keine Wiedergabe läuft oder wartet."""
        return self.replay is None or self.replay.phase == "done"

    def step(self, op, selector=None, value=None, comment=None):
        if not self.recording:
            return
        step = {"op": op}
        if selector:
            step["selector"] = selector
        if value:
            step["value"] = value
        if comment:
            step["comment"] = comment[:MAX_STRING]
        self.emit({"t": "step", "step": step})

    # ---------- Aktionen ----------

    # ---------- Wiedergabe bis zur Stopmarke ----------

    def begin_replay(self):
        rp = self.replay
        if rp is not None and rp.phase == "pending":
            rp.phase = "running"
            rp.task = asyncio.ensure_future(self.run_replay())

    def replay_snapshot(self):
        """Letzter Stand für einen Betrachter, der sich (wieder) verbindet."""
        rp = self.replay
        return rp.last_event if rp is not None and rp.phase in ("running", "paused") else None

    def replay_control(self, kind):
        rp = self.replay
        if rp is None or rp.phase == "done":
            return
        if kind == "replay_stop":
            rp.action = "stop"
        elif rp.phase != "paused":
            return
        elif kind == "replay_resume":
            rp.action = "skip"
        elif kind == "replay_retry" and rp.last_event.get("can_retry"):
            rp.action = "retry"
        else:
            return
        rp.wake.set()

    async def _pause(self, kind, index, message, can_retry):
        rp = self.replay
        rp.phase = "paused"
        rp.last_event = {
            "t": "replay_pause", "kind": kind, "index": index, "total": len(rp.steps),
            "message": message, "can_retry": can_retry,
        }
        self.emit(rp.last_event)
        while rp.action is None:
            rp.wake.clear()
            await rp.wake.wait()
        action, rp.action = rp.action, None
        rp.phase = "running"
        return action

    async def _focus_field(self, step):
        """Setzt den Cursor in das Feld, das der Betrachter gleich selbst ausfüllt."""
        selector = step.get("selector")
        if step["op"] == "fill" and selector and not selector.strip().upper().startswith("TODO"):
            try:
                await self.page.locator(selector).focus(timeout=3000)
            except Exception:  # noqa: BLE001 - dann klickt der Betrachter selbst ins Feld
                pass

    async def run_replay(self):
        rp = self.replay
        total = len(rp.steps)
        try:
            while rp.pos < total and rp.action != "stop":
                step, n = rp.steps[rp.pos], rp.pos + 1
                self.touch()
                reason = replay_block_reason(step)
                if reason is None:
                    rp.last_event = {"t": "replay", "index": n, "total": total, "label": replay_label(step)}
                    self.emit(rp.last_event)
                    try:
                        async with self._lock:
                            await replay_step(self.page, step, rp.base_url)
                    except Exception as exc:  # noqa: BLE001 - Fehler der Seite sind keine Abstürze des Recorders
                        first = (str(exc).strip().splitlines() or [exc.__class__.__name__])[0][:200]
                        action = await self._pause("failed", n, f"Schritt {n} fehlgeschlagen: {first}", True)
                    else:
                        rp.pos += 1
                        continue
                else:
                    await self._focus_field(step)
                    action = await self._pause("manual", n, f"Schritt {n} ({replay_label(step)}): {reason}", False)
                if action == "skip":  # vom Betrachter selbst erledigt (oder bewusst übergangen)
                    rp.pos += 1
                elif action == "stop":
                    break
        finally:
            rp.phase = "done"
            rp.last_event = None
            self.emit({"t": "replay_done", "at": rp.pos, "total": total})

    async def handle(self, msg):
        kind = msg.get("t")
        if kind in REPLAY_CONTROLS:
            self.replay_control(kind)
            return
        if not self.recording and self.replay.phase != "paused":
            # Läuft die Wiedergabe, hält sie die Sperre. Würden wir hier warten, käme auch "Hier aufzeichnen"
            # (replay_stop) erst nach dem Schritt an, weil der WebSocket Nachrichten nacheinander abarbeitet.
            if kind != "scroll":  # Mausrad-Ereignisse kommen in Serie, sie werden ohne Meldung verworfen
                self.emit({"t": "error", "message": "Die Wiedergabe läuft, bitte kurz warten."})
            return
        try:
            async with self._lock:
                if kind == "click":
                    await self._click(msg)
                elif kind == "fill":
                    await self._fill(msg)
                elif kind == "key":
                    await self._key(msg)
                elif kind == "select":
                    await self._select(msg)
                elif kind == "scroll":
                    await self._scroll(msg)
        except RecorderError as exc:
            self.emit({"t": "error", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - Fehler der Seite sind keine Abstürze des Recorders
            first = (str(exc).strip().splitlines() or [exc.__class__.__name__])[0]
            self.emit({"t": "error", "message": f"Aktion fehlgeschlagen: {first[:200]}"})

    def _coords(self, msg):
        x, y = msg.get("x"), msg.get("y")
        for v, limit in ((x, VIEWPORT["width"]), (y, VIEWPORT["height"])):
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v < limit:
                raise RecorderError("Ungültige Position.")
        return int(x), int(y)

    async def _scroll(self, msg):
        """Mausrad, Wischen oder Pfeilknöpfe. dx/dy in Pixeln, x/y (optional) = Position des Zeigers."""
        deltas = []
        for key in ("dx", "dy"):
            v = msg.get(key, 0)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v:  # NaN
                raise RecorderError("Ungültige Scroll-Angabe.")
            deltas.append(max(-2000, min(2000, v)))
        if "x" in msg or "y" in msg:
            x, y = self._coords(msg)
        else:  # ohne Position: Bildmitte, damit auch innere Bereiche scrollen
            x, y = VIEWPORT["width"] // 2, VIEWPORT["height"] // 2
        await self.page.mouse.move(x, y)
        await self.page.mouse.wheel(deltas[0], deltas[1])

    async def _click(self, msg):
        x, y = self._coords(msg)
        info = await self.describe(x, y)
        if info is None:
            raise RecorderError("An dieser Stelle gibt es kein Element.")

        pick = msg.get("pick")
        if pick is not None:
            if not self.recording:
                raise RecorderError("Prüfungen lassen sich erst setzen, wenn die Wiedergabe fertig ist.")
            await self._pick(pick, info)
            return

        if info["isSelect"]:
            selector = await pick_selector(self.page, info)
            self.emit({"t": "select", "selector": selector, "options": info["options"]})
            return

        selector = await pick_selector(self.page, info)
        await self.page.mouse.click(x, y)
        if info["isText"]:
            return  # nur Fokus setzen, das fill-Schritt übernimmt den Rest
        op = "click"
        if info["isCheck"]:
            await asyncio.sleep(0.2)
            after = await self.describe(x, y)
            if after is not None and after["isCheck"]:
                op = "check" if after["checked"] else "uncheck"
        self.step(op, selector, comment=_label_of(info))

    async def _pick(self, kind, info):
        if kind not in PICK_KINDS:
            raise RecorderError("Unbekannte Prüfung.")
        if kind in ("expect_checked", "expect_unchecked") and not info["isCheck"]:
            raise RecorderError("Das ist kein Kontrollkästchen.")
        selector = await pick_selector(self.page, info)
        if kind == "expect_text":
            text = info["text"] or info["value"]
            if not text:
                raise RecorderError("Das Element hat keinen Text.")
            self.step(kind, selector, text, comment=_label_of(info))
        else:
            self.step(kind, selector, comment=_label_of(info))

    async def _fill(self, msg):
        text, mode = msg.get("text"), msg.get("as", "auto")
        if not isinstance(text, str) or not text or len(text) > MAX_STRING:
            raise RecorderError(f"Text fehlt oder ist länger als {MAX_STRING} Zeichen.")
        if mode not in TEXT_MODES:
            raise RecorderError("Unbekannter Speichermodus.")
        info = await self.describe(focused=True)
        if info is None or not info["isText"]:
            raise RecorderError("Erst in ein Eingabefeld klicken.")
        if mode == "literal" and info["isPassword"]:
            raise RecorderError("Passwörter werden nie im Klartext gespeichert.")
        selector = await pick_selector(self.page, info)
        await self.page.locator(selector).fill(text)
        if mode == "auto":
            value = "${SS_PASSWORD}" if info["isPassword"] else PLACEHOLDER_VALUE
        elif mode == "user":
            value = "${SS_USER}"
        elif mode == "password":
            value = "${SS_PASSWORD}"
        else:
            value = text
        self.step("fill", selector, value, comment=_label_of(info))

    async def _key(self, msg):
        key = msg.get("key")
        if key not in KEYS:
            raise RecorderError("Taste nicht erlaubt.")
        info = await self.describe(focused=True)
        selector = await pick_selector(self.page, info) if info else "body"
        await self.page.keyboard.press(key)
        self.step("press", selector, key)

    async def _select(self, msg):
        selector, value = msg.get("selector"), msg.get("value")
        for v in (selector, value):
            if not isinstance(v, str) or not v or len(v) > MAX_STRING:
                raise RecorderError("Ungültige Auswahl.")
        await self.page.locator(selector).select_option(value)
        self.step("select_option", selector, value)

    async def close(self):
        if self.replay is not None and self.replay.task is not None:
            self.replay.task.cancel()
        for closer in (self.context.close, self.browser.close, self.pw.stop):
            try:
                await closer()
            except Exception:  # noqa: BLE001
                pass


class Recorder:
    """Verwaltet höchstens eine Aufnahme-Sitzung."""

    def __init__(self, allowed_hosts, *, ignore_https_errors=False, no_sandbox=True,
                 max_seconds=600, idle_seconds=180):
        if not allowed_hosts:
            raise RuntimeError("SS_ALLOWED_HOSTS ist leer, der Recorder startet nicht.")
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.ignore_https_errors = ignore_https_errors
        self.no_sandbox = no_sandbox
        self.max_seconds = max_seconds
        self.idle_seconds = idle_seconds
        self.session = None
        self.viewer = None
        self._starting = False
        self._watchdog = None

    def state(self):
        s = self.session
        return {"active": s is not None, "url": s.current_url() if s else ""}

    def _check_replay(self, base_url, steps):
        """Prüft die Schritte bis zur Stopmarke wie der Runner ein Profil und gibt sie bereinigt zurück."""
        if not isinstance(steps, list) or not steps:
            raise RecorderError("Für die Wiedergabe fehlen die Schritte bis zur Stopmarke.", 422)
        errors = validate_profile({"name": "wiedergabe", "base_url": base_url, "steps": steps})
        if not errors:
            for i, step in enumerate(steps, 1):
                if step["op"] == "goto" and not is_allowed_url(resolve_url(base_url, step["value"]), self.allowed_hosts):
                    errors.append(f"Schritt {i}: goto-Ziel liegt außerhalb der erlaubten Hosts.")
        if errors:
            raise RecorderError("Wiedergabe nicht möglich: " + " ".join(errors[:3]), 422)
        return [{k: step[k] for k in ("op", "selector", "value") if step.get(k)} for step in steps]

    async def start(self, base_url, path, replay=None):
        if self.session is not None or self._starting:
            raise RecorderError("Es läuft bereits eine Aufnahme.", 409)
        if not isinstance(base_url, str) or url_host(base_url) not in self.allowed_hosts:
            raise RecorderError("Die Basis-URL liegt nicht in SS_ALLOWED_HOSTS.", 422)
        if not is_plain_path(path):
            raise RecorderError("Der Startpfad muss mit / beginnen.", 422)
        replay_steps = self._check_replay(base_url, replay) if replay is not None else None
        self._starting = True
        pw = browser = None
        try:
            from playwright.async_api import async_playwright

            pw = await async_playwright().start()
            args = ["--disable-dev-shm-usage"] + (["--no-sandbox"] if self.no_sandbox else [])
            try:
                browser = await pw.chromium.launch(args=args)
            except Exception as exc:  # noqa: BLE001
                raise RecorderError(
                    "Chromium lässt sich nicht starten. Läuft der Dienst im Recorder-Image?", 503
                ) from exc
            context = await browser.new_context(
                ignore_https_errors=self.ignore_https_errors,
                service_workers="block",
                accept_downloads=False,
                viewport=VIEWPORT,
                locale="de-DE",
            )
            page = await context.new_page()
            session = Session(pw, browser, context, page, self.allowed_hosts)
            await context.route("**/*", session.guard)
            page.on("framenavigated", session.on_navigated)
            page.on("dialog", session.on_dialog)
            context.on("page", session.on_popup)
            page.set_default_timeout(10_000)
            page.set_default_navigation_timeout(15_000)
            try:
                await page.goto(base_url.rstrip("/") + path, wait_until="domcontentloaded")
            except Exception as exc:  # noqa: BLE001
                first = (str(exc).strip().splitlines() or [""])[0][:200]
                raise RecorderError(f"Seite lässt sich nicht öffnen: {first}", 502) from exc
        except BaseException:
            for closer in (browser.close if browser else None, pw.stop if pw else None):
                if closer:
                    try:
                        await closer()
                    except Exception:  # noqa: BLE001
                        pass
            raise
        finally:
            self._starting = False
        if replay_steps:
            session.replay = Replay(replay_steps, base_url)
        self.session = session
        self._watchdog = asyncio.ensure_future(self._watch(session))
        if replay_steps:  # beginnt, sobald ein Betrachter verbunden ist; das goto steht schon im Profil
            return {"viewport": VIEWPORT, "replay": {"total": len(replay_steps)}}
        return {"viewport": VIEWPORT, "step": {"op": "goto", "value": path}}

    async def _watch(self, session):
        while self.session is session:
            await asyncio.sleep(2)
            now = time.monotonic()
            if now - session.started > self.max_seconds:
                await self.stop("Zeitlimit der Aufnahme erreicht.")
            elif now - session.last_activity > self.idle_seconds:
                await self.stop("Aufnahme wegen Inaktivität beendet.")

    async def stop(self, reason="Aufnahme beendet."):
        session, self.session = self.session, None
        if session is None:
            return
        session.emit({"t": "closed", "reason": reason})
        await session.close()


async def stream_frames(send_bytes, session, interval=0.2):
    """Schickt das Live-Bild, aber nur wenn es sich geändert hat."""
    last = b""
    while True:
        try:
            data = await session.page.screenshot(type="jpeg", quality=60, timeout=4000)
        except Exception:  # noqa: BLE001 - z. B. während einer Navigation
            await asyncio.sleep(0.5)
            continue
        digest = hashlib.blake2b(data, digest_size=8).digest()
        if digest != last:
            last = digest
            await send_bytes(data)
        await asyncio.sleep(interval)
