"""Now playing, transport, and volume for the OCP / audio-service media stack.

These use the message types the modern media service (``ovos-media``) and the
legacy OCP plugin (``ovos-plugin-common-play``) already register — no new
ones are introduced:

* ``ovos.common_play.status`` -> ``ovos.common_play.status.response`` (rich
  now-playing status: state, media type, title, artist, image, shuffle,
  playlist position/size). Handled by ``ovos_media/player.py`` ``handle_status``,
  which replies with ``message.response(...)`` — see line ~466-479.
* ``ovos.common_play.track_info`` -> ``ovos.common_play.track_info.response``
  (the current ``MediaEntry`` dict) — a fallback for a stack that answers
  track info but not the newer ``status`` query. See ``handle_track_info_request``
  at ``ovos_media/player.py`` ~1427.
* ``ovos.common_play.play_pause`` / ``.pause`` / ``.resume`` / ``.stop`` /
  ``.next`` / ``.previous`` — fire-and-forget transport, no reply.
* ``ovos.common_play.ping`` -> ``ovos.common_play.pong`` — a capability probe;
  the pong is sent back on the literal ``ovos.common_play.pong`` topic (not a
  ``.response`` suffix), from ``ovos_media/service.py`` ``handle_ping`` (~line
  71-84), which replies with ``message.reply("ovos.common_play.pong")``.
* ``mycroft.volume.get`` -> ``mycroft.volume.get.response`` (``percent`` is a
  0.0-1.0 fraction, ``muted`` a bool).
* ``mycroft.volume.set`` (``percent`` a 0.0-1.0 fraction) — the same message
  the Device page uses. Volume is owned by the PHAL plugins: alsa binds
  ``mycroft.volume.set``, pulseaudio binds that *and*
  ``mycroft.volume.set.gui``. Both multiply what they are given by 100, so both
  want a fraction. This page used to send ``.gui`` with a 0-100 int, which alsa
  ignored and pulseaudio turned into 7300 for 73%, clamped to full volume.
* ``mycroft.volume.mute`` / ``mycroft.volume.unmute`` — fire-and-forget.

When nothing answers (no media service running, or an old OCP plugin that
does not know ``status``/``ping``), every function here reports that instead
of hanging or raising — the bounded bus wrapper guarantees a deadline.
"""
from __future__ import annotations

from typing import Any

#: A status/track_info/volume query should come back quickly.
QUERY_TIMEOUT = 5.0

#: The capability probe is even more time sensitive: it gates the whole page.
PING_TIMEOUT = 3.0

#: ``ovos.common_play.player.PlayerState`` values, duplicated here rather than
#: importing ovos-utils just for three ints — see ``ovos_utils/ocp.py``.
_STATE_NAMES = {0: "stopped", 1: "playing", 2: "paused"}


def _msg(msg_type: str, data: dict[str, Any] | None = None):
    from ovos_bus_client.message import Message

    return Message(msg_type, data or {}, {"source": "ovos-webui"})


def available(bus) -> bool:
    """True when something answers the OCP ping within a short deadline."""
    from ovos_webui import buswait

    reply = buswait.wait_for_response(
        bus, _msg("ovos.common_play.ping"), timeout=PING_TIMEOUT,
        reply_type="ovos.common_play.pong")
    return reply is not None


def _empty_status() -> dict[str, Any]:
    return {"state": "stopped", "media_type": None, "title": None,
            "artist": None, "image": None, "shuffle": None,
            "playlist_position": None, "playlist_size": None}


def status(bus) -> dict[str, Any]:
    """Return the now-playing status.

    Tries the rich ``ovos.common_play.status`` query first; a stack that only
    knows the older ``ovos.common_play.track_info`` still gets metadata back,
    just without the player/playlist fields. No reply at all reports the
    stopped/empty state rather than raising.
    """
    from ovos_webui import buswait

    reply = buswait.wait_for_response(
        bus, _msg("ovos.common_play.status"), timeout=QUERY_TIMEOUT)
    if reply is not None:
        data = reply.data or {}
        state = data.get("player_state")
        return {
            "state": _STATE_NAMES.get(state, "unknown"),
            "media_type": data.get("media_type"),
            "title": data.get("title") or None,
            "artist": data.get("artist") or None,
            "image": data.get("image") or None,
            "shuffle": bool(data.get("shuffle")) if "shuffle" in data else None,
            "playlist_position": data.get("playlist_position"),
            "playlist_size": data.get("playlist_size"),
        }

    reply = buswait.wait_for_response(
        bus, _msg("ovos.common_play.track_info"), timeout=QUERY_TIMEOUT)
    if reply is not None:
        data = reply.data or {}
        out = _empty_status()
        out["title"] = data.get("title") or None
        out["artist"] = data.get("artist") or None
        out["image"] = data.get("image") or None
        out["media_type"] = data.get("media_type")
        return out

    return _empty_status()


def _transport(bus, msg_type: str) -> dict[str, Any]:
    """Fire a transport message. Still gated through the bus wrapper so a
    dead bus is reported rather than left to raise from a caller's `emit`."""
    from ovos_webui import buswait

    ok = buswait.emit(bus, _msg(msg_type))
    return {"ok": ok}


def play_pause(bus) -> dict[str, Any]:
    return _transport(bus, "ovos.common_play.play_pause")


def pause(bus) -> dict[str, Any]:
    return _transport(bus, "ovos.common_play.pause")


def resume(bus) -> dict[str, Any]:
    return _transport(bus, "ovos.common_play.resume")


def stop(bus) -> dict[str, Any]:
    return _transport(bus, "ovos.common_play.stop")


def next(bus) -> dict[str, Any]:  # noqa: A001 - matches the route name
    return _transport(bus, "ovos.common_play.next")


def previous(bus) -> dict[str, Any]:
    return _transport(bus, "ovos.common_play.previous")


def get_volume(bus) -> dict[str, Any]:
    """Return the current volume (0..100) and mute flag, or unknowns."""
    from ovos_webui import buswait

    reply = buswait.wait_for_response(
        bus, _msg("mycroft.volume.get"), timeout=QUERY_TIMEOUT)
    if reply is None:
        return {"percent": None, "muted": None}
    data = reply.data or {}
    percent = data.get("percent")
    if isinstance(percent, (int, float)) and not isinstance(percent, bool):
        # Most plugins report a 0.0-1.0 fraction, but some already report a
        # 0-100 percent — treat anything above 1 as already scaled rather
        # than multiplying it into e.g. 5000%.
        value = percent if percent > 1 else percent * 100
        value = max(0, min(100, value))
        percent_out = round(value)
    else:
        percent_out = None
    return {
        "percent": percent_out,
        "muted": bool(data.get("muted")) if "muted" in data else None,
    }


def set_volume(bus, percent: int) -> dict[str, Any]:
    """Set the volume to a whole percentage 0..100.

    Sent as a fraction, which is what both PHAL volume plugins expect. The
    device plays its volume-change sound either way -- the ``.gui`` variant
    suppresses only the re-report of the new level, not the sound -- so nothing
    is lost by using the message alsa also listens on.
    """
    from ovos_webui import buswait

    # bool is a subclass of int, so guard it out explicitly: True would sail
    # through the range check and set the volume to 1%.
    if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
        raise ValueError("the volume must be a whole number from 0 to 100")
    ok = buswait.emit(bus, _msg("mycroft.volume.set", {"percent": percent / 100.0}))
    return {"percent": percent, "ok": ok}


def mute(bus) -> dict[str, Any]:
    from ovos_webui import buswait

    ok = buswait.emit(bus, _msg("mycroft.volume.mute"))
    return {"muted": True, "ok": ok}


def unmute(bus) -> dict[str, Any]:
    from ovos_webui import buswait

    ok = buswait.emit(bus, _msg("mycroft.volume.unmute"))
    return {"muted": False, "ok": ok}
