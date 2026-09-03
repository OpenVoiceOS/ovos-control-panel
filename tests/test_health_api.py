"""Tests for the dashboard health route.

The bus interactions use ``FakeBus``. A fake service answers the same
``mycroft.<name>.is_alive`` and ``mycroft.<name>.is_ready`` messages that
``ovos_utils.process_utils.ProcessStatus`` registers, so nothing new is
invented here.
"""
import pytest

from ovos_webui import health


@pytest.fixture
def answering_bus(bus):
    """Attach real ProcessStatus handlers for two services."""
    from ovos_utils.process_utils import ProcessState, ProcessStatus

    ready = ProcessStatus("skills", bus)
    ready.state = ProcessState.READY
    starting = ProcessStatus("audio", bus)
    starting.state = ProcessState.ALIVE
    return bus


def test_snapshot_with_no_services(bus):
    snap = health.snapshot(bus, timeout=0.1)
    assert snap["bus"]["reachable"] is True
    assert {s["name"] for s in snap["services"]} == {s["name"] for s in health.SERVICES}
    assert all(s["state"] == "no answer" for s in snap["services"])
    assert snap["healthy"] is False


def test_snapshot_reads_process_status(answering_bus):
    snap = health.snapshot(answering_bus, timeout=1.0)
    by_name = {s["name"]: s for s in snap["services"]}
    assert by_name["skills"]["state"] == "ready"
    assert by_name["audio"]["state"] == "starting"
    assert by_name["PHAL"]["state"] == "no answer"


def test_media_has_its_own_card(bus):
    """ovos-media is a separate service from ovos-audio and probes its own
    ``mycroft.media.is_ready``, not ``mycroft.audio.is_ready``."""
    snap = health.snapshot(bus, timeout=0.1)
    names = {s["name"] for s in snap["services"]}
    assert "media" in names


def test_media_probes_its_own_message_type(bus):
    seen = []
    original = bus.emit

    def spy(message):
        seen.append(message.msg_type)
        return original(message)

    bus.emit = spy
    health.probe(bus, "media", timeout=0.05)
    assert "mycroft.media.is_ready" in seen or "mycroft.media.is_alive" in seen
    assert "mycroft.audio.is_ready" not in seen


def test_a_device_without_ovos_media_still_reads_healthy(bus):
    """ovos-media is optional: a device that only runs ovos-audio must not
    show unhealthy just because nothing answers the media probes."""
    from ovos_utils.process_utils import ProcessState, ProcessStatus

    ready = ProcessStatus("skills", bus)
    ready.state = ProcessState.READY
    ready = ProcessStatus("intents", bus)
    ready.state = ProcessState.READY
    ready = ProcessStatus("audio", bus)
    ready.state = ProcessState.READY

    snap = health.snapshot(bus, timeout=0.5)
    by_name = {s["name"]: s for s in snap["services"]}
    assert by_name["media"]["state"] == "no answer"
    assert snap["healthy"] is True


def test_snapshot_without_a_bus():
    snap = health.snapshot(None, timeout=0.1)
    assert snap["bus"]["reachable"] is False
    assert snap["healthy"] is False


def test_probe_survives_a_broken_bus():
    class Broken:
        def wait_for_response(self, *a, **kw):
            raise RuntimeError("bus is gone")

    assert health.probe(Broken(), "skills", timeout=0.1) == {"alive": None, "ready": None}


def test_health_route(client):
    body = client.get("/api/health").json()
    assert "services" in body and "bus" in body
    assert len(body["services"]) == len(health.SERVICES)


def test_health_route_without_a_bus(bus):
    from fastapi.testclient import TestClient

    from ovos_webui.service import create_app
    app = create_app(bus=None, host="127.0.0.1", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500") as c:
        assert c.get("/api/health").json()["bus"]["reachable"] is False


def test_only_known_message_types_are_used(bus):
    seen = []
    original = bus.emit

    def spy(message):
        seen.append(message.msg_type)
        return original(message)

    bus.emit = spy
    health.snapshot(bus, timeout=0.05)
    allowed = set()
    for spec in health.SERVICES:
        allowed.add(f"mycroft.{spec['name']}.is_alive")
        allowed.add(f"mycroft.{spec['name']}.is_ready")
    assert set(seen) <= allowed
