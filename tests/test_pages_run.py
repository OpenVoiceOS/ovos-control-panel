"""Every page must run its own JavaScript without throwing.

The rest of the suite tests the Python side and reads the HTML as text, so a
page whose script dies on load still passes everything: the markup is there,
the strings are there, the routes answer. A real browser is the only thing
that notices.

This caught a `var canvas` declared below the geometry that used it -- `var`
hoists the declaration but not the assignment, so the whole script died on
load and the faceplate drew nothing at all, with 961 other tests green.

Skipped when Playwright's browser is not present. Playwright itself is a dev
dependency, but the browser binary is a separate ~115MB download that the
shared build workflow has no hook to trigger -- it exposes `pre_install_pip`
for packages and nothing that runs a command before the tests. So this gate
runs for anyone working on the panel (`playwright install chromium`) and skips
in CI.

That matters more here than the count suggests. Nearly everything the Mark-1
page does -- the canvas geometry, the eye diff, the poll chain, the animation
editor and its exports -- is asserted only in this file. CI proves the routes
answer and the strings are there; it proves nothing about whether the face
draws. Said plainly rather than left as a guard that looks like it protects the
pipeline and does not; raised with the shared workflows so it can run
everywhere.
"""
import json
import re
import time
import warnings
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api",
                    reason="playwright is not installed")


def _pages():
    from ovos_webui.service import PAGES

    return sorted(PAGES)


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
            pytest.skip(message)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
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
      for (let i = 0; i < d.length; i += 4) {
        if (d[i] > 20 || d[i + 1] > 20 || d[i + 2] > 20) { n++; }
      }
      return n;
    })()""")
    assert lit > 500, f"the faceplate drew nothing ({lit} lit pixels)"


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
    from ovos_webui.service import PAGES

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
def _media_page(page, url, *, backends, status=None, progress=None):
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
    import json as _json

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
