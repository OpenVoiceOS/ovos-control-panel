"""The one Skills page: installed skills know their package, so they can be
updated and removed where they are listed."""
from ovos_webui import capabilities


def _with(monkeypatch, summaries):
    monkeypatch.setattr(capabilities, "_summaries", lambda: dict(summaries))


def test_a_skill_with_settings_knows_its_id_and_its_package(client, make_skill, monkeypatch):
    make_skill("ovos-skill-weather.openvoiceos", {})
    _with(monkeypatch, {"ovos-skill-weather": "Weather forecasts"})
    skills = {s["id"]: s for s in client.get("/api/capabilities").json()["skills"]}
    weather = skills["ovos-skill-weather.openvoiceos"]
    assert weather["skill_id"] == "ovos-skill-weather.openvoiceos"
    assert weather["package"] == "ovos-skill-weather"
    assert weather["description"] == "Weather forecasts"
    assert weather["configurable"] is True
    assert "ovos-skill-weather" not in skills, "listed once, not once per source"


def test_a_skill_without_settings_is_listed_by_its_package(client, monkeypatch):
    _with(monkeypatch, {"ovos-skill-hello-world": "Says hello"})
    (hello,) = client.get("/api/capabilities").json()["skills"]
    assert hello["package"] == "ovos-skill-hello-world"
    assert hello["skill_id"] is None
    assert hello["configurable"] is False


def test_a_settings_folder_with_no_package_cannot_be_removed(client, make_skill, monkeypatch):
    make_skill("my-local-skill.someone", {})
    _with(monkeypatch, {})
    (local,) = client.get("/api/capabilities").json()["skills"]
    assert local["package"] is None


def test_skills_not_named_ovos_count_as_skills():
    # skill-homeassistant and friends (#102), and the *-skill-* convention
    assert capabilities._is_skill_package("skill-homeassistant")
    assert capabilities._is_skill_package("ovos-skill-news")
    assert capabilities._is_skill_package("neon-skill-alerts")
    assert not capabilities._is_skill_package("ovos-tts-plugin-piper")
    assert not capabilities._is_skill_package("requests")
