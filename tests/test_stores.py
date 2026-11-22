"""Stores set on the Control panel page, read in the Emkay and the Klondike
format, and searched instead of PyPI."""
import json

import pytest

from ovos_webui import configio, pypi, release, stores
from ovos_webui.fsutils import atomic_write

EMKAY = [
    {"package": "ovos-skill-jokes", "kind": "skill", "status": "works",
     "texts": {"en-us": {"name": "Jokes", "description": "Tells jokes", "examples": ["tell me a joke"]},
               "da-dk": {"name": "Vittigheder", "description": "Fortæller vittigheder",
                         "examples": ["fortæl en vittighed"]}}},
    {"package": "ovos-skill-broken", "kind": "skill", "status": "broken", "texts": {}},
    {"package": "ovos-tts-plugin-piper", "kind": "tts", "status": "untested",
     "texts": {"en-us": {"name": "Piper"}}},
    {"package": "not-ovos-at-all", "kind": "skill", "status": "works", "texts": {}},
]
KLONDIKE = [
    {"package_name": "ovos-skill-weather", "component_type": "Skill", "name": "Weather",
     "description": "Weather forecasts", "examples": ["what is the weather"], "archived": False, "on_pypi": True},
    {"package_name": "ovos-skill-youtube", "component_type": "Skill", "archived": True, "on_pypi": True},
    {"package_name": "ovos-skill-git-only", "component_type": "Skill", "archived": False, "on_pypi": False},
    {"package_name": "ovos-media-provider-local", "component_type": "Plugin", "archived": False, "on_pypi": True},
]


def test_both_formats_are_read_and_what_is_not_offered_is_left_out():
    got = {e["package"]: e for e in stores.parse(EMKAY)}
    assert set(got) == {"ovos-skill-jokes", "ovos-tts-plugin-piper"}, "broken and non-OVOS left out"
    assert got["ovos-skill-jokes"]["works"] is True and got["ovos-tts-plugin-piper"]["works"] is None
    assert got["ovos-tts-plugin-piper"]["kind"] == "tts"
    got = {e["package"]: e for e in stores.parse(KLONDIKE)}
    assert set(got) == {"ovos-skill-weather", "ovos-media-provider-local"}, "archived and not on PyPI left out"
    assert got["ovos-media-provider-local"]["kind"] == "media_provider"
    assert stores.parse({"not": "a list"}) == [] and stores.parse(["x", 5]) == []


def test_texts_in_the_readers_language_else_english():
    jokes = stores.parse(EMKAY)[0]
    assert stores.text(jokes, "da-DK")["name"] == "Vittigheder"
    assert stores.text(jokes, "da")["examples"] == ["fortæl en vittighed"]
    assert stores.text(jokes, "fr-fr")["name"] == "Jokes"


def test_the_stores_set_are_checked():
    assert stores.configured() == []
    atomic_write(configio.user_config_path(), json.dumps({"webui": {"stores": [
        {"name": "Emkay", "url": "https://store.emkay.ai/data/skills.json"},
        {"name": "Plain", "url": "http://example.org/x.json"}, "junk",
        {"url": "https://example.org/y.json"}]}}))
    assert stores.configured() == [
        {"name": "Emkay", "url": "https://store.emkay.ai/data/skills.json"},
        {"name": "https://example.org/y.json", "url": "https://example.org/y.json"}]
    with pytest.raises(ValueError, match="https"):
        stores.check([{"name": "x", "url": "http://a.b/c"}])
    with pytest.raises(ValueError, match="name"):
        stores.check([{"name": " ", "url": "https://a.b/c"}])
    with pytest.raises(ValueError, match="at most"):
        stores.check([{"name": "x", "url": "https://a.b/c"}] * 9)


def test_stores_are_set_on_the_control_panel_page(token_client):
    c = token_client
    one = [{"name": "Emkay", "url": "https://store.emkay.ai/data/skills.json"}]
    assert c.post("/api/panel/stores", json={"stores": one}).status_code == 401
    c.headers["Authorization"] = "Bearer s3cret-token"
    assert c.post("/api/panel/stores", json={"stores": [{"name": "x", "url": "ftp://a"}]}).status_code == 400
    assert c.post("/api/panel/stores", json={"stores": one}).json() == {"stores": one}
    assert configio.read_user_config()["webui"]["stores"] == one
    assert c.get("/api/stores").json() == {"stores": [{"name": "Emkay"}]}
    assert c.post("/api/panel/stores", json={"stores": []}).json() == {"stores": []}
    assert "stores" not in configio.read_user_config()["webui"]


@pytest.fixture
def two_stores(monkeypatch):
    atomic_write(configio.user_config_path(), json.dumps({"webui": {"stores": [
        {"name": "Emkay", "url": "https://e.example/skills.json"},
        {"name": "Klondike", "url": "https://k.example/skills.json"}]}}))
    data = {"https://e.example/skills.json": EMKAY, "https://k.example/skills.json": KLONDIKE}
    monkeypatch.setattr(stores, "_read", lambda url: data[url])
    monkeypatch.setattr(release, "_read", lambda src: "ovos-skill-weather>=0.1\n")
    monkeypatch.setattr(pypi, "installed_versions", lambda: {"ovos-tts-plugin-piper": "0.1"})


def test_a_store_is_searched_instead_of_pypi(client, two_stores):
    r = client.get("/api/plugins/search", params={"store": 0, "lang": "da-dk", "q": "vittig"}).json()
    assert [x["name"] for x in r["results"]] == ["ovos-skill-jokes"]
    jokes = r["results"][0]
    assert jokes["store"] == {"name": "Vittigheder", "description": "Fortæller vittigheder",
                              "examples": ["fortæl en vittighed"], "works": True}
    assert jokes["in_release"] is False and r["from_store"]["name"] == "Emkay"
    r = client.get("/api/plugins/search", params={"store": 0, "kind": "tts"}).json()
    assert [(x["name"], x["installed"]) for x in r["results"]] == [("ovos-tts-plugin-piper", True)]
    r = client.get("/api/plugins/search", params={"store": 1, "kind": "skill"}).json()
    assert [(x["name"], x["in_release"]) for x in r["results"]] == [("ovos-skill-weather", True)]
    assert client.get("/api/plugins/search", params={"store": 2}).status_code == 404


def test_a_store_that_cannot_be_reached_says_so(client, monkeypatch):
    atomic_write(configio.user_config_path(), json.dumps({"webui": {"stores": [
        {"name": "Down", "url": "https://down.example/x.json"}]}}))
    r = client.get("/api/plugins/search", params={"store": 0}).json()
    assert r["offline"] is True and r["results"] == [] and r["error"]
