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


def _registry(tmp_path, monkeypatch, names):
    root = tmp_path / "reg"
    for profile, files in names.items():
        (root / profile).mkdir(parents=True)
        for name in files:
            (root / profile / f"{name}.conf").write_text(
                json.dumps({"tts": {"module": name}}))
    monkeypatch.setattr(recommends, "registry_root", lambda: root)


_OLD_NAMES = {"base": ["en-au", "en-gb", "en-us", "pt-br", "pt-pt", "an-es",
                       "eu-es", "hr-hr", "de-de"]}
_NEW_NAMES = {"base": ["en-AU", "en-GB", "en-US", "pt-BR", "pt-PT", "arg",
                       "eus", "hr-HR", "de-DE"]}


def _picked(lang):
    return recommends.for_language(lang)["profiles"].get("base", {}).get("lang")


def test_closest_file_with_old_lowercase_names(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, _OLD_NAMES)
    assert _picked("en-gb") == "en-gb"
    assert _picked("pt-pt") == "pt-pt"
    assert _picked("an-es") == "an-es"
    assert _picked("eu-es") == "eu-es"


def test_closest_file_with_language_tag_names(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, _NEW_NAMES)
    assert _picked("en-gb") == "en-GB"
    assert _picked("pt-pt") == "pt-PT"
    assert _picked("an-es") == "arg"
    assert _picked("eu-es") == "eus"
    assert _picked("eu") == "eus"


def test_regional_fallback_is_kept_and_other_languages_are_rejected(
        tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, _NEW_NAMES)
    assert _picked("en-nz") in ("en-GB", "en-AU", "en-US")
    assert _picked("pt-ao") == "pt-PT"
    assert _picked("de-at") == "de-DE"
    assert _picked("sr-latn") is None
    assert _picked("bs") is None
    assert _picked("lb") is None


_ARABIC = {"base": ["en-US"], "offline_stt": ["arb", "zh-CN"]}


def _arabic(lang, profile="offline_stt"):
    return recommends.for_language(lang)["profiles"].get(profile, {}).get("lang")


def test_arabic_reaches_modern_standard_arabic(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, _ARABIC)
    for lang in ("ar", "ar-sa", "ar-eg", "ar-ma", "arb"):
        assert _arabic(lang) == "arb", lang


def test_arabic_in_a_profile_without_an_msa_file_reads_nothing(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, _ARABIC)
    assert _arabic("ar-sa", "base") is None


def test_cantonese_does_not_reach_mandarin(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, _ARABIC)
    assert _arabic("yue") is None


def test_distance_five_is_kept(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, {"base": ["en-US", "es-ES"]})
    assert _picked("en-nz") == "en-US"
    assert _picked("es-419") == "es-ES"


def test_platform_files_are_not_language_files(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, {"base": ["en-US"], "platform": ["mac", "linux"]})
    for lang in ("mk", "mk-mk", "mkd"):
        assert "platform" not in recommends.for_language(lang)["profiles"], lang
