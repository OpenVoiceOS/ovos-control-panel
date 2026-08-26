"""Report the versions of the OVOS packages that are installed."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

PREFIXES = ("ovos", "hivemind", "neon", "mycroft", "padatious", "padacioso", "adapt")


def installed_packages() -> list[dict[str, str]]:
    """Return the name and version of each installed OVOS related package."""
    from importlib.metadata import distributions

    seen: dict[str, str] = {}
    for dist in distributions():
        try:
            name = dist.metadata["Name"]
            version = dist.version
        except (KeyError, TypeError):  # pragma: no cover - broken metadata
            continue
        if not name:
            continue
        lowered = name.lower().replace("_", "-")
        if not lowered.startswith(PREFIXES):
            continue
        seen[lowered] = version or "unknown"
    return [{"name": k, "version": v} for k, v in sorted(seen.items())]


def link_host(request_host: str) -> str:
    """Return the host part of a Host header, ready to put back in a URL.

    Splitting on the first colon is wrong for an IPv6 literal, which contains
    colons of its own and arrives bracketed: ``[::1]:8500`` would become ``[``.
    The brackets are part of the URL syntax rather than of the address, so they
    are put back.
    """
    host = urlsplit(f"//{request_host.strip()}").hostname or ""
    if not host:
        return "localhost"
    return f"[{host}]" if ":" in host else host


def about(request_host: str = "") -> dict[str, Any]:
    """Return everything the About page shows."""
    from ovos_webui.version import __version__

    host = link_host(request_host)
    return {
        "version": __version__,
        "packages": installed_packages(),
        "links": [
            {"label": "Bus monitor on this device", "url": f"http://{host}:8005/"},
            {"label": "ovos-busmon", "url": "https://github.com/OpenVoiceOS/ovos-busmon"},
            {"label": "ovos-yaml-editor", "url": "https://github.com/OpenVoiceOS/ovos-yaml-editor"},
            {"label": "ovos-config", "url": "https://github.com/OpenVoiceOS/ovos-config"},
            {"label": "OVOS documentation", "url": "https://openvoiceos.github.io/ovos-technical-manual/"},
            {"label": "OpenVoiceOS", "url": "https://openvoiceos.org"},
        ],
    }
