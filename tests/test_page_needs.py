"""Which pages the device can use, so the menu can leave the rest out."""
import json
import re
from pathlib import Path

from ovos_webui import phal
from ovos_webui.service import STATIC_DIR

ON_DEVICE = {"ovos-core": "2.1.1", "ovos-phal-plugin-system": "1.0.0"}


def test_a_need_is_met_by_any_of_its_packages():
    out = phal.page_needs(dict(ON_DEVICE, **{"ovos-plugin-common-play": "1.3.1"}))
    assert out["colocated"] is True
    assert out["needs"]["system"]["met"] is True
    assert out["needs"]["media"]["met"] is True
    assert out["needs"]["wallpaper"]["met"] is False
    assert out["needs"]["wallpaper"]["suggest"] == "ovos-PHAL-plugin-wallpaper-manager"


def test_package_names_are_matched_case_insensitively():
    # installed_versions() lowercases; the table keeps PyPI's own spelling
    out = phal.page_needs(dict(ON_DEVICE, **{"ovos-phal-plugin-mk1": "0.1.3"}))
    assert out["needs"]["mark1"]["met"] is True


def test_a_panel_running_apart_from_the_assistant_hides_nothing():
    # without the assistant's own packages, ours say nothing about the device
    out = phal.page_needs({"fastapi": "0.115"})
    assert out["colocated"] is False


def test_every_need_in_the_menu_has_packages_and_back():
    js = (Path(STATIC_DIR) / "app.js").read_text(encoding="utf-8")
    nav = json.loads(re.search(r"var NAV = (\[.*?\n  \]);", js, re.DOTALL).group(1))
    used = {item["needs"] for item in nav if item["needs"]}
    assert used == set(phal.PAGE_NEEDS)


def test_the_route_answers(client):
    r = client.get("/api/nav/needs")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"colocated", "needs"}
    assert set(body["needs"]) == set(phal.PAGE_NEEDS)


def test_the_route_needs_a_session(token_client):
    assert token_client.get("/api/nav/needs").status_code == 401
