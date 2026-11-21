"""The backup page's API."""
from typing import Any

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ovos_webui import backupio
from ovos_webui.fsutils import UnsafeIdentifier


class BackupIdBody(BaseModel):
    id: str = Field(max_length=512)


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


def routes(r) -> None:
    # ── backup and restore ───────────────────────────────────────────────────
    @r.api.get("/backup")
    def api_backup() -> Response:
        blob = backupio.make_archive()
        name = backupio.archive_name()
        return Response(content=blob, media_type="application/gzip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @r.api.post("/restore")
    async def api_restore(request: Request) -> dict[str, Any]:
        blob = await _read_upload(request)
        try:
            # restore_archive does synchronous, fsync-heavy file I/O under a
            # lock; run it off the event loop so a restore cannot stall every
            # other request (this is an async route).
            return await run_in_threadpool(backupio.restore_archive, blob, r.bus())
        except (backupio.RestoreError, UnsafeIdentifier) as err:
            raise HTTPException(400, str(err)) from None

    # ── backup history: the backups every save keeps on the device ───────────
    @r.api.get("/backups")
    def api_backups() -> dict[str, Any]:
        from ovos_webui import history
        return {"backups": history.list_backups()}

    @r.api.get("/backups/show")
    def api_backup_show(id: str) -> dict[str, Any]:
        from ovos_webui import history
        try:
            return history.read_backup(id)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    @r.api.post("/backups/revert")
    def api_backup_revert(body: BackupIdBody) -> dict[str, Any]:
        from ovos_webui import history
        try:
            return history.revert(body.id, bus=r.bus())
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))
