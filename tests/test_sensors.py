"""The sensor readings the device broadcasts (ovos-PHAL-sensors) are collected
and served as a snapshot. Nothing is sent; the app only listens to
``ovos.phal.sensor`` / ``ovos.phal.binary_sensor``."""
import pytest

from ovos_webui import sensors

_AUTH = {"Authorization": "Bearer s3cret-token"}


@pytest.fixture(autouse=True)
def _reset_singleton():
    sensors.LOG_SINGLETON._sensors = {}
    sensors.LOG_SINGLETON._bus = None
    yield


def _emit(bus, topic, data):
    from ovos_utils.fakebus import Message
    bus.emit(Message(topic, data))


# ── the store ────────────────────────────────────────────────────────────────

def test_snapshot_starts_empty():
    assert sensors.SensorLog().snapshot() == {"sensors": []}


def test_record_keeps_the_latest_reading():
    log = sensors.SensorLog()
    log.record("sensor", "pi_cpu", {"state": 40, "device_name": "pi", "name": "cpu",
                                    "attributes": {"unit_of_measurement": "%"}})
    log.record("sensor", "pi_cpu", {"state": 55, "device_name": "pi", "name": "cpu"})
    snap = log.snapshot()["sensors"]
    assert len(snap) == 1 and snap[0]["state"] == 55


def test_sorted_by_device_then_name():
    log = sensors.SensorLog()
    log.record("sensor", "b_z", {"device_name": "b", "name": "z"})
    log.record("sensor", "a_y", {"device_name": "a", "name": "y"})
    names = [s["name"] for s in log.snapshot()["sensors"]]
    assert names == ["y", "z"]


# ── the bus subscription ─────────────────────────────────────────────────────

def test_attach_captures_both_kinds(bus):
    log = sensors.SensorLog()
    log.attach(bus)
    _emit(bus, "ovos.phal.sensor", {"state": 21.5, "sensor_id": "pi_temp",
                                    "device_name": "pi", "name": "temp",
                                    "attributes": {"unit_of_measurement": "°C"}})
    _emit(bus, "ovos.phal.binary_sensor", {"state": True, "sensor_id": "pi_charging",
                                           "device_name": "pi", "name": "charging"})
    snap = {s["sensor_id"]: s for s in log.snapshot()["sensors"]}
    assert snap["pi_temp"]["state"] == 21.5 and snap["pi_temp"]["kind"] == "sensor"
    assert snap["pi_charging"]["kind"] == "binary" and snap["pi_charging"]["state"] is True


def test_attach_is_idempotent(bus):
    log = sensors.SensorLog()
    log.attach(bus); log.attach(bus)
    _emit(bus, "ovos.phal.sensor", {"state": 1, "sensor_id": "x"})
    # Only one handler, so exactly one record, not two.
    assert len(log.snapshot()["sensors"]) == 1


def test_reading_without_a_sensor_id_is_ignored(bus):
    log = sensors.SensorLog()
    log.attach(bus)
    _emit(bus, "ovos.phal.sensor", {"state": 5})
    assert log.snapshot()["sensors"] == []


# ── HTTP route ───────────────────────────────────────────────────────────────

def test_sensors_route_needs_a_token(token_client):
    assert token_client.get("/api/sensors").status_code in (401, 403)


def test_sensors_page_needs_auth(token_client):
    r = token_client.get("/sensors", follow_redirects=False)
    assert r.status_code in (302, 303)


def test_api_sensors_returns_collected_readings(token_client, bus):
    # The endpoint attaches the singleton to the app's bus, then a broadcast
    # is captured and shows up in the snapshot.
    token_client.get("/api/sensors", headers=_AUTH)  # attaches
    _emit(bus, "ovos.phal.sensor", {"state": 66, "sensor_id": "pi_cpu",
                                    "device_name": "pi", "name": "cpu"})
    got = token_client.get("/api/sensors", headers=_AUTH).json()
    ids = [s["sensor_id"] for s in got["sensors"]]
    assert "pi_cpu" in ids


def test_attach_resubscribes_on_a_new_bus_but_not_the_same_one():
    from ovos_utils.fakebus import FakeBus, Message
    log = sensors.SensorLog()
    bus1 = FakeBus()
    log.attach(bus1); log.attach(bus1)  # same bus twice: one handler only
    bus1.emit(Message("ovos.phal.sensor", {"state": 1, "sensor_id": "x"}))
    assert len(log.snapshot()["sensors"]) == 1  # not doubled
    # a reconnect gives a new bus object; the feed must not go stale
    bus2 = FakeBus()
    log.attach(bus2)
    bus2.emit(Message("ovos.phal.sensor", {"state": 2, "sensor_id": "y"}))
    ids = {s["sensor_id"] for s in log.snapshot()["sensors"]}
    assert "y" in ids
