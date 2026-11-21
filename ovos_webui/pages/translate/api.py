"""The translate page's API."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ovos_webui import translate
from ovos_webui.fsutils import UnsafeIdentifier


class OverrideBody(BaseModel):
    lines: list[str]


class TranslateBody(BaseModel):
    lines: list[str]
    source: str = Field(..., max_length=16)
    target: str = Field(..., max_length=16)
    plugin: str | None = Field(None, max_length=128)


def routes(r) -> None:
    # ── resource translation ─────────────────────────────────────────────────
    @r.api.get("/translate/skills")
    def api_tr_skills() -> dict[str, Any]:
        return {"skills": translate.list_skills(),
                "plugins": translate.translation_plugins(),
                "root": str(translate.user_resources_root())}

    @r.api.get("/translate/{skill_id}/languages")
    def api_tr_langs(skill_id: str) -> dict[str, Any]:
        try:
            return {"languages": translate.source_languages(skill_id)}
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))

    @r.api.get("/translate/{skill_id}/{lang}/files")
    def api_tr_files(skill_id: str, lang: str) -> dict[str, Any]:
        try:
            return {"files": translate.list_resources(skill_id, lang)}
        except (UnsafeIdentifier, translate.TranslateError) as err:
            raise HTTPException(400, str(err))

    @r.api.get("/translate/{skill_id}/{lang}/file/{file_name}")
    def api_tr_file(skill_id: str, lang: str, file_name: str) -> dict[str, Any]:
        try:
            return {"source": translate.read_source(skill_id, lang, file_name),
                    "override": translate.read_override(skill_id, lang, file_name)}
        except (UnsafeIdentifier, translate.TranslateError) as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    @r.api.post("/translate/{skill_id}/{lang}/machine")
    def api_tr_machine(skill_id: str, lang: str,
                       body: TranslateBody) -> dict[str, Any]:
        try:
            translate.validate_skill_id(skill_id)
            translate.validate_lang(lang)
            return translate.machine_translate(body.lines, body.source, body.target,
                                               body.plugin)
        except (UnsafeIdentifier, translate.TranslateError) as err:
            raise HTTPException(400, str(err))

    @r.api.put("/translate/{skill_id}/{lang}/file/{file_name}")
    def api_tr_put(skill_id: str, lang: str, file_name: str,
                   body: OverrideBody) -> dict[str, Any]:
        try:
            return translate.write_override(skill_id, lang, file_name, body.lines)
        except (UnsafeIdentifier, translate.TranslateError) as err:
            raise HTTPException(400, str(err))

    @r.api.delete("/translate/{skill_id}/{lang}/file/{file_name}")
    def api_tr_delete(skill_id: str, lang: str, file_name: str) -> dict[str, Any]:
        try:
            return translate.delete_override(skill_id, lang, file_name)
        except (UnsafeIdentifier, translate.TranslateError) as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))
