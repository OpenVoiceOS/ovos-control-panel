"""Wi-Fi over the network-manager PHAL plugin: scan, status, connect (success
and failure on two different reply topics), forget/disconnect, timeouts, and
the privileged routes."""


# ── a FakeBus that answers the network-manager topics ────────────────────────
def _nm_bus(*, networks=None, connected_ssid=None, connect_ok=None,
           forget_ok=True, disconnect_ok=True):
    """Build a FakeBus wired to the nm handlers we want to exercise.

    ``connect_ok`` None means "do not answer connect at all" (a timeout).
    """
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus

    bus = FakeBus()

    if networks is not None:
        bus.on("ovos.phal.nm.scan", lambda m: bus.emit(Message(
            "ovos.phal.nm.scan.complete", {"networks": networks}, m.context)))

    def on_get_connected(m):
        if connected_ssid:
            bus.emit(Message("ovos.phal.nm.is.connected",
                             {"connection_name": connected_ssid}, m.context))
        else:
            bus.emit(Message("ovos.phal.nm.is.not.connected", {}, m.context))
    bus.on("ovos.phal.nm.get.connected", on_get_connected)

    def _reply(m, ok, ok_topic, fail_topic, name):
        topic = ok_topic if ok else fail_topic
        data = {"connection_name": name} if ok else {}
        bus.emit(Message(topic, data, m.context))

    if connect_ok is not None:
        bus.on("ovos.phal.nm.connect", lambda m: _reply(
            m, connect_ok, "ovos.phal.nm.connection.successful",
            "ovos.phal.nm.connection.failure", m.data.get("connection_name")))
        bus.on("ovos.phal.nm.connect.open.network", lambda m: _reply(
            m, connect_ok, "ovos.phal.nm.connection.successful",
            "ovos.phal.nm.connection.failure", m.data.get("connection_name")))

    bus.on("ovos.phal.nm.forget", lambda m: _reply(
        m, forget_ok, "ovos.phal.nm.forget.successful",
        "ovos.phal.nm.forget.failure", m.data.get("connection_name")))
    bus.on("ovos.phal.nm.disconnect", lambda m: _reply(
        m, disconnect_ok, "ovos.phal.nm.disconnection.successful",
        "ovos.phal.nm.disconnection.failure", m.data.get("connection_name")))
    return bus


# ── scan ─────────────────────────────────────────────────────────────────────
def test_scan_parses_dedupes_and_drops_blanks():
    from ovos_webui import network

    bus = _nm_bus(networks=[
        {"ssid": "home", "security": "WPA2"},
        {"ssid": "home", "security": "WPA2"},   # duplicate band -> collapsed
        {"ssid": "", "security": "open"},         # blank -> dropped
        {"ssid": "cafe", "security": ""},
        {"nope": 1},                               # malformed -> ignored
    ])
    nets = network.scan(bus)
    assert nets == [{"ssid": "home", "security": "WPA2"},
                    {"ssid": "cafe", "security": ""}]


def test_scan_without_a_responder_returns_empty_and_does_not_hang():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import network

    network.SCAN_TIMEOUT = 0.3  # keep the test quick
    assert network.scan(FakeBus()) == []


# ── status ───────────────────────────────────────────────────────────────────
def test_connected_reports_the_ssid():
    from ovos_webui import network
    assert network.connected(_nm_bus(connected_ssid="home")) == {
        "connected": True, "ssid": "home"}


def test_not_connected():
    from ovos_webui import network
    assert network.connected(_nm_bus(connected_ssid=None)) == {
        "connected": False, "ssid": None}


def test_connected_timeout_is_reported_as_not_connected():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import network

    network.QUERY_TIMEOUT = 0.3
    assert network.connected(FakeBus()) == {"connected": False, "ssid": None}


# ── connect: success and failure on two different reply topics ────────────────
def test_connect_secured_success():
    from ovos_webui import network
    r = network.connect(_nm_bus(connect_ok=True), "home", "hunter2", "WPA2")
    assert r == {"ok": True, "error": None}


def test_connect_failure_topic_is_an_error_not_a_success():
    from ovos_webui import network
    r = network.connect(_nm_bus(connect_ok=False), "home", "wrong", "WPA2")
    assert r["ok"] is False and r["error"]


def test_connect_open_network_uses_the_open_path():
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import network

    bus = FakeBus()
    seen = {}

    def on_open(m):
        seen["open"] = m.data
        bus.emit(Message("ovos.phal.nm.connection.successful",
                         {"connection_name": m.data.get("connection_name")}, m.context))
    bus.on("ovos.phal.nm.connect.open.network", on_open)
    # a secured-path handler that must NOT be hit
    bus.on("ovos.phal.nm.connect", lambda m: seen.setdefault("secured", True))

    assert network.connect(bus, "cafe", "", "open")["ok"] is True
    assert seen.get("open") == {"connection_name": "cafe"}
    assert "secured" not in seen


def test_connect_requires_a_valid_ssid():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import network
    assert network.connect(FakeBus(), "", "pw", "WPA2")["ok"] is False


def test_connect_caps_the_password_length():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import network
    r = network.connect(FakeBus(), "home", "x" * 500, "WPA2")
    assert r["ok"] is False and "too long" in r["error"]


def test_connect_timeout_returns_an_error_dict_without_hanging():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import network

    network.CONNECT_TIMEOUT = 0.3
    r = network.connect(FakeBus(), "home", "pw", "WPA2")
    assert r["ok"] is False and r["error"]


# ── forget / disconnect ──────────────────────────────────────────────────────
def test_forget_success_and_failure():
    from ovos_webui import network
    assert network.forget(_nm_bus(forget_ok=True), "home")["ok"] is True
    assert network.forget(_nm_bus(forget_ok=False), "home")["ok"] is False


def test_disconnect_success_and_failure():
    from ovos_webui import network
    assert network.disconnect(_nm_bus(disconnect_ok=True), "home")["ok"] is True
    assert network.disconnect(_nm_bus(disconnect_ok=False), "home")["ok"] is False


# ── routes ───────────────────────────────────────────────────────────────────
def test_network_routes_need_a_token(token_client):
    # every route is privileged: no Authorization header -> 401
    assert token_client.get("/api/network/status").status_code == 401
    assert token_client.post("/api/network/scan").status_code == 401
    assert token_client.post("/api/network/connect",
                             json={"ssid": "x"}).status_code == 401
    assert token_client.post("/api/network/forget",
                             json={"ssid": "x"}).status_code == 401
    assert token_client.post("/api/network/disconnect",
                             json={"ssid": "x"}).status_code == 401


def test_network_routes_503_without_a_device():
    from fastapi.testclient import TestClient
    from ovos_webui.service import create_app

    app = create_app(bus=None, host="0.0.0.0", token="s3cret-token",
                     connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        auth = {"Authorization": "Bearer s3cret-token"}
        assert c.get("/api/network/status", headers=auth).status_code == 503
        assert c.post("/api/network/scan", headers=auth).status_code == 503
        assert c.post("/api/network/connect", json={"ssid": "x"},
                      headers=auth).status_code == 503


def test_network_status_route_reads_the_bus(bus):
    from fastapi.testclient import TestClient
    from ovos_bus_client.message import Message
    from ovos_webui.service import create_app

    bus.on("ovos.phal.nm.get.connected", lambda m: bus.emit(Message(
        "ovos.phal.nm.is.connected", {"connection_name": "home"}, m.context)))
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token",
                     connect_bus=False)
    with TestClient(app, base_url="http://127.0.0.1:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        r = c.get("/api/network/status",
                  headers={"Authorization": "Bearer s3cret-token"})
        assert r.status_code == 200
        assert r.json() == {"connected": True, "ssid": "home"}


def test_network_page_renders(client):
    assert client.get("/network").status_code == 200


# ── concurrency / correlation ───────────────────────────────────────────────
def test_connect_ignores_a_success_reply_for_a_different_ssid():
    """A stray success reply naming a different connection must not resolve
    this call — it should time out instead of reporting a false ok=True."""
    from ovos_bus_client.message import Message
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import network

    network.CONNECT_TIMEOUT = 0.3
    bus = FakeBus()
    # Simulate cross-request bleed: whichever ssid is requested, the plugin
    # (mis)replies with success for "A" instead — as if another in-flight
    # request's reply landed on this handler.
    bus.on("ovos.phal.nm.connect", lambda m: bus.emit(Message(
        "ovos.phal.nm.connection.successful", {"connection_name": "A"},
        m.context)))

    r = network.connect(bus, "B", "pw", "WPA2")
    assert r["ok"] is False


def test_connect_accepts_a_matching_success_reply():
    from ovos_webui import network
    r = network.connect(_nm_bus(connect_ok=True), "A", "pw", "WPA2")
    assert r == {"ok": True, "error": None}


def test_connect_rejects_control_characters_in_ssid():
    from ovos_utils.fakebus import FakeBus
    from ovos_webui import network

    bus = FakeBus()
    seen = {}
    bus.on("ovos.phal.nm.connect", lambda m: seen.setdefault("emitted", True))
    bus.on("ovos.phal.nm.connect.open.network",
          lambda m: seen.setdefault("emitted", True))

    r = network.connect(bus, "evil\nssid", "pw", "WPA2")
    assert r["ok"] is False and "required" in r["error"]
    assert "emitted" not in seen


def test_valid_ssid_rejects_control_characters():
    from ovos_webui.network import _valid_ssid
    assert _valid_ssid("a\x00b") is False
    assert _valid_ssid("a\x7fb") is False
    assert _valid_ssid("home") is True
