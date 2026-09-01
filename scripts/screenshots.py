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
import os
import secrets
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


def shoot(url: str, token: str, out: Path, only: str | None) -> int:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    routes = _pages()
    if only:
        routes = {r: f for r, f in routes.items() if only in r}
    taken = 0
    with sync_playwright() as play:
        browser = play.chromium.launch()
        try:
            for label, (width, height) in VIEWPORTS.items():
                context = browser.new_context(viewport={"width": width, "height": height},
                                              device_scale_factor=2)
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
                    target = out / f"{_name(route)}-{label}.png"
                    page.screenshot(path=str(target), full_page=(label == "wide"))
                    taken += 1
                    print(f"  {_shown(target)}")
                context.close()

            context = browser.new_context(viewport={"width": 1280, "height": 900},
                                          device_scale_factor=2, locale="ar")
            page = context.new_page()
            page.goto(f"{url}/login")
            page.fill("input[type=password]", token)
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle")
            if page.url.rstrip("/").endswith("/login"):
                raise SystemExit(
                    "signing in failed; every shot would be the login page")
            for route in RTL_PAGES:
                if route not in routes:
                    continue
                page.goto(f"{url}{route}")
                page.evaluate("window.localStorage.setItem('ovos_webui_lang','ar')")
                page.reload()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(400)
                target = out / f"{_name(route)}-rtl-arabic.png"
                page.screenshot(path=str(target), full_page=True)
                taken += 1
                print(f"  {_shown(target)}")
            context.close()
        finally:
            browser.close()
    return taken


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="a panel that is already running")
    parser.add_argument("--token", help="its access token")
    parser.add_argument("--out", default=str(OUT), help="where to write the images")
    parser.add_argument("--only", help="shoot only routes containing this")
    args = parser.parse_args()

    if args.url:
        if not args.token:
            parser.error("--url needs --token")
        taken = shoot(args.url.rstrip("/"), args.token, Path(args.out), args.only)
        print(f"{taken} images written to {args.out}")
        return 0

    # Start our own instance, so a run cannot photograph whatever happens to
    # be listening on a port left over from a previous session.
    port = _free_port()
    token = secrets.token_urlsafe(16)
    env = dict(os.environ, OVOS_WEBUI_TOKEN=token, OVOS_WEBUI_PORT=str(port),
               OVOS_WEBUI_HOST="127.0.0.1")
    proc = subprocess.Popen([sys.executable, "-c",
                             "from ovos_webui.service import main; main()"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_for(url)
        taken = shoot(url, token, Path(args.out), args.only)
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)
    print(f"{taken} images written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
