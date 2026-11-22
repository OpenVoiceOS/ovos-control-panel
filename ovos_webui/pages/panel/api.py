"""The control panel page's API: the panel's own look, and where its
recommendations come from."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ovos_webui import branding, configio


class LookBody(BaseModel):
    """An empty value takes the setting out of your layer again."""
    name: str = Field("", max_length=branding.MAX_NAME)
    accent: str = Field("", max_length=7)
    theme: str = Field("", max_length=10)
    text_size: str = Field("", max_length=10)


class RecommendsBody(BaseModel):
    """A directory laid out like ovos-config's recommendations, "openvoiceos"
    for OpenVoiceOS's own, or empty for what the device came with."""
    path: str = Field("", max_length=300)


class UploadsBody(BaseModel):
    """The largest file a page may keep on the device, in MB; 0 takes the
    setting out of your layer again."""
    max_mb: int = Field(ge=0, le=configio.MAX_UPLOAD_MB_LIMIT, strict=True)


def _uploads() -> dict[str, Any]:
    mine = configio.get_in(configio.read_user_config(), ["webui", "max_upload_mb"])
    return {"max_mb": configio.max_upload_mb(), "default": configio.MAX_UPLOAD_MB_DEFAULT,
            "yours": mine if isinstance(mine, int) and not isinstance(mine, bool) else None}


def _put(user: dict, key: str, value: str) -> None:
    webui = user.setdefault("webui", {})
    if value:
        webui[key] = value
    else:
        webui.pop(key, None)


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
        return dict(branding.appearance(),
                    name=brand["name"], accent=brand["colors"].get("accent"),
                    default_name=branding.DEFAULT_NAME,
                    warnings=branding.warnings(brand), yours=bool(mine))

    @r.privileged.post("/panel/look")
    def api_look_set(body: LookBody) -> dict[str, Any]:
        name = body.name.strip()
        accent = body.accent.strip().lower()
        if name and branding._CONTROL_RE.search(name):  # noqa: SLF001 - one rule for names
            raise HTTPException(400, "the name cannot hold markup or control characters")
        if accent and not (len(accent) == 7 and branding._COLOR_RE.match(accent)):  # noqa: SLF001
            raise HTTPException(400, "the colour must be written as #rrggbb")
        if body.theme and body.theme not in branding.THEMES:
            raise HTTPException(400, "the theme is choose, dark or light")
        if body.text_size and body.text_size not in branding.TEXT_SIZES:
            raise HTTPException(400, "the text size is choose, normal, large or xlarge")

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
            # written as chosen, "choose" too, so it can undo a distribution's
            # choice; empty takes yours out again
            _put(user, "theme", body.theme)
            _put(user, "text_size", body.text_size)

        result = configio.mutate(change, bus=r.bus())
        mine = configio.get_in(configio.read_user_config(), ["webui", "branding"]) or {}
        result["warnings"] = branding.warnings(_in_force(mine))
        return result

    @r.api.get("/panel/recommends")
    def api_recommends() -> dict[str, Any]:
        from ovos_webui import recommends
        return recommends.source()

    @r.privileged.post("/panel/recommends")
    def api_recommends_set(body: RecommendsBody) -> dict[str, Any]:
        from pathlib import Path

        from ovos_webui import recommends
        path = body.path.strip()
        if path and path != recommends.OPENVOICEOS:
            folder = Path(path).expanduser()
            if not folder.is_dir():
                raise HTTPException(400, "there is no such folder on the device")
            if not any(d.is_dir() and any(d.glob("*.conf")) for d in folder.iterdir()):
                raise HTTPException(400, "the folder holds no recommendations "
                                         "(<profile>/<language>.conf)")
        configio.mutate(lambda user: _put(user, "recommends", path), bus=r.bus())
        return recommends.source()

    @r.api.get("/panel/uploads")
    def api_uploads() -> dict[str, Any]:
        return _uploads()

    @r.privileged.post("/panel/uploads")
    def api_uploads_set(body: UploadsBody) -> dict[str, Any]:
        def change(user: dict) -> None:
            webui = user.setdefault("webui", {})
            if body.max_mb:
                webui["max_upload_mb"] = body.max_mb
            else:
                webui.pop("max_upload_mb", None)
        configio.mutate(change, bus=r.bus())
        return _uploads()
