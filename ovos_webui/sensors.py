"""Latest readings from the device's sensors, if it has any.

The ``ovos-PHAL-sensors`` plugin does not answer queries. It broadcasts a
reading on the bus every time a sensor changes: ``ovos.phal.sensor`` for a value
(temperature, CPU load, battery, …) and ``ovos.phal.binary_sensor`` for an
on/off state. Each carries ``state``, ``sensor_id``, ``device_name``, ``name``
and an ``attributes`` map (unit, device class, …), read from the plugin source.

So the web UI listens for those broadcasts and keeps the latest value of each
sensor. The Sensors page polls this snapshot. Nothing is ever sent; this only
listens, so a device without the plugin simply shows an empty list.
"""
from __future__ import annotations

import threading
import time
from typing import Any


class SensorLog:
    """Thread-safe store of the most recent reading of each sensor."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sensors: dict[str, dict[str, Any]] = {}
        self._attached = False

    def attach(self, bus) -> None:
        """Subscribe to the two sensor broadcasts once."""
        if self._attached or bus is None:
            return
        self._attached = True
        bus.on("ovos.phal.sensor", self._handler("sensor"))
        bus.on("ovos.phal.binary_sensor", self._handler("binary"))

    def _handler(self, kind: str):
        def on_message(message):
            data = getattr(message, "data", None) or {}
            sensor_id = data.get("sensor_id")
            if not isinstance(sensor_id, str) or not sensor_id:
                return
            self.record(kind, sensor_id, data)
        return on_message

    def record(self, kind: str, sensor_id: str, data: dict[str, Any]) -> None:
        attributes = data.get("attributes")
        with self._lock:
            self._sensors[sensor_id] = {
                "sensor_id": sensor_id,
                "kind": kind,
                "state": data.get("state"),
                "device_name": data.get("device_name"),
                "name": data.get("name"),
                "attributes": attributes if isinstance(attributes, dict) else {},
                "updated": time.time(),
            }

    def snapshot(self) -> dict[str, Any]:
        """Return every known sensor's latest reading, sorted for display."""
        with self._lock:
            items = sorted(self._sensors.values(),
                           key=lambda s: ((s.get("device_name") or "").lower(),
                                          (s.get("name") or "").lower()))
            return {"sensors": [dict(s) for s in items]}


LOG_SINGLETON = SensorLog()


def attach(bus) -> None:
    LOG_SINGLETON.attach(bus)


def snapshot() -> dict[str, Any]:
    return LOG_SINGLETON.snapshot()
