"use strict";

// Darstellung: automatisch (Systemeinstellung), hell oder dunkel. Der Knopf schaltet der Reihe nach weiter.
// Das Skript steht im <head>, damit die Seite nicht erst hell aufblitzt und dann dunkel wird.
(function () {
  const KEY = "ss-theme";
  const ORDER = ["auto", "light", "dark"];
  const LABEL = {
    auto: "automatisch (nach Systemeinstellung)",
    light: "hell",
    dark: "dunkel",
  };
  const PATHS = {
    auto: ["M12 3a9 9 0 100 18 9 9 0 000-18z", "M12 3v18"],
    light: ["M12 8a4 4 0 100 8 4 4 0 000-8z", "M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"],
    dark: ["M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z"],
  };

  function read() {
    try {
      const value = localStorage.getItem(KEY);
      return ORDER.indexOf(value) >= 0 ? value : "auto";
    } catch (e) {
      return "auto";
    }
  }

  let mode = read();

  function apply() {
    const root = document.documentElement;
    if (mode === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", mode);
  }

  function icon(kind) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.9");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    PATHS[kind].forEach((d) => {
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    });
    return svg;
  }

  function paint(button) {
    const next = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
    button.replaceChildren(icon(mode));
    button.title = "Darstellung: " + LABEL[mode] + ". Klicken für " + LABEL[next] + ".";
    button.setAttribute("aria-label", button.title);
  }

  apply();

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("theme-toggle");
    if (!button) return;
    paint(button);
    button.addEventListener("click", () => {
      mode = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
      try {
        if (mode === "auto") localStorage.removeItem(KEY);
        else localStorage.setItem(KEY, mode);
      } catch (e) {
        /* Speichern ist nur eine Bequemlichkeit */
      }
      apply();
      paint(button);
    });
  });
})();
