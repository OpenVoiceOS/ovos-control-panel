"""What the device can do, and which companion plugin each capability needs.

Several device controls — volume, the microphone, power — are not part of the
core stack: they are carried by PHAL plugins, and some of those run with root
through ``ovos-PHAL-admin``. This module answers, for each capability, whether
its plugin is installed and whether it needs the admin service, so the UI can
enable a control, or offer to install what it needs, instead of firing a bus
message into the void.

Nothing here runs a command; installation goes through the ordinary sandboxed
plugin installer, which already accepts ``ovos-PHAL-plugin-*`` names.
"""
from __future__ import annotations

from typing import Any

#: capability -> the PHAL plugins that can provide it (any one is enough),
#: whether it needs the admin (root) service, and a plain description.
CAPABILITIES: dict[str, dict[str, Any]] = {
    "volume": {
        "plugins": ["ovos-phal-plugin-alsa", "ovos-PHAL-plugin-alsa"],
        "admin": False,
        "label": "Volume",
        "hint": "Set how loud the device speaks and plays media.",
    },
    "power": {
        "plugins": ["ovos-phal-plugin-system", "ovos-PHAL-plugin-system"],
        "admin": False,
        "label": "Power",
        "hint": "Restart the services or reboot the device.",
    },
    "network": {
        "plugins": ["ovos-phal-plugin-wifi-setup", "ovos-PHAL-plugin-wifi-setup"],
        "admin": True,
        "label": "Wi-Fi setup",
        "hint": "Wi-Fi setup happens on the device screen, not here — this only "
                "shows whether the plugin is present.",
    },
}

#: The microphone mute lives in the listener, not a PHAL plugin, so it has no
#: package to install — it is available whenever the listener answers.
MIC_CAPABILITY = {
    "label": "Microphone",
    "hint": "Mute or unmute the microphone.",
}


def installed_phal_plugins() -> list[str]:
    """Return the installed ``ovos-*PHAL*-plugin-*`` distribution names."""
    from ovos_webui.pypi import classify, installed_versions

    return sorted(name for name in installed_versions()
                  if classify(name) == "phal")


def capability_status() -> dict[str, Any]:
    """Report, per capability, whether a providing plugin is installed."""
    from ovos_webui.pypi import installed_versions

    have = installed_versions()
    out = {}
    for key, spec in CAPABILITIES.items():
        provider = next((p for p in spec["plugins"] if p.lower() in have), None)
        # the canonical (lowercase) package name to offer for install
        suggest = spec["plugins"][0]
        out[key] = {
            "label": spec["label"],
            "hint": spec["hint"],
            "installed": provider is not None,
            "provider": provider,
            "needs_admin": spec["admin"],
            "suggest": suggest,
        }
    return {"capabilities": out, "phal_plugins": installed_phal_plugins()}
