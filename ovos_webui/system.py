"""SSH, factory reset, device language, connectivity, and IP-geolocation over
the message bus.

These use the message types ``ovos-PHAL-plugin-system`` (SSH, factory reset,
language), ``ovos-PHAL-plugin-connectivity-events`` (connectivity), and
``ovos-PHAL-plugin-ipgeo`` (IP geolocation) already register — no new ones are
introduced:

* ``system.ssh.status`` -> ``.response`` (``enabled``) — ovos-PHAL-plugin-system
  ``handle_ssh_status`` replies with ``message.response(...)``, i.e. the usual
  ``<type>.response`` topic.
* ``system.ssh.enable`` -> the plugin emits ``system.ssh.enabled`` once it has
  run ``systemctl enable``/``start``; ``system.ssh.disable`` -> ``system.ssh.disabled``
  the same way (``handle_ssh_enable_request`` / ``handle_ssh_disable_request``).
* ``system.factory.reset`` — destructive: the plugin forwards the message to
  ``system.factory.reset.start`` at once, then wipes cache/data and lets other
  PHAL plugins registered on ``system.factory.reset.register`` run their own
  wipe (``handle_factory_reset_request``). There is no "done" reply to wait on
  — the wipe can outlive the request — so this is fire-and-forget like the
  existing reboot/shutdown actions on the controls page.
* ``system.configure.language`` (``language_code``, e.g. ``en_US``) ->
  ``system.configure.language.complete`` (``lang``) (``handle_configure_language_request``).

* ``ovos.PHAL.internet_check`` drives ``ovos-PHAL-plugin-connectivity-events``
  to answer on ``mycroft.internet.state`` and ``mycroft.network.state``
  (each ``{"state": "connected"|"disconnected"}``) — see ``update_state`` in
  that plugin. Both come back for a single check, so both reply topics are
  listened for and their states merged into one result.

* ``ovos.ipgeo.update`` drives ``ovos-PHAL-plugin-ipgeo`` to geolocate the
  device by its public IP and write the result into ``location`` in the user
  config (``update_mycroft_config``). The plugin answers with
  ``message.response(...)`` — ``ovos.ipgeo.update.response`` — carrying
  either ``{"location": {...}}`` or ``{"error": true}``.

Every helper here goes through ``buswait`` (never raises on a bus problem —
timeouts and a down bus come back as an error dict, exactly like ``network.py``).
"""
from __future__ import annotations

import re
from typing import Any

#: How long a status/config round trip may take.
DEFAULT_TIMEOUT = 5.0

#: Wiping and unregistering things device-side can take a moment longer than
#: an ordinary query, but this is still fire-and-forget: no reply is awaited.
FACTORY_RESET_TIMEOUT = 5.0

#: A loose BCP-47-ish check: 2-3 letter language, optional region/script,
#: e.g. "en", "en-US", "en_US", "pt-PT", "zh-Hans-CN". Not a full BCP-47
#: validator — just enough to keep obvious junk off the bus.
_LANG_RE = re.compile(r"\A[a-zA-Z]{2,3}([_-][a-zA-Z0-9]{2,8}){0,2}\Z")


def _msg(msg_type: str, data: dict[str, Any] | None = None):
    from ovos_bus_client.message import Message

    return Message(msg_type, data or {}, {"source": "ovos-webui"})


# ── SSH ───────────────────────────────────────────────────────────────────────
def ssh_status(bus) -> dict[str, Any]:
    """Return ``{"available": bool, "enabled": bool|None}``.

    ``available`` is False when nothing answered ``system.ssh.status`` inside
    the timeout — that is the capability gate: the system plugin is not
    installed, or not running.
    """
    from ovos_webui import buswait

    reply = buswait.wait_for_response(bus, _msg("system.ssh.status"),
                                      timeout=DEFAULT_TIMEOUT)
    if reply is None:
        return {"available": False, "enabled": None}
    data = reply.data or {}
    return {"available": True, "enabled": bool(data.get("enabled"))}


def ssh_enable(bus) -> dict[str, Any]:
    """Ask the system plugin to enable and start the SSH service."""
    from ovos_webui import buswait

    ok = buswait.emit(bus, _msg("system.ssh.enable"))
    return {"sent": ok}


def ssh_disable(bus) -> dict[str, Any]:
    """Ask the system plugin to stop and disable the SSH service."""
    from ovos_webui import buswait

    ok = buswait.emit(bus, _msg("system.ssh.disable"))
    return {"sent": ok}


# ── factory reset ────────────────────────────────────────────────────────────
def factory_reset(bus) -> dict[str, Any]:
    """Ask the system plugin to wipe the device back to defaults.

    Destructive and irreversible on the device; the UI must confirm this with
    the user before ever calling it. Fire-and-forget: the plugin starts
    wiping immediately and there is no single "done" reply to wait for.
    """
    from ovos_webui import buswait

    ok = buswait.emit(bus, _msg("system.factory.reset"),
                      timeout=FACTORY_RESET_TIMEOUT)
    return {"sent": ok}


# ── device language ─────────────────────────────────────────────────────────
def valid_lang(lang: Any) -> bool:
    """A plausible BCP-47-ish language code, e.g. ``en-US`` or ``pt_PT``."""
    return isinstance(lang, str) and bool(_LANG_RE.match(lang))


def set_language(bus, lang: str) -> dict[str, Any]:
    """Set the device language. Rejects anything that is not a plausible code.

    Returns ``{"ok": True, "lang": ...}`` on the plugin's completion reply,
    or ``{"ok": False, "error": ...}`` on a bad code or a bus timeout.
    """
    if not valid_lang(lang):
        return {"ok": False, "error": "that does not look like a language code"}
    from ovos_webui import buswait

    reply = buswait.wait_for_response(
        bus, _msg("system.configure.language", {"language_code": lang}),
        timeout=DEFAULT_TIMEOUT, reply_type="system.configure.language.complete")
    if reply is None:
        return {"ok": False,
                "error": "the system plugin did not answer — is it installed "
                         "and running?"}
    return {"ok": True, "lang": (reply.data or {}).get("lang")}


# ── connectivity ─────────────────────────────────────────────────────────────
def connectivity(bus) -> dict[str, Any]:
    """Report ``{"internet": "connected"|"disconnected"|None, "network": ...}``.

    Drives ``ovos-PHAL-plugin-connectivity-events`` with ``ovos.PHAL.internet_check``
    and listens for both ``mycroft.internet.state`` and ``mycroft.network.state``,
    since a single check answers on both topics. A value stays ``None`` when
    its topic never answered inside the timeout.
    """
    import threading

    from ovos_webui import buswait

    if not buswait.is_connected(bus):
        return {"internet": None, "network": None}

    def run():
        from ovos_bus_client.message import Message

        got = threading.Event()
        box: dict[str, Any] = {}

        def make(key):
            def handler(message):
                box[key] = (message.data or {}).get("state")
                if "internet" in box and "network" in box:
                    got.set()
            return handler

        h_internet = make("internet")
        h_network = make("network")
        bus.on("mycroft.internet.state", h_internet)
        bus.on("mycroft.network.state", h_network)
        try:
            bus.emit(Message("ovos.PHAL.internet_check", {},
                             {"source": "ovos-webui"}))
            got.wait(DEFAULT_TIMEOUT)
        finally:
            try:
                bus.remove("mycroft.internet.state", h_internet)
                bus.remove("mycroft.network.state", h_network)
            except Exception:  # noqa: BLE001 # pragma: no cover
                pass
        return {"internet": box.get("internet"), "network": box.get("network")}

    result = buswait.call(run, timeout=DEFAULT_TIMEOUT + 1.0, default=None)
    if result is None:
        return {"internet": None, "network": None}
    return result


# ── detect location by IP ───────────────────────────────────────────────────
def detect_location(bus) -> dict[str, Any]:
    """Ask ``ovos-PHAL-plugin-ipgeo`` to geolocate the device by its public IP.

    On success the plugin has already written the result into ``location`` in
    the user config — see the [Settings](configuration.md)/config editor to
    review it. Returns ``{"ok": True, "location": {...}}`` or
    ``{"ok": False, "error": ...}``.
    """
    from ovos_webui import buswait

    reply = buswait.wait_for_response(bus, _msg("ovos.ipgeo.update"),
                                      timeout=DEFAULT_TIMEOUT)
    if reply is None:
        return {"ok": False,
                "error": "the ip-geolocation plugin did not answer — is it "
                         "installed and running?"}
    data = reply.data or {}
    if data.get("error"):
        return {"ok": False, "error": "could not geolocate this device by its IP"}
    return {"ok": True, "location": data.get("location")}
