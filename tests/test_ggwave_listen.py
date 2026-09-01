"""Tests for the "Device listening" toggle on the Send-over-sound panel.

The webui does not run the ggwave listener itself; it only emits the two
bus messages the ovos-audio-transformer-plugin-ggwave plugin already
listens for: ``ovos.ggwave.enable`` and ``ovos.ggwave.disable``. These
tests cover that contract on a FakeBus, plus the auth and bus-down guards
shared by every privileged route.
"""
from fastapi.testclient import TestClient

from ovos_webui.service import create_app

AUTH = {"Authorization": "Bearer s3cret-token"}


def test_ggwave_listen_enable_emits_the_enable_message(token_client, bus):
    seen = []
    bus.on("ovos.ggwave.enable", lambda m: seen.append(m))
    r = token_client.post("/api/ggwave/listen", json={"enabled": True}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert len(seen) == 1
    assert seen[0].data == {}


def test_ggwave_listen_disable_emits_the_disable_message(token_client, bus):
    seen = []
    bus.on("ovos.ggwave.disable", lambda m: seen.append(m.msg_type))
    r = token_client.post("/api/ggwave/listen", json={"enabled": False}, headers=AUTH)
    assert r.status_code == 200
    assert seen == ["ovos.ggwave.disable"]


def test_ggwave_listen_promises_no_auto_off_it_cannot_deliver(token_client, bus):
    """The plugin has no timer and never reads the message data.

    `handle_enable` in ovos-audio-transformer-plugin-ggwave sets a flag and
    replies; there is no `listen_timeout`, no timer, and no path that turns the
    listener off again. Sending a timeout would offer a safety net that does not
    exist, on the one page where being wrong means a microphone stays open.
    """
    seen = []
    bus.on("ovos.ggwave.enable", lambda m: seen.append(m.data))
    r = token_client.post("/api/ggwave/listen", json={"enabled": True}, headers=AUTH)
    assert r.status_code == 200
    assert seen == [{}], "the panel is sending a timeout the plugin discards"
    assert "timeout" not in r.json()


def test_ggwave_listen_ignores_a_timeout_it_cannot_honour(token_client, bus):
    """An old client may still send one; it must not be forwarded."""
    seen = []
    bus.on("ovos.ggwave.enable", lambda m: seen.append(m.data))
    r = token_client.post("/api/ggwave/listen", json={"enabled": True, "timeout": 60},
                          headers=AUTH)
    assert r.status_code == 200
    assert seen == [{}]


def test_ggwave_listen_needs_a_token(token_client):
    r = token_client.post("/api/ggwave/listen", json={"enabled": True})
    assert r.status_code == 401


def test_ggwave_listen_without_a_token_configured_is_refused(client):
    # No token configured at all: privileged actions are simply off.
    r = client.post("/api/ggwave/listen", json={"enabled": True})
    assert r.status_code == 403


def test_ggwave_listen_503_without_a_device():
    # a token app whose bus is None (no device connected)
    app = create_app(bus=None, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        r = c.post("/api/ggwave/listen", json={"enabled": True}, headers=AUTH)
        assert r.status_code == 503
