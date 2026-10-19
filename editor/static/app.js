"use strict";

(function () {
  const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
  const $ = (id) => document.getElementById(id);

  let token = "";
  try {
    token = sessionStorage.getItem("ss-token") || "";
  } catch (e) {
    token = "";
  }
  let ops = [];
  let isNew = false;
  let steps = [];

  function el(tag, props, children) {
    const node = document.createElement(tag);
    Object.keys(props || {}).forEach((key) => {
      if (key === "text") node.textContent = props[key];
      else if (key === "class") node.className = props[key];
      else if (key in node) node[key] = props[key];
      else node.setAttribute(key, props[key]);
    });
    (children || []).forEach((child) => node.appendChild(child));
    return node;
  }

  async function api(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: { "X-Token": token, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      data = null;
    }
    return { status: res.status, ok: res.ok, data };
  }

  function say(items) {
    const box = $("messages");
    box.replaceChildren();
    items.forEach((item) => box.appendChild(el("div", { class: "msg " + item.kind, text: item.text })));
  }

  function apiError(res) {
    if (res.data && Array.isArray(res.data.errors)) {
      return res.data.errors.map((text) => ({ kind: "error", text }));
    }
    const detail = res.data && res.data.detail ? res.data.detail : "Fehler " + res.status;
    return [{ kind: "error", text: String(detail) }];
  }

  function opSpec(op) {
    return ops.find((o) => o.op === op) || { op, required: [], description: "" };
  }

  function renderSteps() {
    const list = $("steps");
    list.replaceChildren();
    steps.forEach((step, i) => {
      const spec = opSpec(step.op);
      const needsSelector = spec.required.includes("selector");
      const needsValue = spec.required.includes("value");

      const select = el("select", { title: spec.description, "aria-label": "Operation" });
      ops.forEach((o) => select.appendChild(el("option", { value: o.op, text: o.op, selected: o.op === step.op })));
      select.addEventListener("change", () => {
        step.op = select.value;
        const next = opSpec(step.op);
        if (!next.required.includes("selector")) step.selector = "";
        if (!next.required.includes("value")) step.value = "";
        renderSteps();
      });

      const selector = el("input", {
        value: step.selector || "",
        disabled: !needsSelector,
        placeholder: needsSelector ? "Selektor (CSS/XPath)" : "",
        maxLength: 500,
        "aria-label": "Selektor",
      });
      selector.addEventListener("input", () => (step.selector = selector.value));

      const value = el("input", {
        value: step.value || "",
        disabled: !needsValue,
        placeholder: needsValue ? (step.op === "fill" ? "Wert oder ${SS_PASSWORD}" : "Wert") : "",
        maxLength: 500,
        "aria-label": "Wert",
      });
      value.addEventListener("input", () => (step.value = value.value));

      const comment = el("input", {
        value: step.comment || "",
        placeholder: "Notiz",
        maxLength: 500,
        "aria-label": "Notiz",
      });
      comment.addEventListener("input", () => (step.comment = comment.value));

      const up = el("button", { type: "button", text: "↑", title: "Nach oben", disabled: i === 0 });
      up.addEventListener("click", () => {
        steps.splice(i - 1, 0, steps.splice(i, 1)[0]);
        renderSteps();
      });
      const down = el("button", { type: "button", text: "↓", title: "Nach unten", disabled: i === steps.length - 1 });
      down.addEventListener("click", () => {
        steps.splice(i + 1, 0, steps.splice(i, 1)[0]);
        renderSteps();
      });
      const del = el("button", { type: "button", text: "✕", title: "Schritt entfernen", class: "danger" });
      del.addEventListener("click", () => {
        steps.splice(i, 1);
        renderSteps();
      });

      list.appendChild(el("li", { class: "step" }, [select, selector, value, comment, el("div", { class: "tools" }, [up, down, del])]));
    });
  }

  function collect() {
    const profile = {
      name: $("f-name").value.trim(),
      description: $("f-desc").value,
      base_url: $("f-base").value.trim(),
      timeout_ms: Number($("f-timeout").value),
      steps: steps.map((s) => {
        const out = { op: s.op };
        if (s.selector) out.selector = s.selector;
        if (s.value) out.value = s.value;
        if (s.comment) out.comment = s.comment;
        return out;
      }),
    };
    return profile;
  }

  function show(profile, fresh) {
    isNew = fresh;
    $("editor").hidden = false;
    $("editor-title").textContent = fresh ? "Neues Profil" : "Profil: " + profile.name;
    $("f-name").value = profile.name || "";
    $("f-name").readOnly = !fresh;
    $("f-desc").value = profile.description || "";
    $("f-base").value = profile.base_url || "";
    $("f-timeout").value = profile.timeout_ms || 15000;
    steps = (profile.steps || []).map((s) => ({
      op: s.op,
      selector: s.selector || "",
      value: s.value || "",
      comment: s.comment || "",
    }));
    $("delete").hidden = fresh;
    say([]);
    renderSteps();
  }

  async function loadList(activeName) {
    const res = await api("GET", "/api/profiles");
    const list = $("profile-list");
    list.replaceChildren();
    if (!res.ok) {
      say(apiError(res));
      return;
    }
    res.data.forEach((p) => {
      const button = el(
        "button",
        { type: "button", class: p.name === activeName ? "active" : "" },
        [el("span", { text: p.name }), el("span", { class: "sub", text: p.steps + " Schritte · " + p.description })]
      );
      button.addEventListener("click", () => openProfile(p.name));
      list.appendChild(el("li", {}, [button]));
    });
  }

  async function openProfile(name) {
    if (rec.active) return say([{ kind: "warn", text: "Bitte zuerst die Aufnahme beenden." }]);
    const res = await api("GET", "/api/profiles/" + encodeURIComponent(name));
    if (!res.ok) {
      say(apiError(res));
      return;
    }
    show(res.data, false);
    loadList(name);
  }

  async function connect(event) {
    if (event) event.preventDefault();
    token = $("token").value || token;
    const res = await api("GET", "/api/ops");
    if (!res.ok) {
      say(apiError(res));
      return;
    }
    try {
      sessionStorage.setItem("ss-token", token);
    } catch (e) {
      /* Speichern ist nur eine Bequemlichkeit */
    }
    ops = res.data;
    $("new-profile").disabled = false;
    $("editor").hidden = true;
    say([]);
    await loadList(null);
    await initRecorder();
  }

  async function validate() {
    const res = await api("POST", "/api/validate", collect());
    if (!res.ok) return say(apiError(res));
    const items = res.data.errors.map((text) => ({ kind: "error", text }));
    res.data.warnings.forEach((text) => items.push({ kind: "warn", text }));
    if (!items.length) items.push({ kind: "ok", text: "Profil ist gültig." });
    say(items);
  }

  async function save() {
    const profile = collect();
    if (!NAME_RE.test(profile.name)) {
      return say([{ kind: "error", text: "Name: nur a-z, 0-9, _ und -, nicht mit - oder _ beginnen." }]);
    }
    const res = await api("PUT", "/api/profiles/" + encodeURIComponent(profile.name), profile);
    if (!res.ok) return say(apiError(res));
    const items = [{ kind: "ok", text: "Gespeichert." }];
    res.data.warnings.forEach((text) => items.push({ kind: "warn", text: text + " Der Runner führt es so nicht aus." }));
    isNew = false;
    $("f-name").readOnly = true;
    $("delete").hidden = false;
    $("editor-title").textContent = "Profil: " + profile.name;
    say(items);
    loadList(profile.name);
  }

  async function remove() {
    const name = $("f-name").value;
    if (!window.confirm("Profil " + name + " wirklich löschen?")) return;
    const res = await api("DELETE", "/api/profiles/" + encodeURIComponent(name));
    if (!res.ok) return say(apiError(res));
    $("editor").hidden = true;
    loadList(null);
  }


  // ---------- Aufnahme-Modus ----------
  const rec = { ws: null, active: false, viewport: { width: 1280, height: 800 }, pick: null, frame: null };

  function note(kind, text) {
    const box = $("rec-note");
    box.className = "msg " + kind;
    box.textContent = text;
  }

  function setRecording(active) {
    rec.active = active;
    $("rec-start").hidden = active;
    $("rec-stop").hidden = !active;
    $("rec-live").hidden = !active;
    $("rec-path").disabled = active;
    if (!active) {
      setPick(null);
      if (rec.frame) URL.revokeObjectURL(rec.frame);
      rec.frame = null;
      $("live").removeAttribute("src");
      $("rec-select").hidden = true;
    }
  }

  function setPick(kind) {
    rec.pick = kind;
    document.querySelectorAll("#rec-picks button").forEach((b) => b.classList.toggle("active", b.dataset.kind === kind));
  }

  function send(message) {
    if (rec.ws && rec.ws.readyState === WebSocket.OPEN) rec.ws.send(JSON.stringify(message));
  }

  function offerSelect(event) {
    const box = $("rec-select");
    box.replaceChildren();
    const select = el("select", { "aria-label": "Eintrag wählen" });
    select.appendChild(el("option", { value: "", text: "Eintrag wählen …" }));
    event.options.forEach((o) => select.appendChild(el("option", { value: o.value || o.label, text: o.label || o.value })));
    select.addEventListener("change", () => {
      if (select.value) send({ t: "select", selector: event.selector, value: select.value });
      box.hidden = true;
    });
    const cancel = el("button", { type: "button", text: "Abbrechen" });
    cancel.addEventListener("click", () => (box.hidden = true));
    box.appendChild(select);
    box.appendChild(cancel);
    box.hidden = false;
  }

  function onRecEvent(event) {
    if (event.t === "hello") {
      rec.viewport = event.viewport;
      $("rec-url").textContent = event.url || "";
    } else if (event.t === "step") {
      steps.push({ op: event.step.op, selector: event.step.selector || "", value: event.step.value || "", comment: event.step.comment || "" });
      renderSteps();
    } else if (event.t === "url") {
      $("rec-url").textContent = event.url;
    } else if (event.t === "blocked") {
      note("warn", "Anfrage an nicht erlaubten Host blockiert: " + event.host);
    } else if (event.t === "dialog") {
      note("warn", "Die Seite zeigte einen Dialog (wird verworfen): " + event.message);
    } else if (event.t === "popup") {
      note("warn", "Ein Popup wurde geschlossen.");
    } else if (event.t === "error") {
      rec.lastError = event.message;
      note("error", event.message);
    } else if (event.t === "select") {
      offerSelect(event);
    } else if (event.t === "closed") {
      setRecording(false);
      say([{ kind: "warn", text: event.reason }]);
    }
  }

  function openSocket() {
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    const ws = new WebSocket(proto + location.host + "/api/rec/ws");
    rec.ws = ws;
    ws.addEventListener("open", () => ws.send(JSON.stringify({ t: "auth", token })));
    ws.addEventListener("message", (message) => {
      if (typeof message.data === "string") {
        onRecEvent(JSON.parse(message.data));
        return;
      }
      const url = URL.createObjectURL(new Blob([message.data], { type: "image/jpeg" }));
      $("live").src = url;
      if (rec.frame) URL.revokeObjectURL(rec.frame);
      rec.frame = url;
    });
    ws.addEventListener("close", (event) => {
      if (rec.ws !== ws || !rec.active) return;
      if (event.code === 4409 || event.code === 4401) {
        // Abgelehnt (anderes Fenster zeigt die Aufnahme / Anmeldung fehlgeschlagen)
        setRecording(false);
        say([{ kind: "error", text: rec.lastError || "Verbindung zum Live-Browser abgelehnt." }]);
        return;
      }
      note("error", "Verbindung zum Live-Browser getrennt.");
    });
  }

  async function startRecording() {
    const res = await api("POST", "/api/rec/start", { base_url: $("f-base").value.trim(), path: $("rec-path").value.trim() || "/" });
    if (!res.ok) return say(apiError(res));
    const start = { op: res.data.step.op, selector: "", value: res.data.step.value, comment: "" };
    // Ein leeres oder nur aus dem Start-goto bestehendes Profil wird ersetzt, sonst angehängt
    if (steps.length === 0 || (steps.length === 1 && steps[0].op === "goto")) steps = [start];
    else steps.push(start);
    renderSteps();
    say([]);
    note("warn", "");
    setRecording(true);
    openSocket();
  }

  async function stopRecording() {
    await api("POST", "/api/rec/stop");
    if (rec.ws) rec.ws.close();
    setRecording(false);
  }

  async function initRecorder() {
    const config = await api("GET", "/api/config");
    $("recorder").hidden = !(config.ok && config.data.recorder);
    if (!config.ok || !config.data.recorder) return;
    rec.viewport = config.data.viewport;
    const state = await api("GET", "/api/rec/state");
    if (state.ok && state.data.active && !rec.active) {
      setRecording(true);
      openSocket();
      note("warn", "Eine laufende Aufnahme wurde wieder verbunden. Frühere Schritte stehen nicht mehr in der Liste.");
    }
  }

  function livePoint(event) {
    const box = $("live").getBoundingClientRect();
    return {
      x: Math.floor(((event.clientX - box.left) * rec.viewport.width) / box.width),
      y: Math.floor(((event.clientY - box.top) * rec.viewport.height) / box.height),
    };
  }

  let swipeEndedAt = 0; // ein Klick unmittelbar nach einem Wisch ist nur ein Nachläufer und wird verworfen
  $("live").addEventListener("click", (event) => {
    if (Date.now() - swipeEndedAt < 60) return;
    const point = livePoint(event);
    const message = { t: "click", x: point.x, y: point.y };
    if (rec.pick) message.pick = rec.pick;
    send(message);
    setPick(null);
  });
  // Scrollen: Mausrad, Wischen (Touch/Stift) und Pfeilknöpfe schicken alle {t:"scroll", dx, dy, x, y}
  let lastScroll = 0;
  $("live").addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const now = Date.now();
      if (now - lastScroll < 80) return;
      lastScroll = now;
      const point = livePoint(event);
      send({ t: "scroll", dx: event.deltaX, dy: event.deltaY, x: point.x, y: point.y });
    },
    { passive: false }
  );

  const SCROLL_STEP = 400;
  const SCROLL_DIRS = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
  document.querySelectorAll("#rec-scroll [data-scroll]").forEach((button) =>
    button.addEventListener("click", () => {
      const dir = SCROLL_DIRS[button.dataset.scroll];
      if (dir) send({ t: "scroll", dx: dir[0] * SCROLL_STEP, dy: dir[1] * SCROLL_STEP });
    })
  );

  // Wischen: Finger nach unten = Seite nach oben (wie auf dem Gerät gewohnt)
  const swipe = { id: null, lastX: 0, lastY: 0, startX: 0, startY: 0, moved: false, dx: 0, dy: 0, sent: 0, point: null };
  function flushSwipe(force) {
    const now = Date.now();
    if (!force && now - swipe.sent < 80) return;
    if (!swipe.dx && !swipe.dy) return;
    const box = $("live").getBoundingClientRect();
    const scale = rec.viewport.width / box.width;
    send({ t: "scroll", dx: swipe.dx * scale, dy: swipe.dy * scale, x: swipe.point.x, y: swipe.point.y });
    swipe.dx = 0;
    swipe.dy = 0;
    swipe.sent = now;
  }
  $("live").addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" || swipe.id !== null) return;
    swipe.id = event.pointerId;
    swipe.startX = swipe.lastX = event.clientX;
    swipe.startY = swipe.lastY = event.clientY;
    swipe.moved = false;
    swipe.dx = 0;
    swipe.dy = 0;
    swipe.point = livePoint(event);
    $("live").setPointerCapture(event.pointerId);
  });
  $("live").addEventListener("pointermove", (event) => {
    if (event.pointerId !== swipe.id) return;
    if (!swipe.moved && Math.hypot(event.clientX - swipe.startX, event.clientY - swipe.startY) < 10) return;
    swipe.moved = true;
    swipe.dx += swipe.lastX - event.clientX;
    swipe.dy += swipe.lastY - event.clientY;
    swipe.lastX = event.clientX;
    swipe.lastY = event.clientY;
    flushSwipe(false);
  });
  function endSwipe(event) {
    if (event.pointerId !== swipe.id) return;
    flushSwipe(true);
    if (swipe.moved) swipeEndedAt = Date.now();
    swipe.id = null;
  }
  $("live").addEventListener("pointerup", endSwipe);
  $("live").addEventListener("pointercancel", endSwipe);
  document.querySelectorAll("#rec-picks button").forEach((button) =>
    button.addEventListener("click", () => setPick(rec.pick === button.dataset.kind ? null : button.dataset.kind))
  );
  document.querySelectorAll("#rec-text-form [data-key]").forEach((button) =>
    button.addEventListener("click", () => send({ t: "key", key: button.dataset.key }))
  );
  $("rec-text-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = $("rec-text").value;
    if (!text) return;
    send({ t: "fill", text, as: $("rec-as").value });
    $("rec-text").value = "";
  });
  $("rec-show").addEventListener("change", () => ($("rec-text").type = $("rec-show").checked ? "text" : "password"));
  $("rec-start").addEventListener("click", startRecording);
  $("rec-stop").addEventListener("click", stopRecording);

  $("token-form").addEventListener("submit", connect);
  $("new-profile").addEventListener("click", () => {
    if (rec.active) return say([{ kind: "warn", text: "Bitte zuerst die Aufnahme beenden." }]);
    show({ name: "", description: "", base_url: "http://", timeout_ms: 15000, steps: [{ op: "goto", value: "/" }] }, true);
  });
  $("add-step").addEventListener("click", () => {
    steps.push({ op: "click", selector: "", value: "", comment: "" });
    renderSteps();
  });
  $("validate").addEventListener("click", validate);
  $("save").addEventListener("click", save);
  $("delete").addEventListener("click", remove);

  if (token) {
    $("token").value = token;
    connect();
  }
})();
