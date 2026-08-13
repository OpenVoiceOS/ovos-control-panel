"""The ovos-webui FastAPI service.

Every route lives on one of three routers, and each router carries its own
checks:

- ``public`` — the few things that must work before a sign in.
- ``pages``  — the HTML and the assets. Signed in.
- ``api``    — everything that reads or writes. Signed in.

A route added to a router inherits that router's checks, so a route cannot be
published without them by forgetting an argument.
"""
from __future__ import annotations

import argparse
import asyncio
import time
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from ovos_utils.log import LOG
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ovos_webui import (backupio, configio, health, installer, meta, personas,
                        pypi, recommends, servers, skillsio, translate)
from ovos_webui.auth import (
    COOKIE_NAME,
    AuthPolicy,
    check_csrf,
    check_host,
    policy_from_config,
)
from ovos_webui.fsutils import (MAX_PAYLOAD_BYTES, MAX_UPLOAD_BYTES,
                                UnsafeIdentifier,
                                validate_skill_id as fsutils_validate_skill_id)
from ovos_webui.limits import BodyLimitMiddleware
from ovos_webui.version import __version__

#: Starlette renamed this constant. Keep working with both names.
TOO_LARGE = getattr(status, "HTTP_413_CONTENT_TOO_LARGE",
                    getattr(status, "HTTP_413_REQUEST_ENTITY_TOO_LARGE", 413))

STATIC_DIR = Path(__file__).parent / "static"

#: A quiet spell at least this long resets the failed-login count (module level
#: so tests can shorten it).
THROTTLE_DECAY = 30.0
PAGES = {
    "/": "index.html",
    "/config": "config.html",
    "/skills": "skills.html",
    "/backup": "backup.html",
    "/about": "about.html",
    "/plugins": "plugins.html",
    "/personas": "personas.html",
    "/translate": "translate.html",
    "/sound": "sound.html",
    "/tryit": "tryit.html",
    "/setup": "setup.html",
    "/controls": "controls.html",
    "/abilities": "abilities.html",
    "/network": "network.html",
    "/media": "media.html",
    "/mark1": "mark1.html",
    "/servers": "servers.html",
}

#: The bus messages a browser may ask the device to act on. Each one is an
#: existing message type that ovos-PHAL-plugin-system already handles; when
#: that plugin is absent the message is simply ignored by the stack.
SYSTEM_ACTIONS = {
    "reboot": "system.reboot",
    "shutdown": "system.shutdown",
    "restart_services": "system.mycroft.service.restart",
}

#: The endpoints that take an upload, and so have a larger body limit.
UPLOAD_PATHS = frozenset({"/api/restore"})


class ConfigBody(BaseModel):
    text: str = Field(..., description="the whole user layer, as JSON or YAML")
    format: str = Field("json", pattern="^(json|yaml)$")


class QuickBody(BaseModel):
    values: dict[str, Any]


class SettingsBody(BaseModel):
    settings: dict[str, Any]


class LoginBody(BaseModel):
    token: str = Field(..., max_length=512)


class PackageBody(BaseModel):
    package: str = Field(..., max_length=100)


class PersonaBody(BaseModel):
    persona: dict[str, Any]


class PersonaTestBody(BaseModel):
    question: str = Field(..., max_length=2000)


class TranslateBody(BaseModel):
    lines: list[str]
    source: str = Field(..., max_length=16)
    target: str = Field(..., max_length=16)
    plugin: str | None = Field(None, max_length=128)


class UtteranceBody(BaseModel):
    text: str = Field(max_length=500)


class ChannelBody(BaseModel):
    channel: str = Field(max_length=16)


class ServersBody(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=servers.MAX_URLS)


class BackupIdBody(BaseModel):
    id: str = Field(max_length=512)


class EnabledBody(BaseModel):
    enabled: bool


class GgwaveListenBody(BaseModel):
    enabled: bool
    # 0 is a real, meaningful value here ("never auto-disable"), so the floor
    # is 0, not 1 — only a negative timeout is rejected. Cap at 24h so an
    # unbounded value cannot ride onto the bus.
    timeout: int | None = Field(None, ge=0, le=86400, strict=True)


class VolumeBody(BaseModel):
    percent: int = Field(ge=0, le=100, strict=True)


class MediaVolumeBody(BaseModel):
    percent: int = Field(ge=0, le=100, strict=True)


class MuteBody(BaseModel):
    muted: bool


class TokenBody(BaseModel):
    current: str | None = Field(None, max_length=512)
    new: str = Field(max_length=512)


class OverrideBody(BaseModel):
    lines: list[str]


class WifiConnectBody(BaseModel):
    ssid: str = Field(..., max_length=64)
    password: str = Field("", max_length=128)
    security: str = Field("", max_length=64)


class WifiSsidBody(BaseModel):
    ssid: str = Field(..., max_length=64)


class Mark1DisplayBody(BaseModel):
    # Bound both dimensions so a huge nested body is rejected during validation
    # rather than fully materialized (the faceplate is exactly 8 rows x 32 cols;
    # mark1._valid_grid re-checks the exact shape).
    grid: Annotated[list[Annotated[list[int], Field(max_length=32)]],
                    Field(max_length=8)]
    x: int = Field(0, ge=-64, le=64)
    y: int = Field(0, ge=-64, le=64)
    clear: bool = True


class Mark1TextBody(BaseModel):
    text: str = Field("", max_length=500)


class Mark1AnimBody(BaseModel):
    kind: str = Field(..., max_length=16)


class Mark1VisemeBody(BaseModel):
    code: int = Field(ge=0, le=6)


class Mark1ColorBody(BaseModel):
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)


class Mark1SideBody(BaseModel):
    side: str = Field(..., max_length=8)


class Mark1PercentBody(BaseModel):
    percentage: int = Field(ge=0, le=100)


class Mark1LevelBody(BaseModel):
    level: int = Field(ge=1, le=30)


class Mark1VolumeBody(BaseModel):
    volume: int = Field(ge=0, le=11)


class Mark1TimesBody(BaseModel):
    times: int = Field(ge=1, le=20)


def _connect_bus():
    """Return a connected bus client, or ``None`` when the bus is not up."""
    try:
        from ovos_bus_client.client import MessageBusClient
        bus = MessageBusClient()
        bus.run_in_thread()
        bus.connected_event.wait(timeout=5)
        return bus
    except Exception as err:  # noqa: BLE001 - the UI must start without a bus
        LOG.warning(f"could not connect to the message bus: {err}")
        return None


def body_limit_for(scope: dict[str, Any]) -> int:
    """Return the number of body bytes allowed for one request."""
    return MAX_UPLOAD_BYTES if scope.get("path") in UPLOAD_PATHS else MAX_PAYLOAD_BYTES


def _page(name: str) -> FileResponse:
    path = STATIC_DIR / name
    if not path.is_file():  # pragma: no cover - packaging problem
        raise HTTPException(status_code=500, detail=f"missing page: {name}")
    return FileResponse(path, media_type="text/html")


def create_app(bus=None, host: str = "127.0.0.1", token: str | None = None,
               connect_bus: bool = True,
               hostnames: tuple[str, ...] = ()) -> FastAPI:
    """Build the application.

    ``bus`` lets a test pass a ``FakeBus``. When it is ``None`` and
    ``connect_bus`` is true, the app connects to the real message bus while it
    starts up, and it keeps working if the bus is down. ``hostnames`` lists
    extra names a browser may use in the ``Host`` header, for a reverse proxy
    or an mDNS name.
    """
    policy: AuthPolicy = policy_from_config(host=host, token=token,
                                            hostnames=hostnames)
    state: dict[str, Any] = {"bus": bus}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if state["bus"] is None and connect_bus:
            state["bus"] = _connect_bus()
        if state["bus"] is not None:
            from ovos_webui.events import LOG_SINGLETON
            LOG_SINGLETON.attach(state["bus"])
        yield
        client = state["bus"]
        if client is not None and bus is None:
            try:
                client.close()
            except Exception as err:  # noqa: BLE001 # pragma: no cover
                LOG.debug(f"closing the bus client failed: {err}")

    # The interactive documentation and the schema are turned off: they told a
    # stranger the whole shape of the service before any sign in.
    app = FastAPI(title="OpenVoiceOS Web UI", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.policy = policy

    # ── the checks every router hangs off ────────────────────────────────────
    def guard(request: Request) -> AuthPolicy:
        """A signed in caller, and not a request forged by another site."""
        check_host(policy, request)
        check_csrf(request)
        policy.check(request)
        return policy

    def guard_public(request: Request) -> None:
        """Open, but still not usable as a forgery target."""
        check_host(policy, request)
        check_csrf(request)

    def guard_page(request: Request) -> None:
        """Guard an HTML page: same checks as ``guard``, but an unauthenticated
        browser is sent to the login screen instead of getting a bare JSON 401.

        Host and cross-site failures stay hard blocks (a real attack), only the
        missing/invalid-token case becomes a redirect, so typing the device URL
        lands on the login page rather than an error. A static asset (js/css/img)
        keeps the plain 401 — a non-navigation fetch must not be answered with an
        HTML login page.
        """
        check_host(policy, request)
        check_csrf(request)
        try:
            policy.check(request)
        except HTTPException as err:
            if (err.status_code == status.HTTP_401_UNAUTHORIZED
                    and not request.url.path.startswith("/static/")):
                raise HTTPException(
                    status_code=status.HTTP_303_SEE_OTHER,
                    headers={"Location": "/login"}) from None
            raise

    def guard_privileged(request: Request) -> AuthPolicy:
        """Anything that changes the software on the device.

        A token is always required here, whatever the bind address is. On
        loopback the rest of the page is open for convenience, but nothing that
        runs a process is ever open. The host and cross-site checks still run,
        because this router carries ``guard`` as well.
        """
        if not policy.token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This device has no access token yet. Set one on the "
                       "Settings page to enable installing, speaking, and "
                       "device controls.")
        policy.check(request)
        return policy

    public = APIRouter(dependencies=[Depends(guard_public)])
    pages = APIRouter(dependencies=[Depends(guard_page)], include_in_schema=False)
    api = APIRouter(prefix="/api", dependencies=[Depends(guard)])
    # Privileged routes inherit the host and cross-site checks from ``guard``
    # and add the always-a-token rule on top.
    privileged = APIRouter(prefix="/api",
                           dependencies=[Depends(guard), Depends(guard_privileged)])
    app.state.routers = {"public": public, "pages": pages, "api": api,
                         "privileged": privileged}

    # ── public ───────────────────────────────────────────────────────────────
    @public.get("/api/status")
    def api_status(request: Request) -> dict[str, Any]:
        """What the sign in page needs, and nothing more.

        Before a caller signs in this says only that a token is needed. The
        bind address and the version are not told to a stranger.
        """
        signed_in = not policy.token or policy.matches(policy.supplied_token(request))
        if not signed_in:
            # A stranger is told only whether a token is needed — not the
            # version, the bind address, or the device language.
            return {"auth": True, "signed_in": False}
        # The device language drives which language and direction the page uses.
        # It is only told to a signed-in caller; the sign in page follows the
        # browser's own language instead.
        try:
            lang = configio.read_merged_config().get("lang") or "en-us"
        except Exception:  # noqa: BLE001 - a broken config must not stop the UI
            lang = "en-us"
        return {
            "version": __version__,
            "host": policy.host,
            "auth": bool(policy.token),
            "signed_in": True,
            "insecure": policy.insecure,
            "warning": policy.warning,
            # No token yet means device controls / installs / speak will 403;
            # the UI uses this to prompt the owner to set one during onboarding,
            # even on loopback where `insecure` is False.
            "has_token": bool(policy.token),
            "lang": lang,
        }

    #: Wrong tokens in a row, across all callers, to slow a token guesser. Kept
    #: global on purpose: a per-source count is defeated by a reverse proxy (every
    #: request then carries the proxy's IP) and by IPv6 source rotation. The count
    #: decays after a quiet spell, so an honest typo made once the guessing has
    #: stopped barely waits at all.
    login_throttle = {"fails": 0, "last": 0.0}
    #: The longest a failed sign in ever waits.
    MAX_LOGIN_DELAY = 5.0

    async def _throttle_after_failed_login(request: Request) -> None:
        now = time.monotonic()
        if now - login_throttle["last"] > THROTTLE_DECAY:
            login_throttle["fails"] = 0
        login_throttle["fails"] += 1
        login_throttle["last"] = now
        who = request.client.host if request.client else "?"
        LOG.warning(f"ovos-webui: a sign in was refused from {who} "
                    f"({login_throttle['fails']} in a row)")
        delay = min(login_throttle["fails"] * 0.5, MAX_LOGIN_DELAY)
        await asyncio.sleep(delay)

    @public.post("/api/login")
    async def api_login(request: Request, response: Response) -> Any:
        """Exchange a token for a cookie.

        The token arrives in the body of a POST, so it is not written to the
        access log of every proxy and to the browser history on every click,
        which is what a token in the query string would do.
        """
        supplied, from_form = await _read_login(request)
        if not policy.token:
            return _login_answer(request, from_form, {"ok": True, "auth": False})
        if not policy.matches(supplied):
            # There is no account lock-out, so slow a guesser down: each wrong
            # try in a row from the SAME source waits a little longer, up to a
            # few seconds. One caller's mistyped token barely notices; a script
            # trying thousands from one place cannot, and it cannot make another
            # caller's first mistake pay its accumulated delay.
            await _throttle_after_failed_login(request)
            if from_form:
                return RedirectResponse("/login?bad=1", status_code=303)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="that token is not right")
        login_throttle["fails"] = 0
        answer = _login_answer(request, from_form, {"ok": True, "auth": True})
        answer.set_cookie(COOKIE_NAME, supplied, httponly=True,
                          samesite="strict", path="/", max_age=30 * 24 * 3600)
        return answer

    async def _read_login(request: Request) -> tuple[str, bool]:
        """Return the token, and whether it came from an HTML form."""
        ctype = request.headers.get("content-type", "")
        if ctype.startswith(("application/x-www-form-urlencoded",
                             "multipart/form-data")):
            form = await request.form()
            return str(form.get("token") or ""), True
        try:
            body = LoginBody.model_validate(await request.json())
        except Exception as err:  # noqa: BLE001 - any bad body is the same answer
            raise HTTPException(422, f"send a token: {err}") from None
        return body.token, False

    def _login_answer(request: Request, from_form: bool, payload: dict) -> Response:
        """A form post goes back to a page; a fetch gets JSON."""
        if from_form:
            return RedirectResponse("/", status_code=303)
        return JSONResponse(payload)

    @public.post("/api/logout")
    def api_logout(response: Response) -> dict[str, Any]:
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True}

    @public.get("/login", include_in_schema=False)
    def login_page() -> FileResponse:
        return _page("login.html")

    @public.get("/static/app.css", include_in_schema=False)
    def public_stylesheet() -> FileResponse:
        """The sign in page needs this before anyone has signed in.

        It is the stylesheet that ships in the package, the same one anybody
        can read on PyPI, so serving it to a stranger gives nothing away. Every
        other asset stays behind the sign in.
        """
        return FileResponse(STATIC_DIR / "app.css", media_type="text/css")

    @public.get("/static/manifest.webmanifest", include_in_schema=False)
    def public_manifest() -> FileResponse:
        """The web-app manifest and its icons ship in the package — the same
        bytes anybody can read on PyPI — and a browser fetches the manifest
        without cookies, so they stay public like the stylesheet."""
        return FileResponse(STATIC_DIR / "manifest.webmanifest",
                            media_type="application/manifest+json")

    @public.get("/static/icon-192.png", include_in_schema=False)
    def public_icon_small() -> FileResponse:
        return FileResponse(STATIC_DIR / "icon-192.png", media_type="image/png")

    @public.get("/static/icon-512.png", include_in_schema=False)
    def public_icon_large() -> FileResponse:
        return FileResponse(STATIC_DIR / "icon-512.png", media_type="image/png")

    @public.get("/healthz", include_in_schema=False)
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    # ── pages and assets ─────────────────────────────────────────────────────
    def _page_handler(name: str):
        def handler() -> FileResponse:
            return _page(name)
        return handler

    for route, filename in PAGES.items():
        pages.get(route)(_page_handler(filename))

    @pages.get("/static/{asset:path}")
    def static_asset(asset: str) -> FileResponse:
        """Serve one asset from the package.

        A mount cannot carry a dependency, so the assets are served by a normal
        route. That keeps them behind the same sign in as the pages.
        """
        if not asset or asset.startswith("/") or ".." in Path(asset).parts:
            raise HTTPException(404, "no such asset")
        path = (STATIC_DIR / asset).resolve()
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            raise HTTPException(404, "no such asset") from None
        if not path.is_file():
            raise HTTPException(404, "no such asset")
        media, _ = mimetypes.guess_type(str(path))
        return FileResponse(path, media_type=media or "application/octet-stream")

    # ── health ───────────────────────────────────────────────────────────────
    @api.get("/health")
    def api_health() -> dict[str, Any]:
        return health.snapshot(state["bus"])

    # ── configuration ────────────────────────────────────────────────────────
    @api.get("/config")
    def api_config_get(format: str = "json") -> dict[str, Any]:
        if format not in ("json", "yaml"):
            raise HTTPException(400, "format must be json or yaml")
        data = configio.read_user_config()
        return {
            "path": str(configio.user_config_path()),
            "format": format,
            "text": configio.dump_text(data, format),
        }

    @api.put("/config")
    def api_config_put(body: ConfigBody) -> dict[str, Any]:
        try:
            data = configio.parse_text(body.text, body.format)
        except configio.ConfigError as err:
            raise HTTPException(400, str(err)) from None
        return configio.write_user_config(data, bus=state["bus"])

    @api.get("/config/merged")
    def api_config_merged() -> dict[str, Any]:
        return {"config": configio.read_merged_config()}

    @api.get("/config/quick")
    def api_quick_get() -> dict[str, Any]:
        return {"fields": configio.quick_form(),
                "path": str(configio.user_config_path())}

    @api.post("/config/quick")
    def api_quick_post(body: QuickBody) -> dict[str, Any]:
        try:
            return configio.apply_quick_form(body.values, bus=state["bus"])
        except configio.ConfigError as err:
            raise HTTPException(400, str(err)) from None

    @api.get("/plugins")
    def api_plugins() -> dict[str, Any]:
        return {"plugins": configio.plugin_options()}

    # ── self-hosted servers (STT / TTS / translate) ─────────────────────────
    # These write the user configuration layer, exactly like /api/config and
    # /api/config/quick above — no bus message is specific to this feature.
    # Reads sit on ``api``; the write changes what the device does, so it sits
    # on ``privileged`` like the other device-changing routes.
    @privileged.get("/servers")
    def api_servers_get() -> dict[str, Any]:
        return {kind: servers.get_servers(kind) for kind in servers.KINDS}

    @privileged.post("/servers/{kind}")
    def api_servers_set(kind: str, body: ServersBody) -> dict[str, Any]:
        if kind not in servers.KINDS:
            raise HTTPException(404, f"unknown kind '{kind}'")
        result = servers.set_servers(kind, body.urls)
        if "error" in result:
            raise HTTPException(400, result["error"])
        return result

    # ── skill settings ───────────────────────────────────────────────────────
    @api.get("/skills")
    def api_skills() -> dict[str, Any]:
        return {"skills": skillsio.list_skills()}

    @api.get("/skills/{skill_id}")
    def api_skill_get(skill_id: str) -> dict[str, Any]:
        try:
            return {
                "skill_id": skill_id,
                "settings": skillsio.read_settings(skill_id),
                "meta": skillsio.settings_meta(skill_id),
                "generated_meta": skillsio.find_settingsmeta(skill_id) is None,
                "path": str(skillsio.settings_path(skill_id)),
            }
        except (UnsafeIdentifier, skillsio.SkillSettingsError) as err:
            raise HTTPException(400, str(err)) from None

    @api.put("/skills/{skill_id}")
    def api_skill_put(skill_id: str, body: SettingsBody) -> dict[str, Any]:
        try:
            return skillsio.write_settings(skill_id, body.settings)
        except (UnsafeIdentifier, skillsio.SkillSettingsError) as err:
            raise HTTPException(400, str(err)) from None

    # ── backup and restore ───────────────────────────────────────────────────
    @api.get("/backup")
    def api_backup() -> Response:
        blob = backupio.make_archive()
        name = backupio.archive_name()
        return Response(content=blob, media_type="application/gzip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def _read_upload(request: Request) -> bytes:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if not hasattr(upload, "read"):
                # A plain text field named "file", or nothing at all, has no
                # file to read. Answer 400 rather than let ``.read`` raise 500.
                raise HTTPException(400, "no file was sent")
            return await upload.read()
        return await request.body()

    @api.post("/restore")
    async def api_restore(request: Request) -> dict[str, Any]:
        blob = await _read_upload(request)
        try:
            # restore_archive does synchronous, fsync-heavy file I/O under a
            # lock; run it off the event loop so a restore cannot stall every
            # other request (this is an async route).
            return await run_in_threadpool(backupio.restore_archive, blob)
        except (backupio.RestoreError, UnsafeIdentifier) as err:
            raise HTTPException(400, str(err)) from None

    # ── plugin catalog and installer ─────────────────────────────────────────
    # Reads sit on the ``api`` router (host + cross-site + sign-in). Anything
    # that *changes* the software — install, uninstall, upgrade — sits on
    # ``privileged``, which adds the always-a-token rule. The read-only
    # diagnostics on ``api`` (``/updates`` sweeps PyPI, ``/updates/conflicts``
    # runs ``pip check``, ``/plugins/search`` reads the index) each take their
    # work-lock without blocking and are rate-limited (updates.py, pypi.py), so
    # a burst of concurrent requests neither amplifies outward nor parks the
    # worker pool — it just reads the cache.
    @api.get("/plugins/search")
    def api_plugin_search(q: str = "", kind: str = "",
                          refresh: bool = False) -> dict[str, Any]:
        if len(q) > 100 or len(kind) > 50:
            raise HTTPException(400, "the search is too long")
        return pypi.search(query=q, kind=kind, refresh=refresh)

    @api.get("/plugins/details/{package}")
    def api_plugin_details(package: str) -> dict[str, Any]:
        try:
            return pypi.details(package)
        except installer.UnsafePackageName as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))
        except OSError as err:
            raise HTTPException(502, f"PyPI could not be reached: {err}")

    @api.get("/plugins/recommended")
    def api_recommended(lang: str = "") -> dict[str, Any]:
        if not lang:
            lang = configio.read_merged_config().get("lang") or "en-us"
        if len(lang) > 32:
            raise HTTPException(400, "that is not a language code")
        from ovos_webui.pypi import installed_versions
        have = installed_versions()
        data = recommends.for_language(lang)  # computed once, reused below
        plugins = [dict(p, installed=p["module"].lower() in have)
                   for p in recommends.recommended_plugins(lang, data)]
        return {"lang": lang, "profiles": data, "plugins": plugins}

    @privileged.post("/plugins/install")
    def api_install(body: PackageBody) -> dict[str, Any]:
        try:
            return installer.INSTALLER.install(body.package, bus=state["bus"]).as_dict()
        except installer.UnsafePackageName as err:
            raise HTTPException(400, str(err))
        except installer.InstallerBusy as err:
            raise HTTPException(409, str(err))
        except installer.InstallerUnavailable as err:
            raise HTTPException(503, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))
        except OSError as err:
            raise HTTPException(502, f"PyPI could not be reached: {err}")

    @privileged.post("/plugins/uninstall")
    def api_uninstall(body: PackageBody) -> dict[str, Any]:
        try:
            return installer.INSTALLER.uninstall(body.package, bus=state["bus"]).as_dict()
        except installer.UnsafePackageName as err:
            raise HTTPException(400, str(err))
        except installer.InstallerBusy as err:
            raise HTTPException(409, str(err))
        except installer.InstallerUnavailable as err:
            raise HTTPException(503, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    @privileged.get("/plugins/jobs/{job_id}")
    def api_job(job_id: str, since: int = 0) -> dict[str, Any]:
        job = installer.INSTALLER.get(job_id)
        if job is None:
            raise HTTPException(404, "there is no job with that id")
        return job.as_dict(since=max(0, since))

    @privileged.get("/plugins/jobs")
    def api_jobs() -> dict[str, Any]:
        current = installer.INSTALLER.current()
        return {"current": current.as_dict(since=10 ** 9) if current else None,
                "recent": installer.INSTALLER.recent()}

    # ── updates, release channel, dependency health ──────────────────────────
    @api.get("/updates")
    def api_updates(refresh: bool = False) -> dict[str, Any]:
        from ovos_webui import updates
        return updates.check_updates(refresh=refresh)

    @privileged.post("/plugins/upgrade")
    def api_upgrade(body: PackageBody) -> dict[str, Any]:
        try:
            return installer.INSTALLER.upgrade(body.package, bus=state["bus"]).as_dict()
        except installer.UnsafePackageName as err:
            raise HTTPException(400, str(err))
        except installer.InstallerBusy as err:
            raise HTTPException(409, str(err))
        except installer.InstallerUnavailable as err:
            raise HTTPException(503, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    @api.get("/updates/channel")
    def api_channel_get() -> dict[str, Any]:
        from ovos_webui import updates
        return {"channel": updates.release_channel(),
                "channels": list(updates.CHANNELS)}

    @privileged.post("/updates/channel")
    def api_channel_set(body: ChannelBody) -> dict[str, Any]:
        from ovos_webui import updates
        try:
            return updates.set_release_channel(body.channel, bus=state["bus"])
        except ValueError as err:
            raise HTTPException(400, str(err))

    @api.get("/updates/conflicts")
    def api_conflicts() -> dict[str, Any]:
        from ovos_webui import updates
        return updates.dependency_conflicts()

    # ── backup history: the backups every save keeps on the device ───────────
    @api.get("/backups")
    def api_backups() -> dict[str, Any]:
        from ovos_webui import history
        return {"backups": history.list_backups()}

    @api.get("/backups/show")
    def api_backup_show(id: str) -> dict[str, Any]:
        from ovos_webui import history
        try:
            return history.read_backup(id)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    @api.post("/backups/revert")
    def api_backup_revert(body: BackupIdBody) -> dict[str, Any]:
        from ovos_webui import history
        try:
            return history.revert(body.id)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    # ── try it: the round trip a spoken sentence would take ──────────────────
    # Sending an utterance is running a command on the device, so it sits on
    # ``privileged`` — a token is always required, like the installer.
    @privileged.post("/tryit/ask")
    def api_tryit(body: UtteranceBody) -> dict[str, Any]:
        from ovos_webui import tryit
        if state["bus"] is None or not health.bus_reachable(state["bus"]):
            raise HTTPException(503, "the message bus is not reachable")
        lang = configio.read_merged_config().get("lang") or "en-us"
        try:
            return tryit.ask(state["bus"], body.text, lang)
        except ValueError as err:
            raise HTTPException(400, str(err))

    @privileged.post("/tryit/speak")
    def api_tryit_speak(body: UtteranceBody) -> dict[str, Any]:
        from ovos_webui import tryit
        if state["bus"] is None or not health.bus_reachable(state["bus"]):
            raise HTTPException(503, "the message bus is not reachable")
        lang = configio.read_merged_config().get("lang") or "en-us"
        try:
            return tryit.preview(state["bus"], body.text, lang)
        except ValueError as err:
            raise HTTPException(400, str(err))

    # The live feed carries what the device heard and said in plain text, so
    # it is as sensitive as causing speech: it sits on the privileged router,
    # a token always required, never open on a tokenless loopback device.
    @privileged.get("/events")
    def api_events(since: int = 0) -> dict[str, Any]:
        from ovos_webui.events import LOG_SINGLETON
        return LOG_SINGLETON.since(max(0, since))

    # ── skill enable / disable via the blacklist ─────────────────────────────
    @api.get("/skills/{skill_id}/enabled")
    def api_skill_enabled(skill_id: str) -> dict[str, Any]:
        try:
            skill_id = fsutils_validate_skill_id(skill_id)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        blacklist = configio.user_or_merged(
            ["skills", "blacklisted_skills"]) or []
        return {"skill_id": skill_id, "enabled": skill_id not in blacklist}

    @api.put("/skills/{skill_id}/enabled")
    def api_skill_set_enabled(skill_id: str, body: EnabledBody) -> dict[str, Any]:
        try:
            skill_id = fsutils_validate_skill_id(skill_id)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        def change(data):
            blacklist = list(configio.get_in(data, ["skills", "blacklisted_skills"])
                             or [])
            if body.enabled:
                blacklist = [s for s in blacklist if s != skill_id]
            elif skill_id not in blacklist:
                blacklist.append(skill_id)
            configio.set_in(data, ["skills", "blacklisted_skills"], blacklist)

        result = configio.mutate(change, bus=state["bus"])
        result.update({"skill_id": skill_id, "enabled": body.enabled})
        return result

    # ── system actions: bus messages PHAL may act on ─────────────────────────
    @privileged.post("/system/{action}")
    def api_system(action: str) -> dict[str, Any]:
        message_type = SYSTEM_ACTIONS.get(action)
        if message_type is None:
            raise HTTPException(404, "there is no such action")
        if state["bus"] is None or not health.bus_reachable(state["bus"]):
            raise HTTPException(503, "the message bus is not reachable")
        from ovos_bus_client.message import Message
        state["bus"].emit(Message(message_type, {}, {"source": "ovos-webui"}))
        return {"sent": message_type}

    def _need_bus():
        if state["bus"] is None or not health.bus_reachable(state["bus"]):
            raise HTTPException(503, "the message bus is not reachable")
        return state["bus"]

    # ── device controls: volume, microphone, and what each needs ─────────────
    @api.get("/device/capabilities")
    def api_capabilities_status() -> dict[str, Any]:
        from ovos_webui import phal
        return phal.capability_status()

    @api.get("/device/volume")
    def api_volume_get() -> dict[str, Any]:
        from ovos_webui import devicecontrol
        return devicecontrol.get_volume(_need_bus())

    @privileged.post("/device/volume")
    def api_volume_set(body: VolumeBody) -> dict[str, Any]:
        from ovos_webui import devicecontrol
        try:
            return devicecontrol.set_volume(_need_bus(), body.percent)
        except ValueError as err:
            raise HTTPException(400, str(err))

    @privileged.post("/device/volume/mute")
    def api_volume_mute(body: MuteBody) -> dict[str, Any]:
        from ovos_webui import devicecontrol
        return devicecontrol.set_mute(_need_bus(), body.muted)

    @api.get("/device/mic")
    def api_mic_get() -> dict[str, Any]:
        from ovos_webui import devicecontrol
        return devicecontrol.get_mic(_need_bus())

    @privileged.post("/device/mic/mute")
    def api_mic_mute(body: MuteBody) -> dict[str, Any]:
        from ovos_webui import devicecontrol
        return devicecontrol.set_mic_mute(_need_bus(), body.muted)

    # ── Wi-Fi: scan and join networks over the network-manager PHAL plugin ────
    # The plugin runs with root (the admin PHAL process) and joining a network
    # changes device state — and can drop this very browser's link to the
    # device — so every route sits on the privileged router: a token is always
    # required, like the installer and the power actions.
    @privileged.get("/network/status")
    def api_network_status() -> dict[str, Any]:
        from ovos_webui import network
        return network.connected(_need_bus())

    @privileged.post("/network/scan")
    def api_network_scan() -> dict[str, Any]:
        # POST, not GET: a scan drives an nmcli rescan on the device.
        from ovos_webui import network
        return {"networks": network.scan(_need_bus())}

    @privileged.post("/network/connect")
    def api_network_connect(body: WifiConnectBody) -> dict[str, Any]:
        from ovos_webui import network
        return network.connect(_need_bus(), body.ssid, body.password, body.security)

    @privileged.post("/network/disconnect")
    def api_network_disconnect(body: WifiSsidBody) -> dict[str, Any]:
        from ovos_webui import network
        return network.disconnect(_need_bus(), body.ssid)

    @privileged.post("/network/forget")
    def api_network_forget(body: WifiSsidBody) -> dict[str, Any]:
        from ovos_webui import network
        return network.forget(_need_bus(), body.ssid)

    # ── media: now-playing, transport, and volume over OCP / ovos-media ──────
    # All /media/* routes are privileged: even the reads (status, available,
    # volume) expose what's playing and current device state, so they should
    # not be readable on a token-less device, matching the transport and
    # volume-set/mute routes that change state.
    @privileged.get("/media/status")
    def api_media_status() -> dict[str, Any]:
        from ovos_webui import media
        return media.status(_need_bus())

    @privileged.get("/media/available")
    def api_media_available() -> dict[str, Any]:
        from ovos_webui import media
        return {"available": media.available(_need_bus())}

    @privileged.post("/media/play_pause")
    def api_media_play_pause() -> dict[str, Any]:
        from ovos_webui import media
        return media.play_pause(_need_bus())

    @privileged.post("/media/pause")
    def api_media_pause() -> dict[str, Any]:
        from ovos_webui import media
        return media.pause(_need_bus())

    @privileged.post("/media/resume")
    def api_media_resume() -> dict[str, Any]:
        from ovos_webui import media
        return media.resume(_need_bus())

    @privileged.post("/media/stop")
    def api_media_stop() -> dict[str, Any]:
        from ovos_webui import media
        return media.stop(_need_bus())

    @privileged.post("/media/next")
    def api_media_next() -> dict[str, Any]:
        from ovos_webui import media
        return media.next(_need_bus())

    @privileged.post("/media/previous")
    def api_media_previous() -> dict[str, Any]:
        from ovos_webui import media
        return media.previous(_need_bus())

    @privileged.get("/media/volume")
    def api_media_volume_get() -> dict[str, Any]:
        from ovos_webui import media
        return media.get_volume(_need_bus())

    @privileged.post("/media/volume")
    def api_media_volume_set(body: MediaVolumeBody) -> dict[str, Any]:
        from ovos_webui import media
        try:
            return media.set_volume(_need_bus(), body.percent)
        except ValueError as err:
            raise HTTPException(400, str(err))

    @privileged.post("/media/mute")
    def api_media_mute() -> dict[str, Any]:
        from ovos_webui import media
        return media.mute(_need_bus())

    @privileged.post("/media/unmute")
    def api_media_unmute() -> dict[str, Any]:
        from ovos_webui import media
        return media.unmute(_need_bus())

    # ── Mark-1 faceplate: eyes + mouth over enclosure.* ───────────────────────
    # Every route changes what the faceplate shows, so all of it sits on the
    # privileged router, like the network and system controls.
    @privileged.get("/mark1/available")
    def api_mark1_available() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.available(_need_bus())

    @privileged.post("/mark1/display")
    def api_mark1_display(body: Mark1DisplayBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.display_grid(_need_bus(), body.grid, body.x, body.y, body.clear)

    @privileged.post("/mark1/mouth/text")
    def api_mark1_mouth_text(body: Mark1TextBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.mouth_text(_need_bus(), body.text)

    @privileged.post("/mark1/mouth/reset")
    def api_mark1_mouth_reset() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.mouth_reset(_need_bus())

    @privileged.post("/mark1/mouth/anim")
    def api_mark1_mouth_anim(body: Mark1AnimBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.mouth_anim(_need_bus(), body.kind)

    @privileged.post("/mark1/mouth/viseme")
    def api_mark1_mouth_viseme(body: Mark1VisemeBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.mouth_viseme(_need_bus(), body.code)

    @privileged.post("/mark1/eyes/color")
    def api_mark1_eyes_color(body: Mark1ColorBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_color(_need_bus(), body.r, body.g, body.b)

    @privileged.post("/mark1/eyes/on")
    def api_mark1_eyes_on() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_on(_need_bus())

    @privileged.post("/mark1/eyes/off")
    def api_mark1_eyes_off() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_off(_need_bus())

    @privileged.post("/mark1/eyes/reset")
    def api_mark1_eyes_reset() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_reset(_need_bus())

    @privileged.post("/mark1/eyes/narrow")
    def api_mark1_eyes_narrow() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_narrow(_need_bus())

    @privileged.post("/mark1/eyes/spin")
    def api_mark1_eyes_spin() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_spin(_need_bus())

    @privileged.post("/mark1/eyes/blink")
    def api_mark1_eyes_blink(body: Mark1SideBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_blink(_need_bus(), body.side)

    @privileged.post("/mark1/eyes/look")
    def api_mark1_eyes_look(body: Mark1SideBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_look(_need_bus(), body.side)

    @privileged.post("/mark1/eyes/fill")
    def api_mark1_eyes_fill(body: Mark1PercentBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_fill(_need_bus(), body.percentage)

    @privileged.post("/mark1/eyes/brightness")
    def api_mark1_eyes_brightness(body: Mark1LevelBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_brightness(_need_bus(), body.level)

    @privileged.post("/mark1/eyes/volume")
    def api_mark1_eyes_volume(body: Mark1VolumeBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.eyes_volume(_need_bus(), body.volume)

    @privileged.post("/mark1/system/reset")
    def api_mark1_system_reset() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.system_reset(_need_bus())

    @privileged.post("/mark1/system/mute")
    def api_mark1_system_mute() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.system_mute(_need_bus())

    @privileged.post("/mark1/system/unmute")
    def api_mark1_system_unmute() -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.system_unmute(_need_bus())

    @privileged.post("/mark1/system/blink")
    def api_mark1_system_blink(body: Mark1TimesBody) -> dict[str, Any]:
        from ovos_webui import mark1
        return mark1.system_blink(_need_bus(), body.times)

    # ── ggwave listener: turn the device's sound receiver on or off ──────────
    # Fire-and-forget, like /system/{action} — the ggwave audio transformer
    # plugin does not answer a query, it just starts or stops listening.
    @privileged.post("/ggwave/listen")
    def api_ggwave_listen(body: GgwaveListenBody) -> dict[str, Any]:
        from ovos_bus_client.message import Message
        if body.enabled:
            # timeout is optional: leave it out and the plugin falls back to
            # its own configured "listen_timeout"; 0 means never auto-disable.
            data = {"timeout": body.timeout} if body.timeout is not None else {}
            _need_bus().emit(Message("ovos.ggwave.enable", data, {"source": "ovos-webui"}))
            return {"ok": True, "sent": "ovos.ggwave.enable", "timeout": body.timeout}
        _need_bus().emit(Message("ovos.ggwave.disable", {}, {"source": "ovos-webui"}))
        return {"ok": True, "sent": "ovos.ggwave.disable"}

    # ── what can it do: the installed skills ─────────────────────────────────
    @api.get("/capabilities")
    def api_abilities() -> dict[str, Any]:
        from ovos_webui import capabilities
        return capabilities.list_capabilities()

    # ── access token: set the first one, or rotate it ────────────────────────
    # On a device that already has a token, changing it needs a signed-in
    # session (the ``api`` guard) AND the current token re-supplied in the body.
    # On a device with no token yet, the ``api`` router is open to the same
    # callers that can already write it through ``PUT /api/config`` — setting a
    # token here only tightens the device, so it is allowed on the same terms.
    @api.post("/auth/token")
    def api_set_token(body: TokenBody, response: Response) -> dict[str, Any]:
        from ovos_webui.auth import MIN_TOKEN_LENGTH

        new = (body.new or "").strip()
        had_token = bool(policy.token)
        if len(new) < MIN_TOKEN_LENGTH:
            raise HTTPException(400, f"the token must be at least "
                                     f"{MIN_TOKEN_LENGTH} characters")
        if policy.token:
            # Changing an existing token needs the current one, so a walk-up to
            # an unlocked session cannot silently lock the owner out.
            if not policy.matches((body.current or "").strip()):
                raise HTTPException(403, "the current token is not right")
        # Route through mutate so a concurrent config save cannot revert the
        # token (or the token save clobber another change) — the lost-update
        # race configio.mutate exists to close.
        configio.mutate(
            lambda user: configio.set_in(user, ["webui", "access_token"], new),
            bus=state["bus"])
        policy.token = new  # take effect at once for the rest of this process
        # Keep this session signed in under the new token.
        response.set_cookie(COOKIE_NAME, new, httponly=True, samesite="strict",
                            path="/", max_age=30 * 24 * 3600)
        return {"ok": True, "had_token": had_token}

    # ── personas ─────────────────────────────────────────────────────────────
    @api.get("/personas")
    def api_personas() -> dict[str, Any]:
        active = configio.user_or_merged(
            ["intents", "persona", "default_persona"])
        return {"personas": personas.list_personas(),
                "solvers": personas.available_solvers(),
                "memory_plugins": personas.available_memory_plugins(),
                "active": active,
                "path": str(personas.personas_root())}

    @api.post("/personas/{persona_id}/activate")
    def api_persona_activate(persona_id: str) -> dict[str, Any]:
        try:
            data = personas.read_persona(persona_id)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))
        except personas.PersonaError as err:
            raise HTTPException(400, str(err))
        # The persona service matches ``default_persona`` against the *name*
        # a persona declares, so that is what goes in the configuration.
        name = data.get("name") or persona_id
        result = configio.mutate(
            lambda user: configio.set_in(
                user, ["intents", "persona", "default_persona"], name),
            bus=state["bus"])
        # Warn if the persona's solvers are not installed — activating it is the
        # moment the user commits, so a silently-broken persona must be flagged.
        result.update({"active": name, "persona_id": persona_id,
                       "missing_solvers": personas.missing_solvers(data)})
        return result

    @api.get("/personas/{persona_id}")
    def api_persona_get(persona_id: str) -> dict[str, Any]:
        try:
            data = personas.read_persona(persona_id)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))
        except personas.PersonaError as err:
            raise HTTPException(400, str(err))
        return {"persona_id": persona_id, "persona": data,
                "missing_solvers": personas.missing_solvers(data)}

    @api.put("/personas/{persona_id}")
    def api_persona_put(persona_id: str, body: PersonaBody) -> dict[str, Any]:
        try:
            return personas.write_persona(persona_id, body.persona)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except personas.PersonaError as err:
            raise HTTPException(400, str(err))

    @api.delete("/personas/{persona_id}")
    def api_persona_delete(persona_id: str) -> dict[str, Any]:
        try:
            return personas.delete_persona(persona_id)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    @api.post("/personas/{persona_id}/try")
    def api_persona_try(persona_id: str, body: PersonaTestBody) -> dict[str, Any]:
        try:
            return personas.try_persona(persona_id, body.question)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))
        except personas.PersonaError as err:
            raise HTTPException(400, str(err))

    # ── resource translation ─────────────────────────────────────────────────
    @api.get("/translate/skills")
    def api_tr_skills() -> dict[str, Any]:
        return {"skills": translate.list_skills(),
                "plugins": translate.translation_plugins(),
                "root": str(translate.user_resources_root())}

    @api.get("/translate/{skill_id}/languages")
    def api_tr_langs(skill_id: str) -> dict[str, Any]:
        try:
            return {"languages": translate.source_languages(skill_id)}
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))

    @api.get("/translate/{skill_id}/{lang}/files")
    def api_tr_files(skill_id: str, lang: str) -> dict[str, Any]:
        try:
            return {"files": translate.list_resources(skill_id, lang)}
        except (UnsafeIdentifier, translate.TranslateError) as err:
            raise HTTPException(400, str(err))

    @api.get("/translate/{skill_id}/{lang}/file/{file_name}")
    def api_tr_file(skill_id: str, lang: str, file_name: str) -> dict[str, Any]:
        try:
            return {"source": translate.read_source(skill_id, lang, file_name),
                    "override": translate.read_override(skill_id, lang, file_name)}
        except (UnsafeIdentifier, translate.TranslateError) as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    @api.post("/translate/{skill_id}/{lang}/machine")
    def api_tr_machine(skill_id: str, lang: str,
                       body: TranslateBody) -> dict[str, Any]:
        try:
            translate.validate_skill_id(skill_id)
            translate.validate_lang(lang)
            return translate.machine_translate(body.lines, body.source, body.target,
                                               body.plugin)
        except (UnsafeIdentifier, translate.TranslateError) as err:
            raise HTTPException(400, str(err))

    @api.put("/translate/{skill_id}/{lang}/file/{file_name}")
    def api_tr_put(skill_id: str, lang: str, file_name: str,
                   body: OverrideBody) -> dict[str, Any]:
        try:
            return translate.write_override(skill_id, lang, file_name, body.lines)
        except (UnsafeIdentifier, translate.TranslateError) as err:
            raise HTTPException(400, str(err))

    @api.delete("/translate/{skill_id}/{lang}/file/{file_name}")
    def api_tr_delete(skill_id: str, lang: str, file_name: str) -> dict[str, Any]:
        try:
            return translate.delete_override(skill_id, lang, file_name)
        except (UnsafeIdentifier, translate.TranslateError) as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    # ── about ────────────────────────────────────────────────────────────────
    @api.get("/about")
    def api_about(request: Request) -> dict[str, Any]:
        return meta.about(request.headers.get("host", ""))

    app.include_router(public)
    app.include_router(pages)
    app.include_router(api)
    app.include_router(privileged)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        # A token in a Referer header would leak to any site a page links to,
        # so no referrer leaves this origin.
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # The Send-over-sound page loads ggwave (data-over-sound). Its Emscripten
        # glue registers JS<->wasm types with new Function(), which a browser only
        # runs under 'unsafe-eval'. Confine that one relaxation to that page; every
        # other page keeps the strict script-src with no eval. (A cleaner long-term
        # fix is to rebuild ggwave.js with Emscripten -sDYNAMIC_EXECUTION=0, which
        # avoids eval/new Function entirely.)
        if request.url.path == "/sound":
            script_src = "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        else:
            script_src = "script-src 'self' 'unsafe-inline'; "
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; " + script_src +
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; form-action 'self'; frame-ancestors 'none'")
        return response

    app.add_middleware(BodyLimitMiddleware, limit_for=body_limit_for,
                       status_code=TOO_LARGE)
    return app


def main() -> None:
    """Console entry point."""
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the OpenVoiceOS web UI.")
    parser.add_argument("--host", default=os.environ.get("OVOS_WEBUI_HOST", "127.0.0.1"),
                        help="address to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("OVOS_WEBUI_PORT", "8500")),
                        help="port to listen on (default: 8500)")
    parser.add_argument("--token", default=os.environ.get("OVOS_WEBUI_TOKEN"),
                        help="access token; overrides webui.access_token")
    parser.add_argument("--no-bus", action="store_true",
                        help="do not connect to the message bus")
    parser.add_argument("--hostname", action="append", default=[],
                        help="extra Host header name to accept (repeatable); "
                             "for a reverse proxy or an mDNS name. Numeric IPs "
                             "and the loopback names are always accepted.")
    args = parser.parse_args()

    hostnames = tuple(args.hostname)
    try:
        policy = policy_from_config(host=args.host, token=args.token,
                                    hostnames=hostnames)
    except ValueError as err:
        parser.error(str(err))
    if policy.insecure:
        LOG.warning(f"ovos-webui is bound to {args.host} with no token. Anyone "
                    "on the network can change this device. Set "
                    "webui.access_token in mycroft.conf, or pass --token.")

    app = create_app(host=args.host, token=args.token,
                     connect_bus=not args.no_bus, hostnames=hostnames)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
