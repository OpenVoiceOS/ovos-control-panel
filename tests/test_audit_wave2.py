"""Regression tests for audit wave-2 findings.

- history.list_backups sorted by the stamp STRING, so once a file had 10+
  same-second backups the unpadded counter (".9" vs ".10") ordered them wrong
  and the History page could surface/revert a stale "latest" backup.
- tryit.ask counted a context-less reply from any concurrent try as its own;
  it is now serialized so only one try waits on the shared topics at a time.
"""
import os

from ovos_utils.fakebus import FakeBus


def test_history_orders_same_second_backups_by_mtime(tmp_path, monkeypatch):
    import ovos_webui.history as history

    bdir = tmp_path / history.BACKUP_DIR_NAME
    bdir.mkdir()
    stamp = "20260811T000000Z"
    older = bdir / f"settings.json.{stamp}.9.bak"    # made first
    newer = bdir / f"settings.json.{stamp}.10.bak"   # made later -> newest
    older.write_text("old")
    newer.write_text("new")
    # Same-second stamp; the real order is modification time.
    os.utime(older, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    os.utime(newer, ns=(2_000_000_000_000_000_000, 2_000_000_000_000_000_000))
    monkeypatch.setattr(history, "roots", lambda: [tmp_path])

    ids = [e["id"] for e in history.list_backups()]
    assert ids, "no backups found"
    # Newest first: the .10 backup, not the lexicographically-larger .9 string.
    assert ids[0].endswith(".10.bak"), ids


def test_tryit_is_serialized_while_one_is_running():
    import ovos_webui.tryit as tryit

    orig_t, orig_s = tryit.ANSWER_TIMEOUT, tryit.SETTLE
    tryit.ANSWER_TIMEOUT, tryit.SETTLE = 0.1, 0.0
    tryit._ASK_LOCK.acquire()  # stand in for another try already in flight
    try:
        res = tryit.ask(FakeBus(), "hello", "en-us")
    finally:
        tryit._ASK_LOCK.release()
        tryit.ANSWER_TIMEOUT, tryit.SETTLE = orig_t, orig_s
    # A second try does not run concurrently — it reports busy instead of
    # racing on the shared reply topics.
    assert res.get("busy") is True
