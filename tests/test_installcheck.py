"""What an install would change, before it runs (#113)."""
import json
import subprocess
import sys

import pytest

from ovos_webui import installcheck, pages, pypi

REPORT = {"install": [
    {"metadata": {"name": "neon-homeassistant-skill", "version": "1.0.0"}, "requested": True},
    {"metadata": {"name": "ovos_bus_client", "version": "1.3.7"}},
    {"metadata": {"name": "ovos-utils", "version": "0.16.0"}},
    {"metadata": {"name": "nested-lookup", "version": "0.2.25"}},
]}
INSTALLED = {"ovos-bus-client": "2.11.29a1", "ovos-utils": "0.15.7a3"}


@pytest.fixture(autouse=True)
def _fresh():
    installcheck.forget()
    yield
    installcheck.forget()


def test_the_dry_run_mirrors_the_device_installer():
    argv = installcheck.pip_argv("ovos-skill-news", {})
    assert argv[:4] == [sys.executable, "-m", "pip", "install"]
    assert "--dry-run" in argv and argv[argv.index("--report") + 1] == "-"
    assert argv[argv.index("-c") + 1] == installcheck.DEFAULT_CONSTRAINTS
    assert argv[-1] == "ovos-skill-news"
    assert "--pre" not in argv and "--upgrade" not in argv

    argv = installcheck.pip_argv("ovos-skill-news", {
        "constraints": "https://example.org/constraints-alpha.txt",
        "allow_alphas": True, "upgrade": True, "break_system_packages": True})
    assert argv[argv.index("-c") + 1] == "https://example.org/constraints-alpha.txt"
    assert {"--pre", "--upgrade", "--break-system-packages"} <= set(argv)
    assert argv[-1] == "ovos-skill-news"


def test_downgrades_upgrades_and_new_packages_are_told_apart():
    out = installcheck.compare(REPORT, INSTALLED, "neon-homeassistant-skill")  # what #103 saw
    assert out["downgrades"] == [{"name": "ovos_bus_client", "to": "1.3.7", "from": "2.11.29a1"}]
    assert out["upgrades"] == [{"name": "ovos-utils", "to": "0.16.0", "from": "0.15.7a3"}]
    assert out["new"] == [{"name": "nested-lookup", "to": "0.2.25"}], "the package itself is not listed"


def _colocated(monkeypatch, yes=True):
    monkeypatch.setattr(pages, "colocated", lambda have=None: yes)


def test_a_panel_apart_from_the_assistant_cannot_check(monkeypatch):
    _colocated(monkeypatch, False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("pip must not run"))
    assert installcheck.check("ovos-skill-news") == {
        "package": "ovos-skill-news", "checked": False, "reason": "apart"}


def test_a_check_runs_pip_once_and_is_kept(monkeypatch):
    _colocated(monkeypatch)
    monkeypatch.setattr(pypi, "installed_versions", lambda: dict(INSTALLED))
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert kwargs.get("shell") is False
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(REPORT), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    first = installcheck.check("ovos-skill-news")
    assert first["checked"] is True and first["downgrades"][0]["to"] == "1.3.7"
    assert installcheck.check("ovos-skill-news") == first
    assert len(calls) == 1
    pypi.invalidate_installed_cache()
    installcheck.check("ovos-skill-news")
    assert len(calls) == 2, "an install or removal drops the kept answers"


def test_a_run_pip_could_not_work_out_says_so(monkeypatch):
    _colocated(monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(
        argv, 1, stdout="", stderr="ERROR: Failed to build 'pyyaml'"))
    out = installcheck.check("ovos-skill-news")
    assert out["checked"] is False and out["reason"] == "pip-failed"
    assert "pyyaml" in out["detail"]


def test_a_slow_run_gives_up(monkeypatch):
    _colocated(monkeypatch)

    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", slow)
    assert installcheck.check("ovos-skill-news")["reason"] == "timeout"


@pytest.mark.parametrize("bad", ["ovos-skill-news==0.1", "ovos-skill-news; rm -rf /", "requests"])
def test_only_valid_package_names_are_checked(monkeypatch, bad):
    _colocated(monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("pip must not run"))
    from ovos_webui.installer import UnsafePackageName
    with pytest.raises(UnsafePackageName):
        installcheck.check(bad)


AUTH = {"Authorization": "Bearer s3cret-token"}


def test_the_route_needs_a_token_even_on_localhost(client, token_client):
    # it runs pip, so it is guarded like installing is
    assert client.post("/api/plugins/check", json={"package": "ovos-skill-news"}).status_code == 403
    assert token_client.post("/api/plugins/check", json={"package": "ovos-skill-news"},
                             headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_the_route(token_client, monkeypatch):
    _colocated(monkeypatch, False)
    r = token_client.post("/api/plugins/check", json={"package": "ovos-skill-news"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["reason"] == "apart"
    assert token_client.post("/api/plugins/check", json={"package": "requests"},
                             headers=AUTH).status_code == 400
