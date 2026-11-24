"""Verify the webhooks that Snapsbrew sends.

An async snap and a batch post a webhook to their ``webhook_url``. The
instance signs each request with the webhook signing secret of your company.
``X-Snapsbrew-Signature`` is the lowercase HMAC-SHA256 hex digest of
``{X-Snapsbrew-Timestamp}.{raw body}``.

Use this module only on a server. The webhook signing secret is a secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from snapsbrew.errors import WebhookVerificationError
from snapsbrew.models import Batch, Snap

__all__ = [
    "DEFAULT_TOLERANCE",
    "DELIVERY_HEADER",
    "SIGNATURE_HEADER",
    "SNAP_COMPLETED",
    "SNAP_FAILED",
    "SNAP_IMPORT_CANCELED",
    "SNAP_IMPORT_COMPLETED",
    "SNAP_IMPORT_FAILED",
    "TIMESTAMP_HEADER",
    "WebhookEvent",
    "sign",
    "verify_webhook",
]

DELIVERY_HEADER: Final = "X-Snapsbrew-Delivery"
TIMESTAMP_HEADER: Final = "X-Snapsbrew-Timestamp"
SIGNATURE_HEADER: Final = "X-Snapsbrew-Signature"

DEFAULT_TOLERANCE: Final = 300
"""The maximum distance of the timestamp from the current time, in seconds."""

SNAP_COMPLETED: Final = "snap.completed"
"""An async snap rendered. ``event.snap`` has the image URL."""

SNAP_FAILED: Final = "snap.failed"
"""An async snap did not render. ``event.snap.last_error`` is ``"render_failed"``."""

SNAP_IMPORT_COMPLETED: Final = "snap-import.completed"
"""A batch finished. ``event.batch`` has the counts. Read ``batch.failed`` too."""

SNAP_IMPORT_FAILED: Final = "snap-import.failed"
"""No item of a batch rendered."""

SNAP_IMPORT_CANCELED: Final = "snap-import.canceled"
"""A batch was canceled."""

_UNIX_SECONDS = re.compile(r"[0-9]+")
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")


class Headers(Protocol):
    """A header object with a ``get()`` method, for example ``request.headers``."""

    def get(self, key: str, /) -> str | None: ...


@dataclass(frozen=True)
class WebhookEvent:
    """A webhook that passed the verification.

    Attributes:
        type: The ``event`` field of the body, for example :data:`SNAP_COMPLETED`.
            A new instance version can send a type that this package does not know.
        delivery_id: The ``X-Snapsbrew-Delivery`` header. All attempts of one
            delivery have the same value. Keep it to ignore a duplicate. It is
            ``None`` when an older instance sends no delivery header.
        timestamp: The ``X-Snapsbrew-Timestamp`` header, in Unix seconds.
        data: The decoded body.
    """

    type: str
    delivery_id: str | None
    timestamp: int
    data: Mapping[str, Any] = field(repr=False)

    @property
    def snap(self) -> Snap | None:
        """The snap of a ``snap.*`` event, else ``None``."""
        snap = self.data.get("snap")
        return Snap.from_dict(snap) if isinstance(snap, dict) else None

    @property
    def batch(self) -> Batch | None:
        """The batch counts of a ``snap-import.*`` event, else ``None``.

        The body also has ``data["template"]``, with the ``uuid`` and the
        ``title`` of the template. Both are ``None`` when the template is gone.
        """
        batch = self.data.get("import")
        return Batch.from_dict(batch) if isinstance(batch, dict) else None


def verify_webhook(
    payload: bytes | str,
    headers: Mapping[str, str] | Headers,
    secret: str,
    *,
    tolerance: int = DEFAULT_TOLERANCE,
    now: float | None = None,
) -> WebhookEvent:
    """Verify one webhook and return the event.

    Example::

        event = verify_webhook(request.body, request.headers, settings.SNAPSBREW_WEBHOOK_SECRET)
        if event.type == SNAP_COMPLETED:
            print(event.snap.media_url)

    Args:
        payload: The raw request body, byte for byte. Do not decode the JSON and
            encode it again. The instance escapes ``/`` and non-ASCII
            characters, so a new encoding gives other bytes.
        headers: The request headers. The names are not case-sensitive.
        secret: The webhook signing secret of your company, with its
            ``whsec_`` prefix.
        tolerance: The maximum distance of the timestamp from the current
            time, in seconds. The default is 300.
        now: The current Unix time. The default is ``time.time()``. Tests use it.

    Raises:
        WebhookVerificationError: Read ``reason``: ``"signature"``,
            ``"timestamp"`` or ``"payload"``.
        ValueError: ``secret`` is empty, or ``tolerance`` is less than 0.
    """
    if not secret:
        raise ValueError("secret must be the webhook signing secret of your company")
    if tolerance < 0:
        raise ValueError("tolerance must be 0 or more seconds")

    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    signature = _header(headers, SIGNATURE_HEADER)
    timestamp = _header(headers, TIMESTAMP_HEADER)

    if signature is None:
        raise WebhookVerificationError(
            f"The {SIGNATURE_HEADER} header is missing.", reason="signature"
        )
    if timestamp is None or not _UNIX_SECONDS.fullmatch(timestamp):
        raise WebhookVerificationError(
            f"The {TIMESTAMP_HEADER} header is missing or is not Unix seconds.",
            reason="timestamp",
        )
    # Check the format first, so that compare_digest gets two ASCII strings.
    received = signature.lower()
    if not _HEX_DIGEST.fullmatch(received) or not hmac.compare_digest(
        sign(timestamp, body, secret), received
    ):
        raise WebhookVerificationError(
            "The signature does not match. Use the raw body and the secret of your company.",
            reason="signature",
        )
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > tolerance:
        raise WebhookVerificationError(
            f"The timestamp is more than {tolerance} seconds from the current time.",
            reason="timestamp",
        )
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise WebhookVerificationError("The body is not a JSON object.", reason="payload")
    return WebhookEvent(
        type=str(data.get("event", "")),
        delivery_id=_header(headers, DELIVERY_HEADER),
        timestamp=int(timestamp),
        data=data,
    )


def sign(timestamp: str, payload: bytes | str, secret: str) -> str:
    """Return the ``X-Snapsbrew-Signature`` value for a timestamp and a raw body.

    Use it in a test to make a signed webhook.
    """
    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    message = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _header(headers: Mapping[str, str] | Headers, name: str) -> str | None:
    """Return the trimmed header value, or ``None`` when it is missing or empty."""
    value: Any = headers.get(name)
    if value is None and isinstance(headers, Mapping):
        wanted = name.lower()
        value = next((item for key, item in headers.items() if key.lower() == wanted), None)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
