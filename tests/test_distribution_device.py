"""What a distribution says about its device: services it leaves out on
purpose (webui.absent_services), and who may show the panel in a frame of
their own (webui.frame_ancestors)."""
import json

import pytest
from fastapi.testclient import TestClient

from ovos_webui import configio, framing, health
from ovos_webui.service import create_app


def set_webui(**webui):
    configio.user_config_path().write_text(json.dumps({"webui": webui}), encoding="utf-8")
    framing._cache["value"] = None   # noqa: SLF001 - read it again now


@pytest.fixture
def client(bus):
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False,
                     hostnames=("house.local",))
    with TestClient(app, base_url="http://house.local:8500",
                    headers={"sec-fetch-site": "same-origin", "Authorization": "Bearer s3cret-token"}) as c:
        yield c
    framing._cache["value"] = None   # noqa: SLF001


def answer_all(bus, but=()):
    for spec in health.SERVICES:
        if spec["name"] in but:
            continue
        for what in ("is_alive", "is_ready"):
            bus.on(f"mycroft.{spec['name']}.{what}",
                   lambda m: bus.emit(m.response({"status": True})))


# ── absent_services ─────────────────────────────────────────────────────────
def test_without_the_setting_every_service_counts(client, bus):
    answer_all(bus, but=("audio",))
    h = client.get("/api/health").json()
    assert "audio" in [s["name"] for s in h["services"]] and h["healthy"] is False
    assert h["absent"] == []


def test_a_service_left_out_on_purpose_is_not_asked_listed_or_counted(client, bus):
    asked = []
    bus.on("mycroft.audio.is_alive", lambda m: asked.append(m))
    answer_all(bus, but=("audio",))
    set_webui(absent_services=["audio"])
    h = client.get("/api/health").json()
    assert "audio" not in [s["name"] for s in h["services"]]
    assert h["healthy"] is True, "a house with no ears or voice of its own is healthy"
    assert h["absent"] == [{"name": "audio", "label": "Audio"}]
    assert not asked


def test_a_service_meant_to_run_still_shows_when_it_stops(client, bus):
    answer_all(bus, but=("audio", "skills"))
    set_webui(absent_services=["audio"])
    h = client.get("/api/health").json()
    assert h["healthy"] is False
    assert [s["state"] for s in h["services"] if s["name"] == "skills"] == ["no answer"]


@pytest.mark.parametrize("bad, problem", [
    (["audio", "toaster"], "no service called 'toaster'"),
    ("audio", "a list of service names"),
])
def test_a_name_that_is_not_a_service_is_named_on_the_about_page(client, bus, bad, problem):
    set_webui(absent_services=bad)
    assert any(problem in p for p in client.get("/api/pages").json()["settings"])


def test_the_dashboard_says_what_is_left_out():
    from pathlib import Path
    import ovos_webui
    html = (Path(ovos_webui.__file__).parent / "pages" / "dashboard" / "page.html").read_text()
    assert 'id="absent"' in html and "dash.absent" in html
    for f in (Path(ovos_webui.__file__).parent / "pages" / "dashboard" / "i18n").glob("*.json"):
        assert "{names}" in json.loads(f.read_text())["dash.absent"], f.name


# ── frame_ancestors ─────────────────────────────────────────────────────────
def test_without_the_setting_nobody_may_frame_the_panel(client):
    r = client.get("/login")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_self_lets_the_panels_own_host_frame_it_on_any_port(client):
    set_webui(frame_ancestors=["self"])
    r = client.get("/login")
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'self' https://house.local:* http://house.local:*" in csp
    assert "x-frame-options" not in r.headers


def test_an_origin_may_be_named(client):
    set_webui(frame_ancestors=["https://emkay.example:8443"])
    csp = client.get("/login").headers["content-security-policy"]
    assert "frame-ancestors https://emkay.example:8443" in csp


@pytest.mark.parametrize("bad", ["*", "https://*.example", "javascript:alert(1)", "https://a b", 7,
                                 "https://x.example; script-src *"])
def test_anything_else_is_skipped_and_named(client, bad):
    set_webui(frame_ancestors=[bad])
    r = client.get("/login")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert any("webui.frame_ancestors" in p for p in client.get("/api/pages").json()["settings"])


def test_a_host_header_that_is_not_a_name_adds_nothing():
    assert framing.policy(["self"], "evil.example; script-src *") == "frame-ancestors 'self'"
    assert framing.policy(["self"], "[::1]:8500") == "frame-ancestors 'self' https://[::1]:* http://[::1]:*"
    assert framing.policy([], "house.local") == "frame-ancestors 'none'"
