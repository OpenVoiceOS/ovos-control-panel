"""Tests for the plugin installer.

The installer is the only part of ovos-webui that starts a process, so the
injection vectors are tested here first and hardest.
"""
import time

import pytest

from ovos_webui import installer, pypi

# Every one of these must be refused before pip is reached. They cover shell
# metacharacters, version pins, extras, index redirection, paths and VCS URLs.
INJECTION = [
    "ovos-x; rm -rf /",
    "ovos-x && rm -rf /",
    "ovos-x | tee /etc/passwd",
    "ovos-x`id`",
    "ovos-x$(id)",
    "ovos-x\nrm -rf /",
    "ovos-tts-plugin-mimic3==1.0 --index-url http://evil.example",
    "ovos-tts-plugin-mimic3==1.0",
    "ovos-tts-plugin-mimic3>=1.0",
    "ovos-tts-plugin-mimic3[extra]",
    "ovos-tts-plugin-mimic3 --target /etc",
    "--index-url=http://evil.example",
    "-e /tmp/evil",
    "/tmp/evil",
    "./evil",
    "../ovos-evil",
    "git+https://evil.example/x.git",
    "https://evil.example/x.tar.gz",
    "file:///tmp/evil",
    "ovos-x@https://evil.example/x.whl",
    "requests",
    "pip",
    "ovos_tts_plugin_mimic3",  # underscores are not the PyPI name form
    "OVOS-TTS-PLUGIN-évil",
    "ovos-tts-plugin-mimic3 ",
    " ovos-tts-plugin-mimic3",
    "ovos-",
    "ovos-x\x00",
    "ovos-tts-plugin-mimic3\n",     # trailing newline: $ + re.match would accept it
    "ovos-skill-news\n",
    "ovos-skill-news\r",
    "ovos-skill-news\t",
    "",
    "x" * 200,
]


@pytest.mark.parametrize("bad", INJECTION)
def test_validate_package_name_refuses(bad):
    with pytest.raises((installer.UnsafePackageName, ValueError)):
        installer.validate_package_name(bad)


@pytest.mark.parametrize("good", [
    "ovos-tts-plugin-mimic3",
    "ovos-stt-plugin-vosk",
    "ovos-ww-plugin-precise-onnx",
    "ovos-vad-plugin-silero",
    "ovos-PHAL-plugin-alsa",
    "ovos-solver-wikipedia-plugin",
    "ovos-skill-news",
])
def test_validate_package_name_accepts(good):
    assert installer.validate_package_name(good) == good


def test_a_valid_name_that_is_not_an_ovos_family_is_refused():
    # Matches the character pattern but is not a plugin family.
    with pytest.raises(installer.UnsafePackageName):
        installer.validate_package_name("ovos-core")


@pytest.mark.parametrize("bad", INJECTION[:12])
def test_install_route_refuses_injection(token_client, bad):
    r = token_client.post("/api/plugins/install", json={"package": bad},
                          headers={"Authorization": "Bearer s3cret-token"})
    assert r.status_code in (400, 422), f"{bad!r} returned {r.status_code}"


@pytest.mark.parametrize("bad", INJECTION[:12])
def test_uninstall_route_refuses_injection(token_client, bad):
    r = token_client.post("/api/plugins/uninstall", json={"package": bad},
                          headers={"Authorization": "Bearer s3cret-token"})
    assert r.status_code in (400, 422)


def test_install_needs_a_token_even_on_localhost(client):
    """The rest of the page is open on loopback. Installing never is."""
    r = client.post("/api/plugins/install", json={"package": "ovos-tts-plugin-mimic3"})
    assert r.status_code == 403
    assert "token" in r.json()["detail"]


def test_uninstall_needs_a_token_even_on_localhost(client):
    r = client.post("/api/plugins/uninstall", json={"package": "ovos-tts-plugin-mimic3"})
    assert r.status_code == 403


def test_jobs_need_a_token_even_on_localhost(client):
    assert client.get("/api/plugins/jobs").status_code == 403


def test_install_with_a_wrong_token_is_refused(token_client):
    r = token_client.post("/api/plugins/install", json={"package": "ovos-tts-plugin-mimic3"},
                          headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_uninstall_delegates_to_the_device(token_client):
    # Whether the package is present is decided by the service that owns the
    # environment, so a valid name is delegated (job started), not pre-judged.
    r = token_client.post("/api/plugins/uninstall",
                          json={"package": "ovos-tts-plugin-doesnotexist"},
                          headers={"Authorization": "Bearer s3cret-token"})
    assert r.status_code == 200
    assert r.json()["action"] == "uninstall"


def test_install_emits_a_plain_packages_list(monkeypatch):
    """No shell, no subprocess — the name travels as one bus-message field."""
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import configio, updates
    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    monkeypatch.setattr(updates, "latest_versions", lambda name: {})  # offline: bare name
    # No operator override -> broadcast (the default the running core answers).
    monkeypatch.setattr(configio, "user_or_merged", lambda *a, **k: None)
    bus = FakeBus()
    seen = {}
    bus.on("ovos.pip.install", lambda m: seen.setdefault("packages", m.data.get("packages")))
    installer.Installer().install("ovos-tts-plugin-mimic3", bus=bus)
    for _ in range(100):
        if "packages" in seen:
            break
        time.sleep(0.01)
    assert seen["packages"] == ["ovos-tts-plugin-mimic3"]


def test_install_delegates_to_the_device(monkeypatch):
    """A plugin must land where OVOS imports from — so the device installs it."""
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import configio
    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    monkeypatch.setattr(configio, "user_or_merged", lambda *a, **k: None)
    bus = FakeBus()
    seen = {}
    bus.on("ovos.pip.install", lambda m: (seen.update(got=True),
           bus.emit(m.reply("ovos.pip.install.complete"))))
    job = installer.Installer().install("ovos-tts-plugin-mimic3", bus=bus)
    for _ in range(200):
        if job.state != "running":
            break
        time.sleep(0.01)
    assert seen.get("got") and job.state == "done"


def test_install_checks_pypi_before_delegating(monkeypatch):
    """A name that PyPI does not know must never be sent to the device."""
    from ovos_utils.fakebus import FakeBus
    bus = FakeBus()
    emitted = []
    bus.on("ovos.pip.install.ovos_audio", lambda m: emitted.append(m))
    bus.on("ovos.pip.install", lambda m: emitted.append(m))

    def missing(name):
        raise LookupError("no such package")
    monkeypatch.setattr(pypi, "details", missing)
    with pytest.raises(LookupError):
        installer.Installer().install("ovos-tts-plugin-nope", bus=bus)
    assert emitted == []


def test_only_one_job_runs_at_a_time(monkeypatch):
    from ovos_utils.fakebus import FakeBus
    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    bus = FakeBus()  # no responder, so the first job stays running
    inst = installer.Installer()
    inst.install("ovos-tts-plugin-a", bus=bus)
    with pytest.raises(installer.InstallerBusy):
        inst.install("ovos-tts-plugin-b", bus=bus)


def test_install_without_a_device_is_unavailable(monkeypatch):
    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    with pytest.raises(installer.InstallerUnavailable):
        installer.Installer().install("ovos-tts-plugin-a", bus=None)


def test_job_log_is_bounded():
    job = installer.Job("install", "ovos-tts-plugin-a")
    for i in range(installer.MAX_LOG_LINES + 500):
        job.append(f"line {i}")
    assert len(job.lines) == installer.MAX_LOG_LINES
    assert job.lines[-1] == f"line {installer.MAX_LOG_LINES + 499}"


def test_job_paging():
    job = installer.Job("install", "ovos-tts-plugin-a")
    job.append("one")
    job.append("two")
    first = job.as_dict(since=0)
    assert first["lines"] == ["one", "two"] and first["next"] == 2
    job.append("three")
    assert job.as_dict(since=first["next"])["lines"] == ["three"]


def test_finished_job_tells_the_user_to_restart(monkeypatch):
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import configio
    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    monkeypatch.setattr(configio, "user_or_merged", lambda *a, **k: None)
    bus = FakeBus()
    bus.on("ovos.pip.install", lambda m: bus.emit(m.reply("ovos.pip.install.complete")))
    job = installer.Installer().install("ovos-tts-plugin-a", bus=bus)
    for _ in range(200):
        if job.state != "running":
            break
        time.sleep(0.01)
    assert job.state == "done"
    assert any("restart" in line.lower() for line in job.lines)
    assert job.as_dict()["restart_hint"] is True


def test_default_install_broadcasts_not_targeted(monkeypatch):
    """With no operator override, install broadcasts ovos.pip.install — the
    topic the running core actually answers — and does NOT emit a per-service
    topic (which nothing subscribes to and would hang the job)."""
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import configio
    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    monkeypatch.setattr(configio, "user_or_merged", lambda *a, **k: None)
    bus = FakeBus()
    targeted, broadcast = [], []
    bus.on("ovos.pip.install.ovos_audio", lambda m: targeted.append(m))
    bus.on("ovos.pip.install", lambda m: broadcast.append(m))
    installer.Installer().install("ovos-tts-plugin-mimic3", bus=bus)
    for _ in range(100):
        if broadcast:
            break
        time.sleep(0.01)
    assert broadcast and not targeted


def test_install_targets_a_service_when_the_operator_opts_in(monkeypatch):
    """An operator who runs a ServiceInstaller opts a kind in via
    webui.install_services; then that kind is addressed to its service."""
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import configio, updates
    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    monkeypatch.setattr(updates, "latest_versions", lambda name: {})  # offline: bare name
    monkeypatch.setattr(configio, "user_or_merged",
                        lambda *a, **k: {"tts": "ovos_audio"})
    bus = FakeBus()
    targeted = []
    bus.on("ovos.pip.install.ovos_audio", lambda m: targeted.append(m.data.get("packages")))
    installer.Installer().install("ovos-tts-plugin-mimic3", bus=bus)
    for _ in range(100):
        if targeted:
            break
        time.sleep(0.01)
    assert targeted == [["ovos-tts-plugin-mimic3"]]


def test_clear_plugin_caches_invalidates_the_installed_snapshot():
    """A just-installed package must not read as 'not installed' for 15s."""
    import time as _time
    pypi._INSTALLED_CACHE["val"] = {"ovos-utils": "1.0"}
    pypi._INSTALLED_CACHE["ts"] = _time.monotonic()
    installer._clear_plugin_caches()
    assert pypi._INSTALLED_CACHE["val"] is None
