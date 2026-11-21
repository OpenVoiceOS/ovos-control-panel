"""Translate: one of the control panel's own pages."""
from ovos_webui.pages.translate.api import routes

PAGE = {
    "api_version": 1,
    "id": "translate",
    "path": "/translate",
    "title": {"key": "nav.translate", "label": "Translate"},
    "group": "voice",
    "order": 30,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.translate", "label": "Translate a skill"},
    "i18n": "i18n",
    "routes": routes,
}
