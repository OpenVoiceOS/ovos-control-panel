"""Read and set the device volume and microphone over the bus.

These use the standard OVOS message types — no new ones are introduced:

* ``mycroft.volume.get`` → ``mycroft.volume.get.response`` (``percent`` 0..1)
* ``mycroft.volume.set`` (``percent`` 0..1), ``mycroft.volume.mute`` / ``.unmute``
* ``mycroft.mic.get_status`` → response (``muted``), ``mycroft.mic.mute`` / ``.unmute``

The volume messages are answered by an audio PHAL plugin (e.g.
``ovos-PHAL-plugin-alsa``); the mic messages by the listener. When nothing is
there to answer, the read simply reports the value as unknown rather than
hanging — the bounded bus wrapper guarantees the deadline.
"""
from __future__ import annotations

from typing import Any


def _msg(msg_type: str, data: dict[str, Any] | None = None):
    from ovos_bus_client.message import Message

    return Message(msg_type, data or {}, {"source": "ovos-webui"})


def get_volume(bus) -> dict[str, Any]:
    """Return the current volume (0..100) and mute flag, or unknowns."""
    from ovos_webui import buswait

    reply = buswait.wait_for_response(bus, _msg("mycroft.volume.get"))
    if reply is None:
        return {"percent": None, "muted": None}
    data = reply.data or {}
    percent = data.get("percent")
    return {
        "percent": round(percent * 100) if isinstance(percent, (int, float)) else None,
        "muted": bool(data.get("muted")) if "muted" in data else None,
    }


def set_volume(bus, percent: int) -> dict[str, Any]:
    """Set the volume to a whole percentage 0..100."""
    from ovos_webui import buswait

    # bool is a subclass of int, so guard it out explicitly: True would sail
    # through the range check and set the volume to 1%.
    if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
        raise ValueError("the volume must be a whole number from 0 to 100")
    buswait.emit(bus, _msg("mycroft.volume.set", {"percent": percent / 100.0}))
    return {"percent": percent}


def set_mute(bus, muted: bool) -> dict[str, Any]:
    """Mute or unmute the speaker."""
    from ovos_webui import buswait

    buswait.emit(bus, _msg("mycroft.volume.mute" if muted else "mycroft.volume.unmute"))
    return {"muted": bool(muted)}


def get_mic(bus) -> dict[str, Any]:
    """Return whether the microphone is muted, or unknown."""
    from ovos_webui import buswait

    reply = buswait.wait_for_response(bus, _msg("mycroft.mic.get_status"))
    if reply is None:
        return {"muted": None}
    return {"muted": bool((reply.data or {}).get("muted"))}


def set_mic_mute(bus, muted: bool) -> dict[str, Any]:
    """Mute or unmute the microphone."""
    from ovos_webui import buswait

    buswait.emit(bus, _msg("mycroft.mic.mute" if muted else "mycroft.mic.unmute"))
    return {"muted": bool(muted)}
