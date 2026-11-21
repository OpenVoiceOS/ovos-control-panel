"""System: one of the control panel's own pages."""
from ovos_webui.phal import CAPABILITIES

from ovos_webui.pages.system.api import routes

PAGE = {
    "api_version": 1,
    "id": "system",
    "path": "/system",
    "title": {"key": "nav.system", "label": "System"},
    "group": "device",
    "order": 10,
    # SSH and factory reset are the system plugin's, the location the IP
    # geolocation plugin's
    "needs": CAPABILITIES["system"]["plugins"] + ["ovos-PHAL-plugin-ipgeo"],
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.system", "label": "System"},
    "i18n": "i18n",
    "routes": routes,
}
