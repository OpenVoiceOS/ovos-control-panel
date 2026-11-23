"""What the device can do, and which companion plugin each capability needs.

Several device controls — volume, the microphone, power — are not part of the
core stack: they are carried by PHAL plugins, and some of those run with root
through ``ovos-PHAL-admin``. This module answers, for each capability, whether
its plugin is installed and whether it needs the admin service, so the UI can
enable a control, or offer to install what it needs, instead of firing a bus
message into the void.

Nothing here runs a command; installation goes through the ordinary sandboxed
plugin installer, which already accepts ``ovos-PHAL-plugin-*`` names.

A plugin the table does not name can say what it provides, in its
``controlpanel.json``: ``"provides": ["volume", "power"]`` (a PHAL plugin for
other hardware, a browser tab). And a distribution chooses which missing
companions are offered for install, in ``webui.companions`` (a list of
capabilities; unset offers them all): a device with no Wi-Fi of its own has no
use for the network manager.
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
        "hint": "SSH and a factory reset, from the System page.",
    },
    "network": {
        "plugins": ["ovos-phal-plugin-network-manager", "ovos-PHAL-plugin-network-manager"],
        "admin": True,
        "label": "Wi-Fi setup",
        "hint": "Scan for and join Wi-Fi networks, with the ovos-control-panel-network "
                "extension. Needs this plugin, which runs with the admin service.",
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


def page_providers() -> dict[str, list[str]]:
    """Capability -> the packages whose ``controlpanel.json`` says they
    provide it (``"provides"``)."""
    out: dict[str, list[str]] = {}
    try:
        from ovos_webui import described
        found = described.discover()
    except Exception:  # noqa: BLE001 - a broken description adds nothing
        return out
    for f in found:
        provides = f.data.get("provides") if isinstance(f.data, dict) else None
        if not isinstance(provides, list):
            continue
        for key in provides:
            if key in CAPABILITIES and f.package not in out.setdefault(key, []):
                out[key].append(f.package)
    return out


def offered_companions() -> set[str] | None:
    """The capabilities whose plugin is offered for install when missing
    (``webui.companions``); None offers every one."""
    try:
        from ovos_webui import configio
        raw = configio.user_or_merged(["webui", "companions"])
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, list):
        return None
    return {k for k in raw if isinstance(k, str)}


def capability_status() -> dict[str, Any]:
    """Report, per capability, whether a providing plugin is installed."""
    from ovos_webui.pypi import installed_versions

    have = installed_versions()
    extra = page_providers()
    offered = offered_companions()
    out = {}
    for key, spec in CAPABILITIES.items():
        plugins = list(spec["plugins"]) + [p for p in extra.get(key, []) if p not in spec["plugins"]]
        provider = next((p for p in plugins if p.lower() in have), None)
        # the canonical (lowercase) package name to offer for install
        suggest = spec["plugins"][0]
        out[key] = {
            "label": spec["label"],
            "hint": spec["hint"],
            "installed": provider is not None,
            "provider": provider,
            "needs_admin": spec["admin"],
            "suggest": suggest,
            # missing and not offered by this distribution: the page leaves it out
            "offered": offered is None or key in offered,
        }
    return {"capabilities": out, "phal_plugins": installed_phal_plugins(have)}

