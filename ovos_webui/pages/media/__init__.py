"""Media: one of the control panel's own pages."""
from ovos_webui.pages.media.api import routes

PAGE = {
    "api_version": 1,
    "id": "media",
    "path": "/media",
    "title": {"key": "nav.media", "label": "Media"},
    "group": "library",
    "order": 5,
    "needs": ["ovos-media", "ovos-plugin-common-play", "ovos-ocp-pipeline-plugin"],
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.media", "label": "Media"},
    "i18n": "i18n",
    "routes": routes,
}
