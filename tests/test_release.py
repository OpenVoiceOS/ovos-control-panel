"""The OVOS release the device follows, read from the installer's
constraints file, and how the search uses it."""
import json

import pytest

from ovos_webui import configio, pypi, release
from ovos_webui.fsutils import atomic_write

STABLE = """# OVOS stable
ovos-core>=1.3.1,<1.4.0
ovos-skill-local-media>=0.2.12,<0.3.0
OVOS_Skill_Weather>=0.1.18,<0.2.0
ovos-tts-plugin-piper[extra]>=0.1 ; python_version >= "3.9"
-c other.txt

"""


def _installer(constraints):
    atomic_write(configio.user_config_path(),
                 json.dumps({"skills": {"installer": {"constraints": constraints}}}))


def test_a_constraints_file_is_read_as_the_packages_in_the_release():
    got = release.parse(STABLE)
    assert got == {"ovos-core": ">=1.3.1,<1.4.0", "ovos-skill-local-media": ">=0.2.12,<0.3.0",
                   "ovos-skill-weather": ">=0.1.18,<0.2.0", "ovos-tts-plugin-piper": ">=0.1"}


def test_the_file_is_the_one_the_installer_uses():
    assert release.source() == release.DEFAULT
    assert release.name_of(release.DEFAULT) == "stable"
    alpha = "https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/main/constraints-alpha.txt"
    _installer(alpha)
    assert release.source() == alpha and release.name_of(alpha) == "alpha"
    assert release.name_of("/etc/mine.txt") is None


def test_a_local_file_is_read_and_an_unknown_scheme_is_not(tmp_path, monkeypatch):
    monkeypatch.undo()          # the real _read
    release.clear()
    mine = tmp_path / "mine.txt"
    mine.write_text(STABLE)
    _installer(str(mine))
    got = release.packages()
    assert got["name"] is None and got["error"] is None and "ovos-core" in got["packages"]
    _installer("ftp://example.org/c.txt")
    got = release.packages()
    assert got["packages"] is None and "https" in got["error"]


def test_a_failed_read_keeps_the_last_good_list(monkeypatch):
    calls = []

    def read(src):
        calls.append(src)
        if len(calls) > 1:
            raise OSError("offline")
        return STABLE
    monkeypatch.setattr(release, "_read", read)
    assert "ovos-core" in release.packages()["packages"]
    assert len(calls) == 1 and "ovos-core" in release.packages()["packages"], "kept, not read again"
    got = release.packages(refresh=True)
    assert got["error"] == "offline" and "ovos-core" in got["packages"]


@pytest.fixture
def index(monkeypatch):
    monkeypatch.setattr(release, "_read", lambda src: STABLE)
    monkeypatch.setattr(pypi, "index", lambda refresh=False: {"packages": {
        "ovos-skill-local-media": "skill", "ovos-skill-weather": "skill",
        "ovos-skill-unknown": "skill", "ovos-media-provider-local": "media_provider"}})
    monkeypatch.setattr(pypi, "installed_versions", lambda: {"ovos-media-provider-local": "0.0.1a5"})


def test_the_search_says_what_is_in_the_release_and_lists_it_first(index):
    got = pypi.search(kind="")
    by = {r["name"]: r for r in got["results"]}
    assert by["ovos-skill-weather"]["in_release"] is True
    assert by["ovos-skill-unknown"]["in_release"] is False
    assert [r["name"] for r in got["results"]] == [
        "ovos-media-provider-local",                        # installed
        "ovos-skill-local-media", "ovos-skill-weather",     # in the release
        "ovos-skill-unknown"]
    assert got["release"] == {"name": "stable", "source": release.DEFAULT, "known": True}


def test_only_the_release_still_lists_what_is_installed(index):
    names = [r["name"] for r in pypi.search(only_release=True)["results"]]
    assert names == ["ovos-media-provider-local", "ovos-skill-local-media", "ovos-skill-weather"]


def test_without_the_release_file_nothing_is_said_about_it(monkeypatch, index):
    def offline(src):
        raise OSError("offline")
    monkeypatch.setattr(release, "_read", offline)
    got = pypi.search(only_release=True)
    assert got["release"]["known"] is False
    assert all(r["in_release"] is None for r in got["results"])
    assert len(got["results"]) == 4, "nothing is left out on a guess"


def test_the_route_takes_release(client, index):
    r = client.get("/api/plugins/search", params={"q": "skill", "release": "true"})
    assert [x["name"] for x in r.json()["results"]] == ["ovos-skill-local-media", "ovos-skill-weather"]
