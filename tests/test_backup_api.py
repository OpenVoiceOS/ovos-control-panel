"""Tests for backup and restore, including crafted archives."""
import io
import json
import tarfile

import pytest

from ovos_webui import backupio, configio, skillsio
from ovos_webui.fsutils import MAX_UPLOAD_BYTES


def _archive(members):
    """Build a gzip tar archive from ``{name: bytes}``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _link_archive(name, target, kind="sym"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name)
        info.type = tarfile.SYMTYPE if kind == "sym" else tarfile.LNKTYPE
        info.linkname = target
        tar.addfile(info)
    return buf.getvalue()


def test_download_backup(client, make_skill):
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    make_skill("skill-a", {"volume": 3})
    r = client.get("/api/backup")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gzip"
    assert "attachment" in r.headers["content-disposition"]
    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tar:
        names = sorted(tar.getnames())
    assert names == ["config/mycroft.conf", "skills/skill-a/settings.json"]


def test_backup_restore_round_trip(client, make_skill):
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    make_skill("skill-a", {"volume": 3})
    blob = client.get("/api/backup").content

    client.put("/api/config", json={"text": '{"lang": "en-us"}', "format": "json"})
    client.put("/api/skills/skill-a", json={"settings": {"volume": 99}})

    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 200
    assert len(r.json()["restored"]) == 2
    assert configio.read_user_config()["lang"] == "pt-pt"
    assert skillsio.read_settings("skill-a") == {"volume": 3}


def test_restore_keeps_a_backup_of_what_it_replaced(client):
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    blob = client.get("/api/backup").content
    client.put("/api/config", json={"text": '{"lang": "en-us"}', "format": "json"})
    backups = client.post("/api/restore",
                          files={"file": ("b.tar.gz", blob, "application/gzip")}).json()["backups"]
    assert backups
    with open(backups[0]) as handle:
        assert json.load(handle)["lang"] == "en-us"


def test_restore_accepts_a_raw_body(client):
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    blob = client.get("/api/backup").content
    r = client.post("/api/restore", content=blob,
                    headers={"content-type": "application/gzip"})
    assert r.status_code == 200


@pytest.mark.parametrize("name", [
    "../../../../tmp/pwned",
    "/tmp/pwned",
    "config/../../pwned",
    "skills/../../pwned",
    "skills/../evil/settings.json",
    "skills/.hidden/settings.json",
    "skills/a/b/settings.json",
    "random.txt",
    "config/other.conf",
])
def test_restore_refuses_a_crafted_member(client, name):
    blob = _archive({name: b"{}"})
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400, f"{name} was accepted"


def test_restore_refuses_a_symlink_member(client):
    blob = _link_archive("config/mycroft.conf", "/etc/passwd", "sym")
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400


def test_restore_refuses_a_hard_link_member(client):
    blob = _link_archive("config/mycroft.conf", "/etc/passwd", "link")
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400


def test_restore_writes_nothing_when_one_member_is_bad(client, sandbox_root):
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    blob = _archive({"config/mycroft.conf": b'{"lang": "hacked"}', "evil.txt": b"x"})
    assert client.post("/api/restore",
                       files={"file": ("b.tar.gz", blob, "application/gzip")}).status_code == 400
    assert configio.read_user_config()["lang"] == "pt-pt"


def test_restore_refuses_a_file_that_is_not_an_archive(client):
    r = client.post("/api/restore", files={"file": ("b.tar.gz", b"not an archive", "application/gzip")})
    assert r.status_code == 400


def test_restore_refuses_an_empty_archive(client):
    r = client.post("/api/restore", files={"file": ("b.tar.gz", _archive({}), "application/gzip")})
    assert r.status_code == 400


def test_restore_refuses_an_oversized_upload(client):
    payload = b"x" * (MAX_UPLOAD_BYTES + 4096)
    r = client.post("/api/restore", content=payload,
                    headers={"content-type": "application/gzip"})
    assert r.status_code == 413


def test_restore_refuses_a_bomb(client):
    big = b"0" * (backupio.MAX_UNPACKED_BYTES + 1)
    blob = _archive({"config/mycroft.conf": big})
    assert len(blob) < MAX_UPLOAD_BYTES
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400


def test_restore_without_a_file_field(client):
    r = client.post("/api/restore", files={"other": ("b", b"x", "application/gzip")})
    assert r.status_code == 400
