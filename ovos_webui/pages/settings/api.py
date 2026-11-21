"""The settings page's API."""
from typing import Any

from fastapi import HTTPException

from ovos_webui import configio


def routes(r) -> None:
    @r.api.post("/config/undo")
    def api_config_undo() -> dict[str, Any]:
        try:
            return configio.undo_last(bus=r.bus())
        except configio.ConfigError as err:
            raise HTTPException(400, str(err)) from None

    @r.api.get("/config/layers")
    def api_config_layers() -> dict[str, Any]:
        from ovos_webui import layers
        # Without the values: this says which files exist, in what order they
        # merge, and which of them this device's policy ignores.
        return {"layers": [{k: v for k, v in layer.items() if k != "data"}
                           for layer in layers.stack()]}

    @r.api.get("/config/resolve")
    def api_config_resolve(key: str) -> dict[str, Any]:
        from ovos_webui import layers
        if not key or len(key) > 200:
            raise HTTPException(400, "key must be a dotted configuration key")
        return layers.resolve(key)
