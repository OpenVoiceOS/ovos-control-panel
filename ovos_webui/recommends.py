"""Read the per-language plugin recommendations that ovos-config ships.

``ovos-config`` keeps a registry at ``ovos_config/recommends/<profile>/<lang>.conf``.
Each file is a JSON config fragment. ``ovos_config/__main__.py`` merges them in
this order to build a first configuration: ``base``, then ``platform/<name>``,
then an STT profile, then a TTS profile, then ``gpu``.

This module only reads them. It never merges them into the live configuration:
the Settings page does that, one field at a time, when a user asks for it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ovos_utils.log import LOG

#: A language code, e.g. ``pt`` or ``pt-pt``. Anything else is refused before
#: it can be joined into a path: ``lang`` is used to build ``<lang>.conf``, so
#: a value with a separator or ``..`` would otherwise walk out of the registry.
LANG_RE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$")

#: The profiles the registry ships, in the order ovos-config merges them.
PROFILE_ORDER = ["base", "platform", "offline_stt", "online_stt",
                 "offline_male", "offline_female", "online_male", "online_female", "gpu"]


def registry_root() -> Path | None:
    """Return the recommends directory inside the installed ovos-config."""
    try:
        import ovos_config
        root = Path(ovos_config.__file__).parent / "recommends"
    except Exception as err:  # noqa: BLE001
        LOG.warning(f"could not find the ovos-config recommends registry: {err}")
        return None
    return root if root.is_dir() else None


def profiles() -> list[str]:
    """Return the profiles the installed ovos-config has."""
    root = registry_root()
    if root is None:
        return []
    found = sorted(p.name for p in root.iterdir() if p.is_dir())
    return sorted(found, key=lambda p: (PROFILE_ORDER.index(p)
                                        if p in PROFILE_ORDER else 99, p))


def languages(profile: str = "base") -> list[str]:
    """Return the languages a profile has a file for."""
    root = registry_root()
    if root is None or not _safe_profile(profile):
        return []
    directory = root / profile
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.conf"))


def _safe_profile(profile: str) -> bool:
    """A profile is a plain directory name from the registry itself."""
    return isinstance(profile, str) and profile in set(profiles())


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        LOG.warning(f"could not read {path}: {err}")
        return {}


def for_language(lang: str) -> dict[str, Any]:
    """Return every recommendation the registry holds for ``lang``.

    ovos-config falls back from ``pt-pt`` to any file that starts with ``pt``,
    so the same fallback is used here.
    """
    root = registry_root()
    if root is None:
        return {"available": False, "profiles": {}}
    lang = (lang or "").lower()
    if not LANG_RE.match(lang):
        # Not a language code. Refuse it rather than build a path from it.
        return {"available": True, "lang": lang, "profiles": {}}
    short = lang.split("-")[0]
    out: dict[str, Any] = {}
    for profile in profiles():
        directory = root / profile
        if not directory.is_dir():
            continue
        path = directory / f"{lang}.conf"
        if not path.is_file():
            matches = sorted(p for p in directory.glob(f"{short}*.conf"))
            if not matches:
                continue
            path = matches[0]
        data = _read(path)
        if data:
            out[profile] = {"lang": path.stem, "config": data,
                            "plugins": _plugins_in(data)}
    return {"available": True, "lang": lang, "profiles": out}


def _plugins_in(data: dict[str, Any]) -> list[dict[str, str]]:
    """Return the plugin names a recommendation fragment names."""
    found: list[dict[str, str]] = []

    def walk(node: Any, section: str) -> None:
        if not isinstance(node, dict):
            return
        module = node.get("module")
        if isinstance(module, str) and module:
            found.append({"section": section, "module": module})
        for key, value in node.items():
            if isinstance(value, dict):
                walk(value, f"{section}.{key}" if section else key)

    walk(data, "")
    seen = set()
    unique = []
    for entry in found:
        if entry["module"] in seen:
            continue
        seen.add(entry["module"])
        unique.append(entry)
    return unique


def recommended_plugins(lang: str, data: dict | None = None) -> list[dict[str, str]]:
    """Return a flat list of the plugins recommended for ``lang``.

    ``data`` is an already-computed ``for_language(lang)`` result; pass it to
    avoid recomputing the profile scan when the caller also needs the profiles.
    """
    data = for_language(lang) if data is None else data
    if not data.get("available"):
        return []
    out: list[dict[str, str]] = []
    seen = set()
    for profile, block in (data.get("profiles") or {}).items():
        for entry in block.get("plugins") or []:
            key = (entry["module"], entry["section"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"module": entry["module"], "section": entry["section"],
                        "profile": profile})
    return out
