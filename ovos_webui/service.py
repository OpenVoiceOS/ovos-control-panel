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
import mimetypes
import os
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
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from ovos_utils.log import LOG
from pydantic import BaseModel, Field

from ovos_webui import (backupio, configio, health, installer, meta, personas,
                        pypi, recommends, skillsio, translate)
from ovos_webui.auth import (
    COOKIE_NAME,
    AuthPolicy,
    check_csrf,
    check_host,
    policy_from_config,
)
from ovos_webui.fsutils import MAX_PAYLOAD_BYTES, MAX_UPLOAD_BYTES, UnsafeIdentifier
from ovos_webui.limits import BodyLimitMiddleware
from ovos_webui.version import __version__

#: Starlette renamed this constant. Keep working with both names.
TOO_LARGE = getattr(status, "HTTP_413_CONTENT_TOO_LARGE",
                    getattr(status, "HTTP_413_REQUEST_ENTITY_TOO_LARGE", 413))

STATIC_DIR = Path(__file__).parent / "static"
PAGES = {
    "/": "index.html",
    "/config": "config.html",
    "/skills": "skills.html",
    "/backup": "backup.html",
    "/about": "about.html",
    "/plugins": "plugins.html",
    "/personas": "personas.html",
    "/translate": "translate.html",
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


class OverrideBody(BaseModel):
    lines: list[str]


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
                detail="this needs a token. Set webui.access_token in "
                       "mycroft.conf, or start the service with --token.")
        policy.check(request)
        return policy

    public = APIRouter(dependencies=[Depends(guard_public)])
    pages = APIRouter(dependencies=[Depends(guard)], include_in_schema=False)
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
            "lang": lang,
        }

    #: How many wrong tokens in a row we have seen, to slow a guesser down.
    login_throttle = {"fails": 0}
    #: The longest a failed sign in ever waits.
    MAX_LOGIN_DELAY = 5.0

    async def _throttle_after_failed_login(request: Request) -> None:
        login_throttle["fails"] += 1
        LOG.warning("ovos-webui: a sign in was refused from "
                    f"{request.client.host if request.client else '?'} "
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
            # try in a row waits a little longer, up to a few seconds. A single
            # mistyped token barely notices; a script trying thousands cannot.
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
        return {"fields": configio.quick_form()}

    @api.post("/config/quick")
    def api_quick_post(body: QuickBody) -> dict[str, Any]:
        try:
            return configio.apply_quick_form(body.values, bus=state["bus"])
        except configio.ConfigError as err:
            raise HTTPException(400, str(err)) from None

    @api.get("/plugins")
    def api_plugins() -> dict[str, Any]:
        return {"plugins": configio.plugin_options()}

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
            return backupio.restore_archive(blob)
        except (backupio.RestoreError, UnsafeIdentifier) as err:
            raise HTTPException(400, str(err)) from None

    # ── plugin catalog and installer ─────────────────────────────────────────
    # Reads sit on the ``api`` router (host + cross-site + sign-in). Anything
    # that runs pip sits on ``privileged``, which adds the always-a-token rule.
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
        return {"lang": lang, "profiles": recommends.for_language(lang),
                "plugins": recommends.recommended_plugins(lang)}

    @privileged.post("/plugins/install")
    def api_install(body: PackageBody) -> dict[str, Any]:
        try:
            return installer.INSTALLER.install(body.package).as_dict()
        except installer.UnsafePackageName as err:
            raise HTTPException(400, str(err))
        except installer.InstallerBusy as err:
            raise HTTPException(409, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))
        except OSError as err:
            raise HTTPException(502, f"PyPI could not be reached: {err}")

    @privileged.post("/plugins/uninstall")
    def api_uninstall(body: PackageBody) -> dict[str, Any]:
        try:
            return installer.INSTALLER.uninstall(body.package).as_dict()
        except installer.UnsafePackageName as err:
            raise HTTPException(400, str(err))
        except installer.InstallerBusy as err:
            raise HTTPException(409, str(err))
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

    # ── personas ─────────────────────────────────────────────────────────────
    @api.get("/personas")
    def api_personas() -> dict[str, Any]:
        return {"personas": personas.list_personas(),
                "solvers": personas.available_solvers(),
                "memory_plugins": personas.available_memory_plugins(),
                "path": str(personas.personas_root())}

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
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
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
