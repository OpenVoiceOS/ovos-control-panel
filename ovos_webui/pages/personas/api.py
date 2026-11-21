"""The personas page's API."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ovos_webui import configio, personas
from ovos_webui.fsutils import UnsafeIdentifier


class PersonaBody(BaseModel):
    persona: dict[str, Any]


class PersonaTestBody(BaseModel):
    question: str = Field(..., max_length=2000)


def routes(r) -> None:
    # ── personas ─────────────────────────────────────────────────────────────
    @r.api.get("/personas")
    def api_personas() -> dict[str, Any]:
        active = configio.user_or_merged(
            ["intents", "persona", "default_persona"])
        return {"personas": personas.list_personas(),
                "solvers": personas.available_solvers(),
                "memory_plugins": personas.available_memory_plugins(),
                "active": active,
                "path": str(personas.personas_root())}

    @r.api.post("/personas/{persona_id}/activate")
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
            bus=r.bus())
        # Warn if the persona's solvers are not installed — activating it is the
        # moment the user commits, so a silently-broken persona must be flagged.
        result.update({"active": name, "persona_id": persona_id,
                       "missing_solvers": personas.missing_solvers(data)})
        return result

    @r.api.get("/personas/{persona_id}")
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

    @r.api.put("/personas/{persona_id}")
    def api_persona_put(persona_id: str, body: PersonaBody) -> dict[str, Any]:
        try:
            return personas.write_persona(persona_id, body.persona)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except personas.PersonaError as err:
            raise HTTPException(400, str(err))

    @r.api.delete("/personas/{persona_id}")
    def api_persona_delete(persona_id: str) -> dict[str, Any]:
        try:
            return personas.delete_persona(persona_id)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))

    @r.api.post("/personas/{persona_id}/try")
    def api_persona_try(persona_id: str, body: PersonaTestBody) -> dict[str, Any]:
        try:
            return personas.try_persona(persona_id, body.question)
        except UnsafeIdentifier as err:
            raise HTTPException(400, str(err))
        except LookupError as err:
            raise HTTPException(404, str(err))
        except personas.PersonaError as err:
            raise HTTPException(400, str(err))
