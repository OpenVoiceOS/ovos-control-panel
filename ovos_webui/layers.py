"""Which configuration layer a setting actually came from.

OVOS merges its configuration from a stack of files. The panel could already
show what a key resolves to, and the Settings page writes to the user file --
but "I changed it and nothing happened" is the commonest configuration report
there is, and the answer is almost never that the change was not saved. It is
that a later layer sets the same key and wins.

The order is ``ovos_config.config.Configuration.load_all_configs``: the
packaged defaults, the remote cache, the distribution file, the system file,
then the XDG files, then runtime patches from skills and bus events. Each
overrides the one before, so the last layer that mentions a key is the one a
reader has to edit.

Read-only. Nothing here writes configuration.
"""
from __future__ import annotations

from typing import Any

#: The layers in merge order, each with the attribute on ``Configuration``
#: that holds it. ``xdg`` is a list rather than a single file, and ``patch``
#: is held privately because nothing outside the library is meant to write it.
_LAYERS: list[tuple[str, str]] = [
    ("default", "default"),
    ("remote", "remote"),
    ("distribution", "distribution"),
    ("system", "system"),
    ("xdg", "xdg_configs"),
    ("patch", "_Configuration__patch"),
]


def _as_dict(layer: Any) -> dict[str, Any]:
    try:
        return dict(layer)
    except Exception:  # noqa: BLE001 - an unreadable layer is an empty one
        return {}


def _constraints() -> dict[str, Any]:
    from ovos_config.config import Configuration

    try:
        return Configuration.get_system_constraints() or {}
    except Exception:  # noqa: BLE001 - an unreadable policy constrains nothing
        return {}


def _without(data: dict[str, Any], protections: list[Any]) -> dict[str, Any]:
    """``data`` with each protected key removed.

    The nested separator is ``:``, which is what ``flattened_delete`` uses --
    not the ``.`` this module addresses keys by. Copied rather than deleted in
    place: ``filter_and_merge`` mutates the real layer objects, and stripping
    a key here must not strip it from the device.
    """
    from copy import deepcopy

    out = deepcopy(data)
    for protection in protections:
        if not isinstance(protection, str):
            continue
        parts = protection.split(":")
        target: Any = out
        for part in parts[:-1]:
            if not isinstance(target, dict) or part not in target:
                target = None
                break
            target = target[part]
        if isinstance(target, dict):
            target.pop(parts[-1], None)
    return out


def stack() -> list[dict[str, Any]]:
    """Every configuration layer, in the order they merge.

    A layer that does not exist on this machine is still listed: knowing that
    the system file is absent is part of the answer to where a value came
    from. So is a layer the device is configured to ignore -- those are
    marked ``dropped``, because "your user file is disabled by system policy"
    is the best possible answer to the question this page asks.

    The rules are ``Configuration.filter_and_merge``'s, applied to copies:
    ``disable_user_config`` drops every layer that is not the packaged
    defaults or the system file -- the distribution file and runtime patches
    included -- and ``protected_keys`` removes named keys from the remote or
    the user layers.
    """
    from ovos_config.config import Configuration

    policy = _constraints()
    protected = policy.get("protected_keys") or {}
    skip_user = bool(policy.get("disable_user_config"))
    skip_remote = bool(policy.get("disable_remote_config"))

    default_path = getattr(Configuration.default, "path", None)
    system_path = getattr(Configuration.system, "path", None)
    remote_path = getattr(Configuration.remote, "path", None)

    found: list[dict[str, Any]] = []
    for name, attribute in _LAYERS:
        layer = getattr(Configuration, attribute, None)
        if layer is None:
            continue
        parts = layer if name == "xdg" else [layer]
        for part in parts:
            path = getattr(part, "path", None)
            data = _as_dict(part)
            is_user = path is None or path not in (default_path, system_path)
            is_remote = path is not None and path == remote_path
            dropped = (is_remote and skip_remote) or (is_user and skip_user)
            if not dropped and is_remote:
                data = _without(data, protected.get("remote") or [])
            elif not dropped and is_user:
                data = _without(data, protected.get("user") or [])
            found.append({
                "name": name,
                "path": str(path) if path else None,
                "exists": bool(path and _exists(path)) or (not path and bool(data)),
                "dropped": dropped,
                "data": {} if dropped else data,
            })
    return found


def _exists(path: Any) -> bool:
    from pathlib import Path

    try:
        return Path(path).is_file()
    except OSError:
        return False


#: What a layer does to a key: it sets it, it says nothing about it, or it
#: replaces one of its parents with something that is not a dict -- which
#: removes the key from the merge as surely as deleting it would.
SET, SILENT, CLEARED = "set", "silent", "cleared"


def _dig(data: dict[str, Any], key: str) -> tuple[str, Any]:
    """Follow a dotted key through one layer.

    A layer that sets `tts` to a string has not left `tts.module` alone: after
    the merge there is no `tts.module` at all. Reporting an older layer's
    value for it would name a value the device does not have, which is the one
    failure this page exists to remove.
    """
    current: Any = data
    parts = key.split(".")
    for part in parts:
        if not isinstance(current, dict):
            return CLEARED, None
        if part not in current:
            return SILENT, None
        current = current[part]
    return SET, current


def resolve(key: str, stack: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Where ``key`` gets its value, and which layers were overruled.

    ``overridden`` is the interesting half: those are the files someone may
    have edited, in the belief that editing them would change something.

    A key whose value is a dict is not overridden by a later layer, it is
    merged with it -- ``merge_dict`` recurses -- so for those the value is the
    union down the stack and every layer that contributes is named as a
    contributor rather than as a loser. Reporting the last layer's copy as the
    value would state a fact the device does not agree with.
    """
    from ovos_utils.json_helper import merge_dict

    from copy import deepcopy

    layers = [layer for layer in (globals()["stack"]() if stack is None else stack)
              if not layer.get("dropped")]
    winner: dict[str, Any] | None = None
    value: Any = None
    contributors: list[dict[str, Any]] = []
    overridden: list[dict[str, Any]] = []

    for layer in layers:
        state, found = _dig(layer.get("data") or {}, key)
        # Copied once, here, and never referenced again: `merge_dict` assigns
        # sub-dicts by reference and recurses into them, so a value carried
        # forward from one layer is written through by the next. Answering a
        # question about the configuration must not change it, and the
        # read-only guard on a config layer does not reach inside a nested
        # plain dict.
        found = deepcopy(found)
        if state is SILENT:
            continue
        if state is CLEARED:
            # A parent of this key stopped being a dict here, so everything
            # under it is gone from the merge.
            if winner is not None:
                overridden.append({"name": winner["name"], "path": winner["path"],
                                   "value": value})
            winner, value = None, None
            continue
        if isinstance(found, dict) and isinstance(value, dict):
            contributors.append({"name": winner["name"], "path": winner["path"]})
            merged: dict[str, Any] = {}
            merge_dict(merged, value)
            merge_dict(merged, found)
            winner, value = layer, merged
            continue
        if winner is not None:
            overridden.append({"name": winner["name"], "path": winner["path"],
                               "value": value})
        winner, value = layer, found

    return {
        "key": key,
        "set": winner is not None,
        "value": value,
        "winner": winner["name"] if winner else None,
        "winner_path": winner["path"] if winner else None,
        "merged_from": contributors,
        "overridden": overridden,
    }
