"""Intents: one of the control panel's own pages."""
from ovos_webui.pages.intents.api import routes

PAGE = {
    "api_version": 1,
    "id": "intents",
    "path": "/intents",
    "title": {"key": "nav.intents", "label": "Intents"},
    "group": "understanding",
    "order": 10,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.intents", "label": "Intents"},
    "i18n": "i18n",
    "routes": routes,
}
