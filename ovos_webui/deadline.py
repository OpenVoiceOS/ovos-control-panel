"""Run a blocking third-party call with a wall-clock deadline.

Plugin calls the web-ui makes into installed plugins — a translation backend, an
LLM-backed persona solver — can hang on a network read with no timeout of their
own. A hung call in a request thread pins a FastAPI worker forever; enough of
them and the whole UI stops answering (worker-pool starvation) with no error.

``run_with_deadline`` runs the call in a throwaway daemon thread and gives up
after ``timeout`` seconds. Unlike :func:`ovos_webui.buswait.call` it keeps no
shared permit pool or circuit breaker: a stalling *plugin* must never trip the
*message-bus* breaker or consume a bus permit. The abandoned thread is a daemon,
so it cannot keep the process alive.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from ovos_utils.log import LOG


class DeadlineExceeded(RuntimeError):
    """Raised when a guarded call does not finish within its deadline."""


class GuardPoolExhausted(RuntimeError):
    """Raised when too many guarded calls are already in flight."""


#: A guarded call that times out leaves its thread running (Python cannot cancel
#: it), so a hung plugin flooded with requests would grow threads without bound.
#: Cap the number of concurrent guard threads: a permit is taken before the
#: thread starts and only returned when it truly finishes, so hung threads keep
#: their permits and, once the pool is full, new calls are refused instead of
#: amplified into thread/FD/memory exhaustion.
MAX_GUARD_THREADS = 8
_slots = threading.Semaphore(MAX_GUARD_THREADS)


def run_with_deadline(func: Callable[[], Any], timeout: float,
                      what: str = "the plugin") -> Any:
    """Return ``func()``, or raise if it overruns ``timeout`` or itself raises.

    A ``DeadlineExceeded`` means the call is still running (abandoned); a
    ``GuardPoolExhausted`` means too many calls are already stuck; any other
    exception is the one ``func`` raised, re-raised for the caller to handle.
    """
    if not _slots.acquire(blocking=False):
        LOG.warning(f"guard pool exhausted; refusing to run {what}")
        raise GuardPoolExhausted(
            f"too many plugin calls are already in flight; refusing {what}")
    box: dict[str, Any] = {}
    done = threading.Event()

    def runner() -> None:
        try:
            box["value"] = func()
        except Exception as err:  # noqa: BLE001 - handed back through the box
            box["error"] = err
        finally:
            done.set()
            # Release only when the call really finished — a thread still stuck
            # in a hung plugin keeps its permit, which is what bounds the pool.
            _slots.release()

    threading.Thread(target=runner, daemon=True,
                     name="ovos-webui-plugin").start()
    if not done.wait(timeout):
        LOG.warning(f"{what} did not respond within {timeout}s; giving up")
        raise DeadlineExceeded(f"{what} did not respond within {timeout}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")
