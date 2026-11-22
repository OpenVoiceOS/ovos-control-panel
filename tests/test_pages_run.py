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


def test_the_mark1_face_actually_draws(signed_in_page):
    """A canvas that stays blank is the shape the ordering bug took.

    Asserting the script does not throw is not enough on its own: a drawing
    that silently no-ops looks identical to a working one in every other test.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
    lit = page.evaluate("""(() => {
      const c = document.getElementById('mark1-canvas');
      if (!c) { return -1; }
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let n = 0;
      // Counted bright, not merely non-black: the unlit lamps are drawn dark
      // grey and there are 256 of them, so anything counting "not the
      // background" is cleared many times over by a face where nothing lights
      // and nothing works.
      for (let i = 0; i < d.length; i += 4) {
        if (Math.max(d[i], d[i + 1], d[i + 2]) > 140) { n++; }
      }
      return n;
    })()""")
    assert lit > 500, f"the faceplate drew nothing lit ({lit} bright pixels)"


def _canvas_signature(page):
    """A cheap fingerprint of what the face is showing."""
    return page.evaluate("""(() => {
      const c = document.getElementById('mark1-canvas');
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let sum = 0;
      for (let i = 0; i < d.length; i += 4) { sum += d[i] + d[i + 1] + d[i + 2]; }
      return sum;
    })()""")


def test_capturing_and_replaying_a_frame_round_trips(signed_in_page):
    """Draw, capture, clear, replay: the face must come back.

    Driven entirely through the page's own controls and read off the canvas,
    because the script runs inside a closure -- reaching into its variables
    would test something the user cannot do.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    page.click("#preset-heart")
    page.wait_for_timeout(100)
    drawn = _canvas_signature(page)
    page.click("#anim-capture")
    assert page.locator("#anim-frames li").count() == 1

    page.click("#mouth-clear")
    page.wait_for_timeout(100)
    cleared = _canvas_signature(page)
    assert cleared < drawn, "clearing the mouth changed nothing on the canvas"

    page.locator("#anim-frames li button").first.click()
    page.wait_for_timeout(100)
    assert _canvas_signature(page) == drawn, (
        "replaying the frame did not restore the face"
    )


def test_a_frame_cannot_be_asked_to_hold_shorter_than_the_writer_accepts(
        signed_in_page):
    """Below 0.4s ovos-mark1-utils clamps the delay itself.

    A shorter hold is not a faster animation. The `min`
    attribute on the field is only form validation, and nothing here submits a
    form, so this drives the field to an impossible value and reads back what
    the export actually wrote.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)
    assert page.get_attribute("#anim-hold", "min") == "0.4"

    page.click("#preset-smile")
    page.click("#anim-capture")
    page.fill("#anim-hold", "0.05")
    with page.expect_download() as caught:
        page.click("#anim-export")
    exported = json.loads(Path(caught.value.path()).read_text())
    assert exported["hold"] >= 0.4, (
        f"exported an animation the faceplate would drop: {exported['hold']}"
    )

    # The ceiling is form validation too, and nothing here submits a form.
    page.fill("#anim-hold", "9999")
    with page.expect_download() as caught:
        page.click("#anim-export")
    exported = json.loads(Path(caught.value.path()).read_text())
    assert exported["hold"] <= 10, (
        f"exported a frame held for {exported['hold']}s"
    )


def test_a_removed_frame_leaves_the_rest_of_the_sequence(signed_in_page):
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)
    for preset in ("#preset-heart", "#preset-note", "#preset-smile"):
        page.click(preset)
        page.click("#anim-capture")
    assert page.locator("#anim-frames li").count() == 3
    page.locator("#anim-frames li").nth(1).locator("button").nth(1).click()
    assert page.locator("#anim-frames li").count() == 2
    page.click("#anim-clear")
    assert page.locator("#anim-frames li").count() == 0


def test_clicking_one_eye_led_sends_a_request_the_route_accepts(signed_in_page):
    """A body the browser stringifies to "[object Object]" is a 422.

    `fetch` does not serialise a plain object and does not set a content type,
    so a per-LED write that skipped `JSON.stringify` reached the route as text
    and was rejected on every click. Nothing in the Python suite sees this: the
    route is fine, the page is fine, only the pair is wrong.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    statuses = []
    page.on("response", lambda r: statuses.append(r.status)
            if "/api/mark1/eyes/pixel" in r.url else None)

    # LED 0 sits at the top of the left ring. The eyes are drawn on the canvas,
    # not built from elements, so the click has to land where the LED is.
    box = page.locator("#mark1-canvas").bounding_box()
    spot = page.evaluate("""(() => {
      const c = document.getElementById("mark1-canvas");
      const RING_R = 38, LED_R = 5.5, GAP = 20, CELL = 12;
      const EYE_BOX = RING_R * 2 + LED_R * 2, MOUTH_W = 32 * CELL;
      const FACE_H = Math.max(8 * CELL, EYE_BOX);
      const PAD_X = Math.round((c.width - (EYE_BOX * 2 + GAP * 2 + MOUTH_W)) / 2);
      const PAD_Y = Math.round((c.height - FACE_H) / 2);
      return {x: PAD_X + EYE_BOX / 2, y: PAD_Y + FACE_H / 2 - RING_R,
              w: c.width, h: c.height};
    })()""")
    page.mouse.click(box["x"] + spot["x"] * box["width"] / spot["w"],
                     box["y"] + spot["y"] * box["height"] / spot["h"])
    page.wait_for_timeout(500)

    assert statuses, "clicking an LED sent nothing at all"
    assert 422 not in statuses, (
        f"the route rejected the per-LED body: {statuses}"
    )


def test_an_imported_animation_with_the_wrong_shape_is_refused(signed_in_page):
    """A row of the wrong width plays as a face nobody drew."""
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    good_grid = [[0] * 32 for _ in range(8)]
    good_eyes = [[1, 2, 3] for _ in range(24)]
    rejected = {
        "a row narrower than the mouth": {
            "grid": [[1, 1, 1, 1, 1]] * 8, "eyes": good_eyes},
        "a cell that is not 0 or 1": {
            "grid": [[7] * 32] + good_grid[1:], "eyes": good_eyes},
        "an eye list of the wrong length": {
            "grid": good_grid, "eyes": good_eyes[:5]},
        "an eye that is not a colour": {
            "grid": good_grid, "eyes": [None] * 24},
        "an eye with the wrong number of channels": {
            "grid": good_grid, "eyes": [[1, 2]] * 24},
        "a channel outside 0-255": {
            "grid": good_grid,
            "eyes": [[999, 0, 0]] + good_eyes[1:]},
    }
    for why, frame in rejected.items():
        page.set_input_files("#anim-import", files=[{
            "name": "bad.json", "mimeType": "application/json",
            "buffer": json.dumps(
                {"version": 1, "hold": 0.4, "frames": [frame]}).encode()}])
        page.wait_for_timeout(200)
        assert page.locator("#anim-frames li").count() == 0, (
            f"loaded a frame with {why}"
        )

    page.set_input_files("#anim-import", files=[{
        "name": "good.json", "mimeType": "application/json",
        "buffer": json.dumps({"version": 1, "hold": 0.4, "frames": [
            {"grid": good_grid, "eyes": good_eyes}]}).encode()}])
    page.wait_for_timeout(200)
    assert page.locator("#anim-frames li").count() == 1, (
        "refused a frame that is the right shape"
    )

    # A file that is partly usable must say what it dropped, or the editor
    # quietly holds fewer frames than the file the reader just opened.
    page.set_input_files("#anim-import", files=[{
        "name": "mixed.json", "mimeType": "application/json",
        "buffer": json.dumps({"version": 1, "hold": 0.4, "frames": [
            {"grid": good_grid, "eyes": good_eyes},
            {"grid": [[7] * 32] * 8, "eyes": good_eyes}]}).encode()}])
    page.wait_for_timeout(200)
    assert page.locator("#anim-frames li").count() == 1
    said = page.locator("#msg-anim").inner_text()
    assert "1" in said and "skipped" in said.lower(), (
        f"loaded half a file without saying so: {said!r}"
    )


def test_the_python_export_carries_the_eyes_it_showed(signed_in_page):
    """A frame is a mouth and two eyes; exporting half of it is a lie."""
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    page.click("#preset-smile")
    page.click("#anim-capture")
    with page.expect_download() as caught:
        page.click("#anim-export-py")
    source = Path(caught.value.path()).read_text()

    assert "enclosure.eyes.setpixel" in source, (
        "the exported eyes never reach the faceplate"
    )
    table = source[source.index("EYES = ["):source.index("class PanelAnimation")]
    colours = re.findall(r"\((\d+), (\d+), (\d+)\)", table)
    assert len(colours) == 24, (
        f"exported {len(colours)} eye pixels for one frame, not 24: {table}"
    )
    assert any(c != ("0", "0", "0") for c in colours), (
        "every exported eye pixel is off, so the export lost the colours"
    )
    assert "frame.display(invert=True)" in source, (
        "the export draws the mouth inverted against what the panel showed"
    )


def test_a_refused_frame_stops_the_animation(signed_in_page):
    """`ok: false` arrives as HTTP 200, so only the body says it failed.

    Walking on through a refusal and then announcing that the animation
    finished is the exact failure this panel exists to stop: a control that
    reports success and did nothing.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    posted = []

    def refuse(route):
        posted.append(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": False, "error": "no faceplate"}))

    # Both halves of a frame, because a frame is a mouth and two eyes and
    # either being refused has to stop the run.
    page.route("**/api/mark1/display", refuse)
    page.route("**/api/mark1/eyes/**", refuse)

    for preset in ("#preset-heart", "#preset-note", "#preset-smile"):
        page.click(preset)
        page.click("#anim-capture")
    page.click("#anim-send")
    page.wait_for_timeout(2000)

    displays = [u for u in posted if u.endswith("/display")]
    assert len(displays) == 1, (
        f"kept sending frames after the device refused one: {displays}"
    )
    said = page.locator("#msg-anim").inner_text()
    assert "no faceplate" in said, f"did not report the refusal: {said!r}"


def test_the_controls_send_even_when_no_device_could_be_confirmed(
        signed_in_page):
    """The probe cannot prove a Mark 1 is absent, so it must not disable them.

    Nothing answers `enclosure.eyes.rgb.get` in this fixture, which is exactly
    what a real Mark 1 running a plugin too old to reply looks like.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    assert not page.locator("#gate").is_hidden(), (
        "said nothing about being unable to confirm a device"
    )

    sent = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" else None)
    page.click("#preset-smile")
    page.click("#mouth-send")
    page.click("#eyes-on")
    page.wait_for_timeout(700)

    assert any("/api/mark1/display" in u for u in sent), (
        "the drawing was never sent because the probe stayed silent"
    )
    assert any("/api/mark1/eyes" in u for u in sent), (
        "the eye control was never sent because the probe stayed silent"
    )


def test_playing_an_animation_sends_the_eyes_it_showed(signed_in_page):
    """A frame is a mouth and twenty-four LEDs; sending half of it is a lie.

    The on-screen face animates from the frame directly, so eyes that never
    reach the device look exactly like eyes that did -- an eyes-only animation
    plays perfectly in the browser and does nothing on the hardware, with the
    panel reporting that it finished.

    Asserting on the exact writes, not merely that some request went out: the
    interesting failures are a frame after the first being skipped, a diff
    that compares one channel, and an index off by one. All three send
    something.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    posts = []

    def record(route):
        request = route.request
        posts.append((request.url.rsplit("/api/mark1", 1)[1],
                      request.post_data_json))
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": True}))

    page.route("**/api/mark1/eyes/**", record)
    page.route("**/api/mark1/display", record)

    # Frame one: every LED the same colour, so one fill covers it.
    page.click("#preset-smile")
    page.eval_on_selector("#eyes-color", "el => { el.value = '#0a1400'; "
                          "el.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.wait_for_timeout(150)
    page.click("#anim-capture")

    # Frame two: four LEDs changed, the other twenty untouched. One of them
    # keeps frame one's red and changes only green, so a diff that compares a
    # single channel drops it.
    changed = {2: (255, 0, 0), 7: (0, 255, 0), 19: (0, 0, 255),
               15: (10, 200, 0)}
    page.evaluate(
        """(changed) => {
          const c = document.getElementById("mark1-canvas");
          const RING_R = 38, LED_R = 5.5, GAP = 20, CELL = 12;
          const EYE_BOX = RING_R * 2 + LED_R * 2, MOUTH_W = 32 * CELL;
          const FACE_H = Math.max(8 * CELL, EYE_BOX);
          const PAD_X = Math.round((c.width - (EYE_BOX * 2 + GAP * 2 + MOUTH_W)) / 2);
          const PAD_Y = Math.round((c.height - FACE_H) / 2);
          const MOUTH_X = PAD_X + EYE_BOX + GAP;
          const rect = c.getBoundingClientRect();
          const picker = document.getElementById("eyes-color");
          for (const [idx, rgb] of Object.entries(changed)) {
            const i = Number(idx);
            const within = i % 12;
            const angle = (within / 12) * Math.PI * 2 - Math.PI / 2;
            const cx = i < 12 ? PAD_X + EYE_BOX / 2
                              : MOUTH_X + MOUTH_W + GAP + EYE_BOX / 2;
            const x = cx + Math.cos(angle) * RING_R;
            const y = PAD_Y + FACE_H / 2 + Math.sin(angle) * RING_R;
            // Set the value only. An "input" event repaints the whole ring,
            // which would make every LED differ from the previous frame and
            // hide exactly the diff this test is about.
            picker.value = "#" + rgb.map(
              v => v.toString(16).padStart(2, "0")).join("");
            c.dispatchEvent(new PointerEvent("pointerdown", {
              bubbles: true,
              clientX: rect.left + x * rect.width / c.width,
              clientY: rect.top + y * rect.height / c.height}));
          }
        }""", {str(k): list(v) for k, v in changed.items()})
    page.wait_for_timeout(300)
    page.click("#anim-capture")
    assert page.locator("#anim-frames li").count() == 2

    posts.clear()
    page.click("#anim-send")
    page.wait_for_timeout(3000)

    fills = [body for path, body in posts if path == "/eyes/color"]
    pixels = [body for path, body in posts if path == "/eyes/pixel"]
    displays = [body for path, body in posts if path == "/display"]

    assert len(displays) == 2, f"sent {len(displays)} mouths for two frames"
    assert len(fills) == 1, (
        f"a frame whose LEDs all match is one fill, not {len(fills)}: {fills}"
    )
    assert fills[0] == {"r": 10, "g": 20, "b": 0}, fills[0]
    assert {p["idx"] for p in pixels} == set(changed), (
        f"wrote {sorted(p['idx'] for p in pixels)}, expected {sorted(changed)}"
    )
    for post in pixels:
        r, g, b = changed[post["idx"]]
        assert (post["r"], post["g"], post["b"]) == (r, g, b), (
            f"LED {post['idx']} was sent {post} instead of {(r, g, b)}"
        )


def test_toggling_away_and_back_does_not_stack_poll_chains(signed_in_page):
    """The eye readback blocks for the probe timeout on a silent device.

    Anything that starts a second chain while the first is still waiting
    leaves both running, and each one hits a privileged route every 1.5s
    forever. Switching tabs is the easy way to do it by accident.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    reads = []

    def slow(route):
        reads.append(route.request.url)
        page.wait_for_timeout(1200)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": True, "pixels": [[1, 2, 3]] * 24}))

    page.route("**/api/mark1/eyes", slow)
    page.evaluate("() => { document.getElementById('live-row').hidden = false; }")
    page.click("#live-toggle")
    page.wait_for_timeout(200)

    for _ in range(3):
        page.evaluate("""() => {
          Object.defineProperty(document, "hidden", {value: true, configurable: true});
          document.dispatchEvent(new Event("visibilitychange"));
          Object.defineProperty(document, "hidden", {value: false, configurable: true});
          document.dispatchEvent(new Event("visibilitychange"));
        }""")
        page.wait_for_timeout(100)

    reads.clear()
    page.wait_for_timeout(4000)
    page.click("#live-toggle")

    # One chain reads about once per 1.2s request plus 1.5s wait. Several
    # chains read several times as often.
    assert len(reads) <= 3, (
        f"visibility toggling started concurrent poll chains: {len(reads)} "
        "reads in four seconds"
    )


def test_a_frame_that_rewrites_every_led_is_held_longer_than_the_floor(
        signed_in_page):
    """The floor is what the faceplate tolerates, not what the wire can carry.

    Twenty-four eye writes plus a mouth, each about twenty bytes down a
    9600-baud line, take longer than 0.4s to arrive. Sending the next frame on
    the floor regardless grows the queue behind the serial port for as long as
    the animation runs.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    at = []
    page.route("**/api/mark1/display", lambda route: (
        at.append(time.monotonic()),
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": True}))))
    page.route("**/api/mark1/eyes/**", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True})))

    # The heavy frame first: a frame's own hold is what delays the frame after
    # it, so measuring the gap between the first two writes measures frame
    # one. Every LED a different colour, so the diff cannot collapse to a
    # single fill and all twenty-four are written.
    page.evaluate("""() => {
      const c = document.getElementById("mark1-canvas");
      const RING_R = 38, LED_R = 5.5, GAP = 20, CELL = 12;
      const EYE_BOX = RING_R * 2 + LED_R * 2, MOUTH_W = 32 * CELL;
      const FACE_H = Math.max(8 * CELL, EYE_BOX);
      const PAD_X = Math.round((c.width - (EYE_BOX * 2 + GAP * 2 + MOUTH_W)) / 2);
      const PAD_Y = Math.round((c.height - FACE_H) / 2);
      const MOUTH_X = PAD_X + EYE_BOX + GAP;
      const rect = c.getBoundingClientRect();
      const picker = document.getElementById("eyes-color");
      for (let i = 0; i < 24; i++) {
        const angle = ((i % 12) / 12) * Math.PI * 2 - Math.PI / 2;
        const cx = i < 12 ? PAD_X + EYE_BOX / 2
                          : MOUTH_X + MOUTH_W + GAP + EYE_BOX / 2;
        picker.value = "#" + (0x201000 + i * 0x010101).toString(16).padStart(6, "0");
        c.dispatchEvent(new PointerEvent("pointerdown", {
          bubbles: true,
          clientX: rect.left + (cx + Math.cos(angle) * RING_R) * rect.width / c.width,
          clientY: rect.top + (PAD_Y + FACE_H / 2 + Math.sin(angle) * RING_R)
                   * rect.height / c.height}));
      }
    }""")
    page.wait_for_timeout(300)
    page.click("#anim-capture")
    page.eval_on_selector("#eyes-color", "el => { el.value = '#010203'; "
                          "el.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.wait_for_timeout(150)
    page.click("#anim-capture")
    page.fill("#anim-hold", "0.4")

    at.clear()
    page.click("#anim-send")
    page.wait_for_timeout(3000)

    assert len(at) == 2, f"expected two frames, saw {len(at)}"
    gap = at[1] - at[0]
    # The mouth costs about 0.36s and each of the twenty-four eye writes about
    # 0.022s, so this frame needs roughly 0.89s. The lower bound has to sit
    # above the floor plus request overhead, or a hold that ignored the write
    # count would clear it anyway; the upper bound is what stops the constant
    # from being quietly doubled, which would halve every heavy animation's
    # speed for no reason.
    assert 0.8 < gap < 1.2, (
        f"held a twenty-five-write frame for {gap:.2f}s; it needs about 0.89s "
        "for its own writes to reach the board"
    )


def test_following_can_be_restarted_after_it_is_stopped(signed_in_page):
    """Stopping mid-read must not leave the chain unable to start again.

    The guard that stops a second chain from starting is a flag, and a flag
    that nothing clears on the way out is a page that says it is following
    and never reads anything again.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    reads = []

    def answer(route):
        reads.append(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": True, "pixels": [[1, 2, 3]] * 24}))

    page.route("**/api/mark1/eyes", answer)
    page.evaluate("() => { document.getElementById('live-row').hidden = false; }")

    # Stopped between reads, not during one: an outstanding read would clear
    # the guard on its way out and hide a guard that is never cleared.
    page.click("#live-toggle")          # follow
    page.wait_for_timeout(600)          # first read done, waiting for the next
    page.click("#live-toggle")          # stop while idle
    page.wait_for_timeout(200)

    reads.clear()
    page.click("#live-toggle")          # follow again
    page.wait_for_timeout(1200)
    page.click("#live-toggle")

    assert reads, "following never read the device again after a stop"


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
def _media_page(page, url, *, backends, status=None, progress=None, likes=None):
    """The media page against a device that answers what we say it answers."""
    import json as _json

    def answer(payload):
        return lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=_json.dumps(payload))

    # Handlers accumulate, and a second call to this would otherwise be
    # answered by the first call's stubs.
    for pattern in ("**/api/media/available", "**/api/media/backends",
                    "**/api/media/status", "**/api/media/progress",
                    "**/api/media/volume", "**/api/media/seek"):
        page.unroute(pattern)

    page.route("**/api/media/available", answer({"available": True}))
    page.route("**/api/media/likes",
               answer(likes if likes is not None else {"ok": True, "entries": []}))
    page.route("**/api/media/backends", answer(backends))
    page.route("**/api/media/status", answer(status or {
        "state": "playing", "title": "A song", "artist": "Someone",
        "image": None, "shuffle": False, "repeat": "off", "media_type": None,
        "playlist_position": 0, "playlist_size": 1}))
    page.route("**/api/media/progress", answer(progress or {
        "ok": True, "position": 30000, "length": 240000}))
    page.route("**/api/media/volume", answer({"percent": 50, "muted": False}))
    page.goto(f"{url}/media")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


def test_a_device_with_no_playback_backend_says_so(signed_in_page):
    """The hardest media failure to see from outside: every play request is
    accepted and nothing comes out."""
    page, url = signed_in_page
    _media_page(page, url, backends={"ok": True, "backends": [],
                                     "can_play": False})
    assert not page.locator("#no-backends").is_hidden(), (
        "a device that cannot play anything said nothing about it"
    )


def test_a_device_that_cannot_be_asked_is_not_accused_of_being_mute(
        signed_in_page):
    """An older media service that does not answer the question has not told
    us the device has no backends."""
    page, url = signed_in_page
    _media_page(page, url, backends={"ok": False, "backends": [],
                                     "can_play": None})
    assert page.locator("#no-backends").is_hidden()


def test_a_device_with_a_backend_says_nothing(signed_in_page):
    page, url = signed_in_page
    _media_page(page, url, backends={
        "ok": True, "can_play": True,
        "backends": [{"name": "mpv", "remote": False, "uris": ["file"]}]})
    assert page.locator("#no-backends").is_hidden()


def test_the_scrub_bar_only_appears_for_a_track_with_an_end(signed_in_page):
    """A live stream has no length, so there is nowhere to drag to."""
    page, url = signed_in_page
    good = {"ok": True, "backends": [{"name": "mpv", "remote": False,
                                      "uris": ["file"]}], "can_play": True}

    _media_page(page, url, backends=good)
    assert not page.locator("#seek-row").is_hidden(), "no scrub bar for a track"
    assert page.locator("#seek-length").inner_text() == "4:00"
    assert page.locator("#seek-position").inner_text() == "0:30"

    _media_page(page, url, backends=good,
                progress={"ok": True, "position": 9000, "length": None})
    # Polled rather than read once: the row is hidden when the page's own
    # progress request comes back, not when the page finishes loading.
    page.wait_for_selector("#seek-row", state="hidden", timeout=5000)


def test_dragging_the_scrub_bar_sends_an_absolute_position(signed_in_page):
    page, url = signed_in_page
    sent = []
    _media_page(page, url, backends={"ok": True, "can_play": True,
                                     "backends": [{"name": "mpv",
                                                   "remote": False,
                                                   "uris": ["file"]}]})
    page.route("**/api/media/seek", lambda route: (
        sent.append(route.request.post_data_json),
        route.fulfill(status=200, content_type="application/json",
                      body='{"ok": true}')))
    page.eval_on_selector("#seek", "el => { el.value = 500; "
                          "el.dispatchEvent(new Event('change', {bubbles: true})); }")
    page.wait_for_timeout(400)

    assert sent, "dragging the bar sent nothing"
    # Half of a four minute track, in milliseconds.
    assert sent[0]["position"] == 120000, sent[0]


def test_hidden_means_hidden_whatever_the_element_is(signed_in_page):
    """`hidden` is an attribute, not a class, and any rule that sets
    `display` outranks the browser's default for it.

    Two rows in this panel are flex containers marked hidden, and both were
    on screen: the Mark-1 live row on a device with no Mark-1, and the media
    scrub bar for a track with no length. A page that shows a control it
    means to be offering later is a page lying about what it can do.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)

    showing = page.evaluate("""() => [...document.querySelectorAll("[hidden]")]
        .filter(el => getComputedStyle(el).display !== "none")
        .map(el => el.id || el.className)""")
    assert showing == [], f"marked hidden and still on screen: {showing}"


def test_the_repeat_box_reports_and_sets_the_state_the_device_is_in(signed_in_page):
    """`REPEAT` is the queue and `REPEAT_TRACK` is the one track; naming them
    the other way round makes the badge say the opposite of what is happening.
    """
    page, url = signed_in_page
    good = {"ok": True, "can_play": True,
            "backends": [{"name": "mpv", "remote": False, "uris": ["file"]}]}
    _media_page(page, url, backends=good, status={
        "state": "playing", "title": "A song", "artist": "Someone",
        "image": None, "shuffle": False, "repeat": "all", "media_type": None,
        "playlist_position": 0, "playlist_size": 3})

    assert page.locator("#repeat").is_checked(), (
        "the queue repeats and the box says it does not"
    )
    assert "queue" in page.locator("#np-repeat").inner_text().lower()

    sent = []
    page.route("**/api/media/repeat", lambda route: (
        sent.append(route.request.post_data_json),
        route.fulfill(status=200, content_type="application/json",
                      body='{"ok": true}')))
    page.uncheck("#repeat")
    page.wait_for_timeout(400)
    assert sent == [{"enabled": False}], sent


def test_a_single_track_repeat_is_not_called_a_queue_repeat(signed_in_page):
    page, url = signed_in_page
    _media_page(page, url,
                backends={"ok": True, "can_play": True,
                          "backends": [{"name": "mpv", "remote": False,
                                        "uris": ["file"]}]},
                status={"state": "playing", "title": "A song", "artist": "S",
                        "image": None, "shuffle": False, "repeat": "one",
                        "media_type": None, "playlist_position": 0,
                        "playlist_size": 3})
    said = page.locator("#np-repeat").inner_text().lower()
    assert "track" in said, said
    assert not page.locator("#repeat").is_checked(), (
        "repeating one track is not repeating the queue"
    )
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


def test_clicking_between_two_lamps_still_draws_that_pixel(signed_in_page):
    """The lamps are drawn smaller than their cells, so there is a gap
    between them on screen. Hit-testing is by cell, not by lamp: a person
    aiming at the corner of a pixel gets that pixel, not nothing.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)

    page.click("#mouth-clear")
    page.wait_for_timeout(150)
    before = _canvas_signature(page)

    box = page.locator("#mark1-canvas").bounding_box()
    spot = page.evaluate("""(() => {
      const c = document.getElementById("mark1-canvas");
      const RING_R = 38, LED_R = 5.5, GAP = 20, CELL = 12;
      const EYE_BOX = RING_R * 2 + LED_R * 2, MOUTH_W = 32 * CELL;
      const FACE_H = Math.max(8 * CELL, EYE_BOX);
      const PAD_X = Math.round((c.width - (EYE_BOX * 2 + GAP * 2 + MOUTH_W)) / 2);
      const PAD_Y = Math.round((c.height - FACE_H) / 2);
      const MOUTH_X = PAD_X + EYE_BOX + GAP;
      const MOUTH_Y = PAD_Y + Math.round((FACE_H - 8 * CELL) / 2);
      // The very corner of the first cell: as far from that lamp's centre as
      // a click can land while still being inside the pixel.
      return {x: MOUTH_X + 1, y: MOUTH_Y + 1, w: c.width, h: c.height};
    })()""")
    page.mouse.click(box["x"] + spot["x"] * box["width"] / spot["w"],
                     box["y"] + spot["y"] * box["height"] / spot["h"])
    page.wait_for_timeout(200)

    assert _canvas_signature(page) != before, (
        "a click inside a pixel but between the lamps drew nothing"
    )


def test_the_mouth_is_round_lamps_that_stay_visible_unlit(signed_in_page):
    """On the device every lamp in the grid is there in the plastic whether
    it is lit or not, and the lamps are round.

    Both halves matter and neither is visible to a test that only counts
    pixels: square cells that fill their cell, or unlit lamps painted the
    colour of the background, each make the display read as something other
    than the one on the desk.
    """
    page, url = signed_in_page
    page.goto(f"{url}/mark1")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)
    page.click("#mouth-clear")
    page.wait_for_timeout(200)

    sampled = page.evaluate("""(() => {
      const c = document.getElementById("mark1-canvas");
      const g = c.getContext("2d");
      const RING_R = 38, LED_R = 5.5, GAP = 20, CELL = 12;
      const EYE_BOX = RING_R * 2 + LED_R * 2, MOUTH_W = 32 * CELL;
      const FACE_H = Math.max(8 * CELL, EYE_BOX);
      const PAD_X = Math.round((c.width - (EYE_BOX * 2 + GAP * 2 + MOUTH_W)) / 2);
      const PAD_Y = Math.round((c.height - FACE_H) / 2);
      const MOUTH_X = PAD_X + EYE_BOX + GAP;
      const MOUTH_Y = PAD_Y + Math.round((FACE_H - 8 * CELL) / 2);
      const at = (x, y) => {
        const d = g.getImageData(Math.round(x), Math.round(y), 1, 1).data;
        return Math.max(d[0], d[1], d[2]);
      };
      // The middle of a lamp, and the corner of the same cell.
      const cell = (col, rowIndex) => ({
        centre: at(MOUTH_X + col * CELL + CELL / 2, MOUTH_Y + rowIndex * CELL + CELL / 2),
        corner: at(MOUTH_X + col * CELL + 1, MOUTH_Y + rowIndex * CELL + 1)
      });
      return {first: cell(0, 0), middle: cell(15, 4), last: cell(31, 7)};
    })()""")

    for where, sample in sampled.items():
        assert sample["centre"] > 24, (
            f"the unlit lamp at {where} is invisible against the faceplate "
            f"({sample['centre']})"
        )
        assert sample["corner"] < sample["centre"] - 8, (
            f"the lamp at {where} fills its cell corner to centre "
            f"({sample['corner']} vs {sample['centre']}), so it is not round"
        )


def test_the_candidate_list_offers_the_other_matches(signed_in_page):
    """"It played the wrong thing" should be one click, not a rephrase."""
    import json as _json

    page, url = signed_in_page
    entries = [
        {"title": "The right one", "artist": "A", "uri": "file:///a.mp3",
         "match_confidence": 90},
        {"title": "The wrong one", "artist": "B", "uri": "file:///b.mp3",
         "match_confidence": 60},
    ]
    page.route("**/api/media/candidates", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=_json.dumps({"ok": True, "entries": entries})))
    _media_page(page, url, backends={"ok": True, "can_play": True,
                                     "backends": [{"name": "mpv",
                                                   "remote": False,
                                                   "uris": ["file"]}]})

    assert not page.locator("#candidates-card").is_hidden()
    titles = page.locator("#candidates li button").all_inner_texts()
    assert "The right one" in titles[0], titles

    sent = []
    page.route("**/api/media/play_entry", lambda route: (
        sent.append(route.request.post_data_json),
        route.fulfill(status=200, content_type="application/json",
                      body='{"ok": true}')))
    page.locator("#candidates li button").nth(1).click()
    page.wait_for_timeout(400)
    assert sent and sent[0]["entry"]["uri"] == "file:///b.mp3", sent
    # This row knows the set, because it is the row showing it, so it sends it
    # rather than making the service read it back.
    assert [e["uri"] for e in sent[0]["among"]] == \
        [e["uri"] for e in entries], sent[0]


def test_one_candidate_is_not_a_choice(signed_in_page):
    """A single candidate is what is already playing."""
    import json as _json

    page, url = signed_in_page
    page.route("**/api/media/candidates", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=_json.dumps({"ok": True, "entries": [
            {"title": "Only", "uri": "file:///a.mp3"}]})))
    _media_page(page, url, backends={"ok": True, "can_play": True,
                                     "backends": [{"name": "mpv",
                                                   "remote": False,
                                                   "uris": ["file"]}]})
    assert page.locator("#candidates-card").is_hidden()


def test_a_player_too_old_to_be_asked_shows_no_candidate_card(signed_in_page):
    """The queries arrived in ovos-media 2.2.0a1; before that, silence."""
    import json as _json

    page, url = signed_in_page
    page.route("**/api/media/candidates", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=_json.dumps({"ok": False, "entries": []})))
    _media_page(page, url, backends={"ok": True, "can_play": True,
                                     "backends": [{"name": "mpv",
                                                   "remote": False,
                                                   "uris": ["file"]}]})
    assert page.locator("#candidates-card").is_hidden()


def test_a_title_from_a_catalogue_is_never_markup(signed_in_page):
    """Titles and artists come from the internet by way of a media
    provider, so they reach the page as text or not at all."""
    import json as _json

    page, url = signed_in_page
    page.route("**/api/media/candidates", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=_json.dumps({"ok": True, "entries": [
            {"title": "<img src=x onerror='window.__x=1'>", "uri": "file:///a.mp3"},
            {"title": "Second", "artist": "<b>bold</b>", "uri": "file:///b.mp3"}]})))
    _media_page(page, url, backends={"ok": True, "can_play": True,
                                     "backends": [{"name": "mpv",
                                                   "remote": False,
                                                   "uris": ["file"]}]})

    assert page.evaluate("() => window.__x") is None, "a title ran as script"
    assert page.locator("#candidates li button img").count() == 0
    assert page.locator("#candidates li button b").count() == 0
    assert "<b>bold</b>" in page.locator("#candidates li button").nth(1).inner_text()


def test_the_liked_songs_are_listed_and_playable(signed_in_page):
    import json as _json

    page, url = signed_in_page
    # A search is showing at the same time: playing a liked song must not
    # drag those matches along with it.
    page.route("**/api/media/candidates", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=_json.dumps({"ok": True, "entries": [
            {"title": "From a search", "uri": "file:///s1.mp3"},
            {"title": "Also from it", "uri": "file:///s2.mp3"}]})))
    _media_page(page, url,
                backends={"ok": True, "can_play": True,
                          "backends": [{"name": "mpv", "remote": False,
                                        "uris": ["file"]}]},
                likes={"ok": True, "entries": [
                    {"title": "A liked song", "artist": "Someone",
                     "uri": "file:///liked.mp3"}]})

    page.click("#likes-wrap summary")
    page.wait_for_timeout(200)
    assert page.locator("#likes li button").count() == 1
    assert page.locator("#likes-empty").is_hidden(), (
        "said nothing is liked while listing something"
    )

    sent = []
    page.route("**/api/media/play_entry", lambda route: (
        sent.append(route.request.post_data_json),
        route.fulfill(status=200, content_type="application/json",
                      body='{"ok": true}')))
    page.locator("#likes li button").first.click()
    page.wait_for_timeout(400)
    assert sent and sent[0]["entry"]["uri"] == "file:///liked.mp3", sent
    # A liked song was not matched for the request on screen, so the page
    # holds no candidate set for it and says so by leaving `among` out. The
    # service then reads the device's own set. It must NOT send an empty list:
    # that states the set is empty, and the device would replace what it
    # matched with the one liked song -- emptying the card this page adds.
    assert "among" not in sent[0], sent[0]


def test_a_player_that_cannot_be_asked_about_likes_hides_the_list(signed_in_page):
    """Nothing liked and cannot be asked are different, and the page shows
    the difference rather than an empty list in both cases."""
    page, url = signed_in_page
    _media_page(page, url,
                backends={"ok": True, "can_play": True,
                          "backends": [{"name": "mpv", "remote": False,
                                        "uris": ["file"]}]},
                likes={"ok": False, "entries": []})
    assert page.locator("#likes-wrap").is_hidden()


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
    assert page.locator("nav .nav-advanced .nav-sub button.nav-fold").count() == 5
    assert not _fold(page, "understanding").is_visible(), "Advanced folds its groups away"
    folded = _visible_nav(page)
    assert "/about" in folded and "/skills" in folded
    assert "/intents" not in folded and "/plugins" not in folded
    assert "/media" not in folded, "the Library folds too"
    _fold(page, "library").click()
    assert "/media" in _visible_nav(page)
    _fold(page, "library").click()

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
        k: {"met": k in ("system", "media"), "suggest": "pkg-" + k}
        for k in ("system", "sensors", "media", "mark1")}}

    def answer(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(needs))

    page.route("**/api/nav/needs", answer)
    try:
        page.goto(f"{url}/")
        page.evaluate("() => { sessionStorage.removeItem('ovos-nav-needs.v2'); "
                      "localStorage.setItem('ovos-nav-open', JSON.stringify(['advanced', 'library', 'voice', 'understanding', 'device', 'screen', 'maintenance'])); }")
        page.reload()
        page.wait_for_function("() => document.querySelector('nav a[href=\"/mark1\"]').hidden")
        shown = _visible_nav(page)
        assert "/system" in shown and "/media" in shown
        assert not {"/sensors", "/mark1"} & set(shown)
        assert not page.locator('nav .nav-group[data-group="screen"]').is_visible()

        page.goto(f"{url}/mark1")
        note = page.locator("#needs-note")
        note.wait_for()
        assert "pkg-mark1" in note.inner_text()
        assert note.locator('a[href="/plugins"]').count() == 1
        assert "/mark1" in _visible_nav(page), "the page you are on stays in the menu"
    finally:
        page.unroute("**/api/nav/needs")
        page.evaluate("() => { sessionStorage.removeItem('ovos-nav-needs.v2'); "
                      "localStorage.removeItem('ovos-nav-open'); }")


def test_a_panel_apart_from_the_device_hides_no_page(signed_in_page):
    page, url = signed_in_page
    needs = {"colocated": False, "needs": {"mark1": {"met": False, "suggest": "x"}}}
    page.route("**/api/nav/needs", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(needs)))
    try:
        page.goto(f"{url}/")
        page.evaluate("() => { sessionStorage.removeItem('ovos-nav-needs.v2'); "
                      "localStorage.setItem('ovos-nav-open', JSON.stringify(['advanced', 'library', 'voice', 'understanding', 'device', 'screen', 'maintenance'])); }")
        page.reload()
        page.wait_for_load_state("networkidle")
        assert "/mark1" in _visible_nav(page)
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


def test_the_internet_status_moved_to_network(signed_in_page):
    page, url = signed_in_page
    page.goto(f"{url}/network")
    page.wait_for_load_state("networkidle")
    assert page.locator("#internet-card").is_visible()
    page.goto(f"{url}/system")
    page.wait_for_load_state("networkidle")
    assert page.locator("#language").count() == 0
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
