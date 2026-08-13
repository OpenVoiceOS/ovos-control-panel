"""Tests for the voice settings page: wake word, VAD, STT, TTS, pipeline,
transformers and language."""
import pytest

from ovos_webui import configio, voicecfg

AUTH = {"Authorization": "Bearer s3cret-token"}


def _installed(monkeypatch, packages):
    """Pretend exactly ``packages`` (name -> version) are installed."""
    monkeypatch.setattr("ovos_webui.pypi.installed_versions", lambda: dict(packages))


# ── voicecfg.get_settings ────────────────────────────────────────────────────

def test_get_settings_shape(monkeypatch):
    _installed(monkeypatch, {})
    r = voicecfg.get_settings()
    assert "path" in r
    fields = r["fields"]
    for key in voicecfg.FIELD_PATHS:
        assert key in fields
        assert "value" in fields[key] and "effective" in fields[key]


def test_get_settings_reflects_current_user_value(monkeypatch):
    _installed(monkeypatch, {})
    configio.write_user_config({"stt": {"module": "ovos-stt-plugin-server"}})
    r = voicecfg.get_settings()
    assert r["fields"]["stt_module"]["value"] == "ovos-stt-plugin-server"


def test_get_settings_populates_options_from_installed_plugins(monkeypatch):
    _installed(monkeypatch, {
        "ovos-stt-plugin-vosk": "1.0.0",
        "ovos-tts-plugin-mimic3-server": "1.0.0",
        "ovos-vad-plugin-silero": "1.0.0",
        "ovos-not-a-plugin-at-all": "1.0.0",
    })
    r = voicecfg.get_settings()
    assert r["fields"]["stt_module"]["options"] == ["ovos-stt-plugin-vosk"]
    assert r["fields"]["stt_fallback"]["options"] == ["ovos-stt-plugin-vosk"]
    assert r["fields"]["tts_module"]["options"] == ["ovos-tts-plugin-mimic3-server"]
    assert r["fields"]["vad_module"]["options"] == ["ovos-vad-plugin-silero"]


def test_get_settings_empty_options_when_nothing_installed(monkeypatch):
    _installed(monkeypatch, {})
    r = voicecfg.get_settings()
    assert r["fields"]["stt_module"]["options"] == []
    assert r["fields"]["tts_module"]["options"] == []
    assert r["fields"]["vad_module"]["options"] == []


def test_get_settings_never_raises_when_plugin_listing_breaks(monkeypatch):
    def boom():
        raise RuntimeError("broken site-packages")
    monkeypatch.setattr("ovos_webui.pypi.installed_versions", boom)
    r = voicecfg.get_settings()  # must not raise
    assert r["fields"]["stt_module"]["options"] == []


def test_get_settings_wake_word_options_come_from_hotwords(monkeypatch):
    _installed(monkeypatch, {})
    r = voicecfg.get_settings()
    assert "hey_mycroft" in r["fields"]["wake_word"]["options"]


def test_get_settings_pipeline_options_include_defaults_and_installed(monkeypatch):
    _installed(monkeypatch, {"ovos-ollama-intent-pipeline-plugin": "1.0"})
    r = voicecfg.get_settings()
    opts = r["fields"]["pipeline"]["options"]
    assert "ovos-adapt-pipeline-plugin-high" in opts  # a shipped default
    assert "ovos-ollama-intent-pipeline-plugin" in opts  # installed extra


# ── voicecfg.set_value: each key round-trips ─────────────────────────────────

@pytest.mark.parametrize("key,path,value", [
    ("wake_word", ["listener", "wake_word"], "hey_mycroft"),
    ("vad_module", ["listener", "VAD", "module"], "ovos-vad-plugin-silero"),
    ("stt_module", ["stt", "module"], "ovos-stt-plugin-vosk"),
    ("tts_module", ["tts", "module"], "ovos-tts-plugin-server"),
    ("lang", ["lang"], "pt-pt"),
])
def test_set_value_writes_each_key(key, path, value):
    voicecfg.set_value(key, value)
    assert configio.get_in(configio.read_user_config(), path) == value


def test_set_value_stt_fallback_round_trip():
    voicecfg.set_value("stt_fallback", "ovos-stt-plugin-vosk")
    assert configio.read_user_config()["stt"]["fallback_module"] == "ovos-stt-plugin-vosk"


def test_set_value_empty_fallback_clears_it():
    voicecfg.set_value("stt_fallback", "ovos-stt-plugin-vosk")
    voicecfg.set_value("stt_fallback", "")
    assert "fallback_module" not in configio.read_user_config().get("stt", {})


def test_set_value_pipeline_round_trip():
    stages = ["ovos-stop-pipeline-plugin-high", "ovos-adapt-pipeline-plugin-high"]
    voicecfg.set_value("pipeline", stages)
    assert configio.read_user_config()["intents"]["pipeline"] == stages


def test_set_value_pipeline_rejects_empty_list():
    with pytest.raises(voicecfg.VoiceConfigError):
        voicecfg.set_value("pipeline", [])


def test_set_value_pipeline_rejects_duplicate_stage():
    with pytest.raises(voicecfg.VoiceConfigError):
        voicecfg.set_value("pipeline", ["a", "a"])


def test_set_value_pipeline_rejects_non_list():
    with pytest.raises(voicecfg.VoiceConfigError):
        voicecfg.set_value("pipeline", "not-a-list")


def test_set_value_transformers_round_trip():
    voicecfg.set_value("utterance_transformers", ["ovos-utterance-normalizer"])
    section = configio.read_user_config()["utterance_transformers"]
    assert section == {"ovos-utterance-normalizer": {}}


def test_set_value_transformers_keeps_existing_plugin_config():
    configio.write_user_config({
        "utterance_transformers": {"ovos-utterance-normalizer": {"some": "opt"}}})
    voicecfg.set_value("utterance_transformers", ["ovos-utterance-normalizer", "ovos-utterance-plugin-cancel"])
    section = configio.read_user_config()["utterance_transformers"]
    assert section["ovos-utterance-normalizer"] == {"some": "opt"}
    assert section["ovos-utterance-plugin-cancel"] == {}


def test_set_value_metadata_transformers_round_trip():
    voicecfg.set_value("metadata_transformers", ["ovos-audio-transformer-plugin-example"])
    section = configio.read_user_config()["metadata_transformers"]
    assert section == {"ovos-audio-transformer-plugin-example": {}}


def test_set_value_secondary_langs_round_trip():
    voicecfg.set_value("secondary_langs", ["en-us", "pt-pt"])
    assert configio.read_user_config()["secondary_langs"] == ["en-us", "pt-pt"]


def test_set_value_secondary_langs_rejects_bad_code():
    with pytest.raises(voicecfg.VoiceConfigError):
        voicecfg.set_value("secondary_langs", ["not a code!"])


def test_set_value_lang_rejects_bad_code():
    with pytest.raises(voicecfg.VoiceConfigError):
        voicecfg.set_value("lang", "not a code!")


def test_set_value_module_rejects_empty_string():
    with pytest.raises(voicecfg.VoiceConfigError):
        voicecfg.set_value("stt_module", "")


def test_set_value_module_rejects_non_string():
    with pytest.raises(voicecfg.VoiceConfigError):
        voicecfg.set_value("tts_module", 123)


def test_set_value_module_rejects_multiline():
    with pytest.raises(voicecfg.VoiceConfigError):
        voicecfg.set_value("stt_module", "line1\nline2")


# ── the key allowlist rejects arbitrary config-path injection ───────────────

def test_set_value_rejects_unknown_key():
    with pytest.raises(voicecfg.VoiceConfigError):
        voicecfg.set_value("__proto__", "x")


def test_set_value_cannot_write_an_arbitrary_config_path():
    """The allowlist is by field name, not by an arbitrary path a caller could
    pass in — there is no way to reach, say, ``auth.token`` through this API."""
    with pytest.raises(voicecfg.VoiceConfigError):
        voicecfg.set_value("auth.token", "hijacked")
    assert "auth" not in configio.read_user_config()


# ── HTTP routes ───────────────────────────────────────────────────────────────

def test_get_voice_route_shape(token_client, monkeypatch):
    _installed(monkeypatch, {})
    r = token_client.get("/api/voice", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "fields" in body and "wake_word" in body["fields"]


def test_post_voice_route_writes_the_value(token_client, monkeypatch):
    _installed(monkeypatch, {})
    r = token_client.post("/api/voice", json={"key": "lang", "value": "de-de"}, headers=AUTH)
    assert r.status_code == 200
    assert configio.read_user_config()["lang"] == "de-de"


def test_post_voice_route_rejects_unknown_key(token_client):
    r = token_client.post("/api/voice", json={"key": "auth.token", "value": "x"}, headers=AUTH)
    assert r.status_code == 400


def test_post_voice_route_rejects_bad_value(token_client):
    r = token_client.post("/api/voice", json={"key": "pipeline", "value": []}, headers=AUTH)
    assert r.status_code == 400


def test_post_voice_route_rejects_wrong_body(token_client):
    assert token_client.post("/api/voice", json={"value": "x"}, headers=AUTH).status_code == 422


def test_voice_routes_need_a_token(token_client):
    """The privileged router always needs a token, whatever the bind address."""
    assert token_client.get("/api/voice").status_code == 401
    assert token_client.post("/api/voice", json={"key": "lang", "value": "en-us"}).status_code == 401


def test_voice_notify_emits_existing_message_only(token_client, bus):
    seen = []
    bus.on("configuration.patch", lambda m: seen.append(m.msg_type))
    bus.on("configuration.patch.clear", lambda m: seen.append(m.msg_type))
    token_client.post("/api/voice", json={"key": "lang", "value": "fr-fr"}, headers=AUTH)
    assert seen == ["configuration.patch.clear", "configuration.patch"]


def test_voice_page_served(client):
    r = client.get("/voice")
    assert r.status_code == 200
    assert 'class="skip"' in r.text
    assert 'href="#main"' in r.text
    assert 'id="main"' in r.text and "tabindex" in r.text
    assert "aria-label" in r.text


def test_get_settings_survives_a_malformed_config(monkeypatch):
    """A hand-edited config with wrong shapes must not 500 the page (SEC-001)."""
    _installed(monkeypatch, {})
    configio.write_user_config({
        "intents": {"pipeline": 5},           # should be a list
        "utterance_transformers": ["a", "b"],  # should be a dict
        "metadata_transformers": "oops",       # should be a dict
    })
    r = voicecfg.get_settings()  # must not raise
    assert isinstance(r["fields"]["pipeline"]["options"], list)
    assert isinstance(r["fields"]["utterance_transformers"]["options"], list)
