"""Wallpaper manager over a FakeBus, plus the privileged HTTP routes.

Bus messages verified against ovos-PHAL-plugin-wallpaper-manager source: the
``ovos.wallpaper.manager.get.*`` / ``set.*`` queries, all using the
``message.response()`` convention, and the fire-and-forget ``change.wallpaper`` /
``set.active.provider`` / ``enable|disable.auto.rotation``.
"""
import pytest

from ovos_webui import wallpaper

_AUTH = {"Authorization": "Bearer s3cret-token"}
_B = "ovos.wallpaper.manager"


def _reply(bus, suffix, data):
    from ovos_bus_client.message import Message
    topic = f"{_B}.{suffix}"
    bus.on(topic, lambda m: bus.emit(Message(topic + ".response", data, m.context)))


def _full(bus):
    _reply(bus, "get.wallpaper", {"url": "/data/current.jpg"})
    _reply(bus, "get.registered.providers", {"registered_providers": [
        {"provider_name": "local", "provider_display_name": "Local photos"},
        {"provider_name": "unsplash", "provider_display_name": "Unsplash"}]})
    _reply(bus, "get.collection", {"wallpaper_collection": ["/a.jpg", "/b.jpg"]})
    _reply(bus, "get.active.provider", {"active_provider": "local"})
    _reply(bus, "get.auto.rotation", {"auto_rotation": True, "rotation_time": 60})


# ── state ────────────────────────────────────────────────────────────────────

def test_get_state_assembles_everything(bus):
    _full(bus)
    s = wallpaper.get_state(bus)
    assert s["available"] is True
    assert s["current"] == "/data/current.jpg"
    assert s["active_provider"] == "local"
    assert [p["provider_display_name"] for p in s["providers"]] == ["Local photos", "Unsplash"]
    assert s["collection"] == ["/a.jpg", "/b.jpg"]
    assert s["auto_rotation"] is True and s["rotation_time"] == 60


def test_get_state_unavailable_when_manager_silent(bus):
    wallpaper.QUERY_TIMEOUT = 0.3
    assert wallpaper.get_state(bus) == {"available": False}


def test_get_state_drops_providers_without_a_name(bus):
    wallpaper.QUERY_TIMEOUT = 4.0
    _reply(bus, "get.wallpaper", {"url": None})
    _reply(bus, "get.registered.providers", {"registered_providers": [
        {"provider_display_name": "nameless"}, {"provider_name": "ok"}]})
    _reply(bus, "get.collection", {"wallpaper_collection": []})
    _reply(bus, "get.active.provider", {"active_provider": None})
    _reply(bus, "get.auto.rotation", {"auto_rotation": False})
    s = wallpaper.get_state(bus)
    assert [p["provider_name"] for p in s["providers"]] == ["ok"]


# ── set / fire-and-forget ────────────────────────────────────────────────────

def test_set_wallpaper_returns_the_stored_url(bus):
    _reply(bus, "set.wallpaper", {"wallpaper": "/data/stored.jpg"})
    out = wallpaper.set_wallpaper(bus, "https://x/y.jpg")
    assert out == {"available": True, "url": "/data/stored.jpg"}


def test_set_wallpaper_rejects_blank(bus):
    with pytest.raises(wallpaper.WallpaperError):
        wallpaper.set_wallpaper(bus, "   ")


def test_next_emits_change(bus):
    sent = []
    bus.on(f"{_B}.change.wallpaper", lambda m: sent.append(m.msg_type))
    wallpaper.next_wallpaper(bus)
    assert sent == [f"{_B}.change.wallpaper"]


def test_set_provider_emits_with_name(bus):
    sent = []
    bus.on(f"{_B}.set.active.provider", lambda m: sent.append(m.data))
    wallpaper.set_provider(bus, "unsplash")
    assert sent == [{"provider_name": "unsplash"}]


def test_set_provider_rejects_empty(bus):
    with pytest.raises(wallpaper.WallpaperError):
        wallpaper.set_provider(bus, "")


def test_auto_rotation_emits_enable_and_disable(bus):
    on, off = [], []
    bus.on(f"{_B}.enable.auto.rotation", lambda m: on.append(1))
    bus.on(f"{_B}.disable.auto.rotation", lambda m: off.append(1))
    wallpaper.set_auto_rotation(bus, True)
    wallpaper.set_auto_rotation(bus, False)
    assert on == [1] and off == [1]


# ── HTTP routes ──────────────────────────────────────────────────────────────

def test_wallpaper_page_needs_auth(token_client):
    r = token_client.get("/wallpaper", follow_redirects=False)
    assert r.status_code in (302, 303)


def test_wallpaper_routes_need_a_token(token_client):
    assert token_client.get("/api/wallpaper").status_code in (401, 403)
    assert token_client.post("/api/wallpaper/set",
                             json={"url": "x"}).status_code in (401, 403)


def test_api_state_roundtrip(token_client, bus):
    wallpaper.QUERY_TIMEOUT = 4.0
    _full(bus)
    r = token_client.get("/api/wallpaper", headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["current"] == "/data/current.jpg"


def test_api_set_roundtrip(token_client, bus):
    _reply(bus, "set.wallpaper", {"wallpaper": "/data/stored.jpg"})
    r = token_client.post("/api/wallpaper/set", headers=_AUTH,
                          json={"url": "https://x/y.jpg"})
    assert r.status_code == 200 and r.json()["url"] == "/data/stored.jpg"


def test_api_next_roundtrip(token_client, bus):
    sent = []
    bus.on(f"{_B}.change.wallpaper", lambda m: sent.append(1))
    r = token_client.post("/api/wallpaper/next", headers=_AUTH)
    assert r.status_code == 200 and sent == [1]
