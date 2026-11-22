"""A distribution's own packages bring pages too (webui.pages.packages),
though they are not named like an OVOS skill or plugin."""
import json

from ovos_webui import configio, described

PAGE = {"controlpanel": 1, "id": "house", "title": {"key": "house.title", "en": "House"}, "bus": "ovos.house.",
        "blocks": [{"type": "text", "text": {"key": "house.intro", "en": "Hello"}}]}


def install(tmp_path, monkeypatch, name="emkay-house", top="emkay_house"):
    (tmp_path / top).mkdir()
    (tmp_path / top / "__init__.py").write_text("")
    (tmp_path / top / "controlpanel.json").write_text(json.dumps(PAGE))
    info = tmp_path / f"{name.replace('-', '_')}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    (info / "top_level.txt").write_text(top + "\n")
    monkeypatch.syspath_prepend(str(tmp_path))


def ids():
    return [f.package for f in described.discover() if not isinstance(f.data, Exception)]


def test_a_package_not_named_like_ovos_is_passed_by(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    assert "emkay-house" not in ids()


def test_a_distribution_can_name_its_own(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    configio.user_config_path().write_text(json.dumps({"webui": {"pages": {"packages": ["Emkay_House"]}}}))
    assert "emkay-house" in ids(), "named as pip would, in any spelling"


def test_a_malformed_setting_adds_nothing(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    configio.user_config_path().write_text(json.dumps({"webui": {"pages": {"packages": "emkay-house"}}}))
    assert "emkay-house" not in ids()
