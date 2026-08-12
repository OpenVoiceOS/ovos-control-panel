"""Regression tests for round-1 review fixes that lacked direct coverage.

DI-2 skill-settings merge preserves the skill's own runtime keys; SEC-2 the
guarded-call pool is bounded so a hung plugin cannot be flooded into thread
exhaustion.
"""
import threading

import pytest


def test_skill_settings_save_preserves_runtime_keys(make_skill):
    # DI-2: settings.json is co-owned; the running skill writes runtime keys
    # (tokens, counters) the page never showed. Saving the page's snapshot must
    # merge over the on-disk file, not clobber it.
    from ovos_webui import skillsio

    make_skill("ovos-skill-demo.author", {"__oauth_token": "secret", "shown": 1})
    # the page only ever saw/edited "shown"
    skillsio.write_settings("ovos-skill-demo.author", {"shown": 2})
    after = skillsio.read_settings("ovos-skill-demo.author")
    assert after["shown"] == 2
    assert after["__oauth_token"] == "secret"  # runtime key survived the save


def test_guard_pool_refuses_when_full(monkeypatch):
    # SEC-2: a timed-out guard call leaves its thread running; once the pool is
    # full, new calls must be refused (GuardPoolExhausted), not spawn unbounded
    # threads.
    from ovos_webui import deadline

    monkeypatch.setattr(deadline, "_slots", threading.Semaphore(2))
    gate = threading.Event()
    try:
        # fill both permits with calls that time out but keep running (holding
        # their permit until released)
        for _ in range(2):
            with pytest.raises(deadline.DeadlineExceeded):
                deadline.run_with_deadline(lambda: gate.wait(30), 0.05)
        # pool is now exhausted -> the next call is refused immediately
        with pytest.raises(deadline.GuardPoolExhausted):
            deadline.run_with_deadline(lambda: 1, 0.05)
    finally:
        gate.set()  # let the parked threads finish and return their permits


def test_guard_pool_recovers_after_calls_finish(monkeypatch):
    from ovos_webui import deadline

    monkeypatch.setattr(deadline, "_slots", threading.Semaphore(1))
    # a call that completes returns its permit, so the pool is reusable
    assert deadline.run_with_deadline(lambda: 7, 1.0) == 7
    assert deadline.run_with_deadline(lambda: 8, 1.0) == 8


@pytest.mark.parametrize("text", ["a\nb\n", "a\nb", "a\n\n", "", "a",
                                  "l1\r\nl2\r\n", "x\n\n\n"])
def test_splitlines_matches_stdlib_for_real_newlines(text):
    # DI-5: only real newlines split, and a trailing newline must NOT add a
    # spurious empty line (would grow the override by a line every save).
    from ovos_webui.translate import _splitlines

    assert _splitlines(text) == text.splitlines()


def test_splitlines_keeps_unicode_line_separators_intact():
    # the whole point: a vertical tab / U+2028 inside a line must not split
    from ovos_webui.translate import _splitlines

    assert _splitlines("hello\x0bworld") == ["hello\x0bworld"]
    assert _splitlines("a b") == ["a b"]


def test_machine_translate_stops_hammering_a_stalled_backend(monkeypatch):
    # V2: a hung backend must be called at most once per request, not once per
    # line — otherwise one ordinary multi-line request drains the guard pool.
    import time
    from ovos_webui import translate

    calls = {"n": 0}

    class Hang:
        def translate(self, line, target, source):
            calls["n"] += 1
            time.sleep(30)  # never returns in time

    monkeypatch.setattr(translate, "translation_plugins",
                        lambda: ["ovos-translate-plugin-x"])
    monkeypatch.setattr(translate, "_load_translator", lambda p: Hang())
    monkeypatch.setattr(translate, "LINE_TIMEOUT", 0.1)

    r = translate.machine_translate(["a", "b", "c", "d", "e", "f", "g"], "en",
                                    "pt-pt", "ovos-translate-plugin-x")
    # a fully-hung backend is tried at most a few times (MAX_TIMEOUTS=3), then
    # the rest of the batch fails fast — bounding guard-pool permits used per
    # request instead of one permit per line for all 7 lines.
    assert calls["n"] == 3
    assert all(line["machine"] is False for line in r["lines"])
