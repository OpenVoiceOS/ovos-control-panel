"""Servers: one of the control panel's own pages."""
from ovos_webui.pages.servers.api import routes

PAGE = {
    "api_version": 1,
    "id": "servers",
    "path": "/servers",
    "title": {"key": "nav.servers", "label": "Servers"},
    "group": "voice",
    "order": 20,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.servers", "label": "Servers"},
    "i18n": "i18n",
    "routes": routes,
}
