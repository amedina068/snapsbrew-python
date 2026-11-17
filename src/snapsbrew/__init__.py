"""Python client for the Snapsbrew image rendering API.

Example::

    from snapsbrew import Snapsbrew, Text, Image

    client = Snapsbrew(base_url="https://snapsbrew.example.com", token="...")
    snap = client.snaps.create(
        "044ec825-ee2f-4d06-bb77-98663e27f529",
        variants=[Text("title", "Hello"), Image("cover", "https://example.com/a.jpg")],
    )
    print(snap.media_url)
"""

from snapsbrew._client import AsyncSnapsbrew, Snapsbrew
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
    SnapsbrewError,
    ValidationError,
    WaitTimeoutError,
)
from snapsbrew.models import (
    Account,
    Batch,
    BatchItem,
    Layer,
    Media,
    MediaPage,
    Page,
    Screenshot,
    Snap,
    Template,
    TemplateSize,
)
from snapsbrew.signing import canonical_string, encode_variants, sign, signed_url
from snapsbrew.variants import (
    BackgroundColor,
    Barcode,
    Hidden,
    Image,
    QRCode,
    Text,
    Variant,
    VariantLike,
)

__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "Account",
    "AsyncSnapsbrew",
    "AuthenticationError",
    "AuthorizationError",
    "BackgroundColor",
    "BadRequestError",
    "Barcode",
    "Batch",
    "BatchItem",
    "ConflictError",
    "Hidden",
    "Image",
    "Layer",
    "Media",
    "MediaPage",
    "NotFoundError",
    "Page",
    "QRCode",
    "RateLimitError",
    "Screenshot",
    "ServerError",
    "Snap",
    "Snapsbrew",
    "SnapsbrewError",
    "Template",
    "TemplateSize",
    "Text",
    "ValidationError",
    "Variant",
    "VariantLike",
    "WaitTimeoutError",
    "__version__",
    "canonical_string",
    "encode_variants",
    "sign",
    "signed_url",
]
