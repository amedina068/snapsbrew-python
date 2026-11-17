"""The errors that the Snapsbrew client raises.

All errors come from :class:`SnapsbrewError`::

    SnapsbrewError
    +-- APIConnectionError         the request did not get a response
    |   +-- APITimeoutError        the request took more time than the timeout
    +-- APIError                   the server sent an error response
    |   +-- BadRequestError        400
    |   +-- AuthenticationError    401
    |   +-- AuthorizationError     403
    |   +-- NotFoundError          404
    |   +-- ConflictError          409
    |   +-- ValidationError        422, with the field errors
    |   +-- RateLimitError         429, with the Retry-After value
    |   +-- ServerError            5xx
    +-- WaitTimeoutError           a batch did not finish in the wait time
"""

from __future__ import annotations

from typing import Any

import httpx

__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "AuthenticationError",
    "AuthorizationError",
    "BadRequestError",
    "ConflictError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "SnapsbrewError",
    "ValidationError",
    "WaitTimeoutError",
]


class SnapsbrewError(Exception):
    """The base class of every error that this package raises."""


class APIConnectionError(SnapsbrewError):
    """The client did not get a response from the instance.

    The cause is a DNS error, a refused connection, a closed connection or a TLS
    error. The original ``httpx`` exception is in ``__cause__``.
    """

    def __init__(self, message: str, *, request: httpx.Request | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.request = request


class APITimeoutError(APIConnectionError):
    """The request took more time than the timeout of the client."""


class WaitTimeoutError(SnapsbrewError, TimeoutError):
    """A batch did not get to a terminal status before the wait time ended."""


class APIError(SnapsbrewError):
    """The instance sent a response with an error status.

    Attributes:
        status_code: The HTTP status code.
        message: The ``message`` field of the body, or the reason phrase.
        code: The ``code`` field of the body, when the body has one.
        body: The decoded JSON body, or the text body.
        request_id: The ``X-Request-Uuid`` header. Give it to support.
        response: The ``httpx.Response``.
    """

    def __init__(self, message: str, *, response: httpx.Response, body: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.response = response
        self.status_code = response.status_code
        self.body = body
        self.request_id: str | None = response.headers.get("x-request-uuid")
        self.code: str | None = None
        if isinstance(body, dict) and isinstance(body.get("code"), str):
            self.code = body["code"]

    def __str__(self) -> str:
        return f"{self.status_code}: {self.message}"


class BadRequestError(APIError):
    """The server refused the request (400)."""


class AuthenticationError(APIError):
    """The token is missing, not valid or expired (401)."""


class AuthorizationError(APIError):
    """The token is valid but it cannot do this action (403).

    A token must have the ``api_requests`` ability.
    """


class NotFoundError(APIError):
    """The resource does not exist in your company (404)."""


class ConflictError(APIError):
    """The request conflicts with the state on the server (409).

    For example, a request with the same ``idempotency_key`` is in progress.
    """


class ValidationError(APIError):
    """A field of the request failed a validation rule (422).

    Attributes:
        errors: The field errors, for example ``{"template_id": ["..."]}``.
    """

    def __init__(self, message: str, *, response: httpx.Response, body: Any = None) -> None:
        super().__init__(message, response=response, body=body)
        self.errors: dict[str, list[str]] = _field_errors(body)


class RateLimitError(APIError):
    """The instance received too many requests (429).

    Attributes:
        retry_after: The seconds to wait from the ``Retry-After`` header, or ``None``.
    """

    def __init__(
        self,
        message: str,
        *,
        response: httpx.Response,
        body: Any = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, response=response, body=body)
        self.retry_after = retry_after


class ServerError(APIError):
    """The instance had an internal error (5xx)."""


def _field_errors(body: Any) -> dict[str, list[str]]:
    if not isinstance(body, dict):
        return {}
    raw = body.get("errors")
    if not isinstance(raw, dict):
        return {}
    errors: dict[str, list[str]] = {}
    for field, messages in raw.items():
        if isinstance(messages, list):
            errors[str(field)] = [str(item) for item in messages]
        else:
            errors[str(field)] = [str(messages)]
    return errors
