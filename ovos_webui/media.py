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

#: ``loop_state`` as the player reports it: ``ovos_utils.ocp.LoopState`` is
#: ``NONE = 0``, ``REPEAT = 1``, ``REPEAT_TRACK = 2``, so 1 repeats the queue
#: and 2 repeats the one track. Read from the enum rather than assumed: the
#: two are easy to swap and the badge then tells the reader the opposite of
#: what the device is doing.
_REPEAT_NAMES = {0: "off", 1: "all", 2: "one"}


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
            "artist": None, "image": None, "shuffle": None, "repeat": None,
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
            "repeat": _REPEAT_NAMES.get(data.get("loop_state")),
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


def track_progress(bus) -> dict[str, Any]:
    """Where the track is and how long it runs, both in milliseconds.

    Read live rather than from the status snapshot: the player asks its
    backend for the position each time, and a snapshot taken a second ago
    would draw the handle behind where the music actually is.

    A length of zero means the player does not know one -- a live stream has
    no end -- and is reported as no length rather than as a track of zero
    seconds, so the page can offer a position without offering a scrub bar.
    """
    from ovos_webui import buswait

    position = buswait.wait_for_response(
        bus, _msg("ovos.common_play.get_track_position"), timeout=QUERY_TIMEOUT)
    if position is None:
        return {"ok": False, "position": None, "length": None}
    length = buswait.wait_for_response(
        bus, _msg("ovos.common_play.get_track_length"), timeout=QUERY_TIMEOUT)
    reported = (length.data or {}).get("length") if length is not None else None
    return {"ok": True,
            "position": (position.data or {}).get("position"),
            "length": reported or None}


def seek_to(bus, position: Any) -> dict[str, Any]:
    """Move to an absolute position, in milliseconds.

    Checked here rather than left to the player: it drops a position that is
    not a real number, and a dropped message is a control that reports
    success and does nothing.
    """
    import math

    if isinstance(position, bool) or not isinstance(position, (int, float)):
        return {"ok": False, "error": "the position must be a number of "
                                      "milliseconds"}
    if math.isnan(position) or math.isinf(position) or position < 0:
        return {"ok": False, "error": "the position must be a number of "
                                      "milliseconds"}
    from ovos_webui import buswait

    return {"ok": buswait.emit(
        bus, _msg("ovos.common_play.set_track_position",
                  {"position": int(position)}))}


def set_shuffle(bus, enabled: Any) -> dict[str, Any]:
    """Turn shuffle on or off.

    Two topics rather than one with a flag, because that is what the player
    binds: ``shuffle.set`` and ``shuffle.unset``.
    """
    topic = ("ovos.common_play.shuffle.set" if enabled
             else "ovos.common_play.shuffle.unset")
    return _transport(bus, topic)


def set_repeat(bus, enabled: Any) -> dict[str, Any]:
    """Repeat the queue, or stop repeating it.

    Two topics, as with shuffle. The player's ``repeat.set`` means repeat the
    queue; it has no separate message for repeating one track, so the panel
    offers the state it can actually set.
    """
    topic = ("ovos.common_play.repeat.set" if enabled
             else "ovos.common_play.repeat.unset")
    return _transport(bus, topic)


def backends(bus) -> dict[str, Any]:
    """What the device can actually play audio through.

    A media service with no backend loaded accepts every play request and
    makes no sound, which is the single hardest media failure to diagnose
    from the outside: nothing errors, and the only evidence is a line in a
    log. Nothing answering is reported separately from answering with none --
    an older service that cannot be asked has not told us it is mute.
    """
    from ovos_webui import buswait

    reply = buswait.wait_for_response(
        bus, _msg("ovos.common_play.list_backends"), timeout=QUERY_TIMEOUT)
    if reply is None:
        return {"ok": False, "backends": [], "can_play": None}
    data = reply.data or {}
    found = [{"name": name,
              "remote": bool((info or {}).get("remote")),
              "uris": [u for u in ((info or {}).get("supported_uris") or [])
                       if isinstance(u, str)]}
             for name, info in sorted(data.items()) if isinstance(name, str)]
    return {"ok": True, "backends": found, "can_play": bool(found)}


def _playable(entry: Any) -> bool:
    """Whether the player would accept this entry as something to play.

    Mirrors `_is_valid_media` in `ovos_media.bus.schemas`, precedence and
    all: a playlist wins, then an extractor with a stream, then a non-empty
    uri. An entry the player would drop is a row that cannot do anything, so
    the page does not offer it.
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("playlist"):
        return isinstance(entry["playlist"], (list, tuple)) and bool(entry["playlist"])
    if entry.get("extractor_id"):
        return isinstance(entry["extractor_id"], str) and bool(entry.get("stream"))
    uri = entry.get("uri")
    return isinstance(uri, str) and uri != ""


def _entries(bus, msg_type: str) -> dict[str, Any]:
    """Ask for a list of media entries, and say plainly when nobody answers.

    An empty list means the device has nothing to offer. No reply usually
    means the player is older than the query -- both arrived in ovos-media
    2.2.0a1 -- though a player that simply did not answer in time looks the
    same from here, and over a request-and-reply query the two cannot be told
    apart. Either way it is not the same as having nothing to offer, and the
    page does not show it as such.
    """
    from ovos_webui import buswait

    reply = buswait.wait_for_response(bus, _msg(msg_type), timeout=QUERY_TIMEOUT)
    if reply is None:
        return {"ok": False, "entries": []}
    found = (reply.data or {}).get("entries") or []
    return {"ok": True, "entries": [e for e in found if _playable(e)]}


def candidates(bus) -> dict[str, Any]:
    """What else the device considered for the request it is playing.

    The commonest complaint about voice media is that it played the wrong
    thing and there is no way to correct it except rephrasing. The player
    keeps the candidate set the queue was chosen from, in descending match
    order; this is a read of it.
    """
    return _entries(bus, "ovos.common_play.disambiguation")


def likes(bus) -> dict[str, Any]:
    """The liked-songs store, which the heart button writes to."""
    return _entries(bus, "ovos.common_play.likes")


def play_entry(bus, entry: Any,
               among: list[Any] | None = None) -> dict[str, Any]:
    """Play one of those entries, keeping the others on offer.

    An ordinary play request carrying the chosen entry, not a "switch to
    candidate" verb: the player already knows how to play an entry, and a new
    message for it would be a second way to say the same thing.

    The candidate set travels with it. A play request's ``disambiguation`` is
    the complete candidate set for that request, and the player replaces what
    it holds with it -- so sending only the picked entry would leave the
    device believing that one entry was all it ever found, and the next pick
    would have nothing to choose from.
    """
    if not _playable(entry):
        # Keyed, not prose: the page turns this into the reader's language.
        return {"ok": False, "error": "media.notPlayable"}
    from ovos_webui import buswait

    data: dict[str, Any] = {"media": entry}
    candidates = [e for e in (among or []) if _playable(e)]
    if entry not in candidates:
        candidates = [entry] + candidates
    if len(candidates) > 1:
        data["disambiguation"] = candidates
    return {"ok": buswait.emit(bus, _msg("ovos.common_play.play", data))}


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
