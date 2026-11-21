"""The Wallpaper page's API: the existing ovos-PHAL-plugin-wallpaper-manager
bus queries. No new message type."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ovos_webui import wallpaper


class WallpaperUrlBody(BaseModel):
    url: str = Field(max_length=wallpaper.MAX_URL)


class WallpaperProviderBody(BaseModel):
    provider_name: str = Field(max_length=255)


class WallpaperRotationBody(BaseModel):
    enabled: bool


def routes(r) -> None:
    @r.privileged.get("/wallpaper")
    def api_wallpaper_get() -> dict[str, Any]:
        return wallpaper.get_state(r.need_bus())

    @r.privileged.post("/wallpaper/set")
    def api_wallpaper_set(body: WallpaperUrlBody) -> dict[str, Any]:
        try:
            return wallpaper.set_wallpaper(r.need_bus(), body.url)
        except wallpaper.WallpaperError as err:
            raise HTTPException(400, str(err)) from None

    @r.privileged.post("/wallpaper/next")
    def api_wallpaper_next() -> dict[str, Any]:
        return wallpaper.next_wallpaper(r.need_bus())

    @r.privileged.post("/wallpaper/provider")
    def api_wallpaper_provider(body: WallpaperProviderBody) -> dict[str, Any]:
        try:
            return wallpaper.set_provider(r.need_bus(), body.provider_name)
        except wallpaper.WallpaperError as err:
            raise HTTPException(400, str(err)) from None

    @r.privileged.post("/wallpaper/rotation")
    def api_wallpaper_rotation(body: WallpaperRotationBody) -> dict[str, Any]:
        return wallpaper.set_auto_rotation(r.need_bus(), body.enabled)
