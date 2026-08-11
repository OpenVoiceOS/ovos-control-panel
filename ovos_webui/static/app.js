/* ovos-webui — plain browser JavaScript. No build step, no CDN. */
(function () {
  "use strict";

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
      .replace(/"/g, "&quot;");
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

  function showBanner(status) {
    var b = el("banner");
    if (b && status && status.warning) { b.textContent = status.warning; b.hidden = false; }
  }

  window.OvosWebUI = {
    api: api, el: el, say: say, esc: esc, t: t, applyI18n: applyI18n,
    ready: function (fn) {
      document.addEventListener("DOMContentLoaded", function () {
        markNav();
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
