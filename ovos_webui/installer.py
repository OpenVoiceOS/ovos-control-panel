"""Install and remove OVOS plugins with pip.

This is the only part of ovos-webui that starts a process. Everything else
works on files and on the message bus. The rules that keep it safe:

- The command is built as an argument vector. There is no shell, so there is
  nothing for a `;` or a `|` in a name to break out of.
- The package name must match a strict pattern **and** belong to a known OVOS
  family. A version pin, an extras bracket, an index URL, a path or a VCS URL
  never reaches pip, because none of them match the pattern.
- The name must exist on PyPI before an install starts.
- The interpreter is the one this service runs in, so a plugin lands in the
  environment that OVOS actually imports from.
- A token is always required, whatever the bind address is.

One job runs at a time. Its output is kept in memory and streamed to the page.
"""
from __future__ import annotations

import re
import subprocess  # noqa: S404 - argument vectors only, never a shell
import sys
import threading
import time
import uuid
from typing import Any

from ovos_utils.log import LOG

#: A package name and nothing else. No version, no extras, no path, no URL.
#: Anchored, so a trailing `; rm -rf /` cannot match.
PACKAGE_RE = re.compile(r"^ovos-[a-z0-9]([a-z0-9-]{0,78}[a-z0-9])?$", re.IGNORECASE)

#: Give up on a pip run after this long.
JOB_TIMEOUT = 900

#: Keep this many output lines per job.
MAX_LOG_LINES = 2000

#: Keep this many finished jobs.
MAX_JOBS = 20


class UnsafePackageName(ValueError):
    """Raised when a package name is not a plain OVOS package name."""


class InstallerBusy(RuntimeError):
    """Raised when a job is already running."""


def validate_package_name(name: str) -> str:
    """Return ``name`` when it is a plain OVOS package name, else raise.

    This runs before anything else. It is the reason a shell is not needed and
    a shell would not help an attacker anyway.
    """
    from ovos_webui.pypi import classify

    if not isinstance(name, str) or not name:
        raise UnsafePackageName("the package name is empty")
    if len(name) > 100:
        raise UnsafePackageName("the package name is too long")
    if not PACKAGE_RE.match(name):
        raise UnsafePackageName(
            "the package name must be a plain OVOS package name, "
            "with no version, extras, path or URL")
    if classify(name) is None:
        raise UnsafePackageName(
            f"'{name}' is not one of the OVOS plugin families this page installs")
    return name


class Job:
    """One pip run."""

    def __init__(self, action: str, package: str):
        self.id = uuid.uuid4().hex
        self.action = action
        self.package = package
        self.started = time.time()
        self.finished: float | None = None
        self.returncode: int | None = None
        self.state = "running"
        self.lines: list[str] = []
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        with self._lock:
            self.lines.append(line.rstrip("\n"))
            if len(self.lines) > MAX_LOG_LINES:
                del self.lines[:len(self.lines) - MAX_LOG_LINES]

    def as_dict(self, since: int = 0) -> dict[str, Any]:
        with self._lock:
            lines = self.lines[since:]
            total = len(self.lines)
        return {
            "id": self.id,
            "action": self.action,
            "package": self.package,
            "state": self.state,
            "returncode": self.returncode,
            "started": self.started,
            "finished": self.finished,
            "lines": lines,
            "next": total,
            "restart_hint": self.state == "done" and self.returncode == 0,
        }


class Installer:
    """Runs one pip job at a time and keeps the output of the last few."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._current: Job | None = None
        self._lock = threading.Lock()

    # ── queries ──────────────────────────────────────────────────────────────
    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def current(self) -> Job | None:
        job = self._current
        return job if job is not None and job.state == "running" else None

    def recent(self) -> list[dict[str, Any]]:
        return [self._jobs[j].as_dict(since=10 ** 9) for j in reversed(self._order)]

    # ── actions ──────────────────────────────────────────────────────────────
    def install(self, package: str, check_pypi: bool = True) -> Job:
        """Start an install. The name is checked, then looked up on PyPI."""
        validate_package_name(package)
        if check_pypi:
            from ovos_webui.pypi import details
            details(package)  # raises LookupError when PyPI does not have it
        return self._start("install", package, [
            sys.executable, "-m", "pip", "install", "--no-input",
            "--disable-pip-version-check", *_channel_flags(), "--", package,
        ])

    def upgrade(self, package: str) -> Job:
        """Start an upgrade of a package that is already installed.

        On the ``alpha`` channel pip may pick a pre-release; on ``stable`` it
        only moves between releases. The flag is decided here from the
        configuration — nothing from the request reaches the argument vector
        except the validated package name.
        """
        validate_package_name(package)
        from ovos_webui.pypi import installed_versions
        if package.lower() not in installed_versions():
            raise LookupError(f"'{package}' is not installed")
        return self._start("upgrade", package, [
            sys.executable, "-m", "pip", "install", "--no-input",
            "--disable-pip-version-check", "--upgrade", *_channel_flags(),
            "--", package,
        ])

    def uninstall(self, package: str) -> Job:
        """Start an uninstall. The package must be installed already."""
        validate_package_name(package)
        from ovos_webui.pypi import installed_versions
        if package.lower() not in installed_versions():
            raise LookupError(f"'{package}' is not installed")
        return self._start("uninstall", package, [
            sys.executable, "-m", "pip", "uninstall", "-y", "--", package,
        ])

    def _start(self, action: str, package: str, argv: list[str]) -> Job:
        with self._lock:
            if self._current is not None and self._current.state == "running":
                raise InstallerBusy("another job is still running")
            job = Job(action, package)
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > MAX_JOBS:
                self._jobs.pop(self._order.pop(0), None)
            self._current = job
        thread = threading.Thread(target=self._run, args=(job, argv), daemon=True)
        thread.start()
        return job

    def _run(self, job: Job, argv: list[str]) -> None:
        job.append(f"$ {' '.join(argv)}")
        try:
            # No shell. argv is a list, so the name is one argument whatever
            # characters it holds — and the name was checked before we got here.
            process = subprocess.Popen(  # noqa: S603 - argument vector, no shell
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                shell=False,
            )
        except OSError as err:
            job.append(f"could not start pip: {err}")
            job.state = "error"
            job.returncode = -1
            job.finished = time.time()
            return

        def reader():
            assert process.stdout is not None
            for line in process.stdout:
                job.append(line)

        pump = threading.Thread(target=reader, daemon=True)
        pump.start()
        try:
            process.wait(timeout=JOB_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            job.append(f"the job took longer than {JOB_TIMEOUT} seconds and was stopped")
        pump.join(timeout=5)
        job.returncode = process.returncode
        job.state = "done" if process.returncode == 0 else "error"
        job.finished = time.time()
        if job.state == "done":
            job.append("")
            job.append("Finished. Restart the OVOS services to load the change:")
            job.append("  systemctl --user restart ovos-skills ovos-audio")
            _clear_plugin_caches()
        LOG.info(f"pip {job.action} {job.package} finished with {job.returncode}")


def _channel_flags() -> list[str]:
    """Extra pip flags for the configured release channel."""
    from ovos_webui.updates import release_channel

    return ["--pre"] if release_channel() == "alpha" else []


def _clear_plugin_caches() -> None:
    """Make the new entrypoints visible to this process."""
    try:
        import importlib
        import importlib.metadata
        importlib.invalidate_caches()
        if hasattr(importlib.metadata, "MetadataPathFinder"):
            importlib.metadata.MetadataPathFinder.invalidate_caches()
    except Exception as err:  # noqa: BLE001 - never fatal
        LOG.debug(f"could not refresh the package caches: {err}")


#: The service uses one installer.
INSTALLER = Installer()
