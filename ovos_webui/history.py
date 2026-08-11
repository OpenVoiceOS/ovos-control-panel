"""Browse and revert the backups the app keeps on the device.

Every save in this app first copies the old file into a
``.ovos-webui-backups`` directory next to it (:mod:`ovos_webui.fsutils`).
This module makes that promise usable from the browser: list those backups,
show one, and put one back.

A backup is addressed by its path *relative to the configuration home*. The
identifier is validated the same way uploaded archive members are: it must
resolve inside the configuration home, its directory must be a
``.ovos-webui-backups`` directory, and its name must end in ``.bak``. Nothing
else on the disk is reachable.

Reverting goes through :func:`ovos_webui.fsutils.atomic_write`, so the file
being replaced is itself backed up first — a revert can always be reverted.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ovos_webui.fsutils import UnsafeIdentifier, atomic_write, is_within

BACKUP_DIR_NAME = ".ovos-webui-backups"

#: ``settings.json.20260811T000000Z.bak`` (with an optional ``.N`` counter
#: when two saves land in the same second) — name, stamp, suffix.
_BAK_RE = re.compile(
    r"^(?P<name>.+?)\.(?P<stamp>[0-9]{8}T[0-9]{6}Z(?:\.[0-9]+)?)\.bak$")

#: The largest backup the preview endpoint will return, in bytes.
MAX_PREVIEW = 256 * 1024

#: Never walk deeper than this below the configuration home.
MAX_DEPTH = 6


def config_home() -> Path:
    """The directory everything this app writes lives under."""
    from ovos_webui.configio import user_config_path

    return Path(user_config_path()).parent.resolve()


def roots() -> list[Path]:
    """The directories that may hold backups."""
    from ovos_webui.personas import personas_root

    home = config_home()
    out = [home]
    try:
        personas = Path(personas_root()).resolve()
        if personas != home and not is_within(home, personas):
            out.append(personas)
    except Exception:  # pragma: no cover - ovos_persona missing
        pass
    return out


def _describe(bak: Path, root: Path) -> dict[str, Any] | None:
    match = _BAK_RE.match(bak.name)
    if not match:
        return None
    try:
        size = bak.stat().st_size
    except OSError:
        return None
    target = bak.parent.parent / match.group("name")
    return {
        "id": bak.relative_to(root).as_posix(),
        "root": root.name,
        "file": match.group("name"),
        "target": str(target),
        "stamp": match.group("stamp"),
        "size": size,
    }


def list_backups() -> list[dict[str, Any]]:
    """Every backup on the device, newest first."""
    found = []
    for root in roots():
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            if len(here.parts) - base_depth > MAX_DEPTH:
                dirnames[:] = []
                continue
            if here.name != BACKUP_DIR_NAME:
                continue
            for filename in filenames:
                entry = _describe(here / filename, root)
                if entry:
                    found.append(entry)
    found.sort(key=lambda e: e["stamp"], reverse=True)
    return found


def _resolve(backup_id: str) -> tuple[Path, Path]:
    """Turn a backup id back into (backup path, its target file), safely."""
    if not isinstance(backup_id, str) or not backup_id or "\x00" in backup_id:
        raise UnsafeIdentifier("that is not a backup id")
    for root in roots():
        candidate = (root / backup_id).resolve()
        if not is_within(root, candidate):
            continue
        if candidate.parent.name != BACKUP_DIR_NAME:
            continue
        match = _BAK_RE.match(candidate.name)
        if not match:
            continue
        if not candidate.is_file() or candidate.is_symlink():
            continue
        target = candidate.parent.parent / match.group("name")
        return candidate, target
    raise LookupError("there is no backup with that id")


def read_backup(backup_id: str) -> dict[str, Any]:
    """Return the text of one backup, capped at :data:`MAX_PREVIEW`."""
    backup, target = _resolve(backup_id)
    raw = backup.read_bytes()[:MAX_PREVIEW + 1]
    truncated = len(raw) > MAX_PREVIEW
    text = raw[:MAX_PREVIEW].decode("utf-8", errors="replace")
    return {"id": backup_id, "target": str(target), "text": text,
            "truncated": truncated}


def revert(backup_id: str) -> dict[str, Any]:
    """Put one backup back in place of its file."""
    backup, target = _resolve(backup_id)
    content = backup.read_text(encoding="utf-8")
    new_backup = atomic_write(target, content)
    return {"reverted": str(target),
            "backup": str(new_backup) if new_backup else None}
