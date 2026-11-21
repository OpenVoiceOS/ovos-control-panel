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


# ── what a page brings: its body, strings, files and routes ─────────────────
@pytest.fixture
def guardian_pkg(tmp_path, monkeypatch):
    """A package outside the panel with a page: body, strings, assets, routes."""
    # A name of its own per test: the import system keeps a module it has seen.
    name = f"guardian_page_{tmp_path.name.replace('-', '_')}"
    pkg = tmp_path / name
    (pkg / "i18n").mkdir(parents=True)
    (pkg / "static").mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "page.html").write_text(
        '<section class="card"><h2 data-i18n="guardian.mode">Mode</h2>'
        '<p>{{heading}} stays text</p></section>\n'
        '<script src="/pages/guardian/guardian.js"></script>')
    (pkg / "icon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (pkg / "i18n" / "en.json").write_text('{"guardian.mode": "Mode", "nav.dashboard": "Hijacked"}')
    (pkg / "i18n" / "da.json").write_text('{"guardian.mode": "Tilstand"}')
    (pkg / "static" / "guardian.js").write_text("console.log('guardian');")
    (pkg / "static" / ".secret").write_text("no")
    monkeypatch.syspath_prepend(str(tmp_path))
    return name


def _guardian(module, **over):
    def routes(r):
        @r.api.get("/guardian/state")
        def state():
            return {"mode": "day"}

    desc = {"api_version": 1, "id": "guardian", "path": "/emkay/guardian",
            "title": {"key": "guardian.title", "label": "Guardian"}, "group": "device",
            "html": (module, "page.html"), "icon": (module, "icon.svg"),
            "i18n": "i18n", "assets": "static", "routes": routes}
    desc.update(over)
    ep = _EP("guardian", desc)
    ep.value = f"{module}:PAGE"
    return ep


@pytest.fixture
def guardian_app(guardian_pkg, monkeypatch, bus):
    from fastapi.testclient import TestClient

    from ovos_webui.service import create_app
    eps = _own() + [_guardian(guardian_pkg)]
    monkeypatch.setattr(pages, "_entry_points", lambda: eps)
    app = create_app(bus=bus, host="127.0.0.1", token=None, connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500") as c:
        yield c


def test_a_page_body_is_wrapped_in_the_shell(guardian_app):
    body = guardian_app.get("/emkay/guardian").text
    assert body.startswith("<!doctype html>")
    assert "<title>Guardian — OpenVoiceOS</title>" in body
    assert '<h1 data-i18n="guardian.title">Guardian</h1>' in body
    assert 'id="ovos-nav"' in body and 'class="skip"' in body
    assert 'data-page="guardian"' in body
    assert "{{heading}} stays text" in body, "text in the body is not a slot"


def test_a_page_gets_its_own_routes_with_the_panels_checks(guardian_app):
    assert guardian_app.get("/api/guardian/state").json() == {"mode": "day"}


def test_a_page_serves_its_own_files_and_nothing_else(guardian_app):
    r = guardian_app.get("/pages/guardian/guardian.js")
    assert r.status_code == 200 and "guardian" in r.text
    assert r.headers["x-content-type-options"] == "nosniff"
    for bad in ("/pages/guardian/.secret", "/pages/guardian/missing.js",
                "/pages/guardian/..%2F__init__.py", "/pages/nobody/guardian.js"):
        assert guardian_app.get(bad).status_code == 404, bad


def test_a_pages_strings_join_the_panels_but_cannot_change_them(guardian_app):
    da = guardian_app.get("/static/i18n/da.json").json()
    assert da["guardian.mode"] == "Tilstand"
    en = guardian_app.get("/static/i18n/en.json").json()
    assert en["nav.dashboard"] == "Dashboard"


def test_a_page_whose_routes_clash_is_left_out(guardian_pkg):
    def routes(r):
        @r.api.get("/health")
        def mine():
            return {}

    reg = pages.load(_own() + [_guardian(guardian_pkg, routes=routes)])
    taken = {("GET", "/api/health")}
    included = []
    pages.mount_routes(reg, lambda page: pages.Routes(
        api=__import__("fastapi").APIRouter(prefix="/api"),
        privileged=__import__("fastapi").APIRouter(prefix="/api"),
        need_bus=lambda: None, config=None), taken, included.append)
    assert "/emkay/guardian" not in reg.by_path()
    assert "GET /api/health" in reg.problems[-1]["error"]
    assert len(included) == len([p for p in reg.pages if p.routes]), "the other pages with routes are still mounted"


def test_a_page_whose_routes_fail_is_left_out(guardian_pkg):
    def routes(r):
        raise RuntimeError("no database")

    reg = pages.load(_own() + [_guardian(guardian_pkg, routes=routes)])
    pages.mount_routes(reg, lambda page: pages.Routes(
        api=__import__("fastapi").APIRouter(prefix="/api"),
        privileged=__import__("fastapi").APIRouter(prefix="/api"),
        need_bus=lambda: None, config=None), set(), lambda r: None)
    assert "/emkay/guardian" not in reg.by_path()
    assert "no database" in reg.problems[-1]["error"]


def test_a_broken_language_file_leaves_the_page_out(guardian_pkg, tmp_path):
    (tmp_path / guardian_pkg / "i18n" / "de.json").write_text('["not", "a", "map"]')
    reg = pages.load(_own() + [_guardian(guardian_pkg)])
    assert "/emkay/guardian" not in reg.by_path()
    assert "de.json" in reg.problems[-1]["error"]


def test_the_panels_own_page_strings_cover_every_language():
    """The panel's own pages must ship every language the panel does."""
    from pathlib import Path
    shipped = {p.stem for p in (Path(pages.__file__).parent.parent / "static" / "i18n").glob("*.json")}
    for page in pages.load().pages:
        if page.strings:
            assert set(page.strings) == shipped, page.id
            keys = set(page.strings["en"])
            for lang, table in page.strings.items():
                assert set(table) == keys, (page.id, lang)


def test_a_page_cannot_take_a_shell_address_through_a_parameter(guardian_pkg):
    """Pages' routes are matched first, so /api/{anything} would swallow the
    shell's own routes."""
    from fastapi import APIRouter

    def routes(r):
        @r.api.get("/{anything}")
        def swallow(anything: str):
            return {}

    reg = pages.load(_own() + [_guardian(guardian_pkg, routes=routes)])
    pages.mount_routes(reg, lambda page: pages.Routes(
        api=APIRouter(prefix="/api"), privileged=APIRouter(prefix="/api"),
        need_bus=lambda: None, config=None), {("GET", "/api/health")}, lambda r: None)
    assert "/emkay/guardian" not in reg.by_path()
    assert "GET /api/{anything}" in reg.problems[-1]["error"]


def test_a_page_route_wins_over_a_shell_route_with_a_parameter(client, bus):
    """POST /api/system/ssh belongs to the System page, although the shell has
    POST /api/system/{action}; without a device both answer, the page's own."""
    r = client.post("/api/system/ssh", json={"enabled": True})
    assert r.status_code != 404
