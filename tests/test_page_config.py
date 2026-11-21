"""webui.pages, webui.groups and webui.branding: what a distribution or the
user can change about the menu and the look, with configuration only."""
import json
import re

import pytest

from ovos_webui import branding, configio, pages
from ovos_webui.fsutils import atomic_write

REG = pages.load()


def _set_webui(webui):
    atomic_write(configio.user_config_path(), json.dumps({"webui": webui}))


def _menu(client, path="/about"):
    body = client.get(path).text
    return json.loads(re.search(r'id="ovos-nav">(.*?)</script>', body).group(1))


# ── webui.pages and webui.groups ──────────────────────────────────────────────
def test_prefs_reads_and_checks_the_settings():
    p = pages.prefs({
        "pages": {"disabled": ["mark1", "about", 3], "move": {"media": {"group": "screen", "order": 5}}},
        "groups": {"order": ["screen", "voice"], "rename": {"device": {"label": "Hardware"}, "x": {}}}})
    assert p.disabled == {"mark1"}
    assert p.move == {"media": {"group": "screen", "order": 5}}
    assert p.group_order == ["screen", "voice"]
    assert p.rename["device"]["label"] == "Hardware"
    assert any("core page" in x for x in p.problems)
    assert any("webui.groups.rename.x" in x for x in p.problems)


def test_nothing_set_means_the_menu_as_it_ships():
    assert REG.nav(pages.prefs({})) == REG.nav()


def test_the_menu_follows_the_settings():
    nav = REG.nav(pages.prefs({
        "pages": {"disabled": ["mark1"], "move": {"media": {"group": "screen", "order": 5}}},
        "groups": {"order": ["screen"], "rename": {"device": {"label": "Hardware"}}}}))
    ids = [p["id"] for p in nav["pages"]]
    assert "mark1" not in ids
    media = [p for p in nav["pages"] if p["id"] == "media"][0]
    assert media["group"] == "screen"
    screen = [p["id"] for p in nav["pages"] if p["group"] == "screen"]
    assert screen[0] == "media", "order 5 puts it first in the group"
    advanced = [g["id"] for g in nav["groups"] if g["level"] == "advanced"]
    assert advanced[0] == "screen"
    assert [g for g in nav["groups"] if g["id"] == "device"][0]["label"] == "Hardware"


def test_a_page_turned_off_answers_nothing(client):
    assert client.get("/api/sensors").status_code != 404
    _set_webui({"pages": {"disabled": ["sensors"]}})
    assert client.get("/sensors").status_code == 404
    assert client.get("/api/sensors").status_code == 404, "its routes go too"
    assert "sensors" not in [p["id"] for p in _menu(client)["pages"]]
    listed = {p["id"]: p["disabled"] for p in client.get("/api/pages").json()["pages"]}
    assert listed["sensors"] is True and listed["about"] is False


def test_a_core_page_cannot_be_turned_off(client):
    _set_webui({"pages": {"disabled": ["plugins"]}})
    assert client.get("/plugins").status_code == 200
    assert any("core page" in x for x in client.get("/api/pages").json()["settings"])


def test_a_change_shows_on_the_next_page_load(client):
    assert "mark1" in [p["id"] for p in _menu(client)["pages"]]
    _set_webui({"pages": {"disabled": ["mark1"]}})
    assert "mark1" not in [p["id"] for p in _menu(client)["pages"]]


# ── webui.branding ───────────────────────────────────────────────────────────
def test_branding_takes_only_known_variables_and_plain_colours():
    brand = branding.read({"name": "Emkay", "colors": {
        "accent": "#1f6feb", "accent-strong": "rgb(17, 88, 199)",
        "bg": "red; } body { display: none", "font": "#000", "ink": "url(x)"}})
    assert brand["name"] == "Emkay"
    assert brand["colors"] == {"accent": "#1f6feb", "accent-strong": "rgb(17, 88, 199)"}
    css = branding.css(brand)
    assert "--accent: #1f6feb;" in css and "display" not in css and "url(" not in css


def test_a_name_with_markup_is_not_used():
    assert branding.read({"name": "<script>x</script>"})["name"] == branding.DEFAULT_NAME
    assert branding.read({"name": "   "})["name"] == branding.DEFAULT_NAME


def test_dark_colours_win_however_dark_mode_was_chosen():
    css = branding.css(branding.read({"colors_dark": {"accent": "#ff8800"}}))
    assert "prefers-color-scheme: dark" in css and ':root[data-theme="dark"]' in css


def test_hard_to_read_colours_are_named():
    assert branding.warnings(branding.read({"colors": {"accent-strong": "#eeeeee"}}))
    assert branding.warnings(branding.read({"colors": {"accent-strong": "#1158c7"}})) == []
    assert branding.contrast("#000000", "#ffffff") == pytest.approx(21.0)


def test_the_panel_wears_the_name_and_colours(client):
    _set_webui({"branding": {"name": "Emkay", "colors": {"accent": "#1f6feb"}}})
    page = client.get("/about").text
    assert "<title>About — Emkay</title>" in page
    assert '<link rel="stylesheet" href="/static/branding.css">' in page
    assert "<h1>Emkay</h1>" in client.get("/").text, "the Dashboard's heading is the name"
    assert "--accent: #1f6feb;" in client.get("/static/branding.css").text
    login = client.get("/login").text
    assert "— Emkay</title>" in login and "<h1>Emkay</h1>" in login
    assert client.get("/api/pages").json()["branding"]["name"] == "Emkay"


def test_without_branding_nothing_changes(client):
    assert "<h1>OpenVoiceOS</h1>" in client.get("/").text
    assert client.get("/static/branding.css").text.strip() == "/* webui.branding */"
    assert client.get("/static/branding/logo").status_code == 404


def test_a_logo_replaces_the_waveform(client, tmp_path):
    logo = tmp_path / "logo.svg"
    logo.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    _set_webui({"branding": {"logo": str(logo)}})
    page = client.get("/about").text
    assert 'class="brand-logo"' in page and 'class="wave"' not in page
    r = client.get("/static/branding/logo")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("name, size", [("logo.html", 10), ("logo.png", 600 * 1024)])
def test_a_logo_of_the_wrong_kind_or_size_is_not_served(client, tmp_path, name, size):
    logo = tmp_path / name
    logo.write_bytes(b"x" * size)
    _set_webui({"branding": {"logo": str(logo)}})
    assert client.get("/static/branding/logo").status_code == 404
    assert 'class="wave"' in client.get("/about").text


def test_branding_is_readable_before_sign_in(token_client):
    assert token_client.get("/static/branding.css").status_code == 200


def test_a_section_keeps_the_system_layer_under_the_users():
    merged = configio._deep_merge({"branding": {"name": "Emkay", "colors": {"accent": "#111111"}}},
                                  {"release_channel": "alpha", "branding": {"colors": {"ink": "#000000"}}})
    assert merged == {"branding": {"name": "Emkay", "colors": {"accent": "#111111", "ink": "#000000"}},
                      "release_channel": "alpha"}
