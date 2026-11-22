"""Tests for the skill settings routes, including path traversal attempts."""
import json

import pytest

from ovos_webui import skillsio
from ovos_webui.fsutils import MAX_PAYLOAD_BYTES

META = {"skillMetadata": {"sections": [{"name": "General", "fields": [
    {"name": "volume", "type": "number", "label": "Volume", "value": "5"},
    {"name": "loud", "type": "checkbox", "label": "Loud", "value": "false"},
]}]}}

TRAVERSAL_IDS = [
    "../../../../etc/passwd",
    "..",
    "../ovos-webui",
    "%2e%2e%2f%2e%2e%2fetc",
    ".hidden",
    "a/b",
    "a\\b",
]


def test_list_skills_empty(client):
    assert client.get("/api/skills").json()["skills"] == []


def test_list_skills(client, make_skill):
    make_skill("skill-a", {"x": 1})
    make_skill("skill-b", {"y": 2}, meta=META)
    skills = client.get("/api/skills").json()["skills"]
    assert [s["skill_id"] for s in skills] == ["skill-a", "skill-b"]
    assert skills[1]["has_meta"] is True
    assert skills[0]["has_meta"] is False


def test_list_skills_ignores_unsafe_directory_names(client):
    root = skillsio.skills_root()
    (root / ".secret").mkdir(parents=True, exist_ok=True)
    (root / "ok").mkdir(parents=True, exist_ok=True)
    ids = [s["skill_id"] for s in client.get("/api/skills").json()["skills"]]
    assert ids == ["ok"]


def test_get_settings(client, make_skill):
    make_skill("skill-a", {"volume": 7}, meta=META)
    body = client.get("/api/skills/skill-a").json()
    assert body["settings"] == {"volume": 7}
    assert body["generated_meta"] is False
    assert body["meta"]["skillMetadata"]["sections"][0]["fields"][0]["name"] == "volume"


def test_get_settings_generates_meta_when_missing(client, make_skill):
    make_skill("skill-a", {"volume": 7, "name": "x"})
    body = client.get("/api/skills/skill-a").json()
    assert body["generated_meta"] is True
    names = [f["name"] for f in body["meta"]["skillMetadata"]["sections"][0]["fields"]]
    assert "volume" in names


def test_get_settings_for_unknown_skill_is_empty(client):
    body = client.get("/api/skills/never-installed").json()
    assert body["settings"] == {}


def test_put_settings_round_trip(client, make_skill):
    make_skill("skill-a", {"volume": 1})
    r = client.put("/api/skills/skill-a", json={"settings": {"volume": 9, "new": True}})
    assert r.status_code == 200
    assert skillsio.read_settings("skill-a") == {"volume": 9, "new": True}
    assert client.get("/api/skills/skill-a").json()["settings"]["volume"] == 9


def test_put_settings_makes_a_backup(client, make_skill):
    make_skill("skill-a", {"volume": 1})
    backup = client.put("/api/skills/skill-a", json={"settings": {"volume": 2}}).json()["backup"]
    with open(backup) as handle:
        assert json.load(handle) == {"volume": 1}


@pytest.mark.parametrize("bad", TRAVERSAL_IDS)
def test_get_settings_rejects_traversal(client, bad):
    r = client.get(f"/api/skills/{bad}")
    assert r.status_code in (400, 404), f"{bad} returned {r.status_code}"


@pytest.mark.parametrize("bad", TRAVERSAL_IDS)
def test_put_settings_rejects_traversal(client, bad):
    r = client.put(f"/api/skills/{bad}", json={"settings": {"pwned": True}})
    assert r.status_code in (400, 404), f"{bad} returned {r.status_code}"


def test_traversal_writes_nothing_outside_the_skills_directory(client, sandbox_root):
    victim = sandbox_root / "victim.json"
    victim.write_text("safe")
    client.put("/api/skills/..%2F..%2Fvictim.json", json={"settings": {"pwned": True}})
    client.put("/api/skills/../../victim.json", json={"settings": {"pwned": True}})
    assert victim.read_text() == "safe"


def test_put_settings_rejects_non_mapping(client, make_skill):
    make_skill("skill-a")
    assert client.put("/api/skills/skill-a", json={"settings": [1, 2]}).status_code == 422
    assert client.put("/api/skills/skill-a", json={"settings": "x"}).status_code == 422
    assert client.put("/api/skills/skill-a", json={}).status_code == 422


def test_put_settings_rejects_oversized_body(client, make_skill):
    make_skill("skill-a")
    payload = {"settings": {"pad": "x" * (MAX_PAYLOAD_BYTES + 1024)}}
    assert client.put("/api/skills/skill-a", json=payload).status_code == 413


def test_get_settings_reports_broken_json(client, make_skill):
    sdir = make_skill("skill-a")
    (sdir / "settings.json").write_text("{not json", encoding="utf-8")
    r = client.get("/api/skills/skill-a")
    assert r.status_code == 400
    assert "JSON" in r.json()["detail"]


def test_broken_settingsmeta_is_ignored(client, make_skill):
    sdir = make_skill("skill-a", {"volume": 1})
    (sdir / "settingsmeta.json").write_text("{not json", encoding="utf-8")
    body = client.get("/api/skills/skill-a").json()
    assert body["generated_meta"] is True


def test_yaml_settingsmeta_is_read(client, make_skill):
    sdir = make_skill("skill-a", {"volume": 1})
    (sdir / "settingsmeta.yaml").write_text(
        "skillMetadata:\n  sections:\n    - name: S\n      fields:\n        - name: volume\n",
        encoding="utf-8")
    body = client.get("/api/skills/skill-a").json()
    assert body["generated_meta"] is False


def test_concurrent_settings_writes_keep_valid_json(client, make_skill):
    import threading
    make_skill("skill-a", {"n": 0})
    def write(n):
        client.put("/api/skills/skill-a", json={"settings": {"n": n, "pad": "x" * 2000}})
    threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert isinstance(skillsio.read_settings("skill-a")["n"], int)


FORM_META = {"skillMetadata": {"sections": [
    {"name": "Radio", "fields": [
        {"type": "label", "label": "Pick a station"},
        {"name": "station", "type": "text", "label": "Station", "value": "P3"},
        {"name": "quality", "type": "select", "label": "Quality", "options": "Low|64;High|320", "value": "64"},
        {"name": "token", "type": "password", "label": "Token"},
        {"name": "loud", "type": "checkbox", "label": "Loud"},
        {"name": "odd", "type": "sparkles", "label": "Odd"},
    ]}]}}


def test_settingsmeta_is_a_form_in_the_readers_language(client, make_skill, tmp_path, monkeypatch):
    """The labels come from the skill's own controlpanel.json by the field's
    name: the reader's language, then English, then settingsmeta."""
    make_skill("skill-radio", {"station": "P1", "token": "s3cret"}, meta=FORM_META)
    src = tmp_path / "radio"
    (src / "locale" / "da-dk").mkdir(parents=True)
    (src / "locale" / "en-us").mkdir(parents=True)
    (src / "locale" / "da-dk" / "controlpanel.json").write_text(json.dumps({
        "settings.station": "Radiostation", "settings.section.Radio": "Radio",
        "settings.quality.option.320": "Høj"}), encoding="utf-8")
    (src / "locale" / "en-us" / "controlpanel.json").write_text(json.dumps({
        "settings.station.hint": "As the station calls itself"}), encoding="utf-8")
    monkeypatch.setattr(skillsio, "_skill_source_dir", lambda skill_id, plugins=None: src)
    form = client.get("/api/skills/skill-radio?lang=da-DK").json()["form"]
    assert form["translated"] is True
    [section] = form["sections"]
    assert section["heading"] == "Radio"
    note, station, quality, token, loud, odd = section["fields"]
    assert note == {"type": "note", "label": "Pick a station"}
    assert (station["label"], station["hint"], station["default"]) == \
        ("Radiostation", "As the station calls itself", "P3")
    assert quality["options"] == [{"value": "64", "label": "Low"}, {"value": "320", "label": "Høj"}]
    assert token["type"] == "password" and loud["type"] == "checkbox"
    assert odd["type"] == "text", "an unknown type is a text field"
    english = client.get("/api/skills/skill-radio?lang=en").json()["form"]["sections"][0]["fields"]
    assert english[1]["label"] == "Station"


def test_a_skill_without_strings_keeps_the_settingsmeta_texts(client, make_skill, monkeypatch):
    make_skill("skill-plain", {}, meta=FORM_META)
    monkeypatch.setattr(skillsio, "_skill_source_dir", lambda skill_id, plugins=None: None)
    form = client.get("/api/skills/skill-plain?lang=da").json()["form"]
    assert form["translated"] is False
    assert [f.get("label") for f in form["sections"][0]["fields"]][:3] == ["Pick a station", "Station", "Quality"]


@pytest.mark.parametrize("raw, pairs", [
    ("Low|64;High|320", [("Low", "64"), ("High", "320")]),
    ("one;two", [("one", "one"), ("two", "two")]),
    ([{"label": "A", "value": 1}, ["B", "b"]], [("A", "1"), ("B", "b")]),
    (None, []),
])
def test_settingsmeta_options(raw, pairs):
    assert skillsio._options(raw) == pairs
