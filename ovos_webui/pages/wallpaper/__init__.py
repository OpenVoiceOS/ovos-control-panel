"""Wallpaper: one of the control panel's own pages."""
PAGE = {
    "api_version": 1,
    "id": "wallpaper",
    "path": "/wallpaper",
    "title": {"key": "nav.wallpaper", "label": "Wallpaper"},
    "group": "screen",
    "order": 20,
    "needs": ["ovos-PHAL-plugin-wallpaper-manager"],
    "html": "page.html",
    "icon": "icon.svg",
}
