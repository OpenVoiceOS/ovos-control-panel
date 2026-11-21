"""Apps: one of the control panel's own pages."""
from ovos_webui.pages.apps.routes import routes

PAGE = {
    "api_version": 1,
    "id": "apps",
    "path": "/apps",
    "title": {"key": "nav.apps", "label": "Apps"},
    "group": "screen",
    "order": 10,
    "needs": ["ovos-PHAL-plugin-app-launcher"],
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.apps", "label": "Apps"},
    "i18n": "i18n",
    "routes": routes,
}
