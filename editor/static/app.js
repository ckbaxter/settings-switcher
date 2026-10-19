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

  $("token-form").addEventListener("submit", connect);
  $("new-profile").addEventListener("click", () =>
    show({ name: "", description: "", base_url: "http://", timeout_ms: 15000, steps: [{ op: "goto", value: "/" }] }, true)
  );
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
