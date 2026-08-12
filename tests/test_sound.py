"""Tests for the "Send over sound" (ggwave) panel.

Encoding and playback happen entirely in the browser: the server's job is
only to serve the authenticated page and the vendored ggwave library. These
tests cover that contract — nothing about audio encoding, since there is no
server-side code for it.
"""
from pathlib import Path

from ovos_webui.service import PAGES, STATIC_DIR

VENDOR_DIR = STATIC_DIR / "vendor" / "ggwave"


def test_sound_is_a_registered_page():
    assert PAGES["/sound"] == "sound.html"


def test_sound_page_requires_auth(token_client):
    r = token_client.get("/sound", headers={"sec-fetch-site": "same-origin"},
                         follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_sound_page_serves_once_authenticated(token_client):
    r = token_client.get("/sound", headers={"Authorization": "Bearer s3cret-token",
                                            "sec-fetch-site": "same-origin"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_sound_page_serves_without_a_token(client):
    r = client.get("/sound")
    assert r.status_code == 200
    assert "<nav" in r.text and "app.js" in r.text


def test_ggwave_library_is_vendored_on_disk():
    assert (VENDOR_DIR / "ggwave.js").is_file()
    assert (VENDOR_DIR / "ggwave.js").stat().st_size > 1000
    assert (VENDOR_DIR / "LICENSE.md").is_file()


def test_ggwave_license_credits_upstream():
    text = (VENDOR_DIR / "LICENSE.md").read_text(encoding="utf-8")
    assert "ggerganov/ggwave" in text
    assert "MIT" in text


def test_ggwave_asset_is_served(client):
    r = client.get("/static/vendor/ggwave/ggwave.js")
    assert r.status_code == 200


def test_sound_page_references_the_vendored_script_only(client):
    body = client.get("/sound").text
    assert '/static/vendor/ggwave/ggwave.js' in body
    for marker in ["cdn.", "unpkg.com", "jsdelivr", "googleapis", "//ajax.",
                   "raw.githubusercontent.com"]:
        assert marker not in body, f"/sound pulls in {marker}"


def test_sound_page_never_loads_a_remote_script_tag():
    body = Path(STATIC_DIR / "sound.html").read_text(encoding="utf-8")
    import re
    for src in re.findall(r'<script[^>]+src="([^"]+)"', body):
        assert src.startswith("/static/"), f"remote script source: {src}"
