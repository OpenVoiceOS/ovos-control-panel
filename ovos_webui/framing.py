"""Who may show the panel inside a page of their own (webui.frame_ancestors).

The panel says ``frame-ancestors 'none'``: no other page may put it in a
frame, which is right for a device on its own. A distribution may show the
panel inside its own page, though, as Emkay does over its face, also from the
house's own address when it is a satellite of Emkay Home. It says so in
configuration::

    {"webui": {"frame_ancestors": ["self", "https://house.local:8443"]}}

- ``"self"``: the panel's own host, on any port and either scheme. A
  distribution that serves its own pages from the same machine needs no
  more than this.
- An origin, ``https://name`` with an optional port (``:8443``, or ``:*``
  for any). No wildcards in the name, so it cannot become "anyone".

Anything else is skipped and named on the About page. Without the setting
nothing changes.
"""
from __future__ import annotations

import re
import time
from typing import Any

_ORIGIN_RE = re.compile(r"^https?://(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)"
                        r"(?::(?:\*|[0-9]{1,5}))?$")
_HOST_RE = re.compile(r"^(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$")

#: How long a read of webui.frame_ancestors is used before it is read again:
#: every response asks, and the setting seldom changes.
CACHE_SECONDS = 5.0
_cache: dict[str, Any] = {"at": 0.0, "value": None}


def read(webui: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """The allowed framers (``"self"`` and origins), and the problems."""
    raw = (webui or {}).get("frame_ancestors")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["webui.frame_ancestors: a list of \"self\" and origins"]
    allowed, problems = [], []
    for item in raw:
        if item == "self" or (isinstance(item, str) and _ORIGIN_RE.match(item)):
            if item not in allowed:
                allowed.append(item)
        else:
            problems.append(f"webui.frame_ancestors: {item!r} is not \"self\" or an origin (https://name:port)")
    return allowed, problems


def _hostname(host: str) -> str | None:
    """The name in a Host header, without its port; None when it is not a name."""
    host = (host or "").strip()
    if host.startswith("["):
        name = host[: host.find("]") + 1] if "]" in host else ""
    else:
        name = host.split(":", 1)[0]
    return name if name and _HOST_RE.match(name) else None


def policy(allowed: list[str], host: str) -> str:
    """The CSP ``frame-ancestors`` value for a response to ``host``."""
    if not allowed:
        return "frame-ancestors 'none'"
    parts = []
    for item in allowed:
        if item == "self":
            parts.append("'self'")
            name = _hostname(host)
            if name:
                parts += [f"https://{name}:*", f"http://{name}:*"]
        else:
            parts.append(item)
    return "frame-ancestors " + " ".join(dict.fromkeys(parts))


def allowed_now() -> list[str]:
    """webui.frame_ancestors as the configuration says now (cached briefly)."""
    now = time.monotonic()
    if _cache["value"] is None or now - _cache["at"] > CACHE_SECONDS:
        try:
            from ovos_webui import configio
            webui = configio.section("webui")
        except Exception:  # noqa: BLE001 - a broken config keeps the panel unframed
            webui = {}
        _cache["value"], _ = read(webui)
        _cache["at"] = now
    return _cache["value"]
