"""Tests for the ovos-config recommends registry reader.

The language code is taken from the URL and used to build a file name, so it
must not be able to walk out of the registry directory.
"""
import json

from ovos_webui import recommends


def _fake_registry(tmp_path, monkeypatch):
    root = tmp_path / "reg"
    (root / "base").mkdir(parents=True)
    (root / "base" / "pt.conf").write_text(json.dumps({"tts": {"module": "x"}}))
    # a JSON .conf file one level above the profile, the traversal target
    (root / "secret.conf").write_text(json.dumps({"stolen": True}))
    monkeypatch.setattr(recommends, "registry_root", lambda: root)
    return root


def test_a_real_language_is_read(tmp_path, monkeypatch):
    _fake_registry(tmp_path, monkeypatch)
    out = recommends.for_language("pt")
    assert out["profiles"]["base"]["config"] == {"tts": {"module": "x"}}


def test_a_traversing_language_reads_nothing(tmp_path, monkeypatch):
    """`../secret` would resolve to the file above the profile directory."""
    _fake_registry(tmp_path, monkeypatch)
    out = recommends.for_language("../secret")
    assert out["profiles"] == {}, "a language code walked out of the registry"


def test_a_language_with_a_slash_reads_nothing(tmp_path, monkeypatch):
    _fake_registry(tmp_path, monkeypatch)
    assert recommends.for_language("pt/../../secret")["profiles"] == {}


def test_recommended_plugins_is_also_guarded(tmp_path, monkeypatch):
    _fake_registry(tmp_path, monkeypatch)
    assert recommends.recommended_plugins("../secret") == []
