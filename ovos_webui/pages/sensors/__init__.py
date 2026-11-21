"""Sensors: one of the control panel's own pages."""
PAGE = {
    "api_version": 1,
    "id": "sensors",
    "path": "/sensors",
    "title": {"key": "nav.sensors", "label": "Sensors"},
    "group": "device",
    "order": 20,
    "needs": ["ovos-PHAL-sensors"],
    "html": "page.html",
    "icon": "icon.svg",
}
