"""System: one of the control panel's own pages."""
from ovos_webui.phal import CAPABILITIES

PAGE = {
    "api_version": 1,
    "id": "system",
    "path": "/system",
    "title": {"key": "nav.system", "label": "System"},
    "group": "device",
    "order": 10,
    "needs": CAPABILITIES["system"]["plugins"],
    "html": "page.html",
    "icon": "icon.svg",
}
