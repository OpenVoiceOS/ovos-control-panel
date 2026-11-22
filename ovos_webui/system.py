"""Detecting the device's location by its IP, for the Voice and language page.

SSH and the factory reset are a page the panel brings for
``ovos-PHAL-plugin-system`` (``bundled/ovos-phal-plugin-system``), and the
internet check is the ovos-control-panel-network extension's. What is left
here uses the message types ``ovos-PHAL-plugin-ipgeo`` already registers:

* ``ovos.ipgeo.update`` drives ``ovos-PHAL-plugin-ipgeo`` to geolocate the
  device by its public IP. It writes the result into the *assistant layer*
  (``Configuration.assistant``, ``runtime.conf``), not the user config. That
  layer sits below the XDG configs in the merge, so a ``location`` set by hand
  in ``mycroft.conf`` keeps winning and the detected one has no effect. The
  plugin answers with ``message.response(...)`` — ``ovos.ipgeo.update.response``
  — carrying either ``{"location": {...}}`` or ``{"error": true}``.

Every helper here goes through ``buswait`` (never raises on a bus problem —
timeouts and a down bus come back as an error dict, exactly like ``network.py``).
"""
from __future__ import annotations

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


def _msg(msg_type: str, data: dict[str, Any] | None = None):
    from ovos_bus_client.message import Message

    return Message(msg_type, data or {}, {"source": "ovos-webui"})


# ── detect location by IP ───────────────────────────────────────────────────
def detect_location(bus) -> dict[str, Any]:
    """Ask ``ovos-PHAL-plugin-ipgeo`` to geolocate the device by its public IP.

    The plugin writes what it finds into the assistant layer, which sits above
    the system and distribution configs and *below* the user configuration in
    the merge. So a ``location`` set by hand in ``mycroft.conf`` keeps winning,
    and the detected one changes nothing -- reporting a plain success there
    would be a lie of the same kind this page exists to avoid. That case comes
    back as ``overridden``, with a ``reason`` saying which of the two ways it
    will not take effect -- see ``_detected_location_fate``.

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

    The plugin writes the assistant layer (``Configuration.assistant``,
    ``runtime.conf``). ovos-config 3.x merges
    ``[default, distribution, system, assistant, *xdg_configs, patch]``, so the
    assistant layer sits above the system and distribution configs and below
    the XDG user files and the runtime patch layer. Two different things can
    stop the detected location mattering, and they need different advice.

    ``protected_keys.assistant`` covering ``location`` strips it out of the
    assistant layer before the merge. Then nothing is overriding anything: the
    detected location never arrives, pointing the reader at the Settings page
    would send them to fix a layer that is not the problem, and the answer is
    ``"ignored"``. ``disable_user_config`` does not do that:
    ``filter_and_merge`` never drops the assistant layer, only user layers.

    A ``location`` in a layer above the assistant layer wins, and the remedy is
    to clear that layer -- ``"overridden"``. Only the XDG user files and the
    runtime patch layer are above it, and ``filter_and_merge`` counts both as
    user layers: ``disable_user_config`` drops them, and
    ``protected_keys.user`` strips a ``location`` out of them. In either case
    they cannot override. The system and distribution configs merge below the
    assistant layer, so a ``location`` there never wins over the detected one.

    Returns ``None`` when the detected location is the one the device will use.
    """
    try:
        from ovos_config.config import Configuration
        from ovos_config.models import LocalConf

        constraints = Configuration.get_system_constraints() or {}
        protected = constraints.get("protected_keys") or {}
        if _protects_location(protected.get("assistant")):
            return "ignored"
        if (constraints.get("disable_user_config")
                or _protects_location(protected.get("user"))):
            return None

        # Read the files rather than the layer objects. `LocalConf.load_local`
        # merges the file in and never clears, so a `location` the reader has
        # just deleted -- following the very advice the "overridden" message
        # gives -- would keep answering until the process restarts, and the
        # message would repeat forever. Building fresh objects also keeps this
        # out of ovos-config's process-global layers, which the panel serves
        # from a thread pool.
        higher = list(Configuration.xdg_configs) + [Configuration._Configuration__patch]
        higher = [LocalConf(layer.path) if getattr(layer, "path", None) else layer
                  for layer in higher]
    except Exception:  # noqa: BLE001 - a bad config must not fail the lookup
        return None

    return "overridden" if any(layer.get("location") for layer in higher) else None


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
