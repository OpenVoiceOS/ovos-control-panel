"""Now playing, transport, and volume over OCP / ovos-media: status (rich
reply and track_info fallback), transport emits, volume get/set, the ping
capability probe, and the privileged/503 routes."""
import pytest


def _reply(bus, req_topic, data):
    """Wire ``req_topic`` to answer with ``req_topic``.response carrying ``data``."""
    from ovos_bus_client.message import Message

    bus.on(req_topic, lambda m: bus.emit(Message(
        req_topic + ".response", data, m.context)))


# ── status ───────────────────────────────────────────────────────────────────
def test_status_maps_player_state_and_returns_metadata(bus):
    from ovos_webui import media

    _reply(bus, "ovos.common_play.status", {
        "player_state": 1, "media_type": "music", "title": "Song",
        "artist": "Artist", "image": "http://x/img.png", "shuffle": True,
        "playlist_position": 2, "playlist_size": 5,
    })
    s = media.status(bus)
    assert s == {
        "state": "playing", "media_type": "music", "title": "Song",
        "artist": "Artist", "image": "http://x/img.png", "shuffle": True,
        "playlist_position": 2, "playlist_size": 5,
    }


def test_status_maps_paused_and_stopped():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import media

    for value, name in ((2, "paused"), (0, "stopped")):
        bus = FakeBus()
        _reply(bus, "ovos.common_play.status", {"player_state": value})
        assert media.status(bus)["state"] == name


def test_status_maps_unrecognized_player_state_to_unknown():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import media

    bus = FakeBus()
    _reply(bus, "ovos.common_play.status", {"player_state": 5})
    assert media.status(bus)["state"] == "unknown"


def test_status_falls_back_to_track_info_when_status_unanswered():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import media

    media.QUERY_TIMEOUT = 0.3
    bus = FakeBus()
    _reply(bus, "ovos.common_play.track_info", {
        "title": "Old Song", "artist": "Old Artist", "image": "http://x/old.png",
        "media_type": "music",
    })
    s = media.status(bus)
    assert s["title"] == "Old Song"
    assert s["artist"] == "Old Artist"
    assert s["image"] == "http://x/old.png"
    assert s["state"] == "stopped"  # unknown from track_info alone


def test_status_with_no_responder_returns_empty_stopped_state():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import media

    media.QUERY_TIMEOUT = 0.3
    s = media.status(FakeBus())
    assert s["state"] == "stopped"
    assert s["title"] is None


# ── capability probe ─────────────────────────────────────────────────────────
def test_available_true_on_pong(bus):
    from ovos_bus_client.message import Message
    from ovos_webui import media

    bus.on("ovos.common_play.ping",
           lambda m: bus.emit(Message("ovos.common_play.pong", {}, m.context)))
    assert media.available(bus) is True


def test_available_false_without_a_responder():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import media

    media.PING_TIMEOUT = 0.3
    assert media.available(FakeBus()) is False


# ── transport ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("func_name,msg_type", [
    ("play_pause", "ovos.common_play.play_pause"),
    ("pause", "ovos.common_play.pause"),
    ("resume", "ovos.common_play.resume"),
    ("stop", "ovos.common_play.stop"),
    ("next", "ovos.common_play.next"),
    ("previous", "ovos.common_play.previous"),
])
def test_transport_emits_the_right_message_type(bus, func_name, msg_type):
    from ovos_webui import media

    seen = []
    bus.on(msg_type, lambda m: seen.append(m.msg_type))
    result = getattr(media, func_name)(bus)
    assert result == {"ok": True}
    assert seen == [msg_type]


def test_transport_reports_not_ok_on_a_disconnected_bus():
    import threading

    from ovos_utils.fakebus import FakeBus
    from ovos_webui import media

    bus = FakeBus()
    bus.connected_event = threading.Event()  # never set = not connected
    assert media.play_pause(bus) == {"ok": False}


# ── volume ───────────────────────────────────────────────────────────────────
def test_get_volume_converts_fraction_to_percent(bus):
    from ovos_webui import media

    _reply(bus, "mycroft.volume.get", {"percent": 0.42, "muted": False})
    v = media.get_volume(bus)
    assert v == {"percent": 42, "muted": False}


def test_get_volume_treats_a_value_over_1_as_already_a_percent(bus):
    """A plugin that (against the documented contract) already answers with
    a 0-100 int must not get re-scaled into e.g. 5000%."""
    from ovos_webui import media

    _reply(bus, "mycroft.volume.get", {"percent": 50})
    assert media.get_volume(bus)["percent"] == 50


def test_get_volume_full_scale_fraction_and_over_range_values():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import media

    bus = FakeBus()
    _reply(bus, "mycroft.volume.get", {"percent": 1.0})
    assert media.get_volume(bus)["percent"] == 100

    bus = FakeBus()
    _reply(bus, "mycroft.volume.get", {"percent": 250})
    assert media.get_volume(bus)["percent"] == 100  # clamped


def test_get_volume_without_a_responder_returns_unknowns():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import media

    media.QUERY_TIMEOUT = 0.3
    assert media.get_volume(FakeBus()) == {"percent": None, "muted": None}


def test_set_volume_emits_the_gui_variant_with_int_percent(bus):
    from ovos_webui import media

    seen = []
    bus.on("mycroft.volume.set.gui", lambda m: seen.append(m.data))
    r = media.set_volume(bus, 73)
    assert r["percent"] == 73
    assert seen == [{"percent": 73}]


def test_set_volume_rejects_out_of_range_and_bool():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import media

    bus = FakeBus()
    with pytest.raises(ValueError):
        media.set_volume(bus, 101)
    with pytest.raises(ValueError):
        media.set_volume(bus, -1)
    with pytest.raises(ValueError):
        media.set_volume(bus, True)


def test_mute_and_unmute_emit(bus):
    from ovos_webui import media

    seen = []
    bus.on("mycroft.volume.mute", lambda m: seen.append("mute"))
    bus.on("mycroft.volume.unmute", lambda m: seen.append("unmute"))
    assert media.mute(bus) == {"muted": True, "ok": True}
    assert media.unmute(bus) == {"muted": False, "ok": True}
    assert seen == ["mute", "unmute"]


# ── routes ───────────────────────────────────────────────────────────────────
def test_media_routes_need_a_token(token_client):
    assert token_client.get("/api/media/status").status_code == 401
    assert token_client.get("/api/media/available").status_code == 401
    assert token_client.post("/api/media/play_pause").status_code == 401
    assert token_client.post("/api/media/next").status_code == 401
    assert token_client.post("/api/media/previous").status_code == 401
    assert token_client.post("/api/media/stop").status_code == 401
    assert token_client.get("/api/media/volume").status_code == 401
    assert token_client.post("/api/media/volume", json={"percent": 10}).status_code == 401
    assert token_client.post("/api/media/mute").status_code == 401
    assert token_client.post("/api/media/unmute").status_code == 401


def test_media_read_routes_require_privilege(client):
    # No token configured at all: previously these GETs sat on the plain
    # ``api`` router and were reachable; they must now be refused like the
    # other media routes that change device state.
    assert client.get("/api/media/status").status_code == 403
    assert client.get("/api/media/available").status_code == 403
    assert client.get("/api/media/volume").status_code == 403


def test_media_routes_403_without_a_token_configured(client):
    assert client.post("/api/media/play_pause").status_code == 403
    assert client.post("/api/media/volume", json={"percent": 10}).status_code == 403


def test_media_routes_503_without_a_device():
    from fastapi.testclient import TestClient
    from ovos_webui.service import create_app

    app = create_app(bus=None, host="0.0.0.0", token="s3cret-token",
                     connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        auth = {"Authorization": "Bearer s3cret-token"}
        assert c.get("/api/media/status", headers=auth).status_code == 503
        assert c.post("/api/media/play_pause", headers=auth).status_code == 503
        assert c.get("/api/media/volume", headers=auth).status_code == 503
        assert c.post("/api/media/volume", json={"percent": 10},
                      headers=auth).status_code == 503


def test_media_status_route_reads_the_bus(bus):
    from fastapi.testclient import TestClient
    from ovos_webui.service import create_app

    _reply(bus, "ovos.common_play.status", {
        "player_state": 1, "title": "Song", "artist": "Artist",
    })
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token",
                     connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        r = c.get("/api/media/status",
                  headers={"Authorization": "Bearer s3cret-token"})
        assert r.status_code == 200
        assert r.json()["state"] == "playing"
        assert r.json()["title"] == "Song"


def test_media_volume_set_route_validates_range(bus):
    from fastapi.testclient import TestClient
    from ovos_webui.service import create_app

    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token",
                     connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        auth = {"Authorization": "Bearer s3cret-token"}
        assert c.post("/api/media/volume", json={"percent": 200},
                      headers=auth).status_code == 422


def test_media_page_renders(client):
    assert client.get("/media").status_code == 200
