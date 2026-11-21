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
import json
import time
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

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
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from ovos_utils.log import LOG
from pydantic import BaseModel, Field

from ovos_webui import configio, health, installer, pypi, recommends, voicecfg
from ovos_webui import pages as page_registry
from ovos_webui.auth import (
    COOKIE_NAME,
    AuthPolicy,
    check_csrf,
    check_host,
    policy_from_config,
)
from ovos_webui.fsutils import MAX_PAYLOAD_BYTES, MAX_UPLOAD_BYTES
from ovos_webui.limits import BodyLimitMiddleware
from ovos_webui.version import __version__

#: Starlette renamed this constant in 1.0 and warns on the old name. A default
#: argument is evaluated whether or not it is needed, so the two names have to
#: be tried one at a time or the warning fires on every modern install.
TOO_LARGE = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", None) or getattr(
    status, "HTTP_413_REQUEST_ENTITY_TOO_LARGE", 413)

STATIC_DIR = Path(__file__).parent / "static"

#: A quiet spell at least this long resets the failed-login count (module level
#: so tests can shorten it).
THROTTLE_DECAY = 30.0
#: Pages that moved. The old address still works and lands on the new page.
MOVED_PAGES = {
    "/abilities": "/skills",
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


class PackageBody(BaseModel):
    package: str = Field(..., max_length=100)


class UtteranceBody(BaseModel):
    text: str = Field(max_length=500)


class ConfigBody(BaseModel):
    text: str = Field(..., description="the whole user layer, as JSON or YAML")
    format: str = Field("json", pattern="^(json|yaml)$")


class QuickBody(BaseModel):
    values: dict[str, Any]


class VoiceBody(BaseModel):
    key: str
    value: Any = None


class LoginBody(BaseModel):
    token: str = Field(..., max_length=512)


class TokenBody(BaseModel):
    current: str | None = Field(None, max_length=512)
    new: str = Field(max_length=512)


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
    app = FastAPI(title="OpenVoiceOS Control Panel", version=__version__, lifespan=lifespan,
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
        # The sign in page belongs to the shell, not to the page registry:
        # it has no menu, because you are not signed in yet.
        return FileResponse(STATIC_DIR / "login.html", media_type="text/html")

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
    # Every page in the menu comes from the page registry, the panel's own
    # included. The pages themselves are served once every route is known
    # (see "pages from the registry", below), because a page whose routes
    # clash is left out.
    registry = page_registry.load()
    app.state.registry = registry

    def _moved_handler(target: str):
        def handler(request: Request) -> RedirectResponse:
            # keep a #fragment working: the browser carries it over itself
            query = ("?" + request.url.query) if request.url.query else ""
            return RedirectResponse(target + query, status_code=308)
        return handler

    for route, target in MOVED_PAGES.items():
        pages.get(route, include_in_schema=False)(_moved_handler(target))

    @pages.get("/static/i18n/{lang}.json", include_in_schema=False)
    def static_strings(lang: str) -> JSONResponse:
        """The strings for a language: the panel's, with each page's own."""
        lang = lang.lower()
        if not re.fullmatch(r"[a-z]{2,3}", lang):
            raise HTTPException(404, "no such language")
        path = STATIC_DIR / "i18n" / f"{lang}.json"
        base = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        merged = registry.strings(lang, base)
        if not merged:
            raise HTTPException(404, "no such language")
        return JSONResponse(merged)

    @pages.get("/pages/{page_id}/{asset:path}", include_in_schema=False)
    def page_asset(page_id: str, asset: str) -> Response:
        """Serve a file from a page's own assets folder."""
        page = registry.by_id().get(page_id)
        parts = Path(asset).parts if asset else ()
        if page is None or page.assets is None or not parts or asset.startswith("/") \
                or any(p in ("", ".", "..") or p.startswith(".") for p in parts):
            raise HTTPException(404, "no such asset")
        target = page.assets.joinpath(*parts)
        if not target.is_file():
            raise HTTPException(404, "no such asset")
        media, _ = mimetypes.guess_type(parts[-1])
        return Response(target.read_bytes(), media_type=media or "application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff"})

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

    # ── voice settings ───────────────────────────────────────────────────────
    # Wake word, VAD, STT/TTS (+ fallback), pipeline order, transformers and
    # language change how the device listens and speaks, so both routes sit on
    # ``privileged``, like the plugin installer and the device controls.
    @privileged.get("/voice")
    def api_voice_get() -> dict[str, Any]:
        return voicecfg.get_settings()

    @privileged.post("/voice")
    def api_voice_post(body: VoiceBody) -> dict[str, Any]:
        try:
            return voicecfg.set_value(body.key, body.value, bus=state["bus"])
        except voicecfg.VoiceConfigError as err:
            raise HTTPException(400, str(err)) from None

    @api.get("/plugins")
    def api_plugins() -> dict[str, Any]:
        return {"plugins": configio.plugin_options()}




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

    @privileged.post("/plugins/check")
    def api_install_check(body: PackageBody) -> dict[str, Any]:
        """What installing a package would change here, before it runs."""
        from ovos_webui import installcheck
        try:
            return installcheck.check(body.package)
        except installer.UnsafePackageName as err:
            raise HTTPException(400, str(err))

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

    # ── updates: what can be upgraded ────────────────────────────────────────
    @api.get("/updates")
    def api_updates(refresh: bool = False) -> dict[str, Any]:
        from ovos_webui import updates
        return updates.check_updates(refresh=refresh)


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

    @api.get("/nav/needs")
    def api_nav_needs() -> dict[str, Any]:
        """Which page needs are met, so the menu can leave out what cannot work."""
        return page_registry.needs(registry)

    @api.get("/pages")
    def api_pages() -> dict[str, Any]:
        """Every page in the menu, where it comes from, and the ones left out."""
        return {"pages": [p.about() for p in registry.pages],
                "problems": list(registry.problems)}


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


    # ── pages from the registry ──────────────────────────────────────────────
    # A page may add its own API routes. It gets routers with the same checks
    # as the panel's own, and is left out if it adds a route that exists.
    def _make_page_routes() -> page_registry.Routes:
        return page_registry.Routes(
            api=APIRouter(prefix="/api", dependencies=[Depends(guard)]),
            privileged=APIRouter(prefix="/api",
                                 dependencies=[Depends(guard), Depends(guard_privileged)]),
            need_bus=_need_bus, config=configio, bus=lambda: state["bus"])

    page_routers: list[page_registry.Routes] = []
    taken = {(m, r.path) for router in (public, pages, api, privileged)
             for r in router.routes for m in (getattr(r, "methods", None) or ())}
    page_registry.mount_routes(registry, _make_page_routes, taken, page_routers.append)

    # Each page is served with the menu in its head, so the menu is there as
    # the page paints, with no request of its own.
    nav_json = registry.nav_json()

    def _page_handler(page):
        body = page_registry.render(page, nav_json)

        def handler() -> HTMLResponse:
            return HTMLResponse(body)
        return handler

    for page in registry.pages:
        pages.get(page.path)(_page_handler(page))

    # Pages' routes go before the shell's own, so a shell route with a
    # parameter (POST /api/system/{action}) does not answer for a page's
    # (POST /api/system/ssh). mount_routes made sure no page takes a shell's.
    app.include_router(public)
    app.include_router(pages)
    for r in page_routers:
        app.include_router(r.api)
        app.include_router(r.privileged)
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
