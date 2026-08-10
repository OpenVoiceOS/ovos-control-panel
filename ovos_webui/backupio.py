"""Make and restore a backup of the user configuration and skill settings.

The archive holds two things: the user layer of ``mycroft.conf`` and every
``settings.json`` under the skill settings directory. Restore refuses any
archive member that would write outside those two places, so a crafted
archive cannot reach the rest of the file system.
"""
from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any

from ovos_webui.configio import user_config_path
from ovos_webui.fsutils import (
    MAX_UPLOAD_BYTES,
    atomic_write,
    timestamp,
    validate_skill_id,
)
from ovos_webui.skillsio import skills_root

CONFIG_MEMBER = "config/mycroft.conf"
SKILLS_PREFIX = "skills/"

#: Refuse an archive that unpacks to more than this. It guards against a
#: small archive that expands to fill the disk.
MAX_UNPACKED_BYTES = 64 * 1024 * 1024

#: Refuse an archive with more members than this.
MAX_MEMBERS = 5000


class RestoreError(ValueError):
    """Raised when an uploaded archive is refused."""


def archive_name() -> str:
    """Return the file name to offer for download."""
    return f"ovos-webui-backup-{timestamp()}.tar.gz"


def make_archive() -> bytes:
    """Return a gzip tar archive of the user config and the skill settings."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        conf = user_config_path()
        if conf.is_file():
            tar.add(str(conf), arcname=CONFIG_MEMBER)
        root = skills_root()
        if root.is_dir():
            for child in sorted(root.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                try:
                    validate_skill_id(child.name)
                except ValueError:
                    continue
                settings = child / "settings.json"
                if settings.is_file():
                    tar.add(str(settings), arcname=f"{SKILLS_PREFIX}{child.name}/settings.json")
    return buf.getvalue()


def _check_member(member: tarfile.TarInfo) -> None:
    """Raise when a member is not a plain file in an allowed place."""
    name = member.name
    if member.issym() or member.islnk():
        raise RestoreError(f"the archive holds a link: {name}")
    if member.isdir():
        return
    if not member.isfile():
        raise RestoreError(f"the archive holds a special file: {name}")
    if name.startswith("/") or "\x00" in name:
        raise RestoreError(f"the archive holds an absolute path: {name}")
    parts = Path(name).parts
    if ".." in parts or any(p.endswith(":") for p in parts[:1] if ":" in p):
        raise RestoreError(f"the archive holds a parent reference: {name}")
    if name == CONFIG_MEMBER:
        return
    if len(parts) == 3 and parts[0] == "skills" and parts[2] == "settings.json":
        validate_skill_id(parts[1])
        return
    raise RestoreError(f"the archive holds an unexpected file: {name}")


def restore_archive(blob: bytes) -> dict[str, Any]:
    """Unpack ``blob`` over the live files, after checking every member.

    Each target file is backed up before it is replaced, so a restore can be
    undone.
    """
    if len(blob) > MAX_UPLOAD_BYTES:
        raise RestoreError("the upload is too large")
    try:
        tar = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")  # noqa: SIM115 - closed below
    except tarfile.TarError as err:
        raise RestoreError(f"this is not a gzip tar archive: {err}") from err

    written: list[str] = []
    backups: list[str] = []
    with tar:
        members = tar.getmembers()
        if len(members) > MAX_MEMBERS:
            raise RestoreError("the archive holds too many files")
        total = sum(m.size for m in members if m.isfile())
        if total > MAX_UNPACKED_BYTES:
            raise RestoreError("the archive unpacks to too much data")
        for member in members:
            _check_member(member)
        for member in members:
            if not member.isfile():
                continue
            handle = tar.extractfile(member)
            if handle is None:  # pragma: no cover - defensive
                continue
            content = handle.read().decode("utf-8", errors="replace")
            if member.name == CONFIG_MEMBER:
                target = user_config_path()
            else:
                skill_id = Path(member.name).parts[1]
                target = skills_root() / skill_id / "settings.json"
            backup = atomic_write(target, content)
            written.append(str(target))
            if backup:
                backups.append(str(backup))
    if not written:
        raise RestoreError("the archive holds nothing to restore")
    return {"restored": written, "backups": backups}
