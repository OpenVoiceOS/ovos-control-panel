"""Links the panel offers must point where the thing actually listens.

A wrong port here is invisible in testing -- the page renders, the link is
clickable, and it fails only on somebody's device. The bus monitor is a separate
service with its own default, so the number is pinned in one place and checked
against both the place it is served from and the place the page builds it.
"""
import re
from pathlib import Path

import pytest

from ovos_webui import meta
from ovos_webui.service import STATIC_DIR

#: ovos-busmon serves on this port by default (`BUSMON_PORT` in its service).
BUSMON_PORT = 8005


def test_the_bus_monitor_link_uses_the_port_busmon_serves_on():
    links = {link["label"]: link["url"] for link in meta.about("device.local:8500")["links"]}
    url = links.get("Bus monitor on this device")
    assert url, f"the About page no longer offers a bus monitor link: {list(links)}"
    assert url == f"http://device.local:{BUSMON_PORT}/", (
        f"the About page points at {url}, but ovos-busmon serves on "
        f"{BUSMON_PORT} by default"
    )


def test_the_dashboard_builds_the_same_bus_monitor_link():
    page = (Path(STATIC_DIR) / "index.html").read_text(encoding="utf-8")
    ports = re.findall(r'el\("busmon"\)\.href\s*=\s*[^;]*?:(\d+)/', page)
    assert ports, "the dashboard no longer builds a bus monitor link"
    assert all(int(p) == BUSMON_PORT for p in ports), (
        f"the dashboard points at {ports}, but the About page and ovos-busmon "
        f"use {BUSMON_PORT}"
    )


def test_the_docs_quote_the_same_port():
    doc = (Path(__file__).resolve().parent.parent / "docs" / "dashboard.md")
    text = doc.read_text(encoding="utf-8")
    assert f"port {BUSMON_PORT}" in text, (
        f"docs/dashboard.md does not name port {BUSMON_PORT} for the bus monitor"
    )


@pytest.mark.parametrize("request_host,expected", [
    ("device.local:8500", "device.local"),
    ("device.local", "device.local"),
    ("192.168.1.10:8500", "192.168.1.10"),
    # An IPv6 literal carries colons of its own and arrives bracketed, so
    # splitting on the first colon leaves "[".
    ("[::1]:8500", "[::1]"),
    ("[2001:db8::1]:8500", "[2001:db8::1]"),
    ("[2001:db8::1]", "[2001:db8::1]"),
    # Nothing usable to build a link from.
    ("", "localhost"),
    ("   ", "localhost"),
])
def test_the_link_host_survives_every_shape_of_host_header(request_host, expected):
    assert meta.link_host(request_host) == expected


@pytest.mark.parametrize("request_host", [
    "device.local:8500", "[::1]:8500", "[2001:db8::1]", "", "localhost",
])
def test_the_bus_monitor_link_is_a_usable_url(request_host):
    """Whatever the Host header, the link must parse back to what it names."""
    from urllib.parse import urlsplit

    links = {link["label"]: link["url"] for link in meta.about(request_host)["links"]}
    parsed = urlsplit(links["Bus monitor on this device"])
    assert parsed.scheme == "http"
    assert parsed.port == BUSMON_PORT, f"{links['Bus monitor on this device']}"
    assert parsed.hostname, "the link names no host at all"
