"""The page registry: how pages from any package are found and checked."""
import types

import pytest

from ovos_webui import pages

OWN = types.SimpleNamespace(name=pages.OWN_DIST, version="1.0")
OTHER = types.SimpleNamespace(name="ovos-skill-guardian", version="0.3.0")


class _EP:
    """An entry point whose target is a page description in this module."""

    def __init__(self, name, desc, dist=OTHER):
        self.name = name
        self.dist = dist
        self.value = f"{__name__}:PAGE"
        self._desc = desc

    def load(self):
        if isinstance(self._desc, Exception):
            raise self._desc
        return self._desc


def _desc(**over):
    desc = {"api_version": 1, "id": "guardian", "path": "/emkay/guardian",
            "title": {"key": "guardian.title", "label": "Guardian"},
            "group": "device", "html": ("ovos_webui.pages.about", "page.html"),
            "icon": ("ovos_webui.pages.about", "icon.svg")}
    desc.update(over)
    return desc


def _own():
    """The panel's own pages, as installed entry points."""
    import importlib
    eps = []
    for name in pages.BUILTIN:
        desc = importlib.import_module(f"ovos_webui.pages.{name}").PAGE
        ep = _EP(desc["id"], desc, OWN)
        ep.value = f"ovos_webui.pages.{name}:PAGE"
        eps.append(ep)
    return eps


def test_a_page_from_another_package_joins_the_menu():
    reg = pages.load(_own() + [_EP("guardian", _desc())])
    page = reg.by_path()["/emkay/guardian"]
    assert page.package == "ovos-skill-guardian" and page.builtin is False
    assert any(p["id"] == "guardian" for p in reg.nav()["pages"])
    assert reg.problems == []


def test_without_its_own_entry_points_the_panel_reads_its_pages_directly():
    """A source tree that was never installed has no entry points."""
    reg = pages.load([_EP("guardian", _desc())])
    assert len(reg.pages) == len(pages.BUILTIN) + 1


@pytest.mark.parametrize("bad, why", [
    (_desc(api_version=2), "version"),
    (_desc(id="Not An Id"), "id"),
    (_desc(path="/api/guardian"), "belongs to the panel"),
    (_desc(path="/login"), "belongs to the panel"),
    (_desc(path="no-slash"), "path"),
    (_desc(path="/"), "already the dashboard"),
    (_desc(title={"key": "x"}), "label"),
    (_desc(html="missing.html"), "missing"),
    (_desc(html="../../etc/passwd"), "plain file name"),
    (_desc(needs="ovos-skill-guardian"), "list"),
    (_desc(group="nowhere"), "no group"),
    (_desc(routes="not a function"), "function"),
    (["not", "a", "dict"], "dict"),
    (ImportError("no module named guardian"), "no module"),
])
def test_a_broken_page_is_left_out_and_named(bad, why):
    reg = pages.load(_own() + [_EP("guardian", bad)])
    assert "/emkay/guardian" not in reg.by_path()
    assert len(reg.pages) == len(pages.BUILTIN), "the panel's own pages still load"
    assert len(reg.problems) == 1
    problem = reg.problems[0]
    assert problem["package"] in {"ovos-skill-guardian", OTHER.name}
    assert why in problem["error"]


def test_a_second_page_with_the_same_id_is_left_out():
    reg = pages.load(_own() + [_EP("a", _desc()), _EP("b", _desc(path="/emkay/other"))])
    assert "/emkay/other" not in reg.by_path()
    assert "already has the id" in reg.problems[0]["error"]


def test_a_page_can_bring_its_own_group():
    group = {"id": "emkay", "title": {"key": "emkay.group", "label": "Emkay"}, "order": 15}
    reg = pages.load(_own() + [_EP("guardian", _desc(group="emkay", groups=[group]))])
    ids = [g["id"] for g in reg.nav()["groups"]]
    assert ids.index("voice") < ids.index("emkay") < ids.index("understanding")
    assert reg.by_path()["/emkay/guardian"].group == "emkay"


def test_a_page_cannot_redefine_a_group_of_the_panel():
    group = {"id": "device", "title": {"label": "Hijacked"}, "order": -1}
    reg = pages.load(_own() + [_EP("guardian", _desc(groups=[group]))])
    device = [g for g in reg.groups if g["id"] == "device"][0]
    assert device["label"] == "Device"


def test_pages_are_ordered_by_group_then_order():
    reg = pages.load(_own() + [_EP("guardian", _desc(order=1))])
    device = [p.id for p in reg.pages if p.group == "device"]
    assert device[0] == "guardian"


def test_unknown_fields_are_ignored_not_fatal():
    reg = pages.load(_own() + [_EP("guardian", _desc(colour="teal"))])
    assert "/emkay/guardian" in reg.by_path()


def test_the_menu_data_cannot_close_its_script_element():
    reg = pages.load(_own() + [_EP("guardian", _desc(title={"label": "</script><b>x"}))])
    assert "</script>" not in reg.nav_json()
    html = pages.render(reg.by_path()["/"], reg.nav_json())
    assert html.count("</script>") == html.count("<script")


def test_render_puts_the_menu_in_the_head():
    reg = pages.load(_own())
    html = pages.render(reg.by_path()["/about"], reg.nav_json())
    assert html.index('id="ovos-nav"') < html.index("</head>")


def test_the_pages_route_lists_where_each_page_comes_from(client):
    body = client.get("/api/pages").json()
    assert body["problems"] == []
    about = [p for p in body["pages"] if p["id"] == "about"][0]
    assert about["package"] == pages.OWN_DIST and about["builtin"] is True
