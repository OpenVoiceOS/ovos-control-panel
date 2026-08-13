"""Install and remove OVOS plugins over the message bus.

The web-ui never runs pip itself. It asks the device's installer service
(``ovos.pip.install`` / ``ovos.pip.uninstall``, handled by ``ovos-core``) to do
the work in the process that owns the environment — so a plugin lands where the
service that needs it imports from, even in a split or containerised
deployment. With no connected device there is nothing to delegate to and the
action fails cleanly, rather than touching the web-ui's own environment.

The rules that keep it safe:

- The package name must match a strict pattern **and** belong to a known OVOS
  family. A version pin, an extras bracket, an index URL, a path or a VCS URL
  never travels, because none of them match the pattern. Only that validated
  name (or ``name==<version>`` for an upgrade, the version from a trusted PyPI
  lookup) is put in the bus message.
- The name must exist on PyPI before an install is requested.
- A token is always required, whatever the bind address is.

One job runs at a time. Its progress is kept in memory and streamed to the page.
"""
from __future__ import annotations

import re
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

#: After the first reply to a *broadcast* install, wait this long for other
#: services to also answer before deciding success/failure.
BROADCAST_GRACE = 2.0

#: Which service's environment each plugin family loads in — so an install is
#: targeted at ``ovos.pip.install.<service_name>`` and lands in the right place.
#: The service names follow ovos_utils.skill_installer.ServiceInstaller's own
#: documented convention: the service's module/process name with underscores
#: (``ovos_audio``, ``ovos_gui``, ``ovos_core``, …), which is exactly the
#: ``service_name`` each service passes when it registers its installer. An
#: operator can override this per family with the config
#: ``webui.install_services`` (a value of "" or "broadcast" reverts to the
#: broadcast topic). A family absent here is broadcast.
DEFAULT_INSTALL_SERVICE = {
    "tts": "ovos_audio",
    "media": "ovos_audio",
    "audio_transformer": "ovos_audio",
    "dialog_transformer": "ovos_audio",
    "stt": "ovos_dinkum_listener",
    "wake_word": "ovos_dinkum_listener",
    "vad": "ovos_dinkum_listener",
    "utterance_transformer": "ovos_core",
    "pipeline": "ovos_core",
    "skill": "ovos_core",
    "solver": "ovos_core",
    "persona": "ovos_core",
    "lang_detect": "ovos_core",
    "translate": "ovos_core",
    "gui": "ovos_gui",
    "phal": "ovos_PHAL",
    # The admin PHAL is a *separate root process* (ovos_PHAL/admin.py,
    # skill_id "PHAL.admin"). Admin plugins — wifi setup, anything needing
    # root — install into its environment, not the plain PHAL one. Which PHAL
    # packages are "admin" is taken from phal.CAPABILITIES (admin=True).
    "phal_admin": "ovos_PHAL_admin",
}


def _admin_phal_packages() -> set[str]:
    """Lower-cased PHAL package names that belong to the admin (root) service."""
    from ovos_webui.phal import CAPABILITIES

    out: set[str] = set()
    for spec in CAPABILITIES.values():
        if spec.get("admin"):
            out.update(p.lower() for p in spec.get("plugins", []))
    return out


class UnsafePackageName(ValueError):
    """Raised when a package name is not a plain OVOS package name."""


class InstallerBusy(RuntimeError):
    """Raised when a job is already running."""


class InstallerUnavailable(RuntimeError):
    """Raised when there is no connected device to run the install on."""


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
    # Reject any surrounding/embedded whitespace or control characters up front
    # (a trailing newline, a leading space) — these never belong in a package
    # name and would otherwise ride into the bus message and the device log.
    if name != name.strip() or any(c.isspace() or ord(c) < 0x20 for c in name):
        raise UnsafePackageName("the package name contains whitespace or control characters")
    # fullmatch, not match: ``$`` matches before a trailing newline and ``match``
    # does not anchor the end, so ``PACKAGE_RE.match("ovos-x\n")`` succeeds while
    # fullmatch correctly refuses it.
    if not PACKAGE_RE.fullmatch(name):
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
    # Installs are done ONLY over the message bus, through the shared installer
    # service ``ovos_utils.skill_installer.ServiceInstaller`` (and ovos-core's
    # older SkillsStore). Running pip in the web-ui process would land the
    # package in the wrong place in a split or containerised deployment, so it
    # is not done at all: with no device to delegate to, an install fails
    # cleanly rather than touching the local env.
    #
    # Each service that runs an installer answers a broadcast
    # ``ovos.pip.install`` *and* a targeted ``ovos.pip.install.<service_name>``.
    # A plugin is routed to the service whose environment actually loads it
    # (a voice → the audio service, a listener plugin → the listener, …) so it
    # installs in the right container; the broadcast topic is the fallback for a
    # kind with no known home. Either way the reply comes back on the base
    # ``ovos.pip.install.complete`` / ``.failed`` topics.
    @staticmethod
    def _channel_spec(package: str) -> str:
        """Return ``package==<latest-for-channel>``, or the bare name offline.

        The version comes from a trusted PyPI lookup, never the request. Pinning
        the channel's latest is what makes the ``alpha`` channel install a
        pre-release — the installer service otherwise does a plain install that
        pip resolves to the newest *stable* regardless of the channel setting.
        """
        try:
            from ovos_webui.updates import latest_versions, release_channel
            latest = latest_versions(package).get(release_channel())
            if latest:
                return f"{package}=={latest}"
        except Exception:  # noqa: BLE001 - offline: ask for a plain install
            pass
        return package

    def install(self, package: str, check_pypi: bool = True, bus=None) -> Job:
        """Ask the right service to install a plugin. Name checked, then PyPI.

        The requested channel is honoured (an ``alpha``-channel install pulls a
        pre-release), the same as upgrade — otherwise switching to ``alpha`` and
        installing a new plugin would silently get the stable build.
        """
        validate_package_name(package)
        if check_pypi:
            from ovos_webui.pypi import details
            details(package)  # raises LookupError when PyPI does not have it
        return self._start_bus("install", package, "ovos.pip.install",
                               bus, [self._channel_spec(package)])

    def upgrade(self, package: str, bus=None) -> Job:
        """Ask the right service to upgrade a plugin to the channel's latest."""
        validate_package_name(package)
        return self._start_bus("upgrade", package, "ovos.pip.install",
                               bus, [self._channel_spec(package)])

    def uninstall(self, package: str, bus=None) -> Job:
        """Ask the right service to remove a plugin."""
        validate_package_name(package)
        return self._start_bus("uninstall", package, "ovos.pip.uninstall",
                               bus, [package])

    def _start_bus(self, action: str, package: str, reply_base: str,
                   bus, packages: list[str]) -> Job:
        from ovos_webui import buswait

        if bus is None or not buswait.is_connected(bus):
            raise InstallerUnavailable(
                "installs run on the device, over the message bus, and no "
                "device is connected. Start OVOS (with 'allow_pip' enabled) "
                "and try again.")
        service = _install_service_for(package)
        emit_type = f"{reply_base}.{service}" if service else reply_base
        with self._lock:
            if self._current is not None and self._current.state == "running":
                raise InstallerBusy("another job is still running")
            job = Job(action, package)
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > MAX_JOBS:
                self._jobs.pop(self._order.pop(0), None)
            self._current = job
        thread = threading.Thread(
            target=self._run_bus,
            args=(job, reply_base, emit_type, packages, bus, service),
            daemon=True)
        thread.start()
        return job

    def _run_bus(self, job: Job, reply_base: str, emit_type: str,
                 packages: list[str], bus, service: str | None) -> None:
        """Ask the installer service(s) to do the pip work and wait.

        A targeted request (``service`` set) is answered by exactly one service,
        so the first reply is the whole answer. A broadcast request may be
        answered by several services; collect a short grace window and fail if
        any of them failed.
        """
        from ovos_bus_client.message import Message

        job.append(f"Asked {'the ' + service if service else 'every'} "
                   f"installer service: {emit_type} {' '.join(packages)}")
        first = threading.Event()
        results: list[dict[str, Any]] = []
        lock = threading.Lock()
        # Every job listens on the SAME base reply topics, so a reply must be
        # matched to its job or a late/duplicate answer from a previous, already
        # finished job would complete (or fail) the wrong one. The service copies
        # the request context into its reply (message.reply), so a per-job nonce
        # round-trips and lets us ignore replies that are not ours.
        nonce = job.id

        def _is_ours(message) -> bool:
            return (getattr(message, "context", None) or {}).get("webui_job") == nonce

        def on_complete(message):
            if not _is_ours(message):
                return
            with lock:
                results.append({"ok": True})
            first.set()

        def on_failed(message):
            if not _is_ours(message):
                return
            with lock:
                results.append({"ok": False, "error": (message.data or {}).get(
                    "error", "the installer service reported a failure")})
            first.set()

        try:
            # Register inside the try so a failure between the two registrations
            # still hits the finally and cannot leak a handler on the shared bus.
            # Targeted requests still reply on the BASE topic, not a targeted one.
            bus.on(reply_base + ".complete", on_complete)
            bus.on(reply_base + ".failed", on_failed)
            bus.emit(Message(emit_type, {"packages": packages},
                             {"source": "ovos-webui", "webui_job": nonce}))
            if not first.wait(JOB_TIMEOUT):
                job.append("No installer service answered. Is OVOS running with "
                           "'allow_pip' enabled in its config?")
                job.state = "error"
                job.returncode = -1
                return
            if service is None:
                # Broadcast: give slower services a moment to also answer.
                time.sleep(BROADCAST_GRACE)
            with lock:
                failures = [r for r in results if not r.get("ok")]
            if failures:
                job.append("Failed: " + str(failures[0].get("error", "")))
                job.state = "error"
                job.returncode = 1
            else:
                job.append("")
                job.append("Done. Restart the OVOS services to load the change.")
                job.state = "done"
                job.returncode = 0
                _clear_plugin_caches()
        except Exception as err:  # noqa: BLE001 - never leave the job "running"
            job.append(f"The install request failed: {err}")
            job.state = "error"
            job.returncode = -1
        finally:
            try:
                bus.remove(reply_base + ".complete", on_complete)
                bus.remove(reply_base + ".failed", on_failed)
            except Exception:  # noqa: BLE001 # pragma: no cover
                pass
            # Belt-and-suspenders: an install must never stay "running" and
            # wedge the single-flight lock, whatever path we left by.
            if job.state == "running":
                job.state = "error"
                job.returncode = -1
            job.finished = time.time()
        LOG.info(f"bus {job.action} {job.package} finished with {job.returncode}")

def _clear_plugin_caches() -> None:
    """Make the new entrypoints visible to this process."""
    # Drop pypi.installed_versions()'s TTL snapshot FIRST and unconditionally,
    # or a just-installed package reads as "not installed" for up to 15s. This
    # must not depend on the importlib refresh below, which can raise on some
    # Python versions and would otherwise skip the invalidation.
    from ovos_webui import pypi
    pypi.invalidate_installed_cache()
    try:
        import importlib
        import importlib.metadata
        importlib.invalidate_caches()
        if hasattr(importlib.metadata, "MetadataPathFinder"):
            importlib.metadata.MetadataPathFinder.invalidate_caches()
    except Exception as err:  # noqa: BLE001 - never fatal
        LOG.debug(f"could not refresh the package caches: {err}")


def _install_service_for(package: str) -> str | None:
    """Return the service to target for ``package``, or None for broadcast."""
    from ovos_webui import configio
    from ovos_webui.pypi import classify

    kind = classify(package)
    if not kind:
        return None
    # A PHAL plugin that needs root belongs to the separate admin process, so
    # it routes by the "phal_admin" key rather than "phal".
    if kind == "phal" and package.lower() in _admin_phal_packages():
        kind = "phal_admin"
    # Broadcast by default. Out of the box no OVOS service subscribes to the
    # per-service `ovos.pip.install.<name>` topic — only ovos-core answers the
    # broadcast `ovos.pip.install`, and it installs any plugin family. Targeting
    # a service that runs no ServiceInstaller would hang the job until
    # JOB_TIMEOUT. So target ONLY when the operator has opted in by adding a
    # `webui.install_services` block (i.e. they run a ServiceInstaller per
    # service); then route by DEFAULT_INSTALL_SERVICE merged with their overrides.
    overrides = configio.user_or_merged(["webui", "install_services"])
    if not isinstance(overrides, dict):
        return None
    mapping = dict(DEFAULT_INSTALL_SERVICE)
    # Only string overrides are usable as a topic suffix; a non-string (an
    # operator typo like {"tts": 123}) falls back to the default for that kind.
    mapping.update({k: v for k, v in overrides.items() if isinstance(v, str)})
    service = mapping.get(kind)
    if not service or service in ("broadcast", "*"):
        return None
    return service


#: The service uses one installer.
INSTALLER = Installer()
