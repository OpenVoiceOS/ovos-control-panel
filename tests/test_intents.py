"""Intent inspector: dry run, active skills, manifest list/describe, and
activate/deactivate — over a FakeBus, plus the privileged HTTP routes.

The bus messages and replies are the real ones from ovos-core's intent
service (verified against source): ``ovos.intent.list`` /
``ovos.intent.describe``, ``intent.service.intent.get`` (dry run),
``intent.service.active_skills.get``, and ``intent.service.skills.activate`` /
``.deactivate``.
"""
import pytest

from ovos_webui import intents

_AUTH = {"Authorization": "Bearer s3cret-token"}


def _reply(bus, req_topic, reply_topic, data):
    from ovos_bus_client.message import Message
    bus.on(req_topic, lambda m: bus.emit(Message(reply_topic, data, m.context)))


# ── list ─────────────────────────────────────────────────────────────────────

def test_list_intents_returns_the_manifest(bus):
    _reply(bus, "ovos.intent.list", "ovos.intent.list.response",
           {"ok": True, "intents": [
               {"skill_id": "time.skill", "intent_name": "what_time",
                "lang": "en-us", "method": "keyword", "enabled": True}]})
    out = intents.list_intents(bus)
    assert out["available"] is True
    assert out["intents"][0]["intent_name"] == "what_time"


def test_list_intents_unavailable_when_no_reply(bus):
    intents.LIST_TIMEOUT = 0.3
    out = intents.list_intents(bus)
    assert out == {"available": False, "intents": []}


def test_list_intents_passes_skill_filter(bus):
    seen = {}
    from ovos_bus_client.message import Message

    def handler(m):
        seen.update(m.data)
        bus.emit(Message("ovos.intent.list.response", {"intents": []}, m.context))
    bus.on("ovos.intent.list", handler)
    intents.list_intents(bus, skill_id="foo.skill", lang="pt-pt")
    assert seen == {"skill_id": "foo.skill", "lang": "pt-pt"}


# ── dry run ──────────────────────────────────────────────────────────────────

def test_dry_run_reports_the_matched_intent(bus):
    _reply(bus, "intent.service.intent.get", "intent.service.intent.reply",
           {"intent": {"skill_id": "time.skill", "intent_name": "what_time",
                       "intent_service": "adapt", "handler": "handle_time"},
            "utterance": "what time is it"})
    out = intents.dry_run(bus, "what time is it")
    assert out["available"] is True
    assert out["intent"]["skill_id"] == "time.skill"


def test_dry_run_reports_no_match(bus):
    _reply(bus, "intent.service.intent.get", "intent.service.intent.reply",
           {"intent": None, "utterance": "blorp"})
    out = intents.dry_run(bus, "blorp")
    assert out["available"] is True
    assert out["intent"] is None


def test_dry_run_unavailable_when_no_reply(bus):
    intents.QUERY_TIMEOUT = 0.3
    out = intents.dry_run(bus, "x")
    assert out["available"] is False


# ── active skills ────────────────────────────────────────────────────────────

def test_active_skills_returns_the_list(bus):
    _reply(bus, "intent.service.active_skills.get",
           "intent.service.active_skills.reply", {"skills": ["a.skill", "b.skill"]})
    out = intents.get_active_skills(bus)
    assert out["available"] is True
    assert out["skills"] == ["a.skill", "b.skill"]


def test_active_skills_drops_non_string_entries(bus):
    _reply(bus, "intent.service.active_skills.get",
           "intent.service.active_skills.reply", {"skills": ["ok.skill", 5, None]})
    assert intents.get_active_skills(bus)["skills"] == ["ok.skill"]


# ── activate / deactivate ────────────────────────────────────────────────────

def test_activate_emits_the_activate_message(bus):
    sent = []
    bus.on("intent.service.skills.activate", lambda m: sent.append(m.data))
    out = intents.set_skill_active(bus, "my.skill", True)
    assert out == {"ok": True, "skill_id": "my.skill", "active": True}
    assert sent == [{"skill_id": "my.skill"}]


def test_deactivate_emits_the_deactivate_message(bus):
    sent = []
    bus.on("intent.service.skills.deactivate", lambda m: sent.append(m.data))
    intents.set_skill_active(bus, "my.skill", False)
    assert sent == [{"skill_id": "my.skill"}]


def test_activate_rejects_a_bad_skill_id(bus):
    for bad in ("", "   ", "has\nnewline", 5):
        with pytest.raises(intents.IntentError):
            intents.set_skill_active(bus, bad, True)


def test_check_utterance_rejects_empty_and_oversized():
    with pytest.raises(intents.IntentError):
        intents.check_utterance("   ")
    with pytest.raises(intents.IntentError):
        intents.check_utterance("x" * (intents.MAX_UTTERANCE + 1))


# ── describe ─────────────────────────────────────────────────────────────────

def test_describe_returns_definitions(bus):
    _reply(bus, "ovos.intent.describe", "ovos.intent.describe.response",
           {"ok": True, "definitions": [{"method": "keyword", "definition": {"x": 1}}]})
    out = intents.describe_intent(bus, "s.skill", "an_intent", "en-us")
    assert out["ok"] is True and out["definitions"][0]["method"] == "keyword"


# ── HTTP routes ──────────────────────────────────────────────────────────────

def test_intents_page_needs_auth(token_client):
    r = token_client.get("/intents", follow_redirects=False)
    assert r.status_code in (302, 303)


def test_intents_routes_need_a_token(token_client):
    assert token_client.get("/api/intents").status_code in (401, 403)
    assert token_client.get("/api/intents/active").status_code in (401, 403)
    assert token_client.post("/api/intents/dry-run",
                             json={"utterance": "hi"}).status_code in (401, 403)


def test_api_list_roundtrip(token_client, bus):
    _reply(bus, "ovos.intent.list", "ovos.intent.list.response",
           {"intents": [{"skill_id": "s", "intent_name": "i", "lang": "en-us",
                         "method": "keyword", "enabled": True}]})
    r = token_client.get("/api/intents", headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["intents"][0]["intent_name"] == "i"


def test_api_dry_run_roundtrip(token_client, bus):
    _reply(bus, "intent.service.intent.get", "intent.service.intent.reply",
           {"intent": {"skill_id": "s", "intent_name": "i"}, "utterance": "hi"})
    r = token_client.post("/api/intents/dry-run", headers=_AUTH, json={"utterance": "hi"})
    assert r.status_code == 200
    assert r.json()["intent"]["skill_id"] == "s"


def test_api_dry_run_rejects_blank(token_client, bus):
    r = token_client.post("/api/intents/dry-run", headers=_AUTH, json={"utterance": "   "})
    assert r.status_code == 400


def test_api_activate_roundtrip(token_client, bus):
    sent = []
    bus.on("intent.service.skills.activate", lambda m: sent.append(m.data))
    r = token_client.post("/api/intents/skills/my.skill/active", headers=_AUTH,
                          json={"active": True})
    assert r.status_code == 200
    assert sent == [{"skill_id": "my.skill"}]
