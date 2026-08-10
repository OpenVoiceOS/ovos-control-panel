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
        throw new Error("Sign in first.");
      }
      if (r.status === 403) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          throw new Error(b.detail || "That is not allowed.");
        });
      }
      var ctype = r.headers.get("content-type") || "";
      if (ctype.indexOf("json") === -1) {
        if (!r.ok) { throw new Error("Request failed (" + r.status + ")"); }
        return r.text();
      }
      return r.json().then(function (body) {
        if (!r.ok) { throw new Error(body.detail || ("Request failed (" + r.status + ")")); }
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

  function markNav() {
    var here = window.location.pathname.replace(/\/$/, "") || "/";
    document.querySelectorAll("nav a").forEach(function (a) {
      var target = a.getAttribute("href").replace(/\/$/, "") || "/";
      if (target === here) { a.setAttribute("aria-current", "page"); }
    });
  }

  function showBanner() {
    return api("/api/status").then(function (s) {
      var b = el("banner");
      if (b && s.warning) { b.textContent = s.warning; b.hidden = false; }
      return s;
    }).catch(function () { return {}; });
  }

  window.OvosWebUI = {
    api: api, el: el, say: say, esc: esc,
    ready: function (fn) {
      document.addEventListener("DOMContentLoaded", function () {
        markNav();
        showBanner();
        try { fn(); } catch (e) { console.error(e); }
      });
    },
    confirmed: function (question) { return window.confirm(question); }
  };
})();
