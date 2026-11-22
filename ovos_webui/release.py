"""The OVOS release the device follows: which packages it holds.

OpenVoiceOS publishes a release per channel in ovos-releases
(``constraints-stable.txt``, ``-testing``, ``-alpha``): every package that
belongs to it, with the versions that go together. The device's installer
installs against one of them (``skills.installer.constraints``, the stable
one when nothing is set), so that file is what "part of the release" means on
this device. The panel reads the same file. When OVOS moves a package into or
out of the release, the panel follows without a change of its own.

A constraints file set by hand to a local path is read from the device; any
other URL than https is not read.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any

from ovos_utils.log import LOG

#: The file a device follows when its installer names none, as ovos-core does
DEFAULT = ("https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/"
           "refs/heads/main/constraints-stable.txt")
_NAMED = re.compile(r"ovos-releases/(?:refs/heads/)?main/constraints-([a-z]+)\.txt$")
#: A line: a package name, and what may follow it (a version range)
_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;#]*)")
#: How long a read file is kept, and how long a failed read waits
TTL = 6 * 3600
RETRY = 10 * 60
MAX_BYTES = 2 * 1024 * 1024

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[str, str] | None, str | None]] = {}


def source() -> str:
    """The constraints file the device's installer uses."""
    from ovos_webui import configio
    found = configio.user_or_merged(["skills", "installer", "constraints"])
    return found.strip() if isinstance(found, str) and found.strip() else DEFAULT


def name_of(src: str) -> str | None:
    """``stable``, ``testing`` or ``alpha`` for one of OVOS's own files."""
    found = _NAMED.search(src)
    return found.group(1) if found else None


def parse(text: str) -> dict[str, str]:
    """Package name (as pip compares them) -> its version range."""
    from packaging.utils import canonicalize_name
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        found = _LINE.match(line)
        if found:
            out[canonicalize_name(found.group(1))] = found.group(3).strip()
    return out


def _read(src: str) -> str:
    if src.startswith("https://"):
        from ovos_webui.pypi import _open
        with _open(src) as response:
            data = response.read(MAX_BYTES + 1)
    elif "://" not in src:
        data = Path(src).expanduser().read_bytes()[:MAX_BYTES + 1]
    else:
        raise OSError("only an https URL or a file on the device is read")
    if len(data) > MAX_BYTES:
        raise OSError("the file is too large to be a constraints file")
    return data.decode("utf-8", "replace")


def packages(refresh: bool = False) -> dict[str, Any]:
    """The release the device follows: ``source``, ``name`` (stable, alpha …
    or None for a file of its own), ``packages`` (name -> range) and
    ``error`` when it could not be read; then ``packages`` is None and the
    panel says nothing about the release rather than something wrong."""
    src = source()
    now = time.time()
    with _LOCK:
        at, found, error = _CACHE.get(src, (0.0, None, None))
        fresh = (found is not None and now - at < TTL) or (found is None and error and now - at < RETRY)
        if refresh or not fresh:
            try:
                found, error = parse(_read(src)), None
            except (OSError, ValueError) as err:
                LOG.info(f"the release file {src} could not be read: {err}")
                error = str(err)
                # keep the last good list when a read fails
                found = _CACHE.get(src, (0.0, None, None))[1]
            _CACHE[src] = (now, found, error)
    return {"source": src, "name": name_of(src), "packages": found, "error": error}


def clear() -> None:
    """Forget what was read (tests, and a changed installer setting)."""
    with _LOCK:
        _CACHE.clear()
