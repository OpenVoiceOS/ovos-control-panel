"""Browser sessions: what the sign-in cookie carries instead of the token.

Signing in used to put the access token itself in the cookie. Logging out
then only asked the browser to forget it: a copied cookie kept working until
the token was changed in mycroft.conf. Now the cookie carries a random
session id. The device keeps only a hash of it, with when it ends and a mark
of the token it was made under, in a file only its owner can read
(``.ovos-webui-sessions.json`` beside mycroft.conf). So:

- logging out ends that session on the device, not just in the browser;
- changing the token ends every session made under the old one;
- a session ends after :data:`MAX_AGE` in any case;
- sessions survive a restart of the panel.

Programs still send the token itself, as ``Authorization: Bearer <token>``.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

from ovos_utils.log import LOG

#: How long a session lasts, as the cookie does
MAX_AGE = 30 * 24 * 3600
#: The most sessions kept; the oldest go first
MAX_SESSIONS = 200
FILE_NAME = ".ovos-webui-sessions.json"

_LOCK = threading.Lock()


def _path() -> Path:
    from ovos_webui.configio import user_config_path
    return Path(user_config_path()).parent / FILE_NAME


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def token_mark(token: str) -> str:
    """A mark of the token a session was made under, not the token."""
    return _hash("ovos-webui-session:" + token)[:32]


def _load() -> dict[str, dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _pruned(data: dict[str, dict], now: float) -> dict[str, dict]:
    live = {k: v for k, v in data.items()
            if isinstance(v, dict) and isinstance(v.get("ends"), (int, float)) and v["ends"] > now}
    if len(live) > MAX_SESSIONS:
        keep = sorted(live.items(), key=lambda kv: kv[1]["ends"], reverse=True)[:MAX_SESSIONS]
        live = dict(keep)
    return live


def start(token: str) -> str:
    """A new session under ``token``; answers the id for the cookie."""
    sid = secrets.token_urlsafe(32)
    now = time.time()
    with _LOCK:
        data = _load()
        data[_hash(sid)] = {"ends": now + MAX_AGE, "token": token_mark(token)}
        data = _pruned(data, now)
        try:
            _save(data)
        except OSError as err:
            LOG.warning(f"ovos-webui: could not keep the session on the device: {err}")
    return sid


def valid(sid: str, token: str | None) -> bool:
    """Whether ``sid`` is a live session made under ``token``."""
    if not sid or not token:
        return False
    with _LOCK:
        found = _load().get(_hash(sid))
    if not isinstance(found, dict):
        return False
    return (isinstance(found.get("ends"), (int, float)) and found["ends"] > time.time()
            and secrets.compare_digest(str(found.get("token", "")), token_mark(token)))


def end(sid: str) -> None:
    """End one session (log out)."""
    if not sid:
        return
    with _LOCK:
        data = _load()
        if data.pop(_hash(sid), None) is not None:
            try:
                _save(_pruned(data, time.time()))
            except OSError as err:
                LOG.warning(f"ovos-webui: could not end the session on the device: {err}")
