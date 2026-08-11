"""Phase 3: try-it, live events, updates and channels, backup history,
skill enable/disable, persona activation, system actions.

The style follows the security review: every test either proves a feature
works or proves an abuse of it is refused.
"""
import json
import threading
import time
from pathlib import Path

import pytest

from ovos_webui import configio, updates
from ovos_webui.fsutils import atomic_write


# ── try it ───────────────────────────────────────────────────────────────────
def _answering_bus():
    from ovos_utils.fakebus import FakeBus, Message

    bus = FakeBus()

    def answer(message):
        bus.emit(Message("mycroft.skill.handler.start", {"name": "clock-skill"},
                         message.context))
        bus.emit(Message("speak", {"utterance": "It is noon."}, message.context))

    bus.on("recognizer_loop:utterance", answer)
    return bus


def test_tryit_reports_the_answer_and_the_skill():
    from ovos_webui import tryit

    result = tryit.ask(_answering_bus(), "what time is it", "en-us")
    assert result["matched"] is True
    assert result["spoken"] == ["It is noon."]
    assert result["handler"] == "clock-skill"


def test_tryit_reports_no_match():
    from ovos_utils.fakebus import FakeBus, Message
    from ovos_webui import tryit

    bus = FakeBus()
    bus.on("recognizer_loop:utterance",
           lambda m: bus.emit(Message("complete_intent_failure", {}, m.context)))
    result = tryit.ask(bus, "gibberish", "en-us")
    assert result["matched"] is False
    assert result["spoken"] == []


def test_tryit_refuses_empty_and_oversized_text():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import tryit

    with pytest.raises(ValueError):
        tryit.ask(FakeBus(), "   ", "en-us")
    with pytest.raises(ValueError):
        tryit.ask(FakeBus(), "x" * 501, "en-us")
    with pytest.raises(ValueError):
        tryit.preview(FakeBus(), "", "en-us")


def test_tryit_removes_its_listeners_afterwards():
    bus = _answering_bus()
    from ovos_webui import tryit

    before = {name: len(handlers) for name, handlers in bus.ee._events.items()}
    tryit.ask(bus, "what time is it", "en-us")
    after = {name: len(handlers) for name, handlers in bus.ee._events.items()}
    for name in ("speak", "mycroft.skill.handler.start", "complete_intent_failure"):
        assert after.get(name, 0) == before.get(name, 0), name


def test_tryit_route_needs_a_token(token_client):
    r = token_client.post("/api/tryit/ask", json={"text": "hello"})
    assert r.status_code == 401


AUTH = {"Authorization": "Bearer s3cret-token"}


def test_tryit_route_without_a_token_configured_is_refused(client):
    # No token configured at all: privileged actions are simply off.
    r = client.post("/api/tryit/speak", json={"text": "hello"})
    assert r.status_code == 403


def test_tryit_route_answers_over_the_bus(token_client):
    r = token_client.post("/api/tryit/speak", json={"text": "hello"},
                          headers=AUTH)
    assert r.status_code == 200
    assert r.json()["sent"] is True


# ── live events ──────────────────────────────────────────────────────────────
def test_events_are_recorded_and_paged():
    from ovos_utils.fakebus import FakeBus, Message
    from ovos_webui.events import EventLog

    bus = FakeBus()
    log = EventLog()
    log.attach(bus)
    bus.emit(Message("recognizer_loop:wakeword", {"hotword": "hey mycroft"}))
    bus.emit(Message("speak", {"utterance": "hello"}))
    first = log.since(0)
    assert [e["event"] for e in first["events"]] == ["wakeword", "speaking"]
    assert first["events"][0]["detail"] == "hey mycroft"
    again = log.since(first["next"])
    assert again["events"] == []


def test_events_buffer_is_bounded():
    from ovos_webui.events import MAX_EVENTS, EventLog

    log = EventLog()
    for i in range(MAX_EVENTS + 50):
        log.add("speaking", str(i))
    events = log.since(0)["events"]
    assert len(events) == MAX_EVENTS
    assert events[-1]["detail"] == str(MAX_EVENTS + 49)


def test_events_detail_is_capped():
    from ovos_webui.events import EventLog

    log = EventLog()
    log.add("speaking", "x" * 10_000)
    assert len(log.since(0)["events"][0]["detail"]) == 300


# ── release channel and upgrades ─────────────────────────────────────────────
def test_channel_defaults_to_stable_and_rejects_nonsense():
    assert updates.release_channel() == "stable"
    with pytest.raises(ValueError):
        updates.set_release_channel("nightly")
    with pytest.raises(ValueError):
        updates.set_release_channel("alpha; rm -rf /")


def test_channel_round_trip():
    updates.set_release_channel("alpha")
    assert updates.release_channel() == "alpha"
    data = configio.read_user_config()
    assert data["webui"]["release_channel"] == "alpha"
    updates.set_release_channel("stable")
    assert updates.release_channel() == "stable"


def test_channel_controls_the_pip_flags():
    from ovos_webui.installer import _channel_flags

    updates.set_release_channel("stable")
    assert _channel_flags() == []
    updates.set_release_channel("alpha")
    assert _channel_flags() == ["--pre"]
    updates.set_release_channel("stable")


def test_channel_route_needs_a_token(token_client):
    r = token_client.post("/api/updates/channel", json={"channel": "alpha"})
    assert r.status_code == 401


def test_channel_route_rejects_a_bad_channel(token_client):
    r = token_client.post("/api/updates/channel", json={"channel": "yolo"},
                          headers=AUTH)
    assert r.status_code == 400


def test_upgrade_route_needs_a_token(token_client):
    r = token_client.post("/api/plugins/upgrade", json={"package": "ovos-utils"})
    assert r.status_code == 401


def test_upgrade_refuses_a_package_that_is_not_installed():
    from ovos_webui.installer import Installer

    with pytest.raises(LookupError):
        Installer().upgrade("ovos-tts-plugin-surely-not-installed")


def test_upgrade_refuses_an_unsafe_name():
    from ovos_webui.installer import Installer, UnsafePackageName

    for evil in ("ovos-utils; rm -rf /", "-r evil.txt", "ovos utils",
                 "OVOS-UTILS", "ovos_utils", "../ovos-utils"):
        with pytest.raises((UnsafePackageName, LookupError)):
            Installer().upgrade(evil)


def test_latest_version_ordering():
    key = updates._version_key
    assert key("0.0.1a3") < key("0.0.1")
    assert key("0.9.0") < key("0.10.0")
    assert key("1.0.0") < key("1.0.1a1")


def test_conflicts_runs_pip_check():
    result = updates.dependency_conflicts()
    assert "ok" in result
    assert isinstance(result["conflicts"], list)


# ── backup history ───────────────────────────────────────────────────────────
def _make_history():
    conf = configio.user_config_path()
    atomic_write(conf, json.dumps({"lang": "en-us"}))
    time.sleep(0.02)
    atomic_write(conf, json.dumps({"lang": "pt-pt"}))


def test_history_lists_newest_first():
    from ovos_webui import history

    _make_history()
    backups = history.list_backups()
    assert len(backups) >= 2
    assert backups[0]["stamp"] >= backups[1]["stamp"]
    assert backups[0]["file"] == configio.user_config_path().name


def test_history_preview_and_revert_round_trip():
    from ovos_webui import history

    _make_history()
    # the newest backup holds the en-us version that the pt-pt save replaced
    newest = history.list_backups()[0]
    shown = history.read_backup(newest["id"])
    assert '"en-us"' in shown["text"]
    result = history.revert(newest["id"])
    assert result["backup"]  # the pt-pt version was itself backed up
    assert configio.read_user_config()["lang"] == "en-us"
    # and the revert can be reverted
    latest = history.list_backups()[0]
    shown = history.read_backup(latest["id"])
    assert '"pt-pt"' in shown["text"]


def test_history_refuses_traversal_and_alien_paths(tmp_path):
    from ovos_webui import history
    from ovos_webui.fsutils import UnsafeIdentifier

    _make_history()
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    for evil in ("../../../../etc/passwd", "/etc/passwd",
                 "..\\..\\config", "a\x00b", "", str(outside),
                 "mycroft.conf"):  # a real file, but not a backup
        with pytest.raises((UnsafeIdentifier, LookupError)):
            history.revert(evil)


def test_history_refuses_a_symlinked_backup():
    from ovos_webui import history

    _make_history()
    entry = history.list_backups()[0]
    bdir = configio.user_config_path().parent / ".ovos-webui-backups"
    link = bdir / "mycroft.conf.20990101T000000Z.bak"
    link.symlink_to("/etc/hostname")
    try:
        with pytest.raises(LookupError):
            history.read_backup(link.relative_to(
                Path(configio.user_config_path()).parent.resolve()).as_posix())
    finally:
        link.unlink()
    # the honest entry still works
    assert history.read_backup(entry["id"])


def test_revert_refuses_a_symlinked_target():
    from ovos_webui import history

    _make_history()
    conf_dir = Path(configio.user_config_path()).parent
    # a config file that is a symlink to an outside secret
    secret = conf_dir.parent / "secret.txt"
    secret.write_text("TOPSECRET")
    link = conf_dir / "linked.json"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(secret)
    atomic_write(conf_dir / "linked.json.placeholder", "{}")  # ensure dir
    # make a backup entry that points at the symlinked target
    from ovos_webui.fsutils import make_backup
    make_backup(link)
    entry = [b for b in history.list_backups() if b["file"] == "linked.json"]
    try:
        assert entry, "the backup of the linked file should still list"
        with pytest.raises(LookupError):
            history.revert(entry[0]["id"])
        # the symlink is intact and the outside file was not copied out
        assert link.is_symlink()
    finally:
        link.unlink()
        secret.unlink()


def test_conflicts_are_cached(monkeypatch):
    calls = {"n": 0}

    def fake_run():
        calls["n"] += 1
        return {"ok": True, "conflicts": []}

    monkeypatch.setattr(updates, "_run_pip_check", fake_run)
    updates._CONFLICTS_CACHE.clear()
    updates.dependency_conflicts()
    updates.dependency_conflicts()
    assert calls["n"] == 1  # the second call read the cache


def test_project_json_is_size_capped(monkeypatch):
    import io

    class Huge:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1): return b"x" * (5 * 1024 * 1024)

    monkeypatch.setattr("ovos_webui.pypi._open", lambda url: Huge())
    with pytest.raises(OSError):
        updates.latest_versions("ovos-tts-plugin-piper")


def test_events_route_needs_a_token(token_client):
    assert token_client.get("/api/events").status_code == 401


def test_history_routes(client):
    _make_history()
    listed = client.get("/api/backups").json()["backups"]
    assert listed
    shown = client.get("/api/backups/show",
                       params={"id": listed[0]["id"]})
    assert shown.status_code == 200
    bad = client.post("/api/backups/revert", json={"id": "../../etc/passwd"})
    assert bad.status_code in (400, 404)


# ── skill enable / disable ───────────────────────────────────────────────────
def test_blacklist_round_trip(client):
    skill = "ovos-skill-jokes.openvoiceos"
    assert client.get(f"/api/skills/{skill}/enabled").json()["enabled"] is True
    r = client.put(f"/api/skills/{skill}/enabled", json={"enabled": False})
    assert r.status_code == 200
    assert skill in configio.read_user_config()["skills"]["blacklisted_skills"]
    assert client.get(f"/api/skills/{skill}/enabled").json()["enabled"] is False
    client.put(f"/api/skills/{skill}/enabled", json={"enabled": True})
    assert skill not in (configio.read_user_config()["skills"]
                         .get("blacklisted_skills") or [])


def test_blacklist_disable_twice_adds_one_entry(client):
    skill = "ovos-skill-jokes.openvoiceos"
    client.put(f"/api/skills/{skill}/enabled", json={"enabled": False})
    client.put(f"/api/skills/{skill}/enabled", json={"enabled": False})
    blacklist = configio.read_user_config()["skills"]["blacklisted_skills"]
    assert blacklist.count(skill) == 1


def test_blacklist_rejects_an_unsafe_id(client):
    r = client.put("/api/skills/..%2F..%2Fetc/enabled", json={"enabled": False})
    assert r.status_code in (400, 404)


# ── persona activation ───────────────────────────────────────────────────────
def test_persona_activate_writes_the_config(client):
    client.put("/api/personas/librarian",
               json={"persona": {"name": "The Librarian",
                                 "solvers": ["ovos-solver-failure-plugin"]}})
    r = client.post("/api/personas/librarian/activate")
    assert r.status_code == 200
    assert r.json()["active"] == "The Librarian"
    merged = configio.read_user_config()
    assert merged["intents"]["persona"]["default_persona"] == "The Librarian"
    assert client.get("/api/personas").json()["active"] == "The Librarian"


def test_persona_activate_unknown_is_404(client):
    assert client.post("/api/personas/nope/activate").status_code == 404


def test_persona_activate_rejects_a_bad_id(client):
    assert client.post("/api/personas/..%2Fetc/activate").status_code in (400, 404)


# ── system actions ───────────────────────────────────────────────────────────
def test_system_action_emits_the_standard_message(token_client, bus):
    seen = []
    bus.on("system.reboot", lambda m: seen.append(m.msg_type))
    r = token_client.post("/api/system/reboot", headers=AUTH)
    assert r.status_code == 200
    assert seen == ["system.reboot"]


def test_system_action_unknown_is_404(token_client):
    r = token_client.post("/api/system/halt-and-catch-fire", headers=AUTH)
    assert r.status_code == 404


def test_system_action_needs_a_token(token_client):
    assert token_client.post("/api/system/reboot").status_code == 401


def test_updates_route_shape(client, monkeypatch):
    # never talk to the network in tests
    monkeypatch.setattr(updates, "latest_versions",
                        lambda name: {"stable": "99.0.0", "alpha": "99.0.1a1"})
    r = client.get("/api/updates")
    assert r.status_code == 200
    body = r.json()
    assert body["channel"] in updates.CHANNELS
    assert isinstance(body["packages"], list)
    for p in body["packages"]:
        assert set(p) == {"name", "installed", "latest", "outdated"}
