"""Tests for the file helpers, including the identifier gate."""
import threading

import pytest

from ovos_webui import fsutils

TRAVERSAL = [
    "../evil",
    "..",
    ".",
    "../../etc/passwd",
    "/etc/passwd",
    "skills/../../evil",
    "a/b",
    "a\\b",
    "..%2f..%2fetc",
    "\x00evil",
    "evil\x00",
    ".hidden",
    "",
    "x" * 200,
    "sk;rm -rf /",
    "sk|id",
    "sk$(id)",
    "sk\nid",
]


@pytest.mark.parametrize("bad", TRAVERSAL)
def test_validate_skill_id_rejects_unsafe(bad):
    with pytest.raises(ValueError):
        fsutils.validate_skill_id(bad)


@pytest.mark.parametrize("good", ["ovos-skill-news.openvoiceos", "skill_a", "A1", "a.b-c_d"])
def test_validate_skill_id_accepts_plain_names(good):
    assert fsutils.validate_skill_id(good) == good


def test_validate_skill_id_rejects_non_string():
    with pytest.raises(ValueError):
        fsutils.validate_skill_id(None)


def test_is_within(tmp_path):
    assert fsutils.is_within(tmp_path, tmp_path / "a" / "b")
    assert fsutils.is_within(tmp_path, tmp_path)
    assert not fsutils.is_within(tmp_path / "a", tmp_path)


def test_atomic_write_creates_and_backs_up(tmp_path):
    target = tmp_path / "f.json"
    assert fsutils.atomic_write(target, "one") is None
    assert target.read_text() == "one"
    backup = fsutils.atomic_write(target, "two")
    assert backup is not None and backup.read_text() == "one"
    assert target.read_text() == "two"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "f.json"
    fsutils.atomic_write(target, "one")
    fsutils.atomic_write(target, "two")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_backups_are_pruned(tmp_path):
    target = tmp_path / "f.json"
    for i in range(fsutils.MAX_BACKUPS + 5):
        fsutils.atomic_write(target, str(i))
    assert len(fsutils.list_backups(target)) <= fsutils.MAX_BACKUPS


def test_concurrent_writes_leave_a_whole_file(tmp_path):
    target = tmp_path / "f.json"
    payloads = ["a" * 5000, "b" * 5000, "c" * 5000]
    threads = [threading.Thread(target=fsutils.atomic_write, args=(target, p))
               for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert target.read_text() in payloads
