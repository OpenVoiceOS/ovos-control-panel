"""The Mark-1 face: what the panel draws, and what it sends per LED.

A Mark 1 is a row -- left eye, mouth, right eye -- behind one panel. The eyes
are two rings of twelve addressable LEDs and the mouth is a 32x8 matrix. The
plugin addresses all twenty-four eye LEDs as one flat range (0-11 left, 12-23
right), verified against ovos-PHAL-plugin-mk1's `on_eyes_set_pixel` and
`handle_get_color`, and against ovos-mark1-utils' `LeftEye`/`RightEye`
pixel ranges.
"""
import pytest
from ovos_utils.fakebus import FakeBus

from ovos_webui import mark1


def _eyes_bus(pixels):
    bus = FakeBus()
    # The plugin answers with an explicit reply type, not `.response()`:
    # `handle_get_color` does `message.reply("enclosure.eyes.rgb", ...)`.
    bus.on("enclosure.eyes.rgb.get", lambda m: bus.emit(
        m.reply("enclosure.eyes.rgb", {"pixels": pixels})))
    return bus


class TestTheEyesAreTwoRingsOfTwelve:
    def test_the_flat_range_matches_the_plugins_own_indexing(self):
        """0-11 is the left eye and 12-23 the right, as one list."""
        assert mark1.EYE_PIXELS == 12
        assert mark1.EYE_PIXEL_COUNT == 24

    def test_every_led_is_reported_even_when_the_device_sends_fewer(self):
        """An older plugin reporting a short list must not blank the face."""
        result = mark1.eyes_state(_eyes_bus([[255, 0, 0]] * 4))
        assert result["ok"] is True
        assert len(result["pixels"]) == 24
        assert result["pixels"][0] == [255, 0, 0]
        assert result["pixels"][23] == [0, 0, 0], "a missing LED reads dark"

    def test_a_longer_list_is_truncated_rather_than_drawn_off_the_face(self):
        result = mark1.eyes_state(_eyes_bus([[1, 2, 3]] * 40))
        assert len(result["pixels"]) == 24

    @pytest.mark.parametrize("junk", [None, "red", [1, 2], [1, 2, 3, 4], {},
                                      [True, 0, 0]])
    def test_a_pixel_that_is_not_a_colour_reads_dark(self, junk):
        """Rather than reaching the canvas as NaN and painting nothing at all."""
        result = mark1.eyes_state(_eyes_bus([junk] + [[0, 0, 0]] * 23))
        assert result["pixels"][0] == [0, 0, 0]

    def test_out_of_range_channels_are_clamped(self):
        result = mark1.eyes_state(_eyes_bus([[999, -5, 12.7]] + [[0, 0, 0]] * 23))
        assert result["pixels"][0] == [255, 0, 12]

    def test_no_answer_is_an_error_not_an_empty_face(self):
        """A blank face would read as "the eyes are off", which is a different
        thing from "nothing answered"."""
        result = mark1.eyes_state(FakeBus())
        assert result["ok"] is False
        assert "enclosure.eyes.rgb.get" in result["error"], (
            "named something other than the topic that went unanswered: "
            f"{result['error']}"
        )
        # Every released plugin is silent here while installed and running, so
        # the message must not send the reader off to install it again.
        assert "installed and running" not in result["error"]


class TestOneLedAtATime:
    @staticmethod
    def _sent(bus, seen):
        # The real topic has no underscore. The mk1 plugin's own docstring
        # says `enclosure.eyes.set_pixel`, but the binding in
        # ovos_plugin_manager.templates.phal is `enclosure.eyes.setpixel`, and
        # the binding is what a message reaches.
        bus.on("enclosure.eyes.setpixel", lambda m: seen.append(m.data))

    def test_the_message_goes_to_the_topic_that_is_actually_bound(self):
        """Pinned against the binding, not against a docstring.

        `ovos_plugin_manager.templates.phal` binds
        `enclosure.eyes.setpixel`. The mk1 plugin's docstring for the same
        handler says `enclosure.eyes.set_pixel`, and trusting it sent every
        per-LED write to a topic nothing listens on -- the panel reporting
        success while the LED never changed.
        """
        bus, seen = FakeBus(), []
        self._sent(bus, seen)
        result = mark1.set_pixel(bus, 17, 10, 20, 30)
        assert result["ok"] is True
        assert seen == [{"idx": 17, "r": 10, "g": 20, "b": 30}]

    @pytest.mark.parametrize("idx", [-1, 24, 100, "left", None, 1.5])
    def test_an_index_off_the_rings_never_reaches_the_bus(self, idx):
        """The plugin indexes its pixel list directly, so a bad index there is
        an IndexError in the service rather than a no-op."""
        bus, seen = FakeBus(), []
        self._sent(bus, seen)
        result = mark1.set_pixel(bus, idx, 1, 1, 1)
        assert result["ok"] is False
        assert seen == []

    @pytest.mark.parametrize("bad", [-1, 256, "ff", None])
    def test_a_channel_outside_a_byte_never_reaches_the_bus(self, bad):
        bus, seen = FakeBus(), []
        self._sent(bus, seen)
        assert mark1.set_pixel(bus, 0, bad, 0, 0)["ok"] is False
        assert seen == []

    def test_both_ends_of_the_range_are_addressable(self):
        bus, seen = FakeBus(), []
        self._sent(bus, seen)
        assert mark1.set_pixel(bus, 0, 0, 0, 0)["ok"] is True
        assert mark1.set_pixel(bus, 23, 255, 255, 255)["ok"] is True
        assert [d["idx"] for d in seen] == [0, 23]


class TestFirmwareIsReportedHonestly:
    @staticmethod
    def _fw_bus(data):
        bus = FakeBus()
        bus.on("enclosure.firmware.version.get", lambda m: bus.emit(
            m.reply("enclosure.firmware.version", data)))
        return bus

    def test_a_board_that_has_not_reported_is_not_guessed_at(self):
        """`None` is not an old version, and must not be shown as one."""
        result = mark1.firmware(self._fw_bus({"version": None, "supported": "1.4.2"}))
        assert result["ok"] is True
        assert result["version"] is None
        assert "outdated" not in result

    def test_an_older_board_is_flagged(self):
        result = mark1.firmware(self._fw_bus({"version": "1.3.0", "supported": "1.4.2"}))
        assert result["outdated"] is True

    def test_a_current_board_is_not_flagged(self):
        result = mark1.firmware(self._fw_bus({"version": "1.4.2", "supported": "1.4.2"}))
        assert result["outdated"] is False

    def test_a_newer_board_than_we_know_about_is_not_flagged(self):
        """Someone running a build of their own must not be told to downgrade."""
        result = mark1.firmware(self._fw_bus({"version": "2.0.0", "supported": "1.4.2"}))
        assert result["outdated"] is False

    def test_versions_compare_as_numbers_not_as_text(self):
        """String order puts 1.10.0 before 1.4.2, which would offer a downgrade."""
        result = mark1.firmware(self._fw_bus({"version": "1.10.0", "supported": "1.4.2"}))
        assert result["outdated"] is False
        result = mark1.firmware(self._fw_bus({"version": "1.4.2", "supported": "1.10.0"}))
        assert result["outdated"] is True

    def test_a_plugin_too_old_to_answer_says_what_to_do(self):
        result = mark1.firmware(FakeBus())
        assert result["ok"] is False
        assert "ovos-PHAL-plugin-mk1" in result["error"]

    def test_asking_for_an_update_does_not_wait_for_the_flash(self):
        """It is minutes of work; the request only reports being accepted."""
        seen = []
        bus = FakeBus()
        bus.on("enclosure.firmware.update", lambda m: seen.append(m.data))
        assert mark1.firmware_update(bus)["ok"] is True
        assert seen == [{}]


class TestMouthEventsGating:
    """Which mouth topics the plugin gates, read from the bindings.

    Not from the handler bodies: `_on_mouth_text`, `_on_mouth_display` and
    `_on_mouth_reset` all check `mouth_events_active`, and all three are dead
    code -- `enclosure.mouth.text`, `.display` and `.reset` are bound to the
    ungated `on_text`, `on_display` and `on_display_reset`. A test that
    regexed the bodies would conclude the opposite of the truth.
    """

    def _bindings(self):
        import inspect
        import re

        from ovos_plugin_manager.templates import phal

        src = inspect.getsource(phal)
        return {m.group(1): m.group(3) for m in re.finditer(
            r"[\"'](enclosure\.mouth\.[^\"']+)[\"']\s*,\s*(self\.)?(\w+)", src)}

    def test_only_the_animation_topics_are_gated(self):
        import inspect

        from ovos_plugin_manager.templates import phal

        gated = {topic for topic, handler in self._bindings().items()
                 if handler.startswith("_on_mouth_")
                 and "mouth_events_active" in inspect.getsource(
                     getattr(phal.PHALPlugin, handler))}
        assert gated == {
            "enclosure.mouth.talk", "enclosure.mouth.think",
            "enclosure.mouth.listen", "enclosure.mouth.smile",
            "enclosure.mouth.viseme", "enclosure.mouth.viseme_list",
        }, f"upstream changed which mouth topics are gated: {sorted(gated)}"

    def test_drawing_and_text_are_not_gated(self):
        """So sending the activate before them would be a side effect for
        nothing: it revokes a deactivate a skill may have asked for."""
        bindings = self._bindings()
        for topic in ("enclosure.mouth.text", "enclosure.mouth.display",
                      "enclosure.mouth.reset"):
            assert not bindings[topic].startswith("_on_mouth_"), (
                f"{topic} is bound to {bindings[topic]}, which may be gated"
            )

    def test_the_gate_is_open_from_construction(self):
        import inspect

        from ovos_plugin_manager.templates import phal

        assert "_activate_mouth_events" in inspect.getsource(
            phal.PHALPlugin.__init__), (
            "the plugin no longer opens the gate itself, so the animation "
            "controls need to send the activate unconditionally"
        )

    @pytest.mark.parametrize("name,call", [
        ("mouth_anim", lambda bus: mark1.mouth_anim(bus, "talk")),
        ("mouth_viseme", lambda bus: mark1.mouth_viseme(bus, 1)),
    ])
    def test_a_gated_control_opens_the_gate_first(self, name, call):
        bus = FakeBus()
        seen = []
        real = bus.emit
        bus.emit = lambda m: (seen.append(m.msg_type), real(m))[1]
        call(bus)
        assert "enclosure.mouth.events.activate" in seen, (
            f"{name} is dropped where a skill deactivated the mouth events"
        )
        assert seen.index("enclosure.mouth.events.activate") < len(seen) - 1

    @pytest.mark.parametrize("name,call", [
        ("display_grid", lambda bus: mark1.display_grid(
            bus, [[0] * 32 for _ in range(8)])),
        ("mouth_text", lambda bus: mark1.mouth_text(bus, "hi")),
        ("mouth_reset", lambda bus: mark1.mouth_reset(bus)),
    ])
    def test_an_ungated_control_leaves_the_gate_alone(self, name, call):
        bus = FakeBus()
        seen = []
        real = bus.emit
        bus.emit = lambda m: (seen.append(m.msg_type), real(m))[1]
        call(bus)
        assert "enclosure.mouth.events.activate" not in seen, (
            f"{name} revoked a deactivate it never needed"
        )


def test_the_pixel_route_accepts_exactly_the_pixels_that_exist():
    """The route's bound is a literal; this is what keeps it honest."""
    from ovos_webui import mark1
    from ovos_webui.service import Mark1PixelBody

    bound = Mark1PixelBody.model_fields["idx"].metadata
    highest = next(m.le for m in bound if hasattr(m, "le"))
    assert highest == mark1.EYE_PIXEL_COUNT - 1, (
        "the route and the eye geometry disagree about how many pixels there are"
    )


def test_a_device_that_only_answers_about_firmware_still_counts():
    """Two readbacks, either of which proves the hardware is there.

    A plugin can answer the firmware question and not the eye-colour one, or
    the other way round. Believing only one of them reports no Mark 1 on a
    device that is plainly present.
    """
    bus = FakeBus()
    bus.on("enclosure.firmware.version.get",
           lambda m: bus.emit(m.reply("enclosure.firmware.version",
                                      {"version": "1.0.0", "supported": True})))
    assert mark1.available(bus)["available"] is True


def test_a_device_that_answers_nothing_is_not_claimed():
    assert mark1.available(FakeBus())["available"] is False


def test_a_silent_device_costs_one_timeout_not_two():
    """Both questions are asked at once.

    Every device answers neither until the plugin gains a readback, so this is
    the cost on every load of the page, not an edge case.
    """
    import time

    started = time.monotonic()
    assert mark1.available(FakeBus())["available"] is False
    took = time.monotonic() - started
    assert took < mark1.PROBE_TIMEOUT * 1.8, (
        f"waited {took:.1f}s for two {mark1.PROBE_TIMEOUT}s probes, so they "
        "were asked one after the other"
    )
