"""Check installed OVOS packages against PyPI and surface conflicts.

Three concerns live here, all read-only towards the system:

* :func:`check_updates` compares every installed ``ovos-*`` distribution with
  the newest release on PyPI and reports which ones are behind.
* :func:`release_channel` / :func:`set_release_channel` read and write the
  ``webui.release_channel`` key of the user configuration. ``stable`` follows
  released versions; ``alpha`` also follows pre-releases (OVOS publishes an
  alpha for every merge, so this is the "get fixes now" channel).
* :func:`dependency_conflicts` runs ``pip check`` — an argument vector with no
  user input in it at all — and returns what pip reports.

The PyPI answers are cached on disk so the Plugins page stays fast and a
broken network never blocks the UI.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
from typing import Any

from ovos_utils.log import LOG

CHANNELS = ("stable", "alpha")

#: How long a fetched latest-version answer stays fresh, in seconds.
CACHE_TTL = 6 * 3600

#: pip check is quick; anything longer than this means something is wrong.
PIP_CHECK_TIMEOUT = 60

#: How long a pip-check result is reused, so a caller cannot make the device
#: spawn a process per request.
CONFLICTS_TTL = 30

#: One lock per expensive operation, so concurrent requests share one run
#: instead of each starting its own subprocess or PyPI sweep.
_CHECK_LOCK = threading.Lock()
_CONFLICTS_LOCK = threading.Lock()
_CONFLICTS_CACHE: dict[str, Any] = {}
_MAX_PROJECT_JSON = 4 * 1024 * 1024

#: The shortest gap between two real PyPI sweeps. A burst of refresh=true
#: requests collapses to one sweep; the rest read the cache the first filled.
_MIN_SWEEP_GAP = 20
_LAST_SWEEP = 0.0

_PRE = re.compile(r"(a|b|rc|dev)", re.IGNORECASE)


def _cache_path():
    from ovos_webui.pypi import cache_path

    return cache_path().parent / "ovos-webui-latest.json"


def _read_cache() -> dict[str, Any]:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_cache(data: dict[str, Any]) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError as err:  # pragma: no cover - disk trouble
        LOG.warning(f"could not write the update cache: {err}")


def _version_key(version: str):
    """Order versions well enough to pick the newest.

    Uses ``packaging`` when it is available and falls back to a numeric split.
    """
    try:
        from packaging.version import InvalidVersion, Version

        try:
            return Version(version)
        except InvalidVersion:
            return Version("0")
    except ImportError:  # pragma: no cover - packaging ships with pip
        return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.+-]", version))


def latest_versions(name: str) -> dict[str, str | None]:
    """Return the newest stable and newest overall release of ``name``."""
    from ovos_webui.installer import validate_package_name
    from ovos_webui.pypi import PROJECT_JSON, _open

    validate_package_name(name)
    url = PROJECT_JSON.format(name=urllib.parse.quote(name, safe=""))
    with _open(url) as response:
        raw = response.read(_MAX_PROJECT_JSON + 1)
    if len(raw) > _MAX_PROJECT_JSON:
        raise OSError("the PyPI response is larger than expected")
    body = json.loads(raw.decode("utf-8"))
    releases = [v for v, files in (body.get("releases") or {}).items() if files]
    if not releases:
        info_version = (body.get("info") or {}).get("version")
        return {"stable": info_version, "alpha": info_version}
    releases.sort(key=_version_key)
    stable = [v for v in releases if not _PRE.search(v)]
    return {"stable": stable[-1] if stable else None, "alpha": releases[-1]}


def check_updates(refresh: bool = False) -> dict[str, Any]:
    """Compare the installed OVOS packages with PyPI.

    Never raises for a single unreachable package — an unreachable PyPI just
    yields ``latest: null`` for the names that could not be checked.
    """
    from ovos_webui.pypi import classify, installed_versions

    # One sweep at a time, and no more often than _MIN_SWEEP_GAP: a burst of
    # refresh=true requests collapses to a single PyPI sweep, so this cannot be
    # turned into a request amplifier against PyPI or the device.
    global _LAST_SWEEP
    with _CHECK_LOCK:
        if refresh and time.time() - _LAST_SWEEP < _MIN_SWEEP_GAP:
            refresh = False
        result = _check_updates_locked(refresh, classify, installed_versions)
        if refresh:
            _LAST_SWEEP = time.time()
        return result


def _check_updates_locked(refresh, classify, installed_versions) -> dict[str, Any]:
    channel = release_channel()
    cache = _read_cache()
    now = time.time()
    packages = []
    offline = False
    dirty = False
    for name, installed in sorted(installed_versions().items()):
        if not classify(name):
            continue
        entry = cache.get(name) or {}
        if refresh or now - entry.get("fetched", 0) > CACHE_TTL:
            try:
                entry = {"fetched": now, **latest_versions(name)}
                cache[name] = entry
                dirty = True
            except (OSError, ValueError, urllib.error.URLError, LookupError):
                offline = True
        latest = entry.get(channel) or entry.get("stable")
        outdated = bool(
            latest and installed != "unknown"
            and _version_key(latest) > _version_key(installed))
        packages.append({"name": name, "installed": installed,
                         "latest": latest, "outdated": outdated})
    if dirty:
        _write_cache(cache)
    checked = max((cache.get(p["name"], {}).get("fetched", 0)
                   for p in packages), default=0) or None
    return {"channel": channel, "offline": offline, "packages": packages,
            "checked": checked,
            "outdated": sum(1 for p in packages if p["outdated"])}


def release_channel() -> str:
    """Return the configured release channel, ``stable`` by default."""
    from ovos_webui import configio

    value = configio.user_or_merged(["webui", "release_channel"])
    return value if value in CHANNELS else "stable"


def set_release_channel(channel: str, bus=None) -> dict[str, Any]:
    """Write the release channel into the user configuration layer."""
    from ovos_webui import configio

    if channel not in CHANNELS:
        raise ValueError(f"the channel must be one of {', '.join(CHANNELS)}")
    data = configio.read_user_config()
    configio.set_in(data, ["webui", "release_channel"], channel)
    result = configio.write_user_config(data, bus=bus)
    result["channel"] = channel
    return result


def dependency_conflicts() -> dict[str, Any]:
    """Run ``pip check`` and report what it prints.

    The argument vector is a constant — no request data reaches it — and there
    is no shell. pip exits non-zero when it finds a conflict, so the exit code
    is the signal, not an error.
    """
    now = time.time()
    with _CONFLICTS_LOCK:
        cached = _CONFLICTS_CACHE.get("result")
        if cached and now - _CONFLICTS_CACHE.get("at", 0) < CONFLICTS_TTL:
            return cached
        result = _run_pip_check()
        _CONFLICTS_CACHE.update({"result": result, "at": now})
        return result


def _run_pip_check() -> dict[str, Any]:
    argv = [sys.executable, "-m", "pip", "check", "--no-input",
            "--disable-pip-version-check"]
    try:
        proc = subprocess.run(  # noqa: S603 - constant argv, no shell
            argv, capture_output=True, text=True, shell=False,
            stdin=subprocess.DEVNULL, timeout=PIP_CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "conflicts": [],
                "error": f"pip check took longer than {PIP_CHECK_TIMEOUT} seconds"}
    if proc.returncode == 0:
        return {"ok": True, "conflicts": []}
    # pip prints conflicts on stdout; a broken environment (no pip at all)
    # complains on stderr instead. Report whichever it said.
    lines = [l.strip() for l in (proc.stdout or "").splitlines() if l.strip()]
    if not lines:
        lines = [l.strip() for l in (proc.stderr or "").splitlines() if l.strip()]
    if any("No module named pip" in l for l in lines):
        return {"ok": False, "conflicts": [],
                "error": "pip is not available in this environment, "
                         "so nothing could be checked"}
    return {"ok": False, "conflicts": lines}
