"""Skills: one of the control panel's own pages."""
from ovos_webui.pages.skills.api import routes

PAGE = {
    "api_version": 1,
    "id": "skills",
    "path": "/skills",
    "title": {"key": "nav.skills", "label": "Skills"},
    "group": "everyday",
    "order": 70,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.skills", "label": "Skills"},
    "i18n": "i18n",
    "routes": routes,
}
