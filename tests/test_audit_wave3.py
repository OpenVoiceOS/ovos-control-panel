"""Regression tests for audit wave-3 findings.

- /api/health "healthy" only counted skills+intents, so it reported healthy
  while audio was dead — contradicting the dashboard's own essential set.
- machine_translate had a line-count cap but no size cap, so a ~1MB line could
  be handed to a live (possibly paid) translation backend.
- the login throttle counter was process-global, so one source's failures paid
  down the delay another (the real owner) incurs on their own first mistake.
"""
import time

import pytest


def test_health_counts_audio_as_essential(monkeypatch):
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import health

    monkeypatch.setattr(health, "bus_reachable", lambda bus: True)
    bus = FakeBus()
    # skills + intents answer "ready"; audio deliberately does not.
    for name in ("skills", "intents"):
        for key in ("alive", "ready"):
            topic = f"mycroft.{name}.is_{key}"
            bus.on(topic, lambda m: bus.emit(m.response({"status": True})))
    snap = health.snapshot(bus, timeout=0.3)
    audio = next(s for s in snap["services"] if s["name"] == "audio")
    assert audio["state"] != "ready"           # audio is down
    assert snap["healthy"] is False            # so the device is not healthy


def test_machine_translate_caps_the_total_size():
    from ovos_webui import translate
    big = "x" * (translate.MAX_RESOURCE_BYTES + 1)
    with pytest.raises(translate.TranslateError) as exc:
        translate.machine_translate([big], "en", "pt-pt")
    assert "too much text" in str(exc.value)


def test_login_throttle_is_per_source():
    from starlette.testclient import TestClient
    from ovos_utils.fakebus import FakeBus
    from ovos_webui.service import create_app

    app = create_app(bus=FakeBus(), host="0.0.0.0", token="realtoken",
                     connect_bus=False, hostnames=("testserver",))
    hdrs = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
    attacker = TestClient(app, client=("10.0.0.9", 5000))
    owner = TestClient(app, client=("10.0.0.5", 5000))
    # The attacker burns three wrong tokens from its own source (a global
    # counter would then make any next failure wait ~2s).
    for _ in range(3):
        attacker.post("/api/login", json={"token": "WRONG"}, headers=hdrs)
    # The owner's very first mistyped token must pay only its own small delay
    # (~0.5s), not the attacker's accumulated one.
    start = time.monotonic()
    owner.post("/api/login", json={"token": "also-wrong-once"}, headers=hdrs)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"owner paid {elapsed:.2f}s for its first mistake"
