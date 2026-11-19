"""Voice profiles: enroll a speaker, list the roster, test a voice, delete one.

Every call here is one of the four OVOS-SPEAKER-1 topics that
``ovos-ww-verifier-plugin-speaker`` answers:

- ``ovos.speaker.list`` → the enrolled names
- ``ovos.speaker.enroll`` (name, clips) → whether the profile was written
- ``ovos.speaker.delete`` (name) → whether a profile was removed
- ``ovos.speaker.verify`` (clip) → which enrolled speaker a fresh clip matches

A clip is a base64 WAV, which is what the plugin's handler decodes. This module
carries the clips and adds no audio rule of its own: the plugin owns what a
usable clip is, and a second rule here would drift from it.

Two things this module deliberately does not do:

- It sets no minimum number of clips. More clips make a better profile, and the
  page asks for three to five, but the number that is enough is the plugin's
  judgement, not this UI's. The page guides; the device decides.
- It never turns enrollment on. ``ovos.speaker.enroll`` and
  ``ovos.speaker.delete`` sit behind the plugin's ``allow_bus_enrollment`` key,
  which is off unless the deployment turns it on. A closed gate answers
  ``enrollment disabled``, and this module passes that answer through so the
  page can say so rather than showing a failure with no cause.

The topics are fixed by OVOS-SPEAKER-1, which is proposed in
OpenVoiceOS/architecture#277 and not merged at the time of writing. The names
here follow that draft. If the clause changes a name before it merges, this
module and the page change with it.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any

from ovos_webui import buswait

#: OVOS-SPEAKER-1 §2.
TOPIC_LIST = "ovos.speaker.list"
TOPIC_ENROLL = "ovos.speaker.enroll"
TOPIC_DELETE = "ovos.speaker.delete"
TOPIC_VERIFY = "ovos.speaker.verify"

#: Reading the roster is a file read on the device.
LIST_TIMEOUT = 5.0
#: Deleting is a file write.
DELETE_TIMEOUT = 5.0
#: One clip through the embedding model. The model is loaded on first use, so
#: the first verify after a restart is the slow one.
VERIFY_TIMEOUT = 30.0
#: Three to five clips through the same model, plus the profile write.
ENROLL_TIMEOUT = 120.0

#: The longest a speaker name may be, so a hostile body cannot ride a huge
#: string onto the bus.
MAX_NAME = 64

#: The most clips one enrollment may carry. The page asks for three to five;
#: this is the ceiling that keeps a single request bounded.
MAX_CLIPS = 20

#: The plugin's own default bound on the decoded audio of one request
#: (``DEFAULT_MAX_AUDIO_BYTES``, OVOS-SPEAKER-1 §4.5). Checked here as well so
#: an oversized body is refused before it reaches the bus, with a message that
#: names the cause.
MAX_AUDIO_BYTES = 8 * 1024 * 1024


class SpeakerError(ValueError):
    """Raised when a name or a clip cannot be sent as it is."""


def _msg(msg_type: str, data: dict[str, Any] | None = None):
    from ovos_bus_client.message import Message

    return Message(msg_type, data or {}, {"source": "ovos-webui"})


def check_name(name: Any) -> str:
    """Validate a speaker name, returning the trimmed text."""
    if not isinstance(name, str):
        raise SpeakerError("name must be text")
    name = name.strip()
    if not name:
        raise SpeakerError("name must not be empty")
    if len(name) > MAX_NAME:
        raise SpeakerError(f"name must be {MAX_NAME} characters or fewer")
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in name):
        raise SpeakerError("name must be a single line")
    return name


def check_clips(clips: Any) -> list[str]:
    """Validate the clips of one enrollment, returning them unchanged.

    Each clip must be base64 text, and the decoded total must stay inside the
    bound the plugin applies. The decoded bytes are thrown away here: this
    module does not parse audio, it only refuses what the bus would refuse
    anyway, and does so before the body reaches the bus.
    """
    if not isinstance(clips, list) or not clips:
        raise SpeakerError("at least one recording is needed")
    if len(clips) > MAX_CLIPS:
        raise SpeakerError(f"{MAX_CLIPS} recordings at most")
    total = 0
    for clip in clips:
        total += len(check_clip(clip))
        if total > MAX_AUDIO_BYTES:
            raise SpeakerError("the recordings are too large")
    return clips


def check_clip(clip: Any) -> bytes:
    """Validate one base64 clip, returning its decoded bytes."""
    if not isinstance(clip, str) or not clip:
        raise SpeakerError("a recording is needed")
    try:
        raw = base64.b64decode(clip, validate=True)
    except (binascii.Error, ValueError):
        raise SpeakerError("the recording is not readable") from None
    if not raw:
        raise SpeakerError("the recording is empty")
    if len(raw) > MAX_AUDIO_BYTES:
        raise SpeakerError("the recording is too large")
    return raw


def list_speakers(bus) -> dict[str, Any]:
    """Return the enrolled speaker names."""
    reply = buswait.wait_for_response(bus, _msg(TOPIC_LIST), timeout=LIST_TIMEOUT)
    if reply is None:
        return {"available": False, "speakers": [], "error": None}
    payload = reply.data or {}
    speakers = [s for s in (payload.get("speakers") or []) if isinstance(s, str)]
    return {"available": True, "speakers": speakers,
            "error": payload.get("error")}


def enroll(bus, name: str, clips: list[str]) -> dict[str, Any]:
    """Enroll ``name`` from ``clips``, base64 WAV recordings."""
    name = check_name(name)
    clips = check_clips(clips)
    reply = buswait.wait_for_response(
        bus, _msg(TOPIC_ENROLL, {"name": name, "clips": clips}),
        timeout=ENROLL_TIMEOUT)
    if reply is None:
        return {"available": False, "name": name, "enrolled": False,
                "clips": 0, "error": None}
    payload = reply.data or {}
    return {"available": True, "name": payload.get("name", name),
            "enrolled": bool(payload.get("enrolled")),
            "clips": int(payload.get("clips") or 0),
            "error": payload.get("error")}


def delete_speaker(bus, name: str) -> dict[str, Any]:
    """Delete the profile of ``name``.

    A name that is not enrolled is not an error: the roster ends in the state
    the caller asked for (OVOS-SPEAKER-1 §4.2), and ``removed`` says whether
    anything was actually there.
    """
    name = check_name(name)
    reply = buswait.wait_for_response(
        bus, _msg(TOPIC_DELETE, {"name": name}), timeout=DELETE_TIMEOUT)
    if reply is None:
        return {"available": False, "name": name, "removed": False,
                "error": None}
    payload = reply.data or {}
    return {"available": True, "name": payload.get("name", name),
            "removed": bool(payload.get("removed")),
            "error": payload.get("error")}


def verify(bus, clip: str) -> dict[str, Any]:
    """Say which enrolled speaker one fresh clip matches.

    ``accepted`` is the deployment's own verdict, not a score comparison made
    here: with nobody enrolled it is the ``fail_open`` setting, and
    ``roster_empty`` says which case this is. A null ``speaker`` with a
    non-empty roster means nobody enrolled matches.
    """
    check_clip(clip)
    reply = buswait.wait_for_response(
        bus, _msg(TOPIC_VERIFY, {"clip": clip}), timeout=VERIFY_TIMEOUT)
    if reply is None:
        return {"available": False, "speaker": None, "score": None,
                "accepted": False, "roster_empty": None, "error": None}
    payload = reply.data or {}
    score = payload.get("score")
    return {"available": True, "speaker": payload.get("speaker"),
            "score": float(score) if isinstance(score, (int, float)) else None,
            "accepted": bool(payload.get("accepted")),
            "roster_empty": payload.get("roster_empty"),
            "error": payload.get("error")}
