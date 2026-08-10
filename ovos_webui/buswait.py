"""Talk to the message bus without ever blocking a request, and without
leaking a thread for every call that does not come back.

``MessageBusClient._send`` waits on ``connected_event`` with no limit once the
client has been started (ovos-bus-client ``client/client.py``). A call that
goes into that wait never returns. So two things have to be true at once:

1. a request must get an answer even when the bus is gone, and
2. the number of threads stuck in that wait must be bounded by a constant,
   whatever the number of requests.

Giving each call its own thread satisfies the first and breaks the second: a
page that polls the dashboard would add stuck threads for as long as the bus
stays down, until the device cannot start another thread.

So a fixed number of permits is handed out. A call that cannot get a permit
fails at once instead of queueing, and a call that hangs keeps its permit for
good, which is exactly what bounds the damage. On top of that a short lived
circuit breaker remembers that the bus did not answer, so the calls that follow
fail immediately instead of each waiting out the full timeout.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from ovos_utils.log import LOG

#: How long any single bus call may take.
DEFAULT_TIMEOUT = 3.0

#: The largest number of threads this module may ever have in flight. A thread
#: stuck inside the bus client keeps its permit, so this is also the largest
#: number of threads that can ever be stuck.
MAX_INFLIGHT = 4

#: After a call gives up, treat the bus as down for this long and answer at
#: once instead of waiting again.
BREAKER_TTL = 10.0


class BusUnavailable(RuntimeError):
    """Raised when there is no capacity left to talk to the bus."""


class _Gate:
    """The permits and the circuit breaker, kept together."""

    def __init__(self, permits: int = MAX_INFLIGHT, ttl: float = BREAKER_TTL):
        self._semaphore = threading.BoundedSemaphore(permits)
        self._permits = permits
        self._ttl = ttl
        self._open_until = 0.0
        self._lock = threading.Lock()
        self._abandoned = 0

    # ── circuit breaker ──────────────────────────────────────────────────────
    def is_open(self) -> bool:
        """True while the bus is believed to be down."""
        with self._lock:
            return time.monotonic() < self._open_until

    def trip(self) -> None:
        with self._lock:
            self._open_until = time.monotonic() + self._ttl

    def reset(self) -> None:
        with self._lock:
            self._open_until = 0.0

    # ── permits ──────────────────────────────────────────────────────────────
    def acquire(self) -> bool:
        return self._semaphore.acquire(blocking=False)

    def release(self) -> None:
        try:
            self._semaphore.release()
        except ValueError:  # pragma: no cover - released more than acquired
            pass

    def abandon(self) -> None:
        """Record a permit that will never come back."""
        with self._lock:
            self._abandoned += 1

    @property
    def abandoned(self) -> int:
        return self._abandoned

    @property
    def free(self) -> int:
        """Permits still available. Only for tests and for reporting."""
        return self._permits - self._abandoned

    def reset_for_tests(self) -> None:
        self._semaphore = threading.BoundedSemaphore(self._permits)
        self._open_until = 0.0
        self._abandoned = 0


GATE = _Gate()


def is_connected(bus: Any) -> bool:
    """Return True when the bus client says it is connected.

    A test double has no ``connected_event`` and is always usable.
    """
    if bus is None:
        return False
    event = getattr(bus, "connected_event", None)
    if event is not None and hasattr(event, "is_set"):
        return bool(event.is_set())
    return True


def call(func: Callable[[], Any], timeout: float = DEFAULT_TIMEOUT,
         default: Any = None) -> Any:
    """Run ``func`` against the bus, with a deadline and a bounded cost.

    Returns the value of ``func``, or ``default`` when the bus did not answer,
    when there was no capacity left, or when the breaker is open.
    """
    if GATE.is_open():
        # The bus did not answer a moment ago. Do not spend another timeout,
        # and do not spend another permit, finding that out again.
        return default

    if not GATE.acquire():
        LOG.warning("no capacity left to talk to the message bus; "
                    f"{GATE.abandoned} call(s) never came back")
        GATE.trip()
        return default

    box: dict[str, Any] = {}
    done = threading.Event()
    finished = threading.Event()

    def runner() -> None:
        try:
            box["value"] = func()
        except Exception as err:  # noqa: BLE001 - reported through the box
            box["error"] = err
        finally:
            done.set()
            # The permit is only given back by a call that really finished. A
            # call still stuck in the bus client never reaches this line, and
            # that is what keeps the number of stuck threads bounded.
            finished.set()
            GATE.release()

    thread = threading.Thread(target=runner, daemon=True, name="ovos-webui-bus")
    thread.start()

    if not done.wait(timeout):
        LOG.warning(f"a message bus call did not finish in {timeout}s; giving up")
        GATE.trip()
        if not finished.is_set():
            GATE.abandon()
        return default

    if "error" in box:
        LOG.warning(f"a message bus call failed: {box['error']}")
        GATE.trip()
        return default

    GATE.reset()
    return box.get("value", default)


def emit(bus: Any, message: Any, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Send ``message``. Return True when it went out inside the deadline."""
    if not is_connected(bus):
        return False
    sentinel = object()
    result = call(lambda: bus.emit(message) or True, timeout=timeout, default=sentinel)
    return result is not sentinel


def wait_for_response(bus: Any, message: Any, timeout: float = DEFAULT_TIMEOUT) -> Any:
    """Send ``message`` and wait for its reply, with a hard deadline.

    The client's own timeout only covers the waiting, not the emit that comes
    first, so the whole call is wrapped.
    """
    if not is_connected(bus):
        return None
    return call(lambda: bus.wait_for_response(message, timeout=timeout),
                timeout=timeout + 1.0, default=None)


def status() -> dict[str, Any]:
    """Report the state of the gate, for the dashboard and for tests."""
    return {"max_inflight": MAX_INFLIGHT, "abandoned": GATE.abandoned,
            "breaker_open": GATE.is_open()}
