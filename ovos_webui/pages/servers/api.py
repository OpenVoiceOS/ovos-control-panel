"""The servers page's API."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ovos_webui import servers


class ServersBody(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=servers.MAX_URLS)


def routes(r) -> None:
    # ── self-hosted servers (STT / TTS / translate) ─────────────────────────
    # These write the user configuration layer, exactly like /api/config and
    # /api/config/quick above — no bus message is specific to this feature.
    # Reads sit on ``api``; the write changes what the device does, so it sits
    # on ``privileged`` like the other device-changing routes.
    @r.privileged.get("/servers")
    def api_servers_get() -> dict[str, Any]:
        return {kind: servers.get_servers(kind) for kind in servers.KINDS}

    @r.privileged.post("/servers/{kind}")
    def api_servers_set(kind: str, body: ServersBody) -> dict[str, Any]:
        if kind not in servers.KINDS:
            raise HTTPException(404, f"unknown kind '{kind}'")
        result = servers.set_servers(kind, body.urls, bus=r.bus())
        if "error" in result:
            raise HTTPException(400, result["error"])
        return result
