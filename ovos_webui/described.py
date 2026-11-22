"""Pages described in a file: ``controlpanel.json``.

A skill or plugin can describe its page as data instead of bringing HTML and
Python (see ``docs/pages.md``, "Pages described in a file"). The panel finds
the file next to the package's ``skill.json`` without importing the package,
checks it, and draws it in the browser (``static/described.js``). The page
talks to its skill only through the bus messages the file declares, and only
with the data the file says (:func:`message_for`).

Nothing here imports or runs code from the package.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import logging
import re
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

FILE = "controlpanel.json"
#: The versions of the format this panel draws.
VERSIONS = frozenset({1})
MAX_FILE = 256 * 1024
MAX_STRINGS = 256 * 1024
MAX_ICON = 16 * 1024
#: The blocks this panel draws. A block of another type is drawn as "this
#: needs a newer control panel", and the rest of the page still works.
BLOCKS = frozenset({"text", "status", "list", "actions", "form", "choice", "upload", "module"})
FIELD_TYPES = frozenset({"text", "password", "url", "number", "slider", "checkbox", "select", "lines"})
_URL_RE = re.compile(r"^https?://[^\s/]+\S*$")
#: A page's messages start with its own prefix, never with one of these.
RESERVED_BUS = ("mycroft.", "ovos.skills.", "ovos.skill.", "ovos.common_play.", "ovos.phal.",
                "ovos.PHAL.", "ovos.intent", "ovos.utterance", "ovos.webui.", "system.",
                "recognizer_loop:", "speak", "intent.", "skill.", "gui.", "enclosure.",
                "opm.", "ovos.persona", "ovos.pipeline", "ovos.language", "ovos.session")
_BUS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*(\.[a-z0-9_-]+)*\.$")
_MSG_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_FIELD_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
#: a field in an answer, maybe nested: "ports.outputs"
_PATH_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}(\.[a-z_][a-z0-9_]{0,63}){0,3}$")
MAX_DATA = 4096
#: An upload goes to the skill over the bus in parts of this size, so no
#: message is larger than the bus takes; a file is at most MAX_UPLOAD_MB.
UPLOAD_PART = 512 * 1024
MAX_UPLOAD_MB = 64
_EXT_RE = re.compile(r"^\.[a-z0-9]{1,10}$")
_LANG_DIR = re.compile(r"^[a-zA-Z]{2,3}([-_][a-zA-Z0-9]{2,8})?$")
_CONFIG_RE = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_.-]+)*$")
#: What a download may be.
DOWNLOAD_TYPES = frozenset({"audio/midi", "audio/mpeg", "audio/ogg", "audio/wav", "audio/flac",
                            "application/pdf", "text/plain", "application/json", "image/png",
                            "image/jpeg", "image/webp", "application/epub+zip", "text/csv"})
#: An action whose message says one of these asks before it runs.
DESTRUCTIVE = ("delete", "remove", "forget", "reset", "wipe", "erase")
MAX_VALUE = 2000


class DescribedError(ValueError):
    """The file does not follow the format."""


@dataclass
class Found:
    """A ``controlpanel.json`` in an installed package."""

    package: str
    version: str
    module: str
    root: Path
    data: dict
    #: described by the panel, for a package that has no description of its own
    by_panel: bool = False


# ── finding the files ────────────────────────────────────────────────────────
def _tops(dist: metadata.Distribution) -> list[str]:
    """The top-level packages a distribution installs, without importing them."""
    tops: list[str] = []
    try:
        text = dist.read_text("top_level.txt") or ""
        tops += [t.strip() for t in text.splitlines() if t.strip()]
    except Exception:  # noqa: BLE001
        pass
    try:
        for ep in dist.entry_points:
            if ep.group.startswith(("opm.", "neon.", "mycroft.", "ovos.")):
                tops.append(ep.value.split(":", 1)[0].split(".", 1)[0].strip())
    except Exception:  # noqa: BLE001
        pass
    for f in dist.files or ():
        parts = str(f).split("/")
        if len(parts) == 2 and parts[1] == FILE:
            tops.append(parts[0])
    seen, out = set(), []
    for t in tops:
        if t and t.isidentifier() and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _package_dir(top: str) -> Path | None:
    """Where a top-level package lives. find_spec of a top-level name finds
    it without running it."""
    try:
        spec = importlib.util.find_spec(top)
    except (ImportError, ValueError):
        return None
    if spec is None:
        return None
    for location in spec.submodule_search_locations or ():
        return Path(location)
    return None


def discover() -> list[Found]:
    """Every ``controlpanel.json`` in an installed OVOS package."""
    from ovos_webui.pypi import classify
    out: list[Found] = []
    seen: set[str] = set()
    try:
        dists = list(metadata.distributions())
    except Exception as e:  # noqa: BLE001 - broken metadata must not stop the panel
        LOG.warning("could not read the installed packages: %s", e)
        return out
    from packaging.utils import canonicalize_name
    for dist in dists:
        # a wheel may name itself ovos_tts_plugin_server: the same package
        name = canonicalize_name((dist.metadata.get("Name") or "").strip())
        if not name or name in seen or classify(name) is None:
            continue
        seen.add(name)
        for top in _tops(dist):
            root = _package_dir(top)
            path = root / FILE if root else None
            if path is None or not path.is_file():
                continue
            raw = path.read_bytes()
            if len(raw) > MAX_FILE:
                LOG.warning("%s: %s is too large", name, FILE)
                continue
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                data = DescribedError(f"{FILE} is not JSON: {e}")
            out.append(Found(name, dist.version or "?", top, root, data))
            break
        else:
            found = _bundled(name, dist.version or "", _tops(dist))
            if found is not None:
                out.append(found)
    return out


#: Descriptions the panel brings for packages that have none of their own:
#: bundled/<package name>/controlpanel.json, with its locale/ and icon.
BUNDLED = Path(__file__).resolve().parent / "bundled"


def _bundled(name: str, version: str, tops: list[str]) -> Found | None:
    """The panel's description of ``name``, if it has one for this version.
    The file says what it is for: ``"for": "ovos-skill-weather>=1.0,<2"``.
    A version it was not written for gets no page, rather than one that
    writes the wrong keys."""
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion

    root = BUNDLED / canonicalize_name(name)
    path = root / FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        req = Requirement(str(data.get("for") or ""))
    except (OSError, ValueError, InvalidRequirement) as e:
        LOG.warning("the panel's description of %s cannot be used: %s", name, e)
        return None
    if canonicalize_name(req.name) != canonicalize_name(name):
        LOG.warning("the panel's description of %s is for %s", name, req.name)
        return None
    try:
        if req.specifier and not req.specifier.contains(version, prereleases=True):
            LOG.info("the panel's description of %s is for %s, not %s", name, req.specifier, version)
            return None
    except InvalidVersion:
        return None
    return Found(name, version or "?", tops[0] if tops else "", root, data, by_panel=True)


# ── checking a file ──────────────────────────────────────────────────────────
#: Where a plugin's own settings are in mycroft.conf, by its entry point's group
_CONFIG_PLACES = {"opm.tts": "tts", "mycroft.plugin.tts": "tts", "opm.stt": "stt",
                  "mycroft.plugin.stt": "stt", "opm.phal": "PHAL", "opm.phal.admin": "PHAL"}


def config_roots(package: str) -> list[str]:
    """A package's own places in mycroft.conf: PHAL.<package>, and the
    section its plugins read: tts.<module>, stt.<module>, PHAL.<name>.
    Never the choice of module itself (tts.module), only the plugin's own."""
    roots = ["PHAL." + package]
    try:
        eps = metadata.distribution(package).entry_points
    except Exception:  # noqa: BLE001 - only the default then
        return roots
    for ep in eps:
        place = _CONFIG_PLACES.get(ep.group)
        if place and _CONFIG_RE.match(f"{place}.{ep.name}"):
            roots.append(f"{place}.{ep.name}")
    return list(dict.fromkeys(roots))


#: The kinds of plugin a page can make the one in use (a "module" block)
MODULE_KINDS = {"tts": ("opm.tts", "mycroft.plugin.tts"), "stt": ("opm.stt", "mycroft.plugin.stt")}


def plugin_modules(package: str) -> dict[str, list[str]]:
    """The TTS and STT modules a package brings, by kind: their entry point
    names, which are what mycroft.conf calls them (tts.module)."""
    out: dict[str, list[str]] = {}
    try:
        eps = metadata.distribution(package).entry_points
    except Exception:  # noqa: BLE001 - none then
        return out
    for kind, groups in MODULE_KINDS.items():
        names = sorted({ep.name for ep in eps if ep.group in groups and _CONFIG_RE.match(ep.name)})
        if names:
            out[kind] = names
    return out


def is_key(raw: Any) -> bool:
    """Whether a text is a label's key (``books.title``)."""
    return isinstance(raw, str) and bool(_KEY_RE.match(raw))


def _label(raw: Any, where: str) -> dict[str, str]:
    """A label is a key, or a key with its English text."""
    if isinstance(raw, str) and _KEY_RE.match(raw):
        return {"key": raw}
    if isinstance(raw, dict) and isinstance(raw.get("key"), str) and _KEY_RE.match(raw["key"]):
        out = {"key": raw["key"]}
        if isinstance(raw.get("en"), str):
            out["en"] = raw["en"][:500]
        return out
    raise DescribedError(f"{where}: not a label: {raw!r}")


def _field_name(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not _FIELD_RE.match(raw):
        raise DescribedError(f"{where}: not a field name: {raw!r}")
    return raw


def _path(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not _PATH_RE.match(raw):
        raise DescribedError(f"{where}: not a field: {raw!r}")
    return raw


def _when(raw: Any, where: str) -> str | None:
    """A condition: a field that is true, or "!field" for false."""
    if raw is None:
        return None
    if isinstance(raw, str) and _PATH_RE.match(raw.lstrip("!")):
        return raw
    raise DescribedError(f"{where}: not a condition: {raw!r}")


class _Checker:
    def __init__(self, data: dict, package: str):
        self.data = data
        self.package = package
        self.prefix = data.get("bus")
        if not isinstance(self.prefix, str) or not _BUS_RE.match(self.prefix) \
                or self.prefix.startswith(RESERVED_BUS):
            raise DescribedError(f"bus must be the page's own prefix, like 'ovos.jamband.', "
                                 f"not {self.prefix!r}")
        self.refs: dict[str, dict] = {}

    def message(self, raw: Any, where: str) -> str:
        if not isinstance(raw, str) or not _MSG_RE.match(raw) or not raw.startswith(self.prefix):
            raise DescribedError(f"{where}: {raw!r} is not one of the page's messages "
                                 f"(they start with {self.prefix})")
        return raw

    def action(self, raw: Any, where: str, row: bool) -> dict:
        if not isinstance(raw, dict):
            raise DescribedError(f"{where}: not an action")
        out: dict[str, Any] = {"label": _label(raw.get("label"), where), "row": row}
        if raw.get("download"):
            out["download"] = self.message(raw["download"], where)
            spec = raw.get("file") or {}
            kind = spec.get("type")
            if kind not in DOWNLOAD_TYPES:
                raise DescribedError(f"{where}: a download is one of {sorted(DOWNLOAD_TYPES)}")
            out["file"] = {"data": _field_name(spec.get("data", "data"), where),
                           "name": str(spec.get("name") or "download")[:200], "type": kind}
            out["privileged"] = bool(raw.get("privileged", False))
        else:
            out["send"] = self.message(raw.get("send"), where)
            out["privileged"] = bool(raw.get("privileged", True))
            if raw.get("data") is not None:
                # what the button always sends (a test sound, a choice)
                if not isinstance(raw["data"], dict) or len(json.dumps(raw["data"])) > MAX_DATA:
                    raise DescribedError(f"{where}: data must be a small object")
                out["data"] = raw["data"]
        out["when"] = _when(raw.get("when"), where)
        confirm = raw.get("confirm")
        if confirm is not None:
            out["confirm"] = _label(confirm, where)
        elif any(w in (out.get("send") or "").lower() for w in DESTRUCTIVE):
            out["confirm"] = {"key": "common.sure"}
        return out

    def field(self, raw: Any, where: str) -> dict:
        if not isinstance(raw, dict):
            raise DescribedError(f"{where}: not a field")
        kind = raw.get("type", "text")
        if kind not in FIELD_TYPES:
            raise DescribedError(f"{where}: a field is one of {sorted(FIELD_TYPES)}")
        out: dict[str, Any] = {"name": _field_name(raw.get("name"), where), "type": kind,
                               "label": _label(raw.get("label"), where)}
        if raw.get("hint") is not None:
            out["hint"] = _label(raw["hint"], where)
        for num in ("min", "max", "step"):
            if num in raw:
                if not isinstance(raw[num], (int, float)) or isinstance(raw[num], bool):
                    raise DescribedError(f"{where}: {num} must be a number")
                out[num] = raw[num]
        out["max_length"] = min(int(raw.get("max_length", 300)), MAX_VALUE)
        out["required"] = bool(raw.get("required", False))
        if "default" in raw:
            # a value equal to it leaves the setting out of the file
            out["default"] = raw["default"]
        if raw.get("show_when") is not None:
            cond = raw["show_when"]
            if not isinstance(cond, dict) or len(cond) != 1:
                raise DescribedError(f"{where}: show_when is one field and its value")
            name, value = next(iter(cond.items()))
            out["show_when"] = {"field": _field_name(name, where), "value": value}
        if kind == "checkbox" and ("on" in raw or "off" in raw):
            # a setting that is not true/false: ["*"] when ticked, [] when not
            out["on"], out["off"] = raw.get("on", True), raw.get("off", False)
        if kind == "select":
            if raw.get("options_from"):
                src = raw["options_from"]
                out["options_from"] = {"query": self.message(src.get("query"), where),
                                       "items": _path(src.get("items", "options"), where),
                                       "value": _field_name(src.get("value", "value"), where),
                                       "label": _field_name(src.get("label", "label"), where)}
            options = raw.get("options") or []
            if not isinstance(options, list):
                raise DescribedError(f"{where}: options must be a list")
            out["options"] = [{"value": str(o.get("value"))[:200], "label": _label(o.get("label"), where)}
                              for o in options if isinstance(o, dict)]
            if not out["options"] and "options_from" not in out:
                raise DescribedError(f"{where}: a select needs options")
        return out

    def block(self, raw: Any, n: int) -> dict:
        where = f"block {n + 1}"
        if not isinstance(raw, dict):
            raise DescribedError(f"{where}: not a block")
        kind = raw.get("type")
        ref = f"b{n}"
        out: dict[str, Any] = {"type": kind, "ref": ref}
        if kind not in BLOCKS:
            # a newer panel's block: shown as such, the rest still works
            out["type"] = "unknown"
            out["was"] = str(kind)[:40]
            return out
        if kind == "text":
            if raw.get("steps") is not None:
                steps = raw["steps"]
                if not isinstance(steps, list) or not steps or len(steps) > 20:
                    raise DescribedError(f"{where}: steps must be a list of up to 20 labels")
                out["steps"] = [_label(x, f"{where}.steps") for x in steps]
            if raw.get("text") is not None or "steps" not in out:
                out["text"] = _label(raw.get("text"), where)
        if kind in ("status", "list"):
            out["query"] = self.message(raw.get("query"), where)
            if raw.get("refresh") is not None:
                out["refresh"] = max(2, min(int(raw["refresh"]), 3600))
        if kind == "status":
            if raw.get("text") is not None:
                out["text"] = _label(raw["text"], where)
            out["show"] = _when(raw.get("show"), where)
            rows = raw.get("rows") or []
            if not isinstance(rows, list):
                raise DescribedError(f"{where}: rows must be a list")
            out["rows"] = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                row = {"value": str(r.get("value", ""))[:300], "when": _when(r.get("when"), where)}
                # a row without a label is a note across the card
                if r.get("label") is not None:
                    row["label"] = _label(r["label"], where)
                elif r.get("text") is None and not row["value"]:
                    raise DescribedError(f"{where}: a row has a label, or is a note with a text")
                # a label for the value (a hint), and one for when it is empty
                for extra in ("text", "empty"):
                    if r.get(extra) is not None:
                        row[extra] = _label(r[extra], where)
                out["rows"].append(row)
            if "text" not in out and not out["rows"]:
                raise DescribedError(f"{where}: a status has a text or rows")
        if kind == "list":
            out["items"] = _path(raw.get("items", "items"), where)
            out["key"] = _field_name(raw.get("key", "id"), where)
            out["title"] = str(raw.get("title") or "{" + out["key"] + "}")[:200]
            if raw.get("meta") is not None:
                out["meta"] = _label(raw["meta"], where)
            if raw.get("empty") is not None:
                out["empty"] = _label(raw["empty"], where)
            split = raw.get("split")
            if split:
                out["split"] = {"by": _field_name(split.get("by"), where),
                                "true": _label(split.get("true"), where),
                                "false": _label(split.get("false"), where)}
            flt = raw.get("filter")
            if flt:
                if not isinstance(flt, dict):
                    raise DescribedError(f"{where}: a filter is an object")
                out["filter"] = {"by": _field_name(flt.get("by"), where),
                                 "label": _label(flt.get("label"), where),
                                 "all": _label(flt.get("all", "common.all"), where)}
            rename = raw.get("rename")
            if rename:
                out["rename"] = {"field": _field_name(rename.get("field"), where),
                                 "send": self.message(rename.get("send"), where),
                                 "when": _when(rename.get("when"), where),
                                 "max_length": min(int(rename.get("max_length", 120)), 300),
                                 "privileged": bool(rename.get("privileged", True))}
                if rename.get("label") is not None:
                    out["rename"]["label"] = _label(rename["label"], where)
                self.refs[ref + ".rename"] = {"kind": "rename", "block": out, **out["rename"]}
        if kind in ("status", "list", "actions"):
            actions = raw.get("actions") or []
            if not isinstance(actions, list):
                raise DescribedError(f"{where}: actions must be a list")
            out["actions"] = []
            for j, a in enumerate(actions):
                act = self.action(a, f"{where}, action {j + 1}", row=kind == "list")
                act["ref"] = f"{ref}.a{j}"
                out["actions"].append(act)
                self.refs[act["ref"]] = {"kind": "action", "block": out, **act}
        if kind == "form":
            fields = raw.get("fields") or []
            if not isinstance(fields, list) or not fields:
                raise DescribedError(f"{where}: a form needs fields")
            out["fields"] = [self.field(f, f"{where}, field {k + 1}") for k, f in enumerate(fields)]
            save = raw.get("save") or {}
            if save.get("config"):
                path = save["config"]
                roots = getattr(self, "config_roots", None) or ["PHAL." + self.package]
                if not isinstance(path, str) or not _CONFIG_RE.match(path) \
                        or not any(path == own or path.startswith(own + ".") for own in roots):
                    raise DescribedError(f"{where}: a form saves in the package's own place in "
                                         f"mycroft.conf ({', '.join(roots)}), not {path!r}")
                out["config"] = path
                if save.get("reload"):
                    out["reload"] = self.message(save["reload"], where)
            elif save.get("settings"):
                if save["settings"] is not True:
                    raise DescribedError(f"{where}: settings is true")
                if not getattr(self, "skill_id", None):
                    raise DescribedError(f"{where}: only the page of a package with one skill saves "
                                         "in that skill's settings")
                out["settings"] = self.skill_id
            elif save.get("send"):
                out["send"] = self.message(save["send"], where)
                out["query"] = self.message(raw.get("query"), where)
            else:
                raise DescribedError(f"{where}: a form saves with send, config or settings")
            self.refs[ref + ".form"] = {"kind": "form", "block": out}
        if kind == "module":
            # the panel's own part: whether this plugin is the one in use, to
            # make it so, and to hear it; nothing of it comes from the file
            mkind = raw.get("kind")
            if mkind not in MODULE_KINDS:
                raise DescribedError(f"{where}: kind is one of {sorted(MODULE_KINDS)}")
            names = (getattr(self, "modules", None) or {}).get(mkind) or []
            if len(names) != 1:
                raise DescribedError(f"{where}: the package brings no {mkind} plugin, or more than one")
            out["kind"] = mkind
            out["module"] = names[0]
            self.refs[ref + ".module"] = {"kind": "module", "block": out}
        if kind == "upload":
            out["send"] = self.message(raw.get("send"), where)
            accept = raw.get("accept") or []
            if not isinstance(accept, list) or not accept or len(accept) > 30 \
                    or not all(isinstance(a, str) and _EXT_RE.match(a.lower()) for a in accept):
                raise DescribedError(f"{where}: accept is a list of file endings (.pdf)")
            out["accept"] = sorted({a.lower() for a in accept})
            mb = raw.get("max_mb", 10)
            if not isinstance(mb, int) or isinstance(mb, bool) or not 1 <= mb <= MAX_UPLOAD_MB:
                raise DescribedError(f"{where}: max_mb is a whole number from 1 to {MAX_UPLOAD_MB}")
            out["max_mb"] = mb
            if raw.get("field") is not None:
                f = raw["field"]
                if not isinstance(f, dict):
                    raise DescribedError(f"{where}: the field is an object")
                out["field"] = {"name": _field_name(f.get("name"), where), "label": _label(f.get("label"), where),
                                "max_length": min(int(f.get("max_length", 200)), 300)}
            out["privileged"] = True
            self.refs[ref + ".upload"] = {"kind": "upload", "block": out}
        if kind == "choice":
            out["param"] = _field_name(raw.get("param"), where)
            options = raw.get("options") or []
            out["options"] = [{"value": str(o.get("value"))[:100], "label": _label(o.get("label"), where)}
                              for o in options if isinstance(o, dict)]
            if not out["options"]:
                raise DescribedError(f"{where}: a choice needs options")
        if kind in ("status", "list", "form") and "query" in out:
            self.refs[ref] = {"kind": "query", "block": out}
        # a heading over the block ("title" for a list is its rows' title)
        heading = raw.get("heading", raw.get("title") if kind != "list" else None)
        if heading is not None:
            out["heading"] = _label(heading, where)
        return out


def check(data: Any, package: str, skill_id: str | None = None,
          config_roots: list[str] | None = None,
          modules: dict[str, list[str]] | None = None) -> tuple[dict, dict[str, dict]]:
    """Check a file; return the page as the browser gets it, and the
    declarations the bus bridge goes by (ref -> what it may send).
    ``skill_id`` is the skill the package registers, if it is a skill: a
    form may then save in that skill's settings.json. ``config_roots`` are
    the package's own places in mycroft.conf (PHAL.<package> by default)."""
    if isinstance(data, Exception):
        raise DescribedError(str(data))
    if not isinstance(data, dict):
        raise DescribedError("the file is not a JSON object")
    if data.get("controlpanel") not in VERSIONS:
        raise DescribedError(f"written for format {data.get('controlpanel')!r}; "
                             f"this panel draws {sorted(VERSIONS)}")
    checker = _Checker(data, package)
    checker.skill_id = skill_id
    checker.config_roots = config_roots
    checker.modules = modules or {}
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise DescribedError("blocks must be a list of blocks")
    page = {"id": data.get("id"), "bus": checker.prefix,
            "blocks": [checker.block(b, n) for n, b in enumerate(blocks[:50])]}
    params = {b["param"]: {o["value"] for o in b["options"]}
              for b in page["blocks"] if b["type"] == "choice"}
    for decl in checker.refs.values():
        decl["params"] = params
    return page, checker.refs


def strings(root: Path) -> dict[str, dict[str, str]]:
    """``locale/<lang>/controlpanel.json`` per language code (da-DK and da
    are both da). The country with the same name as the language wins
    (pt-PT over pt-BR), otherwise the first."""
    out: dict[str, dict[str, str]] = {}
    locale = root / "locale"
    if not locale.is_dir():
        return out
    folders = sorted(d for d in locale.iterdir() if d.is_dir() and _LANG_DIR.match(d.name))
    for d in sorted(folders, key=lambda d: (d.name.replace("_", "-").lower().split("-")[-1]
                                            != d.name.lower().split("-")[0].split("_")[0], d.name)):
        f = d / FILE
        if not f.is_file():
            continue
        lang = d.name.replace("_", "-").lower().split("-")[0]
        if lang in out:
            continue
        raw = f.read_bytes()
        if len(raw) > MAX_STRINGS:
            continue
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out[lang] = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    return out


def english(page: dict, found: dict[str, dict[str, str]]) -> dict[str, str]:
    """The English text of every label: from locale/en, else from the file."""
    out: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "key" in node and "en" in node and isinstance(node["en"], str):
                out.setdefault(node["key"], node["en"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(page)
    out.update(found.get("en") or {})
    return out


def icon(root: Path, spec: Any) -> str | None:
    """The page's icon: an SVG file in the package, as a data: URL."""
    if not spec:
        return None
    if not isinstance(spec, str) or spec.startswith("/") or "\\" in spec \
            or any(not p or p.startswith(".") for p in spec.split("/")):
        raise DescribedError(f"not a file in the package: {spec!r}")
    path = root.joinpath(*spec.split("/"))
    if not path.is_file():
        raise DescribedError(f"{spec} is not there")
    svg = path.read_bytes()
    if b"<svg" not in svg[:512] or len(svg) > MAX_ICON:
        raise DescribedError("the icon is not a small SVG")
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")


# ── the bus bridge: what a request may send ──────────────────────────────────
def _text(value: Any, limit: int) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise DescribedError("a value must be text")
    text = str(value)
    if len(text) > limit:
        raise DescribedError("a value is too long")
    return text


def _params(decl: dict, given: Any) -> dict[str, str]:
    out = {}
    for name, value in (given or {}).items() if isinstance(given, dict) else ():
        allowed = decl.get("params", {}).get(name)
        if allowed is None or str(value) not in allowed:
            raise DescribedError(f"{name} is not one of the page's choices")
        out[name] = str(value)
    return out


def message_for(refs: dict[str, dict], ref: str, body: dict) -> tuple[str, dict, dict]:
    """The bus message a request may send for ``ref``: (type, data, the
    declaration). Only what the file declared, with only the data it said."""
    decl = refs.get(ref)
    if decl is None:
        raise DescribedError("the page has no such part")
    data = _params(decl, body.get("params"))
    kind = decl["kind"]
    if kind == "query":
        return decl["block"]["query"], data, decl
    block = decl["block"]
    if kind == "action":
        if decl["row"]:
            data[block["key"]] = _text(body.get("key"), 300)
        msg = decl.get("send") or decl.get("download")
        if decl.get("data"):
            data = {**decl["data"], **data}
        return msg, data, decl
    if kind == "rename":
        data[block["key"]] = _text(body.get("key"), 300)
        data[decl["field"]] = _text(body.get("value"), decl["max_length"]).strip()
        return decl["send"], data, decl
    raise DescribedError("that part takes no message")


def form_values(decl: dict, given: Any) -> dict[str, Any]:
    """A form's values, each checked against its field."""
    if not isinstance(given, dict):
        raise DescribedError("the values must be an object")
    out: dict[str, Any] = {}
    for f in decl["block"]["fields"]:
        name = f["name"]
        if name not in given:
            continue
        value = given[name]
        kind = f["type"]
        if kind == "checkbox":
            if not isinstance(value, bool):
                raise DescribedError(f"{name} is yes or no")
            if "on" in f:
                value = f["on"] if value else f["off"]
        elif kind in ("number", "slider"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise DescribedError(f"{name} is a number")
            if ("min" in f and value < f["min"]) or ("max" in f and value > f["max"]):
                raise DescribedError(f"{name} is out of range")
        elif kind == "lines":
            if not isinstance(value, list) or len(value) > 200:
                raise DescribedError(f"{name} is a list")
            value = [_text(v, f["max_length"]).strip() for v in value]
            value = [v for v in value if v]
        elif kind == "select":
            value = _text(value, 200)
            fixed = {o["value"] for o in f.get("options") or ()}
            if fixed and "options_from" not in f and value not in fixed:
                raise DescribedError(f"{name} is not one of its options")
        else:
            value = _text(value, f["max_length"]).strip() if kind == "url" else _text(value, f["max_length"])
            if kind == "password" and value == "":
                continue    # an empty password keeps the one there is
            if kind == "url" and value:
                value = value.rstrip("/")
                if not _URL_RE.match(value):
                    raise DescribedError(f"{name} is an address that starts with http:// or https://")
        if f.get("required") and value in ("", None, []):
            raise DescribedError(f"{name} is needed")
        out[name] = value
    return out


def missing(decl: dict, values: dict, existing: Any) -> list[str]:
    """Required fields neither given now nor saved before (a password left
    empty keeps the one there is, so one is needed the first time only)."""
    existing = existing if isinstance(existing, dict) else {}
    return [f["name"] for f in decl["block"]["fields"]
            if f.get("required") and f["name"] not in values and not existing.get(f["name"])]


# ── the routes a described page gets ─────────────────────────────────────────
TIMEOUT = 10.0


def _ask(r, msg_type: str, data: dict) -> dict:
    from fastapi import HTTPException
    from ovos_bus_client.message import Message

    from ovos_webui import buswait
    reply = buswait.wait_for_response(r.need_bus(), Message(msg_type, data), timeout=TIMEOUT)
    if reply is None:
        raise HTTPException(504, "the skill or plugin did not answer; is it running?")
    if isinstance(reply.data, dict) and reply.data.get("error"):
        raise HTTPException(400, str(reply.data["error"])[:300])
    return reply.data if isinstance(reply.data, dict) else {}


def _get_in(data: Any, path: list[str]) -> Any:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def routes_for(pid: str, refs: dict[str, dict]):
    """The routes of a described page: its bus bridge. Every request names a
    part of the page (``ref``); the message and the data it may carry come
    from the file, never from the request."""
    from fastapi import Body, HTTPException, Request, Response

    def bad(e: Exception):
        return HTTPException(400, str(e))

    def act(r, body: dict, privileged: bool) -> dict:
        try:
            msg, data, decl = message_for(refs, str(body.get("ref", "")), body)
        except DescribedError as e:
            raise bad(e) from None
        if decl["kind"] == "query" or decl.get("download"):
            raise HTTPException(400, "that part is not an action")
        if decl.get("privileged", True) and not privileged:
            raise HTTPException(403, "this needs the access token")
        return _ask(r, msg, data)

    def add(r) -> None:
        base = f"/cp/{pid}"

        @r.api.post(base + "/query")
        def query(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            decl = refs.get(str(body.get("ref", "")))
            if decl is None or decl["kind"] not in ("query",) and not (
                    decl["kind"] == "form" and "query" in decl["block"]):
                raise HTTPException(400, "that part asks for nothing")
            try:
                params = _params(decl, body.get("params"))
            except DescribedError as e:
                raise bad(e) from None
            return _ask(r, decl["block"]["query"], params)

        @r.api.post(base + "/options")
        def options(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            decl = refs.get(str(body.get("ref", "")))
            name = body.get("field")
            if decl is None or decl["kind"] != "form":
                raise HTTPException(400, "that part has no fields")
            field_ = next((f for f in decl["block"]["fields"] if f["name"] == name), None)
            if not field_ or "options_from" not in field_:
                raise HTTPException(400, "that field has no options to ask for")
            return _ask(r, field_["options_from"]["query"], {})

        @r.privileged.post(base + "/act")
        def act_locked(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            return act(r, body, privileged=True)

        @r.api.post(base + "/act-open")
        def act_open(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            return act(r, body, privileged=False)

        def download(ref: str, key: str, privileged: bool) -> Response:
            decl = refs.get(ref)
            if decl is None or not decl.get("download"):
                raise HTTPException(400, "that part is not a download")
            if decl.get("privileged") and not privileged:
                raise HTTPException(403, "this needs the access token")
            try:
                msg, data, _ = message_for(refs, ref, {"key": key})
            except DescribedError as e:
                raise bad(e) from None
            answer = _ask(r, msg, data)
            spec = decl["file"]
            try:
                raw = base64.b64decode(str(answer.get(spec["data"]) or ""), validate=True)
            except ValueError as e:
                raise HTTPException(502, "the answer carried no file") from e
            from urllib.parse import quote
            name = spec["name"]
            for k, v in answer.items():
                if isinstance(v, (str, int, float)):
                    name = name.replace("{" + k + "}", str(v))
            name = re.sub(r"[\x00-\x1f\"\\\\/]+", "_", name).strip()[:150] or "download"
            plain = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip() or "download"
            return Response(raw, media_type=spec["type"], headers={
                "Content-Disposition": f'attachment; filename="{plain}"; '
                                       f"filename*=UTF-8''{quote(name)}",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'"})

        @r.api.get(base + "/download")
        def download_open(ref: str, key: str = "") -> Response:
            return download(ref, key, privileged=False)

        @r.privileged.get(base + "/download-locked")
        def download_locked(ref: str, key: str = "") -> Response:
            return download(ref, key, privileged=True)

        @r.api.get(base + "/form")
        def form_read(ref: str) -> dict[str, Any]:
            decl = refs.get(ref)
            if decl is None or decl["kind"] != "form":
                raise HTTPException(400, "that part is not a form")
            block = decl["block"]
            if "config" in block:
                values = r.config.user_or_merged(block["config"].split(".")) or {}
            elif "settings" in block:
                values = _read_settings(block["settings"])
            else:
                values = _ask(r, block["query"], {})
            out = {}
            for f in block["fields"]:
                value = _get_in(values, [f["name"]])
                if f["type"] == "password":
                    out[f["name"]] = {"set": bool(value)}   # never sent back
                elif value is not None:
                    out[f["name"]] = value
                elif "default" in f:
                    out[f["name"]] = f["default"]
            return {"values": out}

        @r.privileged.post(base + "/form")
        def form_save(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            decl = refs.get(str(body.get("ref", "")))
            if decl is None or decl["kind"] != "form":
                raise HTTPException(400, "that part is not a form")
            try:
                values = form_values(decl, body.get("values"))
            except DescribedError as e:
                raise bad(e) from None
            block = decl["block"]
            if "config" in block:
                path = block["config"].split(".")
                lacking = missing(decl, values, r.config.user_or_merged(path))
                if lacking:
                    raise HTTPException(400, ", ".join(lacking) + " is needed")
                defaults = {f["name"]: f["default"] for f in block["fields"] if "default" in f}

                def change(user: dict) -> None:
                    node = user
                    for key in path:
                        node = node.setdefault(key, {})
                    for name, value in values.items():
                        # a default leaves the file, so it says only what was changed
                        if name in defaults and value == defaults[name]:
                            node.pop(name, None)
                        else:
                            node[name] = value

                r.config.mutate(change, bus=r.bus())
                if block.get("reload"):
                    try:
                        from ovos_bus_client.message import Message
                        section = r.config.user_or_merged(path) or {}
                        # the plugin starts again with its section as saved
                        r.need_bus().emit(Message(block["reload"], {"config": section}))
                    except HTTPException:
                        pass    # saved; the plugin reads it when it starts
                return {"ok": True}
            if "settings" in block:
                skill_id = block["settings"]
                lacking = missing(decl, values, _read_settings(skill_id))
                if lacking:
                    raise HTTPException(400, ", ".join(lacking) + " is needed")
                from ovos_webui import skillsio
                try:
                    # merged over what is there, read again right before
                    # writing: keys the form has not are kept
                    skillsio.write_settings(skill_id, values)
                except skillsio.SkillSettingsError as e:
                    raise HTTPException(400, str(e)) from None
                return {"ok": True}
            return _ask(r, block["send"], values)

        def module_decl(ref: str) -> dict:
            decl = refs.get(ref)
            if decl is None or decl["kind"] != "module":
                raise HTTPException(400, "that part is not a plugin to use")
            return decl["block"]

        @r.api.get(base + "/module")
        def module_read(ref: str) -> dict[str, Any]:
            block = module_decl(ref)
            section = r.config.user_or_merged([block["kind"]]) or {}
            return {"module": block["module"],
                    "active": section.get("module") == block["module"],
                    "fallback": section.get("fallback_module") == block["module"]}

        @r.privileged.post(base + "/module")
        def module_use(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            block = module_decl(str(body.get("ref", "")))
            role = body.get("as")
            if role not in ("module", "fallback_module"):
                raise HTTPException(400, "as is module or fallback_module")

            def change(user: dict) -> None:
                user.setdefault(block["kind"], {})[role] = block["module"]

            r.config.mutate(change, bus=r.bus())
            return module_read(str(body["ref"]))

        @r.privileged.post(base + "/module/test")
        def module_test(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            block = module_decl(str(body.get("ref", "")))
            if block["kind"] != "tts":
                raise HTTPException(400, "only a voice can be heard")
            if (r.config.user_or_merged([block["kind"], "module"]) or "") != block["module"]:
                # what is said is said with the voice in use
                raise HTTPException(409, "it is not the voice in use")
            try:
                text = _text(body.get("text") or "", 200).strip()
                lang = _text(body.get("lang") or "", 20)
            except DescribedError as e:
                raise bad(e) from None
            if not text:
                raise HTTPException(400, "nothing to say")
            from ovos_bus_client.message import Message
            r.need_bus().emit(Message("speak", {"utterance": text, "lang": lang}))
            return {"ok": True}

        async def upload(request: Request) -> dict[str, Any]:
            from starlette.concurrency import run_in_threadpool
            form = await request.form()
            decl = refs.get(str(form.get("ref", "")))
            if decl is None or decl["kind"] != "upload":
                raise HTTPException(400, "that part is not an upload")
            block = decl["block"]
            file = form.get("file")
            if not hasattr(file, "read"):
                raise HTTPException(400, "no file was sent")
            name = upload_name(getattr(file, "filename", "") or "")
            if Path(name).suffix.lower() not in block["accept"]:
                raise HTTPException(415, "the file is not one of " + ", ".join(block["accept"]))
            blob = await file.read()
            if not blob:
                raise HTTPException(400, "the file is empty")
            if len(blob) > block["max_mb"] * 1024 * 1024:
                raise HTTPException(413, f"the file is larger than {block['max_mb']} MB")
            extra = {}
            if block.get("field"):
                f = block["field"]
                extra[f["name"]] = _text(form.get(f["name"]) or "", f["max_length"]).strip()
            return await run_in_threadpool(send_upload, r, block["send"], name, blob, extra)

        # this module's annotations are text; the route needs the class itself
        upload.__annotations__["request"] = Request
        r.privileged.post(base + "/upload")(upload)

    return add


def _read_settings(skill_id: str) -> dict:
    """A skill's settings.json; nothing when it cannot be read."""
    from ovos_webui import skillsio
    try:
        return skillsio.read_settings(skill_id)
    except (skillsio.SkillSettingsError, ValueError):
        return {}


def upload_name(name: str) -> str:
    """A file's name without folders or characters a file name cannot have."""
    import unicodedata
    name = unicodedata.normalize("NFC", name.replace("\\", "/").rsplit("/", 1)[-1]).strip()
    name = re.sub(r'[\x00-\x1f/\\:*?"<>|]+', "_", name).lstrip(".")
    return name[:180] or "file"


def send_upload(r, msg_type: str, name: str, blob: bytes, extra: dict) -> dict:
    """Send a file to the skill in parts: each message carries ``upload`` (the
    same id for every part), ``name``, ``part`` (from 0), ``parts`` and
    ``data`` (base64), and the upload's field. The answer to the last part is
    the skill's answer."""
    import uuid
    upload_id = uuid.uuid4().hex
    parts = max(1, -(-len(blob) // UPLOAD_PART))
    answer: dict = {}
    for n in range(parts):
        chunk = blob[n * UPLOAD_PART:(n + 1) * UPLOAD_PART]
        answer = _ask(r, msg_type, {"upload": upload_id, "name": name, "part": n, "parts": parts,
                                    "data": base64.b64encode(chunk).decode("ascii"), **extra})
    return answer
