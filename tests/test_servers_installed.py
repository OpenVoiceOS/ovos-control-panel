"""The Servers page leaves out a kind whose server plugin is not installed:
a distribution without translation (Emkay) has nothing to point there."""
import types

from ovos_webui import pages, servers


def _eps(*names):
    return [types.SimpleNamespace(name=n, group="opm.stt" if "stt" in n else "neon.plugin.lang.translate")
            for n in names]


def test_a_kind_without_its_plugin_is_left_out(monkeypatch):
    monkeypatch.setattr(pages, "colocated", lambda have=None: True)
    monkeypatch.setattr("importlib.metadata.entry_points", lambda: _eps("ovos-stt-plugin-server"))
    assert servers.installed("stt", {"module": "ovos-stt-plugin-server"}) is True
    assert servers.installed("translate", {"translation_module": "ovos-translate-plugin-server"}) is False


def test_apart_from_the_assistant_nothing_is_left_out(monkeypatch):
    monkeypatch.setattr(pages, "colocated", lambda have=None: False)
    assert servers.installed("translate", {"translation_module": "ovos-translate-plugin-server"}) is None


def test_personas_needs_ovos_persona():
    from ovos_webui.pages.personas import PAGE
    assert PAGE["needs"] == ["ovos-persona"]
