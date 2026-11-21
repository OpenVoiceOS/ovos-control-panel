"""The page registry: every page in the menu, wherever it comes from.

A page is described by a dict (see ``docs/pages.md``) and registered under the
``opm.control_panel.page`` entry point group. The panel's own pages are
registered the same way, by this package, so a page can later move to another
package without changing how it is found.

:func:`load` reads the group once and returns a :class:`Registry`: the pages
that loaded, the menu groups, and the problems with the ones that did not. A
broken page is left out and named; it never stops the panel from starting.
"""
from __future__ import annotations

import base64
import importlib
import json
import logging
import re
from dataclasses import dataclass, field
from importlib import metadata, resources
from typing import Any, Callable

LOG = logging.getLogger(__name__)

ENTRY_POINT = "opm.control_panel.page"
#: The versions of the page contract this panel can load.
API_VERSIONS = frozenset({1})

#: The panel's own groups. Pages may add groups of their own.
GROUPS: tuple[dict[str, Any], ...] = (
    {"id": "everyday", "key": "nav.group.everyday", "label": "Everyday", "order": 0, "level": "everyday"},
    {"id": "voice", "key": "nav.group.voice", "label": "Voice", "order": 10, "level": "advanced"},
    {"id": "understanding", "key": "nav.group.understanding", "label": "Understanding", "order": 20,
     "level": "advanced"},
    {"id": "device", "key": "nav.group.device", "label": "Device", "order": 30, "level": "advanced"},
    {"id": "screen", "key": "nav.group.screen", "label": "Screen", "order": 40, "level": "advanced"},
    {"id": "maintenance", "key": "nav.group.maintenance", "label": "Maintenance", "order": 50,
     "level": "advanced"},
)

#: Paths a page may not take: the shell's own.
RESERVED = ("/api", "/static", "/pages", "/login", "/logout", "/healthz")
#: The pages that always ship with the panel and cannot be turned off.
CORE = frozenset({"dashboard", "settings", "plugins", "skills", "backup", "about"})
#: The panel's own distribution, to tell its pages from added ones.
OWN_DIST = "ovos-control-panel"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_PATH_RE = re.compile(r"^/[a-z0-9/_-]*$")
_KNOWN = {"api_version", "id", "path", "title", "heading", "group", "groups", "order",
          "needs", "icon", "html", "assets", "i18n", "bus", "routes", "manual"}
_LANG_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$")
#: Limits on what a page brings, so one broken page cannot fill the memory.
MAX_HTML = 512 * 1024
MAX_STRINGS = 256 * 1024

#: The panel's own pages, in menu order. Used when the panel runs from a
#: source tree that was never installed, so its entry points are not known.
BUILTIN = (
    "dashboard", "setup", "tryit", "controls", "network", "voice", "skills", "backup",
    "about", "voice_all", "servers", "translate", "intents", "transformers", "personas",
    "system", "sensors", "media", "apps", "wallpaper", "mark1", "plugins", "settings",
    "sound",
)


class PageError(ValueError):
    """A page description that cannot be used."""


@dataclass
class Page:
    """One loaded page."""

    id: str
    path: str
    key: str
    label: str
    group: str
    order: int
    needs: tuple[str, ...]
    html: str
    icon: str | None
    package: str
    version: str
    builtin: bool
    routes: Callable | None = None
    manual: str | None = None
    heading_key: str = ""
    heading: str = ""
    #: A whole document (the panel's pages that have not moved yet) is served
    #: as it is; anything else is the page's body, wrapped in the shell.
    fragment: bool = False
    #: The page's own strings, per language code.
    strings: dict[str, dict[str, str]] = field(default_factory=dict)
    #: The folder served under /pages/<id>/, if the page has one.
    assets: Any = None

    def nav(self) -> dict[str, Any]:
        """What the browser's menu needs to know about the page."""
        return {"id": self.id, "path": self.path, "key": self.key, "label": self.label,
                "group": self.group, "icon": self.icon}

    def about(self) -> dict[str, Any]:
        """What the About page lists about the page."""
        return {"id": self.id, "path": self.path, "title": self.label, "group": self.group,
                "package": self.package, "version": self.version, "builtin": self.builtin}


@dataclass
class Registry:
    """The pages that loaded, the groups, and what went wrong."""

    pages: list[Page] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    problems: list[dict[str, str]] = field(default_factory=list)

    def by_path(self) -> dict[str, Page]:
        return {p.path: p for p in self.pages}

    def by_id(self) -> dict[str, Page]:
        return {p.id: p for p in self.pages}

    def drop(self, page: Page, error: str) -> None:
        """Leave a page out after it loaded, with the reason."""
        self.pages = [p for p in self.pages if p is not page]
        self.problems.append({"page": page.id, "package": page.package, "error": error})
        LOG.warning("page %s from %s left out: %s", page.id, page.package, error)

    def strings(self, lang: str, base: dict[str, str]) -> dict[str, str]:
        """The panel's strings for ``lang`` with every page's own merged in.

        The panel's own strings win: a page cannot change what another page,
        or the shell, says. A key two pages define differently keeps the first.
        """
        merged = dict(base)
        for page in self.pages:
            for key, value in (page.strings.get(lang) or {}).items():
                if key not in merged:
                    merged[key] = value
                elif merged[key] != value and key not in base:
                    LOG.info("page %s: key %s is already defined by another page", page.id, key)
        return merged

    def nav(self, prefs: Prefs | None = None) -> dict[str, Any]:
        """The menu, in order: groups that have pages, and the pages.

        ``prefs`` (from :func:`prefs`) turns pages off, moves them and orders
        and renames the groups, as ``webui.pages`` and ``webui.groups`` say.
        """
        prefs = prefs or Prefs()
        groups = {g["id"]: dict(g) for g in self.groups}
        for gid, change in prefs.rename.items():
            if gid in groups:
                groups[gid].update(change)
        rank = {g["id"]: i for i, g in enumerate(self.groups)}
        for i, gid in enumerate(prefs.group_order):
            if gid in rank and groups[gid]["level"] == "advanced":
                rank[gid] = -1000 + i
        seq = {p.id: i for i, p in enumerate(self.pages)}
        shown = []
        for page in self.pages:
            if page.id in prefs.disabled:
                continue
            item = page.nav()
            move = prefs.move.get(page.id) or {}
            if move.get("group") in groups:
                item["group"] = move["group"]
            order = move.get("order", page.order)
            shown.append((rank[item["group"]], order, seq[page.id], item))
        shown.sort(key=lambda x: x[:3])
        used = {x[3]["group"] for x in shown}
        ordered = sorted((g for g in groups.values() if g["id"] in used),
                         key=lambda g: (rank[g["id"]], g["id"]))
        return {"groups": ordered, "pages": [x[3] for x in shown], "langs": self.langs()}

    def langs(self) -> list[str]:
        """Every language there are strings for: the panel's and the pages'."""
        found = {p.name[:-5] for p in resources.files("ovos_webui").joinpath("static", "i18n").iterdir()
                 if p.name.endswith(".json")}
        for page in self.pages:
            found.update(page.strings)
        return sorted(found - {"en"})

    def nav_json(self, prefs: Prefs | None = None) -> str:
        """The menu as JSON that is safe inside a ``<script>`` element."""
        return json.dumps(self.nav(prefs), ensure_ascii=False,
                          separators=(",", ":")).replace("</", "<\\/")


# ── what the configuration says about the menu ───────────────────────────────
@dataclass
class Prefs:
    """``webui.pages`` and ``webui.groups``, checked."""

    disabled: frozenset = frozenset()
    move: dict[str, dict[str, Any]] = field(default_factory=dict)
    group_order: list[str] = field(default_factory=list)
    rename: dict[str, dict[str, str]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def prefs(webui: dict[str, Any] | None) -> Prefs:
    """Read ``webui.pages`` and ``webui.groups`` from the ``webui`` section.

    Anything malformed is skipped and named in ``problems``. The core pages
    cannot be turned off.
    """
    out = Prefs()
    webui = webui if isinstance(webui, dict) else {}
    pages_cfg = webui.get("pages") if isinstance(webui.get("pages"), dict) else {}
    groups_cfg = webui.get("groups") if isinstance(webui.get("groups"), dict) else {}
    disabled = set()
    for pid in pages_cfg.get("disabled") or ():
        if not isinstance(pid, str):
            out.problems.append(f"webui.pages.disabled: {pid!r} is not a page id")
        elif pid in CORE:
            out.problems.append(f"webui.pages.disabled: {pid} is a core page and stays on")
        else:
            disabled.add(pid)
    out.disabled = frozenset(disabled)
    for pid, change in (pages_cfg.get("move") or {}).items():
        if not isinstance(change, dict):
            out.problems.append(f"webui.pages.move.{pid}: not a mapping")
            continue
        move = {}
        if isinstance(change.get("group"), str):
            move["group"] = change["group"]
        if isinstance(change.get("order"), int) and not isinstance(change.get("order"), bool):
            move["order"] = change["order"]
        out.move[pid] = move
    order = groups_cfg.get("order") or []
    out.group_order = [g for g in order if isinstance(g, str)] if isinstance(order, list) else []
    for gid, change in (groups_cfg.get("rename") or {}).items():
        if isinstance(change, dict) and isinstance(change.get("label"), str) and change["label"].strip():
            # A renamed group shows the new label as written, in every language.
            out.rename[gid] = {"label": change["label"].strip()[:40],
                               "key": change["key"] if isinstance(change.get("key"), str) else ""}
        else:
            out.problems.append(f"webui.groups.rename.{gid}: needs a label")
    return out


# ── reading a description ────────────────────────────────────────────────────
def _resource(module: str, spec: Any):
    """A file given as a name next to the module, or as (package, name)."""
    if isinstance(spec, (tuple, list)) and len(spec) == 2:
        package, name = spec
    elif isinstance(spec, str):
        package, name = module, spec
    else:
        raise PageError(f"not a file: {spec!r}")
    if "/" in name or "\\" in name or name.startswith("."):
        raise PageError(f"not a plain file name: {name!r}")
    try:
        target = resources.files(package).joinpath(name)
    except (ModuleNotFoundError, TypeError) as e:
        raise PageError(f"cannot find {name!r} in {package}: {e}") from e
    if not target.is_file():
        raise PageError(f"{name!r} is missing from {package}")
    return target


def _folder(module: str, spec: Any):
    """A folder: a path next to the module, or (package, path). The path may
    have several parts ("gui/images"), none of them hidden or a parent."""
    if not spec:
        return None
    if isinstance(spec, (tuple, list)) and len(spec) == 2:
        module, spec = spec
    if not isinstance(spec, str) or "\\" in spec or spec.startswith("/") \
            or any(not part or part.startswith(".") for part in spec.split("/")):
        raise PageError(f"not a folder in the package: {spec!r}")
    try:
        target = resources.files(module).joinpath(*spec.split("/"))
    except (ModuleNotFoundError, TypeError) as e:
        raise PageError(f"cannot find {spec!r} in {module}: {e}") from e
    if not target.is_dir():
        raise PageError(f"the folder {spec!r} is missing from {module}")
    return target


def _strings(folder) -> dict[str, dict[str, str]]:
    """Read ``<lang>.json`` files: flat objects of text."""
    out: dict[str, dict[str, str]] = {}
    if folder is None:
        return out
    for item in folder.iterdir():
        name = item.name
        if not name.endswith(".json") or not item.is_file():
            continue
        code = name[:-5].lower().replace("_", "-")
        if not _LANG_RE.match(code):
            raise PageError(f"not a language file: {name}")
        # The browser asks for the language alone (da, not da-dk), so a
        # regional file counts for its language, unless that has a file too.
        lang = code.split("-")[0]
        if lang in out and code != lang:
            continue
        raw = item.read_bytes()
        if len(raw) > MAX_STRINGS:
            raise PageError(f"{name} is too large")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise PageError(f"{name} is not JSON: {e}") from e
        if not isinstance(data, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            raise PageError(f"{name} must map keys to text")
        out[lang] = data
    return out


def _icon(module: str, spec: Any) -> str | None:
    if not spec:
        return None
    svg = _resource(module, spec).read_bytes()
    if b"<svg" not in svg[:512] or len(svg) > 16 * 1024:
        raise PageError("the icon is not a small SVG")
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")


def _title(raw: Any) -> tuple[str, str]:
    if not isinstance(raw, dict) or not isinstance(raw.get("label"), str) or not raw["label"]:
        raise PageError("the title needs an English label")
    key = raw.get("key") or ""
    if not isinstance(key, str):
        raise PageError("the title key must be text")
    return key, raw["label"]


def parse(desc: Any, module: str, package: str, version: str, builtin: bool) -> tuple[Page, list]:
    """Check a page description and turn it into a :class:`Page`.

    Returns the page and the groups it defines. Raises :class:`PageError`.
    """
    if not isinstance(desc, dict):
        raise PageError("the description is not a dict")
    version_wanted = desc.get("api_version")
    if version_wanted not in API_VERSIONS:
        raise PageError(f"written for page contract version {version_wanted!r}; "
                        f"this panel supports {sorted(API_VERSIONS)}")
    unknown = set(desc) - _KNOWN
    if unknown:
        LOG.info("page %s: ignoring fields this panel does not know: %s",
                 desc.get("id"), ", ".join(sorted(unknown)))
    pid = desc.get("id")
    if not isinstance(pid, str) or not _ID_RE.match(pid):
        raise PageError(f"not a page id: {pid!r}")
    path = desc.get("path")
    if not isinstance(path, str) or not _PATH_RE.match(path) or "//" in path \
            or (len(path) > 1 and path.endswith("/")):
        raise PageError(f"not a page path: {path!r}")
    if any(path == r or path.startswith(r + "/") for r in RESERVED):
        raise PageError(f"{path} belongs to the panel itself")
    key, label = _title(desc.get("title"))
    group = desc.get("group")
    if not isinstance(group, str) or not _ID_RE.match(group):
        raise PageError(f"not a group: {group!r}")
    order = desc.get("order", 100)
    if not isinstance(order, int) or isinstance(order, bool):
        raise PageError("the order must be a whole number")
    needs = desc.get("needs") or ()
    if isinstance(needs, str) or not all(isinstance(n, str) and n for n in needs):
        raise PageError("needs must be a list of package names")
    routes = desc.get("routes")
    if routes is not None and not callable(routes):
        raise PageError("routes must be a function")
    groups = []
    for raw in desc.get("groups") or ():
        if not isinstance(raw, dict) or not _ID_RE.match(str(raw.get("id", ""))):
            raise PageError(f"not a group definition: {raw!r}")
        gkey, glabel = _title(raw.get("title"))
        level = raw.get("level", "advanced")
        if level not in ("everyday", "advanced"):
            raise PageError(f"a group level is everyday or advanced, not {level!r}")
        groups.append({"id": raw["id"], "key": gkey, "label": glabel,
                       "order": int(raw.get("order", 100)), "level": level})
    heading_key, heading = (key, label) if desc.get("heading") is None else _title(desc["heading"])
    raw_html = _resource(module, desc.get("html")).read_bytes()
    if len(raw_html) > MAX_HTML:
        raise PageError("the page's HTML is too large")
    html = raw_html.decode("utf-8")
    page = Page(id=pid, path=path, key=key, label=label, group=group, order=order,
                needs=tuple(needs), html=html, icon=_icon(module, desc.get("icon")),
                package=package, version=version, builtin=builtin, routes=routes,
                manual=desc.get("manual"), heading_key=heading_key, heading=heading,
                fragment=not html.lstrip()[:15].lower().startswith("<!doctype"),
                strings=_strings(_folder(module, desc.get("i18n"))),
                assets=_folder(module, desc.get("assets")))
    return page, groups


# ── finding the pages ────────────────────────────────────────────────────────
def _entry_points() -> list:
    try:
        return list(metadata.entry_points(group=ENTRY_POINT))
    except Exception as e:  # noqa: BLE001 - broken metadata must not stop the panel
        LOG.warning("could not read the %s entry points: %s", ENTRY_POINT, e)
        return []


def _own_version() -> str:
    from ovos_webui.version import __version__
    return __version__


def _sources(eps: list | None) -> list[tuple[str, Callable[[], Any], str, str, str]]:
    """(name, loader, module, package, version) for every page to load."""
    eps = _entry_points() if eps is None else eps
    found = []
    own = False
    for ep in eps:
        dist = getattr(ep, "dist", None)
        package = getattr(dist, "name", None) or "?"
        version = getattr(dist, "version", None) or "?"
        if package.lower() == OWN_DIST:
            own = True
        module = ep.value.split(":", 1)[0].strip()
        found.append((ep.name, ep.load, module, package, version))
    if not own:
        # A source tree that was never installed: its entry points are not
        # known, so its own pages are read straight from this package.
        for name in BUILTIN:
            module = f"{__name__}.{name}"
            found.append((name.replace("_", "-"),
                          (lambda m=module: importlib.import_module(m).PAGE),
                          module, OWN_DIST, _own_version()))
    return found


def load(eps: list | None = None) -> Registry:
    """Load every registered page. ``eps`` replaces the entry points (tests)."""
    reg = Registry(groups=[dict(g) for g in GROUPS])
    known_groups = {g["id"] for g in reg.groups}
    paths: dict[str, str] = {}
    ids: set[str] = set()
    loaded: list[tuple[Page, list]] = []
    for name, loader, module, package, version in _sources(eps):
        builtin = package.lower() == OWN_DIST
        try:
            page, groups = parse(loader(), module, package, version, builtin)
            if page.id in ids:
                raise PageError(f"another page already has the id {page.id}")
            if page.path in paths:
                raise PageError(f"{page.path} is already the {paths[page.path]} page")
        except Exception as e:  # noqa: BLE001 - a broken page is left out, not fatal
            reg.problems.append({"page": name, "package": package, "error": str(e)})
            LOG.warning("page %s from %s left out: %s", name, package, e)
            continue
        ids.add(page.id)
        paths[page.path] = page.id
        loaded.append((page, groups))
    for page, groups in loaded:
        for g in groups:
            if g["id"] in known_groups:
                continue
            known_groups.add(g["id"])
            reg.groups.append(g)
    for page, _ in loaded:
        if page.group not in known_groups:
            reg.problems.append({"page": page.id, "package": page.package,
                                 "error": f"no group called {page.group}"})
            continue
        reg.pages.append(page)
    reg.groups.sort(key=lambda g: (g["order"], g["id"]))
    rank = {g["id"]: i for i, g in enumerate(reg.groups)}
    seq = {p.id: i for i, (p, _) in enumerate(loaded)}
    reg.pages.sort(key=lambda p: (rank[p.group], p.order, seq[p.id]))
    return reg


# ── what a page needs ────────────────────────────────────────────────────────
#: Packages that only exist where the assistant itself runs. Without any of
#: them the panel runs apart from the device (in its own container, say), its
#: packages say nothing about the device's, and no page is hidden.
ASSISTANT_PACKAGES = ("ovos-core", "ovos-audio", "ovos-dinkum-listener", "ovos-phal")


def colocated(have: dict[str, str] | None = None) -> bool:
    """Whether the panel shares its environment with the assistant."""
    from ovos_webui.pypi import installed_versions

    have = installed_versions() if have is None else have
    return any(p in have for p in ASSISTANT_PACKAGES)


def needs(reg: Registry, have: dict[str, str] | None = None) -> dict[str, Any]:
    """Per page with needs: is one of the packages it names installed here?"""
    from ovos_webui.pypi import installed_versions

    have = installed_versions() if have is None else have
    out = {}
    for page in reg.pages:
        if page.needs:
            out[page.id] = {"met": any(p.lower() in have for p in page.needs),
                            "suggest": page.needs[0]}
    return {"colocated": colocated(have), "needs": out}


_NAV_SLOT = re.compile(r"</head>", re.I)


def _shell() -> str:
    return resources.files("ovos_webui").joinpath("static", "shell.html").read_text(encoding="utf-8")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def render(page: Page, nav_json: str, brand: dict[str, Any] | None = None) -> str:
    """The page as served: with the menu data in its head, and a page body
    wrapped in the shell's header, menu and main, in the distribution's name.

    A heading with no key that is just the default name (the Dashboard's)
    shows the distribution's name instead.
    """
    from ovos_webui import branding

    brand = brand or branding.read({})
    tag = f'<script type="application/json" id="ovos-nav">{nav_json}</script>\n'
    if page.fragment:
        heading = page.heading
        if not page.heading_key and heading == branding.DEFAULT_NAME:
            heading = brand["name"]
        mark = ('<img class="brand-logo" src="/static/branding/logo" alt="">'
                if branding.logo_file(brand) else
                '<div class="wave" id="wave" aria-hidden="true">' + "<i></i>" * 28 + "</div>")
        parts = {"title": _esc(page.label), "heading": _esc(heading),
                 "heading_key": f' data-i18n="{_esc(page.heading_key)}"' if page.heading_key else "",
                 "id": _esc(page.id), "nav": tag, "brand": _esc(brand["name"]), "mark": mark}
        out = _shell()
        for name, value in parts.items():
            out = out.replace("{{" + name + "}}", value)
        # The body goes in last, so text in it that looks like a slot stays text.
        return out.replace("{{body}}", page.html)
    html, n = _NAV_SLOT.subn(tag + "</head>", page.html, count=1)
    return html if n else tag + page.html


# ── a page's own routes ──────────────────────────────────────────────────────
@dataclass
class Routes:
    """What a page's ``routes`` function is given.

    ``api`` and ``privileged`` are routers under ``/api`` with the panel's sign
    in and cross-site checks already on them; ``privileged`` also always needs
    the token. ``need_bus()`` returns the message bus, or answers 503 when it
    is not reachable; ``bus()`` returns it or ``None``, for a change that
    should tell the device if it can. ``config`` is the panel's configuration
    module.
    """

    api: Any
    privileged: Any
    need_bus: Callable[[], Any]
    config: Any
    bus: Callable[[], Any] = lambda: None


_PARAM_RE = re.compile(r"\{[^}]*\}")


def _matcher(path: str):
    """A regex for a route path: each {param} matches one path segment."""
    parts = _PARAM_RE.split(path)
    return re.compile("^" + "[^/]+".join(re.escape(p) for p in parts) + "$")


def _sample(path: str) -> str:
    """A concrete path a route template answers, with every {param} filled in."""
    return _PARAM_RE.sub("x", path)


def mount_routes(reg: Registry, make: Callable[[Page], Routes], taken: set[tuple[str, str]],
                 include: Callable[[Routes], None]) -> None:
    """Let each page with ``routes`` add its API routes.

    Pages' routes are matched before the shell's, so a page must not take an
    address the shell answers, not even through a ``{param}``; and a page must
    not add a route an earlier page would answer first. A page that does, or
    whose function fails, is left out entirely: its HTML would not work
    without its routes.
    """
    shell = set(taken)
    earlier: set[tuple[str, str]] = set()
    for page in list(reg.pages):
        if page.routes is None:
            continue
        r = make(page)
        try:
            page.routes(r)
        except Exception as e:  # noqa: BLE001 - a broken page is left out, not fatal
            reg.drop(page, f"its routes failed: {e}")
            continue
        mine = set()
        for router in (r.api, r.privileged):
            for route in router.routes:
                for method in getattr(route, "methods", None) or ():
                    mine.add((method, route.path))
        clash = sorted(
            {(m, p) for m, p in mine for sm, sp in shell
             if m == sm and _matcher(p).match(_sample(sp))}
            | {(m, p) for m, p in mine for em, ep in earlier
               if m == em and (_matcher(ep).match(_sample(p)) or _matcher(p).match(_sample(ep)))})
        if clash:
            reg.drop(page, "it adds routes that already exist: "
                     + ", ".join(f"{m} {p}" for m, p in clash))
            continue
        earlier |= mine
        include(r)
