"""Phase 5: device controls (volume, mic), capability detection, the abilities
list, and access-token rotation."""
import pytest

from ovos_webui import configio


AUTH = {"Authorization": "Bearer s3cret-token"}


_real_user_or_merged = configio.user_or_merged


def _targeting_on(keys):
    """Stub for configio.user_or_merged that enables service targeting
    (an operator-present ``webui.install_services`` block) while leaving
    every other config lookup (e.g. the release channel) to the real
    function, key-aware so it only intercepts the routing key."""
    if list(keys) == ["webui", "install_services"]:
        return {}  # present (empty) block -> targeting enabled, DEFAULT mapping
    return _real_user_or_merged(keys)


# ── volume / mic over the bus ────────────────────────────────────────────────
def _volume_bus(percent=0.4, muted=False):
    from ovos_utils.fakebus import FakeBus, Message

    bus = FakeBus()
    bus.on("mycroft.volume.get", lambda m: bus.emit(Message(
        "mycroft.volume.get.response", {"percent": percent, "muted": muted}, m.context)))
    return bus


def test_get_volume_reports_percent_and_mute():
    from ovos_webui import devicecontrol

    v = devicecontrol.get_volume(_volume_bus(0.4, True))
    assert v == {"percent": 40, "muted": True}


def test_get_volume_unknown_when_nothing_answers():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import devicecontrol

    assert devicecontrol.get_volume(FakeBus()) == {"percent": None, "muted": None}


def test_set_volume_validates_range():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import devicecontrol

    for bad in (-1, 101, 5.5, "50"):
        with pytest.raises(ValueError):
            devicecontrol.set_volume(FakeBus(), bad)
    assert devicecontrol.set_volume(FakeBus(), 30) == {"percent": 30}


def test_set_volume_emits_fraction():
    from ovos_utils.fakebus import FakeBus, Message
    from ovos_webui import devicecontrol

    bus = FakeBus()
    seen = []
    bus.on("mycroft.volume.set", lambda m: seen.append(m.data.get("percent")))
    devicecontrol.set_volume(bus, 50)
    assert seen == [0.5]


def test_mic_status_and_mute():
    from ovos_utils.fakebus import FakeBus, Message
    from ovos_webui import devicecontrol

    bus = FakeBus()
    bus.on("mycroft.mic.get_status", lambda m: bus.emit(Message(
        "mycroft.mic.get_status.response", {"muted": True}, m.context)))
    assert devicecontrol.get_mic(bus) == {"muted": True}
    seen = []
    bus.on("mycroft.mic.mute", lambda m: seen.append("mute"))
    devicecontrol.set_mic_mute(bus, True)
    assert seen == ["mute"]


def test_volume_routes_need_a_token(token_client):
    assert token_client.post("/api/device/volume", json={"percent": 20}).status_code == 401
    assert token_client.post("/api/device/mic/mute", json={"muted": True}).status_code == 401


def test_volume_set_is_privileged(client):
    # writing the volume runs a device command, so the tokenless-loopback path
    # is 403 (privileged), not open like a read.
    assert client.post("/api/device/volume", json={"percent": 20}).status_code == 403
    assert client.get("/api/device/volume").status_code == 200  # reads stay open


# ── capability detection ─────────────────────────────────────────────────────
def test_capability_status_shape():
    from ovos_webui import phal

    r = phal.capability_status()
    assert set(r["capabilities"]) == {"volume", "power", "network", "ggwave", "system"}
    for cap in r["capabilities"].values():
        assert set(cap) >= {"installed", "provider", "needs_admin", "suggest", "label", "hint"}
    assert r["capabilities"]["network"]["needs_admin"] is True
    assert isinstance(r["phal_plugins"], list)


def test_capability_detects_installed(monkeypatch):
    from ovos_webui import phal

    monkeypatch.setattr("ovos_webui.pypi.installed_versions",
                        lambda: {"ovos-phal-plugin-system": "1.0.0"})
    r = phal.capability_status()
    assert r["capabilities"]["power"]["installed"] is True
    assert r["capabilities"]["power"]["provider"] == "ovos-phal-plugin-system"
    assert r["capabilities"]["volume"]["installed"] is False


# ── abilities list ───────────────────────────────────────────────────────────
def test_abilities_list_shape(client, make_skill):
    make_skill("ovos-skill-weather.openvoiceos", {})
    r = client.get("/api/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert "skills" in body and body["count"] == len(body["skills"])
    for s in body["skills"]:
        assert set(s) >= {"id", "name", "description", "configurable"}


# ── access token: set and rotate ─────────────────────────────────────────────
def test_set_first_token_on_tokenless_device(client):
    # loopback + no token => api router is open; setting the first token works
    r = client.post("/api/auth/token", json={"new": "averylongtoken"})
    assert r.status_code == 200
    assert r.json()["had_token"] is False
    assert configio.read_user_config()["webui"]["access_token"] == "averylongtoken"


def test_token_min_length_enforced(client):
    assert client.post("/api/auth/token", json={"new": "short"}).status_code == 400


def test_rotate_requires_the_current_token(token_client):
    # token_client's app already has token s3cret-token
    r = token_client.post("/api/auth/token",
                          json={"new": "anotherlongtoken", "current": "wrong"},
                          headers=AUTH)
    assert r.status_code == 403
    r = token_client.post("/api/auth/token",
                          json={"new": "anotherlongtoken", "current": "s3cret-token"},
                          headers=AUTH)
    assert r.status_code == 200
    assert configio.read_user_config()["webui"]["access_token"] == "anotherlongtoken"


def test_rotate_route_needs_sign_in(token_client):
    # no Authorization header at all -> 401 on the signed-in router
    assert token_client.post("/api/auth/token", json={"new": "anotherlongtoken"}).status_code == 401


def test_token_change_reissues_cookie(token_client):
    r = token_client.post("/api/auth/token",
                          json={"new": "brandnewtoken1", "current": "s3cret-token"},
                          headers=AUTH)
    assert r.status_code == 200
    assert "ovos_webui_token" in r.headers.get("set-cookie", "")


def test_new_pages_render(client):
    for page in ("/controls", "/abilities"):
        assert client.get(page).status_code == 200


# ── installer delegates over the bus ─────────────────────────────────────────
def _wait_job(job, timeout=5.0):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end and job.state == "running":
        time.sleep(0.02)
    return job


def test_install_delegates_over_the_bus_when_connected(monkeypatch):
    from ovos_utils.fakebus import FakeBus, Message
    from ovos_webui import installer, pypi, updates

    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    monkeypatch.setattr(updates, "latest_versions", lambda name: {})  # offline: bare name
    monkeypatch.setattr(configio, "user_or_merged", _targeting_on)  # opt in to routing
    bus = FakeBus()
    seen = {}
    # a voice plugin is targeted at the audio service, and it replies on the
    # BASE complete topic (not a targeted one)
    bus.on("ovos.pip.install.ovos_audio", lambda m: (seen.update(pkgs=m.data["packages"]),
           bus.emit(m.reply("ovos.pip.install.complete"))))
    job = installer.Installer().install("ovos-tts-plugin-mimic3", bus=bus)
    _wait_job(job)
    assert seen["pkgs"] == ["ovos-tts-plugin-mimic3"]  # routed to the audio service
    assert job.state == "done"


def test_install_honors_the_release_channel(monkeypatch):
    import time
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import installer, pypi, updates

    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    monkeypatch.setattr(updates, "latest_versions",
                        lambda name: {"stable": "0.9.0", "alpha": "1.0.0a1"})
    monkeypatch.setattr(updates, "release_channel", lambda: "alpha")
    monkeypatch.setattr(configio, "user_or_merged", _targeting_on)  # opt in to routing
    bus = FakeBus()
    seen = {}
    bus.on("ovos.pip.install.ovos_audio",
           lambda m: seen.setdefault("pkgs", m.data.get("packages")))
    installer.Installer().install("ovos-tts-plugin-mimic3", bus=bus)
    for _ in range(200):
        if "pkgs" in seen:
            break
        time.sleep(0.01)
    # an alpha-channel install pins the pre-release, not the bare name
    assert seen["pkgs"] == ["ovos-tts-plugin-mimic3==1.0.0a1"]


def test_bus_install_reports_the_service_failure(monkeypatch):
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import installer, pypi

    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    monkeypatch.setattr(configio, "user_or_merged", _targeting_on)  # opt in to routing
    bus = FakeBus()
    bus.on("ovos.pip.install.ovos_audio", lambda m: bus.emit(m.reply(
        "ovos.pip.install.failed", {"error": "pip is disabled"})))
    job = installer.Installer().install("ovos-tts-plugin-mimic3", bus=bus)
    _wait_job(job)
    assert job.state == "error"
    assert any("pip is disabled" in line for line in job.lines)


def test_routing_maps_kind_to_service(monkeypatch):
    from ovos_webui import installer
    monkeypatch.setattr(configio, "user_or_merged", _targeting_on)  # opt in to routing
    # voice -> audio, listener plugins -> listener, skill -> core, phal -> PHAL
    assert installer._install_service_for("ovos-tts-plugin-piper") == "ovos_audio"
    assert installer._install_service_for("ovos-stt-plugin-vosk") == "ovos_dinkum_listener"
    assert installer._install_service_for("ovos-vad-plugin-silero") == "ovos_dinkum_listener"
    assert installer._install_service_for("ovos-skill-news") == "ovos_core"
    assert installer._install_service_for("ovos-PHAL-plugin-alsa") == "ovos_PHAL"


def test_admin_phal_plugin_routes_to_the_admin_process(monkeypatch):
    from ovos_webui import installer
    monkeypatch.setattr(configio, "user_or_merged", _targeting_on)  # opt in to routing
    # network-manager needs root -> the separate admin PHAL process, not the plain
    # one (wifi-setup, which this used to name, is archived)
    assert installer._install_service_for("ovos-PHAL-plugin-network-manager") == "ovos_PHAL_admin"
    assert installer._install_service_for("ovos-phal-plugin-network-manager") == "ovos_PHAL_admin"
    # a non-admin PHAL plugin stays on the plain PHAL process
    assert installer._install_service_for("ovos-PHAL-plugin-alsa") == "ovos_PHAL"


def test_routing_override_and_broadcast(monkeypatch):
    from ovos_webui import configio, installer
    data = configio.read_user_config()
    configio.set_in(data, ["webui", "install_services"], {"tts": "broadcast"})
    configio.write_user_config(data)
    # an operator can send a family back to the broadcast topic
    assert installer._install_service_for("ovos-tts-plugin-piper") is None
    configio.set_in(data, ["webui", "install_services"], {"tts": "my-audio"})
    configio.write_user_config(data)
    assert installer._install_service_for("ovos-tts-plugin-piper") == "my-audio"


def test_install_without_a_device_is_refused():
    from ovos_webui import installer, pypi
    import pytest as _pytest

    # No bus at all => nothing to delegate to => clear error, never local pip.
    with _pytest.raises(installer.InstallerUnavailable):
        installer.Installer().install("ovos-tts-plugin-mimic3", bus=None,
                                      check_pypi=False)


# ── installer resilience (adversarial review: OCE-001 / OCE-002 / SEC-1) ──────
def test_a_trailing_newline_in_a_name_is_refused():
    # SEC-1: Python's ``$`` matches before a trailing newline and re.match does
    # not anchor the end, so a name with a trailing \n must be refused by
    # fullmatch, not silently accepted into the bus message and the device log.
    from ovos_webui import installer, pypi

    with pytest.raises(installer.UnsafePackageName):
        installer.validate_package_name("ovos-tts-plugin-mimic3\n")
    # classify must not resolve a family for the newline-bearing name either
    assert pypi.classify("ovos-skill-news\n") is None
    assert pypi.classify("ovos-skill-news") == "skill"


def test_a_failed_emit_never_wedges_the_installer(monkeypatch):
    # OCE-001/003: if the emit raises after the single-flight lock is taken, the
    # job must end "error" (not "running") so the NEXT install is not blocked
    # forever with InstallerBusy.
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import installer, pypi

    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    monkeypatch.setattr(configio, "user_or_merged", _targeting_on)  # opt in to routing
    bus = FakeBus()

    def boom(*_a, **_k):
        raise RuntimeError("bus dropped mid-emit")

    bus.emit = boom
    inst = installer.Installer()
    job = _wait_job(inst.install("ovos-tts-plugin-mimic3", bus=bus))
    assert job.state == "error"
    assert job.state != "running"

    # the lock is released, so a fresh install on a healthy bus can run
    bus2 = FakeBus()
    from ovos_utils.fakebus import Message  # noqa: F401
    bus2.on("ovos.pip.install.ovos_audio",
            lambda m: bus2.emit(m.reply("ovos.pip.install.complete")))
    job2 = _wait_job(inst.install("ovos-tts-plugin-piper", bus=bus2))
    assert job2.state == "done"


def test_a_reply_for_another_job_is_ignored(monkeypatch):
    # OCE-002: replies land on the shared base topic. A reply that does not carry
    # THIS job's nonce (e.g. a late answer to a previous job) must not complete
    # or fail the running job.
    from ovos_utils.fakebus import FakeBus, Message
    from ovos_webui import installer, pypi
    import time

    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    bus = FakeBus()  # no auto-responder: the job stays running until WE reply
    job = installer.Installer().install("ovos-tts-plugin-mimic3", bus=bus)

    # a foreign complete with the wrong nonce must be ignored
    bus.emit(Message("ovos.pip.install.complete", {}, {"webui_job": "not-this-job"}))
    time.sleep(0.1)
    assert job.state == "running"

    # the correctly-tagged reply (nonce == job.id) completes it
    bus.emit(Message("ovos.pip.install.complete", {}, {"webui_job": job.id}))
    _wait_job(job)
    assert job.state == "done"


def test_a_non_string_routing_override_is_ignored(monkeypatch):
    # OCE-004: an operator typo like {"tts": 123} must not build a dead topic;
    # the bad value is dropped and the default route is used.
    from ovos_webui import configio, installer

    data = configio.read_user_config()
    configio.set_in(data, ["webui", "install_services"], {"tts": 123})
    configio.write_user_config(data)
    assert installer._install_service_for("ovos-tts-plugin-piper") == "ovos_audio"


def test_install_route_503_without_a_device(monkeypatch):
    from fastapi.testclient import TestClient
    from ovos_webui import pypi
    from ovos_webui.service import create_app

    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    # a token app whose bus is None (no device connected)
    app = create_app(bus=None, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        r = c.post("/api/plugins/install", json={"package": "ovos-tts-plugin-mimic3"},
                   headers={"Authorization": "Bearer s3cret-token"})
        assert r.status_code == 503
