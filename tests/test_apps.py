"""Application launcher over a FakeBus, plus the privileged HTTP routes.

Bus messages verified against ovos-PHAL-plugin-app-launcher source:
``ovos.phal.app_launcher.list`` / ``.launch`` / ``.close``, all using the
``message.response()`` convention (reply type = request type + ``.response``).
"""
import pytest

from ovos_webui import applauncher

_AUTH = {"Authorization": "Bearer s3cret-token"}


def _reply(bus, req_topic, data):
    """Answer ``req_topic`` with ``req_topic``.response carrying ``data``."""
    from ovos_bus_client.message import Message
    bus.on(req_topic, lambda m: bus.emit(Message(req_topic + ".response", data, m.context)))


# ── list ─────────────────────────────────────────────────────────────────────

def test_list_apps_returns_apps(bus):
    _reply(bus, "ovos.phal.app_launcher.list",
           {"apps": [{"name": "Firefox", "exec": "firefox"},
                     {"name": "Files", "exec": "nautilus"}]})
    out = applauncher.list_apps(bus)
    assert out["available"] is True
    assert out["apps"][0] == {"name": "Firefox", "exec": "firefox"}


def test_list_apps_drops_malformed_entries(bus):
    _reply(bus, "ovos.phal.app_launcher.list",
           {"apps": [{"name": "Ok", "exec": "ok"}, {"noname": 1}, "junk", 5]})
    assert applauncher.list_apps(bus)["apps"] == [{"name": "Ok", "exec": "ok"}]


def test_list_apps_unavailable_when_no_reply(bus):
    applauncher.QUERY_TIMEOUT = 0.3
    assert applauncher.list_apps(bus) == {"available": False, "apps": []}


# ── launch / close ───────────────────────────────────────────────────────────

def test_launch_reports_success(bus):
    _reply(bus, "ovos.phal.app_launcher.launch", {"name": "Firefox", "success": True})
    out = applauncher.launch(bus, "Firefox")
    assert out == {"available": True, "name": "Firefox", "success": True, "error": None}


def test_launch_reports_error(bus):
    _reply(bus, "ovos.phal.app_launcher.launch",
           {"name": "Nope", "error": "No application matched 'Nope'"})
    out = applauncher.launch(bus, "Nope")
    assert out["success"] is False
    assert "No application matched" in out["error"]


def test_close_reports_success(bus):
    _reply(bus, "ovos.phal.app_launcher.close", {"name": "Firefox", "success": True})
    assert applauncher.close(bus, "Firefox")["success"] is True


def test_launch_unavailable_when_no_reply(bus):
    applauncher.LAUNCH_TIMEOUT = 0.3
    assert applauncher.launch(bus, "X")["available"] is False


def test_launch_rejects_a_bad_name(bus):
    for bad in ("", "   ", "has\nnewline", 5):
        with pytest.raises(applauncher.AppLauncherError):
            applauncher.launch(bus, bad)


# ── HTTP routes ──────────────────────────────────────────────────────────────

def test_apps_page_needs_auth(token_client):
    r = token_client.get("/apps", follow_redirects=False)
    assert r.status_code in (302, 303)


def test_apps_routes_need_a_token(token_client):
    assert token_client.get("/api/apps").status_code in (401, 403)
    assert token_client.post("/api/apps/launch", json={"name": "x"}).status_code in (401, 403)


def test_api_list_roundtrip(token_client, bus):
    _reply(bus, "ovos.phal.app_launcher.list", {"apps": [{"name": "Firefox", "exec": "firefox"}]})
    r = token_client.get("/api/apps", headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["apps"][0]["name"] == "Firefox"


def test_api_launch_roundtrip(token_client, bus):
    _reply(bus, "ovos.phal.app_launcher.launch", {"name": "Firefox", "success": True})
    r = token_client.post("/api/apps/launch", headers=_AUTH, json={"name": "Firefox"})
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_api_launch_rejects_blank(token_client, bus):
    r = token_client.post("/api/apps/launch", headers=_AUTH, json={"name": "   "})
    assert r.status_code == 400
