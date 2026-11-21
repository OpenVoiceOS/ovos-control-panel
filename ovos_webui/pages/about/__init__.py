"""About: one of the control panel's own pages."""
from ovos_webui.pages.about.api import routes

PAGE = {
    "api_version": 1,
    "id": "about",
    "path": "/about",
    "title": {"key": "nav.about", "label": "About"},
    "group": "everyday",
    "order": 90,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.about", "label": "About this device"},
    "i18n": "i18n",
    "routes": routes,
}
