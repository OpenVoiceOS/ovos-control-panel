"""Mark-1 faceplate: one of the control panel's own pages."""
PAGE = {
    "api_version": 1,
    "id": "mark1",
    "path": "/mark1",
    "title": {"key": "nav.mark1", "label": "Mark-1 faceplate"},
    "group": "screen",
    "order": 30,
    "needs": ["ovos-PHAL-plugin-mk1"],
    "html": "page.html",
    "icon": "icon.svg",
}
