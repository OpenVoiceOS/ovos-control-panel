"""The Voice and language page's API: the device's location."""
from typing import Any


def routes(r) -> None:
    # privileged: it writes the device's location
    @r.privileged.post("/location/detect")
    def api_detect_location() -> dict[str, Any]:
        from ovos_webui import system
        return system.detect_location(r.need_bus())
