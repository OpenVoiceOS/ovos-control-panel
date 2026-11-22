"""The sign-in cookie carries a session, not the token: logging out ends it,
a changed token ends every older one, and it ends by itself."""
import json
import time

from ovos_webui import sessions
from ovos_webui.auth import COOKIE_NAME


def _signed_in(c):
    r = c.post("/api/login", json={"token": "s3cret-token"})
    assert r.status_code == 200
    return c.cookies.get(COOKIE_NAME)


def test_the_cookie_is_not_the_token(token_client):
    sid = _signed_in(token_client)
    assert sid and sid != "s3cret-token" and "s3cret-token" not in sid
    stored = sessions._path().read_text()
    assert sid not in stored and "s3cret-token" not in stored, "only hashes are kept"
    assert oct(sessions._path().stat().st_mode & 0o777) == "0o600"
    assert token_client.get("/api/health").status_code == 200


def test_the_token_itself_as_a_cookie_no_longer_signs_in(token_client):
    token_client.cookies.set(COOKIE_NAME, "s3cret-token")
    assert token_client.get("/api/health").status_code == 401
    token_client.cookies.set("ovos_webui_token", "s3cret-token")
    assert token_client.get("/api/health").status_code == 401


def test_logging_out_ends_the_session_for_a_copy_too(token_client):
    sid = _signed_in(token_client)
    token_client.post("/api/logout")
    token_client.cookies.set(COOKIE_NAME, sid)       # the copied cookie
    assert token_client.get("/api/health").status_code == 401


def test_a_changed_token_ends_the_other_sessions(token_client):
    other = _signed_in(token_client)
    r = token_client.post("/api/auth/token", json={"new": "brandnewtoken1", "current": "s3cret-token"})
    assert r.status_code == 200
    mine = token_client.cookies.get(COOKIE_NAME)
    assert mine and mine != other
    assert token_client.get("/api/health").status_code == 200, "this one goes on"
    token_client.cookies.set(COOKIE_NAME, other)
    assert token_client.get("/api/health").status_code == 401, "the old one ended"


def test_a_session_ends_by_itself():
    sid = sessions.start("tok")
    assert sessions.valid(sid, "tok") and not sessions.valid(sid, "other") and not sessions.valid("", "tok")
    data = json.loads(sessions._path().read_text())
    for v in data.values():
        v["ends"] = time.time() - 1
    sessions._save(data)
    assert not sessions.valid(sid, "tok")


def test_the_bearer_header_still_works_for_programs(token_client):
    assert token_client.get("/api/health", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
    assert token_client.get("/api/health", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_there_are_never_too_many_kept(monkeypatch):
    monkeypatch.setattr(sessions, "MAX_SESSIONS", 3)
    ids = [sessions.start("tok") for _ in range(5)]
    assert len(json.loads(sessions._path().read_text())) == 3
    assert sessions.valid(ids[-1], "tok")
