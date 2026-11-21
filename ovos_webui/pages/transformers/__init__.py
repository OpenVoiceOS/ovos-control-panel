"""Transformers: one of the control panel's own pages."""
from ovos_webui.pages.transformers.api import routes

PAGE = {
    "api_version": 1,
    "id": "transformers",
    "path": "/transformers",
    "title": {"key": "nav.transformers", "label": "Transformers"},
    "group": "understanding",
    "order": 20,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.transformers", "label": "Transformers"},
    "i18n": "i18n",
    "routes": routes,
}
