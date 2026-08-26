"""Regression tests for the whole-app review fixes.

F1 config lost-update race, F2 unbounded plugin calls, F3 glob in resource
names, F4 tryit cross-talk between concurrent asks.
"""
import threading
import time

import pytest


# ── F1: configio.mutate serialises read-modify-write ─────────────────────────
def test_mutate_does_not_lose_concurrent_updates(monkeypatch):
    from ovos_webui import configio

    configio.write_user_config({})
    real_read = configio.read_user_config

    def slow_read():
        data = real_read()
        time.sleep(0.05)  # widen the window a lost-update race would exploit
        return data

    monkeypatch.setattr(configio, "read_user_config", slow_read)

    def worker(key):
        configio.mutate(lambda d: configio.set_in(d, [key], True))

    threads = [threading.Thread(target=worker, args=(k,)) for k in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = real_read()
    # Without the lock across read+write, one writer would clobber the other.
    assert final.get("a") is True
    assert final.get("b") is True


def test_mutate_change_may_return_a_replacement(monkeypatch):
    from ovos_webui import configio

    configio.write_user_config({"keep": 1})
    configio.mutate(lambda d: {"replaced": True})
    assert configio.read_user_config() == {"replaced": True}


# ── F2: run_with_deadline bounds a blocking plugin call ──────────────────────
def test_run_with_deadline_returns_value():
    from ovos_webui.deadline import run_with_deadline

    assert run_with_deadline(lambda: 42, 1.0) == 42


def test_run_with_deadline_times_out():
    from ovos_webui.deadline import run_with_deadline, DeadlineExceeded

    with pytest.raises(DeadlineExceeded):
        run_with_deadline(lambda: time.sleep(5), 0.1)


def test_run_with_deadline_propagates_the_call_error():
    from ovos_webui.deadline import run_with_deadline

    def boom():
        raise ValueError("plugin blew up")

    with pytest.raises(ValueError):
        run_with_deadline(boom, 1.0)


def test_machine_translate_bounds_a_hung_plugin(monkeypatch):
    from ovos_webui import translate

    class Hang:
        def translate(self, line, target, source):
            time.sleep(5)

    monkeypatch.setattr(translate, "translation_plugins",
                        lambda: ["ovos-translate-plugin-x"])
    monkeypatch.setattr(translate, "_load_translator", lambda p: Hang())
    monkeypatch.setattr(translate, "LINE_TIMEOUT", 0.1)

    r = translate.machine_translate(["hello"], "en", "pt-pt",
                                    "ovos-translate-plugin-x")
    # a hung backend leaves the line as a draft instead of parking the worker
    assert r["lines"][0]["machine"] is False


# ── F3: resource names reject glob metacharacters ────────────────────────────
@pytest.mark.parametrize("bad", ["*.dialog", "hi?.voc", "[a-z].word", "a*b.list"])
def test_resource_name_rejects_glob(bad):
    from ovos_webui import translate

    with pytest.raises(translate.TranslateError):
        translate.validate_resource_name(bad)


def test_resource_name_accepts_a_plain_name():
    from ovos_webui import translate

    assert translate.validate_resource_name("hello.dialog") == "hello.dialog"


# ── F4: tryit only harvests its own round trip ───────────────────────────────
def test_tryit_ignores_another_requests_reply(monkeypatch):
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import tryit

    monkeypatch.setattr(tryit, "SETTLE", 0.01)
    bus = FakeBus()

    def responder(m):
        ours = m.context.get("ident")
        # a foreign request's answer (different ident) plus our own
        bus.emit(Message("speak", {"utterance": "OTHER"}, {"ident": "someone-else"}))
        bus.emit(Message("speak", {"utterance": "MINE"}, {"ident": ours}))

    bus.on("recognizer_loop:utterance", responder)
    r = tryit.ask(bus, "what time is it", "en")
    assert r["spoken"] == ["MINE"]
    assert "OTHER" not in r["spoken"]
