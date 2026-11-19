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
    "system": {
        "plugins": ["ovos-phal-plugin-system", "ovos-PHAL-plugin-system"],
        "admin": False,
        "label": "System",
        "hint": "SSH, factory reset, and the device language, from the System page.",
    },
    "network": {
        "plugins": ["ovos-phal-plugin-network-manager", "ovos-PHAL-plugin-network-manager"],
        "admin": True,
        "label": "Wi-Fi setup",
        "hint": "Scan for and join Wi-Fi networks from the Network page. Needs "
                "this plugin, which runs with the admin service.",
    },
    # Not a PHAL plugin — it is an audio transformer plugin that listens for
    # ggwave sound. It still fits this table: one package, no admin service,
    # a plain "is it there" check for the UI to gate the listening toggle on.
    "ggwave": {
        "plugins": ["ovos-audio-transformer-plugin-ggwave"],
        "admin": False,
        "label": "Send over sound listener",
        "hint": "Lets this device hear data sent over sound from the Send over "
                "sound page.",
    },
}

#: The microphone mute lives in the listener, not a PHAL plugin, so it has no
#: package to install — it is available whenever the listener answers.
MIC_CAPABILITY = {
    "label": "Microphone",
    "hint": "Mute or unmute the microphone.",
}


def installed_phal_plugins(have: dict[str, str] | None = None) -> list[str]:
    """Return the installed ``ovos-*PHAL*-plugin-*`` distribution names."""
    from ovos_webui.pypi import classify, installed_versions

    have = installed_versions() if have is None else have
    return sorted(name for name in have if classify(name) == "phal")


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
    return {"capabilities": out, "phal_plugins": installed_phal_plugins(have)}


#: What a page in the menu can say it ``needs`` (see NAV in app.js), and the
#: packages that provide it -- any one is enough. A page whose need is not met
#: is left out of the menu, and says what it needs if you reach it anyway.
PAGE_NEEDS: dict[str, list[str]] = {
    "system": CAPABILITIES["system"]["plugins"],
    "sensors": ["ovos-PHAL-sensors"],
    "media": ["ovos-media", "ovos-plugin-common-play", "ovos-ocp-pipeline-plugin"],
    "app-launcher": ["ovos-PHAL-plugin-app-launcher"],
    "wallpaper": ["ovos-PHAL-plugin-wallpaper-manager"],
    "mark1": ["ovos-PHAL-plugin-mk1"],
}

#: Packages that only exist where the assistant itself runs. Without any of
#: them the panel is running apart from the device (in its own container, for
#: example), its packages say nothing about the device's, and no page is hidden.
_ASSISTANT_PACKAGES = ("ovos-core", "ovos-audio", "ovos-dinkum-listener", "ovos-phal")


def page_needs(have: dict[str, str] | None = None) -> dict[str, Any]:
    """Report, per page need, whether a providing package is installed here."""
    from ovos_webui.pypi import installed_versions

    have = installed_versions() if have is None else have
    colocated = any(p in have for p in _ASSISTANT_PACKAGES)
    needs = {}
    for key, plugins in PAGE_NEEDS.items():
        needs[key] = {
            "met": any(p.lower() in have for p in plugins),
            "suggest": plugins[0],
        }
    return {"colocated": colocated, "needs": needs}
