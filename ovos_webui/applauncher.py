"""Launch and close the desktop applications a device knows about.

All of this is an existing bus query served by ``ovos-PHAL-plugin-app-launcher``
(no new message type). The messages and their replies were read from that
plugin's source:

- ``ovos.phal.app_launcher.list`` → ``…list.response`` ``{"apps": [{"name", "exec"}]}``
- ``ovos.phal.app_launcher.launch`` (``{"name"}``) → ``…launch.response``
  ``{"name", "success": true}`` or ``{"name", "error": "…"}``
- ``ovos.phal.app_launcher.close`` (``{"name"}``) → ``…close.response`` (same shape)

Every query has a hard deadline through :func:`ovos_webui.buswait.wait_for_response`,
so a device without the app-launcher plugin reports ``available: False`` instead
of hanging.
"""
from __future__ import annotations

from typing import Any

from ovos_webui import buswait

QUERY_TIMEOUT = 5.0
#: Launching can be slow (a heavy app starting), so give it a longer deadline.
LAUNCH_TIMEOUT = 10.0
MAX_NAME = 255


class AppLauncherError(ValueError):
    """Raised when an application name is not usable."""


def _msg(msg_type: str, data: dict[str, Any] | None = None):
    from ovos_bus_client.message import Message

    return Message(msg_type, data or {}, {"source": "ovos-webui"})


def list_apps(bus) -> dict[str, Any]:
    """Return the launchable applications the device knows about."""
    reply = buswait.wait_for_response(
        bus, _msg("ovos.phal.app_launcher.list"), timeout=QUERY_TIMEOUT,
        reply_type="ovos.phal.app_launcher.list.response")
    if reply is None:
        return {"available": False, "apps": []}
    payload = reply.data or {}
    apps = []
    for app in payload.get("apps") or []:
        if isinstance(app, dict) and isinstance(app.get("name"), str):
            apps.append({"name": app["name"], "exec": app.get("exec")})
    return {"available": True, "apps": apps}


def _check_name(name: Any) -> str:
    if not isinstance(name, str):
        raise AppLauncherError("application name must be text")
    name = name.strip()
    if not name:
        raise AppLauncherError("application name must not be empty")
    if len(name) > MAX_NAME or any(ord(c) < 0x20 or ord(c) == 0x7f for c in name):
        raise AppLauncherError("application name must be a single short line")
    return name


def _do(bus, msg_type: str, name: str) -> dict[str, Any]:
    reply = buswait.wait_for_response(
        bus, _msg(msg_type, {"name": name}), timeout=LAUNCH_TIMEOUT,
        reply_type=msg_type + ".response")
    if reply is None:
        return {"available": False, "name": name}
    payload = reply.data or {}
    return {"available": True, "name": payload.get("name", name),
            "success": bool(payload.get("success")),
            "error": payload.get("error")}


def launch(bus, name: Any) -> dict[str, Any]:
    """Launch an application by name."""
    return _do(bus, "ovos.phal.app_launcher.launch", _check_name(name))


def close(bus, name: Any) -> dict[str, Any]:
    """Close a running application by name."""
    return _do(bus, "ovos.phal.app_launcher.close", _check_name(name))
