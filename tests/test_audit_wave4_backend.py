"""Regression tests for audit wave-4 backend (concurrency) findings.

- api_restore was an async route calling synchronous, fsync-heavy restore work
  directly on the event loop, stalling every other request.
- restore_archive committed files one at a time, so two concurrent restores
  interleaved into a mix of both archives.
- delete_persona/delete_override did an unguarded unlink after an is_file check,
  so a double-delete raised FileNotFoundError -> 500.
"""
import io
import pathlib
import tarfile
import threading
import time


def _archive(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_restore_runs_off_the_event_loop(client, monkeypatch):
    from ovos_webui import backupio, service
    called: dict = {}

    async def spy(fn, *args):
        called["fn"] = fn
        return {"restored": [], "backups": []}

    monkeypatch.setattr(service, "run_in_threadpool", spy)
    blob = _archive({"config/mycroft.conf": b"{}"})
    r = client.post("/api/restore", content=blob,
                    headers={"content-type": "application/gzip"})
    assert r.status_code == 200
    # The blocking restore must be dispatched off the loop, not called inline.
    assert called.get("fn") is backupio.restore_archive


def test_restore_is_serialized(monkeypatch):
    from ovos_webui import backupio
    live = {"n": 0, "max": 0}

    def fake(blob):
        live["n"] += 1
        live["max"] = max(live["max"], live["n"])
        time.sleep(0.1)
        live["n"] -= 1
        return {"restored": [], "backups": []}

    monkeypatch.setattr(backupio, "_restore_archive", fake)
    threads = [threading.Thread(target=backupio.restore_archive, args=(b"x",))
               for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert live["max"] == 1, "two restores ran at once"


def test_delete_persona_is_idempotent_on_a_lost_file(monkeypatch, tmp_path):
    from ovos_webui import fsutils, personas
    ghost = tmp_path / "ghost.json"
    monkeypatch.setattr(personas, "persona_path", lambda pid: ghost)
    monkeypatch.setattr(fsutils, "make_backup", lambda p: None)
    # The existence check passes, but the file is already gone at unlink time
    # (another delete removed it in between). unlink(missing_ok=True) must not
    # raise FileNotFoundError.
    real_is_file = pathlib.Path.is_file
    monkeypatch.setattr(pathlib.Path, "is_file",
                        lambda self: True if self == ghost else real_is_file(self))
    personas.delete_persona("ghost")  # no exception
