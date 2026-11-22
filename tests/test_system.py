"""Connectivity and IP-geolocation, and the location route on the Voice and
language page. SSH and the factory reset are a page the panel brings for
ovos-PHAL-plugin-system (tests/test_described.py).

Bus messages exercised here, verified against ovos-PHAL-plugin-connectivity-events
and ovos-PHAL-plugin-ipgeo:

* ``ovos.PHAL.internet_check`` -> ``mycroft.internet.state`` /
  ``mycroft.network.state`` (each {"state": "connected"|"disconnected"})
* ``ovos.ipgeo.update`` -> ``ovos.ipgeo.update.response``
  ({"location": {...}} or {"error": True})
"""


def _connectivity_bus(*, internet="connected", network="connected", answer=True):
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus

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
    assert r["ok"] is True
    assert r["location"] == {"city": "Lisbon"}
    assert seen == ["ovos.ipgeo.update"]
    # Nothing above the assistant layer sets a location here, so the detected one
    # stands and the caller is not warned about an override that is not there.
    assert "overridden" not in r


def test_detect_location_reports_plugin_error():
    from ovos_webui import system
    r = system.detect_location(_ipgeo_bus(error=True))
    assert r["ok"] is False and r["error"]


def test_detect_location_timeout_is_an_error_dict(monkeypatch):
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import system

    monkeypatch.setattr(system, "GEOLOCATE_TIMEOUT", 0.3)
    r = system.detect_location(FakeBus())
    assert r["ok"] is False and r["error"]


# ── routes ────────────────────────────────────────────────────────────────────
def test_the_language_route_is_gone(client):
    # the language is set on the Voice and language page, through the config
    paths = {getattr(r, "path", "") for r in client.app.routes}
    assert "/api/system/language" not in paths




def test_the_location_is_detected_from_the_voice_page(token_client, monkeypatch):
    from ovos_webui import system
    monkeypatch.setattr(system, "detect_location", lambda bus: {"ok": True, "location": {"city": "Kvistgård"}})
    assert token_client.post("/api/location/detect").status_code == 401
    got = token_client.post("/api/location/detect", headers={"Authorization": "Bearer s3cret-token"})
    assert got.status_code in (200, 503)
    paths = {getattr(r, "path", "") for r in token_client.app.routes}
    assert "/api/system/detect-location" not in paths and "/api/system/ssh" not in paths
