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
  device by its public IP. It writes the result into the *web cache*
  (``LocalConf(get_webcache_location())``), not the user config. That layer
  sits below the XDG configs in the merge, so a ``location`` set by hand in
  ``mycroft.conf`` keeps winning and the detected one has no effect. The plugin
  answers with ``message.response(...)`` — ``ovos.ipgeo.update.response`` —
  carrying either ``{"location": {...}}`` or ``{"error": true}``.

Every helper here goes through ``buswait`` (never raises on a bus problem —
timeouts and a down bus come back as an error dict, exactly like ``network.py``).
"""
from __future__ import annotations

import re
from typing import Any

#: How long a status/config round trip may take.
DEFAULT_TIMEOUT = 5.0

#: Geolocation is not a local round trip. The plugin fetches the public IP --
#: through a ``requests.get`` with no timeout of its own -- then queries a
#: geolocation API with a 5s timeout, then writes the web cache behind the
#: cross-process config lock. A window the size of an ordinary query reports a
#: missing plugin on any device whose network is merely slow, while the write
#: goes ahead behind the reader's back.
GEOLOCATE_TIMEOUT = 30.0

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

    The plugin writes what it finds into the web cache, which sits *below* the
    user configuration in the merge. So a ``location`` set by hand in
    ``mycroft.conf`` keeps winning, and the detected one changes nothing --
    reporting a plain success there would be a lie of the same kind this page
    exists to avoid. That case comes back as ``overridden``, with a ``reason``
    saying which of the two ways it will not take effect -- see
    ``_detected_location_fate``.

    Returns ``{"ok": True, "location": {...}}``, with ``overridden: True`` and
    a ``reason`` when the detected location will not be the one the device
    uses, or ``{"ok": False, "error": ...}``.
    """
    from ovos_webui import buswait

    # Ask for the location to be replaced. Without this the plugin returns
    # early on any device that already has one -- and returns *before* it
    # replies, so the silence would be reported here as the plugin missing.
    # Pressing "Detect my location" is the request to overwrite.
    reply = buswait.wait_for_response(bus,
                                      _msg("ovos.ipgeo.update", {"overwrite": True}),
                                      timeout=GEOLOCATE_TIMEOUT)
    if reply is None:
        return {"ok": False,
                "error": "no answer from the ip-geolocation plugin — it may "
                         "not be installed, or the lookup may still be "
                         "running. Check the location on the Settings page "
                         "before trying again."}
    data = reply.data or {}
    if data.get("error"):
        return {"ok": False, "error": "could not geolocate this device by its IP"}

    result = {"ok": True, "location": data.get("location")}
    fate = _detected_location_fate()
    if fate:
        result["overridden"] = True
        result["reason"] = fate
    return result


def _detected_location_fate() -> str | None:
    """Whether the location the plugin just wrote will actually take effect.

    The plugin writes the web cache, which ovos-config merges second from the
    bottom: ``[default, remote, distribution, system, *xdg_configs, patch]``.
    Two different things can stop it mattering, and they need different advice.

    A ``location`` in a layer above it wins, and the remedy is to clear that
    layer -- ``"overridden"``. But a system administrator can also constrain
    the merge, and then nothing is overriding anything: the detected location
    simply never arrives, pointing the reader at the Settings page would send
    them to fix a layer that is not the problem, and the answer is
    ``"ignored"``. Three constraints do that. ``disable_remote_config`` drops
    the web cache outright. ``protected_keys.remote`` strips named keys out of
    it. And so does ``disable_user_config``, which is the one that reads
    backwards: ``filter_and_merge`` classifies every config that is not the
    default or the system one as a *user* config, and the web cache is one of
    them -- it is dropped by that test before the remote branch is ever
    reached.

    The same classification decides which layers can override. The
    distribution config and the runtime patch layer are user configs too, so
    ``protected_keys.user`` strips a ``location`` out of them just as it does
    from the XDG files, leaving the system config as the only layer that can
    outrank the web cache.

    Returns ``None`` when the detected location is the one the device will use.
    """
    try:
        from ovos_config.config import Configuration
        from ovos_config.models import LocalConf

        constraints = Configuration.get_system_constraints() or {}
        protected = constraints.get("protected_keys") or {}
        if (constraints.get("disable_remote_config")
                or constraints.get("disable_user_config")
                or _protects_location(protected.get("remote"))):
            return "ignored"

        # Read the files rather than the layer objects. `LocalConf.load_local`
        # merges the file in and never clears, so a `location` the reader has
        # just deleted -- following the very advice the "overridden" message
        # gives -- would keep answering until the process restarts, and the
        # message would repeat forever. Building fresh objects also keeps this
        # out of ovos-config's process-global layers, which the panel serves
        # from a thread pool.
        higher = [Configuration.system]
        if not _protects_location(protected.get("user")):
            higher.append(Configuration.distribution)
            higher += list(Configuration.xdg_configs)
            higher.append(Configuration._Configuration__patch)
        higher = [LocalConf(layer.path) if getattr(layer, "path", None) else layer
                  for layer in higher]
    except Exception:  # noqa: BLE001 - a bad config must not fail the lookup
        return None

    return "overridden" if any(l.get("location") for l in higher) else None


def _protects_location(protected_keys) -> bool:
    """Whether a ``protected_keys`` list covers ``location``.

    ovos-config deletes each entry with ``flattened_delete``, which splits
    nested keys on ``:`` -- ``"listener:channels"`` in the shipped config, not
    ``listener.channels``. A bare ``location`` takes the whole key out of the
    layer; ``location:city`` takes a leaf out of it. Either way the location
    the device ends up with is not the one that was just detected, which is
    what the page has to say.
    """
    return any(key == "location" or key.startswith("location:")
               for key in (protected_keys or []))
