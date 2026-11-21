"""Network: one of the control panel's own pages."""
from ovos_webui.pages.network.api import routes

PAGE = {
    "api_version": 1,
    "id": "network",
    "path": "/network",
    "title": {"key": "nav.network", "label": "Network"},
    "group": "everyday",
    "order": 50,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.network", "label": "Network"},
    "i18n": "i18n",
    "routes": routes,
}
