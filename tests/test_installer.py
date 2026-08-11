"""Tests for the plugin installer.

The installer is the only part of ovos-webui that starts a process, so the
injection vectors are tested here first and hardest.
"""
import subprocess
import sys
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


def test_uninstall_refuses_a_package_that_is_not_installed(token_client):
    r = token_client.post("/api/plugins/uninstall",
                          json={"package": "ovos-tts-plugin-doesnotexist"},
                          headers={"Authorization": "Bearer s3cret-token"})
    assert r.status_code == 404


def test_the_command_never_uses_a_shell(monkeypatch):
    """A pip run must be an argument vector with shell=False."""
    seen = {}

    class FakeProcess:
        returncode = 0
        stdout = iter(["ok\n"])

        def wait(self, timeout=None):
            return 0

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    inst = installer.Installer()
    job = inst._start("install", "ovos-tts-plugin-mimic3",
                      [sys.executable, "-m", "pip", "install", "--", "ovos-tts-plugin-mimic3"])
    for _ in range(100):
        if job.state != "running":
            break
        time.sleep(0.01)
    assert isinstance(seen["argv"], list)
    assert seen["kwargs"]["shell"] is False
    assert seen["argv"][0] == sys.executable
    assert seen["argv"][-1] == "ovos-tts-plugin-mimic3"
    assert "--" in seen["argv"], "pip must be told the name is not an option"


def test_install_uses_this_interpreter(monkeypatch):
    """A plugin must land where OVOS imports from, not in another environment."""
    captured = {}
    monkeypatch.setattr(installer.Installer, "_start",
                        lambda self, a, p, argv: captured.update(argv=argv) or object())
    monkeypatch.setattr(pypi, "details", lambda name: {"name": name})
    installer.Installer().install("ovos-tts-plugin-mimic3")
    assert captured["argv"][:3] == [sys.executable, "-m", "pip"]


def test_install_checks_pypi_before_running(monkeypatch):
    """A name that PyPI does not know must never reach pip."""
    started = []
    monkeypatch.setattr(installer.Installer, "_start",
                        lambda self, a, p, argv: started.append(argv))

    def missing(name):
        raise LookupError("no such package")

    monkeypatch.setattr(pypi, "details", missing)
    with pytest.raises(LookupError):
        installer.Installer().install("ovos-tts-plugin-nope")
    assert started == []


def test_only_one_job_runs_at_a_time(monkeypatch):
    class SlowProcess:
        returncode = 0
        stdout = iter([])

        def wait(self, timeout=None):
            time.sleep(0.5)
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: SlowProcess())
    inst = installer.Installer()
    inst._start("install", "ovos-tts-plugin-a", ["true"])
    with pytest.raises(installer.InstallerBusy):
        inst._start("install", "ovos-tts-plugin-b", ["true"])


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
    class FakeProcess:
        returncode = 0
        stdout = iter(["done\n"])

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: FakeProcess())
    inst = installer.Installer()
    job = inst._start("install", "ovos-tts-plugin-a", ["true"])
    for _ in range(200):
        if job.state != "running":
            break
        time.sleep(0.01)
    assert job.state == "done"
    assert any("restart" in line.lower() for line in job.lines)
    assert job.as_dict()["restart_hint"] is True
