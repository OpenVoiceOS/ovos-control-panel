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
import stat
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from ovos_utils.log import LOG

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


def latest_backup(path: Path) -> Path | None:
    """Return the most recent backup of ``path``, or ``None`` if there is none.

    This is the copy taken just before the last write, so restoring it undoes
    that write.
    """
    backups = _sorted_backups(backup_dir_for(path), Path(path).name)
    return backups[-1] if backups else None


def _sorted_backups(bdir: Path, name: str) -> list[Path]:
    """Return backups oldest first.

    The names carry a timestamp with a resolution of one second, so several
    backups can share a name prefix. Sorting by modification time, with the
    name as the tie breaker, keeps the real order.
    """
    def key(path: Path):
        try:
            return (path.stat().st_mtime_ns, path.name)
        except OSError:  # pragma: no cover - the file went away
            return (0, path.name)

    return sorted(bdir.glob(f"{name}.*.bak"), key=key)


def _restore_metadata(tmp: str, previous) -> None:
    """Give the new file the mode and owner the old one had.

    A file that does not exist yet keeps the private mode ``mkstemp`` gives it.
    The files this package creates hold configuration and skill settings, and
    those carry API keys and passwords, so a new one is private until somebody
    decides otherwise. Only an existing file keeps the mode it already had,
    because that mode was somebody's decision.
    """
    if previous is None:
        os.chmod(tmp, 0o600)
        return
    try:
        os.chmod(tmp, stat.S_IMODE(previous.st_mode))
    except OSError as err:  # pragma: no cover - unusual file systems
        LOG.debug(f"could not copy the file mode: {err}")
    try:
        os.chown(tmp, previous.st_uid, previous.st_gid)
    except (OSError, AttributeError) as err:  # pragma: no cover - needs privilege
        LOG.debug(f"could not copy the file owner: {err}")


def _prune_backups(bdir: Path, name: str) -> None:
    backups = _sorted_backups(bdir, name)
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
    return _sorted_backups(bdir, Path(path).name)


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
        # Remember what the file looks like now. ``mkstemp`` always makes a
        # 0600 file owned by this process, so replacing without copying the
        # old mode and owner would silently tighten or change them.
        previous = None
        try:
            previous = os.stat(path)
        except FileNotFoundError:
            pass
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            _restore_metadata(tmp, previous)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return backup_path


def assert_within(base: Path, target: Path) -> None:
    """Raise when ``target`` does not really sit inside ``base``.

    ``is_within`` resolves symbolic links on both sides, so a directory inside
    ``base`` that is a link to somewhere else fails this check. It is called
    again at the moment of writing, not only when a name is parsed, because a
    link can appear between the two.
    """
    if not is_within(base, target):
        raise UnsafeIdentifier(
            f"{target} resolves outside {base}; refusing to write there")


def stage_file(path: Path, content: str, within: Path | None = None) -> Path:
    """Write ``content`` to a temporary file beside ``path``.

    Nothing at ``path`` is touched. Use :func:`commit_staged` to put the
    staged file into place, or unlink it to throw the change away. This lets a
    caller prepare several files and only then replace any of them.

    ``within`` names a directory the file must really be inside. The check runs
    after the parent directories are made, because that is when a link on the
    way there becomes real.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if within is not None:
        assert_within(within, path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".staged")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        os.unlink(tmp)
        raise
    return Path(tmp)


def commit_staged(path: Path, staged: Path, within: Path | None = None) -> Path | None:
    """Back up ``path`` and rename ``staged`` over it. Return the backup.

    ``within`` is checked once more here. The name was checked when it was
    parsed and again when the file was staged; this is the last moment before
    a real write, so it is the one that counts.
    """
    path = Path(path)
    with _WRITE_LOCK:
        if within is not None:
            assert_within(within, path)
        previous = None
        try:
            previous = os.stat(path)
        except FileNotFoundError:
            pass
        backup_path = make_backup(path)
        _restore_metadata(str(staged), previous)
        os.replace(str(staged), str(path))
    return backup_path
