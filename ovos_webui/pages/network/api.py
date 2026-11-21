"""The network page's API."""
from typing import Any

from pydantic import BaseModel, Field


class WifiConnectBody(BaseModel):
    ssid: str = Field(..., max_length=64)
    password: str = Field("", max_length=128)
    security: str = Field("", max_length=64)


class WifiSsidBody(BaseModel):
    ssid: str = Field(..., max_length=64)


def routes(r) -> None:
    @r.privileged.get("/system/connectivity")
    def api_connectivity() -> dict[str, Any]:
        from ovos_webui import system
        return system.connectivity(r.need_bus())

    # ── Wi-Fi: scan and join networks over the network-manager PHAL plugin ────
    # The plugin runs with root (the admin PHAL process) and joining a network
    # changes device state — and can drop this very browser's link to the
    # device — so every route sits on the privileged router: a token is always
    # required, like the installer and the power actions.
    @r.privileged.get("/network/status")
    def api_network_status() -> dict[str, Any]:
        from ovos_webui import network
        status = network.connected(r.need_bus())
        status.update(network.local_links())
        return status

    @r.privileged.post("/network/scan")
    def api_network_scan() -> dict[str, Any]:
        # POST, not GET: a scan drives an nmcli rescan on the device.
        from ovos_webui import network
        return {"networks": network.scan(r.need_bus())}

    @r.privileged.post("/network/connect")
    def api_network_connect(body: WifiConnectBody) -> dict[str, Any]:
        from ovos_webui import network
        return network.connect(r.need_bus(), body.ssid, body.password, body.security)

    @r.privileged.post("/network/disconnect")
    def api_network_disconnect(body: WifiSsidBody) -> dict[str, Any]:
        from ovos_webui import network
        return network.disconnect(r.need_bus(), body.ssid)

    @r.privileged.post("/network/forget")
    def api_network_forget(body: WifiSsidBody) -> dict[str, Any]:
        from ovos_webui import network
        return network.forget(r.need_bus(), body.ssid)
