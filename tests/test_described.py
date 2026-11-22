"""Pages described in controlpanel.json: the file is checked, and the bus
bridge sends only what the file declares."""
import base64
import re
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
        {"type": "upload", "send": "ovos.demo.upload", "accept": [".TXT", ".pdf"], "max_mb": 1,
         "field": {"name": "title", "label": "demo.title"}},
    ],
}


def checked(page=None, package="ovos-phal-plugin-demo"):
    return described.check(json.loads(json.dumps(page or PAGE)), package)


def test_a_file_is_checked_and_numbered():
    page, refs = checked()
    assert [b["type"] for b in page["blocks"]] == ["text", "choice", "list", "form", "unknown", "upload"]
    assert set(refs) == {"b2", "b2.rename", "b2.a0", "b2.a1", "b2.a2", "b3.form", "b5.upload"}
    assert page["blocks"][5]["accept"] == [".pdf", ".txt"]
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
    answer("ovos.demo.upload", {"ok": True})
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


def test_a_described_page_brings_a_group_named_by_a_label(tmp_path):
    root = tmp_path / "ovos_skill_books"
    (root / "locale" / "en-US").mkdir(parents=True)
    (root / "locale" / "en-US" / "controlpanel.json").write_text('{"nav.group.shelf": "Shelf"}', encoding="utf-8")
    page = {"controlpanel": 1, "id": "shelf", "title": {"key": "shelf.title", "en": "Shelf"}, "bus": "ovos.shelf.",
            "group": "shelf", "groups": [{"id": "shelf", "title": "nav.group.shelf", "order": 5, "level": "everyday"}],
            "blocks": [{"type": "text", "text": "shelf.intro"}]}
    found = described.Found("ovos-skill-books", "1.0", "ovos_skill_books", root, page)
    _, groups = pages.parse_described(found, "ovos-skill-books", "1.0")
    assert groups == [{"id": "shelf", "key": "nav.group.shelf", "label": "Shelf", "order": 5, "level": "everyday"}]


def test_the_menu_carries_a_mark_of_the_pages_strings(tmp_path):
    """The browser keeps the strings it read; a page updated with new words
    changes the mark, so they are read again."""
    def reg(words):
        root = tmp_path / words
        (root / "locale" / "da-DK").mkdir(parents=True, exist_ok=True)
        (root / "locale" / "da-DK" / "controlpanel.json").write_text(json.dumps({"demo.title": words}))
        found = described.Found("ovos-phal-plugin-demo", "1.0", "ovos_phal_plugin_demo", root, PAGE)
        return pages.load([], files=[found])
    first, again, other = reg("Prøve"), reg("Prøve"), reg("Prøv")
    assert first.nav()["strings"] == again.nav()["strings"] != other.nav()["strings"]


def test_an_upload_goes_to_the_skill_in_parts(app, monkeypatch):
    c, seen = app
    monkeypatch.setattr(described, "UPLOAD_PART", 4)
    files = {"file": ("../../etc/My letter.txt", b"hello world", "text/plain")}
    form = {"ref": "b5.upload", "title": " Mit brev "}
    assert c.post("/api/cp/demo/upload", data=form, files=files).status_code in (401, 403), "it needs the token"
    c.headers["Authorization"] = "Bearer s3cret-token"
    assert c.post("/api/cp/demo/upload", data=form, files=files).json() == {"ok": True}
    parts = [d for t, d in seen if t == "ovos.demo.upload"]
    assert [p["part"] for p in parts] == [0, 1, 2] and {p["parts"] for p in parts} == {3}
    assert {p["name"] for p in parts} == {"My letter.txt"} and {p["title"] for p in parts} == {"Mit brev"}
    assert len({p["upload"] for p in parts}) == 1
    assert b"".join(base64.b64decode(p["data"]) for p in parts) == b"hello world"
    bad = {"file": ("x.exe", b"MZ", "application/octet-stream")}
    assert c.post("/api/cp/demo/upload", data={"ref": "b5.upload"}, files=bad).status_code == 415
    big = {"file": ("big.pdf", b"x" * (1024 * 1024 + 1), "application/pdf")}
    assert c.post("/api/cp/demo/upload", data={"ref": "b5.upload"}, files=big).status_code == 413
    assert c.post("/api/cp/demo/upload", data={"ref": "b2"}, files=files).status_code == 400


def test_a_list_can_have_a_filter():
    page = {"controlpanel": 1, "id": "f", "bus": "ovos.f.", "blocks": [
        {"type": "list", "query": "ovos.f.list", "items": "rows", "key": "id",
         "filter": {"by": "who", "label": "f.who"}}]}
    out, _ = checked(page, "ovos-skill-f")
    assert out["blocks"][0]["filter"] == {"by": "who", "label": {"key": "f.who"}, "all": {"key": "common.all"}}
    page["blocks"][0]["filter"] = {"by": "Who!", "label": "f.who"}
    with pytest.raises(described.DescribedError):
        checked(page, "ovos-skill-f")


STORY = {"controlpanel": 1, "id": "story", "title": {"key": "story.title", "en": "Story"},
         "bus": "ovos.story.", "pictures": "gui/images", "blocks": [
             {"type": "list", "query": "ovos.story.parts", "items": "parts", "key": "id",
              "title": "{title}", "text": "{text}", "picture": "image"}]}


def test_a_list_row_has_a_text_and_a_picture_from_the_pages_own_folder(bus, monkeypatch, tmp_path):
    out, _ = checked(STORY, "ovos-skill-story")
    assert out["blocks"][0]["text"] == "{text}" and out["blocks"][0]["picture"] == "image"
    root = tmp_path / "ovos_skill_story"
    (root / "gui" / "images").mkdir(parents=True)
    (root / "gui" / "images" / "me.png").write_bytes(b"\x89PNG")
    (root / "gui" / "images" / "notes.txt").write_text("not a picture", encoding="utf-8")
    found = described.Found("ovos-skill-story", "1.0", "ovos_skill_story", root, STORY)
    monkeypatch.setattr(described, "discover", lambda: [found])
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500", headers={"sec-fetch-site": "same-origin",
                                                                    "Authorization": "Bearer s3cret-token"}) as c:
        got = c.get("/pages/story/me.png")
        assert got.status_code == 200 and got.content == b"\x89PNG"
        # the folder serves pictures, nothing else
        assert c.get("/pages/story/notes.txt").status_code == 404
        assert c.get("/pages/story/..%2Fcontrolpanel.json").status_code == 404


@pytest.mark.parametrize("change", [lambda p: p.pop("pictures"), lambda p: p.update(pictures="../up")])
def test_a_picture_needs_a_folder_in_the_package(change, tmp_path):
    page = json.loads(json.dumps(STORY))
    change(page)
    root = tmp_path / "ovos_skill_story"
    root.mkdir()
    found = described.Found("ovos-skill-story", "1.0", "ovos_skill_story", root, page)
    with pytest.raises(pages.PageError):
        pages.parse_described(found, "ovos-skill-story", "1.0")


SHELF = {"controlpanel": 1, "id": "shelf", "title": {"key": "shelf.title", "en": "Shelf"}, "bus": "ovos.shelf.",
         "blocks": [{"type": "form", "save": {"settings": True}, "fields": [
             {"name": "url", "label": "shelf.url", "type": "url", "required": True},
             {"name": "token", "label": "shelf.token", "type": "password"},
             {"name": "hours", "label": "shelf.hours", "type": "number", "min": 1, "max": 24, "default": 6}]}]}


def test_only_a_skills_page_saves_in_its_settings():
    with pytest.raises(described.DescribedError, match="one skill"):
        described.check(SHELF, "ovos-phal-plugin-shelf")
    page, refs = described.check(SHELF, "ovos-skill-shelf", skill_id="ovos-skill-shelf.me")
    assert refs["b0.form"]["block"]["settings"] == "ovos-skill-shelf.me"
    bad = json.loads(json.dumps(SHELF))
    bad["blocks"][0]["save"] = {"settings": "ovos-skill-other.them"}
    with pytest.raises(described.DescribedError, match="settings is true"):
        described.check(bad, "ovos-skill-shelf", skill_id="ovos-skill-shelf.me")


def test_a_form_saves_in_the_skills_settings_json(bus, monkeypatch, tmp_path):
    from ovos_webui import skillsio
    root = tmp_path / "ovos_skill_shelf"
    root.mkdir()
    found = described.Found("ovos-skill-shelf", "1.0", "ovos_skill_shelf", root, SHELF)
    monkeypatch.setattr(described, "discover", lambda: [found])
    monkeypatch.setattr(pages, "_own_skill_id", lambda package: "ovos-skill-shelf.me")
    skillsio.write_settings("ovos-skill-shelf.me", {"token": "old", "counter": 7})
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        assert c.post("/api/cp/shelf/form", json={"ref": "b0.form", "values": {"url": "https://x.org"}}
                      ).status_code in (401, 403), "it needs the token"
        c.headers["Authorization"] = "Bearer s3cret-token"
        read = c.get("/api/cp/shelf/form", params={"ref": "b0.form"}).json()["values"]
        assert read == {"token": {"set": True}, "hours": 6}, "a password is never sent"
        assert c.post("/api/cp/shelf/form", json={"ref": "b0.form", "values": {"hours": 3}}).status_code == 400
        ok = c.post("/api/cp/shelf/form", json={"ref": "b0.form",
                                                "values": {"url": "https://x.org", "token": "", "hours": 3}})
        assert ok.json() == {"ok": True}
    assert skillsio.read_settings("ovos-skill-shelf.me") == \
        {"token": "old", "counter": 7, "url": "https://x.org", "hours": 3}, "the rest is kept"


def _bundle(tmp_path, monkeypatch, data):
    root = tmp_path / "bundled" / "ovos-skill-weather"
    (root / "locale" / "da-dk").mkdir(parents=True)
    (root / "controlpanel.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(described, "BUNDLED", tmp_path / "bundled")
    return root


def test_the_panel_brings_a_page_for_the_versions_it_was_written_for(tmp_path, monkeypatch):
    page = dict(SHELF, id="weather", **{"for": "ovos-skill-weather>=1.0,<2"})
    _bundle(tmp_path, monkeypatch, page)
    found = described._bundled("OVOS_Skill_Weather", "1.4.2a3", ["ovos_skill_weather"])
    assert found is not None and found.by_panel and found.package == "OVOS_Skill_Weather"
    assert described._bundled("ovos-skill-weather", "2.0.0", []) is None, "not written for 2.x"
    assert described._bundled("ovos-skill-other", "1.0", []) is None


@pytest.mark.parametrize("target", ["", "ovos-skill-other>=1", "not a requirement !"])
def test_a_page_the_panel_brings_must_say_what_it_is_for(tmp_path, monkeypatch, target):
    _bundle(tmp_path, monkeypatch, dict(SHELF, **{"for": target}))
    assert described._bundled("ovos-skill-weather", "1.0", []) is None


def test_a_page_the_panel_brings_says_so_at_its_foot(tmp_path, monkeypatch):
    root = _bundle(tmp_path, monkeypatch, dict(SHELF, **{"for": "ovos-skill-weather"}))
    monkeypatch.setattr(pages, "_own_skill_id", lambda package: "ovos-skill-weather.openvoiceos")
    found = described.Found("ovos-skill-weather", "1.0", "ovos_skill_weather", root, SHELF, by_panel=True)
    page, _ = pages.parse_described(found, "ovos-skill-weather", "1.0")
    assert page.by_panel
    monkeypatch.setattr(pages, "origin", lambda p, lang=None: {"package": p.package, "version": "1.0",
                                                                "name": "Weather", "icon": None})
    assert 'data-i18n="page.byPanel"' in pages._origin_html(page)
    page.by_panel = False
    assert "byPanel" not in pages._origin_html(page)


def test_a_plugin_saves_in_its_own_section_and_no_other(monkeypatch):
    from types import SimpleNamespace as NS
    eps = [NS(group="opm.tts", name="ovos-tts-plugin-server"), NS(group="opm.skill", name="x.y"),
           NS(group="opm.phal", name="ovos-phal-plugin-x")]
    monkeypatch.setattr(described.metadata, "distribution", lambda name: NS(entry_points=eps))
    roots = described.config_roots("ovos-tts-plugin-server")
    assert roots == ["PHAL.ovos-tts-plugin-server", "tts.ovos-tts-plugin-server", "PHAL.ovos-phal-plugin-x"]

    def form(path):
        return {"controlpanel": 1, "id": "t", "bus": "ovos.t.", "blocks": [
            {"type": "form", "save": {"config": path}, "fields": [{"name": "host", "label": "t.host"}]}]}
    described.check(form("tts.ovos-tts-plugin-server"), "ovos-tts-plugin-server", config_roots=roots)
    for bad in ("tts", "tts.module", "tts.ovos-tts-plugin-piper", "stt.ovos-tts-plugin-server"):
        with pytest.raises(described.DescribedError, match="own place"):
            described.check(form(bad), "ovos-tts-plugin-server", config_roots=roots)


def test_a_transformer_saves_in_its_service_section(monkeypatch):
    from types import SimpleNamespace as NS
    name = "ovos-audio-transformer-plugin-overheard-manners"
    eps = [NS(group="opm.transformer.audio", name=name)]
    monkeypatch.setattr(described.metadata, "distribution", lambda n: NS(entry_points=eps))
    roots = described.config_roots(name)
    assert roots == ["PHAL." + name, "audio_transformers." + name]
    page = {"controlpanel": 1, "id": "t", "bus": "ovos.t.", "blocks": [
        {"type": "form", "save": {"config": "audio_transformers." + name},
         "fields": [{"name": "enabled", "label": "t.on", "type": "checkbox"}]}]}
    described.check(page, name, config_roots=roots)


@pytest.mark.parametrize("group, section", [
    ("opm.transformer.text", "utterance_transformers"), ("neon.plugin.text", "utterance_transformers"),
    ("opm.transformer.metadata", "metadata_transformers"), ("opm.transformer.intent", "intent_transformers"),
    ("opm.transformer.dialog", "dialog_transformers"), ("opm.transformer.tts", "tts_transformers")])
def test_every_transformer_saves_where_the_transformers_page_orders_it(monkeypatch, group, section):
    from types import SimpleNamespace as NS
    monkeypatch.setattr(described.metadata, "distribution",
                        lambda n: NS(entry_points=[NS(group=group, name="my-transformer")]))
    assert described.config_roots("my-pkg")[-1] == section + ".my-transformer"


@pytest.mark.parametrize("folder", sorted(p.name for p in described.BUNDLED.iterdir() if p.is_dir()))
def test_every_page_the_panel_brings_is_sound(folder):
    """Each bundled page passes the checks for its package's own places, says
    what it is for, and has the same strings in every language."""
    from packaging.requirements import Requirement
    root = described.BUNDLED / folder
    data = json.loads((root / described.FILE).read_text(encoding="utf-8"))
    assert Requirement(data["for"]).name == folder
    kind = folder.split("-")[1]          # ovos-tts-plugin-server -> tts
    roots = ["PHAL." + folder] + ([f"{kind}.{folder}"] if kind in ("tts", "stt") else [])
    modules = {kind: [folder]} if kind in ("tts", "stt") else {}
    described.check(data, folder, config_roots=roots, modules=modules, by_panel=True)
    found = described.strings(root)
    assert "en" in found and "da" in found
    keys = set(found["en"])
    assert all(set(table) == keys for table in found.values()), "the same strings in every language"
    used = set(re.findall(r'"([a-z][\w]*\.[\w.]+)"', (root / described.FILE).read_text()))
    used -= {data.get("icon"), *data.get("messages", [])}
    assert {k for k in used if not k.startswith(("common.", "ovos."))} <= keys



VOICE = {"controlpanel": 1, "id": "voice-x", "title": {"key": "x.title", "en": "X"}, "bus": "ovos.voice-x.",
         "blocks": [{"type": "module", "kind": "tts"}]}


def test_a_module_block_is_only_for_a_plugin_of_that_kind():
    with pytest.raises(described.DescribedError, match="no tts plugin"):
        described.check(VOICE, "ovos-skill-x")
    with pytest.raises(described.DescribedError, match="kind"):
        described.check(dict(VOICE, blocks=[{"type": "module", "kind": "ww"}]), "x", modules={"tts": ["x"]})
    page, refs = described.check(VOICE, "ovos-tts-plugin-x", modules={"tts": ["ovos-tts-plugin-x"]})
    assert refs["b0.module"]["block"]["module"] == "ovos-tts-plugin-x"


def test_a_plugin_is_made_the_one_in_use_and_heard(bus, monkeypatch, tmp_path):
    root = tmp_path / "ovos_tts_plugin_x"
    root.mkdir()
    found = described.Found("ovos-tts-plugin-x", "1.0", "ovos_tts_plugin_x", root, VOICE)
    monkeypatch.setattr(described, "discover", lambda: [found])
    monkeypatch.setattr(described, "plugin_modules", lambda package: {"tts": ["ovos-tts-plugin-x"]})
    said = []
    bus.on("speak", lambda m: said.append(dict(m.data)))
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        assert c.post("/api/cp/voice-x/module", json={"ref": "b0.module", "as": "module"}
                      ).status_code in (401, 403), "it needs the token"
        c.headers["Authorization"] = "Bearer s3cret-token"
        state = c.get("/api/cp/voice-x/module", params={"ref": "b0.module"}).json()
        assert state["active"] is False
        hear = {"ref": "b0.module", "text": "Hej", "lang": "da-DK"}
        assert c.post("/api/cp/voice-x/module/test", json=hear).status_code == 409, "not the voice in use"
        assert c.post("/api/cp/voice-x/module", json={"ref": "b0.module", "as": "tts.module"}).status_code == 400
        state = c.post("/api/cp/voice-x/module", json={"ref": "b0.module", "as": "fallback_module"}).json()
        assert state["fallback"] is True and state["active"] is False
        state = c.post("/api/cp/voice-x/module", json={"ref": "b0.module", "as": "module"}).json()
        assert state["active"] is True
        assert c.post("/api/cp/voice-x/module/test", json=hear).json() == {"ok": True}
        assert c.post("/api/cp/voice-x/module/test", json=dict(hear, text="x" * 300)).status_code == 400
    import time
    time.sleep(0.2)
    assert said == [{"utterance": "Hej", "lang": "da-DK"}]


def test_a_package_that_names_itself_with_underscores_is_found(tmp_path, monkeypatch):
    """Some wheels say Name: ovos_tts_plugin_server; it is the same package."""
    from types import SimpleNamespace as NS
    _bundle(tmp_path, monkeypatch, dict(SHELF, **{"for": "ovos-skill-weather"}))
    dist = NS(metadata={"Name": "ovos_skill_weather"}, version="1.0", files=[], entry_points=[],
              read_text=lambda name: "")
    monkeypatch.setattr(described.metadata, "distributions", lambda: [dist])
    [found] = described.discover()
    assert found.package == "ovos-skill-weather" and found.by_panel


def test_a_package_the_panel_has_a_page_for_is_found_whatever_its_name(tmp_path, monkeypatch):
    """ovos-PHAL-sensors is named like neither a skill nor a plugin."""
    from types import SimpleNamespace as NS
    root = tmp_path / "bundled" / "ovos-phal-sensors"
    root.mkdir(parents=True)
    (root / "controlpanel.json").write_text(json.dumps(dict(SHELF, **{"for": "ovos-phal-sensors"})),
                                            encoding="utf-8")
    monkeypatch.setattr(described, "BUNDLED", tmp_path / "bundled")
    dists = [NS(metadata={"Name": name}, version="1.0", files=[], entry_points=[], read_text=lambda n: "")
             for name in ("ovos-PHAL-sensors", "requests")]
    monkeypatch.setattr(described.metadata, "distributions", lambda: dists)
    assert [f.package for f in described.discover()] == ["ovos-phal-sensors"]


def test_a_voice_field_is_only_for_a_tts_plugin():
    page = {"controlpanel": 1, "id": "v", "bus": "ovos.v.", "blocks": [{"type": "form", "save": {"settings": True},
            "fields": [{"name": "voice", "label": "v.voice", "type": "select", "voices": True}]}]}
    with pytest.raises(described.DescribedError, match="TTS plugin"):
        described.check(page, "ovos-skill-v", skill_id="ovos-skill-v.me")
    out, _ = described.check(page, "ovos-tts-plugin-v", skill_id="ovos-skill-v.me",
                             modules={"tts": ["ovos-tts-plugin-v"]})
    assert out["blocks"][0]["fields"][0]["voices"] == "ovos-tts-plugin-v"


def test_a_plugins_voices_are_read_in_a_process_of_their_own(monkeypatch):
    import subprocess
    calls = []
    configs = {"da-DK": [{"voice": "da_DK-talesyntese-medium", "display_name": "Talesyntese"}],
               "da": [{"voice": "da_DK-talesyntese-medium"}, {"voice": "da-other", "meta": {"display_name": "Anden"}}],
               "en-GB": [{"alan-low": {"voice": "alan-low", "offline": True}}], "sv": [{"voice": "sv"}]}

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="log line\n" + json.dumps(configs), stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(described, "_VOICES", {})
    voices = described.plugin_voices("ovos-tts-plugin-x", "1.0", "da-DK")
    assert voices == [{"value": "da_DK-talesyntese-medium", "label": "Talesyntese"},
                      {"value": "da-other", "label": "Anden"}]
    assert described.plugin_voices("ovos-tts-plugin-x", "1.0", "en-US") == [{"value": "alan-low", "label": "alan-low"}]
    assert len(calls) == 1, "read once per version"
    assert "-c" in calls[0] and calls[0][-1] == "ovos-tts-plugin-x"


def test_a_plugin_that_says_nothing_has_no_voices(monkeypatch):
    import subprocess

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(subprocess, "run", slow)
    monkeypatch.setattr(described, "_VOICES", {})
    assert described.plugin_voices("ovos-tts-plugin-slow", "1.0", "da") == []


def test_the_voices_code_runs_and_finds_nothing_for_an_unknown_plugin():
    import subprocess
    import sys
    done = subprocess.run([sys.executable, "-c", described._VOICES_CODE, "ovos-tts-plugin-none"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and json.loads(done.stdout) == {}


def test_the_menu_says_which_package_an_added_page_is_from(tmp_path):
    """So the Skills page can point to a skill's own page."""
    root = tmp_path / "ovos_phal_plugin_demo"
    root.mkdir()
    found = described.Found("ovos-phal-plugin-demo", "1.0", "ovos_phal_plugin_demo", root, PAGE)
    reg = pages.load([], files=[found])
    demo = next(p for p in reg.nav()["pages"] if p["id"] == "demo")
    assert demo["package"] == "ovos-phal-plugin-demo"
    assert all("package" not in p for p in reg.nav()["pages"] if p["id"] != "demo"), "the panel's own say nothing"


LAUNCHER = {"controlpanel": 1, "id": "apps", "title": "apps.title",
            "messages": ["ovos.phal.app_launcher.list", "ovos.phal.app_launcher.launch"],
            "blocks": [{"type": "list", "query": "ovos.phal.app_launcher.list", "items": "apps", "key": "name",
                        "actions": [{"label": "apps.launch", "send": "ovos.phal.app_launcher.launch"}]}]}


def test_only_a_page_the_panel_brings_may_name_other_messages():
    with pytest.raises(described.DescribedError, match="only a page the panel brings"):
        checked(LAUNCHER, "ovos-phal-plugin-app-launcher")
    page, refs = described.check(json.loads(json.dumps(LAUNCHER)), "ovos-phal-plugin-app-launcher", by_panel=True)
    assert refs["b0.a0"]["send"] == "ovos.phal.app_launcher.launch"
    # still only the messages it names
    bad = json.loads(json.dumps(LAUNCHER))
    bad["blocks"][0]["actions"][0]["send"] = "ovos.phal.app_launcher.close"
    with pytest.raises(described.DescribedError, match="not one of the page's messages"):
        described.check(bad, "ovos-phal-plugin-app-launcher", by_panel=True)


def test_a_button_that_gets_no_answer_is_sent_and_done(bus, monkeypatch, tmp_path):
    page = {"controlpanel": 1, "id": "w", "title": "w.title", "bus": "ovos.w.", "blocks": [
        {"type": "actions", "actions": [{"label": "w.next", "send": "ovos.w.next", "answer": False}]}]}
    root = tmp_path / "ovos_phal_plugin_w"
    root.mkdir()
    found = described.Found("ovos-phal-plugin-w", "1.0", "ovos_phal_plugin_w", root, page)
    monkeypatch.setattr(described, "discover", lambda: [found])
    seen = []
    bus.on("ovos.w.next", lambda m: seen.append(m.msg_type))
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500", headers={"sec-fetch-site": "same-origin",
                                                                    "Authorization": "Bearer s3cret-token"}) as c:
        got = c.post("/api/cp/w/act", json={"ref": "b0.a0"})
    assert got.status_code == 200 and got.json() == {} and seen == ["ovos.w.next"]


def test_the_apps_page_the_panel_brings_launches_by_name(bus, monkeypatch):
    root = described.BUNDLED / "ovos-phal-plugin-app-launcher"
    data = json.loads((root / "controlpanel.json").read_text(encoding="utf-8"))
    found = described.Found("ovos-PHAL-plugin-app-launcher", "0.0.1a4", "ovos_phal_plugin_app_launcher",
                            root, data, by_panel=True)
    monkeypatch.setattr(described, "discover", lambda: [found])
    seen = []

    def answer(msg_type, data):
        def handler(message):
            seen.append((message.msg_type, dict(message.data)))
            bus.emit(message.response(data))
        bus.on(msg_type, handler)

    answer("ovos.phal.app_launcher.list", {"apps": [{"name": "Firefox", "exec": "firefox"}]})
    answer("ovos.phal.app_launcher.launch", {"name": "Firefox", "success": True})
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500", headers={"sec-fetch-site": "same-origin"}) as c:
        assert c.post("/api/cp/apps/act", json={"ref": "b1.a0", "key": "Firefox"}).status_code in (401, 403)
        c.headers["Authorization"] = "Bearer s3cret-token"
        assert c.post("/api/cp/apps/query", json={"ref": "b1"}).json()["apps"][0]["name"] == "Firefox"
        assert c.post("/api/cp/apps/act", json={"ref": "b1.a0", "key": "Firefox"}).status_code == 200
    assert ("ovos.phal.app_launcher.launch", {"name": "Firefox"}) in seen


def test_the_wallpaper_page_lists_text_and_sends_what_gets_no_answer(bus, monkeypatch):
    root = described.BUNDLED / "ovos-phal-plugin-wallpaper-manager"
    data = json.loads((root / "controlpanel.json").read_text(encoding="utf-8"))
    found = described.Found("ovos-PHAL-plugin-wallpaper-manager", "0.2.8a2", "ovos_PHAL_plugin_wallpaper_manager",
                            root, data, by_panel=True)
    monkeypatch.setattr(described, "discover", lambda: [found])
    seen = []
    bus.on("ovos.wallpaper.manager.change.wallpaper", lambda m: seen.append(m.msg_type))

    def set_it(message):
        seen.append((message.msg_type, dict(message.data)))
        bus.emit(message.response({"wallpaper": message.data["url"]}))
    bus.on("ovos.wallpaper.manager.set.wallpaper", set_it)
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500", headers={"sec-fetch-site": "same-origin",
                                                                    "Authorization": "Bearer s3cret-token"}) as c:
        # "next": the plugin acts and does not answer
        assert c.post("/api/cp/wallpaper/act", json={"ref": "b1.a0"}).json() == {}
        # a row of the collection (a list of text) is set by its address
        assert c.post("/api/cp/wallpaper/act", json={"ref": "b4.a0", "key": "/home/me/sea.jpg"}).status_code == 200
    assert seen == ["ovos.wallpaper.manager.change.wallpaper",
                    ("ovos.wallpaper.manager.set.wallpaper", {"url": "/home/me/sea.jpg"})]


def test_a_list_that_listens_keeps_the_latest_of_each_key(bus, monkeypatch):
    from ovos_bus_client.message import Message
    root = described.BUNDLED / "ovos-phal-sensors"
    data = json.loads((root / "controlpanel.json").read_text(encoding="utf-8"))
    found = described.Found("ovos-PHAL-sensors", "0.1.1a1", "ovos_PHAL_sensors", root, data, by_panel=True)
    monkeypatch.setattr(described, "discover", lambda: [found])
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500", headers={"sec-fetch-site": "same-origin",
                                                                    "Authorization": "Bearer s3cret-token"}) as c:
        assert c.post("/api/cp/sensors/query", json={"ref": "b1"}).json() == {"items": []}
        for state in (21.5, 22.0):
            bus.emit(Message("ovos.phal.sensor", {"sensor_id": "pi_cpu_temp", "device_name": "pi",
                                                  "name": "cpu_temp", "state": state,
                                                  "attributes": {"unit_of_measurement": "°C"}}))
        bus.emit(Message("ovos.phal.binary_sensor", {"sensor_id": "pi_charging", "state": True}))
        bus.emit(Message("ovos.phal.sensor", {"state": 1}))  # no key: left out
        readings = c.post("/api/cp/sensors/query", json={"ref": "b1"}).json()["items"]
        onoff = c.post("/api/cp/sensors/query", json={"ref": "b2"}).json()["items"]
    assert [(r["sensor_id"], r["state"]) for r in readings] == [("pi_cpu_temp", 22.0)]
    assert [r["sensor_id"] for r in onoff] == ["pi_charging"] and "heard" in onoff[0]


def test_a_list_listens_only_to_the_pages_own_messages():
    page = {"controlpanel": 1, "id": "s", "bus": "ovos.s.", "blocks": [
        {"type": "list", "listen": ["ovos.phal.sensor"], "key": "id"}]}
    with pytest.raises(described.DescribedError, match="not one of the page's messages"):
        checked(page, "ovos-phal-plugin-s")
    page["blocks"][0]["listen"] = ["ovos.s.reading"]
    out, refs = checked(page, "ovos-phal-plugin-s")
    assert out["blocks"][0]["items"] == "items" and refs["b0"]["kind"] == "query"


def test_another_ui_reads_the_page_as_checked_with_its_strings(app):
    c, _ = app
    c.headers["Authorization"] = "Bearer s3cret-token"
    got = c.get("/api/cp/demo/page", params={"lang": "da-DK"}).json()
    assert got["lang"] == "da" and got["strings"]["demo.title"] == "Prøve"
    blocks = got["page"]["blocks"]
    assert blocks[2]["type"] == "list" and blocks[2]["ref"] == "b2"
    assert got["page"]["en"]["demo.intro"] == "Hello", "the English texts come along"


def test_the_list_of_pages_says_which_are_described(app):
    c, _ = app
    c.headers["Authorization"] = "Bearer s3cret-token"
    listed = {p["id"]: p["described"] for p in c.get("/api/pages").json()["pages"]}
    assert listed["demo"] is True and listed["about"] is False


def test_what_cannot_be_undone_asks_for_a_typed_word():
    page = {"controlpanel": 1, "id": "w", "title": "w.title", "bus": "ovos.w.", "blocks": [
        {"type": "actions", "actions": [{"label": "w.wipe", "send": "ovos.w.wipe", "answer": False,
                                         "confirm": "w.type", "confirm_text": "RESET", "done": "w.sent"}]}]}
    out, _ = checked(page, "ovos-phal-plugin-w")
    action = out["blocks"][0]["actions"][0]
    assert action["confirm_text"] == "RESET" and action["done"] == {"key": "w.sent"}
    for bad in ("reset", "R", {"word": 1}):
        page["blocks"][0]["actions"][0]["confirm_text"] = bad
        with pytest.raises(described.DescribedError, match="confirm_text"):
            checked(page, "ovos-phal-plugin-w")
    page["blocks"][0]["actions"][0].update(confirm_text="RESET")
    page["blocks"][0]["actions"][0].pop("confirm")
    with pytest.raises(described.DescribedError, match="confirm_text"):
        checked(page, "ovos-phal-plugin-w")


def test_the_system_page_the_panel_brings_reads_ssh_and_resets_only_on_its_word(bus, monkeypatch):
    root = described.BUNDLED / "ovos-phal-plugin-system"
    data = json.loads((root / "controlpanel.json").read_text(encoding="utf-8"))
    found = described.Found("ovos-PHAL-plugin-system", "1.3.8a4", "ovos_PHAL_plugin_system", root, data,
                            by_panel=True)
    monkeypatch.setattr(described, "discover", lambda: [found])
    seen = []
    bus.on("system.ssh.status", lambda m: bus.emit(m.response({"enabled": False})))
    bus.on("system.ssh.enable", lambda m: seen.append(m.msg_type))
    bus.on("system.factory.reset", lambda m: seen.append(m.msg_type))
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500", headers={"sec-fetch-site": "same-origin",
                                                                    "Authorization": "Bearer s3cret-token"}) as c:
        assert c.post("/api/cp/system/query", json={"ref": "b1"}).json() == {"enabled": False}
        assert c.post("/api/cp/system/act", json={"ref": "b1.a0"}).json() == {}
        page = c.get("/api/cp/system/page").json()["page"]
    reset = page["blocks"][4]["actions"][0]
    assert reset["confirm_text"] == "RESET" and reset["done"]["key"] == "system.factory.sent"
    assert seen == ["system.ssh.enable"], "the reset is never sent without the typed word"
