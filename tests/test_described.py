"""Pages described in controlpanel.json: the file is checked, and the bus
bridge sends only what the file declares."""
import base64
import json

import pytest
from fastapi.testclient import TestClient

from ovos_webui import described, pages
from ovos_webui.service import create_app

PAGE = {
    "controlpanel": 1, "id": "demo", "title": {"key": "demo.title", "en": "Demo"},
    "group": "everyday", "bus": "ovos.demo.",
    "blocks": [
        {"type": "text", "text": {"key": "demo.intro", "en": "Hello"}},
        {"type": "choice", "param": "period", "options": [
            {"value": "today", "label": "demo.today"}, {"value": "week", "label": "demo.week"}]},
        {"type": "list", "query": "ovos.demo.list", "items": "things", "key": "id", "title": "{name}",
         "rename": {"field": "name", "send": "ovos.demo.rename", "when": "!fixed", "max_length": 20},
         "actions": [{"label": "common.delete", "send": "ovos.demo.delete", "when": "!fixed"},
                     {"label": "common.download", "download": "ovos.demo.file",
                      "file": {"data": "data", "name": "{name}.txt", "type": "text/plain"}},
                     {"label": "common.play", "send": "ovos.demo.play", "privileged": False}]},
        {"type": "form", "save": {"config": "PHAL.ovos-phal-plugin-demo", "reload": "ovos.demo.reload"},
         "fields": [{"name": "colour", "label": "demo.colour", "type": "select",
                     "options": [{"value": "red", "label": "demo.red"}, {"value": "blue", "label": "demo.blue"}]},
                    {"name": "loud", "label": "demo.loud", "type": "slider", "min": 0, "max": 10},
                    {"name": "secret", "label": "demo.secret", "type": "password"}]},
        {"type": "sparkles", "what": "a block from the future"},
    ],
}


def checked(page=None, package="ovos-phal-plugin-demo"):
    return described.check(json.loads(json.dumps(page or PAGE)), package)


def test_a_file_is_checked_and_numbered():
    page, refs = checked()
    assert [b["type"] for b in page["blocks"]] == ["text", "choice", "list", "form", "unknown"]
    assert set(refs) == {"b2", "b2.rename", "b2.a0", "b2.a1", "b2.a2", "b3.form"}
    assert refs["b2.a0"]["confirm"] == {"key": "common.sure"}, "a delete always asks first"
    assert refs["b2.a0"]["privileged"] and not refs["b2.a2"]["privileged"]
    assert not refs["b2.a1"]["privileged"], "a download is a read"


@pytest.mark.parametrize("change, why", [
    (lambda p: p.update(bus="mycroft."), "own prefix"),
    (lambda p: p.update(bus="ovos.skills."), "own prefix"),
    (lambda p: p["blocks"][2].update(query="ovos.other.list"), "not one of the page's messages"),
    (lambda p: p["blocks"][2]["actions"][0].update(send="mycroft.reboot"), "not one of the page's messages"),
    (lambda p: p["blocks"][3]["save"].update(config="PHAL.ovos-phal-plugin-system"), "own place"),
    (lambda p: p["blocks"][3]["save"].update(config="webui"), "own place"),
    (lambda p: p["blocks"][2]["actions"][1]["file"].update(type="text/html"), "a download is one of"),
    (lambda p: p.update(controlpanel=99), "this panel draws"),
])
def test_a_file_that_reaches_outside_its_own_is_refused(change, why):
    page = json.loads(json.dumps(PAGE))
    change(page)
    with pytest.raises(described.DescribedError, match=why):
        checked(page)


def test_a_request_can_only_send_what_the_file_says():
    _, refs = checked()
    assert described.message_for(refs, "b2", {"params": {"period": "week"}}) [:2] == \
        ("ovos.demo.list", {"period": "week"})
    with pytest.raises(described.DescribedError):
        described.message_for(refs, "b2", {"params": {"period": "forever"}})
    with pytest.raises(described.DescribedError):
        described.message_for(refs, "b2", {"params": {"cmd": "x"}})
    msg, data, _ = described.message_for(refs, "b2.a0", {"key": "a1", "extra": "ignored"})
    assert (msg, data) == ("ovos.demo.delete", {"id": "a1"})
    msg, data, _ = described.message_for(refs, "b2.rename", {"key": "a1", "value": " New "})
    assert (msg, data) == ("ovos.demo.rename", {"id": "a1", "name": "New"})
    with pytest.raises(described.DescribedError, match="too long"):
        described.message_for(refs, "b2.rename", {"key": "a1", "value": "x" * 21})
    with pytest.raises(described.DescribedError):
        described.message_for(refs, "b9", {})


def test_form_values_are_checked_by_their_field():
    _, refs = checked()
    form = refs["b3.form"]
    assert described.form_values(form, {"colour": "red", "loud": 3, "secret": "", "nope": 1}) == \
        {"colour": "red", "loud": 3}, "an empty password keeps the one there is; unknown fields go"
    for bad in ({"colour": "green"}, {"loud": 11}, {"loud": "3"}):
        with pytest.raises(described.DescribedError):
            described.form_values(form, bad)


@pytest.fixture
def app(bus, monkeypatch, tmp_path):
    root = tmp_path / "ovos_phal_plugin_demo"
    (root / "locale" / "da-DK").mkdir(parents=True)
    (root / "locale" / "da-DK" / "controlpanel.json").write_text('{"demo.title": "Prøve"}', encoding="utf-8")
    found = described.Found("ovos-phal-plugin-demo", "1.0", "ovos_phal_plugin_demo", root, PAGE)
    monkeypatch.setattr(described, "discover", lambda: [found])
    things = {"things": [{"id": "a1", "name": "Mine", "fixed": False},
                         {"id": "b2", "name": "Theirs", "fixed": True}]}
    seen = []

    def answer(msg_type, data):
        def handler(message):
            seen.append((message.msg_type, dict(message.data)))
            bus.emit(message.response(data))
        bus.on(msg_type, handler)

    answer("ovos.demo.list", things)
    answer("ovos.demo.delete", {"ok": True})
    answer("ovos.demo.play", {"ok": True})
    answer("ovos.demo.file", {"name": "Mine", "data": base64.b64encode(b"hello").decode()})
    bus.on("ovos.demo.reload", lambda m: seen.append((m.msg_type, {})))
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        yield c, seen


def test_the_page_is_served_and_drawn_from_the_file(app):
    c, _ = app
    c.headers["Authorization"] = "Bearer s3cret-token"
    page = c.get("/demo")
    assert page.status_code == 200 and 'id="cp-desc"' in page.text and "/static/described.js" in page.text
    assert c.get("/static/i18n/da.json").json()["demo.title"] == "Prøve"
    nav = [p for p in pages.load(files=described.discover()).pages if p.id == "demo"]
    assert nav and nav[0].described


def test_the_bridge_reads_acts_and_downloads(app):
    c, seen = app
    c.headers["Authorization"] = "Bearer s3cret-token"
    assert c.post("/api/cp/demo/query", json={"ref": "b2", "params": {"period": "week"}}).json()["things"]
    assert seen[-1] == ("ovos.demo.list", {"period": "week"})
    assert c.post("/api/cp/demo/act", json={"ref": "b2.a0", "key": "a1"}).json() == {"ok": True}
    assert seen[-1] == ("ovos.demo.delete", {"id": "a1"})
    assert c.post("/api/cp/demo/act", json={"ref": "b2", "key": "a1"}).status_code == 400
    r = c.get("/api/cp/demo/download", params={"ref": "b2.a1", "key": "a1"})
    assert r.content == b"hello" and r.headers["content-type"].startswith("text/plain")
    assert 'filename="Mine.txt"' in r.headers["content-disposition"]


def test_changes_need_the_token_and_reads_do_not(app):
    c, _ = app
    c.headers.pop("Authorization", None)
    assert c.post("/api/cp/demo/act", json={"ref": "b2.a0", "key": "a1"}).status_code == 401
    # a page's read-only action may go without the token; a change may not
    assert c.post("/api/cp/demo/act-open", json={"ref": "b2.a2", "key": "a1"}).status_code == 401
    c.headers["Authorization"] = "Bearer s3cret-token"
    assert c.post("/api/cp/demo/act-open", json={"ref": "b2.a0", "key": "a1"}).status_code == 403


def test_a_form_saves_in_the_plugins_own_place_and_reloads_it(app):
    from ovos_webui import configio
    c, seen = app
    c.headers["Authorization"] = "Bearer s3cret-token"
    r = c.post("/api/cp/demo/form", json={"ref": "b3.form", "values": {"colour": "blue", "loud": 4, "secret": "x"}})
    assert r.status_code == 200, r.text
    mine = json.loads(configio.user_config_path().read_text())["PHAL"]["ovos-phal-plugin-demo"]
    assert mine == {"colour": "blue", "loud": 4, "secret": "x"}
    assert ("ovos.demo.reload", {}) in seen
    values = c.get("/api/cp/demo/form", params={"ref": "b3.form"}).json()["values"]
    assert values["colour"] == "blue" and values["secret"] == {"set": True}, "a password never comes back"
    assert c.post("/api/cp/demo/form", json={"ref": "b3.form", "values": {"colour": "green"}}).status_code == 400


def test_buttons_with_fixed_data_and_settings_that_are_not_yes_or_no():
    page = {"controlpanel": 1, "id": "midi", "bus": "ovos.midi.", "blocks": [
        {"type": "status", "query": "ovos.midi.status",
         "rows": [{"label": "midi.plays", "value": "{engine@midi.engine}"}],
         "actions": [{"label": "midi.test", "send": "ovos.midi.events", "privileged": False,
                      "data": {"events": [["note", 0, 0, 60, 90, 1]]}}]},
        {"type": "form", "save": {"config": "PHAL.ovos-phal-plugin-midi"},
         "fields": [{"name": "inputs", "label": "midi.listen", "type": "checkbox", "on": ["*"], "off": []},
                    {"name": "duck", "label": "midi.duck", "type": "checkbox", "default": True},
                    {"name": "output_port", "label": "midi.port", "type": "select",
                     "options_from": {"query": "ovos.midi.status", "items": "ports.outputs"},
                     "show_when": {"synth": "port"}}]}]}
    _, refs = checked(page, "ovos-phal-plugin-midi")
    msg, data, _ = described.message_for(refs, "b0.a0", {"key": "ignored"})
    assert msg == "ovos.midi.events" and data["events"][0][3] == 60
    assert described.form_values(refs["b1.form"], {"inputs": True, "duck": True}) == {"inputs": ["*"], "duck": True}
    assert described.form_values(refs["b1.form"], {"inputs": False})["inputs"] == []
    bad = json.loads(json.dumps(page))
    bad["blocks"][0]["actions"][0]["data"] = {"x": "y" * 5000}
    with pytest.raises(described.DescribedError, match="small"):
        checked(bad, "ovos-phal-plugin-midi")


def test_addresses_and_required_fields():
    page = {"controlpanel": 1, "id": "ha", "bus": "ovos.ha_link.", "blocks": [
        {"type": "form", "save": {"config": "PHAL.ovos-phal-plugin-ha-link"},
         "fields": [{"name": "url", "label": "x", "type": "url", "required": True},
                    {"name": "token", "label": "x", "type": "password", "required": True}]}]}
    _, refs = checked(page, "ovos-phal-plugin-ha-link")
    form = refs["b0.form"]
    assert described.form_values(form, {"url": " http://ha.local:8123/ "}) == {"url": "http://ha.local:8123"}
    with pytest.raises(described.DescribedError, match="http"):
        described.form_values(form, {"url": "ha.local"})
    with pytest.raises(described.DescribedError, match="needed"):
        described.form_values(form, {"url": ""})
    assert described.missing(form, {"url": "http://x"}, {}) == ["token"], "a token the first time"
    assert described.missing(form, {"url": "http://x"}, {"token": "t"}) == [], "then it is kept"


def test_a_text_can_be_numbered_steps():
    page = {"controlpanel": 1, "id": "s", "bus": "ovos.s.", "blocks": [
        {"type": "text", "steps": ["s.one", {"key": "s.two", "en": "Two"}]},
        {"type": "text", "text": "s.intro", "steps": ["s.one"]}]}
    out, _ = checked(page, "ovos-skill-s")
    assert out["blocks"][0]["steps"] == [{"key": "s.one"}, {"key": "s.two", "en": "Two"}]
    assert "text" not in out["blocks"][0]
    assert out["blocks"][1]["text"] == {"key": "s.intro"}
    page["blocks"][0]["steps"] = []
    with pytest.raises(described.DescribedError, match="steps"):
        checked(page, "ovos-skill-s")


def test_a_status_row_without_a_label_is_a_note():
    page = {"controlpanel": 1, "id": "n", "bus": "ovos.n.", "blocks": [
        {"type": "status", "query": "ovos.n.status",
         "rows": [{"text": "n.hint", "when": "server"}, {"label": "n.state", "value": "{state}"}]}]}
    out, _ = checked(page, "ovos-skill-n")
    note, row = out["blocks"][0]["rows"]
    assert "label" not in note and note["text"] == {"key": "n.hint"} and row["label"] == {"key": "n.state"}
    page["blocks"][0]["rows"] = [{"when": "x"}]
    with pytest.raises(described.DescribedError, match="note"):
        checked(page, "ovos-skill-n")
