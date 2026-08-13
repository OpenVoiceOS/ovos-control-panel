"""Look inside the intent engine: what the device understands, and a dry run.

Everything here is an existing bus query — no new message type is added. The
messages and their replies were read from ovos-core's intent service:

- ``ovos.intent.list`` → ``ovos.intent.list.response`` (INTENT-4 §10): every
  registered intent, with its skill, language, method (keyword/template) and
  whether it is enabled. Optional ``skill_id`` / ``lang`` filters.
- ``ovos.intent.describe`` → ``ovos.intent.describe.response``: the full
  definition of one intent (needs skill_id, intent_name, lang).
- ``intent.service.intent.get`` → ``intent.service.intent.reply``: a DRY RUN —
  what intent an utterance would match, without running the skill.
- ``intent.service.active_skills.get`` → ``intent.service.active_skills.reply``:
  the skills currently active for converse, most recent first.
- ``intent.service.skills.activate`` / ``.deactivate`` (data ``skill_id``):
  move a skill in or out of that active set. These are fire-and-forget; the
  service broadcasts ``.activated`` / ``.deactivated`` and the caller re-reads
  the active list to see the result.

Each query has a hard deadline through :func:`ovos_webui.buswait.wait_for_response`,
so a silent bus never hangs a request; a query that gets no reply reports
``available: False`` rather than raising.
"""
from __future__ import annotations

from typing import Any

from ovos_webui import buswait

#: A manifest can be large; give the list query a little longer than a dry run.
LIST_TIMEOUT = 5.0
QUERY_TIMEOUT = 5.0

#: The longest a skill id or an utterance may be, so a hostile body cannot ride
#: a huge string onto the bus.
MAX_SKILL_ID = 255
MAX_UTTERANCE = 500


class IntentError(ValueError):
    """Raised when a skill id or utterance is not usable."""


def _msg(msg_type: str, data: dict[str, Any] | None = None):
    from ovos_bus_client.message import Message

    return Message(msg_type, data or {}, {"source": "ovos-webui"})


def list_intents(bus, skill_id: str | None = None, lang: str | None = None) -> dict[str, Any]:
    """Return every registered intent, optionally filtered by skill or language."""
    data: dict[str, Any] = {}
    if skill_id:
        data["skill_id"] = skill_id
    if lang:
        data["lang"] = lang
    reply = buswait.wait_for_response(
        bus, _msg("ovos.intent.list", data), timeout=LIST_TIMEOUT,
        reply_type="ovos.intent.list.response")
    if reply is None:
        return {"available": False, "intents": []}
    payload = reply.data or {}
    return {"available": True, "intents": payload.get("intents") or []}


def describe_intent(bus, skill_id: str, intent_name: str, lang: str) -> dict[str, Any]:
    """Return the full definition(s) of one intent."""
    reply = buswait.wait_for_response(
        bus, _msg("ovos.intent.describe",
                  {"skill_id": skill_id, "intent_name": intent_name, "lang": lang}),
        timeout=QUERY_TIMEOUT, reply_type="ovos.intent.describe.response")
    if reply is None:
        return {"available": False}
    payload = reply.data or {}
    return {"available": True, "ok": bool(payload.get("ok")),
            "definitions": payload.get("definitions") or [],
            "error": payload.get("error")}


def dry_run(bus, utterance: str) -> dict[str, Any]:
    """Ask the pipeline what ``utterance`` would match, without running a skill."""
    reply = buswait.wait_for_response(
        bus, _msg("intent.service.intent.get", {"utterance": utterance}),
        timeout=QUERY_TIMEOUT, reply_type="intent.service.intent.reply")
    if reply is None:
        return {"available": False, "utterance": utterance}
    payload = reply.data or {}
    return {"available": True, "intent": payload.get("intent"),
            "utterance": payload.get("utterance", utterance)}


def get_active_skills(bus) -> dict[str, Any]:
    """Return the skills active for converse, most recent first."""
    reply = buswait.wait_for_response(
        bus, _msg("intent.service.active_skills.get"),
        timeout=QUERY_TIMEOUT, reply_type="intent.service.active_skills.reply")
    if reply is None:
        return {"available": False, "skills": []}
    payload = reply.data or {}
    skills = payload.get("skills") or []
    return {"available": True, "skills": [s for s in skills if isinstance(s, str)]}


def _check_skill_id(skill_id: Any) -> str:
    if not isinstance(skill_id, str):
        raise IntentError("skill id must be text")
    skill_id = skill_id.strip()
    if not skill_id:
        raise IntentError("skill id must not be empty")
    if len(skill_id) > MAX_SKILL_ID or any(ord(c) < 0x20 or ord(c) == 0x7f for c in skill_id):
        raise IntentError("skill id must be a single short line")
    return skill_id


def set_skill_active(bus, skill_id: Any, active: bool) -> dict[str, Any]:
    """Activate or deactivate a skill for converse (fire-and-forget)."""
    skill_id = _check_skill_id(skill_id)
    msg_type = ("intent.service.skills.activate" if active
                else "intent.service.skills.deactivate")
    bus.emit(_msg(msg_type, {"skill_id": skill_id}))
    return {"ok": True, "skill_id": skill_id, "active": bool(active)}


def check_utterance(utterance: Any) -> str:
    """Validate a dry-run utterance, returning the trimmed text."""
    if not isinstance(utterance, str):
        raise IntentError("utterance must be text")
    utterance = utterance.strip()
    if not utterance:
        raise IntentError("utterance must not be empty")
    if len(utterance) > MAX_UTTERANCE:
        raise IntentError("utterance is too long")
    return utterance
