"""The Apps page's API: the existing ovos-PHAL-plugin-app-launcher bus
queries. No new message type."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ovos_webui import applauncher


class AppNameBody(BaseModel):
    name: str = Field(max_length=applauncher.MAX_NAME)


def routes(r) -> None:
    @r.privileged.get("/apps")
    def api_apps_list() -> dict[str, Any]:
        return applauncher.list_apps(r.need_bus())

    @r.privileged.post("/apps/launch")
    def api_apps_launch(body: AppNameBody) -> dict[str, Any]:
        try:
            return applauncher.launch(r.need_bus(), body.name)
        except applauncher.AppLauncherError as err:
            raise HTTPException(400, str(err)) from None

    @r.privileged.post("/apps/close")
    def api_apps_close(body: AppNameBody) -> dict[str, Any]:
        try:
            return applauncher.close(r.need_bus(), body.name)
        except applauncher.AppLauncherError as err:
            raise HTTPException(400, str(err)) from None
