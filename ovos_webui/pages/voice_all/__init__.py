"""All voice settings: one of the control panel's own pages."""
PAGE = {
    "api_version": 1,
    "id": "voice-all",
    "path": "/voice-all",
    "title": {"key": "nav.voiceAll", "label": "All voice settings"},
    "group": "voice",
    "order": 10,
    "html": ("ovos_webui.pages.voice", "page.html"),
    "icon": "icon.svg",
}
