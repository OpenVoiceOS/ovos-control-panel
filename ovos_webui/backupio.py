"""Make and restore a backup of the user configuration and skill settings.

The archive holds two things: the user layer of ``mycroft.conf`` and every
``settings.json`` under the skill settings directory. Restore refuses any
archive member that would write outside those two places, so a crafted
archive cannot reach the rest of the file system.
"""
from __future__ import annotations

import io
import json
import tarfile
import threading
from pathlib import Path
from typing import Any

#: Only one restore may run at a time. A restore commits many files one by one;
#: two overlapping restores would otherwise interleave at file granularity and
#: leave a mix of both archives on disk.
_RESTORE_LOCK = threading.Lock()

from ovos_webui.configio import user_config_path
from ovos_webui.fsutils import (
    MAX_UPLOAD_BYTES,
    UnsafeIdentifier,
    commit_staged,
    stage_file,
    timestamp,
    validate_skill_id,
)
from ovos_webui.skillsio import SkillSettingsError, settings_path, skills_root

CONFIG_MEMBER = "config/mycroft.conf"
SKILLS_PREFIX = "skills/"

#: Refuse an archive that unpacks to more than this. It guards against a
#: small archive that expands to fill the disk.
MAX_UNPACKED_BYTES = 64 * 1024 * 1024

#: Refuse an archive with more members than this.
MAX_MEMBERS = 5000

#: Refuse a single member larger than this. A ``mycroft.conf`` or a skill's
#: ``settings.json`` is a few kilobytes; a megabyte is already generous. This
#: stops one member that is under the whole-archive limit but still large
#: enough that decoding and ``json.loads`` on it would exhaust the memory of a
#: small device.
MAX_MEMBER_BYTES = 1024 * 1024


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


def _iter_members(tar: tarfile.TarFile):
    """Yield members one at a time, counting as we go.

    ``getmembers()`` parses the whole archive first and keeps every header in
    memory, so a small archive with a huge number of members costs a lot of
    memory before any limit is applied. Iterating the file object reads one
    header at a time, so the count and the size limits bite immediately.
    """
    total = 0
    for count, member in enumerate(tar, start=1):
        if count > MAX_MEMBERS:
            raise RestoreError("the archive holds too many files")
        if member.isfile():
            if member.size > MAX_MEMBER_BYTES:
                raise RestoreError(f"{member.name} is too large to be a "
                                   "settings file")
            total += member.size
            if total > MAX_UNPACKED_BYTES:
                raise RestoreError("the archive unpacks to too much data")
        yield member


def _validate_payload(name: str, raw: bytes) -> str:
    """Return the text of a member, after checking it is what it claims to be.

    A restore replaces the live configuration. Writing bytes that do not decode,
    or JSON that does not parse, would leave the device with a file no service
    can read, and the page would still answer 200.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as err:
        raise RestoreError(f"{name} is not valid UTF-8 text") from err
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as err:
        raise RestoreError(f"{name} is not valid JSON: {err}") from err
    if not isinstance(parsed, dict):
        raise RestoreError(f"{name} must hold a mapping")
    return text


def restore_archive(blob: bytes) -> dict[str, Any]:
    """Unpack ``blob`` over the live files, serialized so two restores never mix."""
    with _RESTORE_LOCK:
        return _restore_archive(blob)


def _restore_archive(blob: bytes) -> dict[str, Any]:
    """Unpack ``blob`` over the live files, after checking every member.

    The work happens in three stages, so a failure never leaves the device with
    half of a restore:

    1. read and check every member, in memory;
    2. write each new file beside its target, as a temporary file;
    3. back up the live file and rename the temporary one over it.

    Only the last stage touches a live file, and by then everything has been
    read, decoded and parsed. A disk error in the middle of stage 3 is reported
    and the files that were already replaced are named in the error.
    """
    if len(blob) > MAX_UPLOAD_BYTES:
        raise RestoreError("the upload is too large")
    try:
        tar = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")  # noqa: SIM115 - closed below
    except tarfile.TarError as err:
        raise RestoreError(f"this is not a gzip tar archive: {err}") from err

    # ── stage 1: read and check everything ───────────────────────────────────
    staged: list[tuple[Path, str, Path]] = []
    try:
        with tar:
            for member in _iter_members(tar):
                _check_member(member)
                if not member.isfile():
                    continue
                handle = tar.extractfile(member)
                if handle is None:  # pragma: no cover - defensive
                    continue
                # Read against the per-member cap, not the whole-archive one:
                # the header size was already checked, but a header can lie, so
                # the read itself is bounded too.
                raw = handle.read(MAX_MEMBER_BYTES + 1)
                if len(raw) > MAX_MEMBER_BYTES:
                    raise RestoreError(f"{member.name} is too large to be a "
                                       "settings file")
                text = _validate_payload(member.name, raw)
                if member.name == CONFIG_MEMBER:
                    target = user_config_path()
                    root = user_config_path().parent
                else:
                    # Build the path with the same function the skill settings
                    # page uses. It validates the id and checks that the result
                    # really sits inside the skills directory, so a skill
                    # directory that is a link to somewhere else is refused
                    # here rather than followed.
                    skill_id = Path(member.name).parts[1]
                    try:
                        target = settings_path(skill_id)
                    except (UnsafeIdentifier, SkillSettingsError) as err:
                        raise RestoreError(
                            f"{member.name} cannot be restored: {err}") from err
                    root = skills_root()
                staged.append((target, text, root))
    except tarfile.TarError as err:
        raise RestoreError(f"the archive could not be read: {err}") from err

    if not staged:
        raise RestoreError("the archive holds nothing to restore")

    # ── stage 2: write every new file beside its target ──────────────────────
    temporaries: list[tuple[Path, Path, Path]] = []
    try:
        for target, text, root in staged:
            temporaries.append((target, stage_file(target, text, within=root), root))
    except UnsafeIdentifier as err:
        for _, tmp, _root in temporaries:
            tmp.unlink(missing_ok=True)
        raise RestoreError(str(err)) from err
    except OSError as err:
        for _, tmp, _root in temporaries:
            tmp.unlink(missing_ok=True)
        raise RestoreError(f"the restore could not be prepared: {err}") from err

    # ── stage 3: back up, then rename each one into place ────────────────────
    written: list[str] = []
    backups: list[str] = []
    try:
        for target, tmp, root in temporaries:
            backup = commit_staged(target, tmp, within=root)
            written.append(str(target))
            if backup:
                backups.append(str(backup))
    except UnsafeIdentifier as err:
        for _, tmp, _root in temporaries:
            tmp.unlink(missing_ok=True)
        raise RestoreError(str(err)) from err
    except OSError as err:
        for _, tmp, _root in temporaries:
            tmp.unlink(missing_ok=True)
        raise RestoreError(
            f"the restore stopped part way: {err}. "
            f"These files were replaced: {', '.join(written) or 'none'}. "
            f"The files they replaced are in the backup directories.") from err
    return {"restored": written, "backups": backups}
