"""The intents page's API."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ovos_webui import intents


class DescribeIntentBody(BaseModel):
    skill_id: str = Field(max_length=intents.MAX_SKILL_ID)
    intent_name: str = Field(max_length=255)
    lang: str = Field(max_length=16)


class DryRunBody(BaseModel):
    utterance: str = Field(max_length=intents.MAX_UTTERANCE)


class SkillActiveBody(BaseModel):
    active: bool


def routes(r) -> None:
    # ── intent inspector ──────────────────────────────────────────────────────
    # Read-only queries into the intent engine, plus activate/deactivate. Every
    # one is an existing bus query (see ovos_webui/intents.py); no new message.
    @r.privileged.get("/intents")
    def api_intents_list(skill_id: str | None = None,
                         lang: str | None = None) -> dict[str, Any]:
        return intents.list_intents(r.need_bus(), skill_id, lang)

    @r.privileged.get("/intents/active")
    def api_intents_active() -> dict[str, Any]:
        return intents.get_active_skills(r.need_bus())

    @r.privileged.post("/intents/describe")
    def api_intents_describe(body: DescribeIntentBody) -> dict[str, Any]:
        return intents.describe_intent(r.need_bus(), body.skill_id,
                                       body.intent_name, body.lang)

    @r.privileged.post("/intents/dry-run")
    def api_intents_dry_run(body: DryRunBody) -> dict[str, Any]:
        try:
            utterance = intents.check_utterance(body.utterance)
        except intents.IntentError as err:
            raise HTTPException(400, str(err)) from None
        return intents.dry_run(r.need_bus(), utterance)

    @r.privileged.post("/intents/skills/{skill_id}/active")
    def api_intents_skill_active(skill_id: str, body: SkillActiveBody) -> dict[str, Any]:
        try:
            return intents.set_skill_active(r.need_bus(), skill_id, body.active)
        except intents.IntentError as err:
            raise HTTPException(400, str(err)) from None
