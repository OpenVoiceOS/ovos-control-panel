"""Read and write the user layer of ``mycroft.conf``.

OVOS merges several configuration files. The user layer is the last one and it
wins. This module only touches the user layer, through ``ovos_config``. It
never parses the merged configuration by hand.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from ovos_utils.log import LOG

from ovos_webui.fsutils import atomic_write


class ConfigError(ValueError):
    """Raised when supplied configuration text is not usable."""


def user_config_path() -> Path:
    """Return the path of the user configuration file.

    The file does not have to exist yet.
    """
    from ovos_config.models import MycroftUserConfig

    return Path(MycroftUserConfig().path)


def read_user_config() -> dict[str, Any]:
    """Return the user layer as a plain dict."""
    from ovos_config.models import MycroftUserConfig

    return dict(MycroftUserConfig())


def read_merged_config() -> dict[str, Any]:
    """Return the full merged configuration as a plain dict."""
    from ovos_config.config import read_mycroft_config

    return read_mycroft_config()


def parse_text(text: str, fmt: str) -> dict[str, Any]:
    """Parse ``text`` as JSON or YAML and check it is a mapping."""
    if fmt not in ("json", "yaml"):
        raise ConfigError(f"unknown format: {fmt}")
    try:
        if fmt == "json":
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as err:
        raise ConfigError(str(err)) from err
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("the configuration must be a mapping at the top level")
    return data


def dump_text(data: dict[str, Any], fmt: str) -> str:
    """Serialise ``data`` as JSON or YAML."""
    if fmt == "yaml":
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)


def write_user_config(data: dict[str, Any], bus=None) -> dict[str, Any]:
    """Replace the whole user layer with ``data``.

    ``update_mycroft_config`` only merges, so it cannot remove a key. To let a
    user delete a key from the user layer, this writes the file itself, with a
    backup, and then tells the running services to re-read it.
    """
    if not isinstance(data, dict):
        raise ConfigError("the configuration must be a mapping at the top level")
    path = user_config_path()
    backup = atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))
    _notify(data, bus)
    return {"path": str(path), "backup": str(backup) if backup else None}


def _notify(data: dict[str, Any], bus) -> None:
    """Tell running services that the configuration changed.

    ``configuration.patch`` is an existing OVOS message. ovos-config also
    watches the file, so this only makes the update faster.

    ``MessageBusClient.emit`` waits for the connection without a limit when the
    bus is down, so a save would never answer. The connection is checked first,
    and a save works with or without the bus.
    """
    from ovos_webui.health import bus_reachable

    if bus is None or not bus_reachable(bus):
        return
    try:
        from ovos_bus_client.message import Message
    except ImportError:  # pragma: no cover - fallback for minimal installs
        from ovos_utils.fakebus import Message
    try:
        bus.emit(Message("configuration.patch", {"config": data}))
    except Exception as err:  # noqa: BLE001 # pragma: no cover - the bus may drop
        LOG.warning(f"could not announce the configuration change: {err}")


def plugin_options() -> dict[str, list[str]]:
    """Return the installed plugin names, grouped by kind.

    The names come from the entrypoints that ovos-plugin-manager reads, so the
    lists only hold plugins that are really installed on this device.
    """
    out: dict[str, list[str]] = {"tts": [], "stt": [], "wake_word": [], "vad": [], "gui": []}
    try:
        from ovos_plugin_manager.utils import PluginTypes, find_plugins
    except ImportError:  # pragma: no cover
        return out
    mapping = {
        "tts": PluginTypes.TTS,
        "stt": PluginTypes.STT,
        "wake_word": PluginTypes.WAKEWORD,
        "vad": PluginTypes.VAD,
        "gui": PluginTypes.GUI,
    }
    for key, ptype in mapping.items():
        try:
            out[key] = sorted(find_plugins(ptype) or {})
        except Exception as err:  # noqa: BLE001 - a broken plugin must not break the page
            LOG.warning(f"could not list {key} plugins: {err}")
            out[key] = []
    return out


#: The keys the simple form shows, with the configuration path of each one.
QUICK_KEYS = [
    {"path": ["lang"], "label": "Language", "kind": "text"},
    {"path": ["system_unit"], "label": "Units", "kind": "choice",
     "options": ["metric", "imperial"]},
    {"path": ["time_format"], "label": "Time format", "kind": "choice",
     "options": ["half", "full"]},
    {"path": ["date_format"], "label": "Date format", "kind": "choice",
     "options": ["DMY", "MDY"]},
    {"path": ["tts", "module"], "label": "Voice (TTS plugin)", "kind": "plugin",
     "plugins": "tts"},
    {"path": ["stt", "module"], "label": "Speech to text plugin", "kind": "plugin",
     "plugins": "stt"},
    {"path": ["listener", "wake_word"], "label": "Wake word", "kind": "hotword"},
    {"path": ["listener", "VAD", "module"], "label": "Voice activity plugin",
     "kind": "plugin", "plugins": "vad"},
]


def get_in(data: dict[str, Any], path: list[str]) -> Any:
    """Return the value at ``path`` in ``data``, or ``None``."""
    node: Any = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def set_in(data: dict[str, Any], path: list[str], value: Any) -> None:
    """Set ``value`` at ``path`` in ``data``, making parents as needed."""
    node = data
    for key in path[:-1]:
        nxt = node.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            node[key] = nxt
        node = nxt
    node[path[-1]] = value


def del_in(data: dict[str, Any], path: list[str]) -> None:
    """Remove the value at ``path`` in ``data`` if it is there."""
    node = data
    for key in path[:-1]:
        nxt = node.get(key)
        if not isinstance(nxt, dict):
            return
        node = nxt
    node.pop(path[-1], None)


def quick_form() -> list[dict[str, Any]]:
    """Return the simple form: one entry per key, with the current values."""
    user = read_user_config()
    merged = read_merged_config()
    plugins = plugin_options()
    fields = []
    for spec in QUICK_KEYS:
        field = dict(spec)
        field["name"] = ".".join(spec["path"])
        field["value"] = get_in(user, spec["path"])
        field["effective"] = get_in(merged, spec["path"])
        if spec["kind"] == "plugin":
            field["options"] = plugins.get(spec["plugins"], [])
        elif spec["kind"] == "hotword":
            # The wake words a device can use are the ones named in the
            # ``hotwords`` section. A free text box here would let a user type
            # a name that does not exist, and the device would stop listening.
            hotwords = merged.get("hotwords") or {}
            field["options"] = sorted(hotwords) if isinstance(hotwords, dict) else []
        fields.append(field)
    return fields


def apply_quick_form(values: dict[str, Any], bus=None) -> dict[str, Any]:
    """Write the simple form back into the user layer.

    An empty value removes the key from the user layer, so the default takes
    over again.
    """
    known = {".".join(spec["path"]): spec["path"] for spec in QUICK_KEYS}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ConfigError(f"unknown field(s): {', '.join(unknown)}")
    user = read_user_config()
    for name, path in known.items():
        if name not in values:
            continue
        value = values[name]
        if value is None or (isinstance(value, str) and not value.strip()):
            del_in(user, path)
        else:
            set_in(user, path, value)
    return write_user_config(user, bus=bus)
