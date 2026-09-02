#!/usr/bin/env python3
"""Re-shoot every documented screenshot against a running control panel.

The images in ``docs/img`` are the only part of the documentation that cannot
be checked by reading it, so they rot silently: a shot taken before a rename
or a new nav entry still looks plausible. This takes them all again from one
instance in one run, so they are at least consistent with each other and with
the version that produced them.

Usage::

    python scripts/screenshots.py            # start an instance and shoot
    python scripts/screenshots.py --url URL --token TOKEN   # shoot a running one

Every page is shot at a desktop and a phone width, and the pages whose layout
depends on writing direction are shot again in Arabic. Nothing here decides
*which* pages exist: the list comes from ``service.PAGES``, so a new page is
photographed the first time this runs after it is added.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "img"

#: Desktop first, because that is what the docs lead with.
VIEWPORTS = {"wide": (1280, 900), "mobile": (420, 900)}

#: Right-to-left is a layout, not a translation, so these are shot again in a
#: right-to-left locale. Keep it short: every extra shot is another image to
#: keep current.
RTL_PAGES = ("/", "/config")

#: Where the stand-in device keeps its configuration. Fixed and neutral,
#: because the panel shows this path to the reader on more than one page: a
#: temporary name would put the operator's home directory and a random suffix
#: into a committed image, and change them on every run.
CONFIG_HOME = Path("/tmp/ovos-panel-demo/config")

#: Its data and its cache, which no page ever shows and which a package index
#: listing can make large. /tmp is memory here, so they do not go in it.
WORK = Path(os.environ.get("TMPDIR", "/var/tmp")) / "ovos-panel-demo-work"

#: The language those shots are taken in. Right-to-left is the point; the
#: language is how a device gets there.
RTL_LANG = "ar-sa"

#: What the stand-in device is configured as. A picture of a panel is a picture
#: of a configuration, so this is a plain one rather than whatever the machine
#: taking the shot happens to run.
DEMO_CONFIG = {"lang": "en-us", "system_unit": "metric",
               "time_format": "full", "date_format": "DMY"}

#: A few pages are documented section by section, where a whole-page shot would
#: be mostly the parts the text is not talking about. Each of these is one
#: element of one page: name, the page it lives on, and how to find it.
#: One page documents what a device with something wrong looks like, so it
#: gets a device with something wrong. The value is the service left silent.
STATES = {"dashboard-degraded": ("/", "skills")}

SECTIONS = {
    "about-power": ("/controls", "#power-card"),
    "backup-history": ("/backup", "#history"),
    "plugins-updates": ("/plugins", "#updates"),
}


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _pages() -> dict[str, str]:
    sys.path.insert(0, str(ROOT))
    from ovos_webui.service import PAGES

    return dict(PAGES)


def _shown(path: Path) -> str:
    """A path to print: relative to the repo when it is inside it."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _name(route: str) -> str:
    return "dashboard" if route == "/" else route.strip("/").replace("/", "-")


def _wait_for(url: str, timeout: float = 30.0) -> None:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url + "/login", timeout=2)
            return
        except urllib.error.HTTPError:
            return  # answering at all is enough
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(0.3)
    raise SystemExit(f"the panel never came up at {url}")


def _still(page) -> None:
    """Stop everything that moves, so two runs of this produce one image.

    The header carries an animated waveform. Without this each shot catches it
    at whatever phase it happened to be in, and a re-run rewrites most of the
    set for no change anyone can see.
    """
    page.add_style_tag(content=(
        "*, *::before, *::after { animation: none !important; "
        "transition: none !important; }"))
    page.wait_for_timeout(150)


def shoot(url: str, token: str, out: Path, only: str | None,
          suffix: str = "", routes_only: tuple[str, ...] | None = None,
          sections: bool = True) -> int:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    routes = _pages()
    if only:
        routes = {r: f for r, f in routes.items() if only in r}
    if routes_only is not None:
        routes = {r: f for r, f in routes.items() if r in routes_only}
    taken = 0
    with sync_playwright() as play:
        browser = play.chromium.launch()
        try:
            widths = ({"wide": VIEWPORTS["wide"]} if suffix
                      else VIEWPORTS)
            for label, (width, height) in widths.items():
                context = browser.new_context(viewport={"width": width, "height": height},
                                              device_scale_factor=2)
                # The sign in page first, from a context that has not signed
                # in yet: it is documented like any other page, and it is the
                # one page a signed-in run can never photograph.
                if not suffix and sections and (only is None or "login" in only):
                    page = context.new_page()
                    page.goto(f"{url}/login")
                    page.wait_for_load_state("networkidle")
                    _still(page)
                    target = out / f"login-{label}.png"
                    page.screenshot(path=str(target), full_page=(label == "wide"))
                    taken += 1
                    print(f"  {_shown(target)}")
                    page.close()
                # Sign in once per context: the panel exchanges the token for a
                # cookie, and every privileged page needs it. Without this the
                # whole run photographs the login screen twenty-four times.
                page = context.new_page()
                page.goto(f"{url}/login")
                page.fill("input[type=password]", token)
                page.click("button[type=submit]")
                page.wait_for_load_state("networkidle")
                # Without this a login regression produces a full set of
                # plausible-looking login screens and exits successfully.
                if page.url.rstrip("/").endswith("/login"):
                    raise SystemExit(
                        "signing in failed; every shot would be the login page")
                for route in routes:
                    page.goto(f"{url}{route}")
                    # Pages fetch their content after load; without settling
                    # first the shot catches empty cards and spinners.
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(400)
                    if label == "wide":
                        # On a wide screen the rail is a sticky sidebar one
                        # viewport tall that scrolls its own contents, so a
                        # full-page shot shows only the entries above the fold
                        # -- and the rail is what half these images are meant
                        # to show. Let it lie flat for the photograph.
                        page.add_style_tag(content=(
                            "nav { position: static; height: auto; "
                            "overflow: visible; }"))
                    _still(page)
                    target = out / f"{_name(route)}-{suffix or label}.png"
                    page.screenshot(path=str(target), full_page=(label == "wide"))
                    taken += 1
                    print(f"  {_shown(target)}")

                # Sections are shot once, at the desktop width, because the
                # text that refers to them is about the controls in them and
                # not about how they reflow.
                if label == "wide" and not suffix and sections:
                    for name, (route, selector) in SECTIONS.items():
                        if only is not None and only not in route:
                            continue
                        page.goto(f"{url}{route}")
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(400)
                        _still(page)
                        found = page.locator(selector)
                        if not found.count():
                            raise SystemExit(
                                f"{selector} is not on {route} any more, so "
                                f"{name}.png would be a shot of nothing")
                        target = out / f"{name}.png"
                        found.first.screenshot(path=str(target))
                        taken += 1
                        print(f"  {_shown(target)}")
                context.close()

        finally:
            browser.close()
    return taken


def _seed(config_home: Path) -> None:
    """Give the stand-in device the history the documentation describes.

    Two pages document a list -- saved versions, and skills with settings --
    and a device that has never been used has neither, so the picture under
    the prose is an empty card. These are the real files, at the
    real paths, that a device acquires by being used.
    """
    mycroft = config_home / "mycroft"

    # One earlier save, so the history list has a row to show. The panel makes
    # these itself on every save; this is the same file under the same name.
    backups = mycroft / ".ovos-webui-backups"
    backups.mkdir(parents=True, exist_ok=True)
    (backups / "mycroft.conf.20260101T090000Z.bak").write_text(
        json.dumps({"lang": "en-us", "system_unit": "imperial"}, indent=1),
        encoding="utf-8")

    # A skill that has been configured, so the skill settings page lists one.
    settings = mycroft / "skills" / "ovos-skill-date-time.openvoiceos"
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "settings.json").write_text(
        json.dumps({"__mycroft_skill_firstrun": False, "use_24_hour": True,
                    "speak_timezone": False}, indent=1), encoding="utf-8")

def _run(out: Path, only: str | None, config: dict, suffix: str = "",
         routes_only: tuple[str, ...] | None = None,
         silent_service: str = "", sections: bool = True) -> int:
    """Stand up a panel with a device behind it, shoot it, and tear it down.

    A sandbox of its own, and a device of its own. Shooting against the machine
    that runs this photographs its configuration, its skills and its home
    directory: one run produced a 48000-pixel strip of a developer's 267 test
    skills, and another published the path to their config file. A run against
    no bus at all photographs a dead device under captions that say every
    service is ready.
    """
    # A fixed path, not a temporary one. Several pages show the reader where
    # their configuration lives, so whatever this is called ends up in the
    # pictures: a `mkdtemp` name puts the operator's home directory and a
    # random suffix into a committed image, and changes it on every run.
    for path in (CONFIG_HOME, WORK):
        shutil.rmtree(path, ignore_errors=True)
    (CONFIG_HOME / "mycroft").mkdir(parents=True)
    (CONFIG_HOME / "mycroft" / "mycroft.conf").write_text(
        json.dumps(config), encoding="utf-8")
    _seed(CONFIG_HOME)

    port = _free_port()
    token = secrets.token_urlsafe(16)
    env = dict(os.environ, OVOS_WEBUI_TOKEN=token, OVOS_WEBUI_PORT=str(port),
               OVOS_WEBUI_HOST="127.0.0.1",
               XDG_CONFIG_HOME=str(CONFIG_HOME),
               XDG_DATA_HOME=str(WORK / "data"),
               XDG_CACHE_HOME=str(WORK / "cache"),
               DEMO_SILENT_SERVICE=silent_service)

    quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bus = subprocess.Popen([sys.executable, "-m", "ovos_messagebus"],
                           env=env, **quiet)
    time.sleep(3)
    device = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "demo_device.py")], env=env,
        **quiet)
    time.sleep(2)
    panel = subprocess.Popen(
        [sys.executable, "-c", "from ovos_webui.service import main; main()"],
        env=env, **quiet)
    try:
        _wait_for(f"http://127.0.0.1:{port}")
        return shoot(f"http://127.0.0.1:{port}", token, out, only,
                     suffix=suffix, routes_only=routes_only, sections=sections)
    finally:
        for running in (panel, device, bus):
            running.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                running.wait(timeout=10)
        shutil.rmtree(WORK, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="a panel that is already running")
    parser.add_argument("--token", help="its access token")
    parser.add_argument("--out", default=str(OUT), help="where to write the images")
    parser.add_argument("--only", help="shoot only routes containing this")
    parser.add_argument("--routes", help="shoot exactly these routes, comma "
                                         "separated, and nothing else")
    parser.add_argument("--pass", dest="which", default="all",
                        choices=("all", "main", "rtl", "states", "extras"),
                        help="one part of the run, for taking it in pieces")
    args = parser.parse_args()

    if args.url:
        if not args.token:
            parser.error("--url needs --token")
        taken = shoot(args.url.rstrip("/"), args.token, Path(args.out), args.only)
        print(f"{taken} images written to {args.out}")
        return 0

    out = Path(args.out)
    chosen = tuple(r.strip() for r in args.routes.split(",")) if args.routes else None
    taken = 0
    if args.which in ("all", "main"):
        taken += _run(out, args.only, DEMO_CONFIG, routes_only=chosen,
                      sections=args.routes is None and args.only is None)
    if args.which == "extras":
        # The sign in page and the section shots, without the page-by-page
        # pass: those two groups are what a --routes run leaves out.
        taken += _run(out, None, DEMO_CONFIG, routes_only=())
    # The panel takes its language from the device, so a right-to-left shot
    # needs a device configured that way -- there is no browser setting for
    # it. That is a second device, so it is a second run.
    if args.which in ("all", "rtl"):
        taken += _run(out, None, dict(DEMO_CONFIG, lang=RTL_LANG),
                      suffix="rtl-arabic", routes_only=RTL_PAGES)
    if args.which in ("all", "states"):
        for name, (route, silent) in STATES.items():
            taken += _run(out, None, DEMO_CONFIG,
                          suffix=name.split("-", 1)[1], routes_only=(route,),
                          silent_service=silent)
    print(f"{taken} images written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
