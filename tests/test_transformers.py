"""Adversarial tests for the transformer chain config backend.

The rules under test come straight from
``ovos_plugin_manager.transformer_services.TransformersService.load_plugins``:
a section key is a plugin unless it is ``order``/``blacklisted_skills``;
``active`` defaults to true; ``order`` lists execution order.
"""
import json

import pytest

from ovos_webui import configio, transformcfg


def _write_user(section_map):
    """Write a raw user-config layer for the test."""
    conf = configio.user_config_path()
    conf.write_text(json.dumps(section_map), encoding="utf-8")


def _user():
    return configio.read_user_config()


# ---------------------------------------------------------------- get_chains

def test_get_chains_lists_all_six_chains():
    data = transformcfg.get_chains()
    assert set(data["chains"]) == set(transformcfg.CHAINS)
    assert "path" in data


def test_installed_audio_plugins_include_a_really_installed_one():
    # ovos-audio-transformer-plugin-ggwave is a test dependency of this repo,
    # registered under opm.transformer.audio — so it must be offered.
    audio = transformcfg.get_chains()["chains"]["audio_transformers"]
    assert "ovos-audio-transformer-plugin-ggwave" in audio["installed"]


def test_utterance_installed_includes_a_neon_legacy_group_plugin():
    # ovos-utterance-normalizer registers under the deprecated ``neon.plugin.text``
    # group, which the plugin manager still loads. The page must offer it too,
    # or it would hide a plugin the device really runs.
    utt = transformcfg.get_chains()["chains"]["utterance_transformers"]
    assert "ovos-utterance-normalizer" in utt["installed"]


def test_reserved_keys_are_not_reported_as_plugins():
    _write_user({"dialog_transformers": {
        "order": ["a"], "blacklisted_skills": ["skill.x"],
        "a": {}, "b": {"active": False}}})
    chain = transformcfg.get_chains()["chains"]["dialog_transformers"]
    names = {p["name"] for p in chain["plugins"]}
    assert names == {"a", "b"}
    assert chain["order"] == ["a"]
    assert chain["blacklisted_skills"] == ["skill.x"]


def test_active_defaults_true_and_false_is_reported():
    _write_user({"utterance_transformers": {"on": {}, "off": {"active": False}}})
    plugins = {p["name"]: p for p in
               transformcfg.get_chains()["chains"]["utterance_transformers"]["plugins"]}
    assert plugins["on"]["active"] is True
    assert plugins["off"]["active"] is False


def test_get_chains_never_raises_on_malformed_section():
    _write_user({"tts_transformers": "not-a-dict"})
    chain = transformcfg.get_chains()["chains"]["tts_transformers"]
    assert chain["plugins"] == []
    assert chain["order"] == []


# ------------------------------------------------------------ set_chain_state

def test_enable_writes_the_plugin_key():
    transformcfg.set_chain_state("utterance_transformers", {"p1": True})
    assert "p1" in _user()["utterance_transformers"]
    assert "active" not in _user()["utterance_transformers"]["p1"]


def test_disable_keeps_block_and_sets_active_false():
    _write_user({"utterance_transformers": {"p1": {"tune": 3}}})
    transformcfg.set_chain_state("utterance_transformers", {"p1": False})
    block = _user()["utterance_transformers"]["p1"]
    assert block["active"] is False
    assert block["tune"] == 3  # existing config preserved


def test_unmentioned_plugin_is_removed_but_reserved_keys_survive():
    _write_user({"dialog_transformers": {
        "keep": {}, "drop": {}, "order": ["keep"], "blacklisted_skills": ["s"]}})
    transformcfg.set_chain_state("dialog_transformers", {"keep": True})
    section = _user()["dialog_transformers"]
    assert "keep" in section and "drop" not in section
    assert section["blacklisted_skills"] == ["s"]


def test_order_is_written_and_cleared():
    transformcfg.set_chain_state("audio_transformers", {"a": True, "b": True},
                                 order=["b", "a"])
    assert _user()["audio_transformers"]["order"] == ["b", "a"]
    transformcfg.set_chain_state("audio_transformers", {"a": True, "b": True}, order=[])
    assert "order" not in _user()["audio_transformers"]


def test_emptying_a_chain_deletes_the_section():
    _write_user({"utterance_transformers": {"p1": {}}})
    transformcfg.set_chain_state("utterance_transformers", {})
    assert "utterance_transformers" not in _user()


def test_re_enable_removes_active_false():
    _write_user({"tts_transformers": {"p1": {"active": False, "k": 1}}})
    transformcfg.set_chain_state("tts_transformers", {"p1": True})
    block = _user()["tts_transformers"]["p1"]
    assert "active" not in block
    assert block["k"] == 1


# ---------------------------------------------------------- set_plugin_config

def test_set_plugin_config_writes_block_and_keeps_active():
    _write_user({"tts_transformers": {"sox": {"active": False}}})
    transformcfg.set_plugin_config("tts_transformers", "sox", {"pitch": 2})
    block = _user()["tts_transformers"]["sox"]
    assert block["pitch"] == 2
    assert block["active"] is False  # preserved, not clobbered


def test_set_plugin_config_explicit_active_wins():
    _write_user({"tts_transformers": {"sox": {"active": False}}})
    transformcfg.set_plugin_config("tts_transformers", "sox", {"active": True, "x": 1})
    assert _user()["tts_transformers"]["sox"]["active"] is True


# --------------------------------------------------------------- rejections

def test_unknown_chain_is_refused():
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_chain_state("evil_transformers", {"p": True})
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_plugin_config("evil", "p", {})


def test_reserved_word_cannot_be_a_plugin_name():
    for bad in ("order", "blacklisted_skills"):
        with pytest.raises(transformcfg.TransformerConfigError):
            transformcfg.set_chain_state("dialog_transformers", {bad: True})


def test_order_must_not_repeat():
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_chain_state("audio_transformers", {"a": True}, order=["a", "a"])


def test_plugin_name_control_chars_refused():
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_chain_state("audio_transformers", {"a\nb": True})


def test_config_must_be_a_mapping():
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_plugin_config("tts_transformers", "sox", ["not", "a", "map"])


def test_enabled_must_be_a_mapping():
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_chain_state("audio_transformers", ["a", "b"])


def test_a_reserved_key_write_does_not_leak_into_order_path():
    # An attempt to disable via the reserved name must not create a bogus
    # "order" plugin entry; the whole call is refused before any write.
    _write_user({"audio_transformers": {"real": {}}})
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_chain_state("audio_transformers", {"order": False})
    assert _user()["audio_transformers"] == {"real": {}}


# ------------------------------------------------------------- HTTP endpoints

_AUTH = {"Authorization": "Bearer s3cret-token"}


def test_transformers_page_needs_auth(token_client):
    # The page is a signed-in page: a caller with no token is redirected.
    r = token_client.get("/transformers", follow_redirects=False)
    assert r.status_code in (302, 303)


def test_api_transformers_read_needs_a_token(token_client):
    # No token -> the privileged read is refused (401/403), never 200.
    assert token_client.get("/api/transformers").status_code in (401, 403)


def test_api_transformers_roundtrip(token_client):
    got = token_client.get("/api/transformers", headers=_AUTH)
    assert got.status_code == 200
    assert set(got.json()["chains"]) == set(transformcfg.CHAINS)

    # Enable one, disable another, set the order.
    r = token_client.post("/api/transformers/audio_transformers", headers=_AUTH, json={
        "enabled": {"a": True, "b": False}, "order": ["b", "a"]})
    assert r.status_code == 200
    user = configio.read_user_config()["audio_transformers"]
    assert user["b"]["active"] is False
    assert "active" not in user["a"]
    assert user["order"] == ["b", "a"]


def test_api_unknown_chain_is_400(token_client):
    r = token_client.post("/api/transformers/nope", headers=_AUTH,
                          json={"enabled": {"a": True}})
    assert r.status_code == 400


def test_api_plugin_config_roundtrip(token_client):
    r = token_client.post("/api/transformers/tts_transformers/sox/config",
                          headers=_AUTH, json={"config": {"pitch": 2}})
    assert r.status_code == 200
    assert configio.read_user_config()["tts_transformers"]["sox"]["pitch"] == 2


def test_api_reserved_plugin_name_is_400(token_client):
    r = token_client.post("/api/transformers/dialog_transformers", headers=_AUTH,
                          json={"enabled": {"order": True}})
    assert r.status_code == 400


# --------------------------------------------------------- bidirectional card

def test_bidirectional_off_by_default():
    d = transformcfg.get_bidirectional()
    assert d["enabled"] is False
    assert d["flags"]["bidirectional"] is True  # plugin default


def test_enable_bidirectional_writes_both_plugins_and_langs():
    transformcfg.set_bidirectional(True, ["pt-pt", "es-es"],
                                   {"bidirectional": True, "verify_lang": True})
    user = _user()
    assert transformcfg.BIDI_UTTERANCE in user["utterance_transformers"]
    assert transformcfg.BIDI_DIALOG in user["dialog_transformers"]
    utt = user["utterance_transformers"][transformcfg.BIDI_UTTERANCE]
    assert utt["verify_lang"] is True and utt["bidirectional"] is True
    assert user["secondary_langs"] == ["pt-pt", "es-es"]


def test_get_bidirectional_reports_enabled_after_enable():
    transformcfg.set_bidirectional(True, ["pt-pt"], {"verify_lang": True})
    d = transformcfg.get_bidirectional()
    assert d["enabled"] is True
    assert d["flags"]["verify_lang"] is True
    assert d["secondary_langs"] == ["pt-pt"]


def test_disable_bidirectional_removes_plugins_but_keeps_langs():
    transformcfg.set_bidirectional(True, ["pt-pt"], {})
    transformcfg.set_bidirectional(False)
    user = _user()
    assert "utterance_transformers" not in user or \
        transformcfg.BIDI_UTTERANCE not in user.get("utterance_transformers", {})
    assert "dialog_transformers" not in user or \
        transformcfg.BIDI_DIALOG not in user.get("dialog_transformers", {})
    assert user["secondary_langs"] == ["pt-pt"]  # left untouched


def test_disable_bidirectional_preserves_other_plugins_in_the_chains():
    _write_user({"utterance_transformers": {"other": {}, transformcfg.BIDI_UTTERANCE: {}},
                 "dialog_transformers": {"otherd": {}, transformcfg.BIDI_DIALOG: {}}})
    transformcfg.set_bidirectional(False)
    assert _user()["utterance_transformers"] == {"other": {}}
    assert _user()["dialog_transformers"] == {"otherd": {}}


def test_bidirectional_rejects_a_bad_language():
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_bidirectional(True, ["not a lang!"])


def test_bidirectional_rejects_an_unknown_flag():
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_bidirectional(True, ["pt-pt"], {"evil": True})


def test_api_bidirectional_roundtrip(token_client):
    assert token_client.get("/api/bidirectional").status_code in (401, 403)  # needs token
    r = token_client.post("/api/bidirectional", headers=_AUTH,
                          json={"enable": True, "secondary_langs": ["pt-pt"],
                                "flags": {"bidirectional": True}})
    assert r.status_code == 200
    got = token_client.get("/api/bidirectional", headers=_AUTH).json()
    assert got["enabled"] is True and got["secondary_langs"] == ["pt-pt"]


def test_api_bidirectional_bad_lang_is_400(token_client):
    r = token_client.post("/api/bidirectional", headers=_AUTH,
                          json={"enable": True, "secondary_langs": ["!!"]})
    assert r.status_code == 400


# --------------------------------------------------------------- SoX card

def test_sox_off_by_default():
    d = transformcfg.get_sox()
    assert d["enabled"] is False
    assert d["effects"] == {}


def test_set_sox_writes_default_effects_and_enables():
    transformcfg.set_sox(True, {"pitch": {"n_semitones": 3}, "reverb": {"reverberance": 40}})
    block = _user()["tts_transformers"][transformcfg.SOX_PLUGIN]
    assert block["default_effects"]["pitch"]["n_semitones"] == 3
    assert block["default_effects"]["reverb"]["reverberance"] == 40
    assert "active" not in block


def test_get_sox_reports_effects_after_set():
    transformcfg.set_sox(True, {"pitch": {"n_semitones": -2}})
    d = transformcfg.get_sox()
    assert d["enabled"] is True
    assert d["effects"]["pitch"]["n_semitones"] == -2


def test_disable_sox_removes_only_that_plugin():
    _write_user({"tts_transformers": {"other": {}, transformcfg.SOX_PLUGIN: {"default_effects": {}}}})
    transformcfg.set_sox(False)
    assert _user()["tts_transformers"] == {"other": {}}


def test_sox_rejects_an_unknown_effect():
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_sox(True, {"explode": {"amount": 9}})


def test_sox_rejects_a_non_numeric_param():
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_sox(True, {"pitch": {"n_semitones": "loud"}})


def test_sox_rejects_a_boolean_param():
    # bool is an int subclass in Python; it must still be refused as an amount.
    with pytest.raises(transformcfg.TransformerConfigError):
        transformcfg.set_sox(True, {"pitch": {"n_semitones": True}})


def test_api_sox_roundtrip(token_client):
    assert token_client.get("/api/sox").status_code in (401, 403)  # needs token
    r = token_client.post("/api/sox", headers=_AUTH,
                          json={"enable": True, "effects": {"pitch": {"n_semitones": 4}}})
    assert r.status_code == 200
    got = token_client.get("/api/sox", headers=_AUTH).json()
    assert got["enabled"] is True and got["effects"]["pitch"]["n_semitones"] == 4


def test_api_sox_unknown_effect_is_400(token_client):
    r = token_client.post("/api/sox", headers=_AUTH,
                          json={"enable": True, "effects": {"explode": {"x": 1}}})
    assert r.status_code == 400
