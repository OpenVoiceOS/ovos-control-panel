"""The Sensors page's API. ovos-PHAL-sensors only broadcasts readings, so the
panel listens and keeps the latest of each. Read-only; nothing is sent. No new
message type."""
from typing import Any

from ovos_webui import sensors as sensorlog


def routes(r) -> None:
    @r.api.get("/sensors")
    def api_sensors_get() -> dict[str, Any]:
        sensorlog.attach(r.need_bus())
        return sensorlog.snapshot()
