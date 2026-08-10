/* ovos-webui — plain browser JavaScript. No build step, no CDN. */
(function () {
  "use strict";

  // A token can be given as ?token=... . It is kept for later requests only in
  // this tab, so it is not written to disk.
  var params = new URLSearchParams(window.location.search);
  var token = params.get("token") || sessionStorage.getItem("ovos-webui-token") || "";
  if (params.get("token")) { sessionStorage.setItem("ovos-webui-token", token); }

  function headers(extra) {
    var h = extra || {};
    if (token) { h["Authorization"] = "Bearer " + token; }
    return h;
  }

  function api(path, options) {
    options = options || {};
    options.headers = headers(options.headers);
    return fetch(path, options).then(function (r) {
      if (r.status === 401) { throw new Error("A token is needed. Add ?token=... to the address."); }
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
      var target = a.getAttribute("href").split("?")[0].replace(/\/$/, "") || "/";
      if (target === here) { a.setAttribute("aria-current", "page"); }
      if (token) { a.href = target + "?token=" + encodeURIComponent(token); }
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
    api: api, el: el, say: say, esc: esc, token: token,
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
