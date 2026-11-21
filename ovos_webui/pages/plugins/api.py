"""The plugins page's API."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ovos_webui import installer
from ovos_webui.service import PackageBody


class ChannelBody(BaseModel):
    channel: str = Field(max_length=16)


def routes(r) -> None:
    @r.privileged.post("/plugins/upgrade")
    def api_upgrade(body: PackageBody) -> dict[str, Any]:
        try:
            return installer.INSTALLER.upgrade(body.package, bus=r.bus()).as_dict()
        except installer.UnsafePackageName as err:
            raise HTTPException(400, str(err))
        except installer.InstallerBusy as err:
            raise HTTPException(409, str(err))
        except installer.InstallerUnavailable as err:
            raise HTTPException(503, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    @r.api.get("/updates/channel")
    def api_channel_get() -> dict[str, Any]:
        from ovos_webui import updates
        return {"channel": updates.release_channel(),
                "channels": list(updates.CHANNELS),
                "installer": updates.installer_follows()}

    @r.privileged.post("/updates/channel")
    def api_channel_set(body: ChannelBody) -> dict[str, Any]:
        from ovos_webui import updates
        try:
            return updates.set_release_channel(body.channel, bus=r.bus())
        except ValueError as err:
            raise HTTPException(400, str(err))

    @r.api.get("/updates/conflicts")
    def api_conflicts() -> dict[str, Any]:
        from ovos_webui import updates
        return updates.dependency_conflicts()
