"""Point the STT / TTS / translate plugins at self-hosted servers.

Three of the plugins OVOS ships with talk to a server over HTTP instead of
running a model locally: ``ovos-stt-plugin-server``, ``ovos-tts-plugin-server``,
and the pair ``ovos-lang-detector-plugin-server`` /
``ovos-translate-plugin-server``. Each reads an ordered list of URLs from its
own section of the configuration and tries them in turn, falling back to the
next one when a request fails or times out — that failover already lives in
the plugins themselves (see each plugin's ``get_servers``/``urls`` code). This
module only reads and writes the list each plugin reads, in the user
configuration layer, the same way the config editor does.

The three plugins do not agree on the config key that holds the list:

- STT (``ovos_stt_plugin_server.OVOSHTTPServerSTT``) reads ``config["urls"]``,
  a list, at ``stt.<module>.urls``.
- TTS (``ovos_tts_plugin_server.OVOSServerTTS``) reads ``config["host"]``, a
  list or a single string, at ``tts.<module>.host``.
- The translate pair (``ovos_translate_server_plugin``) also reads
  ``config["host"]`` at ``language.<module>.host`` — one entry for the
  detector module, one for the translator module. Both are written together
  here, with the same list, because a self-hosted deployment normally serves
  both endpoints from the same box.

This never invents a default URL. An empty list is a legitimate answer: the
plugin then falls back to its own ``public_servers``. Nothing here is a bus
message; it edits the user configuration file, exactly like the config editor
(``configio.mutate``).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ovos_webui import configio

#: The device tries at most this many servers, in order, before giving up.
MAX_URLS = 10
#: A URL longer than this cannot be a real server address.
MAX_URL_LENGTH = 512


class ServersError(ValueError):
    """Raised when a submitted URL list cannot be used."""


#: One entry per engine kind. ``list_key`` is the exact key the plugin's own
#: code reads for its URL list (see the module docstring for the citation).
_SIMPLE_ENGINES = {
    "stt": {
        "section": "stt",
        "default_module": "ovos-stt-plugin-server",
        "list_key": "urls",
    },
    "tts": {
        "section": "tts",
        "default_module": "ovos-tts-plugin-server",
        "list_key": "host",
    },
}

#: The translate kind is not one plugin but a detector/translator pair that
#: share a config section (``language``) and are pointed at the same servers.
_TRANSLATE = {
    "detection_module": "ovos-lang-detector-plugin-server",
    "translation_module": "ovos-translate-plugin-server",
    "list_key": "host",
}

KINDS = ("stt", "tts", "translate")


def _validate_urls(urls: Any) -> list[str]:
    """Return ``urls`` as a clean list of http(s) URLs, or raise."""
    if not isinstance(urls, list):
        raise ServersError("urls must be a list")
    if len(urls) > MAX_URLS:
        raise ServersError(f"no more than {MAX_URLS} servers are allowed")
    out = []
    for item in urls:
        if not isinstance(item, str):
            raise ServersError("every server must be a URL string")
        value = item.strip()
        if not value:
            continue
        if len(value) > MAX_URL_LENGTH:
            raise ServersError(f"'{value[:40]}…' is too long")
        try:
            parsed = urlparse(value)
        except ValueError:
            raise ServersError(f"'{value}' is not a valid URL") from None
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ServersError(f"'{value}' is not a valid http(s) URL")
        # A real URL carries no raw whitespace or control characters (they are
        # percent-encoded), so reject any rather than storing them verbatim.
        # This covers TAB, other C0 controls, DEL, NEL, and the Unicode line/
        # paragraph/space separators, not just NUL/CR/LF.
        if any(ord(c) < 0x20 or ord(c) == 0x7f or c.isspace() for c in value):
            raise ServersError(f"'{value}' is not a valid URL")
        out.append(value)
    return out


def _stt_tts_get(kind: str) -> dict[str, Any]:
    spec = _SIMPLE_ENGINES[kind]
    section = spec["section"]
    module = configio.user_or_merged([section, "module"]) or spec["default_module"]
    if not isinstance(module, str):
        module = spec["default_module"]
    urls = configio.user_or_merged([section, module, spec["list_key"]]) or []
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, list):
        urls = []
    return {"kind": kind, "module": module, "urls": [u for u in urls if isinstance(u, str)]}


def _stt_tts_set(kind: str, urls: list[str]) -> dict[str, Any]:
    spec = _SIMPLE_ENGINES[kind]
    section = spec["section"]
    module = configio.user_or_merged([section, "module"]) or spec["default_module"]
    if not isinstance(module, str):
        module = spec["default_module"]

    def change(user):
        if urls:
            configio.set_in(user, [section, module, spec["list_key"]], urls)
        else:
            configio.del_in(user, [section, module, spec["list_key"]])

    result = configio.mutate(change)
    return {"module": module, "urls": urls, "write": result}


def _translate_get() -> dict[str, Any]:
    detect_module = (configio.user_or_merged(["language", "detection_module"])
                      or _TRANSLATE["detection_module"])
    translate_module = (configio.user_or_merged(["language", "translation_module"])
                        or _TRANSLATE["translation_module"])
    if not isinstance(detect_module, str):
        detect_module = _TRANSLATE["detection_module"]
    if not isinstance(translate_module, str):
        translate_module = _TRANSLATE["translation_module"]
    urls = (configio.user_or_merged(["language", translate_module, _TRANSLATE["list_key"]])
           or configio.user_or_merged(["language", detect_module, _TRANSLATE["list_key"]])
           or [])
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, list):
        urls = []
    return {"kind": "translate", "detection_module": detect_module,
            "translation_module": translate_module,
            "urls": [u for u in urls if isinstance(u, str)]}


def _translate_set(urls: list[str]) -> dict[str, Any]:
    detect_module = (configio.user_or_merged(["language", "detection_module"])
                      or _TRANSLATE["detection_module"])
    translate_module = (configio.user_or_merged(["language", "translation_module"])
                        or _TRANSLATE["translation_module"])
    if not isinstance(detect_module, str):
        detect_module = _TRANSLATE["detection_module"]
    if not isinstance(translate_module, str):
        translate_module = _TRANSLATE["translation_module"]

    def change(user):
        for module in {detect_module, translate_module}:
            if urls:
                configio.set_in(user, ["language", module, _TRANSLATE["list_key"]], urls)
            else:
                configio.del_in(user, ["language", module, _TRANSLATE["list_key"]])

    result = configio.mutate(change)
    return {"detection_module": detect_module, "translation_module": translate_module,
            "urls": urls, "write": result}


def get_servers(kind: str) -> dict[str, Any]:
    """Return the currently configured server list for ``kind``.

    Never raises on an unknown kind or a malformed stored value; returns an
    error dict instead, so a broken user config layer cannot 500 the page.
    """
    try:
        if kind in _SIMPLE_ENGINES:
            return _stt_tts_get(kind)
        if kind == "translate":
            return _translate_get()
        return {"error": f"unknown kind '{kind}'"}
    except Exception as err:  # noqa: BLE001 - never let a bad config 500 this
        return {"error": str(err)}


def set_servers(kind: str, urls: Any) -> dict[str, Any]:
    """Validate and write the server list for ``kind``. Never raises."""
    try:
        clean = _validate_urls(urls)
    except ServersError as err:
        return {"error": str(err)}
    try:
        if kind in _SIMPLE_ENGINES:
            return _stt_tts_set(kind, clean)
        if kind == "translate":
            return _translate_set(clean)
        return {"error": f"unknown kind '{kind}'"}
    except Exception as err:  # noqa: BLE001 - a write must report, not crash
        return {"error": str(err)}
