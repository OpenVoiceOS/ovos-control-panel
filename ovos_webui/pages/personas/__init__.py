"""Personas: one of the control panel's own pages."""
from ovos_webui.pages.personas.api import routes

PAGE = {
    "api_version": 1,
    "id": "personas",
    "path": "/personas",
    "title": {"key": "nav.personas", "label": "Personas"},
    "group": "understanding",
    "order": 30,
    # a persona only answers where ovos-persona is installed; on a device
    # without it the menu leaves the page out (and the page says what to install)
    "needs": ["ovos-persona"],
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.personas", "label": "Personas"},
    "i18n": "i18n",
    "routes": routes,
}
