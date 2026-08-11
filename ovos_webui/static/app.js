/* ovos-webui — plain browser JavaScript. No build step, no CDN. */
(function () {
  "use strict";

  // Apply the saved theme immediately, at head-parse time, before the body
  // paints — so a viewer who chose light never sees a dark flash and back.
  var THEME_KEY = "ovos-theme", THEMES = ["system", "dark", "light"];
  function storedTheme() {
    try {
      var v = window.localStorage.getItem(THEME_KEY);
      return THEMES.indexOf(v) === -1 ? "system" : v;
    } catch (e) { return "system"; }
  }
  function applyTheme(theme) {
    var root = document.documentElement;
    if (theme === "system") { root.removeAttribute("data-theme"); }
    else { root.setAttribute("data-theme", theme); }
  }
  applyTheme(storedTheme());

  // The token is never put in a URL. A sign in exchanges it for a cookie that
  // only this site can send, so nothing ends up in an access log or in the
  // browser history.
  function api(path, options) {
    options = options || {};
    options.credentials = "same-origin";
    return fetch(path, options).then(function (r) {
      if (r.status === 401) {
        window.location.href = "/login";
        throw new Error(t("err.signin", "Sign in first."));
      }
      if (r.status === 403) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          throw new Error(b.detail || t("err.notallowed", "That is not allowed."));
        });
      }
      var ctype = r.headers.get("content-type") || "";
      if (ctype.indexOf("json") === -1) {
        if (!r.ok) { throw new Error(t("err.failed", "Request failed") + " (" + r.status + ")"); }
        return r.text();
      }
      return r.json().then(function (body) {
        if (!r.ok) { throw new Error(body.detail || (t("err.failed", "Request failed") + " (" + r.status + ")")); }
        return body;
      });
    });
  }

  function el(id) { return document.getElementById(id); }

  function say(id, text, bad) {
    var box = el(id);
    if (!box) { return; }
    box.textContent = text;
    box.className = "msg " + (bad ? "err" : "ok");
    box.hidden = false;
  }

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // ── translation ───────────────────────────────────────────────────────────
  // Right-to-left languages, by their base code.
  var RTL = {ar: 1, he: 1, fa: 1, ur: 1, ps: 1, sd: 1, ug: 1, yi: 1, dv: 1, ckb: 1};
  var STRINGS = {};

  // Return the translation for a key, or the fallback text as written on the
  // page. A missing translation never breaks the page: it falls back.
  function t(key, fallback) {
    if (key && Object.prototype.hasOwnProperty.call(STRINGS, key)) { return STRINGS[key]; }
    return fallback !== undefined ? fallback : key;
  }

  // Replace the text of every [data-i18n] element, and the attributes named in
  // [data-i18n-attr] (e.g. "placeholder:key;title:key"). The English text
  // already in the page is the fallback, so nothing disappears when a locale
  // has no entry.
  // Translating a label that wraps a control must not wipe the control:
  // only the element's own text is replaced, child elements stay.
  function firstTextNode(node) {
    for (var i = 0; i < node.childNodes.length; i++) {
      var c = node.childNodes[i];
      if (c.nodeType === 3 && c.nodeValue.trim()) { return c; }
    }
    return null;
  }

  function applyI18n(root) {
    (root || document).querySelectorAll("[data-i18n]").forEach(function (node) {
      var key = node.getAttribute("data-i18n");
      if (node.children.length === 0) {
        node.textContent = t(key, node.textContent);
        return;
      }
      var text = firstTextNode(node);
      if (text) {
        text.nodeValue = t(key, text.nodeValue);
      } else {
        // Only formatting children (e.g. a lone <strong> wrapper): the whole
        // node is the message, so replace it rather than prepend a duplicate.
        // Never do this when a control is inside — it must not be destroyed.
        if (!node.querySelector("input,select,textarea,button")) {
          node.textContent = t(key, node.textContent);
        }
      }
    });
    (root || document).querySelectorAll("[data-i18n-attr]").forEach(function (node) {
      node.getAttribute("data-i18n-attr").split(";").forEach(function (pair) {
        var bits = pair.split(":");
        if (bits.length === 2) {
          var attr = bits[0].trim(), key = bits[1].trim();
          node.setAttribute(attr, t(key, node.getAttribute(attr) || ""));
        }
      });
    });
  }

  function setLangDir(lang) {
    lang = (lang || "en").toLowerCase();
    var base = lang.split("-")[0];
    document.documentElement.lang = lang;
    document.documentElement.dir = RTL[base] ? "rtl" : "ltr";
    return base;
  }

  // Load the locale file for a language, fall back to English, and apply it.
  function loadLocale(lang) {
    var base = setLangDir(lang);
    if (base === "en") { return Promise.resolve(); }
    return fetch("/static/i18n/" + base + ".json", {credentials: "same-origin"})
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (dict) { STRINGS = dict || {}; applyI18n(document); })
      .catch(function () { /* keep the English already on the page */ });
  }

  function markNav() {
    var here = window.location.pathname.replace(/\/$/, "") || "/";
    document.querySelectorAll("nav a").forEach(function (a) {
      var target = a.getAttribute("href").replace(/\/$/, "") || "/";
      if (target === here) { a.setAttribute("aria-current", "page"); }
    });
  }

  // A theme control lives in every header without touching each page's markup.
  // It cycles system → dark → light, persists the choice, and names the
  // current state for a screen reader.
  var THEME_ICON = {system: "◐", dark: "☾", light: "☀"};
  function themeName(theme) {
    return t("theme." + theme, theme === "system" ? "match my device"
      : (theme === "dark" ? "dark" : "light"));
  }
  function labelThemeButton(button, theme) {
    button.textContent = THEME_ICON[theme];
    button.setAttribute("aria-label", t("theme.label", "Theme:") + " " + themeName(theme)
      + " — " + t("theme.change", "change"));
    button.setAttribute("title", t("theme.label", "Theme:") + " " + themeName(theme));
  }
  function mountThemeToggle() {
    var header = document.querySelector("header");
    if (!header || document.getElementById("theme-toggle")) { return; }
    var button = document.createElement("button");
    button.id = "theme-toggle";
    button.type = "button";
    button.className = "theme-toggle";
    // A polite live region so the change is announced, not left to the screen
    // reader re-reading the focused control.
    var live = document.createElement("span");
    live.className = "visually-hidden";
    live.setAttribute("aria-live", "polite");
    var theme = storedTheme();
    labelThemeButton(button, theme);
    button.addEventListener("click", function () {
      theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
      try { window.localStorage.setItem(THEME_KEY, theme); } catch (e) { /* ignore */ }
      applyTheme(theme);
      labelThemeButton(button, theme);
      live.textContent = t("theme.label", "Theme:") + " " + themeName(theme);
    });
    header.appendChild(button);
    header.appendChild(live);
  }

  function showBanner(status) {
    var b = el("banner");
    if (b && status && status.warning) { b.textContent = status.warning; b.hidden = false; }
  }

  // One date renderer for the whole UI: "11 Aug 2026, 10:12" — never a locale
  // DD/MM vs MM/DD guess, never trailing seconds. Accepts a Date, epoch ms, or
  // a "YYYYMMDDTHHMMSSZ" backup stamp.
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtDateTime(value) {
    var d;
    if (value instanceof Date) {
      d = value;
    } else if (typeof value === "number") {
      d = new Date(value);
    } else {
      var m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(String(value));
      if (!m) { return String(value); }
      d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]));
    }
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getDate() + " " + MONTHS[d.getMonth()] + " " + d.getFullYear()
      + ", " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  window.OvosWebUI = {
    api: api, el: el, say: say, esc: esc, t: t, applyI18n: applyI18n,
    fmtDateTime: fmtDateTime,
    ready: function (fn) {
      document.addEventListener("DOMContentLoaded", function () {
        markNav();
        mountThemeToggle();
        // One status call drives both the language/direction and the banner,
        // then the page runs with translations already applied.
        api("/api/status").then(function (s) {
          showBanner(s);
          return loadLocale(s && s.lang);
        }).catch(function () { /* offline or not signed in: stay in English */ })
          .then(function () {
            try { fn(); } catch (e) { console.error(e); }
          });
      });
    },
    confirmed: function (question) { return window.confirm(question); }
  };
})();
