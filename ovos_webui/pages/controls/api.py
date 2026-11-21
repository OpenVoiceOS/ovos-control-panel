"""The controls page's API."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class MuteBody(BaseModel):
    muted: bool


class VolumeBody(BaseModel):
    percent: int = Field(ge=0, le=100, strict=True)


def routes(r) -> None:
    @r.api.get("/device/volume")
    def api_volume_get() -> dict[str, Any]:
        from ovos_webui import devicecontrol
        return devicecontrol.get_volume(r.need_bus())

    @r.privileged.post("/device/volume")
    def api_volume_set(body: VolumeBody) -> dict[str, Any]:
        from ovos_webui import devicecontrol
        try:
            return devicecontrol.set_volume(r.need_bus(), body.percent)
        except ValueError as err:
            raise HTTPException(400, str(err))

    @r.privileged.post("/device/volume/mute")
    def api_volume_mute(body: MuteBody) -> dict[str, Any]:
        from ovos_webui import devicecontrol
        return devicecontrol.set_mute(r.need_bus(), body.muted)

    @r.api.get("/device/mic")
    def api_mic_get() -> dict[str, Any]:
        from ovos_webui import devicecontrol
        return devicecontrol.get_mic(r.need_bus())

    @r.privileged.post("/device/mic/mute")
    def api_mic_mute(body: MuteBody) -> dict[str, Any]:
        from ovos_webui import devicecontrol
        return devicecontrol.set_mic_mute(r.need_bus(), body.muted)
