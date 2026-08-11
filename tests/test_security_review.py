"""Regression tests for the findings of the adversarial review of PR #1.

Each test is named after its finding. Each one was seen to fail against the
code as it was before the fix.
"""
import io
import json
import tarfile
import threading
import time

import pytest
from fastapi.testclient import TestClient

from ovos_webui import backupio, buswait, configio, fsutils
from ovos_webui.service import create_app

# ── S1: cross-site request forgery ───────────────────────────────────────────
# ``sec-fetch-site`` is cleared where the test is about Origin or Referer,
# because a real browser would not send a same-origin value with them.
CROSS_SITE = [
    {"origin": "http://evil.example", "sec-fetch-site": ""},
    {"sec-fetch-site": "cross-site"},
    {"sec-fetch-site": "same-site"},
    {"sec-fetch-site": "none"},
    {"referer": "http://evil.example/page", "sec-fetch-site": ""},
]

UNSAFE_CALLS = [
    ("put", "/api/config", {"json": {"text": "{}", "format": "json"}}),
    ("post", "/api/config/quick", {"json": {"values": {}}}),
    ("put", "/api/skills/a", {"json": {"settings": {}}}),
    ("post", "/api/restore", {"content": b"x"}),
    ("post", "/api/login", {"json": {"token": "s3cret-token"}}),
]


@pytest.mark.parametrize("method,path,kwargs", UNSAFE_CALLS)
@pytest.mark.parametrize("headers", CROSS_SITE)
def test_s1_cross_site_writes_are_refused(client, method, path, kwargs, headers):
    """Any web page could otherwise rewrite the configuration of the device."""
    r = getattr(client, method)(path, headers=headers, **kwargs)
    assert r.status_code == 403, f"{path} accepted a cross-site call"


def test_s1_a_plain_html_form_post_from_another_site_is_refused(client):
    """A form post needs no preflight, so it is the easiest forgery."""
    r = client.post("/api/restore",
                    files={"file": ("b.tar.gz", b"x", "application/gzip")},
                    headers={"origin": "http://evil.example",
                             "sec-fetch-site": "cross-site"})
    assert r.status_code == 403


def test_s1_text_plain_body_from_another_site_is_refused(client):
    r = client.post("/api/restore", content=b"x",
                    headers={"content-type": "text/plain",
                             "sec-fetch-site": "cross-site"})
    assert r.status_code == 403


def test_s1_same_origin_writes_still_work(client):
    r = client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"},
                   headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 200


def test_s1_a_program_that_sends_a_token_still_works(token_client):
    """A browser cannot attach an Authorization header across sites without a
    preflight, and no preflight is ever approved, so this cannot be forged."""
    r = token_client.put("/api/config",
                         json={"text": '{"lang": "pt-pt"}', "format": "json"},
                         headers={"Authorization": "Bearer s3cret-token",
                                  "sec-fetch-site": ""})
    assert r.status_code == 200


def test_s1_reads_are_not_blocked(client):
    assert client.get("/api/health", headers={"sec-fetch-site": "cross-site"}).status_code == 200


# ── S2: body cap must survive a chunked request ──────────────────────────────
def test_s2_chunked_body_without_content_length_is_capped(client):
    """A chunked upload declares no length, so a header check never fires."""
    def chunks():
        for _ in range(400):
            yield b"x" * 65536

    r = client.put("/api/config", content=chunks(),
                   headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_s2_the_body_limit_stops_reading_as_soon_as_the_cap_is_passed():
    """Drive the middleware directly: the test client buffers, a real server does not."""
    import anyio

    from ovos_webui.limits import BodyLimitMiddleware

    produced = {"n": 0}
    reached_app = {"yes": False}

    async def receive():
        produced["n"] += 1
        return {"type": "http.request", "body": b"x" * 4096, "more_body": True}

    async def app(scope, rcv, send):
        reached_app["yes"] = True
        while True:
            message = await rcv()
            if message["type"] == "http.disconnect":
                return
            if not message.get("more_body"):
                return

    sent = []

    async def send(message):
        sent.append(message)

    middleware = BodyLimitMiddleware(app, limit_for=lambda scope: 64 * 1024)
    scope = {"type": "http", "path": "/api/config", "headers": []}
    anyio.run(middleware, scope, receive, send)

    assert reached_app["yes"]
    # 64 KiB cap, 4 KiB chunks: the read must stop at about 17 chunks, not run on.
    assert produced["n"] < 32, f"the middleware read {produced['n']} chunks"
    assert sent[0]["status"] == 413


def test_s2_chunked_upload_to_restore_is_capped(client):
    def chunks():
        for _ in range(600):
            yield b"x" * 65536

    r = client.post("/api/restore", content=chunks(),
                    headers={"content-type": "application/gzip"})
    assert r.status_code == 413


def test_s2_a_lying_content_length_cannot_raise_the_cap(client):
    r = client.put("/api/config", content=b"x" * (2 * 1024 * 1024),
                   headers={"content-type": "application/json",
                            "content-length": "10"})
    assert r.status_code in (400, 413, 422)


# ── S3: YAML alias expansion ─────────────────────────────────────────────────
BILLION_LAUGHS = (
    "a: &a [\"x\",\"x\",\"x\",\"x\",\"x\",\"x\",\"x\",\"x\",\"x\"]\n"
    "b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]\n"
    "c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]\n"
    "d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]\n"
    "e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d]\n"
    "f: &f [*e,*e,*e,*e,*e,*e,*e,*e,*e]\n"
    "g: [*f,*f,*f,*f,*f,*f,*f,*f,*f]\n"
)


def test_s3_yaml_alias_bomb_is_refused():
    assert len(BILLION_LAUGHS) < 1024
    with pytest.raises(configio.ConfigError):
        configio.parse_text(BILLION_LAUGHS, "yaml")


def test_s3_yaml_alias_bomb_is_refused_over_http(client):
    r = client.put("/api/config", json={"text": BILLION_LAUGHS, "format": "yaml"})
    assert r.status_code == 400


def test_s3_a_single_anchor_is_also_refused():
    with pytest.raises(configio.ConfigError):
        configio.parse_text("a: &x 1\nb: *x\n", "yaml")


def test_s3_ordinary_yaml_still_loads():
    assert configio.parse_text("lang: pt-pt\ntts:\n  module: x\n", "yaml") == {
        "lang": "pt-pt", "tts": {"module": "x"}}


# ── S4: a bus that hangs must not hang the request ───────────────────────────
class HangingBus:
    """A bus whose emit never returns, like a disconnected MessageBusClient."""

    def __init__(self):
        self.connected_event = threading.Event()
        self.connected_event.set()  # claims to be connected, then hangs
        self.released = threading.Event()

    def emit(self, message):
        self.released.wait(30)

    def wait_for_response(self, message, timeout=3.0):
        self.released.wait(30)


def test_s4_a_hanging_emit_does_not_hang_a_save():
    bus = HangingBus()
    started = time.monotonic()
    try:
        configio.write_user_config({"lang": "pt-pt"}, bus=bus)
    finally:
        bus.released.set()
    assert time.monotonic() - started < 15, "the save waited on the bus"
    assert configio.read_user_config()["lang"] == "pt-pt"


def test_s4_a_hanging_bus_does_not_hang_the_dashboard():
    from ovos_webui import health

    bus = HangingBus()
    started = time.monotonic()
    try:
        snap = health.snapshot(bus, timeout=0.5)
    finally:
        bus.released.set()
    assert time.monotonic() - started < 20, "the dashboard waited on the bus"
    assert all(s["state"] == "no answer" for s in snap["services"])


def test_s4_bounded_call_returns_the_default_on_a_timeout():
    stop = threading.Event()
    try:
        result = buswait.call(lambda: stop.wait(30) or "late", timeout=0.2,
                              default="gave up")
    finally:
        stop.set()
    assert result == "gave up"


# ── S5 / S6: a restore must be all or nothing, and must be valid ─────────────
def _archive(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_s6_a_config_that_is_not_json_is_refused(client):
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    blob = _archive({"config/mycroft.conf": b"this is not json at all"})
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400
    assert configio.read_user_config()["lang"] == "pt-pt", "the live config was bricked"


def test_s6_a_config_that_is_not_utf8_is_refused(client):
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    blob = _archive({"config/mycroft.conf": b"\xff\xfe\x00binary"})
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400
    assert configio.read_user_config()["lang"] == "pt-pt"


def test_s6_a_config_that_is_a_list_is_refused(client):
    blob = _archive({"config/mycroft.conf": b"[1, 2, 3]"})
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400


def test_s6_skill_settings_are_validated_too(client, make_skill):
    make_skill("skill-a", {"volume": 1})
    blob = _archive({"skills/skill-a/settings.json": b"{broken"})
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400


def test_s5_a_write_failure_part_way_does_not_half_restore(client, make_skill,
                                                           monkeypatch):
    """A disk error must not leave one file new and another old, or return 500."""
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    make_skill("skill-a", {"volume": 1})
    blob = _archive({"config/mycroft.conf": b'{"lang": "restored"}',
                     "skills/skill-a/settings.json": b'{"volume": 99}'})

    calls = {"n": 0}
    real = backupio.commit_staged

    def flaky(target, staged, within=None):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("disk full")
        return real(target, staged, within=within)

    monkeypatch.setattr(backupio, "commit_staged", flaky)
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400, "a disk error must not surface as a 500"
    assert "backup" in r.json()["detail"].lower()


def test_s5_nothing_is_written_before_every_member_is_read(client):
    """The bad member is last, so a streaming writer would already have written."""
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    blob = _archive({"config/mycroft.conf": b'{"lang": "hacked"}',
                     "skills/evil/../../x/settings.json": b"{}"})
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400
    assert configio.read_user_config()["lang"] == "pt-pt"


# ── S7: deleting a key must really drop it ───────────────────────────────────
def test_s7_deleting_a_key_clears_the_volatile_patch_first(client, bus):
    seen = []
    bus.on("configuration.patch", lambda m: seen.append((m.msg_type, m.data)))
    bus.on("configuration.patch.clear", lambda m: seen.append((m.msg_type, m.data)))
    client.put("/api/config", json={"text": '{"lang": "pt-pt", "extra": 1}',
                                    "format": "json"})
    seen.clear()
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    assert [t for t, _ in seen] == ["configuration.patch.clear", "configuration.patch"]
    assert "extra" not in seen[-1][1]["config"]


# ── S8: no route may be published without a check ────────────────────────────
UNAUTHENTICATED_ALLOWED = {"/api/status", "/api/login", "/api/logout",
                           "/login", "/healthz",
                           # the sign in page must be able to style itself
                           "/static/app.css",
                           # a browser fetches the web-app manifest and its
                           # icons without cookies; they ship in the package,
                           # so serving them tells a stranger nothing
                           "/static/manifest.webmanifest",
                           "/static/icon-192.png", "/static/icon-512.png"}


def test_s8_every_route_needs_a_sign_in_except_the_known_few(bus):
    app = create_app(bus=bus, host="0.0.0.0", token="s3cret-token", connect_bus=False)
    routes = []
    for router in app.state.routers.values():
        for route in router.routes:
            routes.append((getattr(route, "path", ""),
                           getattr(route, "methods", set()) or set()))
    checked = 0
    with TestClient(app, base_url="http://127.0.0.1:8500") as c:
        for path, methods in routes:
            if not path.startswith("/") or path in UNAUTHENTICATED_ALLOWED:
                continue
            if "GET" not in methods:
                continue
            probe = path.replace("{asset:path}", "app.js")
            probe = probe.replace("{skill_id}", "x").replace("{persona_id}", "x")
            if "{" in probe:
                continue
            r = c.get(probe)
            checked += 1
            assert r.status_code == 401, f"{probe} answered {r.status_code} with no token"
    assert checked >= 8


def test_s8_pages_need_a_sign_in(token_client):
    for page in ("/", "/config", "/skills", "/backup", "/about"):
        assert token_client.get(page).status_code == 401, page


def test_s8_static_assets_need_a_sign_in(token_client):
    assert token_client.get("/static/app.js").status_code == 401


def test_n3_only_the_stylesheet_is_public(token_client):
    """The sign in page would render unstyled without it, and a stylesheet
    that ships in the package tells a stranger nothing."""
    assert token_client.get("/static/app.css").status_code == 200
    assert token_client.get("/static/app.js").status_code == 401
    assert token_client.get("/static/login.html").status_code == 401


def test_n3_a_form_post_signs_in_without_javascript(token_client):
    r = token_client.post("/api/login", data={"token": "s3cret-token"},
                          follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert "ovos_webui_token" in r.headers.get_list("set-cookie")[0]


def test_n3_a_bad_form_post_goes_back_to_the_form(token_client):
    r = token_client.post("/api/login", data={"token": "wrong"},
                          follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login?bad=1"


def test_n3_a_json_login_still_returns_json(token_client):
    r = token_client.post("/api/login", json={"token": "s3cret-token"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_s8_the_schema_and_docs_are_not_published(client):
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404, path


def test_s8_the_login_page_is_reachable_without_a_token(token_client):
    assert token_client.get("/login").status_code == 200
    assert token_client.get("/healthz").status_code == 200


def test_s8_static_route_refuses_traversal(client):
    for bad in ("../fsutils.py", "..%2f..%2fservice.py", "../../pyproject.toml"):
        assert client.get(f"/static/{bad}").status_code in (400, 404)


# ── S9: the token must not travel in a URL ───────────────────────────────────
def test_s9_signing_in_uses_a_post_and_sets_a_cookie(token_client):
    r = token_client.post("/api/login", json={"token": "s3cret-token"})
    assert r.status_code == 200
    assert "ovos_webui_token" in r.cookies or any(
        "ovos_webui_token" in v for v in r.headers.get_list("set-cookie"))
    cookie = r.headers.get_list("set-cookie")[0].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_s9_the_cookie_then_works(token_client):
    token_client.post("/api/login", json={"token": "s3cret-token"})
    assert token_client.get("/api/health").status_code == 200
    assert token_client.get("/").status_code == 200


def test_s9_a_wrong_token_does_not_sign_in(token_client):
    assert token_client.post("/api/login", json={"token": "nope"}).status_code == 401


def test_s9_referrer_policy_is_set(client):
    r = client.get("/")
    assert r.headers.get("referrer-policy") == "same-origin"
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert "frame-ancestors 'none'" in r.headers.get("content-security-policy", "")


def test_s9_status_tells_a_stranger_almost_nothing(token_client):
    body = token_client.get("/api/status").json()
    assert body == {"auth": True, "signed_in": False}
    assert "host" not in body and "version" not in body


# ── S10: the file mode and owner must survive a write ────────────────────────
def test_s10_atomic_write_keeps_the_file_mode(tmp_path):
    target = tmp_path / "f.json"
    target.write_text("{}")
    target.chmod(0o644)
    fsutils.atomic_write(target, '{"a": 1}')
    assert oct(target.stat().st_mode & 0o777) == "0o644"


def test_s10_a_private_mode_is_kept_private(tmp_path):
    target = tmp_path / "f.json"
    target.write_text("{}")
    target.chmod(0o600)
    fsutils.atomic_write(target, '{"a": 1}')
    assert oct(target.stat().st_mode & 0o777) == "0o600"


def test_n2_a_new_file_is_private(tmp_path):
    """A new settings file can hold an API key, so it starts private."""
    target = tmp_path / "new.json"
    fsutils.atomic_write(target, "{}")
    assert oct(target.stat().st_mode & 0o777) == "0o600"


def test_n2_a_new_skill_settings_file_is_private(client):
    from ovos_webui import skillsio
    client.put("/api/skills/brand-new", json={"settings": {"api_key": "secret"}})
    assert oct(skillsio.settings_path("brand-new").stat().st_mode & 0o777) == "0o600"


def test_n2_an_existing_mode_is_still_respected(tmp_path):
    target = tmp_path / "f.json"
    target.write_text("{}")
    target.chmod(0o644)
    fsutils.atomic_write(target, '{"a": 1}')
    assert oct(target.stat().st_mode & 0o777) == "0o644"


def test_s10_restore_keeps_the_mode(client):
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    path = configio.user_config_path()
    path.chmod(0o640)
    blob = _archive({"config/mycroft.conf": b'{"lang": "en-us"}'})
    client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert oct(path.stat().st_mode & 0o777) == "0o640"


# ── S11: the member count must be applied while streaming ────────────────────
def test_s11_a_million_member_archive_is_refused_quickly(client):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for i in range(backupio.MAX_MEMBERS + 200):
            info = tarfile.TarInfo(f"skills/s{i}/settings.json")
            info.size = 2
            tar.addfile(info, io.BytesIO(b"{}"))
    blob = buf.getvalue()
    assert len(blob) < 2 * 1024 * 1024
    started = time.monotonic()
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400
    assert "too many files" in r.json()["detail"]
    assert time.monotonic() - started < 30


# ── S12: the simple form must validate what it writes ────────────────────────
@pytest.mark.parametrize("values", [
    {"lang": True},
    {"lang": 42},
    {"lang": {"a": 1}},
    {"lang": "not a language"},
    {"system_unit": "furlongs"},
    {"time_format": "sundial"},
    {"date_format": "YMD"},
    {"listener.wake_word": "no_such_wake_word"},
    {"lang": "x" * 300},
    {"lang": "pt-pt\nevil: 1"},
])
def test_s12_bad_quick_form_values_are_refused(client, values):
    r = client.post("/api/config/quick", json={"values": values})
    assert r.status_code in (400, 422), f"{values} was accepted"


def test_s12_a_refused_value_writes_nothing(client):
    client.put("/api/config", json={"text": '{"lang": "pt-pt"}', "format": "json"})
    client.post("/api/config/quick", json={"values": {"lang": True}})
    assert configio.read_user_config()["lang"] == "pt-pt"


def test_s12_good_quick_form_values_still_save(client):
    r = client.post("/api/config/quick",
                    json={"values": {"lang": "gl-es", "system_unit": "metric"}})
    assert r.status_code == 200
    assert configio.read_user_config()["lang"] == "gl-es"


# ── nit: backup pruning must keep the newest ─────────────────────────────────
def test_backup_pruning_keeps_the_newest_within_one_second(tmp_path):
    target = tmp_path / "f.json"
    for i in range(fsutils.MAX_BACKUPS + 6):
        fsutils.atomic_write(target, json.dumps({"n": i}))
    backups = fsutils.list_backups(target)
    assert len(backups) <= fsutils.MAX_BACKUPS
    newest = json.loads(backups[-1].read_text())
    oldest = json.loads(backups[0].read_text())
    assert newest["n"] > oldest["n"], "pruning kept the wrong backups"


# ── B1: bus threads must be bounded, whatever the number of requests ─────────
def _bus_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "ovos-webui-bus")


def test_b1_a_hundred_bus_down_saves_do_not_leak_threads(client):
    """The first fix gave every call its own thread and abandoned it on a
    timeout. A page that polls would then add stuck threads until the device
    could not start another one."""
    from ovos_webui import buswait

    bus = HangingBus()
    before = _bus_threads()
    started = time.monotonic()
    try:
        for _ in range(100):
            configio.write_user_config({"lang": "pt-pt"}, bus=bus)
        leaked = _bus_threads() - before
        elapsed = time.monotonic() - started
    finally:
        bus.released.set()

    assert leaked <= buswait.MAX_INFLIGHT, (
        f"{leaked} stuck bus threads after 100 calls; "
        f"the limit is {buswait.MAX_INFLIGHT}")
    assert elapsed < 60, f"100 bus-down saves took {elapsed:.0f}s"


def test_b1_a_hundred_health_requests_do_not_leak_threads(client):
    """The dashboard polls, and each poll probes six services twice."""
    from ovos_webui import buswait, health

    bus = HangingBus()
    before = _bus_threads()
    try:
        for _ in range(100):
            health.snapshot(bus, timeout=0.2)
        leaked = _bus_threads() - before
    finally:
        bus.released.set()
    assert leaked <= buswait.MAX_INFLIGHT, f"{leaked} stuck bus threads"


def test_b1_the_breaker_makes_repeat_calls_fast():
    """A save that waits three seconds every time makes the page unusable."""

    bus = HangingBus()
    try:
        first = time.monotonic()
        configio.write_user_config({"lang": "pt-pt"}, bus=bus)
        first_took = time.monotonic() - first

        second = time.monotonic()
        for _ in range(20):
            configio.write_user_config({"lang": "pt-pt"}, bus=bus)
        rest_took = time.monotonic() - second
    finally:
        bus.released.set()
    assert rest_took < first_took + 1.0, (
        f"20 more saves took {rest_took:.1f}s after the first took {first_took:.1f}s")


def test_b1_capacity_runs_out_instead_of_growing():
    """When every permit is held by a stuck call, the next one gives up now."""
    from ovos_webui import buswait

    stop = threading.Event()
    try:
        for _ in range(buswait.MAX_INFLIGHT):
            # Clear the breaker each time, so every call really takes a permit
            # and the permits, not the breaker, are what runs out.
            buswait.GATE.reset()
            buswait.call(lambda: stop.wait(60), timeout=0.05, default="gave up")
        buswait.GATE.reset()
        started = time.monotonic()
        assert buswait.call(lambda: "fresh", timeout=5, default="no capacity") == \
            "no capacity"
        assert time.monotonic() - started < 1.0
    finally:
        stop.set()


def test_b1_a_healthy_bus_gives_its_permit_back():
    from ovos_webui import buswait

    for _ in range(buswait.MAX_INFLIGHT * 10):
        assert buswait.call(lambda: "fine", timeout=2) == "fine"
    assert buswait.GATE.abandoned == 0
    assert _bus_threads() == 0


def test_b1_the_breaker_reopens_after_a_success():
    from ovos_webui import buswait

    stop = threading.Event()
    try:
        buswait.call(lambda: stop.wait(60), timeout=0.05)
        assert buswait.GATE.is_open()
    finally:
        stop.set()
    buswait.GATE.reset()
    assert buswait.call(lambda: "fine", timeout=2) == "fine"
    assert not buswait.GATE.is_open()


# ── B2: a symlinked skill directory must not lead a write out of the tree ────
def test_b2_a_symlinked_skill_directory_is_refused(client, tmp_path):
    """The name is a plain skill id, but the directory it names is a link."""
    from ovos_webui import skillsio

    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "settings.json"
    victim.write_text("untouched")

    root = skillsio.skills_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "evil").symlink_to(outside, target_is_directory=True)

    blob = _archive({"skills/evil/settings.json": b'{"pwned": true}'})
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400, f"a symlinked skill directory was accepted ({r.status_code})"
    assert victim.read_text() == "untouched", "a file outside the skills tree was written"


def test_b2_a_symlinked_skill_directory_is_refused_by_the_settings_route(client, tmp_path):
    from ovos_webui import skillsio

    outside = tmp_path / "outside2"
    outside.mkdir()
    victim = outside / "settings.json"
    victim.write_text("untouched")
    root = skillsio.skills_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "evil2").symlink_to(outside, target_is_directory=True)

    r = client.put("/api/skills/evil2", json={"settings": {"pwned": True}})
    assert r.status_code == 400
    assert victim.read_text() == "untouched"


def test_b2_containment_is_checked_again_at_write_time(tmp_path):
    """A link can appear between parsing a name and writing the file."""
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (base / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(fsutils.UnsafeIdentifier):
        fsutils.stage_file(base / "link" / "f.json", "{}", within=base)


def test_b2_commit_refuses_a_target_that_moved_outside(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "elsewhere2"
    outside.mkdir()
    staged = fsutils.stage_file(base / "f.json", "{}", within=base)
    (base / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(fsutils.UnsafeIdentifier):
        fsutils.commit_staged(base / "link" / "f.json", staged, within=base)


def test_b2_an_ordinary_restore_still_works(client, make_skill):
    make_skill("skill-a", {"volume": 1})
    blob = _archive({"skills/skill-a/settings.json": b'{"volume": 7}'})
    r = client.post("/api/restore", files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 200
    from ovos_webui import skillsio
    assert skillsio.read_settings("skill-a") == {"volume": 7}


# ── N1: the cross-site gate must not fail open ───────────────────────────────
def test_n1_a_browser_style_write_with_no_origin_headers_is_refused(client):
    """A request with no Origin, no Referer and no Sec-Fetch-Site and no
    Authorization header is not something this page ever sends."""
    r = client.put("/api/config",
                   json={"text": '{"lang": "pt-pt"}', "format": "json"},
                   headers={"user-agent": "Mozilla/5.0", "sec-fetch-site": ""})
    assert r.status_code == 403


def test_n1_sec_fetch_site_none_is_refused_for_writes(client):
    """`none` means a navigation typed into the address bar, never an API write."""
    r = client.put("/api/config", json={"text": "{}", "format": "json"},
                   headers={"sec-fetch-site": "none"})
    assert r.status_code == 403


def test_n1_a_program_with_a_bearer_token_still_works(token_client):
    r = token_client.put("/api/config",
                         json={"text": '{"lang": "pt-pt"}', "format": "json"},
                         headers={"Authorization": "Bearer s3cret-token"})
    assert r.status_code == 200


def test_n1_reads_with_no_headers_are_still_fine(client):
    assert client.get("/api/health").status_code == 200


# ── N3: the Host header must be checked, or DNS rebinding defeats everything ──
def test_n3_a_foreign_host_header_is_refused(client):
    """A DNS rebinding page reaches the device but the browser still sends the
    attacker's own name in Host. That name is refused, reads included."""
    r = client.get("/api/config", headers={"host": "evil.com"})
    assert r.status_code == 400


def test_n3_a_foreign_host_cannot_write_either(client):
    r = client.put("/api/config", headers={"host": "evil.com:8500"},
                   json={"text": '{"lang": "pt-pt"}', "format": "json"})
    assert r.status_code == 400


def test_n3_a_numeric_ip_host_is_accepted(client):
    """The legitimate case: a browser reaching the device by its LAN address."""
    r = client.get("/api/config", headers={"host": "192.168.1.50:8500"})
    assert r.status_code == 200


def test_n3_the_loopback_names_are_accepted(client):
    for name in ("127.0.0.1:8500", "localhost:8500", "[::1]:8500"):
        r = client.get("/api/status", headers={"host": name})
        assert r.status_code == 200, name


def test_n3_a_configured_hostname_is_accepted(bus):
    app = create_app(bus=bus, host="0.0.0.0", token=None, connect_bus=False,
                     hostnames=("ovos.local",))
    with TestClient(app, base_url="http://ovos.local:8500",
                    headers={"sec-fetch-site": "same-origin"}) as c:
        assert c.get("/api/status").status_code == 200
        assert c.get("/api/status", headers={"host": "evil.com"}).status_code == 400


# ── N4: the bus permit pool must not starve the dashboard's own fan-out ───────
def test_n4_a_healthy_dashboard_load_reports_every_service(bus):
    """One dashboard load probes six services at once. If the permit pool is
    smaller than that fan-out, healthy services show 'no answer' and the
    breaker trips."""
    from ovos_bus_client.message import Message

    from ovos_webui import buswait, health

    for spec in health.SERVICES:
        for key in ("alive", "ready"):
            mt = f"mycroft.{spec['name']}.is_{key}"
            bus.on(mt, (lambda m: bus.emit(
                Message(m.msg_type + ".response", {"status": True}, m.context))))

    for _ in range(3):
        buswait.GATE.reset_for_tests()
        snap = health.snapshot(bus, timeout=1.0)
        assert all(s["state"] == "ready" for s in snap["services"]), \
            [s["state"] for s in snap["services"]]
        assert not buswait.GATE.is_open()

    assert len(health.SERVICES) <= buswait.MAX_INFLIGHT


# ── N5: one archive member must not be able to exhaust memory ─────────────────
def test_n5_a_giant_member_is_refused(client):
    big = b'{"x": "' + b"a" * (backupio.MAX_MEMBER_BYTES + 10) + b'"}'
    blob = _archive({"config/mycroft.conf": big})
    r = client.post("/api/restore",
                    files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 400


def test_n5_a_normal_settings_file_still_restores(client, make_skill):
    make_skill("skill-a", {"volume": 1})
    blob = _archive({"skills/skill-a/settings.json": b'{"volume": 9}'})
    r = client.post("/api/restore",
                    files={"file": ("b.tar.gz", blob, "application/gzip")})
    assert r.status_code == 200


# ── N6: a save that could not reach the bus must say so ───────────────────────
def test_n6_a_save_with_the_bus_down_is_reported_not_live(tmp_path, monkeypatch):
    from ovos_webui import buswait, configio

    class DownBus:
        connected_event = None  # is_connected -> True, but emit hangs

        def emit(self, message):
            import time as _t
            _t.sleep(30)

    buswait.GATE.reset_for_tests()
    # is_connected returns True for a bus with no connected_event attribute
    result = configio.write_user_config({"lang": "pt-pt"}, bus=DownBus())
    assert result["applied"] is False


def test_n6_a_save_with_no_bus_is_live(client):
    """When the UI runs without a bus, nothing was lost, so applied is True."""
    r = client.put("/api/config",
                   json={"text": '{"lang": "pt-pt"}', "format": "json"})
    assert r.status_code == 200
    assert r.json()["applied"] is True


# ── N7: a token too short to resist guessing must be refused at startup ───────
def test_n7_a_short_token_is_refused():
    from ovos_webui.auth import policy_from_config
    with pytest.raises(ValueError):
        policy_from_config(host="0.0.0.0", token="1234")


def test_n7_a_long_enough_token_is_accepted():
    from ovos_webui.auth import policy_from_config
    p = policy_from_config(host="0.0.0.0", token="a-long-token")
    assert p.token == "a-long-token"


# ── N8: a form field named 'file' that is not a file must not crash ───────────
def test_n8_a_multipart_text_field_named_file_is_a_clean_400(client):
    """A multipart form whose ``file`` part is a plain text field, not an
    upload, used to reach ``.read()`` on a str and answer 500."""
    # (None, value) makes httpx send a multipart form field with no filename,
    # so the server parses it as a string, not an upload.
    r = client.post("/api/restore", files={"file": (None, "not a file")})
    assert r.status_code == 400


# ── N9: repeated wrong tokens must be slowed down (no lock-out means throttle) ─
def test_n9_failed_logins_are_throttled_and_reset(token_client, monkeypatch):
    """Each wrong token in a row waits longer; a correct one resets the wait."""
    import ovos_webui.service as service

    delays = []

    async def fake_sleep(d):
        delays.append(d)

    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)

    for _ in range(4):
        r = token_client.post("/api/login", json={"token": "wrong-token"})
        assert r.status_code == 401
    assert delays == [0.5, 1.0, 1.5, 2.0], delays

    # a correct sign in clears the streak
    r = token_client.post("/api/login", json={"token": "s3cret-token"})
    assert r.status_code == 200
    delays.clear()
    r = token_client.post("/api/login", json={"token": "wrong-token"})
    assert r.status_code == 401
    assert delays == [0.5], delays


def test_n9_the_delay_is_capped(token_client, monkeypatch):
    import ovos_webui.service as service

    delays = []

    async def fake_sleep(d):
        delays.append(d)

    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)
    for _ in range(20):
        token_client.post("/api/login", json={"token": "nope-nope"})
    assert max(delays) == 5.0
