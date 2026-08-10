"""Optional token access control.

The service is made for a device on a home network. On ``127.0.0.1`` it is
open by default, because only a user of the device can reach it. When you bind
it to another address, set a token. Without a token, anyone on the network can
change the configuration of the device.

Set the token in ``mycroft.conf``::

    {"webui": {"access_token": "some-long-random-string"}}
"""
from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status
from ovos_utils.log import LOG

LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")

#: A token shorter than this is refused at startup. A short token can be
#: guessed over the network, because there is no account lock-out.
MIN_TOKEN_LENGTH = 8


def host_name(host_header: str) -> str:
    """Return the name part of a ``Host`` header, without the port.

    ``urlsplit`` understands both ``name:port`` and the bracketed
    ``[ipv6]:port`` form, so this works for either.
    """
    if not host_header:
        return ""
    return (urlsplit("//" + host_header).hostname or "").lower()


def is_ip_literal(name: str) -> bool:
    """True when ``name`` is a numeric IPv4 or IPv6 address, not a hostname."""
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False

#: The name of the cookie that carries the token after a sign in.
COOKIE_NAME = "ovos_webui_token"

#: Methods that cannot change anything.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass
class AuthPolicy:
    """The access rules of one running service."""

    token: str | None = None
    host: str = "0.0.0.0"
    #: Extra hostnames a browser may use in the ``Host`` header, on top of the
    #: bind address, the loopback names and any numeric IP. Set this for a
    #: reverse proxy or an mDNS name such as ``ovos.local``.
    allowed_hostnames: tuple[str, ...] = field(default_factory=tuple)

    def host_allowed(self, host_header: str) -> bool:
        """True when a request's ``Host`` header may be served.

        A DNS rebinding attack turns an attacker-owned name into the device
        address so a browser will treat the attacker's page as same-origin.
        The one thing the attacker cannot change is the name the browser puts
        in the ``Host`` header: it is still their domain. So a numeric IP and
        the loopback names are allowed, and any other name must be one the
        operator listed. A bare domain in ``Host`` is refused, which is what
        stops rebinding.
        """
        name = host_name(host_header)
        if not name:
            return False
        if name in LOCAL_HOSTS or is_ip_literal(name):
            return True
        return name in self.allowed_hostnames

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
            LOG.warning("ovos-webui: refused a request with a wrong or missing "
                        f"token from {request.client.host if request.client else '?'} "
                        f"to {request.method} {request.url.path}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="a valid token is needed",
                                headers={"WWW-Authenticate": "Bearer"})


def same_origin(request: Request) -> bool:
    """Return True when a state changing request really came from this page.

    A browser sends ``Sec-Fetch-Site`` on every request, and an ``Origin``
    header on anything that can change state. At least one of the three
    headers below must be there and must say "this site". A request that
    carries none of them is not accepted just because it is quiet: that would
    let anything that can suppress them straight through.

    The one exception is a caller that sends an ``Authorization`` header. A web
    page cannot make a browser attach one to a cross-site request without a
    preflight, and a preflight is never approved here, so such a request cannot
    be a forgery. That is what keeps ``curl`` and other programs working.

    ``Sec-Fetch-Site: none`` means a navigation the user typed, which is never
    how this page sends a write, so it is not accepted for an unsafe method.
    """
    host = request.headers.get("host", "")

    site = request.headers.get("sec-fetch-site", "")
    if site:
        return site == "same-origin"

    origin = request.headers.get("origin", "")
    if origin:
        return bool(host) and urlsplit(origin).netloc == host

    referer = request.headers.get("referer", "")
    if referer:
        return bool(host) and urlsplit(referer).netloc == host

    # Nothing said where this came from. Only a caller that authenticates with
    # a header, which a web page cannot do across sites, is allowed through.
    return request.headers.get("authorization", "").lower().startswith("bearer ")


def check_csrf(request: Request) -> None:
    """Raise 403 when a state changing request came from another site."""
    if request.method in SAFE_METHODS:
        return
    if not same_origin(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this request came from another web site and was refused")


def check_host(policy: AuthPolicy, request: Request) -> None:
    """Raise 400 when the request's ``Host`` header is not one we serve.

    This runs before anything else and on every method, reads included,
    because a DNS rebinding attack reads the configuration as readily as it
    writes it. See :meth:`AuthPolicy.host_allowed`.
    """
    header = request.headers.get("host", "")
    if not policy.host_allowed(header):
        LOG.warning(f"ovos-webui: refused a request for Host {header!r} from "
                    f"{request.client.host if request.client else '?'}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="this request was sent to a host name this service does "
                   "not answer to")


def policy_from_config(host: str = "0.0.0.0", token: str | None = None,
                       hostnames: tuple[str, ...] = ()) -> AuthPolicy:
    """Build the policy from ``mycroft.conf``, with overrides from the caller."""
    section = {}
    if token is None:
        try:
            from ovos_config.config import Configuration
            section = Configuration().get("webui") or {}
        except Exception:  # noqa: BLE001 # pragma: no cover - a broken config must not stop the UI
            section = {}
        token = section.get("access_token") or None
    from_config = section.get("hostnames") or []
    if isinstance(from_config, str):
        from_config = [from_config]
    names = tuple(dict.fromkeys(  # keep order, drop duplicates
        n.lower() for n in (*hostnames, *from_config) if n))

    token = token or None
    if token is not None and len(token) < MIN_TOKEN_LENGTH:
        raise ValueError(
            f"the webui token is too short: it must be at least "
            f"{MIN_TOKEN_LENGTH} characters, because there is no lock-out to "
            f"stop it being guessed over the network")
    return AuthPolicy(token=token, host=host, allowed_hostnames=names)
