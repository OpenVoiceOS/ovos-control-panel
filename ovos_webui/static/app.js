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

  // Larger-text mode, applied at head-parse time too so text never jumps size
  // after the page paints. Cycles normal → large → larger.
  var TEXT_KEY = "ovos-text", TEXT_SIZES = ["normal", "large", "xlarge"];
  function storedText() {
    try {
      var v = window.localStorage.getItem(TEXT_KEY);
      return TEXT_SIZES.indexOf(v) === -1 ? "normal" : v;
    } catch (e) { return "normal"; }
  }
  function applyText(size) {
    var root = document.documentElement;
    if (size === "normal") { root.removeAttribute("data-text"); }
    else { root.setAttribute("data-text", size); }
  }
  applyText(storedText());

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

  // Like say(), but the caller has already escaped/built the markup (e.g. to
  // include a link). Used sparingly, only where a message needs an inline link.
  function sayHtml(id, html, bad) {
    var box = el(id);
    if (!box) { return; }
    box.innerHTML = html;
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

  // The one place the site navigation is defined. Every page carries an empty
  // (or fallback) <nav aria-label="Site">; this fills it, so a new page is
  // added here once rather than in every file.
  var NAV = [
    ["/", "nav.dashboard", "Dashboard"],
    ["/tryit", "nav.tryit", "Try it"],
    ["/controls", "nav.controls", "Device"],
    ["/media", "nav.media", "Media"],
    ["/apps", "nav.apps", "Apps"],
    ["/network", "nav.network", "Network"],
    ["/servers", "nav.servers", "Servers"],
    ["/system", "nav.system", "System"],
    ["/sensors", "nav.sensors", "Sensors"],
    ["/mark1", "nav.mark1", "Mark-1 faceplate"],
    ["/wallpaper", "nav.wallpaper", "Wallpaper"],
    ["/config", "nav.settings", "Settings"],
    ["/voice", "nav.voice", "Voice settings"],
    ["/skills", "nav.skills", "Skills"],
    ["/abilities", "nav.abilities", "Abilities"],
    ["/intents", "nav.intents", "Intents"],
    ["/plugins", "nav.plugins", "Plugins"],
    ["/transformers", "nav.transformers", "Transformers"],
    ["/personas", "nav.personas", "Personas"],
    ["/translate", "nav.translate", "Translate"],
    ["/sound", "nav.sound", "Send over sound"],
    ["/backup", "nav.backup", "Backup"],
    ["/about", "nav.about", "About"]
  ];
  // Simple mode hides the advanced pages, leaving only what a non-technical
  // owner needs day to day. It is a per-browser choice, off by default, and it
  // only changes which nav links show — every page still works if reached
  // directly. The page you are on is always kept in the nav so a link can never
  // strand you on a hidden page.
  var SIMPLE_KEY = "ovos-simple";
  var SIMPLE_PATHS = {"/": 1, "/tryit": 1, "/controls": 1, "/voice": 1,
                      "/config": 1, "/network": 1, "/backup": 1};
  function simpleMode() {
    try { return window.localStorage.getItem(SIMPLE_KEY) === "1"; } catch (e) { return false; }
  }
  function renderNav() {
    var nav = document.querySelector('nav[aria-label], nav#sitenav');
    if (!nav) { return; }
    var here = window.location.pathname.replace(/\/$/, "") || "/";
    var items = simpleMode()
      ? NAV.filter(function (x) { return SIMPLE_PATHS[x[0]] || x[0] === here; })
      : NAV;
    nav.innerHTML = items.map(function (item) {
      return '<a href="' + item[0] + '" data-i18n="' + item[1] + '">'
        + esc(t(item[1], item[2])) + "</a>";
    }).join("");
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

  // A Simple-mode control lives in every header, next to the theme control. It
  // shows or hides the advanced pages and re-draws the nav in place.
  function labelSimpleButton(button) {
    var on = simpleMode();
    button.textContent = on ? "☰" : "⋯";
    button.setAttribute("aria-pressed", on ? "true" : "false");
    var label = on ? t("simple.on", "Simple view on — show all pages")
      : t("simple.off", "Show only the everyday pages");
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
  }
  function mountSimpleToggle() {
    var header = document.querySelector("header");
    if (!header || document.getElementById("simple-toggle")) { return; }
    var button = document.createElement("button");
    button.id = "simple-toggle";
    button.type = "button";
    button.className = "theme-toggle";
    var live = document.createElement("span");
    live.className = "visually-hidden";
    live.setAttribute("aria-live", "polite");
    labelSimpleButton(button);
    button.addEventListener("click", function () {
      var next = simpleMode() ? "0" : "1";
      try { window.localStorage.setItem(SIMPLE_KEY, next); } catch (e) { /* ignore */ }
      labelSimpleButton(button);
      renderNav();
      markNav();
      applyI18n(document.querySelector('nav[aria-label], nav#sitenav'));
      live.textContent = simpleMode()
        ? t("simple.nowOn", "Showing only the everyday pages.")
        : t("simple.nowOff", "Showing all pages.");
    });
    header.appendChild(button);
    header.appendChild(live);
  }

  // A larger-text control in every header. Cycles normal → large → larger,
  // persists the choice, and names the current size for a screen reader.
  var TEXT_NAME = {normal: "normal", large: "large", xlarge: "largest"};
  function labelTextButton(button, size) {
    button.textContent = "A";
    button.style.fontSize = size === "xlarge" ? "1.3em" : (size === "large" ? "1.15em" : "1em");
    var name = t("text." + size, TEXT_NAME[size]);
    button.setAttribute("aria-label", t("text.label", "Text size:") + " " + name
      + " — " + t("theme.change", "change"));
    button.setAttribute("title", t("text.label", "Text size:") + " " + name);
  }
  function mountTextToggle() {
    var header = document.querySelector("header");
    if (!header || document.getElementById("text-toggle")) { return; }
    var button = document.createElement("button");
    button.id = "text-toggle";
    button.type = "button";
    button.className = "theme-toggle";
    var live = document.createElement("span");
    live.className = "visually-hidden";
    live.setAttribute("aria-live", "polite");
    var size = storedText();
    labelTextButton(button, size);
    button.addEventListener("click", function () {
      size = TEXT_SIZES[(TEXT_SIZES.indexOf(size) + 1) % TEXT_SIZES.length];
      try { window.localStorage.setItem(TEXT_KEY, size); } catch (e) { /* ignore */ }
      applyText(size);
      labelTextButton(button, size);
      live.textContent = t("text.label", "Text size:") + " " + t("text." + size, TEXT_NAME[size]);
    });
    header.appendChild(button);
    header.appendChild(live);
  }

  function showBanner(status) {
    var b = el("banner");
    if (b && status && status.warning) { b.textContent = status.warning; b.hidden = false; }
  }

  // One date renderer for the whole UI: locale-aware ("11 Aug 2026, 10:12" in
  // English, but the device's own language elsewhere — never a hardcoded
  // English month name). Accepts a Date, epoch ms, or a "YYYYMMDDTHHMMSSZ"
  // backup stamp.
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
    // The device language, the same one applyI18n/setLangDir put on <html
    // lang>; undefined falls back to the browser's own locale.
    var lang = document.documentElement.lang || undefined;
    return d.toLocaleDateString(lang, {day: "numeric", month: "short", year: "numeric"})
      + ", " + d.toLocaleTimeString(lang, {hour: "2-digit", minute: "2-digit"});
  }

  window.OvosWebUI = {
    api: api, el: el, say: say, sayHtml: sayHtml, esc: esc, t: t, applyI18n: applyI18n,
    fmtDateTime: fmtDateTime,
    ready: function (fn) {
      document.addEventListener("DOMContentLoaded", function () {
        renderNav();
        markNav();
        mountThemeToggle();
        mountSimpleToggle();
        mountTextToggle();
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
