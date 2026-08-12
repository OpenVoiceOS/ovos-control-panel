"""Find OVOS plugins on PyPI, and say which ones are installed.

PyPI has no search API any more. The only complete list is the simple index,
and it is about 45 MB. This module streams that index, keeps only the names
that look like OVOS packages (a few hundred), and writes that small list to the
cache. A search then runs against the cache and needs no network at all.

Details of one package come from the per-project JSON API, which is small.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ovos_utils.log import LOG

#: Single-flight for the PyPI index fetch. A request never blocks on it and
#: never triggers a second concurrent download: if a fetch is already running,
#: or one finished within _INDEX_MIN_GAP, the caller is served the cache.
_INDEX_LOCK = threading.Lock()
_INDEX_MIN_GAP = 30
_INDEX_LAST = 0.0

SIMPLE_INDEX = "https://pypi.org/simple/"
PROJECT_JSON = "https://pypi.org/pypi/{name}/json"
USER_AGENT = "ovos-webui"

#: How long a cached index stays usable, in seconds.
CACHE_TTL = 24 * 60 * 60

#: Stop reading the index after this many bytes. The index is about 45 MB.
MAX_INDEX_BYTES = 120 * 1024 * 1024

#: Give up on the network after this many seconds.
NETWORK_TIMEOUT = 30

#: The families of OVOS packages, and the plugin kind each one holds. The
#: order matters: the first pattern that matches decides the kind.
FAMILIES: list[tuple[str, str]] = [
    (r"^ovos-tts-plugin-[a-z0-9-]+$", "tts"),
    (r"^ovos-stt-plugin-[a-z0-9-]+$", "stt"),
    (r"^ovos-ww-plugin-[a-z0-9-]+$", "wake_word"),
    (r"^ovos-vad-plugin-[a-z0-9-]+$", "vad"),
    # the modern intent stack: ovos-adapt-pipeline-plugin, ovos-padatious-
    # pipeline-plugin, ovos-ocp-pipeline-plugin, ovos-common-query-pipeline-
    # plugin, ovos-ollama-intent-pipeline-plugin, ...
    (r"^ovos-[a-z0-9-]+-pipeline-plugin$", "pipeline"),
    (r"^ovos-(phal|PHAL)-plugin-[a-z0-9-]+$", "phal"),
    (r"^ovos-audio-transformer-plugin-[a-z0-9-]+$", "audio_transformer"),
    (r"^ovos-dialog-transformer-plugin-[a-z0-9-]+$", "dialog_transformer"),
    (r"^ovos-utterance-transformer-plugin-[a-z0-9-]+$", "utterance_transformer"),
    (r"^ovos-solver-[a-z0-9-]+-plugin$", "solver"),
    (r"^ovos-solver-plugin-[a-z0-9-]+$", "solver"),
    # second convention: ovos-ddg-solver-plugin
    (r"^ovos-[a-z0-9-]+-solver-plugin$", "solver"),
    (r"^ovos-translate-plugin-[a-z0-9-]+$", "translate"),
    # second convention: ovos-google-translate-plugin, ovos-gguf-translate-plugin
    (r"^ovos-[a-z0-9-]+-translate-plugin$", "translate"),
    (r"^ovos-lang-detect-plugin-[a-z0-9-]+$", "lang_detect"),
    # second convention: ovos-lang-detector-classics-plugin, -fasttext-plugin
    (r"^ovos-lang-detector-[a-z0-9-]+-plugin$", "lang_detect"),
    (r"^ovos-persona-[a-z0-9-]+$", "persona"),
    (r"^ovos-media-plugin-[a-z0-9-]+$", "media"),
    (r"^ovos-gui-plugin-[a-z0-9-]+$", "gui"),
    (r"^ovos-skill-[a-z0-9-]+$", "skill"),
]

_COMPILED = [(re.compile(pattern, re.IGNORECASE), kind) for pattern, kind in FAMILIES]

#: Matches a name inside an anchor of the simple index.
_HREF = re.compile(rb">([^<>]+)</a>")


def classify(name: str) -> str | None:
    """Return the plugin kind of ``name``, or ``None`` when it is not one."""
    for pattern, kind in _COMPILED:
        # fullmatch, not match: in Python ``$`` also matches just before a
        # trailing newline, and ``match`` never anchors the end — so
        # ``pattern.match("ovos-skill-foo\n")`` would wrongly succeed. fullmatch
        # requires the whole string to be consumed, rejecting the trailing \n.
        if pattern.fullmatch(name):
            return kind
    return None


def cache_path() -> Path:
    """Return the file that holds the cached package list."""
    from ovos_config.locations import get_xdg_cache_save_path

    return Path(get_xdg_cache_save_path()) / "webui-pypi-index.json"


def read_cache() -> dict[str, Any] | None:
    """Return the cached index, or ``None`` when there is none."""
    path = cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "packages" not in data:
        return None
    return data


def cache_age(data: dict[str, Any] | None) -> float | None:
    """Return the age of ``data`` in seconds, or ``None``."""
    if not data or not data.get("fetched"):
        return None
    return max(0.0, time.time() - float(data["fetched"]))


def _open(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT)  # noqa: S310 - https only


def fetch_index() -> dict[str, Any]:
    """Stream the PyPI simple index and keep only the OVOS names.

    The index is read in chunks, so the whole 45 MB is never held in memory.
    """
    packages: dict[str, str] = {}
    read = 0
    tail = b""
    with _open(SIMPLE_INDEX) as response:
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            read += len(chunk)
            if read > MAX_INDEX_BYTES:
                raise OSError("the package index is larger than expected")
            buf = tail + chunk
            # Keep the last partial line for the next round.
            cut = buf.rfind(b"\n")
            if cut == -1:
                tail = buf
                continue
            tail = buf[cut + 1:]
            for match in _HREF.finditer(buf[:cut]):
                name = match.group(1).decode("utf-8", errors="replace").strip()
                kind = classify(name)
                if kind:
                    packages[name] = kind
    for match in _HREF.finditer(tail):
        name = match.group(1).decode("utf-8", errors="replace").strip()
        kind = classify(name)
        if kind:
            packages[name] = kind
    data = {"fetched": time.time(), "packages": packages}
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def index(refresh: bool = False) -> dict[str, Any]:
    """Return the package index, from the cache when it is fresh enough.

    A live fetch is single-flighted and rate-limited so a burst of
    ``refresh=true`` requests cannot each start a multi-megabyte PyPI download
    or park a request thread: if another fetch holds the lock, or one ran in
    the last _INDEX_MIN_GAP seconds, the caller falls back to the cache.
    """
    global _INDEX_LAST
    data = read_cache()
    age = cache_age(data)
    if not refresh and data is not None and age is not None and age < CACHE_TTL:
        return data
    # Do not block a request thread waiting for someone else's fetch, and do
    # not re-fetch if one just completed — serve the cache instead.
    if not _INDEX_LOCK.acquire(blocking=False):
        return _stale_or_empty(data, "a package-index update is already running")
    try:
        # Rate-limit every attempt, not just successful ones and not only when
        # a cache exists: stamp the time before fetching, so a failing or
        # cache-less device cannot be driven into back-to-back downloads.
        if time.time() - _INDEX_LAST < _INDEX_MIN_GAP:
            return _stale_or_empty(data, "the package index was updated moments ago")
        _INDEX_LAST = time.time()
        return fetch_index()
    except (urllib.error.URLError, OSError, TimeoutError) as err:
        LOG.warning(f"could not read the package index from PyPI: {err}")
        return _stale_or_empty(data, str(err))
    finally:
        _INDEX_LOCK.release()


def _stale_or_empty(data: dict[str, Any] | None, error: str) -> dict[str, Any]:
    """Return the cache marked stale, or an empty offline index."""
    if data is not None:
        data = dict(data)
        data["stale"] = True
        data["error"] = error
        return data
    return {"fetched": None, "packages": {}, "error": error, "offline": True}


#: A full ``distributions()`` walk of site-packages costs tens of ms and several
#: handlers call ``installed_versions()`` more than once per request. Cache it
#: briefly — the installed set only changes on an install, which prompts a
#: service restart anyway.
import threading as _threading

_INSTALLED_CACHE: dict[str, Any] = {"ts": 0.0, "val": None}
_INSTALLED_TTL = 15.0
_INSTALLED_LOCK = _threading.Lock()


def installed_versions() -> dict[str, str]:
    """Return the installed distribution names and versions, lowercased."""
    import time
    from importlib.metadata import distributions

    def _fresh(now: float) -> bool:
        cached = _INSTALLED_CACHE["val"]
        return cached is not None and now - _INSTALLED_CACHE["ts"] <= _INSTALLED_TTL

    now = time.monotonic()
    if _fresh(now):
        return _INSTALLED_CACHE["val"]

    # Serialise the fill so a burst of concurrent first-requests does not each
    # walk site-packages; the double-check inside the lock means only one thread
    # does the scan and the rest reuse its result.
    with _INSTALLED_LOCK:
        now = time.monotonic()
        if _fresh(now):
            return _INSTALLED_CACHE["val"]
        out: dict[str, str] = {}
        for dist in distributions():
            try:
                name = dist.metadata["Name"]
            except (KeyError, TypeError):  # pragma: no cover - broken metadata
                continue
            if name:
                out[name.lower().replace("_", "-")] = dist.version or "unknown"
        _INSTALLED_CACHE["val"] = out
        _INSTALLED_CACHE["ts"] = now
        return out


def search(query: str = "", kind: str = "", refresh: bool = False,
           limit: int = 200) -> dict[str, Any]:
    """Return the packages that match ``query`` and ``kind``.

    Installed packages are listed first, so a user sees what they already have
    before what they could add.
    """
    data = index(refresh=refresh)
    packages: dict[str, str] = data.get("packages") or {}
    have = installed_versions()

    # A package installed from git or from a local path may not be on PyPI.
    # It is still real, so add it to the list.
    merged = dict(packages)
    for name in have:
        found = classify(name)
        if found and name not in merged:
            merged[name] = found

    query = (query or "").strip().lower()
    results = []
    for name, found in merged.items():
        if kind and found != kind:
            continue
        if query and query not in name.lower():
            continue
        results.append({
            "name": name,
            "kind": found,
            "installed": name.lower() in have,
            "version": have.get(name.lower()),
        })
    results.sort(key=lambda r: (not r["installed"], r["name"]))
    return {
        "results": results[:limit],
        "total": len(results),
        "kinds": sorted({k for _, k in merged.items()}),
        "cache_age": cache_age(data),
        "stale": bool(data.get("stale")),
        "offline": bool(data.get("offline")),
        "error": data.get("error"),
    }


def details(name: str) -> dict[str, Any]:
    """Return the PyPI description of one package.

    Raises ``LookupError`` when PyPI does not know the name. The installer uses
    this as the check that a name is real before it installs anything.
    """
    from ovos_webui.installer import validate_package_name

    validate_package_name(name)
    url = PROJECT_JSON.format(name=urllib.parse.quote(name, safe=""))
    try:
        with _open(url) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise LookupError(f"PyPI does not have a package called {name}") from err
        raise
    info = body.get("info") or {}
    return {
        "name": info.get("name") or name,
        "version": info.get("version"),
        "summary": info.get("summary"),
        "home_page": info.get("home_page") or (info.get("project_urls") or {}).get("Homepage"),
        "license": info.get("license"),
        "requires_python": info.get("requires_python"),
        "kind": classify(name),
    }

