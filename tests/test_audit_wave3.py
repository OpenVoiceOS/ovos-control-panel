"""Regression tests for audit wave-3 findings.

- /api/health "healthy" only counted skills+intents, so it reported healthy
  while audio was dead — contradicting the dashboard's own essential set.
- machine_translate had a line-count cap but no size cap, so a ~1MB line could
  be handed to a live (possibly paid) translation backend.
- the login throttle counter was process-global, so one source's failures paid
  down the delay another (the real owner) incurs on their own first mistake.
"""

import pytest


def test_health_counts_audio_as_essential(monkeypatch):
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


def test_login_throttle_decays_after_a_quiet_spell(monkeypatch):
    # The throttle is global (proxy- and IP-rotation-safe) but its count decays
    # after a quiet spell, so an honest typo once the guessing has stopped waits
    # barely at all. Shorten the decay window so the quiet spell is real but fast.
    import time as perf
    from starlette.testclient import TestClient
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import service
    from ovos_webui.service import create_app

    monkeypatch.setattr(service, "THROTTLE_DECAY", 0.15, raising=False)
    app = create_app(bus=FakeBus(), host="0.0.0.0", token="realtoken",
                     connect_bus=False, hostnames=("testserver",))
    hdrs = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
    c = TestClient(app)
    for _ in range(2):  # escalate the count
        c.post("/api/login", json={"token": "WRONG"}, headers=hdrs)
    perf.sleep(0.25)  # a quiet spell longer than THROTTLE_DECAY passes
    start = perf.perf_counter()
    c.post("/api/login", json={"token": "wrong-again"}, headers=hdrs)
    elapsed = perf.perf_counter() - start
    # After the decay the count is back to one, so this waits ~0.5s, not the
    # ~1.5s a never-resetting counter (the old per-source code) would inflict.
    assert elapsed < 1.0, f"decayed delay should be small, was {elapsed:.2f}s"
