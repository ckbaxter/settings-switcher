"use strict";

(function () {
  const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
  const SVG_NS = "http://www.w3.org/2000/svg";
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
  let markerStep = null; // Stopmarke: der Schritt, nach dem die Aufnahme weitergehen soll (nur im Browserfenster, nicht im Profil)
  const stepState = new Map(); // Schritt -> "done" | "running" | "paused" (nur während der Wiedergabe bis zur Stopmarke)
  const newSteps = new Set(); // Schritte, die nach der Wiedergabe neu aufgezeichnet wurden
  const suggestions = new Map(); // Schritt -> { loading } | { options, message } (Selektor-Vorschläge aus dem Live-Browser)
  let scrollTarget = null; // Schritt, der nach dem nächsten Zeichnen in den sichtbaren Bereich gescrollt wird
  let profileList = []; // letzter Stand von /api/profiles, für die Übersicht
  let recorderAvailable = false;

  // Pfade der Symbole (24x24, Linien), eigene Zeichnung statt Fremdbibliothek
  const ICON = {
    goto: "M5 12h14M13 6l6 6-6 6",
    click: "M5 3l14 7-6 2-2 6z",
    fill: "M4 7V5h16v2M12 5v14M9 19h6",
    check: "M5 12l4 4 10-10",
    uncheck: "M5 12h14",
    select: "M6 9l6 6 6-6",
    key: "M4 6h16v12H4zM8 10h.01M12 10h.01M16 10h.01M8 14h8",
    clock: "M12 7v5l3 2M12 3a9 9 0 100 18 9 9 0 000-18z",
    expect: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M8.5 12l2.5 2.5 5-5",
    up: "M6 15l6-6 6 6",
    down: "M6 9l6 6 6-6",
    close: "M6 6l12 12M18 6L6 18",
    flag: "M6 21V4M6 5h12l-2 4 2 4H6",
    warn: "M12 3l10 18H2zM12 10v5M12 18v.5",
    lock: "M5 11h14v9H5zM8 11V8a4 4 0 018 0v3",
  };
  const OP_ICON = {
    goto: ICON.goto,
    click: ICON.click,
    click_text: ICON.click,
    fill: ICON.fill,
    check: ICON.check,
    uncheck: ICON.uncheck,
    select_option: ICON.select,
    press: ICON.key,
    wait_for: ICON.clock,
    wait_ms: ICON.clock,
    expect_visible: ICON.expect,
    expect_text: ICON.expect,
    expect_checked: ICON.expect,
    expect_unchecked: ICON.expect,
  };
  const OP_TINT = {
    click: "action",
    click_text: "action",
    check: "ok",
    uncheck: "ok",
    expect_visible: "ok",
    expect_text: "ok",
    expect_checked: "ok",
    expect_unchecked: "ok",
  };
  const STATE_LABEL = { done: "abgespielt", running: "läuft", paused: "angehalten" };
  const PICK_LABEL = {
    expect_text: "Text",
    expect_visible: "Sichtbar",
    expect_checked: "Aktiviert",
    expect_unchecked: "Nicht aktiviert",
    wait_for: "Warten auf",
  };

  function icon(path, size) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", String(size || 16));
    svg.setAttribute("height", String(size || 16));
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.9");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const p = document.createElementNS(SVG_NS, "path");
    p.setAttribute("d", path);
    svg.appendChild(p);
    return svg;
  }

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

  // Meldungen als Toasts: Erfolg verschwindet nach ein paar Sekunden, Fehler und Hinweise bleiben bis zur nächsten Meldung.
  let sayCounter = 0;
  function say(items) {
    const box = $("messages");
    box.replaceChildren();
    const mine = ++sayCounter;
    items.forEach((item) => {
      const close = el("button", { type: "button", class: "msg-close", "aria-label": "Meldung schließen" }, [icon(ICON.close, 14)]);
      close.addEventListener("click", () => say([]));
      const glyph = item.kind === "ok" ? ICON.check : item.kind === "error" ? ICON.close : ICON.warn;
      box.appendChild(
        el("div", { class: "msg " + item.kind }, [
          el("span", { class: "msg-icon" }, [icon(glyph, 16)]),
          el("span", { class: "msg-text", text: item.text }),
          close,
        ])
      );
    });
    if (items.length && items.every((item) => item.kind === "ok")) {
      setTimeout(() => {
        if (sayCounter === mine) box.replaceChildren();
      }, 6000);
    }
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

  // Einschätzung des Selektors nach Muster (Heuristik, keine Garantie)
  function selectorQuality(step) {
    const sel = (step.selector || "").trim();
    if (step.op === "click_text") return step.value ? { level: "ok", text: "stabil · Text" } : null;
    if (!sel) return null;
    if (/^todo/i.test(sel)) return { level: "todo", text: "TODO offen" };
    if (/^(text=|role=)|:has-text\(|:text\(|get_by_/i.test(sel)) return { level: "ok", text: "stabil · Text oder Rolle" };
    if (/^(xpath=|\/\/)|:nth-(child|of-type)\(|>>\s*nth=/i.test(sel)) return { level: "bad", text: "fragil · Position" };
    const id = sel.match(/^#([\w-]+)$/) || sel.match(/\[id=["']?([\w-]+)["']?\]/);
    if (id) {
      return /\d{2,}|[0-9a-f]{8,}/i.test(id[1])
        ? { level: "bad", text: "fragil · generierte ID" }
        : { level: "mid", text: "mittel · ID" };
    }
    if (/\[(name|type|placeholder|aria-label|data-[\w-]+)[~|^$*]?=/i.test(sel)) return { level: "mid", text: "mittel · Attribut" };
    return null;
  }

  function fillQualitySlot(slot, step) {
    slot.replaceChildren();
    const q = selectorQuality(step);
    if (q) {
      slot.appendChild(
        el("span", { class: "pill q-" + q.level, title: "Einschätzung nach Muster, keine Garantie", text: q.text })
      );
    }
    if (q && q.level === "bad") {
      const button = el("button", {
        type: "button",
        class: "suggest-btn",
        text: "Stabileren Selektor vorschlagen",
        title: "Sucht im Live-Browser einen Selektor, der dasselbe Element über Text, Rolle oder Namen trifft",
      });
      button.addEventListener("click", () => requestSuggestion(step));
      slot.appendChild(button);
    }
  }

  // Vorschläge brauchen den Live-Browser: Nur dort lässt sich prüfen, dass ein Selektor genau dieses Element trifft.
  function requestSuggestion(step) {
    if (!rec.active) {
      suggestions.set(step, {
        options: [],
        message: "Dafür muss der Live-Browser laufen: Aufnahme starten, die Seite mit diesem Element öffnen, dann erneut fragen.",
      });
    } else if (!(step.selector || "").trim()) {
      return;
    } else {
      suggestions.set(step, { loading: true });
      rec.suggestFor = step;
      send({ t: "suggest", selector: step.selector });
    }
    renderSteps();
  }

  function suggestPanel(step) {
    const data = suggestions.get(step);
    if (!data) return null;
    const close = el("button", { type: "button", "aria-label": "Vorschläge schließen", title: "Schließen" }, [icon(ICON.close, 14)]);
    close.addEventListener("click", () => {
      suggestions.delete(step);
      renderSteps();
    });
    const head = el("div", { class: "suggest-head" }, [
      el("span", { text: data.loading ? "Suche im Live-Browser …" : data.options.length ? "Trifft genau dieses Element:" : data.message }),
      close,
    ]);
    const box = el("div", { class: "suggest", role: "status" }, [head]);
    (data.options || []).forEach((option) => {
      const q = selectorQuality({ op: "click", selector: option });
      const pick = el("button", { type: "button", class: "suggest-option", title: "Diesen Selektor übernehmen" }, [
        el("code", { text: option }),
        q ? el("span", { class: "pill q-" + q.level, text: q.text }) : el("span"),
      ]);
      pick.addEventListener("click", () => {
        step.selector = option;
        suggestions.delete(step);
        renderSteps();
        say([{ kind: "ok", text: "Selektor ersetzt. Speichern nicht vergessen." }]);
      });
      box.appendChild(pick);
    });
    return box;
  }

  const VAR_ONLY_RE = /^\$\{(SWITCHER_[A-Z0-9_]+)\}$/;
  function fillVarSlot(slot, step) {
    slot.replaceChildren();
    const match = step.op === "fill" ? VAR_ONLY_RE.exec(step.value || "") : null;
    slot.hidden = !match;
    if (!match) return;
    slot.appendChild(el("code", {}, [icon(ICON.lock, 12), el("span", { text: match[1] })]));
    slot.appendChild(el("span", { text: "kommt aus runner.env, nie ins Profil" }));
  }

  function renderSteps() {
    const list = $("steps");
    list.replaceChildren();
    steps.forEach((step, i) => {
      const spec = opSpec(step.op);
      const needsSelector = spec.required.includes("selector");
      const needsValue = spec.required.includes("value");
      const qualitySlot = el("span", { class: "q-slot" });
      const varSlot = el("div", { class: "var-chip", hidden: true });

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
      selector.addEventListener("input", () => {
        step.selector = selector.value;
        fillQualitySlot(qualitySlot, step);
      });

      const value = el("input", {
        value: step.value || "",
        disabled: !needsValue,
        placeholder: needsValue ? (step.op === "fill" ? "Wert oder ${SWITCHER_PASSWORD}" : "Wert") : "",
        maxLength: 500,
        "aria-label": "Wert",
      });
      value.addEventListener("input", () => {
        step.value = value.value;
        fillQualitySlot(qualitySlot, step);
        fillVarSlot(varSlot, step);
      });

      const comment = el("input", {
        value: step.comment || "",
        placeholder: "Notiz",
        maxLength: 500,
        "aria-label": "Notiz",
      });
      comment.addEventListener("input", () => (step.comment = comment.value));

      const up = el("button", { type: "button", title: "Nach oben", "aria-label": "Nach oben", disabled: i === 0 }, [icon(ICON.up, 16)]);
      up.addEventListener("click", () => {
        steps.splice(i - 1, 0, steps.splice(i, 1)[0]);
        renderSteps();
      });
      const down = el(
        "button",
        { type: "button", title: "Nach unten", "aria-label": "Nach unten", disabled: i === steps.length - 1 },
        [icon(ICON.down, 16)]
      );
      down.addEventListener("click", () => {
        steps.splice(i + 1, 0, steps.splice(i, 1)[0]);
        renderSteps();
      });
      const del = el("button", { type: "button", title: "Schritt entfernen", "aria-label": "Schritt entfernen", class: "danger" }, [
        icon(ICON.close, 16),
      ]);
      del.addEventListener("click", () => {
        if (markerStep === step) markerStep = null;
        stepState.delete(step);
        newSteps.delete(step);
        steps.splice(i, 1);
        renderSteps();
      });

      const marked = step === markerStep;
      const flag = el(
        "button",
        {
          type: "button",
          class: "flag" + (marked ? " active" : ""),
          title: marked
            ? "Stopmarke entfernen"
            : "Stopmarke nach diesem Schritt setzen: Die Aufnahme spielt bis hier ab und zeichnet ab hier weiter auf",
          "aria-label": "Stopmarke",
          "aria-pressed": marked ? "true" : "false",
        },
        [icon(ICON.flag, 16)]
      );
      flag.addEventListener("click", () => {
        markerStep = marked ? null : step;
        renderSteps();
      });

      fillQualitySlot(qualitySlot, step);
      fillVarSlot(varSlot, step);

      const state = stepState.get(step);
      const top = el("div", { class: "step-top" }, [el("span", { class: "step-n", text: String(i + 1) }), select, qualitySlot]);
      if (state) top.appendChild(el("span", { class: "pill st-" + state, text: STATE_LABEL[state] }));
      if (newSteps.has(step)) top.appendChild(el("span", { class: "pill st-new", text: "neu" }));

      const tile = el("div", { class: "step-icon tint-" + (OP_TINT[step.op] || "neutral") }, [icon(OP_ICON[step.op] || ICON.click, 18)]);
      const body = el("div", { class: "step-body" }, [top, selector]);
      const panel = suggestPanel(step);
      if (panel) body.appendChild(panel);
      body.appendChild(varSlot);
      body.appendChild(el("div", { class: "step-row" }, [value, comment]));

      list.appendChild(
        el("li", { class: "step" + (state ? " state-" + state : "") }, [tile, body, el("div", { class: "tools" }, [flag, up, down, del])])
      );
      if (marked) {
        list.appendChild(el("li", { class: "marker-line", text: "Stopmarke: bis hier abspielen, ab hier aufzeichnen" }));
      }
    });

    scrollToTarget();
    updateRecMode();
    $("step-count").textContent = String(steps.length);
    $("tab-count").textContent = String(steps.length);
    $("empty-steps").hidden = steps.length > 0;
    $("add-step-end").hidden = steps.length === 0;
    $("no-check").hidden = !(steps.length > 0 && !steps.some((s) => s.op.indexOf("expect_") === 0));
  }

  // Die Schritte scrollen mit: Der gerade abgespielte oder neu aufgezeichnete Schritt bleibt neben dem Live-Browser im Bild.
  function scrollToTarget() {
    const target = scrollTarget;
    scrollTarget = null;
    const at = target ? steps.indexOf(target) : -1;
    const item = at >= 0 ? $("steps").querySelectorAll(".step")[at] : null;
    if (!item) return;
    const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    item.scrollIntoView({ block: "center", behavior: calm ? "auto" : "smooth" });
  }

  // Beschriftung des Aufnahme-Knopfs: Bei einem Profil mit Schritten wird nichts neu aufgenommen, sondern ergänzt.
  function recMode() {
    const markerAt = markerStep ? steps.indexOf(markerStep) : -1;
    if (markerAt >= 0) {
      return {
        label: "Ab Stopmarke aufnehmen",
        hint: "Spielt die ersten " + (markerAt + 1) + " Schritte ab (wird nicht aufgezeichnet) und zeichnet dahinter weiter auf.",
      };
    }
    if (steps.length > 1) {
      return {
        label: "Schritte anhängen",
        hint:
          "Das Profil hat " + steps.length + " Schritte und bleibt unverändert. Neue Schritte kommen ans Ende. " +
          "Soll es mitten im Ablauf weitergehen, setze mit ⚑ eine Stopmarke.",
      };
    }
    return { label: "Aufnahme starten", hint: "Der Browser öffnet den Startpfad, jede Aktion wird ein Schritt." };
  }

  function updateRecMode() {
    const mode = recMode();
    $("rec-start-label").textContent = mode.label;
    $("rec-mode").textContent = mode.hint;
    $("rec-mode").hidden = rec.active;
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

  function setTab(name) {
    $("workspace").dataset.tab = name;
    $("tab-browser").setAttribute("aria-selected", name === "browser" ? "true" : "false");
    $("tab-steps").setAttribute("aria-selected", name === "steps" ? "true" : "false");
  }

  function show(profile, fresh) {
    isNew = fresh;
    $("overview").hidden = true;
    $("editor").hidden = false;
    suggestions.clear();
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
    markerStep = null;
    stepState.clear();
    newSteps.clear();
    setTab("steps");
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
    profileList = res.data;
    if (!$("overview").hidden) renderOverview();
    res.data.forEach((p) => {
      const button = el(
        "button",
        { type: "button", class: p.name === activeName ? "active" : "" },
        [el("span", { class: "p-name", text: p.name }), el("span", { class: "sub", text: p.steps + " Schritte · " + p.description })]
      );
      button.addEventListener("click", () => openProfile(p.name));
      list.appendChild(el("li", {}, [button]));
    });
  }

  // ---------- Profilübersicht ----------

  function formatChanged(seconds) {
    if (!seconds) return "Änderungsdatum unbekannt";
    const when = new Date(seconds * 1000);
    return "Zuletzt geändert: " + when.toLocaleDateString("de-DE") + ", " + when.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  }

  function profileCard(p) {
    const ready = !p.todo;
    const edit = el("button", { type: "button", text: "Bearbeiten" });
    edit.addEventListener("click", () => openProfile(p.name));
    const actions = [edit];
    if (recorderAvailable) {
      const extend = p.steps > 1;
      const record = el(
        "button",
        {
          type: "button",
          class: "rec-btn",
          title: extend
            ? "Öffnet das Profil und startet eine Aufnahme. Die vorhandenen Schritte bleiben, neue kommen ans Ende."
            : "Öffnet das Profil und startet eine Aufnahme.",
        },
        [el("span", { text: extend ? "Schritte anhängen" : "Aufnehmen" })]
      );
      record.prepend(icon("M12 4a8 8 0 100 16 8 8 0 000-16zM12 9a3 3 0 100 6 3 3 0 000-6z", 14));
      record.addEventListener("click", async () => {
        await openProfile(p.name);
        if (!$("editor").hidden && !rec.active) startRecording();
      });
      actions.push(record);
    }
    return el("article", { class: "pcard" }, [
      el("div", { class: "pcard-top" }, [
        el("div", {}, [
          el("h3", { text: p.name }),
          el("div", { class: "pcard-desc", text: p.description || "Keine Beschreibung" }),
        ]),
        el("span", {
          class: "badge " + (ready ? "ok" : "warn"),
          title: ready ? "Kein TODO im Profil" : "Der Runner führt Profile mit TODO nicht aus",
          text: ready ? "Bereit" : "TODO offen",
        }),
      ]),
      el("div", { class: "pcard-chips" }, [
        el("span", { class: "chip", text: p.steps + (p.steps === 1 ? " Schritt" : " Schritte") }),
        el("span", { class: "chip " + (p.check ? "ok" : "warn"), text: p.check ? "Prüft Ergebnis" : "Keine Prüfung" }),
      ]),
      el("div", { class: "pcard-meta", text: formatChanged(p.modified) }),
      el("div", { class: "pcard-actions" }, actions),
    ]);
  }

  function renderOverview() {
    const grid = $("overview-grid");
    grid.replaceChildren();
    $("overview-sub").textContent =
      profileList.length + (profileList.length === 1 ? " Profil" : " Profile") + ". Zugangsdaten liegen nur in runner.env, nie im Profil.";
    profileList.forEach((p) => grid.appendChild(profileCard(p)));
    const fresh = el("button", { type: "button", class: "pcard pcard-new" }, [
      el("span", { class: "plus" }, [icon("M12 5v14M5 12h14", 20)]),
      el("strong", { text: "Neues Profil" }),
      el("span", { text: "Startet mit einem leeren Ablauf für eine Weboberfläche." }),
    ]);
    fresh.addEventListener("click", newProfile);
    grid.appendChild(fresh);
  }

  function showOverview() {
    $("editor").hidden = true;
    $("overview").hidden = false;
    renderOverview();
    document.querySelectorAll("#profile-list .active").forEach((node) => node.classList.remove("active"));
  }

  function newProfile() {
    if (rec.active) return say([{ kind: "warn", text: "Bitte zuerst die Aufnahme beenden." }]);
    show({ name: "", description: "", base_url: "http://", timeout_ms: 15000, steps: [{ op: "goto", value: "/" }] }, true);
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

  function showConnected(connected) {
    $("token-form").hidden = connected;
    $("conn-ok").hidden = !connected;
    $("token-change").hidden = !connected;
  }

  async function connect(event) {
    if (event) event.preventDefault();
    token = $("token").value || token;
    const res = await api("GET", "/api/ops");
    if (!res.ok) {
      showConnected(false);
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
    showConnected(true);
    say([]);
    await initRecorder();
    await loadList(null);
    showOverview();
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
    await loadList(null);
    showOverview();
  }


  // ---------- Aufnahme-Modus ----------
  // insert/after: neue Schritte kommen hinter den Schritt "after" (Stopmarke), statt ans Ende.
  // replaySteps: die Schritte, die der Recorder bis zur Marke abspielt (zum Zuordnen von "at").
  const rec = { ws: null, active: false, viewport: { width: 1280, height: 800 }, pick: null, frame: null, insert: false, after: null, replaySteps: null, suggestFor: null };

  function note(kind, text) {
    const box = $("rec-note");
    box.className = "msg " + kind;
    box.textContent = text;
  }

  // Aufnahmezeit seit Beginn in diesem Fenster
  let timerId = null;
  function startTimer() {
    const began = Date.now();
    const tick = () => {
      const seconds = Math.floor((Date.now() - began) / 1000);
      $("rec-time").textContent = String(Math.floor(seconds / 60)).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
    };
    stopTimer();
    tick();
    timerId = setInterval(tick, 1000);
  }
  function stopTimer() {
    if (timerId !== null) clearInterval(timerId);
    timerId = null;
  }

  function setRecording(active) {
    rec.active = active;
    $("rec-start").hidden = active;
    $("rec-stop").hidden = !active;
    $("rec-live").hidden = !active;
    $("rec-placeholder").hidden = active;
    $("rec-pill").hidden = !active;
    updateRecMode();
    $("rec-path").disabled = active;
    if (active) {
      startTimer();
      setTab("browser");
    } else {
      stopTimer();
      setTab("steps");
      setPick(null);
      if (rec.frame) URL.revokeObjectURL(rec.frame);
      rec.frame = null;
      $("live").removeAttribute("src");
      $("rec-select").hidden = true;
      $("rec-replay").hidden = true;
      rec.insert = false;
      rec.after = null;
      rec.replaySteps = null;
      markerStep = null; // die Marke gehörte zu dieser Aufnahme
      suggestions.clear();
      rec.suggestFor = null;
      stepState.clear();
      newSteps.clear();
      renderSteps();
    }
  }

  // Anzeige der Wiedergabe bis zur Stopmarke. buttons: welche Knöpfe gerade Sinn haben.
  function showReplay(text, buttons) {
    $("rec-replay").hidden = false;
    $("rec-replay-text").textContent = text;
    $("rp-resume").hidden = !buttons.resume;
    $("rp-retry").hidden = !buttons.retry;
    $("rp-resume").textContent = buttons.resume || "";
  }

  // Schrittkarten während der Wiedergabe färben: davor "abgespielt", der aktuelle läuft oder ist angehalten
  function markReplay(index, state) {
    if (!rec.replaySteps) return;
    stepState.clear();
    rec.replaySteps.forEach((s, n) => {
      if (n < index - 1) stepState.set(s, "done");
      else if (n === index - 1) stepState.set(s, state);
    });
    scrollTarget = rec.replaySteps[index - 1] || null;
    renderSteps();
  }

  function onReplayDone(event) {
    $("rec-replay").hidden = true;
    if (rec.replaySteps) {
      // Neue Schritte kommen hinter den letzten abgespielten bzw. übersprungenen Schritt.
      rec.after = event.at > 0 ? rec.replaySteps[event.at - 1] : null;
      rec.insert = true;
      stepState.clear();
      rec.replaySteps.forEach((s, n) => {
        if (n < event.at) stepState.set(s, "done");
      });
      renderSteps();
    }
    if (!rec.replaySteps) return note("ok", "Wiedergabe beendet. Jetzt wird aufgezeichnet.");
    const where = event.at > 0 ? "hinter Schritt " + event.at : "am Anfang";
    note("ok", "Wiedergabe beendet. Jetzt wird aufgezeichnet, neue Schritte kommen " + where + ".");
  }

  function setPick(kind) {
    rec.pick = kind;
    document.querySelectorAll("#rec-picks button").forEach((b) => b.classList.toggle("active", b.dataset.kind === kind));
    const banner = $("pick-banner");
    banner.hidden = !kind;
    if (kind) {
      const label = PICK_LABEL[kind] || kind;
      banner.textContent = (kind === "wait_for" ? label : "Prüfung „" + label + "“") + ": Element im Bild anklicken";
    }
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

  function showViewportSize() {
    $("rec-size").textContent = rec.viewport.width + " × " + rec.viewport.height;
  }

  function onRecEvent(event) {
    if (event.t === "hello") {
      rec.viewport = event.viewport;
      showViewportSize();
      $("rec-url").textContent = event.url || "";
    } else if (event.t === "step") {
      const added = { op: event.step.op, selector: event.step.selector || "", value: event.step.value || "", comment: event.step.comment || "" };
      const at = rec.insert && rec.after ? steps.indexOf(rec.after) : -1;
      if (rec.insert && rec.after && at < 0) rec.insert = false; // der Bezugsschritt wurde entfernt: ans Ende
      if (rec.insert) {
        steps.splice(at + 1, 0, added); // at = -1: ganz an den Anfang
        rec.after = added;
        newSteps.add(added);
      } else {
        steps.push(added);
      }
      scrollTarget = added;
      renderSteps();
    } else if (event.t === "replay") {
      showReplay("Wiedergabe: Schritt " + event.index + " von " + event.total + " (" + event.label + ")", { resume: "", retry: false });
      markReplay(event.index, "running");
    } else if (event.t === "replay_pause") {
      const resume = event.kind === "manual" ? "Erledigt, weiter" : "Schritt überspringen";
      showReplay(event.message, { resume, retry: !!event.can_retry });
      markReplay(event.index, "paused");
    } else if (event.t === "replay_done") {
      onReplayDone(event);
    } else if (event.t === "url") {
      $("rec-url").textContent = event.url;
    } else if (event.t === "blocked") {
      note("warn", "Anfrage an nicht erlaubten Host blockiert: " + event.host);
    } else if (event.t === "dialog") {
      note("warn", "Die Seite zeigte einen Dialog (wird verworfen): " + event.message);
    } else if (event.t === "popup") {
      note("warn", "Ein Popup wurde geschlossen.");
    } else if (event.t === "suggest") {
      const step = rec.suggestFor;
      if (step && suggestions.has(step) && step.selector === event.selector) {
        suggestions.set(step, { options: event.options || [], message: event.message || "" });
        rec.suggestFor = null;
        renderSteps();
      }
    } else if (event.t === "error") {
      rec.lastError = event.message;
      note("error", event.message);
      const waiting = rec.suggestFor;
      if (waiting && suggestions.has(waiting) && suggestions.get(waiting).loading) {
        suggestions.set(waiting, { options: [], message: event.message });
        rec.suggestFor = null;
        renderSteps();
      }
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
    const body = { base_url: $("f-base").value.trim(), path: $("rec-path").value.trim() || "/" };
    // Mit Stopmarke: Schritte bis zur Marke werden erst abgespielt, danach wird dahinter weiter aufgezeichnet
    const markerAt = markerStep ? steps.indexOf(markerStep) : -1;
    const replaySteps = markerAt >= 0 ? steps.slice(0, markerAt + 1) : null;
    if (replaySteps) {
      body.replay = replaySteps.map((s) => {
        const out = { op: s.op };
        if (s.selector) out.selector = s.selector;
        if (s.value) out.value = s.value;
        return out;
      });
    }
    const res = await api("POST", "/api/rec/start", body);
    if (!res.ok) return say(apiError(res));
    rec.replaySteps = replaySteps;
    rec.insert = false;
    rec.after = null;
    stepState.clear();
    newSteps.clear();
    if (!replaySteps) {
      const start = { op: res.data.step.op, selector: "", value: res.data.step.value, comment: "" };
      // Ein leeres oder nur aus dem Start-goto bestehendes Profil wird ersetzt, sonst angehängt
      if (steps.length === 0 || (steps.length === 1 && steps[0].op === "goto")) steps = [start];
      else steps.push(start);
    }
    renderSteps();
    say([]);
    note("warn", "");
    setRecording(true);
    if (replaySteps) showReplay("Wiedergabe startet …", { resume: "", retry: false });
    openSocket();
  }

  async function stopRecording() {
    await api("POST", "/api/rec/stop");
    if (rec.ws) rec.ws.close();
    setRecording(false);
  }

  async function initRecorder() {
    const config = await api("GET", "/api/config");
    const available = config.ok && config.data.recorder;
    recorderAvailable = !!available;
    $("recorder").hidden = !available;
    $("workspace").classList.toggle("no-rec", !available);
    $("editor").classList.toggle("no-rec", !available);
    $("tabs").hidden = !available;
    $("mode-tag").hidden = !available;
    if (!available) return;
    rec.viewport = config.data.viewport;
    showViewportSize();
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
  $("rp-resume").addEventListener("click", () => send({ t: "replay_resume" }));
  $("rp-retry").addEventListener("click", () => send({ t: "replay_retry" }));
  $("rp-stop").addEventListener("click", () => send({ t: "replay_stop" }));

  $("token-form").addEventListener("submit", connect);
  $("token-change").addEventListener("click", () => {
    showConnected(false);
    $("token").focus();
  });
  $("tab-browser").addEventListener("click", () => setTab("browser"));
  $("tab-steps").addEventListener("click", () => setTab("steps"));
  $("new-profile").addEventListener("click", newProfile);
  $("overview-new").addEventListener("click", newProfile);
  $("to-overview").addEventListener("click", () => {
    if (rec.active) return say([{ kind: "warn", text: "Bitte zuerst die Aufnahme beenden." }]);
    showOverview();
  });
  // Oben: neuer Schritt ganz am Anfang. Unten: ans Ende anhängen.
  function addStep(atStart) {
    const step = { op: "click", selector: "", value: "", comment: "" };
    if (atStart) steps.unshift(step);
    else steps.push(step);
    scrollTarget = step;
    renderSteps();
  }
  $("add-step").addEventListener("click", () => addStep(true));
  $("add-step-end").addEventListener("click", () => addStep(false));
  // Hinweis "Keine Prüfung": während der Aufnahme direkt ins Bild klicken, sonst einen Prüfschritt anlegen
  $("add-check").addEventListener("click", () => {
    if (rec.active) {
      setTab("browser");
      setPick("expect_checked");
      note("ok", "Prüfung „Aktiviert“ gewählt: Element im Bild anklicken.");
      return;
    }
    steps.push({ op: "expect_checked", selector: "", value: "", comment: "Ergebnis prüfen" });
    renderSteps();
    const inputs = document.querySelectorAll('#steps .step input[aria-label="Selektor"]');
    if (inputs.length) inputs[inputs.length - 1].focus();
  });
  $("validate").addEventListener("click", validate);
  $("save").addEventListener("click", save);
  $("delete").addEventListener("click", remove);
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s" && !$("editor").hidden) {
      event.preventDefault();
      save();
    }
  });

  setPick(null);
  if (token) {
    $("token").value = token;
    connect();
  }
})();
