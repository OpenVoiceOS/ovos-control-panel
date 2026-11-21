"""Send over sound: one of the control panel's own pages."""
from ovos_webui.pages.sound.api import routes

PAGE = {
    "api_version": 1,
    "id": "sound",
    "path": "/sound",
    "title": {"key": "nav.sound", "label": "Send over sound"},
    "group": "maintenance",
    "order": 30,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.sound", "label": "Send over sound"},
    "i18n": "i18n",
    "routes": routes,
}
