"""Synchronous ChurchTools API client with a Rust core.

    import churchtools_rs as ct

    client = ct.Client("https://meinegemeinde.church.tools", token="...")
    for event in client.events.list(from_=date(2026, 11, 1), to=date(2026, 11, 30)):
        print(event.start_date, event.name)
"""

from __future__ import annotations

import os
import typing as _t

from . import models
from ._base import UNSET, CTModel, Paginator, Upload
from ._core import Client as _CoreClient
from ._errors import (
    ApiError,
    BadRequest,
    ChurchToolsError,
    Conflict,
    DecodeError,
    Forbidden,
    NotFound,
    ServerError,
    TransportError,
    Unauthorized,
    UnprocessableEntity,
)
from ._resources import Resources


class Client(Resources):
    """ChurchTools client.

    Args:
        base_url: Instance URL, e.g. `https://meinegemeinde.church.tools` (`/api` optional).
        token: Personal login token; sent as `Authorization: Login <token>`.
        timeout: Request timeout in seconds.
        min_interval: Minimum time in seconds between two requests (rate limit),
            e.g. `0.25` for at most four requests per second. Answers with
            `429 Too Many Requests` are retried regardless of this setting.
        allow_insecure_http: Allows `http://` for hosts other than localhost. The
            token then travels unencrypted; only for instances in a trusted network.
    """

    def __init__(
        self,
        base_url: str,
        token: _t.Optional[str] = None,
        *,
        timeout: float = 30.0,
        min_interval: _t.Optional[float] = None,
        allow_insecure_http: bool = False,
    ) -> None:
        self._core = _CoreClient(base_url, token, timeout, min_interval, allow_insecure_http)
        super().__init__(self._core)

    @classmethod
    def from_env(cls, *, timeout: float = 30.0, min_interval: _t.Optional[float] = None) -> "Client":
        """Reads `CT_URL` and `CT_TOKEN`."""
        return cls(os.environ["CT_URL"], os.environ.get("CT_TOKEN"), timeout=timeout, min_interval=min_interval)

    def login_with_password(self, username: str, password: str) -> "Client":
        """Logs in with username and password; returns a client using that person's login token.

        Keeps URL, timeout and rate limit. Meant for tests and interactive tools;
        scripts should use a stored token.
        """
        client = Client.__new__(Client)
        client._core = self._core.login_with_password(username, password)
        Resources.__init__(client, client._core)
        return client

    @property
    def api_url(self) -> str:
        return self._core.api_url

    def __repr__(self) -> str:
        return f"Client({self.api_url!r})"


__all__ = [
    "ApiError",
    "BadRequest",
    "ChurchToolsError",
    "Client",
    "Conflict",
    "CTModel",
    "DecodeError",
    "Forbidden",
    "NotFound",
    "Paginator",
    "ServerError",
    "TransportError",
    "Unauthorized",
    "UnprocessableEntity",
    "UNSET",
    "Upload",
    "models",
]
