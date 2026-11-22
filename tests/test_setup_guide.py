"""The Setup guide a distribution can choose (webui.setup): the panel's own
steps by default, its choice of them in its order, and described pages as
steps of their own."""
import json

import pytest
from fastapi.testclient import TestClient

from ovos_webui import configio, described, setupguide
from ovos_webui.service import create_app

PAIR = {
    "controlpanel": 1, "id": "house", "title": {"key": "house.title", "en": "The house"},
    "heading": {"key": "house.heading", "en": "Devices in the house"},
    "bus": "ovos.house.",
    "blocks": [{"type": "list", "query": "ovos.house.devices", "items": "devices",
                "empty": {"key": "house.none", "en": "No devices yet"}}],
}
OTHER = dict(PAIR, id="other", title={"key": "other.title", "en": "Other"}, heading=None, bus="ovos.other.",
             blocks=[{"type": "text", "text": {"key": "other.intro", "en": "Hi"}}])


def set_setup(value, **webui):
    """Put webui.setup (and anything else in webui) in the user's layer."""
    path = configio.user_config_path()
    path.write_text(json.dumps({"webui": dict(webui, setup=value)}), encoding="utf-8")


@pytest.fixture
def client(bus, monkeypatch, tmp_path):
    found = []
    for page, package, module in ((PAIR, "ovos-phal-plugin-house", "ovos_phal_plugin_house"),
                                  ({k: v for k, v in OTHER.items() if v is not None},
                                   "ovos-skill-other", "ovos_skill_other")):
        root = tmp_path / module
        (root / "locale" / "da-DK").mkdir(parents=True)
        (root / "locale" / "da-DK" / "controlpanel.json").write_text(
            '{"house.heading": "Enheder i huset", "house.intro": "Lad os komme i gang"}', encoding="utf-8")
        found.append(described.Found(package, "1.0", module, root, page))
    monkeypatch.setattr(described, "discover", lambda: found)
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin", "Authorization": "Bearer s3cret-token"}) as c:
        yield c


def ids(guide):
    return [s["id"] for s in guide["steps"]]


def test_without_a_choice_the_guide_is_the_panels_own(client):
    g = client.get("/api/setup/guide").json()
    assert ids(g) == list(setupguide.STEPS) == ["token", "language", "voice", "speak", "tryit", "wake"]
    assert g["custom"] is False and g["intro"] is None and g["problems"] == []


def test_a_distribution_chooses_the_steps_and_their_order(client):
    set_setup({"steps": ["language", "voice", "tryit"]})
    g = client.get("/api/setup/guide").json()
    assert ids(g) == ["language", "voice", "tryit"] and g["custom"] is True


def test_a_described_page_is_a_step_with_its_heading_and_blocks(client):
    set_setup({"steps": ["language", "house", "tryit"]})
    g = client.get("/api/setup/guide").json()
    assert ids(g) == ["language", "house", "tryit"]
    step = g["steps"][1]
    assert step["heading"] == "Devices in the house" and step["heading_key"] == "house.heading"
    assert step["page"]["id"] == "house" and step["page"]["blocks"][0]["type"] == "list"
    # the strings the browser draws it with, in English too
    assert step["page"]["en"]["house.none"] == "No devices yet"
    assert client.get("/static/i18n/da.json").json()["house.heading"] == "Enheder i huset"


def test_a_steps_page_talks_to_its_package_as_on_its_own_page(client, bus):
    """The step is drawn with the page's own refs, so its requests go through
    the same bridge, with the same checks."""
    bus.on("ovos.house.devices", lambda m: bus.emit(m.response({"devices": [{"id": "kitchen"}]})))
    set_setup({"steps": ["house"]})
    ref = client.get("/api/setup/guide").json()["steps"][0]["page"]["blocks"][0]["ref"]
    r = client.post("/api/cp/house/query", json={"ref": ref})
    assert r.status_code == 200 and r.json()["devices"] == [{"id": "kitchen"}]


@pytest.mark.parametrize("steps, left, problem", [
    (["language", "nowhere", "tryit"], ["language", "tryit"], "no step or page nowhere"),
    (["language", "language", "tryit"], ["language", "tryit"], "named twice"),
    (["language", "about", "tryit"], ["language", "tryit"], "not a described page"),
])
def test_a_step_that_cannot_be_shown_is_left_out_and_named(client, steps, left, problem):
    set_setup({"steps": steps})
    g = client.get("/api/setup/guide").json()
    assert ids(g) == left
    assert any(problem in p for p in g["problems"]), g["problems"]
    # the About page lists it with the other settings it could not use
    assert any(problem in p for p in client.get("/api/pages").json()["settings"])


def test_a_page_that_is_turned_off_is_not_a_step(client):
    set_setup({"steps": ["language", "house"]}, pages={"disabled": ["house"]})
    g = client.get("/api/setup/guide").json()
    assert ids(g) == ["language"] and any("turned off" in p for p in g["problems"])


def test_a_guide_with_nothing_to_show_falls_back_to_the_panels_own(client):
    set_setup({"steps": ["nowhere"]})
    g = client.get("/api/setup/guide").json()
    assert ids(g) == list(setupguide.STEPS) and g["custom"] is False
    assert any("the guide is the panel's own" in p for p in g["problems"])


@pytest.mark.parametrize("bad", ["language", {"steps": "language"}, {"steps": [1, 2]}])
def test_a_malformed_setting_keeps_the_panels_own_guide(client, bad):
    set_setup(bad)
    g = client.get("/api/setup/guide").json()
    assert ids(g) == list(setupguide.STEPS) and g["custom"] is False and g["problems"]


def test_the_intro_is_a_label_of_the_distributions(client):
    set_setup({"steps": ["language"], "intro": "house.intro"})
    assert client.get("/api/setup/guide").json()["intro"]["key"] == "house.intro"
    set_setup({"steps": ["language"], "intro": {"key": "x.intro", "label": "Welcome to X"}})
    assert client.get("/api/setup/guide").json()["intro"] == {"key": "x.intro", "label": "Welcome to X"}
    set_setup({"steps": ["language"], "intro": 7})
    g = client.get("/api/setup/guide").json()
    assert g["intro"] is None and any("webui.setup.intro" in p for p in g["problems"])


def test_the_setup_page_has_every_own_step_as_a_section():
    """The page wraps each of its own steps in a section the guide can move."""
    from pathlib import Path
    import ovos_webui
    html = (Path(ovos_webui.__file__).parent / "pages" / "setup" / "page.html").read_text()
    for sid in setupguide.STEPS:
        assert f'<section class="setup-step" data-step="{sid}">' in html
    assert 'src="/static/described.js"' in html and "/api/setup/guide" in html


def test_every_language_has_the_custom_intro():
    from pathlib import Path
    import ovos_webui
    folder = Path(ovos_webui.__file__).parent / "pages" / "setup" / "i18n"
    for f in folder.glob("*.json"):
        assert json.loads(f.read_text())["setup.intro.custom"], f.name
