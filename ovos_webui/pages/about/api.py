"""The about page's API."""
from typing import Any

from fastapi import Request

from ovos_webui import meta


def routes(r) -> None:
    # ── about ────────────────────────────────────────────────────────────────
    @r.api.get("/about")
    def api_about(request: Request) -> dict[str, Any]:
        return meta.about(request.headers.get("host", ""))
