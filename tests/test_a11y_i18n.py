"""Accessibility and internationalisation of the served pages."""
import json

import pytest
from fastapi.testclient import TestClient

from ovos_webui.service import create_app

PAGES = ["/", "/config", "/skills", "/plugins", "/personas", "/translate",
         "/backup", "/about", "/transformers", "/intents", "/apps", "/wallpaper", "/sensors"]


@pytest.mark.parametrize("route", PAGES)
def test_every_page_has_the_accessibility_landmarks(client, route):
    body = client.get(route).text
    assert 'class="skip"' in body, "no skip-to-content link"
    assert 'href="#main"' in body
    assert 'id="main"' in body and "tabindex" in body
    assert "aria-label" in body  # the nav names itself


@pytest.mark.parametrize("route", PAGES)
def test_every_page_is_marked_for_translation(client, route):
    body = client.get(route).text
    assert 'data-i18n="nav.dashboard"' in body, "nav is not translatable"


def test_the_status_gives_the_language_to_a_signed_in_caller(bus):
    app = create_app(bus=bus, host="127.0.0.1", token=None, connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500") as c:
        assert "lang" in c.get("/api/status").json()


def test_a_stranger_is_not_told_the_language(token_client):
    # No token supplied: the language must not leak with everything else.
    assert "lang" not in token_client.get("/api/status").json()


@pytest.mark.parametrize("code", ["en", "ar"])
def test_the_locale_files_are_served_and_valid(client, code):
    r = client.get(f"/static/i18n/{code}.json")
    assert r.status_code == 200
    data = r.json()
    assert data["nav.dashboard"] and data["dash.title"]


def test_english_and_arabic_have_the_same_keys(client):
    en = client.get("/static/i18n/en.json").json()
    ar = client.get("/static/i18n/ar.json").json()
    assert set(en) == set(ar), "the Arabic locale is missing keys English has"


def test_every_i18n_key_used_on_a_page_exists_in_the_locales():
    """Every literal data-i18n / data-i18n-attr / t("key", …) reference in the
    shipped HTML and JS must have an entry in en.json (and, by the parity test
    above, in ar.json). Catches a page that ships a key with no translation.
    Keys built at runtime by string concatenation are not literals and are
    skipped — they cannot be checked statically."""
    import re
    from pathlib import Path

    from ovos_webui.service import STATIC_DIR

    en = json.loads((Path(STATIC_DIR) / "i18n" / "en.json").read_text(encoding="utf-8"))
    key_re = re.compile(r'([a-zA-Z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9]+)+)')
    used: set[str] = set()
    for path in sorted(Path(STATIC_DIR).glob("*.html")) + [Path(STATIC_DIR) / "app.js"]:
        text = path.read_text(encoding="utf-8")
        for key in re.findall(r'data-i18n="([a-zA-Z0-9_.]+)"', text):
            used.add(key)
        for pairs in re.findall(r'data-i18n-attr="([^"]+)"', text):
            for pair in pairs.split(";"):
                bits = pair.split(":")
                if len(bits) == 2 and key_re.fullmatch(bits[1].strip()):
                    used.add(bits[1].strip())
        # t("key", …) or t("key") — a literal key ends at the closing quote
        # followed by a comma or a paren, so a concatenated key like t("x." + y)
        # is not matched.
        for key in re.findall(r'\bt\(\s*"([a-zA-Z0-9_.]+)"\s*[,)]', text):
            used.add(key)

    missing = sorted(k for k in used if k not in en)
    assert not missing, f"i18n keys used on a page but missing from en.json: {missing}"
