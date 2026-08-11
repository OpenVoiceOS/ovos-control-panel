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


class NoAliasLoader(yaml.SafeLoader):
    """A YAML loader that refuses anchors and aliases.

    An alias can name the same node many times over, so a few hundred bytes of
    YAML can expand into gigabytes while it loads. This is the "billion laughs"
    attack. A configuration file has no need of aliases, so the loader simply
    refuses them and the expansion can never start.
    """


def _no_alias(loader, node):  # pragma: no cover - reached through compose_node
    raise ConfigError("YAML anchors and aliases are not allowed here")


def _compose_node(self, parent, index):
    if self.check_event(yaml.events.AliasEvent):
        raise ConfigError("YAML anchors and aliases are not allowed here")
    return yaml.composer.Composer.compose_node(self, parent, index)


NoAliasLoader.compose_node = _compose_node


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
            data = yaml.load(text, Loader=NoAliasLoader)
    except ConfigError:
        raise
    except (json.JSONDecodeError, yaml.YAMLError, RecursionError) as err:
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
    applied = _notify(data, bus)
    return {"path": str(path), "backup": str(backup) if backup else None,
            "applied": applied}


def mutate(change, bus=None) -> dict[str, Any]:
    """Read-modify-write the user layer atomically.

    ``read_user_config`` → mutate → ``write_user_config`` done as three separate
    steps is a lost-update race: two requests each read the same file, change a
    different key, and the second write wins, silently dropping the first change
    (e.g. two skills toggled at once, or a freshly-set access token reverted).
    ``atomic_write`` holds ``_WRITE_LOCK`` only for the write itself, not the
    read, so it does not prevent this.

    ``mutate`` takes the same reentrant lock around the whole read-modify-write,
    so concurrent callers serialise and never clobber each other. ``change`` is
    called with the current user-config dict; it may edit it in place, or return
    a replacement dict.
    """
    from ovos_webui.fsutils import _WRITE_LOCK

    with _WRITE_LOCK:
        data = read_user_config()
        replaced = change(data)
        if replaced is not None:
            data = replaced
        return write_user_config(data, bus=bus)


def _notify(data: dict[str, Any], bus) -> bool:
    """Tell running services that the configuration changed.

    Return ``True`` when the running services were told, ``False`` when the
    file was written but the bus could not be reached, so the caller can say
    the change is saved but not yet live. There is no bus when the UI runs
    without one; that is not a failure, so it reports ``True``.

    ``Configuration.patch`` keeps a volatile layer that sits on top of the
    files and is only ever added to, so a key removed from the file stays in
    that layer until a restart. ``configuration.patch.clear`` empties the
    layer. Sending the clear first and the new configuration second makes a
    deletion take effect at once.

    Both messages already exist in ovos-config: ``Configuration.register_bus``
    binds ``configuration.patch`` and ``configuration.patch.clear``. Nothing
    new is added to the bus here.

    Every send goes through the bounded wrapper, because an emit on a bus that
    dropped waits with no limit and would hang the request.
    """
    from ovos_webui import buswait

    if bus is None:
        return True  # no bus to tell; nothing was lost
    if not buswait.is_connected(bus):
        return False
    try:
        from ovos_bus_client.message import Message
    except ImportError:  # pragma: no cover - fallback for minimal installs
        from ovos_utils.fakebus import Message
    if not buswait.emit(bus, Message("configuration.patch.clear", {})):
        LOG.warning("could not clear the volatile configuration patch")
        return False
    return buswait.emit(bus, Message("configuration.patch", {"config": data}))


def user_or_merged(path: list[str]) -> Any:
    """Return a key, preferring the user layer read fresh from disk.

    The merged view (``Configuration``) is a cached singleton that follows
    file changes with a delay. For keys this app itself writes, the user
    layer on disk is the truth of record — reading it first means a page
    never shows a stale value right after its own save.
    """
    value = get_in(read_user_config(), path)
    if value is not None:
        return value
    return get_in(read_merged_config(), path)


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
    specs = {".".join(spec["path"]): spec for spec in QUICK_KEYS}
    unknown = sorted(set(values) - set(specs))
    if unknown:
        raise ConfigError(f"unknown field(s): {', '.join(unknown)}")
    plugins = plugin_options()
    merged = read_merged_config()

    def change(user):
        for name, spec in specs.items():
            if name not in values:
                continue
            value = values[name]
            if value is None or (isinstance(value, str) and not value.strip()):
                del_in(user, spec["path"])
                continue
            set_in(user, spec["path"],
                   _check_quick_value(name, spec, value, plugins, merged))

    return mutate(change, bus=bus)


def _check_quick_value(name: str, spec: dict[str, Any], value: Any,
                       plugins: dict[str, list[str]],
                       merged: dict[str, Any]) -> str:
    """Return ``value`` when it fits the field, else raise.

    Every field of the simple form holds a short string. A boolean or a number
    reaching the configuration would make a service fail later, far away from
    the page that wrote it, so it is refused here.
    """
    if not isinstance(value, str):
        raise ConfigError(f"'{name}' must be text, not {type(value).__name__}")
    value = value.strip()
    if len(value) > 128:
        raise ConfigError(f"'{name}' is too long")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ConfigError(f"'{name}' must be a single line")
    kind = spec["kind"]
    if kind == "choice":
        if value not in spec["options"]:
            raise ConfigError(
                f"'{name}' must be one of: {', '.join(spec['options'])}")
    elif kind == "plugin":
        allowed = plugins.get(spec["plugins"]) or []
        if allowed and value not in allowed:
            raise ConfigError(
                f"'{name}' must be an installed plugin: {', '.join(allowed)}")
    elif kind == "hotword":
        hotwords = merged.get("hotwords") or {}
        if isinstance(hotwords, dict) and hotwords and value not in hotwords:
            raise ConfigError(
                f"'{name}' must be a wake word named in the hotwords section: "
                f"{', '.join(sorted(hotwords))}")
    elif kind == "text" and name == "lang":
        import re
        if not re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$", value):
            raise ConfigError("'lang' must be a language code, for example pt-pt")
    return value
