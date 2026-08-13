"""Read and change the device's wallpaper, through the wallpaper manager.

All of this is an existing bus query served by
``ovos-PHAL-plugin-wallpaper-manager`` (no new message type). The messages and
their replies were read from that plugin's source:

- ``…get.wallpaper`` → ``{"url": …}``            the current wallpaper
- ``…get.active.provider`` → ``{"active_provider": …}``
- ``…get.registered.providers`` → ``{"registered_providers": [{provider_name, provider_display_name}]}``
- ``…get.collection`` → ``{"wallpaper_collection": [url, …]}``
- ``…get.auto.rotation`` → ``{"auto_rotation": bool, "rotation_time": int}``
- ``…set.wallpaper`` (``{"url"}``) → ``{"wallpaper": url}``
- ``…set.active.provider`` (``{"provider_name"}``), ``…change.wallpaper``,
  ``…enable.auto.rotation`` / ``…disable.auto.rotation`` — fire-and-forget.

Every read has a hard deadline through :func:`ovos_webui.buswait.wait_for_response`,
so a device without the wallpaper manager reports ``available: False`` instead
of hanging.
"""
from __future__ import annotations

from typing import Any

from ovos_webui import buswait

QUERY_TIMEOUT = 4.0
MAX_URL = 2048
_BASE = "ovos.wallpaper.manager"


class WallpaperError(ValueError):
    """Raised when a wallpaper url or provider name is not usable."""


def _msg(msg_type: str, data: dict[str, Any] | None = None):
    from ovos_bus_client.message import Message

    return Message(msg_type, data or {}, {"source": "ovos-webui"})


def _reply(bus, suffix: str):
    msg_type = f"{_BASE}.{suffix}"
    return buswait.wait_for_response(
        bus, _msg(msg_type), timeout=QUERY_TIMEOUT, reply_type=msg_type + ".response")


def _query(bus, suffix: str, key: str) -> Any:
    """Send ``<base>.<suffix>`` and return ``reply.data[key]``, or ``None``."""
    reply = _reply(bus, suffix)
    if reply is None:
        return None
    return (reply.data or {}).get(key)


def get_state(bus) -> dict[str, Any]:
    """Return the current wallpaper, providers, collection and rotation state.

    The first query decides availability: if the wallpaper manager does not
    answer it, the whole page reports unavailable rather than half-loading.
    """
    reply = _reply(bus, "get.wallpaper")
    if reply is None:
        return {"available": False}
    current = (reply.data or {}).get("url")
    providers = _query(bus, "get.registered.providers", "registered_providers") or []
    collection = _query(bus, "get.collection", "wallpaper_collection") or []
    active = _query(bus, "get.active.provider", "active_provider")
    rotation = _reply(bus, "get.auto.rotation")
    rot_data = (rotation.data or {}) if rotation is not None else {}
    return {
        "available": True,
        "current": current,
        "active_provider": active,
        "providers": [
            {"provider_name": p.get("provider_name"),
             "provider_display_name": p.get("provider_display_name") or p.get("provider_name")}
            for p in providers if isinstance(p, dict) and p.get("provider_name")],
        "collection": [u for u in collection if isinstance(u, str)],
        "auto_rotation": bool(rot_data.get("auto_rotation")),
        "rotation_time": rot_data.get("rotation_time"),
    }


def _check_url(url: Any) -> str:
    if not isinstance(url, str):
        raise WallpaperError("a wallpaper must be a url or a path")
    url = url.strip()
    if not url:
        raise WallpaperError("a wallpaper must not be empty")
    if len(url) > MAX_URL or any(ord(c) < 0x20 or ord(c) == 0x7f for c in url):
        raise WallpaperError("that wallpaper value is not usable")
    return url


def set_wallpaper(bus, url: Any) -> dict[str, Any]:
    """Set the wallpaper to ``url`` (an http(s) url or a local path)."""
    url = _check_url(url)
    msg_type = f"{_BASE}.set.wallpaper"
    reply = buswait.wait_for_response(
        bus, _msg(msg_type, {"url": url}), timeout=QUERY_TIMEOUT,
        reply_type=msg_type + ".response")
    if reply is None:
        return {"available": False, "url": url}
    return {"available": True, "url": (reply.data or {}).get("wallpaper", url)}


def next_wallpaper(bus) -> dict[str, Any]:
    """Move to the next wallpaper in the active provider's collection."""
    bus.emit(_msg(f"{_BASE}.change.wallpaper"))
    return {"ok": True}


def set_provider(bus, provider_name: Any) -> dict[str, Any]:
    """Choose which registered provider supplies wallpapers."""
    if not isinstance(provider_name, str) or not provider_name.strip():
        raise WallpaperError("a provider name is required")
    provider_name = provider_name.strip()
    if len(provider_name) > 255 or any(ord(c) < 0x20 for c in provider_name):
        raise WallpaperError("that provider name is not usable")
    bus.emit(_msg(f"{_BASE}.set.active.provider", {"provider_name": provider_name}))
    return {"ok": True, "provider_name": provider_name}


def set_auto_rotation(bus, enabled: bool) -> dict[str, Any]:
    """Turn automatic wallpaper rotation on or off."""
    suffix = "enable.auto.rotation" if enabled else "disable.auto.rotation"
    bus.emit(_msg(f"{_BASE}.{suffix}"))
    return {"ok": True, "auto_rotation": bool(enabled)}
