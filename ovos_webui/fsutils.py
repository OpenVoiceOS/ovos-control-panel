"""File helpers: safe identifiers, atomic writes and timestamped backups.

Every write that this package makes to a user file goes through
:func:`atomic_write`. It first copies the old file into a backup, then writes
the new content to a temporary file in the same directory, and finally renames
that file over the target. A crash in the middle leaves the old file intact.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

#: Largest body this service accepts on any write endpoint.
MAX_PAYLOAD_BYTES = 1024 * 1024  # 1 MiB

#: Largest upload this service accepts on the restore endpoint.
MAX_UPLOAD_BYTES = 16 * 1024 * 1024  # 16 MiB

#: Number of backups kept per file.
MAX_BACKUPS = 20

#: A skill id is a plain name. It is never a path.
SKILL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_WRITE_LOCK = threading.RLock()


class UnsafeIdentifier(ValueError):
    """Raised when a caller sends an identifier that is not a plain name."""


def validate_skill_id(skill_id: str) -> str:
    """Return ``skill_id`` if it is a plain name, else raise.

    This is the only gate between an HTTP path parameter and the file system.
    It rejects path separators, parent references, null bytes, absolute paths
    and names that start with a dot.
    """
    if not isinstance(skill_id, str) or not skill_id:
        raise UnsafeIdentifier("skill id is empty")
    if "\x00" in skill_id:
        raise UnsafeIdentifier("skill id contains a null byte")
    if "/" in skill_id or "\\" in skill_id:
        raise UnsafeIdentifier("skill id contains a path separator")
    if skill_id in (".", "..") or skill_id.startswith("."):
        raise UnsafeIdentifier("skill id starts with a dot")
    if not SKILL_ID_RE.match(skill_id):
        raise UnsafeIdentifier("skill id has characters that are not allowed")
    return skill_id


def is_within(base: Path, target: Path) -> bool:
    """Return True when ``target`` stays inside ``base`` after resolution."""
    try:
        base_r = Path(os.path.realpath(base))
        target_r = Path(os.path.realpath(target))
    except OSError:
        return False
    return base_r == target_r or base_r in target_r.parents


def timestamp() -> str:
    """Return a file-name safe UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_dir_for(path: Path) -> Path:
    """Return the directory that holds the backups of ``path``."""
    return Path(path).parent / ".ovos-webui-backups"


def make_backup(path: Path) -> Path | None:
    """Copy ``path`` into its backup directory. Return the backup path.

    Return ``None`` when there is nothing to back up.
    """
    path = Path(path)
    if not path.is_file():
        return None
    bdir = backup_dir_for(path)
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / f"{path.name}.{timestamp()}.bak"
    n = 0
    while dest.exists():
        n += 1
        dest = bdir / f"{path.name}.{timestamp()}.{n}.bak"
    shutil.copy2(path, dest)
    _prune_backups(bdir, path.name)
    return dest


def _prune_backups(bdir: Path, name: str) -> None:
    backups = sorted(bdir.glob(f"{name}.*.bak"))
    for old in backups[:-MAX_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups(path: Path) -> list[Path]:
    """Return the backups of ``path``, oldest first."""
    bdir = backup_dir_for(path)
    if not bdir.is_dir():
        return []
    return sorted(bdir.glob(f"{Path(path).name}.*.bak"))


def atomic_write(path: Path, content: str, backup: bool = True) -> Path | None:
    """Write ``content`` to ``path`` atomically. Return the backup path.

    The lock makes two requests that write the same file run one after the
    other, so a reader never sees a half-written file and the later write wins
    as a whole.
    """
    path = Path(path)
    data = content.encode("utf-8")
    with _WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = make_backup(path) if backup else None
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return backup_path
