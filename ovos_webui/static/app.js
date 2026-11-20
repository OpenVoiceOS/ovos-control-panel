/* ovos-control-panel — plain browser JavaScript. No build step, no CDN. */
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
  // Translating a label that wraps a control must not wipe the control, so
  // there only the element's own first text run is replaced and the control
  // stays. Everywhere else the element is one message and is replaced whole.
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
      // A control inside the element is part of the page, not part of the
      // message: replace the element's own text and leave the control alone.
      // Anything else -- plain text, or a sentence with <code>/<em> inside --
      // is one message, so the whole of it is replaced. Replacing only the
      // first text node there would leave the English after the child on the
      // page, next to the translation of the same sentence.
      if (node.querySelector("input,select,textarea,button")) {
        var text = firstTextNode(node);
        if (text) { text.nodeValue = t(key, text.nodeValue); }
        return;
      }
      if (key && Object.prototype.hasOwnProperty.call(STRINGS, key)) {
        node.textContent = STRINGS[key];
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

  // The languages that ship a file in static/i18n/. Asking for one that does
  // not exist answered 404 on every page load, a console error on a device in
  // any other language; English is the fallback either way. A test keeps this
  // list in step with the files.
  var LOCALES = {ar: 1, da: 1, es: 1, pt: 1};

  // Load the locale file for a language, fall back to English, and apply it.
  function loadLocale(lang) {
    var base = setLangDir(lang);
    if (!LOCALES[base]) { return Promise.resolve(); }
    return fetch("/static/i18n/" + base + ".json", {credentials: "same-origin"})
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (dict) { STRINGS = dict || {}; applyI18n(document); })
      .catch(function () { /* keep the English already on the page */ });
  }

  // The one place the site navigation is defined. Every page carries an empty
  // (or fallback) <nav aria-label="Site">; this fills it, so a new page is
  // added here once rather than in every file.
  //
  // Each page says where it belongs, so the menu can be built from this list:
  //   group  the menu group: "everyday" (always shown), "voice", "understanding",
  //          "device", "screen" or "maintenance" (folded under "Show more")
  //   level  "everyday" or "advanced"
  //   needs  the capability the page depends on (a plugin or a screen), or null.
  //          Pages whose need is not met can be left out of the menu.
  // Kept JSON-shaped (quoted keys, no trailing comma) so the tests can read it.
  var NAV = [
    {"path": "/", "key": "nav.dashboard", "label": "Dashboard", "group": "everyday", "level": "everyday", "needs": null},
    {"path": "/setup", "key": "nav.setup", "label": "Setup", "group": "everyday", "level": "everyday", "needs": null},
    {"path": "/tryit", "key": "nav.tryit", "label": "Try it", "group": "everyday", "level": "everyday", "needs": null},
    {"path": "/controls", "key": "nav.controls", "label": "Device", "group": "everyday", "level": "everyday", "needs": null},
    {"path": "/network", "key": "nav.network", "label": "Network", "group": "everyday", "level": "everyday", "needs": null},
    {"path": "/voice", "key": "nav.voice", "label": "Voice and language", "group": "everyday", "level": "everyday", "needs": null},
    {"path": "/skills", "key": "nav.skills", "label": "Skills", "group": "everyday", "level": "everyday", "needs": null},
    {"path": "/backup", "key": "nav.backup", "label": "Backup", "group": "everyday", "level": "everyday", "needs": null},
    {"path": "/about", "key": "nav.about", "label": "About", "group": "everyday", "level": "everyday", "needs": null},
    {"path": "/voice-all", "key": "nav.voiceAll", "label": "All voice settings", "group": "voice", "level": "advanced", "needs": null},
    {"path": "/servers", "key": "nav.servers", "label": "Servers", "group": "voice", "level": "advanced", "needs": null},
    {"path": "/translate", "key": "nav.translate", "label": "Translate", "group": "voice", "level": "advanced", "needs": null},
    {"path": "/intents", "key": "nav.intents", "label": "Intents", "group": "understanding", "level": "advanced", "needs": null},
    {"path": "/transformers", "key": "nav.transformers", "label": "Transformers", "group": "understanding", "level": "advanced", "needs": null},
    {"path": "/personas", "key": "nav.personas", "label": "Personas", "group": "understanding", "level": "advanced", "needs": null},
    {"path": "/system", "key": "nav.system", "label": "System", "group": "device", "level": "advanced", "needs": "system"},
    {"path": "/sensors", "key": "nav.sensors", "label": "Sensors", "group": "device", "level": "advanced", "needs": "sensors"},
    {"path": "/media", "key": "nav.media", "label": "Media", "group": "device", "level": "advanced", "needs": "media"},
    {"path": "/apps", "key": "nav.apps", "label": "Apps", "group": "screen", "level": "advanced", "needs": "app-launcher"},
    {"path": "/wallpaper", "key": "nav.wallpaper", "label": "Wallpaper", "group": "screen", "level": "advanced", "needs": "wallpaper"},
    {"path": "/mark1", "key": "nav.mark1", "label": "Mark-1 faceplate", "group": "screen", "level": "advanced", "needs": "mark1"},
    {"path": "/plugins", "key": "nav.plugins", "label": "Plugins", "group": "maintenance", "level": "advanced", "needs": null},
    {"path": "/config", "key": "nav.settings", "label": "Settings", "group": "maintenance", "level": "advanced", "needs": null},
    {"path": "/sound", "key": "nav.sound", "label": "Send over sound", "group": "maintenance", "level": "advanced", "needs": null}
  ];
  // The menu shows the everyday pages, then an "Advanced" divider and one
  // row per advanced group. Each row folds its own pages open and shut, and
  // which rows are open is remembered per browser; all start folded. Every
  // link is always in the DOM -- a folded group's links are only hidden --
  // and the group holding the page you are on opens when the page loads, so
  // a link can never strand you on a page the menu does not show.
  var GROUPS = [
    ["voice", "nav.group.voice", "Voice"],
    ["understanding", "nav.group.understanding", "Understanding"],
    ["device", "nav.group.device", "Device"],
    ["screen", "nav.group.screen", "Screen"],
    ["maintenance", "nav.group.maintenance", "Maintenance"]
  ];
  var OPEN_KEY = "ovos-nav-open";
  // The old header switch stored "ovos-simple"; "0" meant someone had asked
  // for every page, so every group starts open for them.
  var OLD_SIMPLE_KEY = "ovos-simple";
  function openGroups() {
    try {
      var v = window.localStorage.getItem(OPEN_KEY);
      if (v === null) {
        return window.localStorage.getItem(OLD_SIMPLE_KEY) === "0"
          ? GROUPS.map(function (g) { return g[0]; }) : [];
      }
      var list = JSON.parse(v);
      return Array.isArray(list) ? list : [];
    } catch (e) { return []; }
  }
  function saveOpen(list) {
    try { window.localStorage.setItem(OPEN_KEY, JSON.stringify(list)); } catch (e) { /* ignore */ }
  }
  function herePath() {
    return window.location.pathname.replace(/\/$/, "") || "/";
  }
  function navLink(item) {
    return '<a href="' + item.path + '" data-i18n="' + item.key + '">'
      + esc(t(item.key, item.label)) + "</a>";
  }
  function renderNav() {
    var nav = document.querySelector('nav[aria-label], nav#sitenav');
    if (!nav) { return; }
    var html = '<div class="nav-group nav-everyday">'
      + NAV.filter(function (x) { return x.group === "everyday"; }).map(navLink).join("")
      + "</div>";
    html += '<span class="nav-divider" data-i18n="nav.advanced">'
      + esc(t("nav.advanced", "Advanced")) + "</span>";
    html += GROUPS.map(function (g) {
      var items = NAV.filter(function (x) { return x.group === g[0]; });
      if (!items.length) { return ""; }
      return '<div class="nav-group" data-group="' + g[0] + '">'
        + '<button type="button" class="nav-fold" aria-expanded="false" aria-controls="navl-' + g[0] + '">'
        + '<span data-i18n="' + g[1] + '">' + esc(t(g[1], g[2])) + "</span></button>"
        + '<div class="nav-links" id="navl-' + g[0] + '">' + items.map(navLink).join("") + "</div></div>";
    }).join("");
    nav.innerHTML = html;
    var here = herePath();
    var current = NAV.filter(function (x) { return x.path === here; })[0];
    var open = openGroups();
    nav.querySelectorAll(".nav-group[data-group]").forEach(function (g) {
      var name = g.getAttribute("data-group");
      foldGroup(g, open.indexOf(name) >= 0 || !!(current && current.group === name));
      g.querySelector(".nav-fold").addEventListener("click", function () {
        var now = g.querySelector(".nav-fold").getAttribute("aria-expanded") !== "true";
        foldGroup(g, now);
        var list = openGroups().filter(function (x) { return x !== name; });
        if (now) { list.push(name); }
        saveOpen(list);
      });
    });
  }
  function foldGroup(g, open) {
    g.querySelector(".nav-fold").setAttribute("aria-expanded", open ? "true" : "false");
    g.querySelector(".nav-links").hidden = !open;
  }
  // Pages whose need is not met (a plugin or a screen the device lacks) are
  // left out of the menu, and a group left empty goes with them. The answer
  // is kept for a few minutes per tab so the menu does not jump on every page.
  // Until it is known, and when the panel runs apart from the assistant (its
  // own packages then say nothing about the device's), every page shows.
  var NEEDS_KEY = "ovos-nav-needs";
  var NEEDS_TTL = 5 * 60 * 1000;
  function cachedNeeds() {
    try {
      var c = JSON.parse(window.sessionStorage.getItem(NEEDS_KEY) || "null");
      return c && Date.now() - c.at < NEEDS_TTL ? c.data : null;
    } catch (e) { return null; }
  }
  function unmet(data, item) {
    return !!(data && data.colocated && item.needs && data.needs
      && data.needs[item.needs] && data.needs[item.needs].met === false);
  }
  function applyNeeds(data) {
    var nav = document.querySelector('nav[aria-label], nav#sitenav');
    if (!nav) { return; }
    var here = herePath();
    NAV.forEach(function (item) {
      var a = nav.querySelector('a[href="' + item.path + '"]');
      if (a) { a.hidden = unmet(data, item) && item.path !== here; }
    });
    nav.querySelectorAll(".nav-group").forEach(function (g) {
      var links = g.querySelectorAll("a[href]");
      var shown = Array.prototype.filter.call(links, function (a) { return !a.hidden; });
      g.classList.toggle("nav-empty", links.length > 0 && shown.length === 0);
    });
    var current = NAV.filter(function (x) { return x.path === here; })[0];
    var note = document.getElementById("needs-note");
    if (current && unmet(data, current)) {
      if (!note) {
        var main = document.querySelector("main");
        if (!main) { return; }
        note = document.createElement("p");
        note.id = "needs-note";
        note.className = "msg needs-note";
        note.setAttribute("role", "note");
        main.insertBefore(note, main.firstChild);
      }
      var pkg = data.needs[current.needs].suggest;
      var parts = t("nav.needs.missing", "This page needs {pkg}, which is not installed on this device.")
        .split("{pkg}");
      note.innerHTML = esc(parts[0]) + "<code>" + esc(pkg) + "</code>" + esc(parts.slice(1).join(""))
        + ' <a href="/plugins">' + esc(t("nav.needs.install", "Install it on the Plugins page")) + "</a>.";
    } else if (note) {
      note.parentNode.removeChild(note);
    }
  }
  function loadNeeds() {
    applyNeeds(cachedNeeds());
    return api("/api/nav/needs").then(function (data) {
      try { window.sessionStorage.setItem(NEEDS_KEY, JSON.stringify({at: Date.now(), data: data})); } catch (e) { /* ignore */ }
      applyNeeds(data);
    }).catch(function () { /* not answered: keep every page */ });
  }
  function markNav() {
    var here = window.location.pathname.replace(/\/$/, "") || "/";
    document.querySelectorAll("nav a").forEach(function (a) {
      var target = a.getAttribute("href").replace(/\/$/, "") || "/";
      if (target === here) { a.setAttribute("aria-current", "page"); }
    });
  }

  // On a phone the page list folds behind one button (#86). The CSS hides the
  // list only once this has run (the js-menu class), so a page whose script
  // fails still shows every link. The button carries the current page's name.
  var renameMenu = function () {};
  function mountMenuToggle() {
    var nav = document.querySelector('nav[aria-label], nav#sitenav');
    if (!nav || document.getElementById("menu-toggle")) { return; }
    if (!nav.id) { nav.id = "sitenav"; }
    var bar = document.createElement("div");
    bar.className = "menubar";
    var button = document.createElement("button");
    button.id = "menu-toggle";
    button.type = "button";
    button.className = "menu-toggle";
    button.setAttribute("aria-controls", nav.id);
    button.setAttribute("aria-expanded", "false");
    var label = document.createElement("span");
    label.textContent = "\u2630 " + t("menu.button", "Menu");
    var here = document.createElement("span");
    here.className = "menu-here";
    function nameHere() {
      var current = nav.querySelector('a[aria-current="page"]');
      here.textContent = current ? current.textContent : "";
      label.textContent = "\u2630 " + t("menu.button", "Menu");
    }
    nameHere();
    button.appendChild(label);
    button.appendChild(here);
    bar.appendChild(button);
    nav.parentNode.insertBefore(bar, nav);
    function setOpen(open) {
      nav.classList.toggle("open", open);
      button.setAttribute("aria-expanded", open ? "true" : "false");
    }
    button.addEventListener("click", function () {
      var open = !nav.classList.contains("open");
      setOpen(open);
      if (open) {
        var first = nav.querySelector('a[aria-current="page"]') || nav.querySelector("a");
        if (first) { first.focus(); }
      }
    });
    nav.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && nav.classList.contains("open")) {
        setOpen(false);
        button.focus();
      }
    });
    document.documentElement.classList.add("js-menu");
    // The page names are translated after the locale loads; follow them.
    renameMenu = nameHere;
  }

  // The header's round buttons share one group, so they wrap together.
  function headerTools() {
    var header = document.querySelector("header");
    if (!header) { return null; }
    var tools = header.querySelector(".header-tools");
    if (!tools) {
      tools = document.createElement("span");
      tools.className = "header-tools";
      header.appendChild(tools);
    }
    return tools;
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
    headerTools().appendChild(button);
    headerTools().appendChild(live);
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
    headerTools().appendChild(button);
    headerTools().appendChild(live);
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

  // Install a package, after saying what it would change. The panel first asks
  // the device what pip would do (a dry run); a downgrade of anything installed
  // is listed in the question, and a run pip could not work out says it would
  // most likely fail. Resolves to the install job, or null when the person
  // said no. ``question`` is the page's own "Install X?".
  function installPackage(name, question) {
    var note = document.getElementById("install-check");
    if (!note) {
      note = document.createElement("p");
      note.id = "install-check";
      note.className = "msg";
      note.setAttribute("role", "status");
      var main = document.querySelector("main");
      if (main) { main.insertBefore(note, main.firstChild); }
    }
    note.hidden = false;
    note.textContent = t("install.checking", "Checking what installing {name} would change…").split("{name}").join(name);
    var post = function (path) {
      return api(path, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({package: name})});
    };
    return post("/api/plugins/check").catch(function () { return {checked: false}; }).then(function (r) {
      note.hidden = true;
      var ask = question;
      if (r && r.checked && r.downgrades && r.downgrades.length) {
        ask = question + "\n\n" + t("install.downgrades",
          "This would change these installed packages to older versions:") + "\n"
          + r.downgrades.map(function (d) { return "  " + d.name + " " + d.from + " \u2192 " + d.to; }).join("\n")
          + "\n\n" + t("install.anyway", "That can stop parts of OpenVoiceOS from working. Install anyway?");
      } else if (r && r.reason === "pip-failed") {
        ask = question + "\n\n" + t("install.wouldFail",
          "pip could not work out this install, so it would most likely fail. Try anyway?");
      }
      if (!window.OvosWebUI.confirmed(ask)) { return null; }
      return post("/api/plugins/install");
    });
  }

  window.OvosWebUI = {
    api: api, el: el, say: say, sayHtml: sayHtml, esc: esc, t: t, applyI18n: applyI18n,
    fmtDateTime: fmtDateTime,
    ready: function (fn) {
      document.addEventListener("DOMContentLoaded", function () {
        renderNav();
        markNav();
        mountMenuToggle();
        mountThemeToggle();
        mountTextToggle();
        // One status call drives both the language/direction and the banner,
        // then the page runs with translations already applied.
        api("/api/status").then(function (s) {
          showBanner(s);
          return loadLocale(s && s.lang);
        }).catch(function () { /* offline or not signed in: stay in English */ })
          .then(function () { renameMenu(); loadNeeds(); })
          .then(function () {
            try { fn(); } catch (e) { console.error(e); }
          });
      });
    },
    confirmed: function (question) { return window.confirm(question); },
    installPackage: installPackage
  };
})();
