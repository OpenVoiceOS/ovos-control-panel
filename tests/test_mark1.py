"""Tests for the Mark-1 faceplate panel: the capability probe, the
``enclosure.*`` messages each control emits, validation, and the auth/bus
guards shared by every privileged route.

The img_code the display route sends is cross-checked against
``ovos_mark1.faceplate.FaceplateGrid`` encoding the same grid directly — this
proves ``mark1.py`` reuses the canonical encoder rather than re-deriving it.
"""
from fastapi.testclient import TestClient

from ovos_webui.service import create_app

AUTH = {"Authorization": "Bearer s3cret-token"}


def _grid(fill=0):
    return [[fill] * 32 for _ in range(8)]


# ── capability probe ─────────────────────────────────────────────────────────
def test_available_true_when_the_plugin_answers(bus):
    from ovos_bus_client.message import Message
    from ovos_webui import mark1

    bus.on("enclosure.eyes.rgb.get", lambda m: bus.emit(
        Message("enclosure.eyes.rgb", {"pixels": [[0, 0, 0]]}, m.context)))
    assert mark1.available(bus) == {"available": True}


def test_available_false_with_no_responder(bus):
    from ovos_webui import mark1

    mark1.PROBE_TIMEOUT = 0.3
    assert mark1.available(bus) == {"available": False}


# ── mouth display: the img_code cross-check ──────────────────────────────────
def test_display_emits_mouth_display_with_the_canonical_encoding(bus):
    from ovos_mark1.faceplate import FaceplateGrid
    from ovos_webui import mark1

    grid = _grid(0)
    # a small recognizable pattern
    grid[0][0] = 1
    grid[3][10] = 1
    grid[7][31] = 1

    seen = []
    bus.on("enclosure.mouth.display", lambda m: seen.append(m.data))

    result = mark1.display_grid(bus, grid, x=1, y=2, clear=False)

    expected_code = FaceplateGrid(grid=[row[:] for row in grid]).encode(invert=True)
    assert result["ok"] is True
    assert result["img_code"] == expected_code
    assert len(seen) == 1
    # the plugin lower-cases clearPrev before comparing it, so it is a string
    assert seen[0] == {"img_code": expected_code, "xOffset": 1, "yOffset": 2,
                       "clearPrev": "false"}


def test_display_rejects_wrong_shape(bus):
    from ovos_webui import mark1

    assert mark1.display_grid(bus, [[0] * 32] * 7)["ok"] is False  # 7 rows
    assert mark1.display_grid(bus, [[0] * 31] * 8)["ok"] is False  # 31 cols
    assert mark1.display_grid(bus, [[2] * 32] * 8)["ok"] is False  # bad value
    assert mark1.display_grid(bus, "nope")["ok"] is False


# ── mouth: text, reset, animations, visemes ──────────────────────────────────
def test_mouth_text_emits_text_message(bus):
    from ovos_webui import mark1

    seen = []
    bus.on("enclosure.mouth.text", lambda m: seen.append(m.data))
    assert mark1.mouth_text(bus, "hello")["ok"] is True
    assert seen == [{"text": "hello"}]


def test_mouth_reset_emits_reset(bus):
    from ovos_webui import mark1

    seen = []
    bus.on("enclosure.mouth.reset", lambda m: seen.append(True))
    assert mark1.mouth_reset(bus)["ok"] is True
    assert seen == [True]


def test_mouth_anim_activates_events_before_the_animation(bus):
    from ovos_webui import mark1

    order = []
    bus.on("enclosure.mouth.events.activate", lambda m: order.append("activate"))
    bus.on("enclosure.mouth.talk", lambda m: order.append("talk"))
    assert mark1.mouth_anim(bus, "talk")["ok"] is True
    assert order == ["activate", "talk"]


def test_mouth_anim_rejects_unknown_kind(bus):
    from ovos_webui import mark1

    assert mark1.mouth_anim(bus, "dance")["ok"] is False


def test_mouth_viseme_wraps_into_a_viseme_list_and_activates_events(bus):
    from ovos_webui import mark1

    order = []
    seen = []
    bus.on("enclosure.mouth.events.activate", lambda m: order.append("activate"))
    bus.on("enclosure.mouth.viseme_list", lambda m: (order.append("viseme"),
                                                      seen.append(m.data)))
    import time

    assert mark1.mouth_viseme(bus, 3)["ok"] is True
    assert order == ["activate", "viseme"]
    # the code is concatenated onto "mouth.viseme=" by the plugin, and start is
    # a timestamp it compares against now, not an offset
    assert seen[0]["visemes"] == [["3", mark1.VISEME_SECONDS]]
    assert seen[0]["start"] > time.time() - 60


def test_mouth_viseme_rejects_out_of_range_code(bus):
    from ovos_webui import mark1

    assert mark1.mouth_viseme(bus, 7)["ok"] is False
    assert mark1.mouth_viseme(bus, -1)["ok"] is False


# ── eyes ──────────────────────────────────────────────────────────────────────
def test_eyes_color_emits_rgb_ints(bus):
    from ovos_webui import mark1

    seen = []
    bus.on("enclosure.eyes.color", lambda m: seen.append(m.data))
    assert mark1.eyes_color(bus, 10, 20, 30)["ok"] is True
    assert seen == [{"r": 10, "g": 20, "b": 30}]


def test_eyes_color_rejects_out_of_range(bus):
    from ovos_webui import mark1

    assert mark1.eyes_color(bus, 300, 0, 0)["ok"] is False
    assert mark1.eyes_color(bus, -1, 0, 0)["ok"] is False


def test_eyes_blink_rejects_bad_side(bus):
    from ovos_webui import mark1

    assert mark1.eyes_blink(bus, "x")["ok"] is False
    seen = []
    bus.on("enclosure.eyes.blink", lambda m: seen.append(m.data))
    assert mark1.eyes_blink(bus, "l")["ok"] is True
    assert seen == [{"side": "l"}]


def test_eyes_look_rejects_bad_side(bus):
    from ovos_webui import mark1

    assert mark1.eyes_look(bus, "x")["ok"] is False
    seen = []
    bus.on("enclosure.eyes.look", lambda m: seen.append(m.data))
    assert mark1.eyes_look(bus, "u")["ok"] is True
    assert seen == [{"side": "u"}]


def test_eyes_brightness_range(bus):
    from ovos_webui import mark1

    assert mark1.eyes_brightness(bus, 0)["ok"] is False
    assert mark1.eyes_brightness(bus, 31)["ok"] is False
    seen = []
    bus.on("enclosure.eyes.level", lambda m: seen.append(m.data))
    assert mark1.eyes_brightness(bus, 15)["ok"] is True
    assert seen == [{"level": 15}]


def test_eyes_volume_range(bus):
    from ovos_webui import mark1

    assert mark1.eyes_volume(bus, -1)["ok"] is False
    assert mark1.eyes_volume(bus, 12)["ok"] is False
    seen = []
    bus.on("enclosure.eyes.volume", lambda m: seen.append(m.data))
    assert mark1.eyes_volume(bus, 5)["ok"] is True
    assert seen == [{"volume": 5}]


def test_eyes_fill_range(bus):
    from ovos_webui import mark1

    assert mark1.eyes_fill(bus, -1)["ok"] is False
    assert mark1.eyes_fill(bus, 101)["ok"] is False
    seen = []
    bus.on("enclosure.eyes.fill", lambda m: seen.append(m.data))
    assert mark1.eyes_fill(bus, 50)["ok"] is True
    assert seen == [{"percentage": 50}]


def test_eyes_no_data_calls(bus):
    from ovos_webui import mark1

    for fn, topic in ((mark1.eyes_on, "enclosure.eyes.on"),
                      (mark1.eyes_off, "enclosure.eyes.off"),
                      (mark1.eyes_reset, "enclosure.eyes.reset"),
                      (mark1.eyes_narrow, "enclosure.eyes.narrow"),
                      (mark1.eyes_spin, "enclosure.eyes.spin")):
        seen = []
        bus.on(topic, lambda m, seen=seen: seen.append(True))
        assert fn(bus)["ok"] is True
        assert seen == [True]


# ── system ────────────────────────────────────────────────────────────────────
def test_system_no_data_calls(bus):
    from ovos_webui import mark1

    for fn, topic in ((mark1.system_reset, "enclosure.system.reset"),
                      (mark1.system_mute, "enclosure.system.mute"),
                      (mark1.system_unmute, "enclosure.system.unmute")):
        seen = []
        bus.on(topic, lambda m, seen=seen: seen.append(True))
        assert fn(bus)["ok"] is True
        assert seen == [True]


def test_system_blink_range_and_payload(bus):
    from ovos_webui import mark1

    assert mark1.system_blink(bus, 0)["ok"] is False
    assert mark1.system_blink(bus, 21)["ok"] is False
    seen = []
    bus.on("enclosure.system.blink", lambda m: seen.append(m.data))
    assert mark1.system_blink(bus, 3)["ok"] is True
    assert seen == [{"times": 3}]


# ── routes: auth and bus guards ──────────────────────────────────────────────
def test_mark1_routes_need_a_token(token_client):
    assert token_client.get("/api/mark1/available").status_code == 401
    assert token_client.post("/api/mark1/display",
                             json={"grid": _grid()}).status_code == 401
    assert token_client.post("/api/mark1/mouth/text",
                             json={"text": "hi"}).status_code == 401
    assert token_client.post("/api/mark1/mouth/reset").status_code == 401
    assert token_client.post("/api/mark1/mouth/anim",
                             json={"kind": "talk"}).status_code == 401
    assert token_client.post("/api/mark1/mouth/viseme",
                             json={"code": 1}).status_code == 401
    assert token_client.post("/api/mark1/eyes/color",
                             json={"r": 1, "g": 1, "b": 1}).status_code == 401
    assert token_client.post("/api/mark1/eyes/on").status_code == 401
    assert token_client.post("/api/mark1/eyes/off").status_code == 401
    assert token_client.post("/api/mark1/eyes/reset").status_code == 401
    assert token_client.post("/api/mark1/eyes/narrow").status_code == 401
    assert token_client.post("/api/mark1/eyes/spin").status_code == 401
    assert token_client.post("/api/mark1/eyes/blink",
                             json={"side": "l"}).status_code == 401
    assert token_client.post("/api/mark1/eyes/look",
                             json={"side": "c"}).status_code == 401
    assert token_client.post("/api/mark1/eyes/fill",
                             json={"percentage": 1}).status_code == 401
    assert token_client.post("/api/mark1/eyes/brightness",
                             json={"level": 1}).status_code == 401
    assert token_client.post("/api/mark1/eyes/volume",
                             json={"volume": 1}).status_code == 401
    assert token_client.post("/api/mark1/system/reset").status_code == 401
    assert token_client.post("/api/mark1/system/mute").status_code == 401
    assert token_client.post("/api/mark1/system/unmute").status_code == 401
    assert token_client.post("/api/mark1/system/blink",
                             json={"times": 1}).status_code == 401


def test_mark1_routes_503_without_a_device():
    app = create_app(bus=None, host="0.0.0.0", token="s3cret-token",
                     connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        assert c.get("/api/mark1/available", headers=AUTH).status_code == 503
        assert c.post("/api/mark1/display", json={"grid": _grid()},
                      headers=AUTH).status_code == 503
        assert c.post("/api/mark1/mouth/reset", headers=AUTH).status_code == 503
        assert c.post("/api/mark1/eyes/on", headers=AUTH).status_code == 503
        assert c.post("/api/mark1/system/reset", headers=AUTH).status_code == 503


def test_mark1_display_route_round_trips(token_client, bus):
    seen = []
    bus.on("enclosure.mouth.display", lambda m: seen.append(m.data))
    r = token_client.post("/api/mark1/display",
                          json={"grid": _grid(), "x": 0, "y": 0, "clear": True},
                          headers=AUTH)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert len(seen) == 1


def test_mark1_display_route_rejects_bad_shape(token_client, bus):
    r = token_client.post("/api/mark1/display",
                          json={"grid": [[0] * 5] * 5}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_mark1_page_renders(client):
    assert client.get("/mark1").status_code == 200


def test_display_body_rejects_oversized_grid():
    """The grid field is bounded to 8 rows x 32 cols so a huge nested body is
    rejected during validation, not materialized first."""
    import pytest
    from pydantic import ValidationError
    from ovos_webui.service import Mark1DisplayBody

    with pytest.raises(ValidationError):
        Mark1DisplayBody(grid=[[0] * 32] * 9)          # too many rows
    with pytest.raises(ValidationError):
        Mark1DisplayBody(grid=[[0] * 33] + [[0] * 32] * 7)  # a row too wide
    # a valid 8x32 grid is still accepted
    Mark1DisplayBody(grid=[[0] * 32] * 8)
