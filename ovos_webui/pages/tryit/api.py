"""The tryit page's API."""
from typing import Any

from fastapi import HTTPException

from ovos_webui import configio, health
from ovos_webui.service import UtteranceBody


def routes(r) -> None:
    # ── try it: the round trip a spoken sentence would take ──────────────────
    # Sending an utterance is running a command on the device, so it sits on
    # ``privileged`` — a token is always required, like the installer.
    @r.privileged.post("/tryit/ask")
    def api_tryit(body: UtteranceBody) -> dict[str, Any]:
        from ovos_webui import tryit
        if r.bus() is None or not health.bus_reachable(r.bus()):
            raise HTTPException(503, "the message bus is not reachable")
        lang = configio.read_merged_config().get("lang") or "en-us"
        try:
            return tryit.ask(r.bus(), body.text, lang)
        except ValueError as err:
            raise HTTPException(400, str(err))
