"""Personas: one of the control panel's own pages."""
from ovos_webui.pages.personas.api import routes

PAGE = {
    "api_version": 1,
    "id": "personas",
    "path": "/personas",
    "title": {"key": "nav.personas", "label": "Personas"},
    "group": "understanding",
    "order": 30,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.personas", "label": "Personas"},
    "i18n": "i18n",
    "routes": routes,
}
