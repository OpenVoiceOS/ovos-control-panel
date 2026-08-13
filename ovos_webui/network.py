"""Scan for and join Wi-Fi networks over the message bus.

These use the message types the network-manager PHAL plugin already registers
(``ovos-PHAL-plugin-network-manager``) — no new ones are introduced:

* ``ovos.phal.nm.scan`` → ``ovos.phal.nm.scan.complete`` (``networks``)
* ``ovos.phal.nm.get.connected`` → ``ovos.phal.nm.is.connected`` (``connection_name``)
  OR ``ovos.phal.nm.is.not.connected``
* ``ovos.phal.nm.connect`` (``connection_name``, ``password``, ``security_type``)
  and ``ovos.phal.nm.connect.open.network`` (``connection_name``)
  → ``ovos.phal.nm.connection.successful`` (``connection_name``) OR ``.failure``
* ``ovos.phal.nm.disconnect`` → ``.disconnection.successful`` / ``.disconnection.failure``
* ``ovos.phal.nm.forget`` → ``.forget.successful`` / ``.forget.failure``

The replies land on *different* topics, not a ``.response`` suffix, and a
connect can come back on either the success or the failure topic. So rather
than ``wait_for_response`` (which listens on a single reply type), each call
registers a temporary handler on every possible reply topic, emits, and waits
on an event — the same shape ``installer._run_bus`` uses. The whole thing is
run through the bounded ``buswait`` gate so a plugin that never answers can
never hang a request or leak a thread; a timeout simply returns an error dict.

The network-manager plugin runs with root (the admin PHAL process), so every
route that reaches these functions sits on the privileged router.
"""
from __future__ import annotations

import threading
from typing import Any

#: Scanning drives an nmcli rescan on the device, which is slow.
SCAN_TIMEOUT = 20.0

#: Joining a network (auth + DHCP) can take a while.
CONNECT_TIMEOUT = 20.0

#: Reads and the forget/disconnect actions come back quickly.
QUERY_TIMEOUT = 10.0

#: An SSID is at most 32 octets; be generous but bounded.
MAX_SSID = 64

#: A WPA passphrase is at most 63 characters; a raw PSK is 64 hex. Cap a little
#: above that so nothing sane is refused but a huge body cannot ride onto the bus.
MAX_PASSWORD = 128

#: Values that mean "no security" — an open network takes the open-network path.
_OPEN = {"", "open", "none", "--"}


def _is_open(security: Any) -> bool:
    return not isinstance(security, str) or security.strip().lower() in _OPEN


def _valid_ssid(ssid: Any) -> bool:
    if not isinstance(ssid, str) or not (0 < len(ssid) <= MAX_SSID):
        return False
    return not any(ord(c) < 32 or ord(c) == 127 for c in ssid)


#: Serializes connect/disconnect/forget so only one mutation is ever waiting on
#: the shared reply topics at a time. Cross-request correlation is handled by
#: ``match`` (a reply naming a different network is ignored); the lock keeps two
#: of *our own* mutations from overlapping. Reads (scan, connected) stay concurrent.
_ACTION_LOCK = threading.Lock()


def _request(bus, msg_type: str, data: dict[str, Any],
             reply_topics: list[str], timeout: float,
             match: tuple[str, str] | None = None):
    """Emit ``msg_type`` and wait for the first of ``reply_topics``.

    Returns ``(topic, message)`` for the reply that arrived, or ``None`` when
    the bus is down, has no capacity, or nothing answered inside ``timeout``.
    Never raises on a bus problem — the caller turns ``None`` into an error dict.

    ``match``, when given, is ``(key, value)``: a reply is ignored when it
    carries ``key`` in its data and that value is not ``value`` — so a reply
    naming a different network never satisfies this request. A reply that omits
    ``key`` (e.g. the failure topics, which the plugin sends with no payload) is
    accepted, since there is nothing to correlate on.
    """
    from ovos_webui import buswait
    from ovos_bus_client.message import Message

    if not buswait.is_connected(bus):
        return None

    def run():
        got = threading.Event()
        box: dict[str, Any] = {}

        def make(topic: str):
            def handler(message):
                # Ignore a reply that names a *different* target (on any topic).
                # A reply with no correlation key is accepted — the failure
                # topics carry no payload, so there is nothing to match on.
                if match is not None:
                    data = message.data or {}
                    if match[0] in data and data.get(match[0]) != match[1]:
                        return
                # The first (matching) reply wins; a plugin only sends one.
                box.setdefault("reply", (topic, message))
                got.set()
            return handler

        handlers: dict[str, Any] = {}
        try:
            for topic in reply_topics:
                handler = make(topic)
                bus.on(topic, handler)
                handlers[topic] = handler
            bus.emit(Message(msg_type, dict(data), {"source": "ovos-webui"}))
            got.wait(timeout)
        finally:
            for topic, handler in handlers.items():
                try:
                    bus.remove(topic, handler)
                except Exception:  # noqa: BLE001 # pragma: no cover
                    pass
        return box.get("reply")

    # Run inside the shared gate: it bounds the number of in-flight threads and
    # gives the whole exchange a hard deadline a little past the wait itself.
    return buswait.call(run, timeout=timeout + 1.0, default=None)


def scan(bus) -> list[dict[str, str]]:
    """Return the networks the device can see, as ``{ssid, security}`` dicts.

    Blank SSIDs are dropped and duplicates (a network seen on two bands) are
    collapsed to one, keeping the first seen. An empty list means either
    nothing was found or nothing answered — the page reports both the same way.
    """
    reply = _request(bus, "ovos.phal.nm.scan", {},
                     ["ovos.phal.nm.scan.complete"], SCAN_TIMEOUT)
    if reply is None:
        return []
    _topic, message = reply
    networks = (message.data or {}).get("networks") or []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for net in networks:
        if not isinstance(net, dict):
            continue
        ssid = net.get("ssid")
        if not isinstance(ssid, str) or not ssid.strip() or ssid in seen:
            continue
        seen.add(ssid)
        security = net.get("security")
        out.append({"ssid": ssid,
                    "security": security if isinstance(security, str) else ""})
    return out


def connected(bus) -> dict[str, Any]:
    """Report the currently-joined network as ``{connected, ssid}``.

    A device that is not on Wi-Fi (or that did not answer) reports
    ``{"connected": False, "ssid": None}``.
    """
    reply = _request(bus, "ovos.phal.nm.get.connected", {},
                     ["ovos.phal.nm.is.connected",
                      "ovos.phal.nm.is.not.connected"], QUERY_TIMEOUT)
    if reply is None:
        return {"connected": False, "ssid": None}
    topic, message = reply
    if topic == "ovos.phal.nm.is.connected":
        ssid = (message.data or {}).get("connection_name")
        return {"connected": True, "ssid": ssid if isinstance(ssid, str) else None}
    return {"connected": False, "ssid": None}


def _act(bus, ssid: str, msg_type: str, data: dict[str, Any],
         ok_topic: str, fail_topic: str, timeout: float) -> dict[str, Any]:
    """Emit an action and resolve its two-topic (success/failure) reply."""
    if not _valid_ssid(ssid):
        return {"ok": False, "error": "a network name is required"}
    if not _ACTION_LOCK.acquire(timeout=timeout):
        return {"ok": False,
                "error": "another network change is still in progress — "
                         "try again in a moment"}
    try:
        reply = _request(bus, msg_type, data, [ok_topic, fail_topic], timeout,
                         match=("connection_name", ssid))
    finally:
        _ACTION_LOCK.release()
    if reply is None:
        return {"ok": False,
                "error": "the network manager did not answer — is the "
                         "network-manager plugin installed and running?"}
    topic, _message = reply
    if topic == ok_topic:
        return {"ok": True, "error": None}
    return {"ok": False, "error": "the network manager could not do that"}


def connect(bus, ssid: str, password: str = "", security: str = "") -> dict[str, Any]:
    """Join ``ssid``. An open/blank ``security`` takes the open-network path.

    Returns ``{ok, error}``; a bus timeout comes back as ``ok=False`` with an
    error, never as an exception.
    """
    if not _valid_ssid(ssid):
        return {"ok": False, "error": "a network name is required"}
    if _is_open(security):
        return _act(bus, ssid, "ovos.phal.nm.connect.open.network",
                    {"connection_name": ssid},
                    "ovos.phal.nm.connection.successful",
                    "ovos.phal.nm.connection.failure", CONNECT_TIMEOUT)
    if not isinstance(password, str):
        password = ""
    if len(password) > MAX_PASSWORD:
        return {"ok": False, "error": "the password is too long"}
    return _act(bus, ssid, "ovos.phal.nm.connect",
                {"connection_name": ssid, "password": password,
                 "security_type": security},
                "ovos.phal.nm.connection.successful",
                "ovos.phal.nm.connection.failure", CONNECT_TIMEOUT)


def disconnect(bus, ssid: str) -> dict[str, Any]:
    """Drop the active connection to ``ssid``."""
    return _act(bus, ssid, "ovos.phal.nm.disconnect",
                {"connection_name": ssid},
                "ovos.phal.nm.disconnection.successful",
                "ovos.phal.nm.disconnection.failure", QUERY_TIMEOUT)


def forget(bus, ssid: str) -> dict[str, Any]:
    """Forget the saved credentials for ``ssid``."""
    return _act(bus, ssid, "ovos.phal.nm.forget",
                {"connection_name": ssid},
                "ovos.phal.nm.forget.successful",
                "ovos.phal.nm.forget.failure", QUERY_TIMEOUT)
