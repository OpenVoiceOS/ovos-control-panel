"""Ask each OVOS service if it is alive and ready.

This uses only messages that OVOS already has. ``ovos_utils.process_utils``
gives every service a ``mycroft.<name>.is_alive`` and a
``mycroft.<name>.is_ready`` handler, and each one answers with
``{"status": true|false}``. No new message type is added here.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

#: The services that answer status messages, and the name each one registers.
#: ``skills`` and ``intents`` come from ovos-core, ``audio`` from ovos-audio or
#: ovos-media, ``voice`` from the listener, ``gui_service`` from ovos-gui and
#: ``PHAL`` from ovos-PHAL.
SERVICES: list[dict[str, str]] = [
    {"name": "skills", "label": "Skills", "hint": "Loads and runs your skills."},
    {"name": "intents", "label": "Intents", "hint": "Decides which skill answers you."},
    {"name": "audio", "label": "Audio", "hint": "Plays speech and media."},
    # ovos-simple-listener does not register a ProcessStatus at all, so a
    # device that uses it instead of ovos-dinkum-listener shows "no answer"
    # here even while it is listening perfectly well.
    {"name": "voice", "label": "Listener", "hint": "Hears the wake word and your speech."},
    {"name": "gui_service", "label": "GUI", "hint": "Drives the screen, if the device has one."},
    {"name": "PHAL", "label": "PHAL", "hint": "Talks to the hardware."},
]

DEFAULT_TIMEOUT = 1.0


def _message_cls():
    from ovos_bus_client.message import Message

    return Message


def probe(bus, name: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, bool | None]:
    """Ask one service if it is alive and ready.

    A value of ``None`` means the service did not answer in time. That is not
    the same as a ``False`` answer: ``None`` means the service is not running,
    ``False`` means it runs but is not finished starting.
    """
    from ovos_webui import buswait

    Message = _message_cls()
    result: dict[str, bool | None] = {"alive": None, "ready": None}
    for key in ("alive", "ready"):
        msg_type = f"mycroft.{name}.is_{key}"
        # ``wait_for_response`` emits first, and an emit on a dropped bus waits
        # with no limit. Go through the bounded wrapper instead.
        reply = buswait.wait_for_response(bus, Message(msg_type), timeout=timeout)
        if reply is not None:
            result[key] = bool(reply.data.get("status"))
        elif key == "alive":
            # Nothing answered, so the service is not running. Asking whether
            # it is ready would only wait for a second timeout.
            break
    return result


def bus_reachable(bus) -> bool:
    """Return True when the bus client believes it is connected."""
    from ovos_webui import buswait

    return buswait.is_connected(bus)


def snapshot(bus, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Return the health of the bus and of every known service."""
    reachable = bus_reachable(bus)
    services = []
    if reachable:
        # Every probe waits for a reply, so asking one service after another
        # would make the page take one timeout per service. Ask all of them at
        # the same time instead: the whole check then costs one timeout.
        with ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
            futures = [pool.submit(probe, bus, s["name"], timeout) for s in SERVICES]
            answers = []
            for future in futures:
                try:
                    answers.append(future.result(timeout=timeout * 2 + 4))
                except Exception:  # noqa: BLE001 - a stuck probe is "no answer"
                    answers.append({"alive": None, "ready": None})
    else:
        answers = [{"alive": None, "ready": None} for _ in SERVICES]
    for spec, answer in zip(SERVICES, answers):
        entry = dict(spec)
        entry.update(answer)
        entry["state"] = _state(entry)
        services.append(entry)
    return {
        "bus": {"reachable": reachable},
        "services": services,
        # The essential set must match the dashboard's own (static/index.html:
        # {skills, intents, audio}), so /api/health and the UI never disagree
        # about whether the device is healthy.
        "healthy": reachable and all(s["state"] == "ready" for s in services
                                     if s["name"] in ("skills", "intents", "audio")),
    }


def _state(entry: dict[str, Any]) -> str:
    if entry.get("ready"):
        return "ready"
    if entry.get("alive"):
        return "starting"
    if entry.get("alive") is False or entry.get("ready") is False:
        return "not ready"
    return "no answer"
