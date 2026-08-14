"""A small ring buffer of the device's recent voice activity.

The Try-it page polls this to show "the wake word fired", "the microphone is
recording", "the device said …" as they happen. The buffer only *listens* to
message types the stack already emits; it never sends anything.

The buffer is bounded, holds plain text only, and keeps no audio.
"""
from __future__ import annotations

import itertools
import threading
import time
from typing import Any

#: How many events are kept. Old ones fall off.
MAX_EVENTS = 100

#: message type -> short event name shown to the page
WATCHED = {
    "recognizer_loop:wakeword": "wakeword",
    "recognizer_loop:record_begin": "listening",
    "recognizer_loop:record_end": "done_listening",
    "recognizer_loop:utterance": "heard",
    "speak": "speaking",
    "complete_intent_failure": "no_match",
    "mycroft.skill.handler.start": "skill_start",
}


class EventLog:
    """Thread-safe bounded log of bus events."""

    def __init__(self):
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._counter = itertools.count(1)
        self._bus = None

    def attach(self, bus) -> None:
        """Subscribe to the watched message types.

        Guards on the bus object, not a flag: a repeat call with the same bus
        does nothing, so no topic gets two handlers, but a new bus after a
        reconnect is subscribed to so the feed does not go stale.
        """
        if bus is None or bus is self._bus:
            return
        self._bus = bus
        for msg_type, name in WATCHED.items():
            bus.on(msg_type, self._handler(name))

    def _handler(self, name: str):
        def on_message(message):
            data = getattr(message, "data", None) or {}
            detail = ""
            if name == "heard":
                utterances = data.get("utterances") or []
                detail = str(utterances[0]) if utterances else ""
            elif name == "speaking":
                detail = str(data.get("utterance") or "")
            elif name == "wakeword":
                detail = str(data.get("hotword") or data.get("wake_word") or "")
            elif name == "skill_start":
                detail = str(data.get("name") or "")
            self.add(name, detail)
        return on_message

    def add(self, name: str, detail: str = "") -> None:
        with self._lock:
            self._events.append({"id": next(self._counter), "event": name,
                                 "detail": detail[:300], "time": time.time()})
            del self._events[:-MAX_EVENTS]

    def since(self, last_id: int = 0) -> dict[str, Any]:
        with self._lock:
            events = [e for e in self._events if e["id"] > last_id]
            next_id = self._events[-1]["id"] if self._events else last_id
        return {"events": events, "next": max(next_id, last_id)}


LOG_SINGLETON = EventLog()
