"""Backup: one of the control panel's own pages."""
from ovos_webui.pages.backup.api import routes

PAGE = {
    "api_version": 1,
    "id": "backup",
    "path": "/backup",
    "title": {"key": "nav.backup", "label": "Backup"},
    "group": "everyday",
    "order": 80,
    "html": "page.html",
    "icon": "icon.svg",
    "heading": {"key": "hdr.backup", "label": "Backup and restore"},
    "i18n": "i18n",
    "routes": routes,
}
