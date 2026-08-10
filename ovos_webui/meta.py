"""Report the versions of the OVOS packages that are installed."""
from __future__ import annotations

from typing import Any

PREFIXES = ("ovos", "hivemind", "neon", "mycroft", "padatious", "padacioso", "adapt")


def installed_packages() -> list[dict[str, str]]:
    """Return the name and version of each installed OVOS related package."""
    from importlib.metadata import distributions

    seen: dict[str, str] = {}
    for dist in distributions():
        try:
            name = dist.metadata["Name"]
        except (KeyError, TypeError):  # pragma: no cover - broken metadata
            continue
        if not name:
            continue
        lowered = name.lower().replace("_", "-")
        if not lowered.startswith(PREFIXES):
            continue
        seen[lowered] = dist.version or "unknown"
    return [{"name": k, "version": v} for k, v in sorted(seen.items())]


def about(request_host: str = "") -> dict[str, Any]:
    """Return everything the About page shows."""
    from ovos_webui.version import __version__

    host = request_host.split(":")[0] or "localhost"
    return {
        "version": __version__,
        "packages": installed_packages(),
        "links": [
            {"label": "Bus monitor on this device", "url": f"http://{host}:8000/"},
            {"label": "ovos-busmon", "url": "https://github.com/OpenVoiceOS/ovos-busmon"},
            {"label": "ovos-yaml-editor", "url": "https://github.com/OpenVoiceOS/ovos-yaml-editor"},
            {"label": "ovos-config", "url": "https://github.com/OpenVoiceOS/ovos-config"},
            {"label": "OVOS documentation", "url": "https://openvoiceos.github.io/ovos-technical-manual/"},
            {"label": "OpenVoiceOS", "url": "https://openvoiceos.org"},
        ],
    }
