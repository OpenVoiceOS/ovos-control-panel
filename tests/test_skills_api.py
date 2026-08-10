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
