"""Parts that the sync client and the async client share.

This module holds the settings, the request description, the retry rules and
the map from an error response to an error class. It does no I/O.
"""

from __future__ import annotations

import email.utils
import os
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import httpx

from snapsbrew._version import __version__
from snapsbrew.errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)

DEFAULT_TIMEOUT: Final = 30.0
DEFAULT_MAX_RETRIES: Final = 2

# The client does not wait longer than this for one Retry-After value. If the
# server asks for a longer wait, the client raises RateLimitError at once.
MAX_RETRY_AFTER: Final = 60.0

BACKOFF_BASE: Final = 0.5
BACKOFF_MAX: Final = 8.0

USER_AGENT: Final = f"snapsbrew-python/{__version__}"


class NotGiven:
    """The type of ``NOT_GIVEN``, a value that is different from ``None``."""

    def __repr__(self) -> str:
        return "NOT_GIVEN"

    def __bool__(self) -> bool:
        return False


NOT_GIVEN: Final = NotGiven()

TimeoutTypes = float | httpx.Timeout | None


@dataclass(frozen=True)
class RequestSpec:
    """One API request, before the client sends it.

    ``idempotent`` tells the retry logic that a second copy of the request is
    safe. The server does not do the action two times.
    """

    method: str
    path: str
    params: Sequence[tuple[str, str]] | None = None
    json: Any = None
    files: Mapping[str, tuple[str, bytes, str]] | None = None
    idempotent: bool = False


def normalize_base_url(base_url: str) -> str:
    """Return the instance URL with no trailing ``/`` and no trailing ``/api``."""
    url = base_url.strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"base_url must start with https:// or http://, not {base_url!r}")
    if url.endswith("/api"):
        url = url[: -len("/api")]
    return url


class BaseClient:
    """Settings and request building for one Snapsbrew instance."""

    def __init__(
        self,
        base_url: str | None,
        token: str | None,
        *,
        timeout: TimeoutTypes | NotGiven,
        max_retries: int,
    ) -> None:
        base_url = base_url or os.environ.get("SNAPSBREW_URL")
        token = token or os.environ.get("SNAPSBREW_TOKEN")
        if not base_url:
            raise ValueError(
                "Give the URL of your Snapsbrew instance as base_url, "
                "or set the SNAPSBREW_URL environment variable."
            )
        if not token:
            raise ValueError(
                "Give an API token as token, or set the SNAPSBREW_TOKEN environment variable."
            )
        if max_retries < 0:
            raise ValueError("max_retries must be 0 or more")
        self.base_url = normalize_base_url(base_url)
        self.max_retries = max_retries
        self._token = token
        self._timeout = timeout

    def __repr__(self) -> str:
        # Never show the token.
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    @property
    def _default_timeout(self) -> TimeoutTypes:
        return DEFAULT_TIMEOUT if isinstance(self._timeout, NotGiven) else self._timeout

    def _build_request(
        self, http: httpx.Client | httpx.AsyncClient, spec: RequestSpec
    ) -> httpx.Request:
        extra: dict[str, Any] = {}
        if not isinstance(self._timeout, NotGiven):
            extra["timeout"] = self._timeout
        return http.build_request(
            spec.method,
            f"{self.base_url}/api{spec.path}",
            params=list(spec.params) if spec.params else None,
            json=spec.json,
            files=dict(spec.files) if spec.files else None,
            headers={
                "Authorization": f"Bearer {self._token}",
                # Laravel sends JSON errors only when the request accepts JSON.
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            **extra,
        )


def backoff(attempt: int) -> float:
    """Return the wait before retry number ``attempt + 1``: exponential, with jitter."""
    ceiling = min(BACKOFF_MAX, BACKOFF_BASE * (2.0**attempt))
    return ceiling * random.uniform(0.5, 1.0)


def parse_retry_after(value: str | None) -> float | None:
    """Read a ``Retry-After`` header: a number of seconds or an HTTP date."""
    if value is None:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        moment = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, moment.timestamp() - time.time())


# The server did not receive the request. A retry is safe for every method.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

# The server can have received the request. Retry only an idempotent request.
_MAYBE_SENT = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


def transport_retry_delay(
    exc: httpx.TransportError, spec: RequestSpec, attempt: int, max_retries: int
) -> float | None:
    """Return the wait before a retry after a transport error, or ``None`` for no retry."""
    if attempt >= max_retries:
        return None
    if isinstance(exc, _NOT_SENT):
        return backoff(attempt)
    if spec.idempotent and isinstance(exc, _MAYBE_SENT):
        return backoff(attempt)
    return None


def response_retry_delay(
    response: httpx.Response, spec: RequestSpec, attempt: int, max_retries: int
) -> float | None:
    """Return the wait before a retry after an error response, or ``None`` for no retry.

    The client retries a 429 for every method, because the rate limiter refuses
    the request before the app does the action. The client retries a 5xx only
    for an idempotent request.
    """
    if attempt >= max_retries:
        return None
    status = response.status_code
    if status != 429 and not (status >= 500 and spec.idempotent):
        return None
    retry_after = parse_retry_after(response.headers.get("retry-after"))
    if retry_after is None:
        return backoff(attempt)
    if retry_after > MAX_RETRY_AFTER:
        return None
    return retry_after


def connection_error(exc: httpx.TransportError) -> APIConnectionError:
    """Convert an ``httpx`` transport error to an error of this package."""
    request = _request_of(exc)
    if isinstance(exc, httpx.TimeoutException):
        return APITimeoutError(f"The request timed out: {exc}", request=request)
    return APIConnectionError(f"The connection to the instance failed: {exc}", request=request)


def _request_of(exc: httpx.TransportError) -> httpx.Request | None:
    try:
        return exc.request
    except RuntimeError:
        return None


_ERRORS_BY_STATUS: Final[dict[int, type[APIError]]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: AuthorizationError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
}


def decode_body(response: httpx.Response) -> Any:
    """Return the JSON body, or the text body when the body is not JSON."""
    try:
        return response.json()
    except ValueError:
        return response.text


def error_from_response(response: httpx.Response) -> APIError:
    """Convert an error response to the matching error class."""
    body = decode_body(response)
    message = ""
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        message = body["message"]
    elif isinstance(body, dict) and isinstance(body.get("code"), str):
        message = body["code"]
    if not message:
        message = response.reason_phrase or f"HTTP {response.status_code}"

    status = response.status_code
    if status == 429:
        return RateLimitError(
            message,
            response=response,
            body=body,
            retry_after=parse_retry_after(response.headers.get("retry-after")),
        )
    if status >= 500:
        return ServerError(message, response=response, body=body)
    error_class = _ERRORS_BY_STATUS.get(status, APIError)
    return error_class(message, response=response, body=body)


def unwrap_data(body: Any) -> Any:
    """Return ``body["data"]`` when the body has the ``data`` envelope, else the body."""
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body
