"""What the panel sends must be what the receiving plugin reads.

Every control here looked fine from the browser: the request succeeded and the
page reported success. Each one sent something no handler could act on, so the
device did nothing and said nothing about it. These tests pin the shape each
handler actually expects, with the version it was read in.
"""
import re
import threading

import pytest
from ovos_utils.fakebus import FakeBus

from ovos_webui import mark1, media, system

#: Every topic these tests care about, so one bus can watch them all.
WATCHED = ("mycroft.volume.set", "mycroft.volume.set.gui",
           "enclosure.mouth.display", "enclosure.mouth.viseme_list",
           "ovos.ipgeo.update")


@pytest.fixture
def sent():
    """Record the messages the panel emits on the topics under test."""
    bus = FakeBus()
    seen = []
    for topic in WATCHED:
        bus.on(topic, lambda m: seen.append(m))
    return bus, seen


def _find(seen, msg_type):
    for message in seen:
        if message.msg_type == msg_type:
            return message
    raise AssertionError(f"{msg_type} was never sent; got {[m.msg_type for m in seen]}")


def test_the_media_volume_is_sent_as_the_fraction_both_plugins_expect(sent):
    """Volume is owned by the PHAL plugins, and both scale by 100.

    alsa binds `mycroft.volume.set`; pulseaudio binds that and
    `mycroft.volume.set.gui`. Sending `.gui` with a 0-100 int was ignored by
    alsa and read by pulseaudio as 7300%, clamped to full volume.
    """
    bus, seen = sent
    media.set_volume(bus, 40)

    types = [m.msg_type for m in seen]
    assert "mycroft.volume.set.gui" not in types, (
        "alsa does not bind mycroft.volume.set.gui at all, so use the message "
        "both plugins listen on"
    )
    message = _find(seen, "mycroft.volume.set")
    # both plugins do `message.data["percent"] * 100`
    assert message.data["percent"] == pytest.approx(0.4)


def test_the_faceplate_drawing_sends_a_string_the_plugin_can_lower(sent):
    """ovos-PHAL-plugin-mk1 does `clear_previous.lower() == "true"`, so a bool
    raises there and nothing is drawn, whichever way the box is ticked."""
    bus, seen = sent
    grid = [[0] * 32 for _ in range(8)]
    mark1.display_grid(bus, grid, x=0, y=0, clear=True)

    value = _find(seen, "enclosure.mouth.display").data["clearPrev"]
    assert isinstance(value, str), f"clearPrev must be a string, got {type(value).__name__}"
    assert value.lower() == "true"

    seen.clear()
    mark1.display_grid(bus, grid, x=0, y=0, clear=False)
    assert _find(seen, "enclosure.mouth.display").data["clearPrev"].lower() == "false"


def test_a_viseme_is_dated_now_so_the_plugin_does_not_skip_it(sent):
    """The plugin writes a viseme only while `time.time() < start + end`, so a
    start of 0 puts every viseme in the past and none is ever shown."""
    import time

    bus, seen = sent
    mark1.mouth_viseme(bus, 3)

    data = _find(seen, "enclosure.mouth.viseme_list").data
    assert data["start"] > time.time() - 60, (
        "start is a timestamp, not an offset; the plugin skips anything already past"
    )
    (code, end), = data["visemes"]
    # the plugin concatenates the code onto "mouth.viseme="
    assert isinstance(code, str), f"the viseme code must be a string, got {type(code).__name__}"
    assert code == "3"
    assert data["start"] + end > time.time(), "the viseme is over before it is drawn"


def test_detecting_the_location_asks_to_replace_the_old_one(sent, monkeypatch):
    """ovos-PHAL-plugin-ipgeo returns early, without replying, when a location
    is already set and `overwrite` is not asked for -- and the panel reports
    that silence as the plugin being missing."""
    bus, seen = sent
    # Nothing answers here, and the real window is a network call's worth of
    # patience; only the message matters to this test.
    monkeypatch.setattr(system, "GEOLOCATE_TIMEOUT", 0.3)
    system.detect_location(bus)

    assert _find(seen, "ovos.ipgeo.update").data.get("overwrite") is True, (
        "without overwrite the plugin never answers on a configured device"
    )


def test_the_skills_service_family_is_broadcast_not_targeted():
    """ovos-core binds only the plain `ovos.pip.install`; it builds no
    ServiceInstaller, so there is no `ovos.pip.install.ovos_core` to target and
    a targeted install waits out the job timeout."""
    from ovos_webui.installer import DEFAULT_INSTALL_SERVICE

    targeted_at_core = sorted(k for k, v in DEFAULT_INSTALL_SERVICE.items()
                              if v == "ovos_core")
    assert "media" not in DEFAULT_INSTALL_SERVICE, (
        "media plugins are loaded by ovos-media, which runs no installer and "
        "answers no targeted topic; addressing them to ovos-audio puts them in "
        "a container that no longer loads them"
    )
    assert not targeted_at_core, (
        f"{targeted_at_core} are routed to a topic nothing listens on; leave them "
        "out of the table so they broadcast"
    )


def test_every_family_is_addressed_to_the_service_that_loads_it():
    """A plugin installed into the wrong container fails silently.

    The negative assertions above catch a family pointed at a service that
    answers nothing. They cannot catch one pointed at a service that answers
    and is still wrong -- the install then succeeds, loudly, into a container
    that never loads the plugin. Each value here is the ``service_name`` its
    owner passes to ``ServiceInstaller``, and each key belongs to the service
    that actually calls the matching ``find_*_plugins``:

    - ovos-audio loads TTS and *dialog* transformers, and no audio ones.
    - ovos-dinkum-listener loads STT, wake words, VAD and *audio*
      transformers.
    - ovos-gui and ovos-PHAL load their own; admin PHAL plugins go to the
      separate root process.
    """
    from ovos_webui.installer import DEFAULT_INSTALL_SERVICE

    assert DEFAULT_INSTALL_SERVICE == {
        "tts": "ovos_audio",
        "dialog_transformer": "ovos_audio",
        "stt": "ovos_dinkum_listener",
        "wake_word": "ovos_dinkum_listener",
        "vad": "ovos_dinkum_listener",
        "audio_transformer": "ovos_dinkum_listener",
        "gui": "ovos_gui",
        "phal": "ovos_PHAL",
        "phal_admin": "ovos_PHAL_admin",
    }


def test_an_admin_phal_plugin_routes_and_advises_by_its_own_key(monkeypatch):
    """The key an operator must set is not the family the page shows.

    An admin PHAL plugin is classified `phal`, which is what the Plugins page
    displays, but it routes by `phal_admin` because it runs in a separate root
    process. Advice that named the visible family would send the operator to a
    key that changes nothing, and they would hit the identical failure again.
    """
    from ovos_webui import configio, installer

    admin = sorted(installer._admin_phal_packages())
    assert admin, "no admin PHAL plugin is known, so this proves nothing"
    package = admin[0]

    monkeypatch.setattr(configio, "user_or_merged",
                        lambda path: {"phal": "broadcast"})
    family, service = installer._install_route_for(package)
    assert family == "phal_admin", (
        f"{package} routes by {family!r}, so setting 'phal' would be a dead end"
    )
    assert service == "ovos_PHAL_admin"

    monkeypatch.setattr(configio, "user_or_merged",
                        lambda path: {"phal_admin": "broadcast"})
    assert installer._install_route_for(package) == ("phal_admin", None), (
        "the key the message names does not turn targeting off"
    )


class TestBroadcastInstallSemantics:
    """Which failures answer for the whole broadcast, and which do not.

    Both installers take the same cross-process `ovos_pip.lock`, so their pip
    runs are serialised and a failure from the first to reply says nothing
    about the one still waiting for the lock.

    Refusing because pip is disabled is different: both read the same global
    `skills.installer` key, so that answer holds for every service on the
    device and there is nothing left to wait for. Since the key is absent from
    the shipped config, that is also the stock device's answer -- which is why
    it has to be fast rather than time out.
    """

    @staticmethod
    def _job(monkeypatch):
        """An installer that does not reach PyPI.

        `install` resolves a version before it emits, so leaving that live puts
        two network calls inside assertions about a two-second budget -- which
        turns a slow index into a failing test about something else entirely.
        """
        from ovos_webui import installer

        inst = installer.Installer()
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 5)
        monkeypatch.setattr(installer, "REMOVE_SETTLE", 1.0)
        monkeypatch.setattr(inst, "_channel_spec", lambda package, **kw: package)
        return inst, installer

    def test_the_job_log_keeps_exactly_the_jobs_it_says_it_does(self):
        """`MAX_JOBS` is a boundary, and boundaries are where off-by-ones live."""
        from ovos_webui import installer

        inst = installer.Installer()
        ids = []
        for index in range(installer.MAX_JOBS + 5):
            job = installer.Job("install", f"pkg-{index}")
            ids.append(job.id)
            with inst._lock:
                inst._remember(job)

        assert len(inst._order) == installer.MAX_JOBS
        assert len(inst._jobs) == installer.MAX_JOBS
        assert inst._order[0] == ids[5], "dropped more history than it kept"

    @pytest.mark.parametrize("sentinel", ["broadcast", "*", ""])
    def test_the_broadcast_sentinels_all_mean_broadcast(self, sentinel,
                                                        monkeypatch):
        """Including the wildcard, which nothing documented and nothing tested."""
        from ovos_webui import configio, installer, pypi

        monkeypatch.setattr(configio, "user_or_merged",
                            lambda keys: {"tts": sentinel})
        monkeypatch.setattr(pypi, "classify", lambda package: "tts")
        assert installer._install_service_for("ovos-tts-plugin-server") is None

    def test_a_deadline_brought_forward_mid_wait_actually_takes_effect(
            self, monkeypatch):
        """The slicing, which every other test of this path misses.

        `FakeBus.emit` is synchronous, so in every other test the failure is
        handled on the installer's own thread before the wait begins, and the
        deadline is already short when the first `Event.wait` is issued. Only a
        reply that arrives while the wait is *already blocked* exercises the
        reason the wait is taken in slices at all: an `Event.wait` under way
        cannot be shortened, so without slicing the shortened deadline is
        ignored and the job runs to the full timeout.
        """
        import threading
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 30)
        monkeypatch.setattr(installer, "INCONCLUSIVE_SETTLE", 1.0)
        bus = FakeBus()

        def on_request(message):
            def late_failure():
                # long enough that the wait loop is blocked when it lands
                time.sleep(0.5)
                bus.emit(message.reply("ovos.pip.install.failed",
                                       {"error": "error in pip subprocess"}))

            threading.Thread(target=late_failure, daemon=True).start()

        bus.on("ovos.pip.install", on_request)
        started = time.time()
        job = inst.install("ovos-skill-news", bus=bus, check_pypi=False)
        deadline = started + 25
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)
        elapsed = time.time() - started

        assert job.state == "error"
        assert elapsed < 5, (
            f"the shortened deadline was ignored by a wait already under way; "
            f"the job ran for {elapsed:.1f}s of its timeout"
        )

    def test_a_broadcast_nobody_answers_names_its_own_likeliest_cause(
            self, monkeypatch):
        """The other half of the same `if`, which nothing else pins.

        A broadcast reached every installer there is, so "that service is too
        old to accept installs addressed to it" is not the cause and telling
        the reader to switch to broadcast is telling them to do what they
        already did. What is worth checking is `allow_pip`.
        """
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 1)
        monkeypatch.setattr(installer, "_install_route_for",
                            lambda package: ("tts", None))
        bus = FakeBus()

        job = inst.install("ovos-tts-plugin-server", bus=bus, check_pypi=False)
        deadline = time.time() + 10
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)

        assert job.state == "error"
        advice = job.lines[-1]
        assert "allow_pip" in advice, (
            f"never named what the reader can check: {job.lines}"
        )
        assert "too old" not in advice, (
            f"blamed a service's vintage for a request nobody was addressed: "
            f"{job.lines}"
        )
        assert "install_services" not in advice, (
            f"told the reader to switch to the broadcast they already used: "
            f"{job.lines}"
        )
        assert "None" not in advice, (
            f"named a service called None: {job.lines}"
        )

    def test_a_targeted_request_nobody_answers_names_its_own_likeliest_cause(
            self, monkeypatch):
        """The broadcast advice is wrong for a targeted request.

        A service answers a request addressed to it only if it is new enough
        to listen for one, which the broadcast text never mentions -- and
        `allow_pip`, which it does mention, is not the likely cause here.
        """
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 1)
        # A name no constant in the module could supply, so a message that
        # hardcodes its own service name fails instead of matching by luck.
        monkeypatch.setattr(installer, "_install_route_for",
                            lambda package: ("zzz_family", "zzz_not_a_real_service"))
        bus = FakeBus()

        job = inst.install("ovos-tts-plugin-server", bus=bus, check_pypi=False)
        deadline = time.time() + 10
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)

        lines = "\n".join(job.lines)
        assert job.state == "error"
        assert "zzz_not_a_real_service" in job.lines[-1], (
            f"did not say which service was asked: {job.lines}"
        )
        assert "too old" in lines, (
            f"never named the likeliest cause for a targeted request: {job.lines}"
        )
        # The remedy has to be one the reader can act on, and it is stated
        # positively rather than by forbidding the wrong wordings. A family the
        # operator never named is still targeted from the built-in table, so
        # advice to take an entry *out* of their config is advice about an
        # entry that need not exist -- and English has more ways to say that
        # than any blacklist can enumerate ("take it out of", "comment out",
        # "no longer list"). Pinning the one correct sentence leaves no room
        # for a wrong one.
        assert re.search(
            r"[Ss]et\s+'zzz_family' to 'broadcast' in "
            r"'webui\.install_services'", lines), (
            f"did not give the remedy the reader can act on: {job.lines}"
        )

    def test_the_shipped_waits_are_the_ones_that_make_the_mechanism_worth_it(self):
        """The values, not just the mechanism they feed.

        Every timing test monkeypatches these constants, so the code that uses
        them is well defended while the shipped numbers are not: setting
        `REMOVE_SETTLE` to `JOB_TIMEOUT` reproduces the fifteen-minute removal
        wedge this module exists to avoid, and every test stays green.

        The bounds here are the reasoning, not the exact figures. A removal
        window has to be short enough that holding the single install slot is
        not the point of it, and long enough for a service to refuse. An
        inconclusive window has to outlast a real plugin install on a slow
        device, and still be a fraction of the timeout it replaces.
        """
        from ovos_webui import installer

        assert 5.0 <= installer.REMOVE_SETTLE <= 30.0, (
            "a removal window this long holds the panel's one install slot for "
            "no gain: nothing that answers a removal takes this long to refuse"
        )
        assert 120.0 <= installer.INCONCLUSIVE_SETTLE <= 300.0, (
            "too short cuts off a queued install; too long is the wedge again"
        )
        # The two windows answer different questions and must not converge: a
        # removal waits only for a fast refusal, an install waits out a real
        # pip run. A removal window creeping up towards the install one means
        # the removal has quietly become the slow path again.
        assert installer.REMOVE_SETTLE * 4 < installer.INCONCLUSIVE_SETTLE
        assert installer.INCONCLUSIVE_SETTLE * 2 <= installer.JOB_TIMEOUT, (
            "the bounded wait is no longer meaningfully shorter than the "
            "timeout it exists to replace"
        )

    def test_an_install_needs_a_connected_bus_not_merely_a_bus_object(self):
        """A disconnected bus must fail cleanly, not emit into the void.

        Without the connection check the panel emits to nobody and waits out
        the job timeout, instead of saying at once that no device is there.
        """
        import pytest
        from ovos_utils.fakebus import FakeBus

        from ovos_webui import buswait, installer

        inst = installer.Installer()
        bus = FakeBus()
        # a bus object that exists but is not connected to anything
        object.__setattr__(bus, "connected_event", threading.Event())

        assert not buswait.is_connected(bus), (
            "the fixture no longer models a disconnected bus"
        )
        with pytest.raises(installer.InstallerUnavailable):
            inst.install("ovos-skill-news", bus=bus, check_pypi=False)

    def test_an_unknown_error_does_not_end_a_broadcast_that_later_succeeds(
            self, monkeypatch):
        """An error outside the vocabulary has to be treated as inconclusive.

        A refusal is the opposite case and settles at once -- see
        `test_pip_being_disabled_answers_for_every_installer_at_once`. These
        tests used to send "pip installs are disabled", which no producer
        emits: it fell out of the vocabulary and exercised this path while
        claiming to be about refusals, so the class asserted two contradictory
        rules and stayed green.
        """
        import threading
        import time

        from ovos_utils.fakebus import FakeBus

        inst, _installer = self._job(monkeypatch)
        bus = FakeBus()

        def on_request(message):
            # a service answers something this panel does not know...
            bus.emit(message.reply("ovos.pip.install.failed",
                                   {"error": "something nobody has seen before"}))

            def slow_success():
                time.sleep(0.5)   # ...the one holding the pip lock finishes later
                bus.emit(message.reply("ovos.pip.install.complete"))

            threading.Thread(target=slow_success, daemon=True).start()

        bus.on("ovos.pip.install", on_request)
        started = time.time()
        job = inst.install("ovos-skill-news", bus=bus, check_pypi=False)
        deadline = started + 10
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)
        elapsed = time.time() - started

        assert job.state == "done", (
            f"a refusal from one service ended the broadcast: {job.lines[-3:]}"
        )
        # Without the success settling the job this still lands on "done" when
        # the wait expires, so the latency is the half worth pinning.
        assert elapsed < 2, (
            f"the success did not settle the job; it waited {elapsed:.1f}s for the timeout"
        )

    def test_one_environment_failing_does_not_cut_off_a_slower_success(
            self, monkeypatch):
        """The temptation this guards against was shipped once and reverted.

        `error in pip subprocess` speaks only for the environment that sent it,
        and on a device where every responder is going to say the same, cutting
        the wait short looks like a kindness. It is not: the services serialise
        on one cross-process pip lock, so a service that has not answered has
        usually not started, and shortening the wait reports a failure for an
        install that goes on to succeed -- leaving the panel's caches saying
        the plugin is absent while it sits installed on the device.
        """
        import threading
        import time

        from ovos_utils.fakebus import FakeBus

        inst, _installer = self._job(monkeypatch)
        bus = FakeBus()

        def on_request(message):
            bus.emit(message.reply("ovos.pip.install.failed",
                                   {"error": "error in pip subprocess"}))

            def slow_success():
                time.sleep(1.5)   # the service still queued on the pip lock
                bus.emit(message.reply("ovos.pip.install.complete"))

            threading.Thread(target=slow_success, daemon=True).start()

        bus.on("ovos.pip.install", on_request)
        job = inst.install("ovos-skill-news", bus=bus, check_pypi=False)
        deadline = time.time() + 10
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)

        assert job.state == "done", (
            f"a failure from one environment buried a success from another: "
            f"{job.lines[-3:]}"
        )

    def test_a_broadcast_nobody_can_do_is_bounded_not_left_to_the_timeout(
            self, monkeypatch):
        """The case the suite had no test for, and so kept shipping wrong.

        Every existing test of this path plants a fictional second peer that
        succeeds after the failure. On a single-container device ovos-core is
        the only responder, and the ordinary "the install failed" answer --
        an unreachable constraints file, a package that resolves nowhere -- is
        `error in pip subprocess` from the one service there is. Nothing can
        settle that job, so it held the panel's single install slot for the
        whole fifteen minutes with the answer already in hand, and every other
        install in the UI raised `InstallerBusy` behind it.
        """
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 30)
        monkeypatch.setattr(installer, "INCONCLUSIVE_SETTLE", 1.0)
        bus = FakeBus()
        bus.on("ovos.pip.install", lambda m: bus.emit(
            m.reply("ovos.pip.install.failed",
                    {"error": "error in pip subprocess"})))

        started = time.time()
        job = inst.install("ovos-skill-news", bus=bus, check_pypi=False)
        deadline = started + 20
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)
        elapsed = time.time() - started

        assert job.state == "error"
        assert elapsed < 5, (
            f"the only answer there was arrived at once and the job still "
            f"held the install slot for {elapsed:.1f}s"
        )
        # and it must not contradict itself on the way out
        lines = "\n".join(job.lines)
        assert "No installer service took it on." not in lines, (
            f"reported that nobody took it on, above the failure they sent: {job.lines}"
        )

    def test_each_failure_re_arms_the_window_for_the_service_behind_it(
            self, monkeypatch):
        """A single window measured from the first failure is spent by the queue.

        An all-in-one device answers one broadcast from ovos-core, ovos-audio,
        the listener, ovos-gui and PHAL, all serialised on the same pip lock.
        Each failure means one more of them has let go of it and the next has
        started, so the window has to restart there -- otherwise the figure
        does not mean "long enough to finish an install", it means "long enough
        for the whole queue", and the last service can never win however fast
        it is.
        """
        import threading
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 30)
        monkeypatch.setattr(installer, "INCONCLUSIVE_SETTLE", 1.0)
        bus = FakeBus()

        def on_request(message):
            def queued():
                # the first two give up in turn, each releasing the lock...
                bus.emit(message.reply("ovos.pip.install.failed",
                                       {"error": "error in pip subprocess"}))
                time.sleep(0.8)
                bus.emit(message.reply("ovos.pip.install.failed",
                                       {"error": "error in pip subprocess"}))
                time.sleep(0.7)   # ...and the third, which started last, finishes
                bus.emit(message.reply("ovos.pip.install.complete"))

            threading.Thread(target=queued, daemon=True).start()

        bus.on("ovos.pip.install", on_request)
        job = inst.install("ovos-skill-news", bus=bus, check_pypi=False)
        deadline = time.time() + 20
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)

        assert job.state == "done", (
            f"the window was spent by the services ahead of the one that "
            f"succeeded: {job.lines[-4:]}"
        )

    def test_a_broadcast_removal_nobody_answers_is_bounded_by_the_settle_window(
            self, monkeypatch):
        """The mechanism itself had no test -- only its consequences did.

        Deleting the whole `REMOVE_SETTLE` deadline and falling back to
        `JOB_TIMEOUT` left every removal test green, because they all poll to a
        ceiling and assert the final state. The bound is the point: without it
        the panel holds its single install slot for fifteen minutes on a
        removal nobody is going to answer.
        """
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 30)
        monkeypatch.setattr(installer, "REMOVE_SETTLE", 1.0)
        bus = FakeBus()

        started = time.time()
        job = inst.uninstall("ovos-tts-plugin-server", bus=bus)
        deadline = started + 20
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)
        elapsed = time.time() - started

        assert elapsed < 5, (
            f"the removal waited {elapsed:.1f}s, so it was bounded by the job "
            "timeout rather than by the settle window"
        )

    def test_a_removal_that_fails_is_not_reassured_in_the_same_breath(
            self, monkeypatch):
        """The twin of the silence case, and it was the unguarded one.

        A failure settles a broadcast removal -- immediately, which is the
        other half of the same rule -- so the reassurance must not print above
        it. Keying that on `settled` rather than on the failures in hand also
        left a window where the two disagreed.
        """
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "REMOVE_SETTLE", 10.0)
        bus = FakeBus()
        bus.on("ovos.pip.uninstall", lambda m: bus.emit(
            m.reply("ovos.pip.uninstall.failed",
                    {"error": "error in pip subprocess"})))

        started = time.time()
        job = inst.uninstall("ovos-tts-plugin-server", bus=bus)
        deadline = started + 20
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)
        elapsed = time.time() - started

        assert job.state == "error"
        assert elapsed < 5, (
            f"a failure is the answer for a removal; it waited {elapsed:.1f}s"
        )
        assert "No installer reported a problem removing it." not in "\n".join(job.lines), (
            f"reassured the reader directly above the failure: {job.lines}"
        )

    def test_a_targeted_install_that_fails_answers_at_once(self, monkeypatch):
        """One responder, so its failure is the whole answer.

        There was no test anywhere for a targeted install that fails. Without
        the `service is not None` arm it would sit out the inconclusive window
        holding the single install slot, waiting for a second opinion that
        cannot arrive.
        """
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 30)
        monkeypatch.setattr(installer, "INCONCLUSIVE_SETTLE", 10.0)
        monkeypatch.setattr(installer, "_install_route_for",
                            lambda package: ("tts", "ovos_audio"))
        bus = FakeBus()
        bus.on("ovos.pip.install.ovos_audio", lambda m: bus.emit(
            m.reply("ovos.pip.install.failed",
                    {"error": "error in pip subprocess"})))

        started = time.time()
        job = inst.install("ovos-tts-plugin-server", bus=bus, check_pypi=False)
        deadline = started + 20
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)
        elapsed = time.time() - started

        assert job.state == "error"
        assert elapsed < 5, (
            f"waited {elapsed:.1f}s for a second opinion that cannot arrive"
        )

    def test_a_stale_reply_from_a_finished_job_cannot_settle_the_next_one(
            self, monkeypatch):
        """The whole defence against cross-job crosstalk, and it had no test.

        Every job listens on the same base reply topics, so the only thing
        keeping a late `.complete` from a previous job out of the current one
        is the per-job nonce in the message context. Mutating that check to
        accept everything left the entire installer corpus green. The window
        it has to be right in is not small either: an inconclusive failure
        keeps a broadcast waiting minutes with its handlers registered, which
        is exactly when a straggler from the last job arrives.
        """
        import time

        from ovos_bus_client.message import Message
        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 3)
        bus = FakeBus()

        def stale_success(message):
            # someone else's job id, on the topic this job is listening to
            bus.emit(Message("ovos.pip.install.complete", {},
                             {"webui_job": "a-previous-job"}))

        bus.on("ovos.pip.install", stale_success)

        started = time.time()
        job = inst.install("ovos-skill-news", bus=bus, check_pypi=False)
        deadline = started + 10
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)

        assert job.state == "error", (
            f"a reply belonging to another job completed this one: {job.lines}"
        )
        assert time.time() - started >= 2.5, (
            "the job ended early, so the stale reply was acted on"
        )

    def test_a_removal_the_window_outlasts_says_what_it_saw(self, monkeypatch):
        """The positive case of the line the last round only tested negatively.

        Someone answers, nobody reports a problem, and the window closes. The
        panel cannot know the plugin is gone -- ovos-core answers a removal it
        could not do with silence -- so it says what it observed.
        """
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "REMOVE_SETTLE", 1.0)
        bus = FakeBus()
        bus.on("ovos.pip.uninstall", lambda m: bus.emit(
            m.reply("ovos.pip.uninstall.complete")))

        job = inst.uninstall("ovos-tts-plugin-server", bus=bus)
        deadline = time.time() + 10
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)

        assert job.state == "done"
        assert "No installer reported a problem removing it." in "\n".join(job.lines), (
            f"claimed the plugin is gone on the strength of a silence: {job.lines}"
        )

    def test_a_removal_nobody_answers_is_not_reassured_and_then_failed(
            self, monkeypatch):
        """Two lines that cannot both be true, one directly above the other."""
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "REMOVE_SETTLE", 1.0)
        bus = FakeBus()

        job = inst.uninstall("ovos-tts-plugin-server", bus=bus)
        deadline = time.time() + 10
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)

        assert job.state == "error"
        lines = "\n".join(job.lines)
        assert "No installer reported a problem removing it." not in lines, (
            f"reassured the reader one line above telling them nobody "
            f"replied: {job.lines}"
        )

    def test_a_targeted_removal_settles_on_its_one_reply(self, monkeypatch):
        """Only a broadcast removal has to wait out the settle window.

        A targeted request is answered by exactly one service, so its reply is
        the whole answer. Waiting `REMOVE_SETTLE` for a second opinion that
        cannot come just holds the install slot.
        """
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "REMOVE_SETTLE", 10.0)
        monkeypatch.setattr(installer, "_install_route_for",
                            lambda package: ("tts", "ovos_audio"))
        bus = FakeBus()
        bus.on("ovos.pip.uninstall.ovos_audio", lambda m: bus.emit(
            m.reply("ovos.pip.uninstall.complete")))

        started = time.time()
        job = inst.uninstall("ovos-tts-plugin-server", bus=bus)
        deadline = started + 20
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)
        elapsed = time.time() - started

        assert job.state == "done", job.lines[-3:]
        assert elapsed < 5, (
            f"a targeted removal waited {elapsed:.1f}s for a second opinion "
            "that cannot arrive"
        )

    def test_a_broadcast_that_only_gets_unknown_errors_still_fails(self, monkeypatch):
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 2)
        bus = FakeBus()
        bus.on("ovos.pip.install", lambda m: bus.emit(
            m.reply("ovos.pip.install.failed",
                    {"error": "something nobody has seen before"})))

        job = inst.install("ovos-skill-news", bus=bus, check_pypi=False)
        deadline = time.time() + 10
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)

        assert job.state == "error"
        assert "something nobody has seen before" in "\n".join(job.lines)

    def test_an_inconclusive_failure_is_reported_while_the_job_still_waits(
            self, monkeypatch):
        """It cannot end the job, so it has to be visible instead.

        Otherwise a device where every service answers the same way shows
        nothing at all until the wait expires, and the reader cannot tell a
        slow install from a stuck one.
        """
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 2)
        bus = FakeBus()
        bus.on("ovos.pip.install", lambda m: bus.emit(
            m.reply("ovos.pip.install.failed",
                    {"error": "something nobody has seen before"})))

        job = inst.install("ovos-skill-news", bus=bus, check_pypi=False)
        # it must show up long before the job settles
        deadline = time.time() + 1.5
        while time.time() < deadline:
            if any("could not do it" in line for line in job.lines):
                break
            time.sleep(0.05)
        assert any("could not do it" in line for line in job.lines), (
            f"the failure was never shown: {job.lines}"
        )
        assert job.state == "running", (
            "an error this panel does not recognise must not settle a broadcast"
        )

    def test_pip_being_disabled_answers_for_every_installer_at_once(self, monkeypatch):
        """The stock device's answer, so it must not wait out the job timeout.

        `skills.installer` is absent from the config ovos-config ships, so
        `allow_pip` defaults to refusing, and both installers read that one
        global key. Every service therefore gives the same answer, and waiting
        for a different one wedges the panel's single install slot for the full
        timeout with nothing to show for it.
        """
        import time

        from ovos_utils.fakebus import FakeBus

        inst, installer = self._job(monkeypatch)
        monkeypatch.setattr(installer, "JOB_TIMEOUT", 30)
        bus = FakeBus()
        bus.on("ovos.pip.install", lambda m: bus.emit(
            m.reply("ovos.pip.install.failed",
                    {"error": "pip disabled in mycroft.conf"})))

        started = time.time()
        job = inst.install("ovos-skill-news", bus=bus, check_pypi=False)
        deadline = started + 10
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)
        elapsed = time.time() - started

        assert job.state == "error"
        assert elapsed < 2, f"a device-wide refusal waited {elapsed:.1f}s"
        assert "disabled" in "\n".join(job.lines)

    def test_removing_waits_for_a_failure_instead_of_the_first_success(self, monkeypatch):
        """`uv pip uninstall` exits 0 for a package it never had.

        So every service that does not hold the plugin reports success at once,
        while the one that does is still working. Settling on that would report
        a removal as done while the plugin is still installed -- and still there
        after the owning service fails.
        """
        import threading
        import time

        from ovos_utils.fakebus import FakeBus

        inst, _installer = self._job(monkeypatch)
        bus = FakeBus()

        def on_request(message):
            # the services that never had it answer immediately...
            bus.emit(message.reply("ovos.pip.uninstall.complete"))

            def owner_fails():
                time.sleep(0.3)   # ...the one that has it fails a moment later
                bus.emit(message.reply("ovos.pip.uninstall.failed",
                                       {"error": "error in pip subprocess"}))

            threading.Thread(target=owner_fails, daemon=True).start()

        bus.on("ovos.pip.uninstall", on_request)
        job = inst.uninstall("ovos-skill-news", bus=bus)
        deadline = time.time() + 10
        while job.state == "running" and time.time() < deadline:
            time.sleep(0.05)

        assert job.state == "error", (
            f"a removal that failed was reported as done: {job.lines[-3:]}"
        )


class TestDetectedLocationIsReportedHonestly:
    """The detected location often does not win, and the page has to say so.

    The plugin writes the web cache, which ovos-config merges second from the
    bottom: the distribution config, `/etc/mycroft`, every XDG config and the
    runtime patch layer all outrank it. Reporting a plain success when the
    device will keep using a different location is the failure this page is
    supposed to have stopped making.
    """

    @staticmethod
    def _bus_answering(location):
        from ovos_utils.fakebus import FakeBus

        bus = FakeBus()
        bus.on("ovos.ipgeo.update", lambda m: bus.emit(
            m.response(data={"location": location})))
        return bus

    def test_a_location_nothing_outranks_is_reported_as_stored(self, monkeypatch):
        from ovos_webui import system

        monkeypatch.setattr(system, "_detected_location_fate", lambda: None)
        result = system.detect_location(self._bus_answering({"city": {"name": "Lisbon"}}))
        assert result["ok"] is True
        assert not result.get("overridden")

    def test_a_location_outranked_by_any_layer_says_so(self, monkeypatch):
        from ovos_webui import system

        monkeypatch.setattr(system, "_detected_location_fate", lambda: "overridden")
        result = system.detect_location(self._bus_answering({"city": {"name": "Lisbon"}}))
        assert result["ok"] is True
        assert result.get("overridden") is True, (
            "the device keeps a different location and the page did not say so"
        )

    def test_the_lookup_is_given_longer_than_an_ordinary_round_trip(self,
                                                                    monkeypatch):
        """It is a network call, not a local query.

        The plugin fetches the public IP through a `requests.get` with no
        timeout of its own, then queries a geolocation API with a five-second
        timeout, then writes the web cache behind the cross-process config
        lock. Waiting only as long as a status query reports the plugin missing
        on a merely slow network -- while the write goes ahead anyway.
        """
        from ovos_utils.fakebus import FakeBus

        from ovos_webui import buswait, system

        seen = {}

        def capture(bus, message, timeout=None, **kwargs):
            seen["timeout"] = timeout
            return None

        monkeypatch.setattr(buswait, "wait_for_response", capture)
        system.detect_location(FakeBus())
        assert seen["timeout"] > system.DEFAULT_TIMEOUT + 5.0, (
            "the panel gives up before the plugin's own API call can time out"
        )

    @staticmethod
    def _layers(monkeypatch, constraints, distribution=None, system_conf=None,
                xdg=None, patch=None, tmp_path=None):
        """Stand in for the config stack, with the XDG layers as real files.

        The XDG layers are read off disk, not out of the layer objects, so a
        test that handed over a dict would not exercise the code that runs.
        """
        import json

        from ovos_config.config import Configuration
        from ovos_config.models import LocalConf

        class _Layer(dict):
            path = None

            def reload(self):
                pass

        xdg_layers = []
        for index, contents in enumerate(xdg or []):
            path = tmp_path / f"xdg{index}.conf"
            path.write_text(json.dumps(contents), encoding="utf-8")
            xdg_layers.append(LocalConf(str(path)))

        monkeypatch.setattr(Configuration, "get_system_constraints",
                            staticmethod(lambda: constraints), raising=False)
        monkeypatch.setattr(Configuration, "distribution",
                            _Layer(distribution or {}), raising=False)
        monkeypatch.setattr(Configuration, "system",
                            _Layer(system_conf or {}), raising=False)
        monkeypatch.setattr(Configuration, "xdg_configs", xdg_layers,
                            raising=False)
        monkeypatch.setattr(Configuration, "_Configuration__patch",
                            _Layer(patch or {}), raising=False)

    def test_a_system_wide_location_counts_not_just_the_user_file(self, monkeypatch):
        """`/etc/mycroft` must not be the layer that is missed."""
        from ovos_webui import system

        self._layers(monkeypatch, {},
                     system_conf={"location": {"city": {"name": "SysWideCity"}}})
        assert system._detected_location_fate() == "overridden"

    def test_a_distribution_image_location_counts_too(self, monkeypatch):
        """The layer a distribution image actually uses, tested positively.

        The test above names this case in its docstring and then sets the
        system layer, so dropping the distribution layer from the check left
        the suite green. The only other test that populates it asserts the
        result is `None`, which passes just as well when the layer is never
        read at all.
        """
        from ovos_webui import system

        self._layers(monkeypatch, {},
                     distribution={"location": {"city": {"name": "DistroCity"}}})
        assert system._detected_location_fate() == "overridden"

    def test_no_location_anywhere_above_the_web_cache_is_not_overridden(
            self, monkeypatch, tmp_path):
        from ovos_webui import system

        self._layers(monkeypatch, {}, xdg=[{}, {}], tmp_path=tmp_path)
        assert system._detected_location_fate() is None

    def test_a_device_that_drops_the_web_cache_is_not_described_as_overridden(
            self, monkeypatch):
        """`disable_remote_config` means the detected location never arrives.

        Nothing is overriding it, so telling the reader to clear a location on
        the Settings page sends them to fix a layer that is not the problem.
        """
        from ovos_webui import system

        self._layers(monkeypatch, {"disable_remote_config": True})
        assert system._detected_location_fate() == "ignored"

    def test_protecting_location_in_the_remote_layer_is_the_same_answer(
            self, monkeypatch):
        """`protected_keys.remote` strips named keys out of the web cache.

        Nested entries are split on `:`, the syntax the shipped `mycroft.conf`
        documents and uses (`listener:channels`). Reading them as dotted paths
        matches nothing any device actually contains, so the panel would report
        a stored location that was thrown away on the way in.
        """
        from ovos_webui import system

        self._layers(monkeypatch,
                     {"protected_keys": {"remote": ["location:city"]}})
        assert system._detected_location_fate() == "ignored"

    def test_a_system_location_still_overrides_under_the_user_protections(
            self, monkeypatch):
        """The system config is exempt from `protected_keys.user`.

        It is one of the two layers `filter_and_merge` does not treat as a user
        config, so a `location` there survives the strip and still wins.
        """
        from ovos_webui import system

        self._layers(monkeypatch,
                     {"protected_keys": {"user": ["location"]}},
                     system_conf={"location": {"city": {"name": "SysCity"}}})
        assert system._detected_location_fate() == "overridden"

    def test_a_location_protected_at_user_level_cannot_override_either(
            self, monkeypatch, tmp_path):
        """`protected_keys.user` takes the key out of the layers above."""
        from ovos_webui import system

        self._layers(monkeypatch,
                     {"protected_keys": {"user": ["location"]}},
                     xdg=[{"location": {"city": {"name": "StrippedCity"}}}],
                     tmp_path=tmp_path)
        assert system._detected_location_fate() is None

    def test_the_distribution_layer_is_stripped_by_the_user_protections(
            self, monkeypatch):
        """`filter_and_merge` classifies it as a user config, not a system one.

        Only the default and the system config are exempt, so
        `protected_keys.user` takes a `location` out of the distribution layer
        the same way it does out of an XDG file, and it cannot override.
        """
        from ovos_webui import system

        self._layers(monkeypatch,
                     {"protected_keys": {"user": ["location"]}},
                     distribution={"location": {"city": {"name": "DistroCity"}}})
        assert system._detected_location_fate() is None

    def test_clearing_the_location_the_page_told_you_to_clear_ends_the_message(
            self, monkeypatch, tmp_path):
        """Otherwise the advice is a loop the reader cannot get out of.

        `LocalConf.reload` merges a file in and never clears, so a layer object
        that has once seen a `location` keeps answering with it for the life of
        the process. The reader clears it exactly as told, presses Detect
        again, and is told the same thing until the web-ui restarts.
        """
        import json

        from ovos_config.config import Configuration
        from ovos_config.models import LocalConf

        from ovos_webui import system

        path = tmp_path / "user.conf"
        path.write_text(json.dumps({"location": {"city": {"name": "OldCity"}}}),
                        encoding="utf-8")

        class _Layer(dict):
            path = None

            def reload(self):
                pass

        monkeypatch.setattr(Configuration, "get_system_constraints",
                            staticmethod(lambda: {}), raising=False)
        monkeypatch.setattr(Configuration, "distribution", _Layer(), raising=False)
        monkeypatch.setattr(Configuration, "system", _Layer(), raising=False)
        monkeypatch.setattr(Configuration, "xdg_configs",
                            [LocalConf(str(path))], raising=False)
        monkeypatch.setattr(Configuration, "_Configuration__patch", _Layer(),
                            raising=False)

        assert system._detected_location_fate() == "overridden"
        path.write_text(json.dumps({}), encoding="utf-8")
        assert system._detected_location_fate() is None, (
            "the reader cleared the location and is still told it wins"
        )

    def test_disabling_user_config_drops_the_web_cache_along_with_the_rest(
            self, monkeypatch, tmp_path):
        """The constraint that reads backwards, and the one this got wrong.

        `filter_and_merge` classifies every config that is not the default or
        the system one as a *user* config, and `RemoteConf`'s path is the web
        cache -- so `disable_user_config` drops the layer the plugin just
        wrote, before the remote branch is ever reached. Answering "nothing
        above is overriding it" is then the same lie as reporting a plain
        success: the device will not use the detected location either way.
        """
        from ovos_webui import system

        self._layers(monkeypatch, {"disable_user_config": True},
                     xdg=[{"location": {"city": {"name": "IgnoredCity"}}}],
                     tmp_path=tmp_path)
        assert system._detected_location_fate() == "ignored"

    def test_the_runtime_patch_layer_outranks_the_web_cache_too(self, monkeypatch):
        """It is the last layer in the merge, so a `location` there wins."""
        from ovos_webui import system

        self._layers(monkeypatch, {},
                     patch={"location": {"city": {"name": "PatchedCity"}}})
        assert system._detected_location_fate() == "overridden"

    def test_the_conclusive_errors_are_the_ones_the_installers_actually_send(self):
        """Pinned against the real vocabulary, not against a guess.

        A broadcast stops waiting on a failure that answers for the whole
        device. That decision reads `ovos.pip.install.failed`'s `error`, which
        both installers document as a fixed `InstallError` vocabulary. If a
        value is reworded upstream and this is not updated, an install on a
        device with pip disabled silently goes back to waiting out the job
        timeout -- so the set is checked against the enum itself.
        """
        from ovos_utils.skill_installer import InstallError

        from ovos_webui.installer import (
            _CONCLUSIVE_ERRORS,
            _ENVIRONMENT_ERROR,
            _is_conclusive,
        )

        known = {member.value for member in InstallError}
        assert _CONCLUSIVE_ERRORS | {_ENVIRONMENT_ERROR} == known, (
            "the InstallError vocabulary has changed upstream; a value that is "
            "no longer matched turns a refusal back into a fifteen-minute wait"
        )

        # Pinned as literals as well as against the enum. ovos-core does not
        # import that enum -- it carries its own copy, and on a stock
        # single-container device its copy is the one that answers. The panel
        # cannot import it to compare, since ovos-core is not a dependency, and
        # a check guarded by ImportError would pass without asserting anything
        # on every machine there is. So the values are written out here: a
        # reword on either side fails this test, rather than quietly turning a
        # refusal back into a long wait.
        assert known == {
            "pip disabled in mycroft.conf",
            "error in pip subprocess",
            "skill url validation failed",
            "no packages to install",
        }, (
            "the vocabulary has moved; check ovos-core's own copy of "
            "InstallError as well as ovos-utils', since the panel matches "
            "values sent by both"
        )
        assert _is_conclusive(InstallError.DISABLED.value)
        assert not _is_conclusive(InstallError.PIP_ERROR.value)
        # an unfamiliar error must not be guessed either way
        assert not _is_conclusive("something nobody has seen before")
        assert not _is_conclusive("")
        assert not _is_conclusive(None)


def test_the_nonce_survives_the_real_installer(monkeypatch):
    """Against the shipped ServiceInstaller, not a hand-rolled reply.

    Every other test here plays the installer's part itself, so it certifies
    the reply shape it already assumed. This stands the real peer up: if
    `ServiceInstaller` ever built a fresh Message instead of replying to ours,
    the correlation nonce would be gone and every job would time out.
    """
    import time

    from ovos_utils.fakebus import FakeBus
    from ovos_utils.skill_installer import ServiceInstaller

    from ovos_webui import installer as inst_mod
    from ovos_webui.installer import Installer

    bus = FakeBus()
    peer = ServiceInstaller(bus, service_name="ovos_audio")
    assert peer

    monkeypatch.setattr(inst_mod, "_install_route_for",
                        lambda package: ("tts", "ovos_audio"))
    monkeypatch.setattr(inst_mod, "JOB_TIMEOUT", 20)

    inst = Installer()
    monkeypatch.setattr(inst, "_channel_spec", lambda package, **kw: package)
    # `allow_pip` defaults to refusing, so the real peer answers at once with
    # a conclusive refusal rather than running pip. That refusal arriving --
    # quickly, and recognised -- is the proof: an uncorrelated reply would be
    # ignored and the job would sit until JOB_TIMEOUT instead.
    started = time.time()
    job = inst.install("ovos-tts-plugin-server", bus=bus, check_pypi=False)
    while job.state == "running" and time.time() - started < 25:
        time.sleep(0.05)
    took = time.time() - started

    assert job.state == "error", f"expected a refusal, got {job.state}"
    assert took < 5, (
        f"waited {took:.1f}s, so the real installer's reply never correlated "
        "back to the job and the wait timed out instead"
    )
    assert any("pip" in line for line in job.lines), (
        f"the refusal never reached the log: {job.lines}"
    )
