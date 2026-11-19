"""Voice profiles: the four OVOS-SPEAKER-1 calls over a bus, and their routes.

The replies here are the ones ``ovos-ww-verifier-plugin-speaker`` really sends
(``ovos_ww_verifier_plugin_speaker/bus.py`` on the branch of
OpenVoiceOS/ovos-ww-verifier-plugin-speaker#23): every handler answers with
``message.response(...)``, so the reply lands on ``<topic>.response``, and each
carries the specification's own short error string or ``None``.

Two behaviours matter more than the happy path and are pinned here:

- a closed enrollment gate answers ``enrollment disabled`` rather than staying
  silent, and that answer must reach the page as a message, not as a failure;
- a device that does not answer at all is reported as ``available: False``,
  never as a success with an empty roster.
"""
import base64

import pytest

from ovos_webui import speakers

_AUTH = {"Authorization": "Bearer s3cret-token"}

#: A minimal readable WAV: the 44-byte header and one sample. The device parses
#: the audio, this package does not, so nothing here needs real speech.
WAV = base64.b64encode(
    b"RIFF" + (36 + 2).to_bytes(4, "little") + b"WAVEfmt "
    + (16).to_bytes(4, "little") + (1).to_bytes(2, "little")
    + (1).to_bytes(2, "little") + (16000).to_bytes(4, "little")
    + (32000).to_bytes(4, "little") + (2).to_bytes(2, "little")
    + (16).to_bytes(2, "little") + b"data" + (2).to_bytes(4, "little")
    + b"\x00\x00"
).decode()


def _answers(bus, topic, data):
    """Answer *topic* the way the plugin does, with message.response."""
    from ovos_bus_client.message import Message

    def handler(message):
        bus.emit(Message(topic + ".response", data, message.context))

    bus.on(topic, handler)


# ── list ─────────────────────────────────────────────────────────────────────

def test_list_returns_the_roster(bus):
    _answers(bus, "ovos.speaker.list", {"speakers": ["alice", "bob"], "error": None})
    out = speakers.list_speakers(bus)
    assert out == {"available": True, "speakers": ["alice", "bob"], "error": None}


def test_list_without_a_device_is_not_an_empty_roster(bus, monkeypatch):
    # Patched, not assigned: a module constant left short here would shorten
    # every later test in the process.
    monkeypatch.setattr(speakers, "LIST_TIMEOUT", 0.3)
    out = speakers.list_speakers(bus)
    assert out["available"] is False and out["speakers"] == []


def test_list_drops_a_name_that_is_not_text(bus):
    _answers(bus, "ovos.speaker.list", {"speakers": ["alice", 7, None], "error": None})
    assert speakers.list_speakers(bus)["speakers"] == ["alice"]


# ── enroll ───────────────────────────────────────────────────────────────────

def test_enroll_sends_the_name_and_the_clips(bus):
    seen = {}
    from ovos_bus_client.message import Message

    def handler(message):
        seen.update(message.data)
        bus.emit(Message("ovos.speaker.enroll.response",
                         {"name": message.data["name"], "enrolled": True,
                          "clips": len(message.data["clips"]), "error": None},
                         message.context))

    bus.on("ovos.speaker.enroll", handler)
    out = speakers.enroll(bus, "  alice  ", [WAV, WAV, WAV])
    assert seen == {"name": "alice", "clips": [WAV, WAV, WAV]}
    assert out["enrolled"] is True and out["clips"] == 3


def test_a_closed_gate_is_an_answer_not_a_failure(bus):
    _answers(bus, "ovos.speaker.enroll",
             {"name": "alice", "enrolled": False, "clips": 0,
              "error": "enrollment disabled"})
    out = speakers.enroll(bus, "alice", [WAV])
    assert out["available"] is True
    assert out["enrolled"] is False
    assert out["error"] == "enrollment disabled"


def test_enroll_without_a_device_says_so(bus, monkeypatch):
    monkeypatch.setattr(speakers, "ENROLL_TIMEOUT", 0.3)
    out = speakers.enroll(bus, "alice", [WAV])
    assert out["available"] is False and out["enrolled"] is False


@pytest.mark.parametrize("name", ["", "   ", None, 7, "a" * 65, "two\nlines"])
def test_a_name_that_cannot_be_sent_is_refused_before_the_bus(bus, name):
    with pytest.raises(speakers.SpeakerError):
        speakers.enroll(bus, name, [WAV])


@pytest.mark.parametrize("clips", [[], None, "not a list", ["not base64!!"], [""], [7]])
def test_clips_that_cannot_be_sent_are_refused_before_the_bus(bus, clips):
    with pytest.raises(speakers.SpeakerError):
        speakers.enroll(bus, "alice", clips)


def test_too_many_clips_are_refused(bus):
    with pytest.raises(speakers.SpeakerError):
        speakers.enroll(bus, "alice", [WAV] * (speakers.MAX_CLIPS + 1))


def test_clips_larger_than_the_device_bound_are_refused(bus):
    big = base64.b64encode(b"\x00" * (speakers.MAX_AUDIO_BYTES + 1)).decode()
    with pytest.raises(speakers.SpeakerError):
        speakers.enroll(bus, "alice", [big])


def test_clips_that_are_each_small_but_too_large_together_are_refused(bus):
    half = base64.b64encode(b"\x00" * (speakers.MAX_AUDIO_BYTES // 2 + 1)).decode()
    with pytest.raises(speakers.SpeakerError):
        speakers.enroll(bus, "alice", [half, half])


# ── delete ───────────────────────────────────────────────────────────────────

def test_delete_reports_what_was_removed(bus):
    _answers(bus, "ovos.speaker.delete",
             {"name": "alice", "removed": True, "error": None})
    assert speakers.delete_speaker(bus, "alice")["removed"] is True


def test_deleting_a_name_nobody_enrolled_is_not_an_error(bus):
    _answers(bus, "ovos.speaker.delete",
             {"name": "nobody", "removed": False, "error": None})
    out = speakers.delete_speaker(bus, "nobody")
    assert out["available"] is True and out["removed"] is False and out["error"] is None


# ── verify ───────────────────────────────────────────────────────────────────

def test_verify_reports_the_device_verdict(bus):
    _answers(bus, "ovos.speaker.verify",
             {"speaker": "alice", "score": 0.83, "accepted": True,
              "roster_empty": False, "error": None})
    out = speakers.verify(bus, WAV)
    assert out == {"available": True, "speaker": "alice", "score": 0.83,
                   "accepted": True, "roster_empty": False, "error": None}


def test_verify_carries_the_empty_roster_case(bus):
    """With nobody enrolled the verdict is the device's fail_open setting.

    The page has to tell that apart from "somebody is enrolled and this is not
    them", because the two mean opposite things about the device.
    """
    _answers(bus, "ovos.speaker.verify",
             {"speaker": None, "score": None, "accepted": False,
              "roster_empty": True, "error": None})
    out = speakers.verify(bus, WAV)
    assert out["roster_empty"] is True and out["accepted"] is False


def test_verify_of_an_unknown_voice_is_not_an_error(bus):
    _answers(bus, "ovos.speaker.verify",
             {"speaker": None, "score": 0.2, "accepted": False,
              "roster_empty": False, "error": None})
    out = speakers.verify(bus, WAV)
    assert out["speaker"] is None and out["error"] is None and out["score"] == 0.2


def test_a_score_that_is_not_a_number_does_not_reach_the_page(bus):
    _answers(bus, "ovos.speaker.verify",
             {"speaker": "alice", "score": "high", "accepted": True,
              "roster_empty": False, "error": None})
    assert speakers.verify(bus, WAV)["score"] is None


# ── the HTTP routes ──────────────────────────────────────────────────────────

def test_the_page_is_served_and_is_in_the_navigation(client):
    body = client.get("/speakers").text
    assert 'data-i18n="hdr.speakers"' in body
    assert 'id="main"' in body


def test_the_roster_route_answers(token_client, bus):
    _answers(bus, "ovos.speaker.list", {"speakers": ["alice"], "error": None})
    out = token_client.get("/api/speakers", headers=_AUTH).json()
    assert out["speakers"] == ["alice"]


def test_enroll_route_refuses_a_name_that_is_all_spaces(token_client, bus):
    r = token_client.post("/api/speakers/enroll", headers=_AUTH,
                          json={"name": "   ", "clips": [WAV]})
    assert r.status_code == 400


def test_enroll_route_passes_the_device_answer_through(token_client, bus):
    _answers(bus, "ovos.speaker.enroll",
             {"name": "alice", "enrolled": True, "clips": 3, "error": None})
    out = token_client.post("/api/speakers/enroll", headers=_AUTH,
                            json={"name": "alice", "clips": [WAV, WAV, WAV]}).json()
    assert out["enrolled"] is True and out["clips"] == 3


def test_verify_route_refuses_a_clip_that_is_not_base64(token_client, bus):
    r = token_client.post("/api/speakers/verify", headers=_AUTH, json={"clip": "zzz!!"})
    assert r.status_code == 400


def test_delete_route_answers(token_client, bus):
    _answers(bus, "ovos.speaker.delete",
             {"name": "alice", "removed": True, "error": None})
    r = token_client.delete("/api/speakers/alice", headers=_AUTH)
    assert r.json()["removed"] is True


def test_a_stranger_reaches_none_of_it(token_client):
    """Every route here is privileged: a caller with no token is refused.

    Enrollment writes a trusted voice onto the device, so an unauthenticated
    caller must not reach it even when the device's own gate is open.
    """
    assert token_client.get("/api/speakers").status_code in (401, 403)
    assert token_client.post("/api/speakers/enroll",
                             json={"name": "x", "clips": [WAV]}).status_code in (401, 403)
    assert token_client.post("/api/speakers/verify",
                             json={"clip": WAV}).status_code in (401, 403)
    assert token_client.delete("/api/speakers/alice").status_code in (401, 403)


def test_the_enroll_route_may_carry_more_than_a_json_body_limit(client):
    """Clips are audio: the enrollment route needs the upload body limit.

    Without it the middleware cuts a three-clip enrollment off at 1 MiB, and
    the page reports a failure that the device never saw.
    """
    from ovos_webui.fsutils import MAX_UPLOAD_BYTES
    from ovos_webui.service import UPLOAD_PATHS, body_limit_for

    assert "/api/speakers/enroll" in UPLOAD_PATHS
    assert body_limit_for({"path": "/api/speakers/enroll"}) == MAX_UPLOAD_BYTES
    assert body_limit_for({"path": "/api/speakers/verify"}) == MAX_UPLOAD_BYTES
