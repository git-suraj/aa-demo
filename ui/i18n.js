// Lightweight, dependency-free i18n runtime for the static dashboard.
//
// Message data is provided by /i18n-active.js (generated at nginx container
// startup from the language YAML selected via the UI_LANG env var) as a flat
// map on window.I18N_MESSAGES, where each value is either a string or a list of
// strings. The active language code is on window.APP_CONFIG.lang.
//
// Design note: translations are applied "overwrite-only-if-resolved" — if a key
// is missing from the active dictionary (e.g. the generated file is absent when
// serving the files directly without the container), the original English text
// baked into index.html / app.js is left untouched. The page therefore always
// renders, with or without the generated dictionary.
(function () {
  "use strict";

  const messages = (window.I18N_MESSAGES && typeof window.I18N_MESSAGES === "object")
    ? window.I18N_MESSAGES
    : {};
  const lang = (window.APP_CONFIG && window.APP_CONFIG.lang) || "en";

  const warned = new Set();
  function warnMissing(key) {
    if (warned.has(key)) return;
    warned.add(key);
    // Non-fatal: missing keys fall back to the inline English default.
    if (typeof console !== "undefined" && console.debug) {
      console.debug(`[i18n] missing key for "${lang}": ${key}`);
    }
  }

  function has(key) {
    return Object.prototype.hasOwnProperty.call(messages, key) && messages[key] != null;
  }

  function interpolate(str, vars) {
    if (!vars || typeof str !== "string") return str;
    return str.replace(/\{(\w+)\}/g, (match, name) =>
      Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : match
    );
  }

  // Translate a single string key. If `fallback` is provided it is used when the
  // key is missing; otherwise the key itself is returned (and a debug warning is
  // logged). `vars` supports {name} placeholder interpolation.
  function t(key, vars, fallback) {
    if (has(key)) {
      const value = messages[key];
      if (Array.isArray(value)) return value.map((v) => interpolate(v, vars)).join(" ");
      return interpolate(value, vars);
    }
    warnMissing(key);
    if (fallback != null) return interpolate(fallback, vars);
    return key;
  }

  // Translate a key whose value is a list of strings (e.g. bullet lists, or
  // [label, value] config rows). Returns an array; falls back to `fallback`
  // (default []) when the key is missing.
  function tList(key, vars, fallback) {
    // Native AI Gateway Model and policy bindings are maintained with kongctl.
    // Keep these scenario configuration rows sourced from app.js so the +
    // dialog cannot fall back to the legacy plugin inventory translations.
    if (key.startsWith("policies.") && (key.endsWith(".config") || key.includes(".config."))) {
      return Array.isArray(fallback) ? fallback : [];
    }
    if (has(key)) {
      const value = messages[key];
      const arr = Array.isArray(value) ? value : [value];
      return arr.map((v) => (Array.isArray(v) ? v.map((x) => interpolate(x, vars)) : interpolate(v, vars)));
    }
    warnMissing(key);
    return Array.isArray(fallback) ? fallback : [];
  }

  // Apply translations to static markup. Only overwrites when the key resolves,
  // so untranslated nodes keep their inline English default.
  function applyStaticTranslations(root) {
    const scope = root || document;

    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (has(key)) el.textContent = t(key);
    });
    scope.querySelectorAll("[data-i18n-html]").forEach((el) => {
      const key = el.getAttribute("data-i18n-html");
      if (has(key)) el.innerHTML = t(key);
    });
    [
      ["data-i18n-placeholder", "placeholder"],
      ["data-i18n-title", "title"],
      ["data-i18n-aria-label", "aria-label"],
    ].forEach(([attr, target]) => {
      scope.querySelectorAll(`[${attr}]`).forEach((el) => {
        const key = el.getAttribute(attr);
        if (has(key)) el.setAttribute(target, t(key));
      });
    });
  }

  try {
    document.documentElement.lang = lang;
  } catch (e) {
    /* no-op */
  }

  const i18n = { lang, t, tList, has, applyStaticTranslations };
  window.i18n = i18n;
  window.t = t;
  window.tList = tList;

  // Apply once when this script runs. app.js (deferred, loaded after i18n.js) owns
  // elements it updates at runtime — do not re-apply on DOMContentLoaded or live
  // run labels (run id, flow stage, run state) get reset mid-scenario.
  applyStaticTranslations();
})();
