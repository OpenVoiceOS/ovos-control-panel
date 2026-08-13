"""System panel: SSH status/enable/disable, factory reset, device language,
connectivity, IP-geolocation, and the privileged routes.

Bus messages exercised here, verified against ovos-PHAL-plugin-system,
ovos-PHAL-plugin-connectivity-events and ovos-PHAL-plugin-ipgeo:

* ``system.ssh.status`` -> ``system.ssh.status.response`` ({"enabled": bool})
* ``system.ssh.enable`` / ``system.ssh.disable`` (fire-and-forget)
* ``system.factory.reset`` (fire-and-forget, destructive)
* ``system.configure.language`` ({"language_code": ...}) ->
  ``system.configure.language.complete`` ({"lang": ...})
* ``ovos.PHAL.internet_check`` -> ``mycroft.internet.state`` /
  ``mycroft.network.state`` (each {"state": "connected"|"disconnected"})
* ``ovos.ipgeo.update`` -> ``ovos.ipgeo.update.response``
  ({"location": {...}} or {"error": True})
"""
import pytest


# ── a FakeBus that answers the system-plugin topics ─────────────────────────
def _system_bus(*, ssh_enabled=None, ssh_answers=True, lang_ok=True):
    """``ssh_enabled=None`` means the status handler never answers (a timeout,
    the capability gate)."""
    from ovos_utils.fakebus import FakeBus, Message

    bus = FakeBus()

    if ssh_answers:
        def on_status(m):
            bus.emit(m.response(data={"enabled": bool(ssh_enabled)}))
        bus.on("system.ssh.status", on_status)

    bus.on("system.ssh.enable", lambda m: bus.emit(
        m.forward("system.ssh.enabled", m.data)))
    bus.on("system.ssh.disable", lambda m: bus.emit(
        m.forward("system.ssh.disabled", m.data)))

    def on_lang(m):
        if not lang_ok:
            return
        lang = m.data.get("language_code", "en_US").lower().replace("_", "-")
        bus.emit(Message("system.configure.language.complete", {"lang": lang}, m.context))
    bus.on("system.configure.language", on_lang)

    return bus


def _connectivity_bus(*, internet="connected", network="connected", answer=True):
    from ovos_utils.fakebus import FakeBus, Message

    bus = FakeBus()
    if answer:
        def on_check(m):
            bus.emit(Message("mycroft.internet.state", {"state": internet}, m.context))
            bus.emit(Message("mycroft.network.state", {"state": network}, m.context))
        bus.on("ovos.PHAL.internet_check", on_check)
    return bus


def _ipgeo_bus(*, location=None, error=False, answer=True):
    from ovos_utils.fakebus import FakeBus

    bus = FakeBus()
    if answer:
        def on_update(m):
            if error:
                bus.emit(m.response(data={"error": True}))
            else:
                bus.emit(m.response(data={"location": location or {"city": "Porto"}}))
        bus.on("ovos.ipgeo.update", on_update)
    return bus


# ── SSH status ────────────────────────────────────────────────────────────────
def test_ssh_status_parses_the_reply():
    from ovos_webui import system
    assert system.ssh_status(_system_bus(ssh_enabled=True)) == {
        "available": True, "enabled": True}
    assert system.ssh_status(_system_bus(ssh_enabled=False)) == {
        "available": True, "enabled": False}


def test_ssh_status_unavailable_when_nothing_answers():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import system

    system.DEFAULT_TIMEOUT = 0.3
    assert system.ssh_status(FakeBus()) == {"available": False, "enabled": None}
    system.DEFAULT_TIMEOUT = 5.0


# ── SSH enable/disable ───────────────────────────────────────────────────────
def test_ssh_enable_emits_the_enable_message():
    from ovos_webui import system

    bus = _system_bus()
    seen = []
    bus.on("system.ssh.enable", lambda m: seen.append(m.msg_type))
    r = system.ssh_enable(bus)
    assert r["sent"] is True
    assert seen == ["system.ssh.enable"]


def test_ssh_disable_emits_the_disable_message():
    from ovos_webui import system

    bus = _system_bus()
    seen = []
    bus.on("system.ssh.disable", lambda m: seen.append(m.msg_type))
    r = system.ssh_disable(bus)
    assert r["sent"] is True
    assert seen == ["system.ssh.disable"]


# ── factory reset ────────────────────────────────────────────────────────────
def test_factory_reset_emits_the_reset_message():
    from ovos_webui import system

    bus = _system_bus()
    seen = []
    bus.on("system.factory.reset", lambda m: seen.append(m.msg_type))
    r = system.factory_reset(bus)
    assert r["sent"] is True
    assert seen == ["system.factory.reset"]


# ── device language ──────────────────────────────────────────────────────────
def test_set_language_emits_the_configure_message_and_parses_the_completion():
    from ovos_webui import system

    bus = _system_bus()
    seen = []
    bus.on("system.configure.language", lambda m: seen.append(m.data))
    r = system.set_language(bus, "pt-PT")
    assert r == {"ok": True, "lang": "pt-pt"}
    assert seen == [{"language_code": "pt-PT"}]


@pytest.mark.parametrize("junk", ["", "  ", "not a lang code!", "1234",
                                  "toolongxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                                  None, 42, "en\n"])
def test_set_language_rejects_junk(junk):
    from ovos_webui import system

    bus = _system_bus()
    seen = []
    bus.on("system.configure.language", lambda m: seen.append(m.data))
    r = system.set_language(bus, junk)
    assert r["ok"] is False
    assert seen == []  # never touched the bus


@pytest.mark.parametrize("lang", ["en", "en-US", "en_US", "pt-PT", "zh-Hans-CN", "yue"])
def test_valid_lang_accepts_plausible_codes(lang):
    from ovos_webui import system
    assert system.valid_lang(lang) is True


def test_set_language_timeout_is_an_error_dict():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import system

    system.DEFAULT_TIMEOUT = 0.3
    r = system.set_language(FakeBus(), "en-US")
    assert r["ok"] is False and r["error"]
    system.DEFAULT_TIMEOUT = 5.0


# ── connectivity ──────────────────────────────────────────────────────────────
def test_connectivity_parses_both_states():
    from ovos_webui import system
    r = system.connectivity(_connectivity_bus(internet="connected", network="connected"))
    assert r == {"internet": "connected", "network": "connected"}

    r = system.connectivity(_connectivity_bus(internet="disconnected", network="disconnected"))
    assert r == {"internet": "disconnected", "network": "disconnected"}


def test_connectivity_timeout_reports_unknown():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import system

    system.DEFAULT_TIMEOUT = 0.3
    assert system.connectivity(FakeBus()) == {"internet": None, "network": None}
    system.DEFAULT_TIMEOUT = 5.0


# ── detect location ──────────────────────────────────────────────────────────
def test_detect_location_emits_ipgeo_update_and_parses_location():
    from ovos_webui import system

    bus = _ipgeo_bus(location={"city": "Lisbon"})
    seen = []
    bus.on("ovos.ipgeo.update", lambda m: seen.append(m.msg_type))
    r = system.detect_location(bus)
    assert r == {"ok": True, "location": {"city": "Lisbon"}}
    assert seen == ["ovos.ipgeo.update"]


def test_detect_location_reports_plugin_error():
    from ovos_webui import system
    r = system.detect_location(_ipgeo_bus(error=True))
    assert r["ok"] is False and r["error"]


def test_detect_location_timeout_is_an_error_dict():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import system

    system.DEFAULT_TIMEOUT = 0.3
    r = system.detect_location(FakeBus())
    assert r["ok"] is False and r["error"]
    system.DEFAULT_TIMEOUT = 5.0


# ── routes ────────────────────────────────────────────────────────────────────
def test_system_routes_need_a_token(token_client):
    assert token_client.get("/api/system/ssh").status_code == 401
    assert token_client.post("/api/system/ssh", json={"enabled": True}).status_code == 401
    assert token_client.post("/api/system/factory-reset").status_code == 401
    assert token_client.post("/api/system/language", json={"lang": "en-US"}).status_code == 401
    assert token_client.get("/api/system/connectivity").status_code == 401
    assert token_client.post("/api/system/detect-location").status_code == 401


def test_system_routes_503_without_a_device():
    from fastapi.testclient import TestClient
    from ovos_webui.service import create_app

    app = create_app(bus=None, host="0.0.0.0", token="s3cret-token",
                     connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        auth = {"Authorization": "Bearer s3cret-token"}
        assert c.get("/api/system/ssh", headers=auth).status_code == 503
        assert c.post("/api/system/ssh", json={"enabled": True}, headers=auth).status_code == 503
        assert c.post("/api/system/factory-reset", headers=auth).status_code == 503
        assert c.post("/api/system/language", json={"lang": "en-US"}, headers=auth).status_code == 503
        assert c.get("/api/system/connectivity", headers=auth).status_code == 503
        assert c.post("/api/system/detect-location", headers=auth).status_code == 503


def test_ssh_status_route_reads_the_bus(bus):
    from fastapi.testclient import TestClient
    from ovos_webui.service import create_app

    def on_status(m):
        bus.emit(m.response(data={"enabled": True}))
    bus.on("system.ssh.status", on_status)

    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        r = c.get("/api/system/ssh", headers={"Authorization": "Bearer s3cret-token"})
        assert r.status_code == 200
        assert r.json() == {"available": True, "enabled": True}


def test_ssh_set_route_enables_and_disables(bus):
    from fastapi.testclient import TestClient
    from ovos_webui.service import create_app

    bus.on("system.ssh.enable", lambda m: bus.emit(m.forward("system.ssh.enabled", m.data)))
    bus.on("system.ssh.disable", lambda m: bus.emit(m.forward("system.ssh.disabled", m.data)))

    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        auth = {"Authorization": "Bearer s3cret-token"}
        r = c.post("/api/system/ssh", json={"enabled": True}, headers=auth)
        assert r.status_code == 200 and r.json()["sent"] is True
        r = c.post("/api/system/ssh", json={"enabled": False}, headers=auth)
        assert r.status_code == 200 and r.json()["sent"] is True


def test_language_route_rejects_junk_with_400_or_error_payload(bus):
    from fastapi.testclient import TestClient
    from ovos_webui.service import create_app

    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        r = c.post("/api/system/language", json={"lang": "not a lang!"},
                   headers={"Authorization": "Bearer s3cret-token"})
        assert r.status_code == 200
        assert r.json()["ok"] is False


def test_system_page_renders(client):
    assert client.get("/system").status_code == 200
