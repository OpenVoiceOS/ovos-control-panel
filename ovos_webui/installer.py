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
    # "media" is deliberately absent, so it broadcasts. Media plugins are
    # loaded by ovos-media, a separate service that runs no ServiceInstaller
    # and so answers no targeted topic; ovos-audio's own media path is
    # deprecated in favour of it. Addressing them to ovos-audio would put the
    # plugin in a container that no longer loads it -- the same wrong-container
    # outcome the ovos_core entries were removed for, differing only in that a
    # topic does answer. An operator whose device still uses ovos-audio's
    # legacy media path can point it there with `webui.install_services`.
    # Audio transformers run in the *listener*: ovos-dinkum-listener builds the
    # AudioTransformersService and calls find_audio_transformer_plugins.
    # ovos-audio loads dialog transformers and never mentions audio ones, so
    # addressing them there installs into a container that cannot load them --
    # and does it loudly, because ovos-audio answers the targeted topic.
    "audio_transformer": "ovos_dinkum_listener",
    "dialog_transformer": "ovos_audio",
    "stt": "ovos_dinkum_listener",
    "wake_word": "ovos_dinkum_listener",
    "vad": "ovos_dinkum_listener",
    # Everything the skills service owns -- skills, solvers, personas, pipeline
    # stages, utterance transformers, language detection and translation -- is
    # broadcast rather than targeted. ovos-core installs plugins from its own
    # skill_installer, which binds only the plain `ovos.pip.install`; it does
    # not build a ServiceInstaller the way ovos-audio, the listener, ovos-gui
    # and PHAL do, so there is no `ovos.pip.install.ovos_core` to send to and a
    # targeted install would wait out the job timeout and report that nothing
    # answered. Reported as OpenVoiceOS/ovos-core#888.
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


#: How long a broadcast *removal* waits for a service to report a problem. A
#: success cannot settle one -- see ``on_complete`` -- so this bounds the wait
#: instead. Long enough for a refusal or a fast failure, far short of a pip run.
#: What that costs: a service that fails later than this is missed, and a
#: removal whose only responder is still blocked on a contended pip lock
#: answers nothing inside the window and is reported as no answer at all, while
#: it is queued and will succeed. The panel's own single-flight lock rules out
#: self-contention, so that needs a concurrent install triggered elsewhere --
#: by voice, say. The alternative is holding the one install slot for the full
#: timeout on every removal.
REMOVE_SETTLE = 15.0

#: How long a broadcast keeps waiting after the last service to fail for a
#: reason that speaks only for its own environment. The services serialise on
#: one cross-process pip lock, so a service that has not answered has usually
#: not started, and a failure from the first to reply says nothing about the
#: one still queued -- that is why an unanswered failure cannot settle the job
#: at once. But it cannot mean waiting out ``JOB_TIMEOUT`` either. On a
#: single-container device ovos-core is the only responder, and the ordinary
#: "the install failed" path -- an unreachable constraints file, an
#: unresolvable package -- then leaves the panel holding its one install slot
#: for fifteen minutes with the answer already in hand.
#:
#: So this is an idle window, not a deadline from the first failure. Each
#: failure re-arms it, because a failure means one more service has let go of
#: the pip lock and the next one has started. An all-in-one device answers a
#: broadcast from ovos-core, ovos-audio, the listener, ovos-gui and PHAL, all
#: queued on that one lock; a single window measured from the first of them
#: would be spent by the queue rather than by the install that might still
#: succeed. Re-arming makes the figure mean what it says: a service still has
#: this long to finish once the one before it has given up, and
#: ``JOB_TIMEOUT`` remains the ceiling on the whole job.
INCONCLUSIVE_SETTLE = 300.0

#: ``ovos.pip.install.failed`` carries an ``error`` from a fixed vocabulary,
#: documented in ovos-core and ovos-utils as ``InstallError``. Three of the four
#: values are about the request or the configuration rather than one
#: environment, so they are treated as answering for every installer: a bad url
#: or an empty package list is the same request whoever receives it, and
#: ``skills.installer`` is one key per configuration. On a device split across
#: containers each has its own configuration, so a refusal from one is not
#: strictly the answer for all -- taking it as one costs a wrong error message
#: on a mixed setup, where waiting instead costs the whole job timeout on the
#: far commoner one. Only a pip failure is about a single environment, and
#: another service may still succeed, so that one settles nothing.
_CONCLUSIVE_ERRORS = frozenset({
    "pip disabled in mycroft.conf",
    "skill url validation failed",
    "no packages to install",
})

#: The one value that is specific to the environment that reported it, and so
#: the one deliberately absent from the set above. Named rather than merely
#: omitted so the test that pins this vocabulary against ``InstallError`` can
#: assert the two together are exhaustive -- a value added upstream then fails
#: here instead of silently becoming inconclusive.
_ENVIRONMENT_ERROR = "error in pip subprocess"


def _is_conclusive(error: str) -> bool:
    """Whether a failure answers for every installer, not just the one.

    An error outside the known vocabulary is treated as inconclusive: waiting
    for another service is the safe way to be wrong, since a broadcast that
    only ever gets failures still reports one when the wait runs out.
    """
    return (error or "").strip().lower() in _CONCLUSIVE_ERRORS


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
        family, service = _install_route_for(package)
        emit_type = f"{reply_base}.{service}" if service else reply_base
        with self._lock:
            if self._current is not None and self._current.state == "running":
                raise InstallerBusy("another job is still running")
            job = Job(action, package)
            self._remember(job)
            self._current = job
        thread = threading.Thread(
            target=self._run_bus,
            args=(job, reply_base, emit_type, packages, bus, service, family),
            daemon=True)
        thread.start()
        return job

    def _remember(self, job: Job) -> None:
        """Add ``job`` to the log, dropping the oldest past ``MAX_JOBS``.

        The caller holds ``self._lock``.
        """
        self._jobs[job.id] = job
        self._order.append(job.id)
        while len(self._order) > MAX_JOBS:
            self._jobs.pop(self._order.pop(0), None)

    def _run_bus(self, job: Job, reply_base: str, emit_type: str,
                 packages: list[str], bus, service: str | None,
                 family: str | None = None) -> None:
        """Ask the installer service(s) to do the pip work and wait.

        A targeted request (``service`` set) is answered by exactly one service,
        so its reply is the whole answer, success or failure.

        A broadcast is answered by every service that has an installer, and they
        do not answer together: within one container both implementations take
        the same ``ovos_pip.lock``, so their pip runs are serialised, while a
        service with ``allow_pip`` off refuses immediately without taking it.
        The first reply is therefore often from a service that was never going
        to do the work.

        Installing is answered by any success -- the package is somewhere it can
        be loaded from -- so a success settles it and a failure only counts once
        nothing succeeded. Removing asks the opposite: every environment has to
        be clean, and ``uv pip uninstall`` exits 0 for a package it never had,
        so the services that do not hold the plugin all report success at once.
        There a failure settles it and a success does not, bounded by
        ``REMOVE_SETTLE`` -- but only when it really is a broadcast. A targeted
        removal settles on its one reply and waits the ordinary timeout.

        A failure that speaks only for the environment that sent it settles
        nothing, but it does bound what is left: the deadline comes in to
        ``INCONCLUSIVE_SETTLE``. Both halves of that matter. Settling at once
        would report a failure for an install that goes on to succeed in a
        service still queued on the pip lock, and leave the panel's caches
        saying the plugin is absent; waiting out ``JOB_TIMEOUT`` would hold the
        panel's one install slot for fifteen minutes on a single-responder
        device where the answer is already in. The failure is written to the
        job log as it arrives, so the wait is never empty either way.
        """
        from ovos_bus_client.message import Message

        job.append(f"Asked {'the ' + service if service else 'every'} "
                   f"installer service: {emit_type} {' '.join(packages)}")
        done = threading.Event()
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

        removing = reply_base.endswith("uninstall")
        # Only a broadcast removal has to sit out a settle window: a targeted
        # one has a single responder and settles on its reply, so capping it
        # below JOB_TIMEOUT would abandon a slow `uv pip uninstall` -- behind a
        # contended pip lock, easily longer than REMOVE_SETTLE -- and then
        # blame the operator's `allow_pip` config for the silence.
        waiting_out_a_broadcast_removal = removing and service is None
        # One-element lists so `on_failed` can move the deadline; guarded by
        # `lock`. `hard_deadline` never moves and caps the whole job.
        deadline = [0.0]
        hard_deadline = [0.0]

        def on_complete(message):
            if not _is_ours(message):
                return
            with lock:
                results.append({"ok": True})
            if waiting_out_a_broadcast_removal:
                # A broadcast removal asks the opposite question. `uv pip
                # uninstall` exits 0 for a package it never had, so every
                # service that does not hold the plugin reports success at
                # once, while the one that does is still working -- and may yet
                # fail. Wait out the settle window and let a failure win. A
                # targeted removal has one responder, so its reply is the
                # whole answer and there is nothing to wait for.
                return
            # Installing is answered by any success: the package is now in some
            # service's environment, which is what was asked for.
            done.set()

        def on_failed(message):
            if not _is_ours(message):
                return
            error = (message.data or {}).get(
                "error", "the installer service reported a failure")
            with lock:
                results.append({"ok": False, "error": error})
            if service is not None or removing or _is_conclusive(error):
                done.set()
            else:
                with lock:
                    # Re-arm rather than only ever shorten: each failure means
                    # another service has released the pip lock, so the one
                    # behind it gets the full window. Never past the hard
                    # deadline, which is the ceiling on the whole job.
                    deadline[0] = min(hard_deadline[0],
                                      time.monotonic() + INCONCLUSIVE_SETTLE)
                # The page follows these lines live, so say what happened rather
                # than leave the reader watching a wait with nothing in it.
                job.append(f"One installer could not do it ({error}); "
                           "waiting in case another one can.")

        try:
            # Register inside the try so a failure between the two registrations
            # still hits the finally and cannot leak a handler on the shared bus.
            # Targeted requests still reply on the BASE topic, not a targeted one.
            deadline[0] = hard_deadline[0] = time.monotonic() + (
                REMOVE_SETTLE if waiting_out_a_broadcast_removal
                else JOB_TIMEOUT)
            bus.on(reply_base + ".complete", on_complete)
            bus.on(reply_base + ".failed", on_failed)
            bus.emit(Message(emit_type, {"packages": packages},
                             {"source": "ovos-webui", "webui_job": nonce}))
            # Waited in slices because `on_failed` can bring the deadline
            # forward while this is blocked, and an `Event.wait` already under
            # way cannot be shortened.
            while True:
                with lock:
                    remaining = deadline[0] - time.monotonic()
                if remaining <= 0:
                    break
                if done.wait(min(remaining, 1.0)):
                    break
            with lock:
                answered = list(results)
            failures = [r for r in answered if not r.get("ok")]
            if waiting_out_a_broadcast_removal and answered and not failures:
                # Nothing failed. That is as much as can be known: a failure
                # arriving later is missed, and on ovos-core before 3.0.10a3 a
                # removal it could not do is answered with silence rather than
                # a failure -- its handlers did not catch the RuntimeError its
                # own pip wrapper raises on a non-zero exit. Say what was
                # observed instead of claiming the plugin is gone.
                #
                # Keyed on the failures actually in hand. Keying it on whether
                # the wait was cut short instead reads a snapshot taken before
                # this one, and a failure landing between the two would print
                # this reassurance directly above the failure it reassures
                # about. And only when something answered at all, or it would
                # reassure the reader one line above telling them nobody
                # replied.
                job.append("No installer reported a problem removing it.")
            if not answered:
                # Silence has two causes and the panel cannot tell them
                # apart, so it must not pick one. Either no service is
                # listening, or one took the job and never answered. On
                # ovos-core before 3.0.10a3 the commonest install failure on
                # the commonest deployment is answered with nothing: its
                # handlers did not catch the RuntimeError its pip wrapper
                # raises on a non-zero exit. Naming `allow_pip` alone sent
                # readers to check a setting that was already on.
                if service is None:
                    job.append(
                        "The installer never answered. Either no OVOS service "
                        "is listening for installs, or one took this on and "
                        "failed without saying so. Check that OVOS is running "
                        "with 'allow_pip' enabled, and check the service logs "
                        "for a pip error.")
                else:
                    # A targeted request has a third cause the broadcast one
                    # does not, and it is the likeliest: only the 2026-08
                    # alphas answer the per-service topics at all.
                    # The remedy has to name the family, not the service:
                    # adding a `webui.install_services` block turns targeting
                    # on for every family, and the ones the operator did not
                    # name are addressed from the built-in table -- so there is
                    # nothing of theirs to remove. Setting the family to
                    # `broadcast` is what puts it back on the broadcast topic.
                    job.append(
                        f"The {service} installer never answered. Either that "
                        "service is too old to accept installs addressed to "
                        "it, or it is not running, or it took this on and "
                        "failed without saying so. Set "
                        f"'{family}' to 'broadcast' in "
                        "'webui.install_services' to have every service hear "
                        "it instead, and check the service logs for a pip "
                        "error.")
                job.state = "error"
                job.returncode = -1
                return
            # Removing wants every environment clean, so one failure is the
            # answer. Installing wants the package in one, so one success is --
            # and a failure only counts when nothing succeeded.
            went_wrong = bool(failures) if removing else not any(
                r.get("ok") for r in answered)
            if went_wrong:
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
    return _install_route_for(package)[1]


def _install_route_for(package: str) -> tuple[str | None, str | None]:
    """The ``webui.install_services`` key for ``package``, and its service.

    The key matters as much as the service: an admin PHAL plugin routes by
    ``phal_admin`` while the family the page shows for it is ``phal``, so a
    message that told the reader to change "this plugin's family" would send
    them to a key that does nothing.
    """
    from ovos_webui import configio
    from ovos_webui.pypi import classify

    kind = classify(package)
    if not kind:
        return None, None
    # A PHAL plugin that needs root belongs to the separate admin process, so
    # it routes by the "phal_admin" key rather than "phal".
    if kind == "phal" and package.lower() in _admin_phal_packages():
        kind = "phal_admin"
    # Broadcast by default. ovos-audio, ovos-dinkum-listener, ovos-gui and
    # PHAL do each run a ServiceInstaller and answer their per-service
    # `ovos.pip.install.<name>` topic, but only since the 2026-08 alphas
    # (ovos-audio 2.2.0a1, ovos-dinkum-listener 0.9.0a1, ovos-gui 1.5.0a1,
    # ovos-PHAL 0.3.0a1). A device on anything older subscribes to none of
    # them, and a targeted request there hangs until JOB_TIMEOUT. Targeting is
    # therefore opt-in: the operator adds a `webui.install_services` block to
    # say their services are new enough, and routing then follows
    # DEFAULT_INSTALL_SERVICE merged with their overrides.
    overrides = configio.user_or_merged(["webui", "install_services"])
    if not isinstance(overrides, dict):
        return kind, None
    mapping = dict(DEFAULT_INSTALL_SERVICE)
    # Only string overrides are usable as a topic suffix; a non-string (an
    # operator typo like {"tts": 123}) falls back to the default for that kind.
    mapping.update({k: v for k, v in overrides.items() if isinstance(v, str)})
    service = mapping.get(kind)
    # "*" alongside "broadcast" because an operator writing a wildcard by
    # analogy with topic patterns should get what they meant rather than a
    # request addressed to a service literally named "*".
    if not service or service in ("broadcast", "*"):
        return kind, None
    return kind, service


#: The service uses one installer.
INSTALLER = Installer()
