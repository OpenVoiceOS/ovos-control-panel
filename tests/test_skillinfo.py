"""Who made a skill, where its source is, what to say to it, and its icon."""
import io
import json
import zipfile

import pytest

from ovos_webui import pypi, skillinfo

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _wheel(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def fake_pypi(monkeypatch, tmp_path):
    """Serve PyPI's JSON, a wheel and an icon from memory."""
    wheel = _wheel({
        "ovos_skill_tales/locale/en-us/skill.json": json.dumps({
            "name": "Tales", "description": "Fairy tales", "examples": ["Tell me a story"],
            "icon": "https://raw.githubusercontent.com/someone/tales/main/icon.png"}).encode(),
        "ovos_skill_tales/locale/da-dk/skill.json": json.dumps({
            "name": "Eventyr", "examples": ["Fortæl en historie"]}).encode(),
        "ovos_skill_tales-1.0.dist-info/entry_points.txt":
            b"[opm.skill]\ntales.someone = ovos_skill_tales:TalesSkill\n",
    })
    project = {
        "info": {"version": "1.0", "author": "Someone", "license": "MIT", "summary": "Tales",
                 "project_urls": {"Source": "https://github.com/someone/tales"},
                 "requires_dist": ["requests"]},
        "urls": [{"filename": "ovos_skill_tales-1.0-py3-none-any.whl",
                  "url": "https://files.example/ovos_skill_tales-1.0-py3-none-any.whl",
                  "size": len(wheel), "upload_time_iso_8601": "2026-10-01T10:00:00Z", "digests": {}}],
    }
    served = {
        "/pypi/ovos-skill-tales/json": json.dumps(project).encode(),
        "ovos_skill_tales-1.0-py3-none-any.whl": wheel,
        "icon.png": PNG,
    }
    fetched = []

    def get(url, limit):
        fetched.append(url)
        for tail, body in served.items():
            if url.endswith(tail):
                return body
        raise OSError("not found")

    monkeypatch.setattr(skillinfo, "_get", get)
    monkeypatch.setattr(skillinfo, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(skillinfo, "_device_lang", lambda: "en-us")
    skillinfo._REMOTE.clear()
    return served, fetched


def test_a_skill_that_is_not_installed_is_read_from_pypi_and_its_wheel(fake_pypi):
    out = skillinfo.info("ovos-skill-tales")
    assert out["installed"] is False
    assert out["author"] == "Someone"
    assert out["source"] == "https://github.com/someone/tales"
    assert out["title"] == "Tales" and out["examples"] == ["Tell me a story"]
    assert out["released"] == "2026-10-01T10:00:00Z"
    assert out["is_ovos_skill"] is True, "the wheel registers a skill"
    assert out["has_icon"] is True
    assert "icon_url" not in out


def test_the_device_language_picks_the_skill_json(fake_pypi, monkeypatch):
    monkeypatch.setattr(skillinfo, "_device_lang", lambda: "da-DK")
    assert skillinfo.info("ovos-skill-tales")["examples"] == ["Fortæl en historie"]


def test_the_icon_is_fetched_once_and_served_as_an_image(fake_pypi):
    _, fetched = fake_pypi
    assert skillinfo.icon("ovos-skill-tales") == (PNG, "image/png")
    assert skillinfo.icon("ovos-skill-tales") == (PNG, "image/png")
    assert sum(u.endswith("icon.png") for u in fetched) == 1


def test_an_icon_that_is_not_a_raster_image_is_not_served(fake_pypi):
    served, _ = fake_pypi
    served["icon.png"] = b"<svg xmlns='http://www.w3.org/2000/svg'><script>x()</script></svg>"
    assert skillinfo.icon("ovos-skill-tales") is None


@pytest.mark.parametrize("url", ["http://raw.githubusercontent.com/a.png", "https://evil.example/a.png",
                                 "https://192.168.1.1/a.png", None, ""])
def test_icons_come_only_from_the_code_hosts_over_https(url):
    assert skillinfo._icon_allowed(url) is False


def test_an_installed_skill_is_read_locally():
    out = skillinfo.info("ovos-skill-hello-world")
    assert out["installed"] is True
    assert out["author"] and out["source"].startswith("https://github.com/")
    assert out["examples"], "hello world ships a skill.json with examples"


@pytest.mark.parametrize("name", ["requests", "ovos-tts-plugin-piper", "ovos-skill-x; rm -rf /"])
def test_only_skill_packages_are_looked_up(name):
    with pytest.raises(skillinfo.NotASkill):
        skillinfo.info(name)
    assert skillinfo.icon(name) is None


def test_pick_skill_json_prefers_the_language_then_english():
    paths = ["p/locale/en-us/skill.json", "p/locale/da-dk/skill.json", "p/locale/pt-br/skill.json"]
    assert skillinfo.pick_skill_json(paths, "da-DK") == "p/locale/da-dk/skill.json"
    assert skillinfo.pick_skill_json(paths, "pt-PT") == "p/locale/pt-br/skill.json"
    assert skillinfo.pick_skill_json(paths, "de-de") == "p/locale/en-us/skill.json"
    assert skillinfo.pick_skill_json(["p/x.py"], "en-us") is None


def test_an_author_given_only_as_an_address_shows_the_name_part():
    assert skillinfo._person(None, "Jane Doe <jane@example.org>") == "Jane Doe"
    assert skillinfo._person(None, "jane@example.org") is None


def test_requires_ovos_tells_a_skill_from_a_namesake():
    assert skillinfo.requires_ovos(["ovos-workshop>=0.1", "requests"])
    assert skillinfo.requires_ovos(["neon-utils"])
    assert not skillinfo.requires_ovos(["requests", "mcp"])
    assert not skillinfo.requires_ovos(None)


def test_skill_names_that_are_not_ovos_skills_leave_the_index(monkeypatch, tmp_path):
    monkeypatch.setattr(pypi, "cache_path", lambda: tmp_path / "index.json")
    answers = {"skill-homeassistant": ["ovos-workshop"], "skill-audit": ["click"]}
    asked = []

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_open(url):
        name = url.split("/pypi/")[1].split("/")[0]
        asked.append(name)
        return Reply(json.dumps({"info": {"requires_dist": answers[name]}}).encode())

    monkeypatch.setattr(pypi, "_open", fake_open)
    names = ["ovos-skill-news", "skill-homeassistant", "skill-audit", "ovos-tts-plugin-piper"]
    assert pypi.check_skill_names(names) == {"skill-audit"}
    assert sorted(asked) == ["skill-audit", "skill-homeassistant"], "ovos-skill-* is not looked up"
    asked.clear()
    assert pypi.check_skill_names(names) == {"skill-audit"}
    assert asked == [], "the answers are remembered"


def test_the_routes(client, fake_pypi):
    r = client.get("/api/skillinfo/ovos-skill-tales")
    assert r.status_code == 200 and r.json()["author"] == "Someone"
    r = client.get("/api/skillinfo/ovos-skill-tales/icon")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/skillinfo/requests").status_code == 400
    assert client.get("/api/skillinfo/requests/icon").status_code == 404


class _Dist:
    def __init__(self, requires, groups=()):
        self.requires = requires
        self.entry_points = [type("EP", (), {"group": g})() for g in groups]


def test_an_installed_namesake_is_not_listed_as_a_skill():
    from ovos_webui import capabilities
    assert not capabilities._is_skill_package("skill-audit", _Dist(["click"]))
    assert capabilities._is_skill_package("skill-homeassistant", _Dist(["ovos-workshop"]))
    assert capabilities._is_skill_package("skill-news", _Dist([], ["ovos.plugin.skill"]))
    assert capabilities._is_skill_package("skill-wolfie", _Dist([], ["opm.skill"]))
    assert capabilities._is_skill_package("ovos-skill-hello-world", _Dist([]))


@pytest.mark.parametrize("text,registers", [
    (b"[opm.skill]\nx.y = m:S\n", True),
    (b"[ovos.plugin.skill]\nx.y = m:S\n", True),
    (b"[console_scripts]\nopm.skill = m:main\n", False),
    (b"[opm.skill.config]\nx = m:c\n", False),
])
def test_both_skill_entry_point_groups_count(text, registers):
    """opm.skill is the group ovos-plugin-manager uses now, ovos.plugin.skill
    the older one; a name that only mentions one is not a registration."""
    assert bool(skillinfo._GROUP_RE.search(text)) is registers


def test_the_author_in_skill_json_comes_before_the_package_metadata(fake_pypi, monkeypatch):
    served, _ = fake_pypi
    wheel = _wheel({
        "ovos_skill_tales/locale/en-us/skill.json": json.dumps({
            "name": "Tales", "author": "emkay-voice"}).encode(),
    })
    served["ovos_skill_tales-1.0-py3-none-any.whl"] = wheel
    project = json.loads(served["/pypi/ovos-skill-tales/json"])
    project["urls"][0]["size"] = len(wheel)
    served["/pypi/ovos-skill-tales/json"] = json.dumps(project).encode()
    assert skillinfo.info("ovos-skill-tales")["author"] == "emkay-voice"


def test_a_skill_json_without_an_author_keeps_the_package_author():
    assert skillinfo._from_skill_json(b'{"name": "Tales"}')["skill_author"] is None
    assert skillinfo._from_skill_json(b'{"author": "  "}')["skill_author"] is None
    assert skillinfo._from_skill_json(b'{"author": "Emkay-Voice"}')["skill_author"] == "Emkay-Voice"
