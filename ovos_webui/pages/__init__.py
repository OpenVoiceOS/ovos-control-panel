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
_KNOWN = {"api_version", "id", "path", "title", "group", "groups", "order", "needs",
          "icon", "html", "assets", "i18n", "bus", "routes", "manual"}

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

    def nav(self) -> dict[str, Any]:
        """The menu, in order: groups that have pages, and the pages."""
        used = {p.group for p in self.pages}
        return {"groups": [dict(g) for g in self.groups if g["id"] in used],
                "pages": [p.nav() for p in self.pages]}

    def nav_json(self) -> str:
        """The menu as JSON that is safe inside a ``<script>`` element."""
        return json.dumps(self.nav(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


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
    html = _resource(module, desc.get("html")).read_text(encoding="utf-8")
    page = Page(id=pid, path=path, key=key, label=label, group=group, order=order,
                needs=tuple(needs), html=html, icon=_icon(module, desc.get("icon")),
                package=package, version=version, builtin=builtin, routes=routes,
                manual=desc.get("manual"))
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


def render(page: Page, nav_json: str) -> str:
    """The page's HTML with the menu data in its head."""
    tag = f'<script type="application/json" id="ovos-nav">{nav_json}</script>\n'
    html, n = _NAV_SLOT.subn(tag + "</head>", page.html, count=1)
    return html if n else tag + page.html
