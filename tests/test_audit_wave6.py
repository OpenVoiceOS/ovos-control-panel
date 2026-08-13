"""Regression test for audit wave-6: buswait abandoned-count reconciliation.

A call that only MISSED its deadline but then finishes must not stay counted as
an abandoned (never-returning) permit — its release reconciles the count. A call
whose worker truly never returns stays counted.
"""
import threading
import time

from ovos_webui import buswait


def test_a_slow_call_that_finishes_after_timeout_is_not_left_abandoned():
    buswait.GATE.reset_for_tests()

    def slow():
        time.sleep(0.3)   # finishes shortly AFTER the deadline
        return "done"

    assert buswait.call(slow, timeout=0.05, default="TIMEDOUT") == "TIMEDOUT"
    time.sleep(0.5)       # let the worker finish and release its permit
    assert buswait.GATE.abandoned == 0
    assert buswait.GATE.free == buswait.MAX_INFLIGHT


def test_a_truly_stuck_call_stays_abandoned():
    buswait.GATE.reset_for_tests()
    block = threading.Event()  # never set within the assertion window

    def stuck():
        block.wait()
        return "x"

    assert buswait.call(stuck, timeout=0.05, default="TIMEDOUT") == "TIMEDOUT"
    time.sleep(0.2)
    assert buswait.GATE.abandoned == 1   # its permit really has not come back
    block.set()  # cleanup: let the daemon thread exit and release
