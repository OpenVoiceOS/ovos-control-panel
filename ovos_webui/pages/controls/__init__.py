"""Device: one of the control panel's own pages."""
from ovos_webui.pages.controls.api import routes

PAGE = {
    "api_version": 1,
    "id": "controls",
    "path": "/controls",
    "title": {"key": "nav.controls", "label": "Device"},
    "group": "everyday",
    "order": 40,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.controls", "label": "Device controls"},
    "i18n": "i18n",
    "routes": routes,
}
