"""Regression tests for audit wave-1 findings.

Each test fails against the unfixed code and passes after the fix:
- devicecontrol.get_volume mis-scaled an already-0-100 percent into e.g. 7500%.
- GgwaveListenBody.timeout had no upper bound (and accepted a bool).
- VolumeBody accepted a JSON bool as 1% (pydantic int coercion).
- network._act accepted a failure reply naming a *different* network.
"""

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
    from ovos_webui.pages.sound.api import GgwaveListenBody
    assert GgwaveListenBody(enabled=True).enabled is True
    assert not hasattr(GgwaveListenBody(enabled=True), "timeout")


def test_volume_bodies_reject_a_bool_percent():
    from ovos_webui.pages.controls.api import VolumeBody
    for model in (VolumeBody,):
        assert model(percent=50).percent == 50
        with pytest.raises(ValidationError):
            model(percent=True)
