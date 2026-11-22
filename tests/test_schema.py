"""docs/controlpanel.schema.json says what the checker says: every page the
panel brings passes it, and so do the test pages, and a typo does not."""
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from ovos_webui import described  # noqa: E402

from tests import test_described as pages_under_test  # noqa: E402

SCHEMA = json.loads((Path(__file__).parent.parent / "docs" / "controlpanel.schema.json")
                    .read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def errors(page):
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in VALIDATOR.iter_errors(page)]


def test_the_schema_is_a_schema():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("folder", sorted(p.name for p in described.BUNDLED.iterdir()
                                          if (p / described.FILE).is_file()))
def test_every_page_the_panel_brings_passes(folder):
    page = json.loads((described.BUNDLED / folder / described.FILE).read_text(encoding="utf-8"))
    assert errors(page) == []


@pytest.mark.parametrize("name", ["PAGE", "STORY", "SHELF", "LAUNCHER", "VOICE"])
def test_the_test_pages_pass(name):
    assert errors(getattr(pages_under_test, name)) == []


def test_a_block_from_a_newer_version_passes():
    page = {"controlpanel": 1, "id": "x", "title": "x.title", "bus": "ovos.x.",
            "blocks": [{"type": "sparkles", "what": "a block from the future"}]}
    assert errors(page) == []


@pytest.mark.parametrize("change, where", [
    (lambda p: p["blocks"][0].update(titel="{name}"), "blocks/0"),          # a typo
    (lambda p: p["blocks"][0].pop("query"), "blocks/0"),                    # neither query nor listen
    (lambda p: p.update(controlpanel=2), "controlpanel"),
    (lambda p: p["blocks"][0]["actions"][0].pop("send"), "blocks/0"),       # an action that sends nothing
    (lambda p: p.pop("bus"), ""),
])
def test_a_mistake_is_caught(change, where):
    page = {"controlpanel": 1, "id": "x", "title": "x.title", "bus": "ovos.x.",
            "blocks": [{"type": "list", "query": "ovos.x.list", "title": "{name}",
                        "actions": [{"label": "common.play", "send": "ovos.x.play"}]}]}
    change(page)
    found = errors(page)
    assert found and any(e.startswith(where) for e in found), found


def test_the_checker_takes_a_schema_line():
    page = dict(pages_under_test.LAUNCHER, **{"$schema": SCHEMA["$id"]})
    described.check(json.loads(json.dumps(page)), "ovos-phal-plugin-app-launcher", by_panel=True)


def test_a_group_title_is_a_key_or_a_key_with_its_english():
    page = {"controlpanel": 1, "id": "x", "title": "x.title", "bus": "ovos.x.", "group": "music",
            "groups": [{"id": "music", "title": {"key": "nav.group.music", "label": "Music"}}],
            "blocks": [{"type": "text", "text": "x.intro"}]}
    assert errors(page) == []
    page["groups"][0]["title"] = "nav.group.music"
    assert errors(page) == []


def test_the_page_the_panel_makes_for_a_plugin_passes(monkeypatch):
    monkeypatch.setattr(described, "plugin_modules", lambda package: {"tts": [package]})
    assert errors(described.plugin_page("ovos-tts-plugin-x", "1.0", []).data) == []
