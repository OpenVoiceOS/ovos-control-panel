"""Which pages the device can use, so the menu can leave the rest out."""
from ovos_webui import pages

ON_DEVICE = {"ovos-core": "2.1.1", "ovos-phal-plugin-system": "1.0.0"}
REG = pages.load()


def test_a_page_is_usable_with_any_of_its_packages():
    out = pages.needs(REG, ON_DEVICE)
    assert out["colocated"] is True
    assert out["needs"]["network"]["met"] is False


def test_package_names_are_matched_case_insensitively():
    # installed_versions() lowercases; the pages keep PyPI's own spelling
    out = pages.needs(REG, dict(ON_DEVICE, **{"ovos-phal-plugin-connectivity-events": "0.1"}))
    assert out["needs"]["network"]["met"] is True


def test_a_panel_running_apart_from_the_assistant_hides_nothing():
    # without the assistant's own packages, ours say nothing about the device
    assert pages.needs(REG, {"fastapi": "0.115"})["colocated"] is False
    assert pages.colocated({"fastapi": "0.115"}) is False


def test_only_pages_with_needs_are_reported():
    out = pages.needs(REG, ON_DEVICE)
    assert set(out["needs"]) == {"network"}


def test_the_route_answers(client):
    r = client.get("/api/nav/needs")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"colocated", "needs"}
    assert set(body["needs"]) == {p.id for p in REG.pages if p.needs}


def test_the_route_needs_a_session(token_client):
    assert token_client.get("/api/nav/needs").status_code == 401
