"""The navigation list says where every page belongs.

`NAV` in app.js is the one place the menu is defined. Each page carries its
group, its level and what it needs, so the menu can be grouped, folded and
trimmed to what the device can use without a second list to keep in step.
"""
import json
import re
from pathlib import Path

from ovos_webui.service import PAGES, STATIC_DIR

GROUPS = {"everyday", "voice", "understanding", "device", "screen", "maintenance"}
LEVELS = {"everyday", "advanced"}
#: What a page may say it needs. A new need is added here and taught to the
#: code that decides whether it is met.
NEEDS = {None, "system", "sensors", "media", "app-launcher", "wallpaper", "mark1"}


def _nav():
    js = (Path(STATIC_DIR) / "app.js").read_text(encoding="utf-8")
    found = re.search(r"var NAV = (\[.*?\n  \]);", js, re.DOTALL)
    assert found, "NAV is no longer declared as a JSON-shaped array in app.js"
    return json.loads(found.group(1))


def _en():
    return json.loads((Path(STATIC_DIR) / "i18n" / "en.json").read_text(encoding="utf-8"))


def test_every_entry_has_the_same_fields():
    for item in _nav():
        assert set(item) == {"path", "key", "label", "group", "level", "needs"}, item


def test_groups_levels_and_needs_are_known():
    for item in _nav():
        assert item["group"] in GROUPS, item
        assert item["level"] in LEVELS, item
        assert item["needs"] in NEEDS, item


def test_the_everyday_group_and_the_everyday_level_agree():
    for item in _nav():
        assert (item["group"] == "everyday") == (item["level"] == "everyday"), item


def test_each_page_is_listed_once_and_is_served():
    paths = [item["path"] for item in _nav()]
    assert len(paths) == len(set(paths)), "a page is in NAV twice"
    served = {p[0] if isinstance(p, (list, tuple)) else p for p in PAGES}
    assert set(paths) <= served, sorted(set(paths) - served)


def test_labels_match_the_english_locale():
    en = _en()
    for item in _nav():
        assert en.get(item["key"]) == item["label"], item


def test_the_pages_a_bug_report_needs_are_everyday():
    everyday = {item["path"] for item in _nav() if item["level"] == "everyday"}
    # About is where the versions are, and Setup is where a new device starts.
    assert {"/", "/setup", "/about", "/skills", "/backup"} <= everyday
