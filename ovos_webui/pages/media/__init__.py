"""Media: one of the control panel's own pages."""
PAGE = {
    "api_version": 1,
    "id": "media",
    "path": "/media",
    "title": {"key": "nav.media", "label": "Media"},
    "group": "device",
    "order": 30,
    "needs": ["ovos-media", "ovos-plugin-common-play", "ovos-ocp-pipeline-plugin"],
    "html": "page.html",
    "icon": "icon.svg",
}
