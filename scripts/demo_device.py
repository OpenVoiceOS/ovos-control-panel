#!/usr/bin/env python3
"""A stand-in OVOS device, for taking pictures of the panel against.

The panel reads a real device over the message bus. Run it with nothing behind
it and every page reports the truth -- that nothing is answering -- which makes
a poor illustration of a working device and an outright false one under a
caption saying the services are ready.

This answers the handful of questions the panel asks about a device's state. It
is not a simulator of OVOS and it runs no skills: it says "alive and ready" for
each service and answers the readbacks the pages poll. Anything a page needs
that is not here still shows as unanswered, which is the honest failure.

Used by ``screenshots.py``. Not part of the installed package.
"""
from __future__ import annotations

import os
import time

from ovos_bus_client import MessageBusClient
from ovos_bus_client.message import Message

from ovos_webui.health import SERVICES

#: Answered as ``{"status": True}``, which is what ``ProcessStatus`` sends.
STATUS_TOPICS = [f"mycroft.{s['name']}.is_{key}"
                 for s in SERVICES for key in ("alive", "ready")]

#: Named on the command line to leave one service unanswered. The
#: troubleshooting page is about what a device with something wrong looks
#: like, and a device where everything answers cannot illustrate it.
SILENT = os.environ.get("DEMO_SILENT_SERVICE", "")

#: A faceplate that is present and showing a colour, so the Mark-1 page draws
#: a device rather than saying it could not find one.
EYE_PIXELS = [[0, 200, 255]] * 24

#: What each page asks for, and what a device carrying that plugin answers.
#: Nothing here answers for a plugin whose page would then show something a
#: device could not: the wallpaper manager was tried and dropped, because the
#: only pictures this can offer are ones that do not resolve, and a page of
#: broken images is a worse illustration than a page saying no manager is
#: installed.
#: The topic is the request; the value is the reply topic and its payload.
#: Nothing here is invented -- each payload is the shape the panel's own
#: reader parses, and a page whose plugin is not answered still reports that
#: honestly rather than being faked into looking installed.
ANSWERS: dict[str, tuple[str, dict]] = {
    "ovos.phal.app_launcher.list": (
        "ovos.phal.app_launcher.list.response",
        {"apps": [{"name": "Files", "exec": "nautilus"},
                  {"name": "Web browser", "exec": "firefox"},
                  {"name": "Terminal", "exec": "kgx"}]}),
    "system.ssh.status": ("", {"enabled": False}),
    # The dashboard reports the intent service ready, so the intents page has
    # to be able to answer as well: a device cannot be both at once, and an
    # image of one saying each is the panel contradicting itself.
    # These are what the two skills in the development extra genuinely
    # register. A `.intent` file is matched by template and travels under the
    # author's label with the skill prefix and the suffix stripped
    # (`ovos_workshop.intents._clean_padatious_name`); an `IntentBuilder`
    # would be matched by keyword and travel under the parser's own name.
    # Neither ever carries the Python handler's method name. Both of these
    # skills declare every intent in a file, so every entry here is a
    # template one -- a test holds this against what they actually ship.
    "ovos.intent.list": (
        "ovos.intent.list.response",
        {"ok": True, "intents": [
            {"skill_id": "ovos-skill-date-time.openvoiceos",
             "intent_name": "what.time.is.it", "lang": "en-US",
             "method": "template", "enabled": True, "session_id": "default"},
            {"skill_id": "ovos-skill-date-time.openvoiceos",
             "intent_name": "what.day.is.it", "lang": "en-US",
             "method": "template", "enabled": True, "session_id": "default"},
            {"skill_id": "ovos-skill-hello-world.openvoiceos",
             "intent_name": "HelloWorldIntent", "lang": "en-US",
             "method": "template", "enabled": True, "session_id": "default"}]}),
    "intent.service.active_skills.get": (
        "intent.service.active_skills.reply",
        {"skills": ["ovos-skill-date-time.openvoiceos"]}),
}


def _reply(bus, message: Message, topic: str, data: dict) -> None:
    bus.emit(message.reply(topic, data) if topic else message.response(data))


def serve(bus) -> None:
    for topic in STATUS_TOPICS:
        if SILENT and topic.startswith(f"mycroft.{SILENT}."):
            continue
        bus.on(topic, lambda m: bus.emit(m.response({"status": True})))

    bus.on("enclosure.eyes.rgb.get",
           lambda m: _reply(bus, m, "enclosure.eyes.rgb", {"pixels": EYE_PIXELS}))
    bus.on("enclosure.firmware.version.get",
           lambda m: _reply(bus, m, "enclosure.firmware.version",
                            {"version": "1.4.2", "supported": "1.4.2"}))

    for ask, (reply_topic, payload) in ANSWERS.items():
        bus.on(ask, lambda m, t=reply_topic, d=payload: _reply(bus, m, t, d))


def main() -> int:
    bus = MessageBusClient()
    bus.run_in_thread()
    bus.connected_event.wait(10)
    serve(bus)
    print("stand-in device answering; ctrl-c to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
