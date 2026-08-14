"""Turn transformer plugins on and off, order them, and edit their config.

OVOS runs six chains of transformer plugins. Each chain has its own section in
``mycroft.conf`` and its own entry-point group of installed plugins:

===================== ========================= ===============================
config section        entry-point group         what the chain does
===================== ========================= ===============================
utterance_transformers ``opm.transformer.text``  change text before intent match
metadata_transformers  ``opm.transformer.metadata`` add data to a request
intent_transformers    ``opm.transformer.intent``   change a matched intent
audio_transformers     ``opm.transformer.audio``    act on captured audio
dialog_transformers    ``opm.transformer.dialog``   change a reply before speech
tts_transformers       ``opm.transformer.tts``      change audio after synthesis
===================== ========================= ===============================

The section names and the enable/disable/order rules are read straight from
``ovos_plugin_manager.transformer_services.TransformersService.load_plugins``:

- A plugin is **enabled** when its name is a key in the section. The two
  reserved keys ``order`` and ``blacklisted_skills`` are never plugin names.
- A plugin stays configured but **off** when its config block has
  ``"active": false``.
- The run **order** is an ``order`` list of plugin names in the section. Names
  in the list but absent as keys are still enabled (the loader unions them).

Every write goes through :func:`ovos_webui.configio.mutate`, so it shares the
one read-modify-write lock and the ``configuration.patch`` notification with
the rest of the app. No new bus message is added here.
"""
from __future__ import annotations

import importlib.metadata as _im
import re
from typing import Any

from ovos_utils.log import LOG

from ovos_webui import configio

#: The two plugins that together give bidirectional translation: talk to the
#: device in a secondary language and hear the answer back in it. Both ship in
#: ``ovos-bidirectional-translation-plugin``. The utterance side translates a
#: request into the device's own language; the dialog side translates the
#: reply back. The config keys below are read verbatim by the plugin
#: (``ovos_bidirectional_translation_plugin.UtteranceTranslator``).
BIDI_UTTERANCE = "ovos-utterance-translation-plugin"
BIDI_DIALOG = "ovos-dialog-translation-plugin"
BIDI_FLAGS = ("bidirectional", "verify_lang", "translate_secondary_langs",
              "ignore_invalid_langs")

_LANG_RE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$")

#: Keys a transformer section may hold that are not plugin names. The plugin
#: loader excludes exactly these when it works out which plugins are enabled
#: (``transformer_services.py``: ``set(config) - {"order", "blacklisted_skills"}``).
RESERVED_KEYS = ("order", "blacklisted_skills")

#: The six chains, in the order a request flows through the device. For each,
#: the config section name and the entry-point group(s) its plugins register
#: under. The first group is the one ``ovos_plugin_manager`` uses today; the
#: second, when present, is the deprecated ``neon.plugin.*`` group the manager
#: still honours (``ovos_plugin_manager.utils.DEPRECATED_ENTRYPOINTS``), so a
#: plugin that ships only the old name is still offered — and, just as
#: important, a group the manager does *not* read (``opm.utterance_transformer``,
#: ``opm.dialog_transformer``) is left out, so this page never offers a plugin
#: the device would not actually load.
CHAINS: dict[str, dict[str, Any]] = {
    "utterance_transformers": {"groups": ("opm.transformer.text", "neon.plugin.text")},
    "metadata_transformers": {"groups": ("opm.transformer.metadata", "neon.plugin.metadata")},
    "intent_transformers": {"groups": ("opm.transformer.intent",)},
    "audio_transformers": {"groups": ("opm.transformer.audio", "neon.plugin.audio")},
    "dialog_transformers": {"groups": ("opm.transformer.dialog",)},
    "tts_transformers": {"groups": ("opm.transformer.tts",)},
}

#: The longest a plugin name may be. A real entry-point name is short; this
#: only stops a hostile request from writing a huge key.
MAX_NAME_LENGTH = 128


class TransformerConfigError(ValueError):
    """Raised when a chain, plugin name, or config value is not usable."""


def _installed_for(groups: tuple[str, ...]) -> list[str]:
    """Return the names of every installed plugin in any of ``groups``.

    Reads real entry points, not a hardcoded list. Never raises: a broken
    distribution's metadata must not break the page, so a failure is logged
    and that group simply contributes nothing.
    """
    names: set[str] = set()
    for group in groups:
        try:
            for ep in _im.entry_points(group=group):
                names.add(ep.name)
        except Exception as err:  # noqa: BLE001 - a page must not die on this
            LOG.warning(f"could not read entry points for {group}: {err}")
    return sorted(names)


def _section(merged: dict[str, Any], chain: str) -> dict[str, Any]:
    value = configio.get_in(merged, [chain])
    return value if isinstance(value, dict) else {}


def _plugins_of(section: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The plugin entries of a section: every key that is not reserved."""
    out: dict[str, dict[str, Any]] = {}
    for name, block in section.items():
        if name in RESERVED_KEYS:
            continue
        out[name] = block if isinstance(block, dict) else {}
    return out


def _order_of(section: dict[str, Any]) -> list[str]:
    order = section.get("order")
    return [n for n in order if isinstance(n, str)] if isinstance(order, list) else []


def get_chains() -> dict[str, Any]:
    """Return, for every chain, its installed and configured plugins.

    Never raises: a chain whose data cannot be read still appears, empty, so
    the page loads. For each configured plugin it reports whether it is active
    (``active`` defaults to true, matching the loader) and its own config block.
    """
    merged = configio.read_merged_config()
    user = configio.read_user_config()
    chains: dict[str, Any] = {}
    for chain, spec in CHAINS.items():
        try:
            installed = _installed_for(spec["groups"])
        except Exception as err:  # noqa: BLE001
            LOG.warning(f"could not list plugins for {chain}: {err}")
            installed = []
        merged_section = _section(merged, chain)
        user_section = _section(user, chain)
        # The merged config comes from a cached singleton, so a section the user
        # just wrote may not be reflected in it yet. The user layer, read from
        # the file, is the fresh record of what the user set. Union the two,
        # letting the user layer win per plugin, so both the default plugins and
        # the user's own always show up regardless of the cache.
        user_plugins = _plugins_of(user_section)
        configured = {**_plugins_of(merged_section), **user_plugins}
        plugins = []
        for name in sorted(configured):
            block = configured[name]
            plugins.append({
                "name": name,
                "active": bool(block.get("active", True)),
                "config": block,
                "in_user_layer": name in user_plugins,
            })
        # Same union rule for the reserved keys: the user layer wins.
        order = _order_of(user_section) or _order_of(merged_section)
        blacklist = user_section.get("blacklisted_skills")
        if blacklist is None:
            blacklist = merged_section.get("blacklisted_skills")
        chains[chain] = {
            "installed": installed,
            "plugins": plugins,
            "order": order,
            "blacklisted_skills": blacklist if chain == "dialog_transformers" else None,
        }
    return {"chains": chains, "path": str(configio.user_config_path())}


def _check_chain(chain: str) -> dict[str, Any]:
    if chain not in CHAINS:
        raise TransformerConfigError(f"unknown transformer chain: {chain}")
    return CHAINS[chain]


def _check_name(name: Any) -> str:
    if not isinstance(name, str):
        raise TransformerConfigError("a plugin name must be text")
    name = name.strip()
    if not name:
        raise TransformerConfigError("a plugin name must not be empty")
    if name in RESERVED_KEYS:
        raise TransformerConfigError(f"'{name}' is a reserved key, not a plugin")
    if len(name) > MAX_NAME_LENGTH or "\n" in name or "\r" in name or "\x00" in name:
        raise TransformerConfigError("a plugin name must be a single short line")
    return name


def set_chain_state(chain: str, enabled: Any, order: Any = None, bus=None) -> dict[str, Any]:
    """Set which plugins in ``chain`` are on, and optionally their order.

    ``enabled`` is a mapping of plugin name to a bool: true keeps the plugin
    active, false keeps its config block but adds ``"active": false`` so the
    loader skips it. A plugin left out of ``enabled`` is removed from the user
    layer entirely. ``order``, when given, is the list of plugin names written
    to the section's ``order`` key; an empty list clears it.

    Any config block a plugin already has is kept. Never touches the reserved
    keys except ``order``. Never raises past validation.
    """
    _check_chain(chain)
    if not isinstance(enabled, dict):
        raise TransformerConfigError("'enabled' must be a map of plugin name to on/off")
    wanted: dict[str, bool] = {}
    for name, on in enabled.items():
        wanted[_check_name(name)] = bool(on)
    order_names: list[str] | None = None
    if order is not None:
        if not isinstance(order, list):
            raise TransformerConfigError("'order' must be a list of plugin names")
        order_names = [_check_name(n) for n in order]
        if len(set(order_names)) != len(order_names):
            raise TransformerConfigError("'order' must not repeat a plugin")

    def change(user: dict[str, Any]) -> None:
        section = configio.get_in(user, [chain])
        section = dict(section) if isinstance(section, dict) else {}
        merged_section = _section(configio.read_merged_config(), chain)
        for name, on in wanted.items():
            block = section.get(name)
            if not isinstance(block, dict):
                base = merged_section.get(name)
                block = dict(base) if isinstance(base, dict) else {}
            if on:
                block.pop("active", None)
            else:
                block["active"] = False
            section[name] = block
        # Drop plugins the caller did not mention (but never the reserved keys).
        for name in list(section):
            if name in RESERVED_KEYS:
                continue
            if name not in wanted:
                del section[name]
        if order_names is not None:
            if order_names:
                section["order"] = order_names
            else:
                section.pop("order", None)
        if section:
            configio.set_in(user, [chain], section)
        else:
            configio.del_in(user, [chain])

    return configio.mutate(change, bus=bus)


def set_plugin_config(chain: str, name: str, config: Any, bus=None) -> dict[str, Any]:
    """Replace one plugin's whole config block inside ``chain``.

    ``config`` is the block written under ``<chain>.<name>``. It must be a
    mapping. This is the generic editor a plugin without a dedicated helper
    card uses. The plugin's on/off state (``active``) is preserved unless the
    submitted block sets it. Never raises past validation.
    """
    _check_chain(chain)
    name = _check_name(name)
    if not isinstance(config, dict):
        raise TransformerConfigError("a plugin's config must be a mapping")
    for key in config:
        if not isinstance(key, str):
            raise TransformerConfigError("config keys must be text")

    def change(user: dict[str, Any]) -> None:
        section = configio.get_in(user, [chain])
        section = dict(section) if isinstance(section, dict) else {}
        block = dict(config)
        # Keep the current active state unless the new block states one.
        if "active" not in block:
            current = section.get(name)
            if isinstance(current, dict) and "active" in current:
                block["active"] = current["active"]
        section[name] = block
        configio.set_in(user, [chain], section)

    return configio.mutate(change, bus=bus)


def _bidi_flags_from(block: dict[str, Any]) -> dict[str, bool]:
    """Read the bidirectional flags from a plugin block, with plugin defaults.

    The defaults match ``UtteranceTranslator.__init__``: bidirectional on,
    everything else off.
    """
    defaults = {"bidirectional": True, "verify_lang": False,
                "translate_secondary_langs": False, "ignore_invalid_langs": False}
    return {k: bool(block.get(k, defaults[k])) for k in BIDI_FLAGS}


def get_bidirectional() -> dict[str, Any]:
    """Report whether bidirectional translation is on, and its settings.

    Enabled means both halves are present and active: the utterance plugin in
    ``utterance_transformers`` and the dialog plugin in ``dialog_transformers``.
    Never raises.
    """
    user = configio.read_user_config()
    merged = configio.read_merged_config()
    utt_section = _section(user, "utterance_transformers")
    dia_section = _section(user, "dialog_transformers")
    utt_block = utt_section.get(BIDI_UTTERANCE)
    utt_block = utt_block if isinstance(utt_block, dict) else None
    dia_block = dia_section.get(BIDI_DIALOG)
    dia_block = dia_block if isinstance(dia_block, dict) else None
    enabled = (utt_block is not None and utt_block.get("active", True)
               and dia_block is not None and dia_block.get("active", True))
    # secondary_langs and lang are user-first, then the merged default.
    secondary = user.get("secondary_langs")
    if not isinstance(secondary, list):
        secondary = merged.get("secondary_langs") if isinstance(
            merged.get("secondary_langs"), list) else []
    return {
        "enabled": bool(enabled),
        "flags": _bidi_flags_from(utt_block or {}),
        "lang": merged.get("lang") or user.get("lang"),
        "secondary_langs": [s for s in secondary if isinstance(s, str)],
        "installed": (BIDI_UTTERANCE in _installed_for(CHAINS["utterance_transformers"]["groups"])
                      and BIDI_DIALOG in _installed_for(CHAINS["dialog_transformers"]["groups"])),
    }


def _check_lang(value: Any) -> str:
    if not isinstance(value, str) or not _LANG_RE.match(value.strip()):
        raise TransformerConfigError(f"'{value}' is not a language code, for example pt-pt")
    return value.strip()


def set_bidirectional(enable: Any, secondary_langs: Any = None,
                      flags: Any = None, bus=None) -> dict[str, Any]:
    """Turn bidirectional translation on or off, in one write.

    When enabling, the utterance and dialog translation plugins are added to
    their chains, the given ``flags`` are written on the utterance plugin, and
    ``secondary_langs`` (the languages to translate to and from) is set. When
    disabling, both plugins are removed from their chains and
    ``secondary_langs`` is left untouched. Never raises past validation.
    """
    enable = bool(enable)
    checked_langs: list[str] | None = None
    if secondary_langs is not None:
        if not isinstance(secondary_langs, list):
            raise TransformerConfigError("'secondary_langs' must be a list of language codes")
        checked_langs = [_check_lang(x) for x in secondary_langs]
    checked_flags: dict[str, bool] = {}
    if flags is not None:
        if not isinstance(flags, dict):
            raise TransformerConfigError("'flags' must be a map")
        for key, value in flags.items():
            if key not in BIDI_FLAGS:
                raise TransformerConfigError(f"unknown flag: {key}")
            checked_flags[key] = bool(value)

    def change(user: dict[str, Any]) -> None:
        utt = configio.get_in(user, ["utterance_transformers"])
        utt = dict(utt) if isinstance(utt, dict) else {}
        dia = configio.get_in(user, ["dialog_transformers"])
        dia = dict(dia) if isinstance(dia, dict) else {}
        if enable:
            block = utt.get(BIDI_UTTERANCE)
            block = dict(block) if isinstance(block, dict) else {}
            block.pop("active", None)
            block.update(checked_flags)
            utt[BIDI_UTTERANCE] = block
            dblock = dia.get(BIDI_DIALOG)
            dia[BIDI_DIALOG] = dict(dblock) if isinstance(dblock, dict) else {}
            if checked_langs is not None:
                configio.set_in(user, ["secondary_langs"], checked_langs)
        else:
            utt.pop(BIDI_UTTERANCE, None)
            dia.pop(BIDI_DIALOG, None)
        for section_name, section in (("utterance_transformers", utt),
                                      ("dialog_transformers", dia)):
            if section:
                configio.set_in(user, [section_name], section)
            else:
                configio.del_in(user, [section_name])

    return configio.mutate(change, bus=bus)


#: The SoX voice-tuning transformer. Config key verified against the plugin's
#: pyproject (group ``opm.transformer.tts``). It applies SoX effects to the
#: synthesized audio, read from ``default_effects`` as {effect: {param: value}}.
SOX_PLUGIN = "ovos-tts-transformer-sox-plugin"

#: The SoX effects this page knows about (the plugin wraps pysox). Only these
#: names may be written, so a request cannot smuggle an arbitrary key into the
#: effect chain. The plugin itself validates the individual parameter values.
SOX_EFFECTS = frozenset({
    "pitch", "tempo", "speed", "reverb", "bass", "treble", "gain", "phaser",
    "flanger", "tremolo", "reverse", "chorus", "echo", "overdrive", "allpass",
    "bandpass", "bandreject", "compand", "contrast", "equalizer", "highpass",
    "lowpass", "bend", "stretch", "loudness", "noisered",
})


def get_sox() -> dict[str, Any]:
    """Report the SoX voice-tuning effects and whether the plugin is on.

    Never raises. ``effects`` is the current ``default_effects`` block.
    """
    user = configio.read_user_config()
    tts = _section(user, "tts_transformers")
    block = tts.get(SOX_PLUGIN)
    block = block if isinstance(block, dict) else {}
    effects = block.get("default_effects")
    effects = effects if isinstance(effects, dict) else {}
    return {
        "enabled": SOX_PLUGIN in tts and block.get("active", True) is not False,
        "effects": effects,
        "installed": SOX_PLUGIN in _installed_for(CHAINS["tts_transformers"]["groups"]),
    }


def _check_sox_effects(effects: Any) -> dict[str, dict[str, float]]:
    if not isinstance(effects, dict):
        raise TransformerConfigError("'effects' must be a map of effect name to settings")
    out: dict[str, dict[str, float]] = {}
    for name, params in effects.items():
        if name not in SOX_EFFECTS:
            raise TransformerConfigError(f"unknown SoX effect: {name}")
        if not isinstance(params, dict):
            raise TransformerConfigError(f"'{name}' settings must be a map")
        clean: dict[str, float] = {}
        for key, value in params.items():
            if not isinstance(key, str):
                raise TransformerConfigError("effect setting names must be text")
            # A bool is an int in Python, but never a valid effect amount.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TransformerConfigError(f"'{name}.{key}' must be a number")
            clean[key] = value
        out[name] = clean
    return out


def set_sox(enable: Any, effects: Any = None, bus=None) -> dict[str, Any]:
    """Turn the SoX voice-tuning plugin on or off and set its effects.

    When enabling, the plugin is added to the ``tts_transformers`` chain and its
    ``default_effects`` block is written. When disabling, only this plugin is
    removed; other speech transformers are left alone. Never raises past
    validation.
    """
    enable = bool(enable)
    checked = _check_sox_effects(effects) if effects is not None else None

    def change(user: dict[str, Any]) -> None:
        tts = configio.get_in(user, ["tts_transformers"])
        tts = dict(tts) if isinstance(tts, dict) else {}
        if enable:
            block = tts.get(SOX_PLUGIN)
            block = dict(block) if isinstance(block, dict) else {}
            block.pop("active", None)
            if checked is not None:
                block["default_effects"] = checked
            tts[SOX_PLUGIN] = block
        else:
            tts.pop(SOX_PLUGIN, None)
        if tts:
            configio.set_in(user, ["tts_transformers"], tts)
        else:
            configio.del_in(user, ["tts_transformers"])

    return configio.mutate(change, bus=bus)
