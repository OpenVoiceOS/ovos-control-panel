"""The system page's API."""
from typing import Any

from pydantic import BaseModel


class SshBody(BaseModel):
    enabled: bool


def routes(r) -> None:
    # ── system: SSH, factory reset, device language, connectivity, IP geo ────
    # These sit BEFORE the "/system/{action}" wildcard below: FastAPI matches
    # routes in registration order, and a wildcard registered first would
    # swallow "/system/ssh" etc. as an unknown action (404) rather than ever
    # reaching these handlers. Every route sits on the privileged router: SSH
    # and factory reset change what the device will accept next, and a
    # factory reset is destructive — a token is always required, like the
    # network and power actions.
    @r.privileged.get("/system/ssh")
    def api_ssh_status() -> dict[str, Any]:
        from ovos_webui import system
        return system.ssh_status(r.need_bus())

    @r.privileged.post("/system/ssh")
    def api_ssh_set(body: SshBody) -> dict[str, Any]:
        from ovos_webui import system
        bus = r.need_bus()
        return system.ssh_enable(bus) if body.enabled else system.ssh_disable(bus)

    @r.privileged.post("/system/factory-reset")
    def api_factory_reset() -> dict[str, Any]:
        from ovos_webui import system
        return system.factory_reset(r.need_bus())

    @r.privileged.post("/system/detect-location")
    def api_detect_location() -> dict[str, Any]:
        from ovos_webui import system
        return system.detect_location(r.need_bus())
