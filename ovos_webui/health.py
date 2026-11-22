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
#: ``skills`` and ``intents`` come from ovos-core, ``audio`` from ovos-audio,
#: ``media`` from ovos-media, ``voice`` from the listener, ``gui_service``
#: from ovos-gui and ``PHAL`` from ovos-PHAL.
SERVICES: list[dict[str, str]] = [
    {"name": "skills", "label": "Skills", "hint": "Loads and runs your skills."},
    {"name": "intents", "label": "Intents", "hint": "Decides which skill answers you."},
    {"name": "audio", "label": "Audio", "hint": "Plays speech."},
    # ovos-media is optional: a device may run only ovos-audio (speech, no
    # music/video playback), so a device without it must not read unhealthy.
    {"name": "media", "label": "Media", "hint": "Plays music and video."},
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


#: The services a device must have for it to read healthy, unless it leaves
#: one out on purpose (webui.absent_services).
ESSENTIAL = ("skills", "intents", "audio")


def absent_services(webui: dict[str, Any] | None = None) -> tuple[list[str], list[str]]:
    """The services this device leaves out on purpose, and the problems.

    ``webui.absent_services`` names them (``["audio"]`` for a house server
    whose ears and voice are elsewhere). They are not asked, not listed and
    not counted against "healthy". A name that is not a service is a problem,
    for the About page.
    """
    if webui is None:
        try:
            from ovos_webui import configio
            webui = configio.section("webui")
        except Exception:  # noqa: BLE001 - a broken config leaves nothing out
            webui = {}
    raw = (webui or {}).get("absent_services")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["webui.absent_services: a list of service names"]
    known = {s["name"] for s in SERVICES}
    names = [n for n in raw if isinstance(n, str) and n in known]
    problems = [f"webui.absent_services: no service called {n!r}" for n in raw
                if not (isinstance(n, str) and n in known)]
    return names, problems


def snapshot(bus, timeout: float = DEFAULT_TIMEOUT, absent: list[str] | None = None) -> dict[str, Any]:
    """Return the health of the bus and of every known service, but those
    the device leaves out on purpose (``absent``, by default
    webui.absent_services)."""
    if absent is None:
        absent, _ = absent_services()
    wanted = [s for s in SERVICES if s["name"] not in absent]
    reachable = bus_reachable(bus)
    services = []
    if reachable:
        # Every probe waits for a reply, so asking one service after another
        # would make the page take one timeout per service. Ask all of them at
        # the same time instead: the whole check then costs one timeout.
        with ThreadPoolExecutor(max_workers=max(1, len(wanted))) as pool:
            futures = [pool.submit(probe, bus, s["name"], timeout) for s in wanted]
            answers = []
            for future in futures:
                try:
                    answers.append(future.result(timeout=timeout * 2 + 4))
                except Exception:  # noqa: BLE001 - a stuck probe is "no answer"
                    answers.append({"alive": None, "ready": None})
    else:
        answers = [{"alive": None, "ready": None} for _ in wanted]
    for spec, answer in zip(wanted, answers):
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
                                     if s["name"] in ESSENTIAL),
        # left out on purpose, so the page can say so rather than leave a gap
        "absent": [{"name": s["name"], "label": s["label"]} for s in SERVICES if s["name"] in absent],
    }


def _state(entry: dict[str, Any]) -> str:
    if entry.get("ready"):
        return "ready"
    if entry.get("alive"):
        return "starting"
    if entry.get("alive") is False or entry.get("ready") is False:
        return "not ready"
    return "no answer"
