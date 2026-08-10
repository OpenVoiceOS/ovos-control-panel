"""Talk to the message bus without ever blocking a request forever.

``MessageBusClient._send`` waits on ``connected_event`` with no limit once the
client has been started (ovos-bus-client ``client/client.py``). So a plain
``bus.emit`` from an HTTP handler can hang for as long as the bus stays down,
and ``wait_for_response`` hangs the same way because it emits first.

Checking ``connected_event`` before the call is not enough on its own: the bus
can drop between the check and the call. Every bus call therefore runs in a
throw-away daemon thread with a deadline. If the deadline passes, the request
gets an answer and the stuck thread dies with the process instead of holding a
worker.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from ovos_utils.log import LOG

#: How long any single bus call may take.
DEFAULT_TIMEOUT = 3.0


class BusTimeout(TimeoutError):
    """Raised when a bus call did not finish inside its deadline."""


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
    """Run ``func`` in a daemon thread and give up after ``timeout``.

    Returns the value of ``func``, or ``default`` when it did not finish or it
    raised. This is the only way this package touches the bus.
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def runner() -> None:
        try:
            box["value"] = func()
        except Exception as err:  # noqa: BLE001 - reported through the box
            box["error"] = err
        finally:
            done.set()

    thread = threading.Thread(target=runner, daemon=True, name="ovos-webui-bus")
    thread.start()
    if not done.wait(timeout):
        LOG.warning(f"a message bus call did not finish in {timeout}s; giving up")
        return default
    if "error" in box:
        LOG.warning(f"a message bus call failed: {box['error']}")
        return default
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
    first, so the whole call is wrapped. The outer deadline is a little longer
    than the inner one so the client can report a normal timeout itself.
    """
    if not is_connected(bus):
        return None
    return call(lambda: bus.wait_for_response(message, timeout=timeout),
                timeout=timeout + 1.0, default=None)
