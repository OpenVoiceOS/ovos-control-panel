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

from fastapi import HTTPException, Request, status

LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")


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

    def check(self, request: Request) -> None:
        """Raise 401 when a token is set and the request does not carry it."""
        if not self.token:
            return
        header = request.headers.get("authorization", "")
        supplied = ""
        if header.lower().startswith("bearer "):
            supplied = header[7:].strip()
        if not supplied:
            supplied = request.query_params.get("token", "")
        if not supplied or not secrets.compare_digest(supplied, self.token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="a valid token is needed",
                                headers={"WWW-Authenticate": "Bearer"})


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
