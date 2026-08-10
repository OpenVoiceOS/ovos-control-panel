"""The ovos-webui FastAPI service."""
from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from ovos_utils.log import LOG
from pydantic import BaseModel, Field

from ovos_webui import backupio, configio, health, meta, skillsio
from ovos_webui.auth import AuthPolicy, policy_from_config
from ovos_webui.fsutils import MAX_PAYLOAD_BYTES, MAX_UPLOAD_BYTES, UnsafeIdentifier
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
}


class ConfigBody(BaseModel):
    text: str = Field(..., description="the whole user layer, as JSON or YAML")
    format: str = Field("json", pattern="^(json|yaml)$")


class QuickBody(BaseModel):
    values: dict[str, Any]


class SettingsBody(BaseModel):
    settings: dict[str, Any]


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


def create_app(bus=None, host: str = "0.0.0.0", token: str | None = None,
               connect_bus: bool = True) -> FastAPI:
    """Build the application.

    ``bus`` lets a test pass a ``FakeBus``. When it is ``None`` and
    ``connect_bus`` is true, the app connects to the real message bus while it
    starts up, and it keeps working if the bus is down.
    """
    policy: AuthPolicy = policy_from_config(host=host, token=token)
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

    app = FastAPI(title="OpenVoiceOS Web UI", version=__version__, lifespan=lifespan)
    app.state.policy = policy

    def guard(request: Request) -> AuthPolicy:
        policy.check(request)
        return policy

    Auth = Depends(guard)

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        raw = request.headers.get("content-length")
        if raw:
            try:
                length = int(raw)
            except ValueError:
                return JSONResponse({"detail": "content-length is not a number"},
                                    status_code=status.HTTP_400_BAD_REQUEST)
            cap = MAX_UPLOAD_BYTES if request.url.path == "/api/restore" else MAX_PAYLOAD_BYTES
            if length > cap:
                return JSONResponse({"detail": "the request body is too large"},
                                    status_code=TOO_LARGE)
        return await call_next(request)

    # ── pages ────────────────────────────────────────────────────────────────
    def _page(name: str) -> FileResponse:
        path = STATIC_DIR / name
        if not path.is_file():  # pragma: no cover - packaging problem
            raise HTTPException(status_code=500, detail=f"missing page: {name}")
        return FileResponse(path, media_type="text/html")

    def _page_handler(name: str):
        """Return a handler that serves one page file."""
        def handler() -> FileResponse:
            return _page(name)
        return handler

    for route, filename in PAGES.items():
        app.get(route, include_in_schema=False)(_page_handler(filename))

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── status and health ────────────────────────────────────────────────────
    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return {
            "version": __version__,
            "host": policy.host,
            "auth": bool(policy.token),
            "insecure": policy.insecure,
            "warning": policy.warning,
        }

    @app.get("/api/health")
    def api_health(_: AuthPolicy = Auth) -> dict[str, Any]:
        return health.snapshot(state["bus"])

    # ── configuration ────────────────────────────────────────────────────────
    @app.get("/api/config")
    def api_config_get(format: str = "json", _: AuthPolicy = Auth) -> dict[str, Any]:
        if format not in ("json", "yaml"):
            raise HTTPException(400, "format must be json or yaml")
        data = configio.read_user_config()
        return {
            "path": str(configio.user_config_path()),
            "format": format,
            "text": configio.dump_text(data, format),
        }

    @app.put("/api/config")
    def api_config_put(body: ConfigBody, _: AuthPolicy = Auth) -> dict[str, Any]:
        try:
            data = configio.parse_text(body.text, body.format)
        except configio.ConfigError as err:
            raise HTTPException(400, str(err))
        return configio.write_user_config(data, bus=state["bus"])

    @app.get("/api/config/merged")
    def api_config_merged(_: AuthPolicy = Auth) -> dict[str, Any]:
        return {"config": configio.read_merged_config()}

    @app.get("/api/config/quick")
    def api_quick_get(_: AuthPolicy = Auth) -> dict[str, Any]:
        return {"fields": configio.quick_form()}

    @app.post("/api/config/quick")
    def api_quick_post(body: QuickBody, _: AuthPolicy = Auth) -> dict[str, Any]:
        try:
            return configio.apply_quick_form(body.values, bus=state["bus"])
        except configio.ConfigError as err:
            raise HTTPException(400, str(err))

    @app.get("/api/plugins")
    def api_plugins(_: AuthPolicy = Auth) -> dict[str, Any]:
        return {"plugins": configio.plugin_options()}

    # ── skill settings ───────────────────────────────────────────────────────
    @app.get("/api/skills")
    def api_skills(_: AuthPolicy = Auth) -> dict[str, Any]:
        return {"skills": skillsio.list_skills()}

    @app.get("/api/skills/{skill_id}")
    def api_skill_get(skill_id: str, _: AuthPolicy = Auth) -> dict[str, Any]:
        try:
            return {
                "skill_id": skill_id,
                "settings": skillsio.read_settings(skill_id),
                "meta": skillsio.settings_meta(skill_id),
                "generated_meta": skillsio.find_settingsmeta(skill_id) is None,
                "path": str(skillsio.settings_path(skill_id)),
            }
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except skillsio.SkillSettingsError as err:
            raise HTTPException(400, str(err))

    @app.put("/api/skills/{skill_id}")
    def api_skill_put(skill_id: str, body: SettingsBody,
                      _: AuthPolicy = Auth) -> dict[str, Any]:
        try:
            return skillsio.write_settings(skill_id, body.settings)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except skillsio.SkillSettingsError as err:
            raise HTTPException(400, str(err))

    # ── backup and restore ───────────────────────────────────────────────────
    @app.get("/api/backup")
    def api_backup(_: AuthPolicy = Auth) -> Response:
        blob = backupio.make_archive()
        name = backupio.archive_name()
        return Response(content=blob, media_type="application/gzip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/restore")
    async def api_restore(request: Request, _: AuthPolicy = Auth) -> dict[str, Any]:
        blob = await _read_upload(request)
        try:
            return backupio.restore_archive(blob)
        except (backupio.RestoreError, UnsafeIdentifier) as err:
            raise HTTPException(400, str(err))

    async def _read_upload(request: Request) -> bytes:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None:
                raise HTTPException(400, "no file was sent")
            return await upload.read()
        return await request.body()

    # ── about ────────────────────────────────────────────────────────────────
    @app.get("/api/about")
    def api_about(request: Request, _: AuthPolicy = Auth) -> dict[str, Any]:
        return meta.about(request.headers.get("host", ""))

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    return app


def main() -> None:
    """Console entry point."""
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the OpenVoiceOS web UI.")
    parser.add_argument("--host", default=os.environ.get("OVOS_WEBUI_HOST", "0.0.0.0"),
                        help="address to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("OVOS_WEBUI_PORT", "8500")),
                        help="port to listen on (default: 8500)")
    parser.add_argument("--token", default=os.environ.get("OVOS_WEBUI_TOKEN"),
                        help="access token; overrides webui.access_token")
    parser.add_argument("--no-bus", action="store_true",
                        help="do not connect to the message bus")
    args = parser.parse_args()

    app = create_app(host=args.host, token=args.token, connect_bus=not args.no_bus)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
