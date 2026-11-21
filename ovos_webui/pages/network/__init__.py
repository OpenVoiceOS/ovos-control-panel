"""Network: one of the control panel's own pages."""
from ovos_webui.phal import CAPABILITIES

from ovos_webui.pages.network.api import routes

PAGE = {
    "api_version": 1,
    "id": "network",
    "path": "/network",
    "title": {"key": "nav.network", "label": "Network"},
    "group": "everyday",
    "order": 50,
    # Wi-Fi is the network-manager plugin's, the internet check the
    # connectivity plugin's. A device with neither (an Emkay in a browser, a
    # container) has nothing to show here.
    "needs": CAPABILITIES["network"]["plugins"] + ["ovos-PHAL-plugin-connectivity-events"],
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.network", "label": "Network"},
    "i18n": "i18n",
    "routes": routes,
}
