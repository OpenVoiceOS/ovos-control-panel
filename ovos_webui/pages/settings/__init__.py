"""Settings: one of the control panel's own pages."""
from ovos_webui.pages.settings.api import routes

PAGE = {
    "api_version": 1,
    "id": "settings",
    "path": "/config",
    "title": {"key": "nav.settings", "label": "Settings"},
    "group": "maintenance",
    "order": 20,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.settings", "label": "Settings"},
    "i18n": "i18n",
    "routes": routes,
}
