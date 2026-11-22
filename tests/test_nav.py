"""The panel's own pages say where they belong in the menu.

Every page comes from the page registry. Each says its group and what it
needs, so the menu can be grouped, folded and trimmed to what the device can
use without a second list to keep in step.
"""
import json
from pathlib import Path

from ovos_webui import pages
from ovos_webui.service import STATIC_DIR

REG = pages.load()


def _en():
    """The panel's English strings with every page's own, as served."""
    return REG.strings(
        "en", json.loads((Path(STATIC_DIR) / "i18n" / "en.json").read_text(encoding="utf-8")))


def test_the_panels_own_pages_all_load():
    assert REG.problems == []
    assert len(REG.pages) == len(pages.BUILTIN)
    assert all(p.builtin and p.package == pages.OWN_DIST for p in REG.pages)


def test_every_page_is_in_a_known_group():
    known = {g["id"] for g in pages.GROUPS}
    for page in REG.pages:
        assert page.group in known, page.id


def test_each_page_is_listed_once():
    paths = [p.path for p in REG.pages]
    assert len(paths) == len(set(paths))


def test_titles_and_group_names_match_the_english_locale():
    en = _en()
    for page in REG.pages:
        assert en.get(page.key) == page.label, page.id
    for group in pages.GROUPS:
        if group["level"] == "advanced":
            assert en.get(group["key"]) == group["label"], group["id"]


def test_every_page_has_its_own_icon():
    icons = [p.icon for p in REG.pages]
    assert all(icons), [p.id for p in REG.pages if not p.icon]
    assert len(set(icons)) == len(icons), "two pages share an icon"


def test_the_pages_a_bug_report_needs_are_everyday():
    everyday = {p.path for p in REG.pages if p.group == "everyday"}
    # About is where the versions are, and Setup is where a new device starts.
    assert {"/", "/setup", "/about", "/skills", "/backup"} <= everyday


def test_the_core_pages_are_the_panels_own():
    assert pages.CORE <= {p.id for p in REG.pages}


def test_every_page_folder_is_one_of_the_panels_own():
    """The panel reads its own pages from BUILTIN, so a page folder left out
    of it would never show."""
    root = Path(pages.__file__).parent
    folders = {p.name for p in root.iterdir() if (p / "__init__.py").is_file()}
    assert folders == set(pages.BUILTIN)


def test_what_it_plays_for_you_is_in_the_library():
    groups = {g["id"]: g for g in pages.GROUPS}
    assert groups["library"]["level"] == groups["music"]["level"] == "everyday"
    assert groups["everyday"]["order"] < groups["library"]["order"] < groups["music"]["order"]
    assert REG.by_id()["media"].group == "library"


def test_every_group_but_the_everyday_pages_folds():
    js = (Path(STATIC_DIR) / "app.js").read_text(encoding="utf-8")
    assert 'groupRow(g, "nav-everyday")' in js, "the Library and Music fold like any group"
    assert 'foldRow(ADVANCED, "nav.advanced"' in js, "Advanced folds all its groups at once"
