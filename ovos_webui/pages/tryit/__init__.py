"""Try it: one of the control panel's own pages."""
from ovos_webui.pages.tryit.api import routes

PAGE = {
    "api_version": 1,
    "id": "tryit",
    "path": "/tryit",
    "title": {"key": "nav.tryit", "label": "Try it"},
    "group": "everyday",
    "order": 30,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.tryit", "label": "Try it"},
    "i18n": "i18n",
    "routes": routes,
}
