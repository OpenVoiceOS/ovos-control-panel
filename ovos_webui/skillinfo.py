"""What a skill is: who made it, where its source is, and what to say to it.

Two places know this, and a skill's page shows both:

* the package metadata: author or maintainer, the project links (the source,
  usually on GitHub), the license and the version. For an installed skill it is
  read from the installed distribution; for one that is not installed, from
  PyPI's JSON API.
* the skill's own ``skill.json``, usually one per language under
  ``locale/<lang>/skill.json``: its name and description in the device's
  language, example sentences, and an icon. It is not on PyPI's JSON, so for a
  skill that is not installed the wheel is downloaded (once per version, and
  size-capped) and the file is read out of it.

An icon is a URL in ``skill.json``. The panel's CSP keeps the browser to its
own origin, so the panel fetches the icon itself and serves it: only from the
code hosts skills use, only raster image types, and size-capped. SVG is left
out, because an SVG opened on the panel's origin could run script.

Whether a ``skill-*`` package is an OpenVoiceOS skill at all is not in its
name: most packages called that on PyPI are something else. A real one
depends on OVOS (or Neon, or Mycroft); :func:`is_ovos_skill_listing` checks
that from PyPI's JSON, and :func:`installed_is_ovos_skill` from the installed
metadata.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import urllib.error
import urllib.parse
import zipfile
from importlib import metadata
from pathlib import Path
from typing import Any

from ovos_utils.log import LOG

#: A requirement on an OVOS, Neon or Mycroft package.
_OVOS_REQ = re.compile(r"^\s*(ovos|neon|mycroft)[-_.]", re.IGNORECASE)

#: The wheel of a skill that is not installed is read for its skill.json.
MAX_WHEEL_BYTES = 20 * 1024 * 1024
#: An icon larger than this is not shown.
MAX_ICON_BYTES = 512 * 1024
#: The hosts an icon is fetched from. These are where skills keep them.
ICON_HOSTS = frozenset({"raw.githubusercontent.com", "github.com", "raw.githack.com"})
#: Image types by their first bytes; anything else is not served.
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_LOCK = threading.Lock()


class NotASkill(ValueError):
    """The name is not a skill package the panel handles."""


# ── is this an OpenVoiceOS skill? ────────────────────────────────────────────
def requires_ovos(requires: list[str] | None) -> bool:
    """True when one of the requirements is an OVOS, Neon or Mycroft package."""
    return any(_OVOS_REQ.match(r or "") for r in (requires or []))


def is_ovos_skill_listing(project_json: dict[str, Any]) -> bool:
    """Judge a ``skill-*`` package from its PyPI JSON."""
    return requires_ovos((project_json.get("info") or {}).get("requires_dist"))


#: The entry point groups a skill registers under: ``opm.skill`` is the one
#: ovos-plugin-manager uses now, ``ovos.plugin.skill`` the older name it still
#: reads.
SKILL_GROUPS = ("opm.skill", "ovos.plugin.skill")
_GROUP_RE = re.compile(rb"^\s*\[\s*(" + b"|".join(re.escape(g.encode()) for g in SKILL_GROUPS)
                       + rb")\s*\]", re.M)


def installed_is_ovos_skill(dist: metadata.Distribution) -> bool:
    """Judge an installed package: it registers a skill, or depends on OVOS."""
    try:
        if any(ep.group in SKILL_GROUPS for ep in dist.entry_points):
            return True
    except Exception:  # noqa: BLE001 - broken metadata is not a skill
        return False
    return requires_ovos(dist.requires)


# ── skill.json ───────────────────────────────────────────────────────────────
def _lang_key(path: str) -> str:
    match = re.search(r"locale/([^/]+)/skill\.json$", path)
    return match.group(1).lower().replace("_", "-") if match else ""


def pick_skill_json(paths: list[str], lang: str) -> str | None:
    """Choose the skill.json for ``lang``: the exact language, then the same
    language in another country, then English, then any."""
    found = [p for p in paths if p.endswith("skill.json")]
    if not found:
        return None
    lang = (lang or "en-us").lower().replace("_", "-")
    base = lang.split("-")[0]
    by_lang = {_lang_key(p): p for p in found}
    if lang in by_lang:
        return by_lang[lang]
    for key, path in sorted(by_lang.items()):
        if key.split("-")[0] == base:
            return path
    for key, path in sorted(by_lang.items()):
        if key.startswith("en"):
            return path
    return sorted(found)[0]


def _from_skill_json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    examples = data.get("examples")
    examples = [str(e) for e in examples if isinstance(e, (str, int, float))][:12] \
        if isinstance(examples, list) else []
    icon = data.get("icon")
    author = data.get("author")
    return {
        # who the skill says made it: an organisation, where the package
        # metadata often names only the person who uploaded it
        "skill_author": author.strip()[:80] or None if isinstance(author, str) else None,
        "title": str(data.get("name") or "").strip() or None,
        "description": str(data.get("description") or "").strip() or None,
        "examples": examples,
        "icon_url": icon if isinstance(icon, str) and icon.startswith("https://") else None,
    }


def _device_lang() -> str:
    try:
        from ovos_webui import configio
        return configio.read_merged_config().get("lang") or "en-us"
    except Exception:  # noqa: BLE001 - fall back to English
        return "en-us"


# ── package metadata ─────────────────────────────────────────────────────────
def _person(name: str | None, email: str | None) -> str | None:
    name = (name or "").strip()
    if name:
        return name
    # "Jane Doe <jane@example.org>" -> "Jane Doe"; a bare address stays out
    match = re.match(r'\s*"?([^"<,]+?)"?\s*<', email or "")
    return match.group(1).strip() if match else None


def _links(urls: dict[str, str], home: str | None) -> dict[str, str | None]:
    lower = {k.lower(): v for k, v in (urls or {}).items() if isinstance(v, str)}
    candidates = [lower.get(k) for k in ("source", "source code", "repository", "code", "github",
                                         "homepage", "home")] + [home] + list(lower.values())
    source = next((u for u in candidates if u and u.startswith("https://")
                   and urllib.parse.urlparse(u).netloc.endswith(("github.com", "gitlab.com",
                                                                 "codeberg.org"))), None)
    homepage = next((u for u in [lower.get("homepage"), home] if u and u.startswith("https://")), None)
    return {"source": source, "homepage": homepage if homepage != source else None}


def _installed(package: str) -> metadata.Distribution | None:
    try:
        return metadata.distribution(package)
    except metadata.PackageNotFoundError:
        return None


def _local_info(dist: metadata.Distribution, lang: str) -> dict[str, Any]:
    meta = dist.metadata
    urls = {}
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls[label.strip()] = url.strip()
    out = {
        "installed": True,
        "version": dist.version,
        "author": _person(meta.get("Author") or meta.get("Maintainer"),
                          meta.get("Author-email") or meta.get("Maintainer-email")),
        "license": (meta.get("License") or "").strip()[:80] or None,
        "summary": (meta.get("Summary") or "").strip() or None,
        "released": None,
        "is_ovos_skill": installed_is_ovos_skill(dist),
    }
    out.update(_links(urls, meta.get("Home-page")))
    files = [str(f) for f in (dist.files or [])]
    chosen = pick_skill_json(files, lang)
    raw = None
    if chosen:
        try:
            raw = Path(dist.locate_file(chosen)).read_bytes()
        except OSError:
            pass
    if raw is None:
        raw = _skill_json_beside_code(dist, lang)
    if raw is not None:
        out.update(_from_skill_json(raw))
    return out


def _skill_json_beside_code(dist: metadata.Distribution, lang: str) -> bytes | None:
    """The skill.json next to the skill's code, for an install whose file list
    does not name it: an editable install (pip install -e) lists only its
    hook. The code is found as Python would find it, without importing it."""
    import importlib.util

    tops = {ep.value.split(":")[0].split(".")[0] for ep in dist.entry_points
            if ep.group in SKILL_GROUPS}
    for top in sorted(t for t in tops if t.isidentifier()):
        try:
            spec = importlib.util.find_spec(top)
        except (ImportError, ValueError):
            continue
        for folder in (spec.submodule_search_locations or []) if spec else []:
            locale = Path(folder) / "locale"
            if not locale.is_dir():
                continue
            paths = [f"locale/{d.name}/skill.json" for d in locale.iterdir()
                     if (d / "skill.json").is_file()]
            chosen = pick_skill_json(paths, lang)
            if chosen:
                try:
                    return (Path(folder) / chosen).read_bytes()
                except OSError:
                    return None
    return None


def _cache_dir() -> Path:
    from ovos_webui import pypi
    return pypi.cache_path().parent / "ovos-webui-skills"


def _get(url: str, limit: int) -> bytes:
    from ovos_webui import pypi
    with pypi._open(url) as response:  # noqa: SLF001 - one opener for all PyPI reads
        data = response.read(limit + 1)
    if len(data) > limit:
        raise OSError("the file is larger than expected")
    return data


def _wheel_skill_json(files: list[dict[str, Any]], lang: str) -> tuple[dict[str, Any], bool | None]:
    """Download (or reuse) the wheel and read skill.json and the entry point."""
    wheel = next((f for f in files if str(f.get("filename", "")).endswith(".whl")
                  and str(f.get("url", "")).startswith("https://")), None)
    if wheel is None or (wheel.get("size") or 0) > MAX_WHEEL_BYTES:
        return {}, None
    name = re.sub(r"[^A-Za-z0-9._-]", "_", wheel["filename"])
    path = _cache_dir() / "wheels" / name
    if not path.is_file():
        data = _get(wheel["url"], MAX_WHEEL_BYTES)
        digest = (wheel.get("digests") or {}).get("sha256")
        if digest and hashlib.sha256(data).hexdigest() != digest:
            raise OSError("the wheel does not match its checksum")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as zf:
        names = zf.namelist()
        info: dict[str, Any] = {}
        chosen = pick_skill_json(names, lang)
        if chosen:
            info = _from_skill_json(zf.read(chosen))
        entry = next((n for n in names if n.endswith(".dist-info/entry_points.txt")), None)
        registers = bool(entry and _GROUP_RE.search(zf.read(entry)))
    return info, registers


def _remote_info(package: str, lang: str) -> dict[str, Any]:
    from ovos_webui import pypi
    project = json.loads(_get(pypi._project_json_url(package), 4 * 1024 * 1024))  # noqa: SLF001
    info = project.get("info") or {}
    files = project.get("urls") or []
    released = next((f.get("upload_time_iso_8601") for f in files if f.get("upload_time_iso_8601")), None)
    out = {
        "installed": False,
        "version": info.get("version"),
        "author": _person(info.get("author") or info.get("maintainer"),
                          info.get("author_email") or info.get("maintainer_email")),
        "license": (info.get("license") or "").strip()[:80] or None,
        "summary": (info.get("summary") or "").strip() or None,
        "released": released,
        "is_ovos_skill": is_ovos_skill_listing(project),
    }
    out.update(_links(info.get("project_urls") or {}, info.get("home_page")))
    try:
        from_wheel, registers = _wheel_skill_json(files, lang)
        out.update(from_wheel)
        if registers:
            out["is_ovos_skill"] = True
    except (OSError, zipfile.BadZipFile, urllib.error.URLError, TimeoutError) as err:
        LOG.info(f"could not read the skill.json of {package}: {err}")
    return out


#: What PyPI said about a package that is not installed, kept for a while so
#: opening a skill and then fetching its icon reads PyPI once.
_REMOTE: dict[str, tuple[float, dict[str, Any]]] = {}
REMOTE_TTL = 60 * 60


def _checked_name(package: str, plugins: bool = False) -> str:
    """A safe package name from the OVOS families; a skill unless ``plugins``."""
    from ovos_webui.installer import UnsafePackageName, validate_package_name
    from ovos_webui.pypi import classify

    try:
        package = validate_package_name(package)
    except UnsafePackageName as err:
        raise NotASkill(str(err)) from err
    kind = classify(package)
    if kind is None or (kind != "skill" and not plugins):
        raise NotASkill("that is not a skill package")
    return package


def _gather(package: str) -> dict[str, Any]:
    import time

    lang = _device_lang()
    out: dict[str, Any] = {"package": package, "lang": lang, "examples": [],
                           "title": None, "description": None, "icon_url": None}
    dist = _installed(package)
    if dist is not None:
        out.update(_local_info(dist, lang))
    else:
        key = package.lower() + "|" + lang
        cached = _REMOTE.get(key)
        if cached and time.time() - cached[0] < REMOTE_TTL:
            out.update(cached[1])
        else:
            found = _remote_info(package, lang)
            _REMOTE[key] = (time.time(), found)
            out.update(found)
    out["pypi"] = "https://pypi.org/project/" + urllib.parse.quote(package) + "/"
    # the skill's own skill.json says who made it, before the package metadata
    skill_author = out.pop("skill_author", None)
    if skill_author:
        out["author"] = skill_author
    return out


def info(package: str, plugins: bool = False) -> dict[str, Any]:
    """Return what is known about one skill package, installed or not.

    With ``plugins`` any package from the OVOS plugin families is looked up the
    same way; a plugin has no skill.json, so it gets the package metadata.
    """
    out = _gather(_checked_name(package, plugins))
    out["has_icon"] = _icon_allowed(out.pop("icon_url", None))
    return out


# ── icons ────────────────────────────────────────────────────────────────────
def _icon_allowed(url: str | None) -> bool:
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ICON_HOSTS


def _sniff(data: bytes) -> str | None:
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def icon(package: str) -> tuple[bytes, str] | None:
    """Return ``(bytes, media type)`` of a skill's icon, or None if it has none
    the panel will show. Fetched once and kept in the cache."""
    try:
        package = _checked_name(package)
        url = _gather(package).get("icon_url")
    except (NotASkill, OSError, ValueError, urllib.error.URLError, TimeoutError):
        return None
    if not _icon_allowed(url):
        return None
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    path = _cache_dir() / "icons" / key
    with _LOCK:
        if path.is_file():
            data = path.read_bytes()
        else:
            try:
                data = _get(url, MAX_ICON_BYTES)
            except (OSError, urllib.error.URLError, TimeoutError) as err:
                LOG.info(f"could not fetch the icon of {package}: {err}")
                return None
            if _sniff(data) is None:
                return None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    kind = _sniff(data)
    return (data, kind) if kind else None
