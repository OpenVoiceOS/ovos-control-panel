"""Test fixtures.

``ovos_config`` resolves the user configuration path when it is imported, so
the XDG variables are set here before anything from OVOS is imported. Every
test then works inside a temporary directory and never touches the real
configuration of the machine that runs the tests.
"""
import os
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="ovos-webui-tests-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_SANDBOX, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_SANDBOX, "data")
os.environ["XDG_CACHE_HOME"] = os.path.join(_SANDBOX, "cache")
os.environ["XDG_CONFIG_DIRS"] = os.path.join(_SANDBOX, "etc")
os.environ["OVOS_DEFAULT_CONFIG"] = os.environ.get("OVOS_DEFAULT_CONFIG", "")
os.makedirs(os.environ["XDG_CONFIG_HOME"], exist_ok=True)

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ovos_webui import configio, skillsio
from ovos_webui.service import create_app


@pytest.fixture(autouse=True)
def clean_sandbox():
    """Start every test with an empty user config and no skill settings."""
    conf = configio.user_config_path()
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("{}", encoding="utf-8")
    root = skillsio.skills_root()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    backups = conf.parent / ".ovos-webui-backups"
    if backups.exists():
        shutil.rmtree(backups)
    yield
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def bus():
    """A FakeBus with no service attached to it."""
    from ovos_utils.fakebus import FakeBus
    return FakeBus()


@pytest.fixture
def client(bus):
    """A TestClient over the app, with no token."""
    app = create_app(bus=bus, host="127.0.0.1", token=None, connect_bus=False)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def token_client(bus):
    """A TestClient over an app that needs a token."""
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret", connect_bus=False)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_skill():
    """Create a skill settings directory and return its path."""
    def _make(skill_id, settings=None, meta=None):
        sdir = skillsio.skills_root() / skill_id
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "settings.json").write_text(
            json.dumps(settings if settings is not None else {}), encoding="utf-8")
        if meta is not None:
            (sdir / "settingsmeta.json").write_text(json.dumps(meta), encoding="utf-8")
        return sdir
    return _make


@pytest.fixture
def sandbox_root() -> Path:
    return Path(_SANDBOX)
