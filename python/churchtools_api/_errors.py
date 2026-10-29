"""Exceptions raised by the client."""

from __future__ import annotations

import json
import typing as _t


class ChurchToolsError(Exception):
    """Base class of all errors raised by churchtools_api."""


class InvalidArgument(ChurchToolsError, ValueError):
    """An argument is invalid before anything is sent: the base URL, the token,
    a timeout, or a path parameter that is empty, `.` or `..`."""


class TransportError(ChurchToolsError):
    """The server could not be reached or the connection failed."""


class ConnectError(TransportError):
    """No connection to the server: wrong address, network down, or the
    connect timeout expired."""


class Timeout(TransportError):
    """The request took longer than `timeout`."""


class ResponseTooLarge(TransportError):
    """The response body is larger than `max_response_size`."""

    def __init__(self, message: str, limit: int) -> None:
        super().__init__(message)
        self.limit = limit


class DecodeError(ChurchToolsError):
    """The response did not match the expected shape (often a spec mismatch)."""

    def __init__(self, message: str, body: bytes = b"") -> None:
        super().__init__(message)
        self.body = body


class RedirectError(ChurchToolsError):
    """The server answered with a redirect (301, 302, 303) that is not followed:
    it would repeat the request as GET without its body."""

    def __init__(self, message: str, status: int, location: _t.Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.location = location


class ApiError(ChurchToolsError):
    """The server answered with a non-2xx status.

    ChurchTools error bodies look like
    `{"message", "translatedMessage", "messageKey", "args", "errors"}`.
    """

    status: int

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        try:
            data = json.loads(body) if body else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        self.message: _t.Optional[str] = data.get("message")
        self.translated_message: _t.Optional[str] = data.get("translatedMessage")
        self.message_key: _t.Optional[str] = data.get("messageKey")
        self.message_args: _t.Any = data.get("args")
        """`args` of the error body (placeholders of the message); `args` itself is the exception's."""
        self.errors: _t.Any = data.get("errors")
        super().__init__(f"HTTP {status}: {self.message or body[:200]!r}{_field_errors(self.errors)}")


def _field_errors(errors: _t.Any) -> str:
    """Validation details, e.g. ` (domainType: must be one of: group)`."""
    if not isinstance(errors, list) or not errors:
        return ""
    parts = []
    for e in errors[:5]:
        if isinstance(e, dict):
            text = e.get("message") or e.get("messageKey") or ""
            args = e.get("args")
            if isinstance(args, dict) and args.get("allowedValues"):
                text = text if str(args["allowedValues"]) in text else f"{text} [{args['allowedValues']}]"
            parts.append(f"{e.get('fieldId', '?')}: {text}".rstrip(": "))
    return f" ({'; '.join(parts)})" if parts else ""


class BadRequest(ApiError):
    """400"""


class Unauthorized(ApiError):
    """401: token missing, invalid or expired."""


class Forbidden(ApiError):
    """403: authenticated, but lacking permission."""


class NotFound(ApiError):
    """404"""


class Conflict(ApiError):
    """409"""


class UnprocessableEntity(ApiError):
    """422: validation failed; see `errors`."""


class ServerError(ApiError):
    """5xx"""


_BY_STATUS: dict[int, type[ApiError]] = {
    400: BadRequest,
    401: Unauthorized,
    403: Forbidden,
    404: NotFound,
    409: Conflict,
    422: UnprocessableEntity,
}


def from_response(status: int, body: bytes) -> ApiError:
    cls = _BY_STATUS.get(status) or (ServerError if status >= 500 else ApiError)
    return cls(status, body)
