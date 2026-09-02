"""Seeking, repeat, and the reason a device makes no sound.

The panel could already say what was playing and press the transport buttons.
It could not scrub, could not show whether the queue repeats, and -- the one
that costs people hours -- could not say that the device has no way to play
audio at all. A bare install loads no media backend, and the only trace of
that is a single line in a log: every play request is accepted, nothing comes
out, and the panel reported success.

Every message here is one `ovos-media` already binds in
`ovos_media/bus/api.py`, and every reply shape is read from the handler that
sends it.
"""
from ovos_utils.fakebus import FakeBus

from ovos_webui import media


def _bus(answers):
    """A bus that answers `topic -> data`, the way the player does."""
    bus = FakeBus()
    for topic, data in answers.items():
        bus.on(topic, lambda m, d=data: bus.emit(m.response(d)))
    return bus


class TestTheSeekBar:
    def test_the_position_and_length_come_back_in_milliseconds(self):
        bus = _bus({"ovos.common_play.get_track_position": {"position": 42000},
                    "ovos.common_play.get_track_length": {"length": 214000}})
        assert media.track_progress(bus) == {"ok": True, "position": 42000,
                                            "length": 214000}

    def test_a_track_that_reports_no_length_is_not_scrubbable(self):
        """A live stream has no end to drag towards."""
        bus = _bus({"ovos.common_play.get_track_position": {"position": 9000},
                    "ovos.common_play.get_track_length": {"length": 0}})
        assert media.track_progress(bus)["length"] is None

    def test_nothing_answering_is_an_error_not_a_position_of_zero(self):
        """Zero is a real place in a track; silence is not."""
        result = media.track_progress(FakeBus())
        assert result["ok"] is False
        assert result["position"] is None

    def test_seeking_sends_an_absolute_position_in_milliseconds(self):
        bus, seen = FakeBus(), []
        bus.on("ovos.common_play.set_track_position",
               lambda m: seen.append(m.data))
        assert media.seek_to(bus, 90500)["ok"] is True
        assert seen == [{"position": 90500}]

    def test_a_position_that_is_not_a_number_never_reaches_the_bus(self):
        """`decode_track_position` drops these, so the seek would silently
        do nothing while the panel said it worked."""
        for bad in ("half way", None, float("inf"), float("nan"), -1):
            bus, seen = FakeBus(), []
            bus.on("ovos.common_play.set_track_position",
                   lambda m: seen.append(m.data))
            assert media.seek_to(bus, bad)["ok"] is False, bad
            assert seen == [], bad


class TestRepeatAndShuffle:
    def test_the_repeat_state_is_reported_with_the_rest_of_the_status(self):
        bus = _bus({"ovos.common_play.status": {
            "player_state": 1, "loop_state": 1, "shuffle": True,
            "title": "A song", "artist": "Someone"}})
        state = media.status(bus)
        assert state["shuffle"] is True
        assert state["repeat"] == "all"

    def test_the_names_are_the_enums_and_not_the_other_way_round(self):
        """`REPEAT` is the queue and `REPEAT_TRACK` is the one track. Naming
        them from memory rather than from the enum gets a badge that says the
        opposite of what the player is doing."""
        from ovos_utils.ocp import LoopState

        assert media._REPEAT_NAMES[LoopState.NONE.value] == "off"
        assert media._REPEAT_NAMES[LoopState.REPEAT.value] == "all"
        assert media._REPEAT_NAMES[LoopState.REPEAT_TRACK.value] == "one"

    def test_each_repeat_state_has_a_name_a_person_can_read(self):
        for value, name in ((0, "off"), (1, "all"), (2, "one")):
            bus = _bus({"ovos.common_play.status": {"player_state": 1,
                                                    "loop_state": value}})
            assert media.status(bus)["repeat"] == name

    def test_an_older_player_that_does_not_report_repeat_says_so(self):
        bus = _bus({"ovos.common_play.status": {"player_state": 1}})
        assert media.status(bus)["repeat"] is None

    def test_setting_shuffle_uses_the_topic_for_the_direction_asked(self):
        for on, topic in ((True, "ovos.common_play.shuffle.set"),
                          (False, "ovos.common_play.shuffle.unset")):
            bus, seen = FakeBus(), []
            for candidate in ("ovos.common_play.shuffle.set",
                              "ovos.common_play.shuffle.unset"):
                bus.on(candidate, lambda m: seen.append(m.msg_type))
            assert media.set_shuffle(bus, on)["ok"] is True
            assert seen == [topic]


class TestWhyTheDeviceMakesNoSound:
    def test_a_device_with_no_backend_at_all_is_reported_as_such(self):
        """The commonest cause of "I asked for music and nothing happened":
        the media service is running and has nothing to play through."""
        bus = _bus({"ovos.common_play.list_backends": {}})
        result = media.backends(bus)
        assert result["ok"] is True
        assert result["backends"] == []
        assert result["can_play"] is False

    def test_the_backends_it_does_have_are_named(self):
        bus = _bus({"ovos.common_play.list_backends": {
            "mpv": {"supported_uris": ["file", "http"], "remote": False},
            "chromecast": {"supported_uris": ["http"], "remote": True}}})
        result = media.backends(bus)
        assert result["can_play"] is True
        assert [b["name"] for b in result["backends"]] == ["chromecast", "mpv"]
        assert [b["remote"] for b in result["backends"]] == [True, False]

    def test_no_answer_is_not_the_same_as_no_backends(self):
        """An older media service that cannot be asked must not be reported
        as a device that cannot play anything."""
        result = media.backends(FakeBus())
        assert result["ok"] is False
        assert result["can_play"] is None


def test_setting_repeat_uses_the_topic_for_the_direction_asked():
    for on, topic in ((True, "ovos.common_play.repeat.set"),
                      (False, "ovos.common_play.repeat.unset")):
        bus, seen = FakeBus(), []
        for candidate in ("ovos.common_play.repeat.set",
                          "ovos.common_play.repeat.unset"):
            bus.on(candidate, lambda m: seen.append(m.msg_type))
        assert media.set_repeat(bus, on)["ok"] is True
        assert seen == [topic]
