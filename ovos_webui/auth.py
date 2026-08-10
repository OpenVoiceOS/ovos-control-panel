"""Optional token access control.

The service is made for a device on a home network. On ``127.0.0.1`` it is
open by default, because only a user of the device can reach it. When you bind
it to another address, set a token. Without a token, anyone on the network can
change the configuration of the device.

Set the token in ``mycroft.conf``::

    {"webui": {"access_token": "some-long-random-string"}}
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")

#: The name of the cookie that carries the token after a sign in.
COOKIE_NAME = "ovos_webui_token"

#: Methods that cannot change anything.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass
class AuthPolicy:
    """The access rules of one running service."""

    token: str | None = None
    host: str = "0.0.0.0"

    @property
    def local_only(self) -> bool:
        """True when the service is bound to the loopback address only."""
        return self.host in LOCAL_HOSTS

    @property
    def insecure(self) -> bool:
        """True when the service is open and reachable from the network."""
        return not self.token and not self.local_only

    @property
    def warning(self) -> str | None:
        """The banner text to show, or ``None`` when there is nothing to warn about."""
        if self.insecure:
            return ("This page is open to your whole network and has no token. "
                    "Anyone on the network can change this device. "
                    "Set webui.access_token in mycroft.conf.")
        return None

    def matches(self, supplied: str) -> bool:
        """Return True when ``supplied`` is the token, compared in constant time."""
        if not self.token or not supplied:
            return False
        return secrets.compare_digest(supplied, self.token)

    def supplied_token(self, request: Request) -> str:
        """Return the token the request carries.

        Only two places are read: the ``Authorization`` header, for programs,
        and the cookie, for browsers. The query string is deliberately not one
        of them, because it is written to the access log of every proxy and to
        the browser history on every click.
        """
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return request.cookies.get(COOKIE_NAME, "")

    def check(self, request: Request) -> None:
        """Raise 401 when a token is set and the request does not carry it."""
        if not self.token:
            return
        if not self.matches(self.supplied_token(request)):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="a valid token is needed",
                                headers={"WWW-Authenticate": "Bearer"})


def same_origin(request: Request) -> bool:
    """Return True when a state changing request did not come from another site.

    A browser sends ``Sec-Fetch-Site`` on every request, and an ``Origin``
    header on anything that can change state. A program such as curl sends
    neither, and a program is not a cross-site request forgery risk, because a
    web page cannot make one send an ``Authorization`` header.

    Without this check any web page in the world could post a form to
    ``http://<device>:8500/api/restore`` and rewrite the configuration of a
    device on the visitor's home network, with no token and no reply needed.
    """
    site = request.headers.get("sec-fetch-site", "")
    if site:
        return site in ("same-origin", "none")
    origin = request.headers.get("origin", "")
    if origin:
        host = request.headers.get("host", "")
        parsed = urlsplit(origin)
        return bool(host) and parsed.netloc == host
    referer = request.headers.get("referer", "")
    if referer:
        host = request.headers.get("host", "")
        return bool(host) and urlsplit(referer).netloc == host
    # No browser sent this.
    return True


def check_csrf(request: Request) -> None:
    """Raise 403 when a state changing request came from another site."""
    if request.method in SAFE_METHODS:
        return
    if not same_origin(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this request came from another web site and was refused")


def policy_from_config(host: str = "0.0.0.0", token: str | None = None) -> AuthPolicy:
    """Build the policy from ``mycroft.conf``, with overrides from the caller."""
    section = {}
    if token is None:
        try:
            from ovos_config.config import Configuration
            section = Configuration().get("webui") or {}
        except Exception:  # noqa: BLE001 # pragma: no cover - a broken config must not stop the UI
            section = {}
        token = section.get("access_token") or None
    return AuthPolicy(token=token or None, host=host)
