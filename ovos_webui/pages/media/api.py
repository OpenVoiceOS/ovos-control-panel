"""The media page's API."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class MediaEntryBody(BaseModel):
    """One media entry, as the player itself describes it, and optionally the
    set it was picked from. Not validated field by field here:
    `media.play_entry` refuses anything the player would refuse, using the
    player's own rule, so the two cannot drift apart."""
    entry: dict[str, Any]
    #: Absent means "the caller does not know the set"; the service reads the
    #: device's own. An empty list means "the set is empty" and reads nothing.
    among: list[dict[str, Any]] | None = None


class MediaSeekBody(BaseModel):
    #: Milliseconds from the start of the track. A day is more than any
    #: track, and the player refuses anything that is not a real number.
    position: int = Field(ge=0, le=86_400_000, strict=True)


class MediaToggleBody(BaseModel):
    """Shuffle and repeat: both are on-or-off, and the name reaches the
    generated API documentation, so it should not say shuffle on the repeat
    route."""
    enabled: bool


class MediaVolumeBody(BaseModel):
    percent: int = Field(ge=0, le=100, strict=True)


def routes(r) -> None:
    # ── media: now-playing, transport, and volume over OCP / ovos-media ──────
    # All /media/* routes are privileged: even the reads (status, available,
    # volume) expose what's playing and current device state, so they should
    # not be readable on a token-less device, matching the transport and
    # volume-set/mute routes that change state.
    @r.privileged.get("/media/status")
    def api_media_status() -> dict[str, Any]:
        from ovos_webui import media
        return media.status(r.need_bus())

    @r.privileged.get("/media/progress")
    def api_media_progress() -> dict[str, Any]:
        from ovos_webui import media
        return media.track_progress(r.need_bus())

    @r.privileged.post("/media/seek")
    def api_media_seek(body: MediaSeekBody) -> dict[str, Any]:
        from ovos_webui import media
        return media.seek_to(r.need_bus(), body.position)

    @r.privileged.post("/media/shuffle")
    def api_media_shuffle(body: MediaToggleBody) -> dict[str, Any]:
        from ovos_webui import media
        return media.set_shuffle(r.need_bus(), body.enabled)

    @r.privileged.post("/media/repeat")
    def api_media_repeat(body: MediaToggleBody) -> dict[str, Any]:
        from ovos_webui import media
        return media.set_repeat(r.need_bus(), body.enabled)

    @r.privileged.get("/media/candidates")
    def api_media_candidates() -> dict[str, Any]:
        from ovos_webui import media
        return media.candidates(r.need_bus())

    @r.privileged.get("/media/likes")
    def api_media_likes() -> dict[str, Any]:
        from ovos_webui import media
        return media.likes(r.need_bus())

    @r.privileged.post("/media/play_entry")
    def api_media_play_entry(body: MediaEntryBody) -> dict[str, Any]:
        from ovos_webui import media
        return media.play_entry(r.need_bus(), body.entry, body.among)

    @r.privileged.get("/media/backends")
    def api_media_backends() -> dict[str, Any]:
        from ovos_webui import media
        return media.backends(r.need_bus())

    @r.privileged.get("/media/available")
    def api_media_available() -> dict[str, Any]:
        from ovos_webui import media
        return {"available": media.available(r.need_bus())}

    @r.privileged.post("/media/play_pause")
    def api_media_play_pause() -> dict[str, Any]:
        from ovos_webui import media
        return media.play_pause(r.need_bus())

    @r.privileged.post("/media/pause")
    def api_media_pause() -> dict[str, Any]:
        from ovos_webui import media
        return media.pause(r.need_bus())

    @r.privileged.post("/media/resume")
    def api_media_resume() -> dict[str, Any]:
        from ovos_webui import media
        return media.resume(r.need_bus())

    @r.privileged.post("/media/stop")
    def api_media_stop() -> dict[str, Any]:
        from ovos_webui import media
        return media.stop(r.need_bus())

    @r.privileged.post("/media/next")
    def api_media_next() -> dict[str, Any]:
        from ovos_webui import media
        return media.next(r.need_bus())

    @r.privileged.post("/media/previous")
    def api_media_previous() -> dict[str, Any]:
        from ovos_webui import media
        return media.previous(r.need_bus())

    @r.privileged.get("/media/volume")
    def api_media_volume_get() -> dict[str, Any]:
        from ovos_webui import media
        return media.get_volume(r.need_bus())

    @r.privileged.post("/media/volume")
    def api_media_volume_set(body: MediaVolumeBody) -> dict[str, Any]:
        from ovos_webui import media
        try:
            return media.set_volume(r.need_bus(), body.percent)
        except ValueError as err:
            raise HTTPException(400, str(err))

    @r.privileged.post("/media/mute")
    def api_media_mute() -> dict[str, Any]:
        from ovos_webui import media
        return media.mute(r.need_bus())

    @r.privileged.post("/media/unmute")
    def api_media_unmute() -> dict[str, Any]:
        from ovos_webui import media
        return media.unmute(r.need_bus())
