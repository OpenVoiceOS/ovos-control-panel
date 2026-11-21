"""The control panel page's API: the panel's own name and colour."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ovos_webui import branding, configio


class LookBody(BaseModel):
    """An empty value takes the setting out of your layer again."""
    name: str = Field("", max_length=branding.MAX_NAME)
    accent: str = Field("", max_length=7)


def _darker(color: str, by: float = 0.18) -> str:
    """The filled variant of the accent: the same colour, a little darker."""
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c * (1 - by)):02x}" for c in rgb)


def _in_force(mine: dict[str, Any]) -> dict[str, Any]:
    """The branding with your layer, read fresh, over the rest (a distribution's
    defaults), so a page shows its own save at once."""
    base = configio.section("webui").get("branding") or {}
    base = base if isinstance(base, dict) else {}
    mine = mine if isinstance(mine, dict) else {}
    merged = {**base, **mine}
    merged["colors"] = {**(base.get("colors") or {}), **(mine.get("colors") or {})}
    return branding.read(merged)


def routes(r) -> None:
    @r.api.get("/panel/look")
    def api_look() -> dict[str, Any]:
        mine = configio.get_in(configio.read_user_config(), ["webui", "branding"]) or {}
        brand = _in_force(mine)
        return {"name": brand["name"], "accent": brand["colors"].get("accent"),
                "default_name": branding.DEFAULT_NAME,
                "warnings": branding.warnings(brand), "yours": bool(mine)}

    @r.privileged.post("/panel/look")
    def api_look_set(body: LookBody) -> dict[str, Any]:
        name = body.name.strip()
        accent = body.accent.strip().lower()
        if name and branding._CONTROL_RE.search(name):  # noqa: SLF001 - one rule for names
            raise HTTPException(400, "the name cannot hold markup or control characters")
        if accent and not (len(accent) == 7 and branding._COLOR_RE.match(accent)):  # noqa: SLF001
            raise HTTPException(400, "the colour must be written as #rrggbb")

        def change(user: dict) -> None:
            look = user.setdefault("webui", {}).setdefault("branding", {})
            if name:
                look["name"] = name
            else:
                look.pop("name", None)
            colors = look.setdefault("colors", {})
            if accent:
                colors["accent"] = accent
                colors["accent-strong"] = _darker(accent)
            else:
                colors.pop("accent", None)
                colors.pop("accent-strong", None)
            if not colors:
                look.pop("colors", None)
            if not look:
                user["webui"].pop("branding", None)

        result = configio.mutate(change, bus=r.bus())
        mine = configio.get_in(configio.read_user_config(), ["webui", "branding"]) or {}
        result["warnings"] = branding.warnings(_in_force(mine))
        return result
