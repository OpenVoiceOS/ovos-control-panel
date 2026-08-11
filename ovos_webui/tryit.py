"""Send a typed utterance through the device and collect what came back.

This is the "does it actually work?" page behind the dashboard's "is it
running?". Everything here rides message types that already exist:

* ``recognizer_loop:utterance`` — what the listener sends after transcription,
  so a typed sentence takes the exact path a spoken one would.
* ``speak`` — what the device answers with.
* ``mycroft.skill.handler.start`` — names the skill that took the utterance.
* ``complete_intent_failure`` — nothing matched.

No new message type is introduced, and nothing here touches the file system.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

#: How long to wait for the first sign of an answer, in seconds.
ANSWER_TIMEOUT = 8.0

#: After the first speak arrived, wait this long for follow-up sentences.
SETTLE = 1.0

MAX_UTTERANCE = 500


def ask(bus, utterance: str, lang: str) -> dict[str, Any]:
    """Send ``utterance`` over the bus and report what the device did."""
    from ovos_bus_client.message import Message

    utterance = (utterance or "").strip()
    if not utterance:
        raise ValueError("type something to try first")
    if len(utterance) > MAX_UTTERANCE:
        raise ValueError(f"keep it under {MAX_UTTERANCE} characters")

    ident = f"ovos-webui-{uuid.uuid4().hex}"
    spoken: list[str] = []
    handlers: list[str] = []
    failed = threading.Event()
    first_answer = threading.Event()

    def on_speak(message):
        text = (message.data or {}).get("utterance")
        if text:
            spoken.append(str(text))
            first_answer.set()

    def on_handler(message):
        name = (message.data or {}).get("name") or (message.data or {}).get("handler")
        if name:
            handlers.append(str(name))

    def on_failure(_message):
        failed.set()
        first_answer.set()

    bus.on("speak", on_speak)
    bus.on("mycroft.skill.handler.start", on_handler)
    bus.on("complete_intent_failure", on_failure)
    started = time.monotonic()
    try:
        bus.emit(Message("recognizer_loop:utterance",
                         {"utterances": [utterance], "lang": lang},
                         {"ident": ident, "source": "ovos-webui",
                          "destination": ["skills"]}))
        first_answer.wait(ANSWER_TIMEOUT)
        if first_answer.is_set() and not failed.is_set():
            # Skills often answer in more than one sentence.
            time.sleep(SETTLE)
    finally:
        bus.remove("speak", on_speak)
        bus.remove("mycroft.skill.handler.start", on_handler)
        bus.remove("complete_intent_failure", on_failure)
    elapsed = round(time.monotonic() - started, 2)
    if failed.is_set():
        return {"matched": False, "spoken": [], "handler": None,
                "elapsed": elapsed}
    return {"matched": bool(spoken) or bool(handlers), "spoken": spoken,
            "handler": handlers[0] if handlers else None, "elapsed": elapsed,
            "timeout": not first_answer.is_set()}


def preview(bus, text: str, lang: str) -> dict[str, Any]:
    """Ask the device to speak ``text`` out loud — a voice test."""
    from ovos_bus_client.message import Message

    text = (text or "").strip()
    if not text:
        raise ValueError("type something to speak first")
    if len(text) > MAX_UTTERANCE:
        raise ValueError(f"keep it under {MAX_UTTERANCE} characters")
    bus.emit(Message("speak", {"utterance": text, "lang": lang},
                     {"source": "ovos-webui"}))
    return {"sent": True}
