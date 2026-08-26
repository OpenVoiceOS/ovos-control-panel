"""Regression tests for audit wave-1 findings.

Each test fails against the unfixed code and passes after the fix:
- devicecontrol.get_volume mis-scaled an already-0-100 percent into e.g. 7500%.
- GgwaveListenBody.timeout had no upper bound (and accepted a bool).
- VolumeBody/MediaVolumeBody accepted a JSON bool as 1% (pydantic int coercion).
- network._act accepted a failure reply naming a *different* network.
"""
import threading
import time

import pytest
from pydantic import ValidationError


def _volume_bus(percent):
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus
    bus = FakeBus()
    bus.on("mycroft.volume.get",
           lambda m: bus.emit(Message("mycroft.volume.get.response",
                                      {"percent": percent, "muted": False},
                                      m.context)))
    return bus


def test_devicecontrol_get_volume_handles_an_already_scaled_percent():
    from ovos_webui import devicecontrol
    assert devicecontrol.get_volume(_volume_bus(75))["percent"] == 75    # already 0-100
    assert devicecontrol.get_volume(_volume_bus(0.4))["percent"] == 40   # fraction
    assert devicecontrol.get_volume(_volume_bus(250))["percent"] == 100  # clamped
    assert devicecontrol.get_volume(_volume_bus(True))["percent"] is None  # bool guarded


def test_ggwave_listen_takes_no_timeout():
    """There is nothing to bound: the plugin has no auto-off to ask for, so the
    body carries only the flag and an extra field is ignored rather than sent."""
    from ovos_webui.service import GgwaveListenBody
    assert GgwaveListenBody(enabled=True).enabled is True
    assert not hasattr(GgwaveListenBody(enabled=True), "timeout")


def test_volume_bodies_reject_a_bool_percent():
    from ovos_webui.service import MediaVolumeBody, VolumeBody
    for model in (VolumeBody, MediaVolumeBody):
        assert model(percent=50).percent == 50
        with pytest.raises(ValidationError):
            model(percent=True)


def test_network_ignores_a_failure_naming_a_different_network():
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus
    import ovos_webui.network as network

    bus = FakeBus()

    def on_forget(_m):
        def fire():
            time.sleep(0.15)  # an unrelated failure lands during our wait
            bus.emit(Message("ovos.phal.nm.forget.failure",
                             {"connection_name": "SOMEONE-ELSE"}, {}))
        threading.Thread(target=fire, daemon=True).start()

    bus.on("ovos.phal.nm.forget", on_forget)
    orig = network.QUERY_TIMEOUT
    network.QUERY_TIMEOUT = 1.0  # keep the timeout path fast
    try:
        res = network.forget(bus, "target-ssid")
    finally:
        network.QUERY_TIMEOUT = orig
    # The mismatched failure must NOT resolve us — we time out instead.
    assert res["ok"] is False
    assert "did not answer" in res["error"]


def test_network_still_accepts_a_keyless_failure():
    # The real plugin sends forget.failure with no payload; that must still
    # resolve the request (there is nothing to correlate on) — a control.
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus
    import ovos_webui.network as network

    bus = FakeBus()
    bus.on("ovos.phal.nm.forget",
           lambda m: bus.emit(Message("ovos.phal.nm.forget.failure", {}, {})))
    res = network.forget(bus, "target-ssid")
    assert res["ok"] is False
    assert "could not do that" in res["error"]
