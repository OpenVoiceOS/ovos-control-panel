"""Tests for the configuration routes."""
import json

import pytest

from ovos_webui import configio
from ovos_webui.fsutils import MAX_PAYLOAD_BYTES


def test_get_config_json(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "json"
    assert json.loads(body["text"]) == {}


def test_get_config_yaml(client):
    r = client.get("/api/config?format=yaml")
    assert r.status_code == 200
    assert r.json()["format"] == "yaml"


def test_get_config_rejects_unknown_format(client):
    assert client.get("/api/config?format=toml").status_code == 400


def test_put_config_round_trip(client):
    payload = {"text": json.dumps({"lang": "pt-pt"}), "format": "json"}
    r = client.put("/api/config", json=payload)
    assert r.status_code == 200
    assert configio.read_user_config()["lang"] == "pt-pt"
    assert json.loads(client.get("/api/config").json()["text"])["lang"] == "pt-pt"


def test_put_config_makes_a_backup(client):
    client.put("/api/config", json={"text": '{"lang": "en-us"}', "format": "json"})
    r = client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    backup = r.json()["backup"]
    with open(backup) as handle:
        assert json.load(handle)["lang"] == "en-us"
    assert backup


def test_put_config_can_delete_a_key(client):
    client.put("/api/config", json={"text": '{"lang": "pt-pt", "extra": 1}', "format": "json"})
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    assert "extra" not in configio.read_user_config()


def test_put_config_yaml(client):
    r = client.put("/api/config", json={"text": "lang: de-de\n", "format": "yaml"})
    assert r.status_code == 200
    assert configio.read_user_config()["lang"] == "de-de"


@pytest.mark.parametrize("text,fmt", [
    ("{not json", "json"),
    ("[1, 2]", "json"),
    ("\"a string\"", "json"),
    ("a: [unclosed", "yaml"),
    ("- 1\n- 2\n", "yaml"),
])
def test_put_config_rejects_bad_text(client, text, fmt):
    r = client.put("/api/config", json={"text": text, "format": fmt})
    assert r.status_code == 400


def test_put_config_rejects_unknown_format(client):
    r = client.put("/api/config", json={"text": "{}", "format": "toml"})
    assert r.status_code == 422


def test_put_config_rejects_oversized_body(client):
    big = json.dumps({"pad": "x" * (MAX_PAYLOAD_BYTES + 1024)})
    r = client.put("/api/config", json={"text": big, "format": "json"})
    assert r.status_code == 413


def test_bad_content_length_header_is_refused(client):
    r = client.put("/api/config", content=b"{}",
                   headers={"content-length": "not-a-number",
                            "content-type": "application/json"})
    assert r.status_code in (400, 422)


def test_merged_config_includes_defaults(client):
    body = client.get("/api/config/merged").json()["config"]
    assert isinstance(body, dict) and "lang" in body


def test_quick_form_lists_known_keys(client):
    fields = client.get("/api/config/quick").json()["fields"]
    names = [f["name"] for f in fields]
    assert "tts.module" in names and "listener.wake_word" in names
    assert all("options" in f for f in fields if f["kind"] in ("choice", "plugin"))


def test_quick_form_save_and_clear(client):
    r = client.post("/api/config/quick",
                    json={"values": {"lang": "fr-fr", "listener.wake_word": "hey_mycroft"}})
    assert r.status_code == 200
    user = configio.read_user_config()
    assert user["lang"] == "fr-fr"
    assert user["listener"]["wake_word"] == "hey_mycroft"

    client.post("/api/config/quick", json={"values": {"lang": ""}})
    assert "lang" not in configio.read_user_config()


def test_quick_form_rejects_unknown_field(client):
    r = client.post("/api/config/quick", json={"values": {"evil.path": "x"}})
    assert r.status_code == 400
    assert "unknown field" in r.json()["detail"]


def test_quick_form_rejects_wrong_body(client):
    assert client.post("/api/config/quick", json={"values": "nope"}).status_code == 422


def test_plugins_endpoint_shape(client):
    plugins = client.get("/api/plugins").json()["plugins"]
    assert set(plugins) == {"tts", "stt", "wake_word", "vad", "gui"}
    assert all(isinstance(v, list) for v in plugins.values())


def test_saving_does_not_emit_when_the_bus_is_down():
    """A save must not touch a disconnected bus client.

    ``MessageBusClient.emit`` waits for the connection with no limit, so an
    emit here would make the request hang until the bus comes back.
    """
    import threading

    calls = []

    class DisconnectedClient:
        connected_event = threading.Event()  # never set

        def emit(self, message):
            calls.append(message.msg_type)

    configio.write_user_config({"lang": "pt-pt"}, bus=DisconnectedClient())
    assert calls == [], "emit was called on a disconnected bus"
    assert configio.read_user_config()["lang"] == "pt-pt"


def test_saving_emits_when_the_bus_is_connected():
    import threading

    seen = []

    class ConnectedClient:
        def __init__(self):
            self.connected_event = threading.Event()
            self.connected_event.set()

        def emit(self, message):
            seen.append(message.msg_type)

    configio.write_user_config({"lang": "pt-pt"}, bus=ConnectedClient())
    # The volatile patch layer is only ever added to, so it must be cleared
    # before the new configuration is sent, or a deleted key survives.
    assert seen == ["configuration.patch.clear", "configuration.patch"]


def test_config_notify_emits_existing_message_only(client, bus):
    seen = []
    bus.on("configuration.patch", lambda m: seen.append(m.msg_type))
    bus.on("configuration.patch.clear", lambda m: seen.append(m.msg_type))
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    assert seen == ["configuration.patch.clear", "configuration.patch"]


def test_wake_word_field_offers_the_configured_hotwords(client):
    fields = {f["name"]: f for f in client.get("/api/config/quick").json()["fields"]}
    ww = fields["listener.wake_word"]
    assert ww["kind"] == "hotword"
    assert "hey_mycroft" in ww["options"], ww["options"]
