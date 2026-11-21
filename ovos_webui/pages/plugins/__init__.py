"""Plugins: one of the control panel's own pages."""
from ovos_webui.pages.plugins.api import routes

PAGE = {
    "api_version": 1,
    "id": "plugins",
    "path": "/plugins",
    "title": {"key": "nav.plugins", "label": "Plugins"},
    "group": "maintenance",
    "order": 10,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.plugins", "label": "Plugins"},
    "i18n": "i18n",
    "routes": routes,
}
