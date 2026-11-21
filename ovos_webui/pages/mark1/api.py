"""The mark1 page's API."""
from typing import Annotated, Any

from pydantic import BaseModel, Field


class Mark1AnimBody(BaseModel):
    kind: str = Field(..., max_length=16)


class Mark1ColorBody(BaseModel):
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)


class Mark1DisplayBody(BaseModel):
    # Bound both dimensions so a huge nested body is rejected during validation
    # rather than fully materialized (the faceplate is exactly 8 rows x 32 cols;
    # mark1._valid_grid re-checks the exact shape).
    grid: Annotated[list[Annotated[list[int], Field(max_length=32)]],
                    Field(max_length=8)]
    x: int = Field(0, ge=-64, le=64)
    y: int = Field(0, ge=-64, le=64)
    clear: bool = True


class Mark1LevelBody(BaseModel):
    level: int = Field(ge=1, le=30)


class Mark1PercentBody(BaseModel):
    percentage: int = Field(ge=0, le=100)


class Mark1PixelBody(BaseModel):
    # 24 eye pixels, twelve per ring. Pinned to mark1.EYE_PIXEL_COUNT by a
    # test rather than read from it: mark1 is imported lazily by the routes
    # that use it, and a module-level import here would pull it in on start.
    idx: int = Field(ge=0, le=23)
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)


class Mark1SideBody(BaseModel):
    side: str = Field(..., max_length=8)


class Mark1TextBody(BaseModel):
    text: str = Field("", max_length=500)


class Mark1TimesBody(BaseModel):
    times: int = Field(ge=1, le=20)


class Mark1VisemeBody(BaseModel):
    code: int = Field(ge=0, le=6)


class Mark1VolumeBody(BaseModel):
    volume: int = Field(ge=0, le=11)


def routes(r) -> None:
    # ── Mark-1 faceplate: eyes + mouth over enclosure.* ───────────────────────
    # Every route changes what the faceplate shows, so all of it sits on the
    # privileged router, like the network and system controls.
    @r.privileged.get("/mark1/available")
    def api_mark1_available() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.available(r.need_bus())

    @r.privileged.get("/mark1/eyes")
    def api_mark1_eyes_state() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_state(r.need_bus())

    @r.privileged.post("/mark1/eyes/pixel")
    def api_mark1_eyes_pixel(body: Mark1PixelBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.set_pixel(r.need_bus(), body.idx, body.r, body.g, body.b)

    @r.privileged.get("/mark1/firmware")
    def api_mark1_firmware() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.firmware(r.need_bus())

    @r.privileged.post("/mark1/firmware/update")
    def api_mark1_firmware_update() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.firmware_update(r.need_bus())

    @r.privileged.post("/mark1/display")
    def api_mark1_display(body: Mark1DisplayBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.display_grid(r.need_bus(), body.grid, body.x, body.y, body.clear)

    @r.privileged.post("/mark1/mouth/text")
    def api_mark1_mouth_text(body: Mark1TextBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.mouth_text(r.need_bus(), body.text)

    @r.privileged.post("/mark1/mouth/reset")
    def api_mark1_mouth_reset() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.mouth_reset(r.need_bus())

    @r.privileged.post("/mark1/mouth/anim")
    def api_mark1_mouth_anim(body: Mark1AnimBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.mouth_anim(r.need_bus(), body.kind)

    @r.privileged.post("/mark1/mouth/viseme")
    def api_mark1_mouth_viseme(body: Mark1VisemeBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.mouth_viseme(r.need_bus(), body.code)

    @r.privileged.post("/mark1/eyes/color")
    def api_mark1_eyes_color(body: Mark1ColorBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_color(r.need_bus(), body.r, body.g, body.b)

    @r.privileged.post("/mark1/eyes/on")
    def api_mark1_eyes_on() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_on(r.need_bus())

    @r.privileged.post("/mark1/eyes/off")
    def api_mark1_eyes_off() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_off(r.need_bus())

    @r.privileged.post("/mark1/eyes/reset")
    def api_mark1_eyes_reset() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_reset(r.need_bus())

    @r.privileged.post("/mark1/eyes/narrow")
    def api_mark1_eyes_narrow() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_narrow(r.need_bus())

    @r.privileged.post("/mark1/eyes/spin")
    def api_mark1_eyes_spin() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_spin(r.need_bus())

    @r.privileged.post("/mark1/eyes/blink")
    def api_mark1_eyes_blink(body: Mark1SideBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_blink(r.need_bus(), body.side)

    @r.privileged.post("/mark1/eyes/look")
    def api_mark1_eyes_look(body: Mark1SideBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_look(r.need_bus(), body.side)

    @r.privileged.post("/mark1/eyes/fill")
    def api_mark1_eyes_fill(body: Mark1PercentBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_fill(r.need_bus(), body.percentage)

    @r.privileged.post("/mark1/eyes/brightness")
    def api_mark1_eyes_brightness(body: Mark1LevelBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_brightness(r.need_bus(), body.level)

    @r.privileged.post("/mark1/eyes/volume")
    def api_mark1_eyes_volume(body: Mark1VolumeBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_volume(r.need_bus(), body.volume)

    @r.privileged.post("/mark1/system/reset")
    def api_mark1_system_reset() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.system_reset(r.need_bus())

    @r.privileged.post("/mark1/system/mute")
    def api_mark1_system_mute() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.system_mute(r.need_bus())

    @r.privileged.post("/mark1/system/unmute")
    def api_mark1_system_unmute() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.system_unmute(r.need_bus())

    @r.privileged.post("/mark1/system/blink")
    def api_mark1_system_blink(body: Mark1TimesBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.system_blink(r.need_bus(), body.times)
