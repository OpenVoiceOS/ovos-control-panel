"""The sound page's API."""
from typing import Any

from pydantic import BaseModel


class GgwaveListenBody(BaseModel):
    enabled: bool


def routes(r) -> None:
    # ── ggwave listener: turn the device's sound receiver on or off ──────────
    # Fire-and-forget, like /system/{action} — the ggwave audio transformer
    # plugin does not answer a query, it just starts or stops listening.
    @r.privileged.post("/ggwave/listen")
    def api_ggwave_listen(body: GgwaveListenBody) -> dict[str, Any]:
        from ovos_bus_client.message import Message
        if body.enabled:
            # The plugin's handle_enable never reads message.data and it runs no
            # timer, so there is no auto-off to ask for: it listens until
            # something disables it. Sending a timeout would promise a safety
            # net that does not exist. Reported as
            # OpenVoiceOS/ovos-audio-transformer-plugin-ggwave#46.
            r.need_bus().emit(Message("ovos.ggwave.enable", {}, {"source": "ovos-webui"}))
            return {"ok": True, "sent": "ovos.ggwave.enable"}
        r.need_bus().emit(Message("ovos.ggwave.disable", {}, {"source": "ovos-webui"}))
        return {"ok": True, "sent": "ovos.ggwave.disable"}
