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


def _locale_codes():
    """Every shipped locale, by its file name (en, ar, pt, es, …)."""
    from pathlib import Path

    from ovos_webui.service import STATIC_DIR
    return sorted(p.stem for p in (Path(STATIC_DIR) / "i18n").glob("*.json"))


@pytest.mark.parametrize("code", _locale_codes())
def test_the_locale_files_are_served_and_valid(client, code):
    r = client.get(f"/static/i18n/{code}.json")
    assert r.status_code == 200
    data = r.json()
    assert data["nav.dashboard"] and data["dash.title"]


@pytest.mark.parametrize("code", [c for c in _locale_codes() if c != "en"])
def test_every_locale_has_the_same_keys_as_english(client, code):
    en = client.get("/static/i18n/en.json").json()
    other = client.get(f"/static/i18n/{code}.json").json()
    assert set(en) == set(other), (
        f"the {code} locale does not have exactly the keys English has: "
        f"missing {sorted(set(en) - set(other))}, extra {sorted(set(other) - set(en))}"
    )


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


def test_every_page_can_be_reached_from_the_navigation():
    """A page nobody can navigate to is a page nobody finds.

    `/setup` was served and documented for months while being absent from the
    rail, reachable only from two links on the dashboard -- so the page written
    for a first-time user was the one a first-time user could not find.
    """
    import re
    from pathlib import Path

    from ovos_webui.service import PAGES, STATIC_DIR

    nav = set(re.findall(r'\["(/[a-z0-9-]*)",\s*"nav\.',
                         (Path(STATIC_DIR) / "app.js").read_text(encoding="utf-8")))
    served = {route for route, _template in
              ((p[0], p[1]) if isinstance(p, (list, tuple)) else (p, None) for p in PAGES)}
    # the sign-in page is deliberately outside the rail: you are not signed in
    unreachable = sorted(served - nav - {"/login"})
    assert not unreachable, (
        f"these pages are served but not in the navigation: {unreachable}"
    )
