"""The skills page's API."""
from typing import Any

from fastapi import HTTPException, Response
from pydantic import BaseModel

from ovos_webui import configio, skillsio
from ovos_webui.fsutils import UnsafeIdentifier, validate_skill_id as fsutils_validate_skill_id


class EnabledBody(BaseModel):
    enabled: bool


class SettingsBody(BaseModel):
    settings: dict[str, Any]


def routes(r) -> None:
        # ── skill settings ───────────────────────────────────────────────────────
    @r.api.get("/skills")
    def api_skills() -> dict[str, Any]:
        return {"skills": skillsio.list_skills()}

    @r.api.get("/skills/{skill_id}")
    def api_skill_get(skill_id: str, lang: str = "en") -> dict[str, Any]:
        try:
            return {
                "skill_id": skill_id,
                "settings": skillsio.read_settings(skill_id),
                "meta": skillsio.settings_meta(skill_id),
                # the same, as a form in the reader's language
                "form": skillsio.settings_form(skill_id, lang),
                "generated_meta": skillsio.find_settingsmeta(skill_id) is None,
                "path": str(skillsio.settings_path(skill_id)),
            }
        except (UnsafeIdentifier, skillsio.SkillSettingsError) as err:
            raise HTTPException(400, str(err)) from None

    @r.api.put("/skills/{skill_id}")
    def api_skill_put(skill_id: str, body: SettingsBody) -> dict[str, Any]:
        try:
            return skillsio.write_settings(skill_id, body.settings)
        except (UnsafeIdentifier, skillsio.SkillSettingsError) as err:
            raise HTTPException(400, str(err)) from None

    # ── skill enable / disable via the blacklist ─────────────────────────────
    @r.api.get("/skills/{skill_id}/enabled")
    def api_skill_enabled(skill_id: str) -> dict[str, Any]:
        try:
            skill_id = fsutils_validate_skill_id(skill_id)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        blacklist = configio.user_or_merged(
            ["skills", "blacklisted_skills"]) or []
        return {"skill_id": skill_id, "enabled": skill_id not in blacklist}

    @r.api.put("/skills/{skill_id}/enabled")
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

        result = configio.mutate(change, bus=r.bus())
        result.update({"skill_id": skill_id, "enabled": body.enabled})
        return result

    # ── what can it do: the installed skills ─────────────────────────────────
    @r.api.get("/skillinfo/{package}")
    def api_skill_info(package: str) -> dict[str, Any]:
        """Who made a skill, where its source is, and what to say to it."""
        from ovos_webui import skillinfo
        try:
            return skillinfo.info(package)
        except skillinfo.NotASkill as err:
            raise HTTPException(400, str(err)) from err
        except (OSError, ValueError) as err:
            raise HTTPException(502, f"could not read the details: {err}") from err

    @r.api.get("/skillinfo/{package}/icon")
    def api_skill_icon(package: str) -> Response:
        """A skill's icon, fetched by the panel so the page stays on its origin."""
        from ovos_webui import skillinfo
        found = skillinfo.icon(package)
        if found is None:
            raise HTTPException(404, "this skill has no icon to show")
        data, kind = found
        return Response(data, media_type=kind,
                        headers={"Cache-Control": "private, max-age=86400",
                                 "X-Content-Type-Options": "nosniff"})
