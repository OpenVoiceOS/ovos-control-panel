"""Tests for access control, the About route and every page (end to end)."""
import pytest
from fastapi.testclient import TestClient

from ovos_webui.auth import AuthPolicy
from ovos_webui.service import PAGES, create_app

PROTECTED = [
    ("get", "/api/health"),
    ("get", "/api/config"),
    ("get", "/api/config/merged"),
    ("get", "/api/config/quick"),
    ("get", "/api/plugins"),
    ("get", "/api/skills"),
    ("get", "/api/skills/skill-a"),
    ("get", "/api/backup"),
    ("get", "/api/about"),
]


def test_policy_flags():
    assert AuthPolicy(token=None, host="127.0.0.1").insecure is False
    assert AuthPolicy(token=None, host="127.0.0.1").warning is None
    assert AuthPolicy(token=None, host="0.0.0.0").insecure is True
    assert "token" in AuthPolicy(token=None, host="0.0.0.0").warning
    assert AuthPolicy(token="x", host="0.0.0.0").insecure is False


def test_status_reports_the_warning(bus):
    app = create_app(bus=bus, host="0.0.0.0", token=None, connect_bus=False)
    with TestClient(app) as c:
        body = c.get("/api/status").json()
    assert body["insecure"] is True and body["auth"] is False and body["warning"]


def test_status_needs_no_token(token_client):
    assert token_client.get("/api/status").status_code == 200


@pytest.mark.parametrize("method,path", PROTECTED)
def test_token_is_required(token_client, method, path):
    assert getattr(token_client, method)(path).status_code == 401


@pytest.mark.parametrize("method,path", PROTECTED)
def test_correct_token_is_accepted(token_client, method, path):
    r = getattr(token_client, method)(path, headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_writes_are_refused_without_a_token(token_client):
    assert token_client.put("/api/config", json={"text": "{}", "format": "json"}).status_code == 401
    assert token_client.put("/api/skills/a", json={"settings": {}}).status_code == 401
    assert token_client.post("/api/restore", content=b"x").status_code == 401


def test_a_wrong_token_is_refused(token_client):
    for bad in ["", "s3cre", "s3cretx", "S3CRET", "bearer"]:
        r = token_client.get("/api/health", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401


def test_a_token_in_the_query_string_is_ignored(token_client):
    """A token in a URL is written to every access log, so it is not accepted."""
    assert token_client.get("/api/health?token=s3cret").status_code == 401


def test_unauthorised_answers_carry_the_scheme(token_client):
    r = token_client.get("/api/health")
    assert r.headers.get("www-authenticate") == "Bearer"


@pytest.mark.parametrize("route", sorted(PAGES))
def test_every_page_renders(client, route):
    r = client.get(route)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "<nav>" in body and "app.js" in body


@pytest.mark.parametrize("route", sorted(PAGES))
def test_pages_load_no_external_assets(client, route):
    body = client.get(route).text
    for marker in ["cdn.", "unpkg.com", "jsdelivr", "googleapis", "//ajax."]:
        assert marker not in body, f"{route} pulls in {marker}"


def test_static_assets_are_served(client):
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_about_route(client):
    body = client.get("/api/about").json()
    assert body["version"]
    assert any(link["label"].startswith("ovos-busmon") or "busmon" in link["url"]
               for link in body["links"])
    names = [p["name"] for p in body["packages"]]
    assert "ovos-config" in names


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


def test_unknown_route_is_a_404(client):
    assert client.get("/nope").status_code == 404


def test_app_starts_and_stops_without_a_bus():
    app = create_app(bus=None, host="127.0.0.1", connect_bus=False)
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
