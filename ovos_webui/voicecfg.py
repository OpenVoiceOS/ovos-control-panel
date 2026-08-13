"""Friendly pickers for the voice settings that matter most.

The Advanced tab of the Settings page already lets a user edit the whole
``mycroft.conf`` user layer as raw text. This module gives the same handful of
keys a plain-language form: wake word, listening (VAD), speech-to-text (with a
fallback), text-to-speech (with a fallback), the pipeline stage order, the
utterance/metadata transformers, and the language.

Every write goes through :func:`ovos_webui.configio.mutate`, so it shares the
one read-modify-write lock and the same ``configuration.patch`` notification
as the rest of the app. No new bus message is added here.

The options offered for each picker come from the plugins really installed on
this device (:func:`ovos_webui.pypi.installed_versions` classified by
:func:`ovos_webui.pypi.classify`), never a hardcoded brand list. When nothing
of a given family is installed, the current value is still shown, with a hint
to visit the Plugins page.
"""
from __future__ import annotations

import re
from typing import Any

from ovos_utils.log import LOG

from ovos_webui import configio, pypi

#: The pipeline stages OVOS ships out of the box, in their default order. A
#: user's list is not limited to these — a plugin not on this list is still
#: kept and shown — but this seeds the picker with the names most devices use.
DEFAULT_PIPELINE = [
    "ovos-stop-pipeline-plugin-high",
    "ovos-converse-pipeline-plugin",
    "ovos-ocp-pipeline-plugin-high",
    "ovos-padatious-pipeline-plugin-high",
    "ovos-adapt-pipeline-plugin-high",
    "ovos-m2v-pipeline-high",
    "ovos-ocp-pipeline-plugin-medium",
    "ovos-fallback-pipeline-plugin-high",
    "ovos-stop-pipeline-plugin-medium",
    "ovos-adapt-pipeline-plugin-medium",
    "ovos-fallback-pipeline-plugin-medium",
    "ovos-fallback-pipeline-plugin-low",
]

_LANG_RE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$")

#: The keys this page may write, and the configuration path each one is at.
#: This is the allowlist a caller must pass through: nothing outside this set
#: can be written by ``set_value``, whatever path a request names.
FIELD_PATHS: dict[str, list[str]] = {
    "wake_word": ["listener", "wake_word"],
    "vad_module": ["listener", "VAD", "module"],
    "stt_module": ["stt", "module"],
    "stt_fallback": ["stt", "fallback_module"],
    "tts_module": ["tts", "module"],
    "tts_fallback": ["tts", "fallback_module"],
    "pipeline": ["intents", "pipeline"],
    "utterance_transformers": ["utterance_transformers"],
    "metadata_transformers": ["metadata_transformers"],
    "lang": ["lang"],
    "secondary_langs": ["secondary_langs"],
}

#: The plugin family (as ``pypi.classify`` names it) each picker's options are
#: drawn from. Wake word and pipeline/transformer keys are not single-plugin
#: pickers, so they are handled on their own below.
_FAMILY_OF = {
    "vad_module": "vad",
    "stt_module": "stt",
    "stt_fallback": "stt",
    "tts_module": "tts",
    "tts_fallback": "tts",
}


class VoiceConfigError(ValueError):
    """Raised when a field name or a value is not usable."""


def _installed_by_family() -> dict[str, list[str]]:
    """Group the installed OVOS plugin distributions by family.

    Reads real, installed packages (not a hardcoded list) through
    ``pypi.installed_versions`` and sorts each into a family with
    ``pypi.classify`` — the same classifier the Plugins page uses.
    """
    out: dict[str, list[str]] = {}
    for name in pypi.installed_versions():
        kind = pypi.classify(name)
        if kind:
            out.setdefault(kind, []).append(name)
    for kind in out:
        out[kind].sort()
    return out


def _hotwords(merged: dict[str, Any]) -> list[str]:
    hotwords = merged.get("hotwords") or {}
    return sorted(hotwords) if isinstance(hotwords, dict) else []


def get_settings() -> dict[str, Any]:
    """Return the current value and the available options of every field.

    Never raises: a broken plugin listing must not break the whole page, so any
    failure while gathering options is logged and that field simply gets an
    empty option list (the current value is still shown).
    """
    user = configio.read_user_config()
    merged = configio.read_merged_config()
    try:
        by_family = _installed_by_family()
    except Exception as err:  # noqa: BLE001 - a page must not die on this
        LOG.warning(f"could not list installed plugins: {err}")
        by_family = {}

    fields: dict[str, Any] = {}
    for name, path in FIELD_PATHS.items():
        fields[name] = {
            "value": configio.get_in(user, path),
            "effective": configio.get_in(merged, path),
        }

    for name, family in _FAMILY_OF.items():
        fields[name]["options"] = by_family.get(family, [])

    fields["wake_word"]["options"] = _hotwords(merged)
    fields["vad_module"]["options"] = fields["vad_module"]["options"] or by_family.get("vad", [])
    # Guard the shapes: a config someone hand-edited badly (a pipeline that is
    # not a list, a transformers block that is not a dict) must not crash this
    # read — the page should still load. isinstance, not truthiness.
    _pipe = fields["pipeline"]["effective"]
    _utt = fields["utterance_transformers"]["effective"]
    fields["pipeline"]["options"] = sorted(
        set(DEFAULT_PIPELINE) | set(by_family.get("pipeline", []))
        | set(_pipe if isinstance(_pipe, list) else []))
    fields["utterance_transformers"]["options"] = sorted(
        set(by_family.get("utterance_transformer", []))
        | set((_utt if isinstance(_utt, dict) else {}).keys()))
    fields["metadata_transformers"]["options"] = sorted(
        # ovos-webui has no separate "metadata_transformer" PyPI family today;
        # these plugins are usually audio- or dialog-transformer packages
        # repurposed, so offer whatever is configured plus the audio/dialog
        # transformer families installed, rather than an empty list.
        set(by_family.get("audio_transformer", [])) | set(by_family.get("dialog_transformer", []))
        | set(_md.keys() if isinstance((_md := fields["metadata_transformers"]["effective"]), dict) else []))

    return {"fields": fields, "path": str(configio.user_config_path())}


def _check_module_name(field: str, value: Any) -> str:
    if not isinstance(value, str):
        raise VoiceConfigError(f"'{field}' must be text")
    value = value.strip()
    if not value:
        raise VoiceConfigError(f"'{field}' must not be empty")
    if len(value) > 128 or "\n" in value or "\r" in value or "\x00" in value:
        raise VoiceConfigError(f"'{field}' must be a single short line")
    return value


def _check_optional_module_name(field: str, value: Any) -> str:
    """Like ``_check_module_name``, but an empty string clears the fallback."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise VoiceConfigError(f"'{field}' must be text")
    value = value.strip()
    if len(value) > 128 or "\n" in value or "\r" in value or "\x00" in value:
        raise VoiceConfigError(f"'{field}' must be a single short line")
    return value


def _check_lang(field: str, value: Any) -> str:
    if not isinstance(value, str) or not _LANG_RE.match(value.strip()):
        raise VoiceConfigError(f"'{field}' must be a language code, for example pt-pt")
    return value.strip()


_KNOWN_STAGES = set(DEFAULT_PIPELINE)


def _check_pipeline(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise VoiceConfigError("'pipeline' must be a non-empty list of stage names")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise VoiceConfigError("'pipeline' entries must be non-empty text")
        item = item.strip()
        if len(item) > 128:
            raise VoiceConfigError("'pipeline' entries are too long")
        out.append(item)
    if len(set(out)) != len(out):
        raise VoiceConfigError("'pipeline' must not repeat a stage")
    return out


def _check_transformer_list(field: str, value: Any) -> dict[str, Any]:
    """A transformer section is a mapping of plugin name to its own config.

    The form only ever needs to turn plugins on and off, so it sends a plain
    list of names; each is stored with an empty config, and any config a name
    already had is kept when that name stays in the list.
    """
    if not isinstance(value, list):
        raise VoiceConfigError(f"'{field}' must be a list of plugin names")
    names = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise VoiceConfigError(f"'{field}' entries must be non-empty text")
        item = item.strip()
        if len(item) > 128:
            raise VoiceConfigError(f"'{field}' entries are too long")
        names.append(item)
    if len(set(names)) != len(names):
        raise VoiceConfigError(f"'{field}' must not repeat a plugin")
    return names


def _check_secondary_langs(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise VoiceConfigError("'secondary_langs' must be a list of language codes")
    out = []
    for item in value:
        out.append(_check_lang("secondary_langs", item))
    return out


_CHECKS = {
    "wake_word": lambda v: _check_module_name("wake_word", v),
    "vad_module": lambda v: _check_module_name("vad_module", v),
    "stt_module": lambda v: _check_module_name("stt_module", v),
    "stt_fallback": lambda v: _check_optional_module_name("stt_fallback", v),
    "tts_module": lambda v: _check_module_name("tts_module", v),
    "tts_fallback": lambda v: _check_optional_module_name("tts_fallback", v),
    "pipeline": _check_pipeline,
    "utterance_transformers": lambda v: _check_transformer_list("utterance_transformers", v),
    "metadata_transformers": lambda v: _check_transformer_list("metadata_transformers", v),
    "lang": lambda v: _check_lang("lang", v),
    "secondary_langs": _check_secondary_langs,
}


def set_value(key: str, value: Any, bus=None) -> dict[str, Any]:
    """Validate ``value`` for ``key`` and write it into the user layer.

    ``key`` must be one of :data:`FIELD_PATHS` — anything else is refused
    before any file is touched, so a request cannot use this endpoint to write
    an arbitrary configuration path. Never raises past validation: a bad value
    is turned into an error dict, the same shape a caller already has to
    handle for a rejected write.
    """
    if key not in FIELD_PATHS:
        raise VoiceConfigError(f"unknown voice setting: {key}")
    checked = _CHECKS[key](value)
    path = FIELD_PATHS[key]

    def change(user: dict[str, Any]) -> None:
        if key in ("stt_fallback", "tts_fallback") and checked == "":
            configio.del_in(user, path)
            return
        if key in ("utterance_transformers", "metadata_transformers"):
            existing = configio.get_in(user, path)
            existing = existing if isinstance(existing, dict) else {}
            merged_map = configio.get_in(configio.read_merged_config(), path)
            merged_map = merged_map if isinstance(merged_map, dict) else {}
            section = {}
            for name in checked:
                section[name] = existing.get(name, merged_map.get(name, {}))
            configio.set_in(user, path, section)
            return
        configio.set_in(user, path, checked)

    return configio.mutate(change, bus=bus)
