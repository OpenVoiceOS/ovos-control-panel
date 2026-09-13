"""Where the location from "Detect my location" ends up, against the real
ovos-config 3.x merge.

ovos-PHAL-plugin-ipgeo writes the assistant layer (``runtime.conf``).
ovos-config 3.x merges ``[default, distribution, system, assistant,
*xdg_configs, patch]``, and ``disable_user_config`` never drops the assistant
layer, only the user layers.

ovos-config builds its layers once per process, from paths it reads out of the
environment at import. So each case runs in its own process, with a fresh
HOME, XDG directories, system file and distribution file. Each case checks two
things: what the merge really gives, and that ``_detected_location_fate`` says
the same thing about it.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("ovos_config")

ROOT = Path(__file__).resolve().parents[1]

SNIPPET = r"""
import json
from ovos_config.config import Configuration

# what ovos-PHAL-plugin-ipgeo does with a detected location
Configuration.assistant["location"] = {"city": {"name": "Detected"}}
Configuration.assistant.store()

from ovos_webui.system import _detected_location_fate

merged = Configuration.load_all_configs(Configuration.get_system_constraints())
city = ((merged.get("location") or {}).get("city") or {}).get("name")
print(json.dumps({"fate": _detected_location_fate(), "city": city,
                  "assistant_path": Configuration.assistant.path}))
"""

USER_SET = {"location": {"city": {"name": "UserSet"}}}


def _constraints(**system):
    return {"system": system}


def _run(tmp_path, *, system=None, distribution=None, user=None):
    xdg = tmp_path / "config"
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("XDG_", "MYCROFT_", "OVOS_CONFIG", "OVOS_DISTRIBUTION"))}
    env.update(
        HOME=str(tmp_path / "home"),
        XDG_CONFIG_HOME=str(xdg),
        XDG_DATA_HOME=str(tmp_path / "data"),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        XDG_STATE_HOME=str(tmp_path / "state"),
        XDG_CONFIG_DIRS=str(tmp_path / "etc"),
        MYCROFT_SYSTEM_CONFIG=str(tmp_path / "system.conf"),
        OVOS_DISTRIBUTION_CONFIG=str(tmp_path / "distribution.conf"),
        MYCROFT_WEB_CACHE=str(tmp_path / "web_cache.json"),
    )
    for name in ("home", "config", "data", "cache", "state", "etc"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    if system is not None:
        (tmp_path / "system.conf").write_text(json.dumps(system))
    if distribution is not None:
        (tmp_path / "distribution.conf").write_text(json.dumps(distribution))
    if user is not None:
        (xdg / "mycroft").mkdir(parents=True, exist_ok=True)
        (xdg / "mycroft" / "mycroft.conf").write_text(json.dumps(user))
    r = subprocess.run([sys.executable, "-c", SNIPPET], env=env, cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    # the case really ran on its own scratch layers, not on this machine's config
    assert out["assistant_path"].startswith(str(xdg)), out
    return out


@pytest.mark.parametrize("layers, fate, city", [
    pytest.param({}, None, "Detected", id="nothing-else"),
    # the assistant layer is not a user layer: disable_user_config keeps it
    pytest.param({"system": _constraints(disable_user_config=True)}, None, "Detected",
                 id="disable-user-config"),
    # system and distribution merge below the assistant layer
    pytest.param({"system": {"location": {"city": {"name": "SystemSet"}}}}, None, "Detected",
                 id="location-in-system"),
    pytest.param({"distribution": {"location": {"city": {"name": "DistSet"}}}}, None, "Detected",
                 id="location-in-distribution"),
    # an XDG user file merges above it and wins
    pytest.param({"user": USER_SET}, "overridden", "UserSet", id="location-in-user-xdg"),
    # ... unless the user layers are dropped, or their location is protected
    pytest.param({"system": _constraints(disable_user_config=True), "user": USER_SET}, None, "Detected",
                 id="user-xdg-under-disable-user-config"),
    pytest.param({"system": _constraints(protected_keys={"user": ["location"]}), "user": USER_SET},
                 None, "Detected", id="user-xdg-under-protected-user"),
])
def test_fate_matches_the_real_merge(tmp_path, layers, fate, city):
    out = _run(tmp_path, **layers)
    assert out["city"] == city, out
    assert out["fate"] == fate, out


def test_protected_assistant_location_is_ignored(tmp_path):
    out = _run(tmp_path, system=_constraints(protected_keys={"assistant": ["location"]}))
    # the detected location never reaches the merge, and nothing overrode it
    assert out["city"] != "Detected", out
    assert out["fate"] == "ignored", out


def test_protected_assistant_leaf_is_ignored(tmp_path):
    out = _run(tmp_path, system=_constraints(protected_keys={"assistant": ["location:city"]}))
    assert out["city"] != "Detected", out
    assert out["fate"] == "ignored", out
