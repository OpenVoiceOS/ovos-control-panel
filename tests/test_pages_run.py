"""Every page must run its own JavaScript without throwing.

The rest of the suite tests the Python side and reads the HTML as text, so a
page whose script dies on load still passes everything: the markup is there,
the strings are there, the routes answer. A real browser is the only thing
that notices.

This caught a `var canvas` declared below the geometry that used it -- `var`
hoists the declaration but not the assignment, so the whole script died on
load and the faceplate drew nothing at all, with 961 other tests green.

Skipped when Playwright's browser is not present, so anyone can run the suite
without the ~115MB browser download. CI installs the browser
(`pre_test_command` in build-tests.yml) and sets OVOS_WEBUI_REQUIRE_BROWSER=1,
which turns that skip into a failure: in CI a missing browser means the gate
did not run, and that must not read as a pass.

That matters more here than the count suggests. Nearly everything the Mark-1
page does -- the canvas geometry, the eye diff, the poll chain, the animation
editor and its exports -- is asserted only in this file. The rest of the suite
proves the routes answer and the strings are there; it proves nothing about
whether the face draws.
"""
import json
import os
import re
import time
import warnings
from pathlib import Path

import pytest


def _browser_required() -> bool:
    return os.environ.get("OVOS_WEBUI_REQUIRE_BROWSER", "") not in ("", "0")


def _not_running(message: str):
    """Skip locally, fail where the gate is required to run."""
    if _browser_required():
        pytest.fail(message, pytrace=False)
    pytest.skip(message)


try:
    import playwright.sync_api  # noqa: F401
except ImportError:  # pragma: no cover - depends on the environment
    if _browser_required():
        raise
    pytest.skip("playwright is not installed", allow_module_level=True)


def _pages():
    from ovos_webui import pages

    return sorted(p.path for p in pages.load().pages)


# The four reads the /plugins page starts on load that leave this machine or
# shell out: `/api/plugins/search` fetches the PyPI index, `/api/updates`
# asks PyPI for the latest of every installed OVOS package, `/api/updates/
# conflicts` runs `pip check`, and `/api/plugins/recommended` reads the
# installed set. On a cold cache they take 21 to 31 seconds together, against
# the 30 second limit `wait_for_load_state("networkidle")` applies, so the
# /plugins case of `test_the_page_script_runs` passed or failed on how busy
# pypi.org was that minute (T-6597).
#
# Each is answered from here with the shape the real handler returns, measured
# against a live panel rather than read off the source:
#
#   /api/plugins/search      keys=['cache_age','error','kinds','offline',
#                                  'results','stale','total']
#   /api/updates             keys=['channel','checked','offline','outdated',
#                                  'packages']
#   /api/updates/conflicts   keys=['conflicts','error','ok']
#   /api/plugins/recommended keys=['lang','plugins','profiles']
#
# What this hides, said plainly: a handler that DROPS a key keeps this test
# green while the real page breaks, because the browser never sees the real
# reply. A handler that adds a key the page needs still reds here, which is
# the direction that matters for a script-runs test. The real replies are
# covered by the python route tests (tests/test_pypi_index.py,
# tests/test_recommends.py), which call the handlers themselves.
_STUBS = {
    "**/api/plugins/search*": {"results": [], "total": 0, "kinds": ["stt", "tts"],
                               "cache_age": 0, "stale": False, "offline": False,
                               "error": None},
    "**/api/updates": {"channel": "stable", "offline": False, "packages": [],
                       "checked": 0, "outdated": 0},
    "**/api/updates/conflicts": {"ok": True, "conflicts": [], "error": None},
    "**/api/plugins/recommended*": {"lang": "en-us", "profiles": {}, "plugins": []},
}


def _answer(payload):
    # A one-argument handler, not two: Playwright inspects the handler's own
    # signature to decide whether to call it with just the route or with
    # (route, request), and a second parameter -- even a defaulted one meant
    # to close over ``payload`` -- is counted, so the request object silently
    # overwrites ``payload`` instead of falling through to its default.
    def handler(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))
    return handler


def _stub_the_slow_reads(context):
    """Answer the PyPI-backed reads in the browser, so no test waits on PyPI."""
    for pattern, payload in _STUBS.items():
        context.route(pattern, _answer(payload))


@pytest.fixture(scope="module")
def signed_in_page(live_panel):
    import os
    import pathlib

    from playwright.sync_api import sync_playwright

    # The suite isolates XDG_CACHE_HOME, which is where Playwright keeps its
    # browsers -- so without this it looks for chromium inside an empty
    # per-run directory and skips every test as "not installed".
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        default = pathlib.Path.home() / ".cache" / "ms-playwright"
        if default.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(default)

    url, token = live_panel
    with sync_playwright() as play:
        try:
            browser = play.chromium.launch()
        except Exception as err:  # noqa: BLE001 - browser not downloaded
            # Loud, because this skips for two different reasons and one of
            # them looks like the other: no browser at all, or a shared cache
            # holding a build from before a playwright bump. Either way the
            # gate is not running, and a silent skip reads as a pass.
            message = (
                f"the browser gate did NOT run: {err}\n"
                "Run `python -m playwright install chromium` (after a "
                "playwright upgrade too -- each version wants its own build)."
            )
            warnings.warn(message, stacklevel=1)
            _not_running(message)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        _stub_the_slow_reads(context)
        page = context.new_page()
        page.goto(f"{url}/login")
        page.fill("input[type=password]", token)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        yield page, url
        browser.close()


@pytest.mark.parametrize("route", _pages())
def test_the_page_script_runs(signed_in_page, route):
    page, url = signed_in_page
    thrown = []
    page.on("pageerror", lambda err: thrown.append(str(err)))
    page.goto(f"{url}{route}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)
    assert not thrown, f"{route} threw on load: {thrown}"


def test_every_page_in_the_nav_has_its_own_icon(signed_in_page):
    """A page added without an icon rule is a solid block in the rail.

    The icons are CSS masks over a box filled with the text colour, so an
    unmasked box is not "no icon" -- it is a filled square where the icon
    should be, on every page of the panel. The nav carries no id, and an
    empty selector passes any per-element check, so the count is asserted
    first.
    """
    PAGES = _pages()

    page, url = signed_in_page
    page.goto(f"{url}/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    found = page.evaluate("""() => {
      const out = [];
      for (const a of document.querySelectorAll("nav a[href]")) {
        const cs = getComputedStyle(a, "::before");
        const mask = cs.maskImage || cs.webkitMaskImage || "none";
        // The blank fallback is the only 1x1 viewBox; matching the bare
        // digits would also hit arc flags in ordinary path data.
        const blank = mask.includes("viewBox='0 0 1 1'")
          || mask.includes("viewBox=%270 0 1 1%27");
        out.push([a.getAttribute("href"), mask === "none" || blank, mask]);
      }
      return out;
    }""")

    assert len(found) == len(PAGES), (
        f"read {len(found)} nav entries, expected {len(PAGES)}"
    )
    bare = [href for href, missing, _ in found if missing]
    assert bare == [], f"nav entries with no icon of their own: {bare}"

    # "Its own" is the point: two entries wearing the same icon is a worse
    # rail than none, because the reader trusts it to tell them apart.
    seen: dict[str, str] = {}
    shared = []
    for href, _, mask in found:
        if mask in seen:
            shared.append((seen[mask], href))
        seen[mask] = href
    assert shared == [], f"nav entries sharing one icon: {shared}"


def test_one_service_down_is_not_reported_as_one_services(signed_in_page):
    """"1 service(s)" is the shape of a string nobody read back.

    The panel writes for a person reading it, and a count of one is the case
    that shows whether anyone did.
    """
    page, url = signed_in_page
    page.route("**/api/health", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({
            "bus": {"reachable": True},
            "healthy": False,
            "services": [
                {"name": "skills", "label": "Skills", "hint": "",
                 "alive": None, "ready": None, "state": "no answer"},
                {"name": "audio", "label": "Audio", "hint": "",
                 "alive": True, "ready": True, "state": "ready"},
            ]})))
    page.goto(f"{url}/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)

    said = page.locator(".summary").inner_text()
    assert "(s)" not in said, f"left the plural for the reader to sort out: {said!r}"
    assert "One service" in said or "1 service " in said, said


def test_the_setup_page_counts_its_own_steps(signed_in_page):
    """"Five short steps" above six of them is the panel miscounting itself.

    The steps are numbered in their own headings, so the intro and the page
    can drift apart silently as steps are added.
    """
    page, url = signed_in_page
    page.goto(f"{url}/setup")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)

    numbered = page.evaluate("""() => [...document.querySelectorAll("h2")]
        .map(h => h.textContent.trim())
        .filter(t => /^\\d+\\./.test(t)).length""")
    intro = page.locator("[data-i18n='setup.intro']").inner_text()
    words = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5, "Six": 6,
             "Seven": 7, "Eight": 8}
    said = next((n for word, n in words.items() if intro.startswith(word)), None)

    assert numbered, "no numbered steps on the setup page"
    assert said == numbered, (
        f"the intro says {said} steps and the page has {numbered}: {intro!r}"
    )
def test_hidden_means_hidden_whatever_the_element_is(signed_in_page):
    """`hidden` is an attribute, not a class, and any rule that sets
    `display` outranks the browser's default for it.

    Two rows in this panel are flex containers marked hidden, and both were
    on screen: the Mark-1 live row on a device with no Mark-1, and the media
    scrub bar for a track with no length. A page that shows a control it
    means to be offering later is a page lying about what it can do.
    """
    page, url = signed_in_page
    page.goto(f"{url}/voice")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)

    showing = page.evaluate("""() => [...document.querySelectorAll("[hidden]")]
        .filter(el => getComputedStyle(el).display !== "none")
        .map(el => el.id || el.className)""")
    assert showing == [], f"marked hidden and still on screen: {showing}"


def test_looking_up_a_setting_names_the_file_it_comes_from(signed_in_page):
    """The answer to "I changed it and nothing happened" is a filename."""
    page, url = signed_in_page
    page.goto(f"{url}/config")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    page.fill("#where-key", "lang")
    page.click("#where-look")
    page.wait_for_timeout(600)

    assert not page.locator("#where-answer").is_hidden()
    said = page.locator("#where-from").inner_text()
    assert said, "did not say where the value came from"
    assert "mycroft.conf" in said or "default" in said.lower(), said


def test_a_setting_nobody_has_touched_says_so(signed_in_page):
    page, url = signed_in_page
    page.goto(f"{url}/config")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    page.fill("#where-key", "nothing.sets.this")
    page.click("#where-look")
    page.wait_for_timeout(600)

    assert "Nothing sets this" in page.locator("#where-value").inner_text()


def test_the_file_list_shows_the_merge_order(signed_in_page):
    """Order is the whole point: later files win."""
    page, url = signed_in_page
    page.goto(f"{url}/config")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)

    # The list sits behind a disclosure, so open it the way a reader would.
    page.click("#where-stack summary")
    page.wait_for_timeout(200)
    items = page.locator("#where-layers li").all_inner_texts()
    assert items, "listed no configuration files"
    assert "packaged defaults" in items[0], items[0]
    assert "runtime change" in items[-1], items[-1]


def _visible_nav(page):
    return page.evaluate("""() => [...document.querySelectorAll("nav a[href]")]
      .filter(a => a.offsetParent !== null).map(a => a.getAttribute("href"))""")


def _fold(page, group):
    return page.locator(f'nav .nav-group[data-group="{group}"] > button.nav-fold')


def test_the_menu_groups_start_folded_and_open_one_at_a_time(signed_in_page):
    """Everyday pages always show; under the "Advanced" divider each group is
    a row that folds its own pages, and which rows are open is remembered."""
    page, url = signed_in_page
    page.goto(f"{url}/")
    page.evaluate("() => { localStorage.removeItem('ovos-nav-open'); "
                  "localStorage.removeItem('ovos-simple'); }")
    page.reload()
    page.wait_for_load_state("networkidle")

    assert page.locator("#simple-toggle").count() == 0, "the header switch is gone"
    advanced = _fold(page, "advanced")
    assert advanced.is_visible() and advanced.get_attribute("aria-expanded") == "false"
    # voice, understanding, maintenance: the device and screen groups' pages
    # come with their plugins, and the test device has none
    assert page.locator("nav .nav-advanced .nav-sub button.nav-fold").count() == 3
    assert not _fold(page, "understanding").is_visible(), "Advanced folds its groups away"
    folded = _visible_nav(page)
    assert "/about" in folded and "/skills" in folded
    assert "/intents" not in folded and "/plugins" not in folded
    # the Library's pages come with their skills, and the test device has none
    assert not _fold(page, "library").is_visible()

    advanced.click()
    understanding = _fold(page, "understanding")
    assert understanding.is_visible()
    assert understanding.get_attribute("aria-expanded") == "false"
    understanding.click()
    assert understanding.get_attribute("aria-expanded") == "true"
    shown = _visible_nav(page)
    assert {"/intents", "/transformers", "/personas"} <= set(shown)
    assert "/plugins" not in shown, "only the opened group unfolds"

    page.reload()
    page.wait_for_load_state("networkidle")
    assert _fold(page, "advanced").get_attribute("aria-expanded") == "true"
    assert _fold(page, "understanding").get_attribute("aria-expanded") == "true"
    assert _fold(page, "maintenance").get_attribute("aria-expanded") == "false"
    _fold(page, "advanced").click()
    assert "/intents" not in _visible_nav(page), "folding Advanced hides its open groups too"
    page.evaluate("() => localStorage.removeItem('ovos-nav-open')")


def test_the_group_of_the_page_you_are_on_opens(signed_in_page):
    page, url = signed_in_page
    page.goto(f"{url}/")
    page.evaluate("() => localStorage.removeItem('ovos-nav-open')")
    page.goto(f"{url}/intents")
    page.wait_for_load_state("networkidle")
    shown = _visible_nav(page)
    assert {"/intents", "/transformers", "/personas"} <= set(shown)
    assert "/plugins" not in shown
    assert _fold(page, "understanding").get_attribute("aria-expanded") == "true"
    assert _fold(page, "advanced").get_attribute("aria-expanded") == "true"
    assert page.locator('nav a[aria-current="page"]').get_attribute("href") == "/intents"


def test_someone_who_had_every_page_on_keeps_them(signed_in_page):
    """The old header switch stored ovos-simple=0 for "show all pages"."""
    page, url = signed_in_page
    page.goto(f"{url}/")
    page.evaluate("() => { localStorage.removeItem('ovos-nav-open'); "
                  "localStorage.setItem('ovos-simple', '0'); }")
    page.reload()
    page.wait_for_load_state("networkidle")
    assert "/plugins" in _visible_nav(page) and "/intents" in _visible_nav(page)
    page.evaluate("() => localStorage.removeItem('ovos-simple')")


def test_pages_the_device_cannot_use_leave_the_menu(signed_in_page):
    """A need that is not met takes its page out of the menu (and an emptied
    group with it); reaching the page anyway says what it needs."""
    page, url = signed_in_page
    needs = {"colocated": True, "needs": {
        k: {"met": False, "suggest": "pkg-" + k}
        for k in ("translate",)}}

    def answer(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(needs))

    page.route("**/api/nav/needs", answer)
    try:
        page.goto(f"{url}/")
        page.evaluate("() => { sessionStorage.removeItem('ovos-nav-needs.v2'); "
                      "localStorage.setItem('ovos-nav-open', JSON.stringify(['advanced', 'library', 'voice', 'understanding', 'device', 'screen', 'maintenance'])); }")
        page.reload()
        page.wait_for_function("() => document.querySelector('nav a[href=\"/translate\"]').hidden")
        shown = _visible_nav(page)
        assert "/translate" not in shown and "/voice" in shown
        assert not page.locator('nav .nav-group[data-group="screen"]').is_visible()

        page.goto(f"{url}/translate")
        note = page.locator("#needs-note")
        note.wait_for()
        assert "pkg-translate" in note.inner_text()
        assert note.locator('a[href="/plugins"]').count() == 1
        assert "/translate" in _visible_nav(page), "the page you are on stays in the menu"
    finally:
        page.unroute("**/api/nav/needs")
        page.evaluate("() => { sessionStorage.removeItem('ovos-nav-needs.v2'); "
                      "localStorage.removeItem('ovos-nav-open'); }")


def test_a_panel_apart_from_the_device_hides_no_page(signed_in_page):
    page, url = signed_in_page
    needs = {"colocated": False, "needs": {"translate": {"met": False, "suggest": "x"}}}
    page.route("**/api/nav/needs", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(needs)))
    try:
        page.goto(f"{url}/")
        page.evaluate("() => { sessionStorage.removeItem('ovos-nav-needs.v2'); "
                      "localStorage.setItem('ovos-nav-open', JSON.stringify(['advanced', 'library', 'voice', 'understanding', 'device', 'screen', 'maintenance'])); }")
        page.reload()
        page.wait_for_load_state("networkidle")
        assert "/translate" in _visible_nav(page)
    finally:
        page.unroute("**/api/nav/needs")
        page.evaluate("() => { sessionStorage.removeItem('ovos-nav-needs.v2'); "
                      "localStorage.removeItem('ovos-nav-open'); }")


def _json_route(page, pattern, body):
    page.route(pattern, lambda r: r.fulfill(status=200, content_type="application/json",
                                            body=json.dumps(body)))


def test_the_plugins_page_puts_the_installer_on_the_channel(signed_in_page):
    """When the device's installer does not follow the chosen channel the page
    says so; the fix sets it, and a restart is offered because the services
    read that setting when they start."""
    page, url = signed_in_page
    posted = []

    def channel(route):
        if route.request.method == "POST":
            posted.append(json.loads(route.request.post_data))
            route.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"ok": True, "channel": "alpha", "restart": True,
                 "installer": {"follows": True, "custom": None}}))
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"channel": "alpha", "channels": ["stable", "alpha"],
                 "installer": {"follows": False, "custom": None}}))

    page.route("**/api/updates/channel", channel)
    try:
        page.goto(f"{url}/plugins")
        page.locator("#installer-off").wait_for()
        assert page.locator("#restart-row").is_hidden()
        page.click("#installer-fix")
        page.locator("#restart-row").wait_for()
        assert posted == [{"channel": "alpha"}]
        assert page.locator("#installer-off").is_hidden()
        assert "restart" in page.locator("#msg-channel").inner_text()
    finally:
        page.unroute("**/api/updates/channel")


def test_the_plugins_page_names_a_constraints_file_chosen_by_hand(signed_in_page):
    page, url = signed_in_page
    _json_route(page, "**/api/updates/channel", {
        "channel": "stable", "channels": ["stable", "alpha"],
        "installer": {"follows": False, "custom": "/home/ovos/mine.txt"}})
    try:
        page.goto(f"{url}/plugins")
        page.locator("#installer-custom").wait_for()
        assert page.locator("#installer-custom-file").inner_text() == "/home/ovos/mine.txt"
        assert page.locator("#installer-off").is_hidden()
    finally:
        page.unroute("**/api/updates/channel")


def test_the_skills_page_lists_opens_and_goes_back(signed_in_page):
    page, url = signed_in_page
    _json_route(page, "**/api/updates", {"packages": [
        {"name": "ovos-skill-hello-world", "installed": "0.0.1", "latest": "0.1.0", "outdated": True}],
        "outdated": 1})
    try:
        page.goto(f"{url}/skills")
        page.wait_for_selector("#skilllist button.pick")
        names = [n.splitlines()[0] for n in page.locator("#skilllist button.pick").all_inner_texts()]
        assert "Hello World" in names and "Date Time" in names
        hello = page.locator("#skilllist li", has_text="Hello World")
        hello.locator(".badge").wait_for()

        page.fill("#filter", "date")
        assert page.locator("#skilllist button.pick").all_inner_texts() == ["Date Time"]
        page.fill("#filter", "")

        page.locator("#skilllist button.pick", has_text="Hello World").click()
        assert page.locator("#detail").is_visible() and not page.locator("#mine").is_visible()
        assert page.locator("#detail-title").inner_text() == "Hello World"
        assert page.locator("#detail-slug").inner_text() == "ovos-skill-hello-world"
        assert page.locator("#do-update").is_visible(), "the update offer shows on the skill"
        assert page.locator("#do-remove").is_visible()
        assert page.locator("#nosettings").is_visible()
        assert "#ovos-skill-hello-world" in page.url

        page.click("#back")
        assert page.locator("#mine").is_visible() and not page.locator("#detail").is_visible()
    finally:
        page.unroute("**/api/updates")


def test_find_more_searches_skills_only(signed_in_page):
    page, url = signed_in_page
    seen = []

    def search(route):
        seen.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "results": [{"name": "skill-homeassistant", "kind": "skill", "installed": False},
                        {"name": "ovos-skill-hello-world", "kind": "skill", "installed": True}],
            "total": 2, "kinds": ["skill"], "cache_age": 60}))

    page.route("**/api/plugins/search*", search)
    try:
        page.goto(f"{url}/")
        page.goto(f"{url}/skills#find")
        page.wait_for_selector("#find:not([hidden])")
        assert page.locator("#tab-find").get_attribute("aria-current") == "true"
        page.fill("#q", "home")
        page.click("#go")
        page.wait_for_selector("#results [data-add]")
        assert any("kind=skill" in u for u in seen)
        assert page.locator('#results [data-add="skill-homeassistant"]').count() == 1
        page.locator('#results [data-open="ovos-skill-hello-world"]').click()
        assert page.locator("#detail-title").inner_text() == "Hello World"
    finally:
        page.unroute("**/api/plugins/search*")


def test_the_old_abilities_address_lands_on_skills(signed_in_page):
    page, url = signed_in_page
    page.goto(f"{url}/abilities")
    page.wait_for_selector("#skilllist button.pick")
    assert page.url.rstrip("/").endswith("/skills")
    assert page.locator('nav a[aria-current="page"]').get_attribute("href") == "/skills"


def test_a_skill_with_settings_opens_its_settings_and_switch(signed_in_page, make_skill):
    page, url = signed_in_page
    make_skill("ovos-skill-hello-world.openvoiceos", {"greeting": "hi", "key": "s3cret", "mood": "glad"},
               meta={"skillMetadata": {"sections": [{"name": "General", "fields": [
                   {"name": "greeting", "type": "text", "label": "Greeting", "value": ""},
                   {"name": "mood", "type": "select", "label": "Mood", "options": "Sad|sad;Glad|glad"},
                   {"name": "key", "type": "password", "label": "Key"}]}]}})
    page.goto(f"{url}/")
    page.goto(f"{url}/skills#ovos-skill-hello-world.openvoiceos")
    page.wait_for_selector("#detail:not([hidden])")
    assert page.locator("#detail-slug").inner_text() == "ovos-skill-hello-world"
    page.wait_for_selector("#editor:not([hidden])")
    assert page.locator('#form input[name="greeting"]').input_value() == "hi"
    assert page.locator("#form h4").inner_text() == "General"
    assert page.locator('#form select[name="mood"]').input_value() == "glad"
    assert page.locator('#form input[name="key"]').input_value() == "", "a password is never shown"
    assert not page.locator("#nosettings").is_visible()
    page.wait_for_selector("#enable-card:not([hidden])")
    assert page.locator("#enable-toggle").inner_text()
    # listed once: the settings folder and the package are the same skill
    page.click("#back")
    assert page.locator("#skilllist button.pick", has_text="Hello World").count() == 1


def test_voice_and_language_shows_the_everyday_settings(signed_in_page):
    page, url = signed_in_page
    page.goto(f"{url}/voice")
    page.wait_for_load_state("networkidle")
    assert page.locator("h1").inner_text() == "Voice and language"
    page.wait_for_selector("#voice-body:not([hidden])")
    assert page.locator("#wake_word-select").is_visible()
    assert page.locator("#tts_module-select").is_visible()
    assert page.locator("#lang-input").is_visible()
    for n in page.locator(".voice-advanced").all():
        assert n.is_hidden()
    assert page.locator('#more-everyday a[href="/voice-all"]').is_visible()


def test_all_voice_settings_shows_everything(signed_in_page):
    page, url = signed_in_page
    page.goto(f"{url}/voice-all")
    page.wait_for_load_state("networkidle")
    assert page.locator("h1").inner_text() == "All voice settings"
    assert page.locator("#more-everyday").is_hidden()
    assert page.locator("#intro-all").is_visible()
    assert page.locator(".voice-advanced").count() == 2
    for n in page.locator(".voice-advanced").all():
        assert not n.evaluate("n => n.hidden")
    assert page.locator('nav a[aria-current="page"]').get_attribute("href") == "/voice-all"


def test_the_location_is_detected_on_the_voice_page(signed_in_page):
    page, url = signed_in_page
    page.goto(f"{url}/voice")
    page.wait_for_load_state("networkidle")
    assert page.locator("#location-card").is_visible()


def test_a_skill_from_find_more_can_be_looked_at_before_installing(signed_in_page):
    page, url = signed_in_page
    _json_route(page, "**/api/plugins/search*", {
        "results": [{"name": "ovos-skill-tales", "kind": "skill", "installed": False}],
        "total": 1, "kinds": ["skill"], "cache_age": 60})
    _json_route(page, "**/api/skillinfo/ovos-skill-tales", {
        "package": "ovos-skill-tales", "installed": False, "title": "Tales", "description": "Fairy tales",
        "examples": ["Tell me a story"], "author": "Someone", "version": "1.0",
        "released": "2026-10-01T10:00:00Z", "license": "MIT", "source": "https://github.com/someone/tales",
        "pypi": "https://pypi.org/project/ovos-skill-tales/", "is_ovos_skill": True, "has_icon": False})
    try:
        page.goto(f"{url}/")
        page.goto(f"{url}/skills#find")
        page.wait_for_selector("#find:not([hidden])")
        page.fill("#q", "tales")
        page.click("#go")
        page.click('[data-preview="ovos-skill-tales"]')
        page.wait_for_selector("#detail-examples:not([hidden])")
        assert page.locator("#detail-title").inner_text() == "Tales"
        assert "Someone" in page.locator("#detail-meta").inner_text()
        assert page.locator("#link-source").get_attribute("href") == "https://github.com/someone/tales"
        assert page.locator("#examples-list li").all_inner_texts() == ["Tell me a story"]
        assert page.locator("#do-install").is_visible()
        assert not page.locator("#do-remove").is_visible() and not page.locator("#settings-part").is_visible()
        page.click("#back")
        assert page.locator("#find").is_visible(), "back from a preview returns to the search"
    finally:
        page.unroute("**/api/plugins/search*")
        page.unroute("**/api/skillinfo/ovos-skill-tales")


def test_installing_says_what_it_would_downgrade_and_can_be_called_off(signed_in_page):
    page, url = signed_in_page
    _json_route(page, "**/api/plugins/search*", {
        "results": [{"name": "ovos-skill-tales", "kind": "skill", "installed": False}],
        "total": 1, "kinds": ["skill"], "cache_age": 60})
    _json_route(page, "**/api/plugins/check", {
        "package": "ovos-skill-tales", "checked": True, "upgrades": [], "new": [],
        "downgrades": [{"name": "ovos-bus-client", "from": "2.11.29", "to": "1.3.7"}]})
    installs = []
    page.route("**/api/plugins/install", lambda r: (installs.append(1), r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"id": "x", "state": "done", "lines": [], "next": 0})))[1])
    asked = []

    def answer(dialog):
        asked.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", answer)
    try:
        page.goto(f"{url}/")
        page.goto(f"{url}/skills#find")
        page.wait_for_selector("#find:not([hidden])")
        page.fill("#q", "tales")
        page.click("#go")
        page.click('#results [data-add="ovos-skill-tales"]')
        page.wait_for_function("() => !document.getElementById('install-check') "
                               "|| document.getElementById('install-check').hidden")
        page.wait_for_timeout(300)
        assert asked, "the install asks first"
        assert "ovos-bus-client 2.11.29 → 1.3.7" in asked[0]
        assert "older versions" in asked[0]
        assert installs == [], "saying no installs nothing"
    finally:
        page.remove_listener("dialog", answer)
        for pattern in ("**/api/plugins/search*", "**/api/plugins/check", "**/api/plugins/install"):
            page.unroute(pattern)


def test_the_about_page_names_pages_other_packages_added(signed_in_page):
    page, url = signed_in_page
    _json_route(page, "**/api/pages", {
        "pages": [{"id": "about", "path": "/about", "title": "About", "group": "everyday",
                   "package": "ovos-control-panel", "version": "1", "builtin": True},
                  {"id": "guardian", "path": "/emkay/guardian", "title": "Guardian", "group": "device",
                   "package": "ovos-skill-guardian", "version": "0.3.0", "builtin": False}],
        "problems": [{"page": "broken", "package": "ovos-skill-x", "error": "no group called nowhere"}]})
    try:
        page.goto(f"{url}/about")
        page.locator("#pages-added li").first.wait_for()
        text = page.locator("#pages-added").inner_text()
        assert "Guardian" in text and "ovos-skill-guardian" in text and "0.3.0" in text
        assert page.locator("#pages-none").is_hidden()
        assert "1 of the pages" in page.locator("#pages-count").inner_text()
        assert "no group called nowhere" in page.locator("#pages-problem-list").inner_text()
    finally:
        page.unroute("**/api/pages")


def test_a_described_page_draws_from_its_file(signed_in_page):
    """described.js: a page from controlpanel.json is drawn, its rows show,
    a row's actions follow their conditions, and nothing throws."""
    page, url = signed_in_page
    thrown = []
    page.on("pageerror", lambda err: thrown.append(str(err)))
    from ovos_webui import described
    desc, _ = described.check({
        "controlpanel": 1, "id": "demo", "bus": "ovos.demo.",
        "blocks": [
            {"type": "status", "query": "ovos.demo.list", "show": "playing",
             "text": {"key": "demo.playing", "en": "Playing {playing}"},
             "actions": [{"label": "common.stop", "send": "ovos.demo.stop"}]},
            {"type": "list", "query": "ovos.demo.list", "items": "things", "key": "id", "title": "{name}",
             "split": {"by": "fixed", "false": "demo.mine", "true": "demo.theirs"},
             "filter": {"by": "who", "label": "demo.who"},
             "rename": {"field": "name", "send": "ovos.demo.rename", "when": "!fixed"},
             "actions": [{"label": "common.delete", "send": "ovos.demo.delete", "when": "!fixed"}]},
            {"type": "sparkles"}]}, "ovos-skill-demo")
    desc["en"] = {"demo.playing": "Playing {playing}"}
    answer = {"playing": "Tune", "things": [{"id": "a", "name": "Mine", "fixed": False, "who": "me"},
                                            {"id": "b", "name": "<b>Theirs</b>", "fixed": True, "who": "you"}]}
    page.route("**/api/cp/demo/query", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(answer)))
    try:
        page.goto(f"{url}/about")
        page.wait_for_load_state("networkidle")
        page.evaluate("""desc => {
            const root = document.createElement('div'); root.id = 'cp-page';
            const data = document.createElement('script'); data.type = 'application/json';
            data.id = 'cp-desc'; data.textContent = JSON.stringify(desc);
            document.querySelector('main').append(root, data);
            const s = document.createElement('script'); s.src = '/static/described.js';
            s.onload = () => document.dispatchEvent(new Event('DOMContentLoaded'));
            document.body.append(s);
        }""", desc)
        page.wait_for_selector("#cp-page .cp-list li")
        page.wait_for_timeout(300)
        text = page.locator("#cp-page").inner_text()
        assert "Playing Tune" in text and "<b>Theirs</b>" in text, "values are text, not HTML"
        assert page.locator("#cp-page input[type=text]").count() == 1, "only my row can be renamed"
        assert page.locator("#cp-page button.danger").count() == 1, "only my row can be deleted"
        assert "newer control panel" in text
        page.select_option("#cp-page .cp-filter select", "you")
        assert page.locator("#cp-page .cp-list li").count() == 2, "their row, and an empty 'mine'"
        assert page.locator("#cp-page input[type=text]").count() == 0, "my row is filtered away"
        page.select_option("#cp-page .cp-filter select", "")
        assert page.locator("#cp-page input[type=text]").count() == 1
        assert not thrown, thrown
    finally:
        page.unroute("**/api/cp/demo/query")
