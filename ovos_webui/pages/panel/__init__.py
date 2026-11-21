"""The control panel's own settings: one of the control panel's own pages."""
from ovos_webui.pages.panel.api import routes

PAGE = {
    "api_version": 1,
    "id": "panel",
    "path": "/panel",
    "title": {"key": "nav.panel", "label": "Control panel"},
    "group": "maintenance",
    "order": 25,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.panel", "label": "The control panel's own settings"},
    "i18n": "i18n",
    "routes": routes,
}
