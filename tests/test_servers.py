"""Self-hosted STT / TTS / translate server lists.

``servers.get_servers``/``set_servers`` read and write the exact keys the
plugins themselves read (confirmed against the plugin source, see
ovos_webui/servers.py's docstring): ``stt.<module>.urls``,
``tts.<module>.host``, ``language.<module>.host`` (one entry per module in the
detector/translator pair). Round-trips are done through a temporary config
file, the same way the config editor tests do.
"""
from ovos_webui import configio, servers


# ── get_servers / set_servers ────────────────────────────────────────────────
def test_get_servers_default_module_and_empty_list():
    r = servers.get_servers("stt")
    assert r == {"kind": "stt", "module": "ovos-stt-plugin-server", "urls": []}


def test_set_then_get_round_trips_stt_urls():
    out = servers.set_servers("stt", ["https://stt.example.com", "http://stt2.example.com:8080"])
    assert out["urls"] == ["https://stt.example.com", "http://stt2.example.com:8080"]
    got = servers.get_servers("stt")
    assert got["urls"] == ["https://stt.example.com", "http://stt2.example.com:8080"]
    # written under the exact key the plugin reads
    assert configio.read_user_config()["stt"]["ovos-stt-plugin-server"]["urls"] == out["urls"]


def test_set_then_get_round_trips_tts_urls_under_host_key():
    servers.set_servers("tts", ["https://tts.example.com"])
    assert configio.read_user_config()["tts"]["ovos-tts-plugin-server"]["host"] == \
        ["https://tts.example.com"]
    assert servers.get_servers("tts")["urls"] == ["https://tts.example.com"]


def test_set_then_get_round_trips_translate_urls_on_both_modules():
    servers.set_servers("translate", ["https://nllb.example.com"])
    user = configio.read_user_config()
    assert user["language"]["ovos-lang-detector-plugin-server"]["host"] == \
        ["https://nllb.example.com"]
    assert user["language"]["ovos-translate-plugin-server"]["host"] == \
        ["https://nllb.example.com"]
    got = servers.get_servers("translate")
    assert got["urls"] == ["https://nllb.example.com"]
    assert got["detection_module"] == "ovos-lang-detector-plugin-server"
    assert got["translation_module"] == "ovos-translate-plugin-server"


def test_set_respects_a_custom_configured_module_name():
    configio.mutate(lambda user: configio.set_in(user, ["stt", "module"], "my-custom-stt"))
    out = servers.set_servers("stt", ["https://stt.example.com"])
    assert out["module"] == "my-custom-stt"
    assert configio.read_user_config()["stt"]["my-custom-stt"]["urls"] == \
        ["https://stt.example.com"]


def test_set_empty_list_clears_the_key():
    servers.set_servers("stt", ["https://stt.example.com"])
    assert configio.read_user_config()["stt"]["ovos-stt-plugin-server"]["urls"]
    servers.set_servers("stt", [])
    assert "urls" not in configio.read_user_config().get("stt", {}).get(
        "ovos-stt-plugin-server", {})
    assert servers.get_servers("stt")["urls"] == []


# ── validation: never raises, returns an error dict ──────────────────────────
def test_set_rejects_a_non_url():
    out = servers.set_servers("stt", ["not a url"])
    assert "error" in out
    assert configio.read_user_config().get("stt", {}) == {}


def test_set_rejects_a_non_http_scheme():
    out = servers.set_servers("stt", ["ftp://example.com"])
    assert "error" in out


def test_set_rejects_too_many_urls():
    urls = [f"https://s{i}.example.com" for i in range(servers.MAX_URLS + 1)]
    out = servers.set_servers("stt", urls)
    assert "error" in out


def test_set_accepts_exactly_the_maximum():
    urls = [f"https://s{i}.example.com" for i in range(servers.MAX_URLS)]
    out = servers.set_servers("stt", urls)
    assert "error" not in out
    assert len(out["urls"]) == servers.MAX_URLS


def test_set_rejects_an_oversized_url():
    out = servers.set_servers("stt", ["https://example.com/" + "x" * servers.MAX_URL_LENGTH])
    assert "error" in out


def test_set_rejects_a_non_list():
    out = servers.set_servers("stt", "https://example.com")
    assert "error" in out


def test_set_rejects_control_characters():
    out = servers.set_servers("stt", ["https://example.com/\nx"])
    assert "error" in out


def test_set_unknown_kind_returns_error_not_raise():
    out = servers.set_servers("bogus", ["https://example.com"])
    assert "error" in out


def test_get_unknown_kind_returns_error_not_raise():
    out = servers.get_servers("bogus")
    assert "error" in out


def test_set_blank_entries_are_dropped_not_rejected():
    out = servers.set_servers("stt", ["https://example.com", "   ", ""])
    assert "error" not in out
    assert out["urls"] == ["https://example.com"]


# ── routes: privileged, need a token ─────────────────────────────────────────
def test_get_servers_route_needs_a_token(token_client):
    assert token_client.get("/api/servers").status_code == 401


def test_post_servers_route_needs_a_token(token_client):
    r = token_client.post("/api/servers/stt", json={"urls": ["https://example.com"]})
    assert r.status_code == 401


def test_get_servers_route_with_token(token_client):
    auth = {"Authorization": "Bearer s3cret-token"}
    r = token_client.get("/api/servers", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"stt", "tts", "translate"}


def test_post_servers_route_round_trips_via_http(token_client):
    auth = {"Authorization": "Bearer s3cret-token"}
    r = token_client.post("/api/servers/tts", json={"urls": ["https://tts.example.com"]},
                          headers=auth)
    assert r.status_code == 200
    assert r.json()["urls"] == ["https://tts.example.com"]
    r2 = token_client.get("/api/servers", headers=auth)
    assert r2.json()["tts"]["urls"] == ["https://tts.example.com"]


def test_post_servers_route_rejects_bad_url_with_400(token_client):
    auth = {"Authorization": "Bearer s3cret-token"}
    r = token_client.post("/api/servers/stt", json={"urls": ["not a url"]}, headers=auth)
    assert r.status_code == 400


def test_post_servers_route_rejects_unknown_kind_with_404(token_client):
    auth = {"Authorization": "Bearer s3cret-token"}
    r = token_client.post("/api/servers/bogus", json={"urls": []}, headers=auth)
    assert r.status_code == 404


def test_servers_page_renders(client):
    assert client.get("/servers").status_code == 200


def test_validate_urls_rejects_whitespace_and_control_chars():
    """A URL with a raw TAB, C0/DEL control, NEL, or Unicode separator/space is
    rejected, not stored verbatim (SEC-001 hardening)."""
    import pytest
    from ovos_webui import servers
    for bad in ["http://a\tb", "http://a\x01b", "http://a\x0bb", "http://a\x7fb",
                "http://a\x85b", "http:// x", "http://a　b", "http://a b"]:
        with pytest.raises(servers.ServersError):
            servers._validate_urls([bad])
    # a clean URL still passes
    assert servers._validate_urls(["https://stt.example.com/asr"]) == ["https://stt.example.com/asr"]
