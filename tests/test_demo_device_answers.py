"""The stand-in device must answer in the shapes the panel reads.

`scripts/demo_device.py` exists so the documentation screenshots show a device
rather than a page reporting that nothing answered. That only helps if what it
says matches what the panel understands: an answer in the wrong shape produces
a picture of a device in a state no device is ever in, and the picture is
committed and shipped. One payload missing `enabled` put an "off" pill on every
intent in the documentation.

The shapes here are read from ovos-core's own manifest, not from this file.
"""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "demo_device.py"
SHOOT = SCRIPT.parent / "screenshots.py"


def _device_language() -> str:
    """The language the shoot configures its stand-in device with."""
    import ast

    tree = ast.parse(SHOOT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "DEMO_CONFIG" for t in node.targets)):
            config = ast.literal_eval(node.value)
            return config["lang"]
    raise AssertionError("the shoot no longer declares DEMO_CONFIG")


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("demo_device", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_intent_list_carries_every_field_core_sends(demo):
    """A missing `enabled` reads as an intent that is switched off.

    The set is core's, not the page's: `_on_list` copies exactly these six
    keys out of the manifest, and answering with fewer describes a reply no
    intent service sends. The page itself reads five of them -- `session_id`
    is on the wire and rendered nowhere.
    """
    _, payload = demo.ANSWERS["ovos.intent.list"]
    intents = payload["intents"]
    assert intents, "answered with no intents at all"
    for intent in intents:
        missing = {"skill_id", "intent_name", "lang", "method", "enabled",
                   "session_id"} - set(intent)
        assert not missing, f"{intent['intent_name']} is missing {sorted(missing)}"
        assert intent["enabled"] is True, (
            f"{intent['intent_name']} would be drawn with an 'off' pill"
        )
        assert intent["method"], "the match method prints blank"


def test_each_intent_is_one_the_named_skill_really_registers(demo):
    """Field names from the manifest are not enough: the values have to be
    real too.

    A payload can carry every key the page reads and still describe a device
    that cannot exist -- an intent under its Python handler's name, which
    never travels on the wire, or matched by keyword when the skill declares
    it in a `.intent` file. The picture then shows a device in a state no
    device is ever in, which is the whole failure this stand-in exists to
    avoid.
    """
    import importlib
    import inspect
    import re

    _, payload = demo.ANSWERS["ovos.intent.list"]
    modules = {"ovos-skill-date-time.openvoiceos": "ovos_skill_date_time",
               "ovos-skill-hello-world.openvoiceos": "ovos_skill_hello_world"}

    for intent in payload["intents"]:
        module = importlib.import_module(modules[intent["skill_id"]])
        source = inspect.getsource(module)

        # ovos-core standardizes the tag when the intent is registered, so a
        # lowercased region never travels: `_on_list` replies with the stored
        # entry verbatim. The skill also has to actually speak the language.
        from ovos_spec_tools import standardize_lang

        lang = intent["lang"]
        assert standardize_lang(lang) == lang, (
            f"{lang} is not the form core stores; it would reach the page as "
            f"{standardize_lang(lang)}"
        )
        locales = Path(module.__file__).parent / "locale" / lang
        assert locales.is_dir(), (
            f"{intent['skill_id']} has no {lang} locale, so it registers no "
            "intent in that language"
        )
        # And it has to be the language the device in the pictures is set to:
        # a skill with a German locale really would register German intents,
        # but not on a device configured for English.
        assert lang == standardize_lang(_device_language()), (
            f"the device in the screenshots speaks {_device_language()}, so "
            f"it would not register a {lang} intent"
        )
        name = intent["intent_name"]
        if intent["method"] == "template":
            # A `.intent` file, named without the skill prefix or the suffix.
            assert f'"{name}.intent"' in source, (
                f"{name} is not a template intent of {intent['skill_id']}"
            )
        else:
            assert re.search(rf'IntentBuilder\(\s*"{re.escape(name)}"', source), (
                f"{name} is not a keyword intent of {intent['skill_id']}"
            )


def test_active_skills_are_plain_ids(demo):
    """`get_active_skills` returns skill ids; the panel drops anything else."""
    from ovos_webui import intents as reader

    _, payload = demo.ANSWERS["intent.service.active_skills.get"]
    assert payload["skills"], "answered with no active skills"
    assert all(isinstance(s, str) for s in payload["skills"]), (
        f"the panel silently drops these: {payload['skills']}"
    )
    assert "isinstance(s, str)" in Path(reader.__file__).read_text(), (
        "the panel no longer filters active skills by type; re-check this"
    )


def test_every_answer_names_a_topic_the_panel_asks_about(demo):
    """An answer to a topic nothing sends is dead weight in the picture."""
    root = Path(demo.__file__).resolve().parent.parent / "ovos_webui"
    source = "\n".join(p.read_text(encoding="utf-8")
                       for p in root.glob("*.py"))
    unused = [topic for topic in demo.ANSWERS if topic not in source]
    assert unused == [], f"nothing in the panel sends {unused}"
