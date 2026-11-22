"""A described page's qr block: a button, and a field of its answer drawn as a
QR code, never shown as text."""
import json

import pytest
from fastapi.testclient import TestClient

from ovos_webui import described
from ovos_webui.service import create_app

PAGE = {
    "controlpanel": 1, "id": "house", "title": {"key": "house.title", "en": "House"}, "bus": "ovos.house.",
    "blocks": [{"type": "qr", "heading": {"key": "house.add", "en": "Add a device"},
                "text": {"key": "house.add.intro", "en": "Scan it with the device"},
                "action": {"label": {"key": "house.add.button", "en": "Show the code"}, "send": "ovos.house.pair"},
                "field": "url", "expires": "seconds",
                "note": {"key": "house.add.note", "en": "Within {minutes} minutes"}}],
}


def checked(page=None):
    return described.check(json.loads(json.dumps(page or PAGE)), "ovos-phal-plugin-house")


def test_a_qr_block_is_checked_like_any_other():
    page, refs = checked()
    block = page["blocks"][0]
    assert block["type"] == "qr" and block["field"] == "url" and block["expires"] == "seconds"
    assert block["action"]["ref"] == "b0.a0" and block["action"]["privileged"] is True
    assert refs["b0.a0"]["send"] == "ovos.house.pair"


@pytest.mark.parametrize("change, why", [
    (lambda b: b.update(action={"label": "x", "send": "mycroft.stop"}), "mycroft"),
    (lambda b: b.update(action={"label": "x", "send": "ovos.house.pair", "answer": False}), "reads its answer"),
    (lambda b: b.update(action={"label": "x", "download": "ovos.house.file", "file": {"type": "text/plain"}}),
     "reads its answer"),
    (lambda b: b.update(field="no such field!"), "not a field"),
    (lambda b: b.pop("action"), "not an action"),
])
def test_a_qr_block_that_reaches_too_far_is_refused(change, why):
    page = json.loads(json.dumps(PAGE))
    change(page["blocks"][0])
    with pytest.raises(described.DescribedError, match=why):
        checked(page)


def test_the_schema_knows_the_qr_block():
    from pathlib import Path
    import jsonschema
    import ovos_webui
    schema = json.loads((Path(ovos_webui.__file__).parents[1] / "docs" / "controlpanel.schema.json").read_text())
    jsonschema.validate(PAGE, schema)


@pytest.fixture
def client(bus, monkeypatch, tmp_path):
    root = tmp_path / "ovos_phal_plugin_house"
    root.mkdir()
    found = described.Found("ovos-phal-plugin-house", "1.0", "ovos_phal_plugin_house", root, PAGE)
    monkeypatch.setattr(described, "discover", lambda: [found])
    bus.on("ovos.house.pair", lambda m: bus.emit(m.response(
        {"url": "https://house.local/pair#t=secret", "seconds": 600, "minutes": 10})))
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500", headers={"sec-fetch-site": "same-origin"}) as c:
        yield c


def test_the_button_needs_the_token_and_gets_the_answer(client):
    assert client.post("/api/cp/house/act", json={"ref": "b0.a0"}).status_code in (401, 403)
    client.headers["Authorization"] = "Bearer s3cret-token"
    assert client.post("/api/cp/house/act-open", json={"ref": "b0.a0"}).status_code == 403, \
        "the code is privileged: not through the open door"
    r = client.post("/api/cp/house/act", json={"ref": "b0.a0"})
    assert r.status_code == 200 and r.json()["url"].endswith("#t=secret")


def test_the_qr_library_is_served_with_its_licence(client):
    client.headers["Authorization"] = "Bearer s3cret-token"
    r = client.get("/static/vendor/qrcode/qrcode.js")
    assert r.status_code == 200 and "Kazuhiko Arase" in r.text and "MIT" in r.text


def test_an_action_can_take_the_name_the_panel_was_opened_by(bus, monkeypatch, tmp_path):
    page = json.loads(json.dumps(PAGE))
    page["blocks"][0]["action"]["host"] = True
    root = tmp_path / "ovos_phal_plugin_house"
    root.mkdir()
    found = described.Found("ovos-phal-plugin-house", "1.0", "ovos_phal_plugin_house", root, page)
    monkeypatch.setattr(described, "discover", lambda: [found])
    seen = []
    bus.on("ovos.house.pair", lambda m: (seen.append(dict(m.data)), bus.emit(m.response({"url": "x"}))))
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False, hostnames=("house.local",))
    with TestClient(app, base_url="http://house.local:8500",
                    headers={"sec-fetch-site": "same-origin", "Authorization": "Bearer s3cret-token"}) as c:
        assert c.post("/api/cp/house/act", json={"ref": "b0.a0"}).status_code == 200
    assert seen == [{"host": "house.local"}], "the name without its port, and nothing else"


def test_host_is_true_or_false():
    page = json.loads(json.dumps(PAGE))
    page["blocks"][0]["action"]["host"] = "yes"
    with pytest.raises(described.DescribedError, match="host is true or false"):
        checked(page)
