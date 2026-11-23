"""Companion plugins: a plugin can say what it provides, and a distribution
chooses which missing ones are offered (webui.companions)."""
import types

from ovos_webui import phal


def _found(package, data):
    return types.SimpleNamespace(package=package, data=data)


def test_a_plugin_that_says_it_provides_volume_counts(monkeypatch):
    monkeypatch.setattr("ovos_webui.pypi.installed_versions", lambda: {"ovos-phal-plugin-browser": "0.1"})
    monkeypatch.setattr("ovos_webui.described.discover", lambda: [
        _found("ovos-phal-plugin-browser", {"provides": ["volume", "power", "not-a-capability"]})])
    monkeypatch.setattr(phal, "offered_companions", lambda: None)
    caps = phal.capability_status()["capabilities"]
    assert caps["volume"]["installed"] and caps["volume"]["provider"] == "ovos-phal-plugin-browser"
    assert caps["power"]["installed"]
    assert not caps["network"]["installed"] and caps["network"]["offered"]


def test_a_distribution_offers_only_its_companions(monkeypatch):
    monkeypatch.setattr("ovos_webui.pypi.installed_versions", lambda: {})
    monkeypatch.setattr("ovos_webui.described.discover", lambda: [])
    monkeypatch.setattr("ovos_webui.configio.user_or_merged",
                        lambda path, default=None: ["volume"] if path == ["webui", "companions"] else default)
    caps = phal.capability_status()["capabilities"]
    assert caps["volume"]["offered"] is True
    assert caps["network"]["offered"] is False and caps["ggwave"]["offered"] is False


def test_unset_offers_every_companion(monkeypatch):
    monkeypatch.setattr("ovos_webui.configio.user_or_merged", lambda path, default=None: default)
    assert phal.offered_companions() is None
