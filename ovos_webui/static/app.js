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
  // A device that decides the theme or the text size (webui.theme,
  // webui.text_size) has it set on <html> by the server, and no button.
  var ROOT = document.documentElement;
  var THEME_LOCKED = ROOT.hasAttribute("data-theme-locked");
  var TEXT_LOCKED = ROOT.hasAttribute("data-text-locked");
  if (!THEME_LOCKED) { applyTheme(storedTheme()); }

  // The page is served in English and translated in the browser. To keep a
  // page from showing English and then switching, the strings of the last
  // language are kept for the session (per panel version), applied before the
  // menu is drawn, and the page is held back from painting until they are on.
  // A first visit, or a language with no strings, waits at most a moment.
  var LANG_KEY = "ovos-lang", STRINGS_KEY = "ovos-strings.";
  var ASSET_V = (function () {
    try { return (document.currentScript.src.split("?v=")[1] || ""); } catch (e) { return ""; }
  })();
  var lastLang = null;
  try { lastLang = window.localStorage.getItem(LANG_KEY); } catch (e) { /* none */ }
  function releasePaint() { document.documentElement.classList.remove("i18n-wait"); }
  if (lastLang && lastLang.split("-")[0] !== "en") {
    document.documentElement.classList.add("i18n-wait");
    setTimeout(releasePaint, 1500);
  }
  // The kept strings are for this panel version and this set of pages: a
  // page installed since brings strings of its own, so they are read again.
  function stringsVersion() {
    var node = document.getElementById("ovos-nav"), text = node ? node.textContent : "", h = 0;
    for (var i = 0; i < text.length; i++) { h = (h * 31 + text.charCodeAt(i)) | 0; }
    return ASSET_V + "|" + h;
  }
  function keptStrings(base) {
    try {
      var c = JSON.parse(window.sessionStorage.getItem(STRINGS_KEY + base) || "null");
      return c && c.v === stringsVersion() ? c.d : null;
    } catch (e) { return null; }
  }
  function keepStrings(base, dict) {
    try { window.sessionStorage.setItem(STRINGS_KEY + base, JSON.stringify({v: stringsVersion(), d: dict})); } catch (e) { /* full */ }
  }

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
  if (!TEXT_LOCKED) { applyText(storedText()); }

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

  // The languages there are strings for -- the panel's own and every page's
  // -- come with the menu data (MENU.langs). Asking for one that has none
  // answered 404 on every page load, a console error on a device in any other
  // language; English is the fallback either way.
  // Load the locale file for a language, fall back to English, and apply it.
  function loadLocale(lang) {
    var base = setLangDir(lang);
    try { window.localStorage.setItem(LANG_KEY, lang || "en"); } catch (e) { /* ignore */ }
    readMenu();
    if ((MENU.langs || []).indexOf(base) === -1) { STRINGS = {}; releasePaint(); return Promise.resolve(); }
    var kept = keptStrings(base);
    if (kept) { STRINGS = kept; applyI18n(document); releasePaint(); return Promise.resolve(); }
    return fetch("/static/i18n/" + base + ".json", {credentials: "same-origin"})
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (dict) { STRINGS = dict || {}; keepStrings(base, STRINGS); applyI18n(document); })
      .catch(function () { /* keep the English already on the page */ })
      .then(releasePaint);
  }

  // The menu comes from the page registry on the server, which puts it in the
  // head of every page it serves (<script type="application/json" id="ovos-nav">),
  // so it is there as the page paints. Each page says where it belongs:
  //   group  a group id; a group's level is "everyday" (always shown, at the
  //          top) or "advanced" (a foldable row under "Advanced")
  //   icon   a data: URL, used as a mask so it takes the menu's colour
  // A page served without the data (the sign in page) has no menu. app.js
  // runs in the head, before that element exists, so it is read when the
  // page is ready (readMenu, from ready()).
  var MENU = {groups: [], pages: []};
  var NAV = [];
  var GROUPS = [];
  function readMenu() {
    try {
      var node = document.getElementById("ovos-nav");
      var data = node ? JSON.parse(node.textContent) : null;
      if (data && data.pages && data.groups) { MENU = data; }
    } catch (e) { /* no menu */ }
    NAV = MENU.pages;
    GROUPS = MENU.groups.filter(function (g) { return g.level === "advanced"; });
  }
  // The menu shows the everyday pages first, always open. Every other group
  // is a row that folds its pages open and shut: the Library and Music under
  // them, and "Advanced", which folds away all the advanced groups at once and
  // holds one such row per group. Which rows are open is remembered per
  // browser; all start folded. Every link is always in the DOM -- a folded
  // group's links are only hidden -- and the rows holding the page you are on
  // open when the page loads, so a link can never strand you on a page the
  // menu does not show.
  var OPEN_KEY = "ovos-nav-open";
  // The old header switch stored "ovos-simple"; "0" meant someone had asked
  // for every page, so every group starts open for them.
  var OLD_SIMPLE_KEY = "ovos-simple";
  //: The row that holds every advanced group. No group is called this.
  var ADVANCED = "advanced";
  //: The page at the foot of the menu.
  var LAST = "about";
  function openGroups() {
    try {
      var v = window.localStorage.getItem(OPEN_KEY);
      if (v === null) {
        return window.localStorage.getItem(OLD_SIMPLE_KEY) === "0"
          ? MENU.groups.map(function (g) { return g.id; }).concat([ADVANCED]) : [];
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
  // The icon is a data: URL from the registry; it is checked again here,
  // because it goes into a style attribute.
  var ICON_RE = /^data:image\/svg\+xml;base64,[A-Za-z0-9+\/=]+$/;
  function navLink(item) {
    var icon = item.icon && ICON_RE.test(item.icon)
      ? ' style="--icon: url(' + item.icon + ')"' : "";
    if (item.from) {
      // two pages with the same title: each says where it comes from
      return '<a href="' + esc(item.path) + '" data-page="' + esc(item.id) + '"' + icon + "><span"
        + (item.key ? ' data-i18n="' + esc(item.key) + '"' : "") + ">" + esc(t(item.key, item.label))
        + '</span><small class="nav-from">' + esc(item.from) + "</small></a>";
    }
    return '<a href="' + esc(item.path) + '" data-page="' + esc(item.id) + '"' + icon
      + (item.key ? ' data-i18n="' + esc(item.key) + '"' : "") + ">"
      + esc(t(item.key, item.label)) + "</a>";
  }
  // Each foldable row has an icon like the pages, so a row reads as part of
  // the same menu. The panel's groups have their own; any other gets a folder.
  var GROUP_ICONS = ["library", "music", "voice", "understanding", "device", "screen",
    "maintenance", "advanced"];
  function foldRow(id, key, label, inner, cls) {
    var gid = esc(id);
    var icon = "/static/nav/" + (GROUP_ICONS.indexOf(id) >= 0 ? id : "group") + ".svg";
    return '<div class="nav-group' + (cls ? " " + cls : "") + '" data-group="' + gid + '">'
      + '<button type="button" class="nav-fold" style="--icon: url(' + icon + ')" aria-expanded="false" aria-controls="navl-' + gid + '">'
      + "<span" + (key ? ' data-i18n="' + esc(key) + '"' : "") + ">" + esc(t(key, label))
      + "</span></button>"
      + '<div class="nav-links" id="navl-' + gid + '">' + inner + "</div></div>";
  }
  function groupRow(g, cls) {
    var items = NAV.filter(function (x) { return x.group === g.id; });
    return items.length ? foldRow(g.id, g.key, g.label, items.map(navLink).join(""), cls) : "";
  }
  function renderNav() {
    var nav = document.querySelector('nav[aria-label], nav#sitenav');
    if (!nav || !NAV.length) { return; }
    var html = MENU.groups.filter(function (g) { return g.level === "everyday"; }).map(function (g) {
      if (g.id !== "everyday") { return groupRow(g, "nav-everyday"); }
      var items = NAV.filter(function (x) { return x.group === g.id && x.id !== LAST; });
      return '<div class="nav-group nav-everyday">' + items.map(navLink).join("") + "</div>";
    }).join("");
    var advanced = GROUPS.map(function (g) { return groupRow(g, "nav-sub"); }).join("");
    if (advanced) { html += foldRow(ADVANCED, "nav.advanced", "Advanced", advanced, "nav-advanced"); }
    // About goes last, at the foot of the menu
    var last = NAV.filter(function (x) { return x.id === LAST && x.group === "everyday"; });
    if (last.length) { html += '<div class="nav-group nav-end">' + last.map(navLink).join("") + "</div>"; }
    nav.innerHTML = html;
    var here = herePath();
    var current = NAV.filter(function (x) { return x.path === here; })[0];
    var currentLevel = current && (MENU.groups.filter(function (g) { return g.id === current.group; })[0] || {}).level;
    var open = openGroups();
    nav.querySelectorAll(".nav-group[data-group]").forEach(function (g) {
      var name = g.getAttribute("data-group");
      var holdsHere = !!current && (current.group === name
        || (name === ADVANCED && currentLevel === "advanced"));
      foldGroup(g, open.indexOf(name) >= 0 || holdsHere);
      g.querySelector(":scope > .nav-fold").addEventListener("click", function () {
        var now = g.querySelector(":scope > .nav-fold").getAttribute("aria-expanded") !== "true";
        foldGroup(g, now);
        var list = openGroups().filter(function (x) { return x !== name; });
        if (now) { list.push(name); }
        saveOpen(list);
      });
    });
  }
  // The rail sits under the header and fills the rest of the window (app.css,
  // --head-h); the header can wrap to two lines, so its height is measured.
  function keepHeaderHeight() {
    var head = document.querySelector("header");
    if (!head) { return; }
    var set = function () {
      document.documentElement.style.setProperty("--head-h", head.offsetHeight + "px");
    };
    set();
    if (typeof ResizeObserver === "function") { new ResizeObserver(set).observe(head); }
    else { window.addEventListener("resize", set); }
  }
  function foldGroup(g, open) {
    g.querySelector(":scope > .nav-fold").setAttribute("aria-expanded", open ? "true" : "false");
    g.querySelector(":scope > .nav-links").hidden = !open;
  }
  // Pages whose need is not met (a plugin or a screen the device lacks) are
  // left out of the menu, and a group left empty goes with them. The answer
  // is kept for a few minutes per tab so the menu does not jump on every page.
  // Until it is known, and when the panel runs apart from the assistant (its
  // own packages then say nothing about the device's), every page shows.
  // Keyed by page id since the page registry; the old key held need names.
  var NEEDS_KEY = "ovos-nav-needs.v2";
  var NEEDS_TTL = 5 * 60 * 1000;
  function cachedNeeds() {
    try {
      var c = JSON.parse(window.sessionStorage.getItem(NEEDS_KEY) || "null");
      return c && Date.now() - c.at < NEEDS_TTL ? c.data : null;
    } catch (e) { return null; }
  }
  function unmet(data, item) {
    return !!(data && data.colocated && data.needs
      && data.needs[item.id] && data.needs[item.id].met === false);
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
      var pkg = data.needs[current.id].suggest;
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
    if (THEME_LOCKED || !header || document.getElementById("theme-toggle")) { return; }
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
    if (TEXT_LOCKED || !header || document.getElementById("text-toggle")) { return; }
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

  // Whether a package is in the OVOS release the device follows (the
  // installer's constraints file), for the Skills and Plugins searches.
  function releaseName(rel) {
    return rel && rel.name ? " (" + rel.name + ")" : "";
  }
  function releaseBadge(p, rel) {
    if (!rel || !rel.known || p.in_release === null || p.in_release === undefined) { return ""; }
    return p.in_release
      ? '<span class="badge ready">' + esc(t("release.in", "in the OVOS release") + releaseName(rel)) + "</span>"
      : '<span class="badge na">' + esc(t("release.not", "not checked")) + "</span>";
  }
  // The stores set on the Control panel page, as choices under Show
  // (value "store:<n>"), after the OVOS release and before all of PyPI.
  function addStores(select) {
    return api("/api/stores").then(function (r) {
      var all = select.querySelector('option[value="all"]');
      (r.stores || []).forEach(function (s, i) {
        var o = document.createElement("option");
        o.value = "store:" + i;
        o.textContent = t("store.option", "Store") + ": " + s.name;
        select.insertBefore(o, all);
      });
    }).catch(function () { /* no stores, then */ });
  }
  // What a Show choice adds to /api/plugins/search
  function showQuery(value) {
    if (value === "release") { return "&release=true"; }
    if (value.indexOf("store:") === 0) {
      return "&store=" + encodeURIComponent(value.slice(6)) + "&lang=" + encodeURIComponent(document.documentElement.lang || "");
    }
    return "";
  }
  function storeNote(node, r) {
    var text = r.offline
      ? t("store.unreachable", "The store could not be reached.") + (r.error ? " (" + r.error + ")" : "")
      : t("store.from", "What the store lists:") + " " + r.from_store.name + ". "
        + t("store.note", "Someone has checked these for a kind of device; the installer still checks the versions before it installs.");
    node.textContent = text;
    node.hidden = false;
  }
  function releaseNote(node, rel, onlyRelease) {
    var text = "";
    if (rel && !rel.known) {
      text = t("release.unknown", "The OVOS release could not be read, so everything on PyPI is shown.");
    } else if (!onlyRelease) {
      text = t("release.allWarn", "Everything on PyPI is shown, and none of it is checked: not whether it works with this device's versions, nor whether anyone still looks after it. The installer still checks the versions before it installs.");
    } else {
      text = t("release.onlyNote", "Only what belongs to the OVOS release this device follows") + releaseName(rel)
        + t("release.onlyNoteEnd", ", and what is installed.");
    }
    node.textContent = text;
    node.hidden = !text;
  }

  window.OvosWebUI = {
    api: api, el: el, say: say, sayHtml: sayHtml, esc: esc, t: t, applyI18n: applyI18n,
    releaseBadge: releaseBadge, releaseNote: releaseNote,
    addStores: addStores, showQuery: showQuery, storeNote: storeNote,
    fmtDateTime: fmtDateTime,
    ready: function (fn) {
      document.addEventListener("DOMContentLoaded", function () {
        readMenu();
        // the last language's strings, if this session has them, before the
        // menu is drawn; the status call below confirms the language
        var early = lastLang && keptStrings(lastLang.split("-")[0]);
        if (early) { setLangDir(lastLang); STRINGS = early; }
        renderNav();
        if (early) { applyI18n(document); releasePaint(); }
        keepHeaderHeight();
        markNav();
        mountMenuToggle();
        mountThemeToggle();
        mountTextToggle();
        // One status call drives both the language/direction and the banner,
        // then the page runs with translations already applied.
        api("/api/status").then(function (s) {
          showBanner(s);
          return loadLocale(s && s.lang);
        }).catch(function () { /* offline or not signed in: stay in English */ releasePaint(); })
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
