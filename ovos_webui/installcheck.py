"""What an install would change, before it runs.

Any package can pin old OVOS packages, whatever it is called, so the name says
nothing about whether an install is safe. pip can say exactly what it would do
without doing it: ``pip install --dry-run --report``. This module runs that
with the same arguments the device's installer uses (the constraints file,
``--pre`` and ``--upgrade`` from ``skills.installer`` in the configuration, as
ovos-core's ``SkillsStore.pip_install`` reads them) and reports which
installed packages would be downgraded or replaced, so the page can ask before
it goes ahead.

The installer itself runs on the device, in the environment of the service
that loads the plugin. The panel can only answer for its own environment, so
the check runs only when that is the assistant's environment too (the same
test the menu uses, :func:`ovos_webui.pages.colocated`). Otherwise it says it
could not check, and the install is asked for as before.

The argument vector holds only the validated package name and values read
from the device's own configuration. There is no shell.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from typing import Any

from ovos_utils.log import LOG

#: The constraints ovos-core uses when the configuration names none.
DEFAULT_CONSTRAINTS = ("https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/"
                       "refs/heads/main/constraints-stable.txt")
#: Give up on a dry run after this long; the install is then asked for as before.
CHECK_TIMEOUT = 240
#: Keep an answer this long, so asking twice does not resolve twice.
CHECK_TTL = 10 * 60

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _installer_config() -> dict[str, Any]:
    from ovos_webui import configio

    found = configio.read_merged_config().get("skills", {}).get("installer", {})
    return found if isinstance(found, dict) else {}


def pip_argv(package: str, config: dict[str, Any] | None = None) -> list[str]:
    """The dry-run command for ``package``, mirroring the device's installer."""
    config = _installer_config() if config is None else config
    argv = [sys.executable, "-m", "pip", "install", "--dry-run", "--quiet",
            "--report", "-", "--no-input", "--disable-pip-version-check"]
    constraints = config.get("constraints") or DEFAULT_CONSTRAINTS
    if isinstance(constraints, str) and constraints:
        argv += ["-c", constraints]
    if config.get("break_system_packages"):
        argv += ["--break-system-packages"]
    if config.get("allow_alphas"):
        argv += ["--pre"]
    if config.get("upgrade"):
        argv += ["--upgrade"]
    return argv + [package]


def _version_key(version: str):
    try:
        from packaging.version import Version
        return Version(version)
    except Exception:  # noqa: BLE001 - an odd version compares as text
        return version


def compare(report: dict[str, Any], installed: dict[str, str],
            package: str) -> dict[str, Any]:
    """Sort what pip would install into downgrades, upgrades and new packages."""
    downgrades, upgrades, added = [], [], []
    for item in report.get("install") or []:
        meta = item.get("metadata") or {}
        name = str(meta.get("name") or "")
        version = str(meta.get("version") or "")
        if not name or not version:
            continue
        have = installed.get(name.lower()) or installed.get(name.lower().replace("_", "-"))
        entry = {"name": name, "to": version}
        if have is None:
            if name.lower() != package.lower():
                added.append(entry)
            continue
        entry["from"] = have
        try:
            older = _version_key(version) < _version_key(have)
        except TypeError:
            older = False
        if older:
            downgrades.append(entry)
        elif version != have:
            upgrades.append(entry)
    return {"downgrades": downgrades, "upgrades": upgrades, "new": added}


def _run(package: str) -> dict[str, Any]:
    argv = pip_argv(package)
    try:
        proc = subprocess.run(  # noqa: S603 - validated name, no shell
            argv, capture_output=True, text=True, shell=False,
            stdin=subprocess.DEVNULL, timeout=CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"checked": False, "reason": "timeout"}
    except OSError as err:
        LOG.info(f"could not run pip to check {package}: {err}")
        return {"checked": False, "reason": "no-pip"}
    if proc.returncode != 0:
        lines = [ln for ln in (proc.stderr or "").splitlines() if ln.strip()]
        return {"checked": False, "reason": "pip-failed", "detail": "\n".join(lines[-12:])}
    try:
        report = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"checked": False, "reason": "no-report"}
    from ovos_webui.pypi import installed_versions

    out = compare(report, installed_versions(), package)
    out["checked"] = True
    return out


def check(package: str) -> dict[str, Any]:
    """Return what installing ``package`` would change here, or why it can't say."""
    from ovos_webui import pages
    from ovos_webui.installer import validate_package_name

    package = validate_package_name(package)
    if not pages.colocated():
        return {"package": package, "checked": False, "reason": "apart"}
    now = time.time()
    cached = _CACHE.get(package.lower())
    if cached and now - cached[0] < CHECK_TTL:
        return cached[1]
    if not _LOCK.acquire(timeout=CHECK_TIMEOUT):
        return {"package": package, "checked": False, "reason": "busy"}
    try:
        result = _run(package)
    finally:
        _LOCK.release()
    result["package"] = package
    if result.get("checked"):
        _CACHE[package.lower()] = (time.time(), result)
    return result


def forget() -> None:
    """Drop the kept answers; the installed set has changed."""
    _CACHE.clear()
