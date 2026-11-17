"""Signed URLs: render an image from an ``<img src>`` or an ``og:image``, with no API call.

A signed URL carries the template, the variants and an HMAC-SHA256 signature.
The instance renders the image on the first request and caches it.

The signing key is a secret. Make signed URLs only on your server. Never send
the key to a browser.

The algorithm is the same as ``SignedUrlMiddleware`` in the Snapsbrew app:

1. Take all query parameters except ``signature``.
2. Sort them by key, in byte order.
3. Join them as ``key=value`` with ``&``. Use the raw values, not URL-encoded values.
4. The signature is the HMAC-SHA256 hex digest of that string, with the signing key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Iterable, Mapping
from typing import Literal
from urllib.parse import quote

from snapsbrew._base import normalize_base_url
from snapsbrew.variants import VariantLike, to_dicts

__all__ = ["build_signed_url", "canonical_string", "encode_variants", "sign", "signed_url"]

SIGNED_URL_PATH = "/signed-url/image.jpg"

ImageFormat = Literal["png", "jpeg", "webp"]

_FORMATS = ("png", "jpeg", "webp")

# The app adds these keys to the request itself, or removes them before it
# signs. A caller value for one of these keys breaks the signature.
_RESERVED_KEYS = frozenset({"signature", "identifier", "api_log_uuid", "template"})

# PHP changes "." and " " in a query key to "_", and it reads a key of only
# digits as an integer. Both change the string that the app signs.
_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

ParamValue = str | int | bool


def encode_variants(variants: Iterable[VariantLike]) -> str:
    """Encode variants as the ``variants`` query value.

    The value is standard base64 (with ``+``, ``/`` and ``=``) of the compact JSON
    array. The app decodes it with PHP ``base64_decode``, so URL-safe base64 does
    not work.
    """
    payload = json.dumps(to_dicts(variants), ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def canonical_string(params: Mapping[str, str]) -> str:
    """Return the string that the signature covers.

    The function removes ``signature``, sorts the keys in byte order and joins
    the raw ``key=value`` pairs with ``&``.
    """
    items = sorted(
        ((key, value) for key, value in params.items() if key != "signature"),
        key=lambda item: item[0].encode("utf-8"),
    )
    return "&".join(f"{key}={value}" for key, value in items)


def sign(params: Mapping[str, str], key: str) -> str:
    """Return the HMAC-SHA256 hex signature of ``params`` with the signing key."""
    message = canonical_string(params).encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signed_url(
    *,
    base_url: str,
    key: str,
    template_id: str,
    variants: Iterable[VariantLike] | None = None,
    format: ImageFormat | None = None,
    transparent: bool = False,
    params: Mapping[str, ParamValue] | None = None,
) -> str:
    """Build a signed image URL.

    Args:
        base_url: The URL of your Snapsbrew instance, for example
            ``"https://snapsbrew.example.com"``.
        key: The signing key. Get it from the signed URL keys page of the instance.
        template_id: The UUID of the template.
        variants: The per-layer changes. Typed variants or dicts.
        format: ``"png"`` (default), ``"jpeg"`` or ``"webp"``.
        transparent: Render on a transparent background. PNG and WebP only.
        params: Other query parameters. The renderer ignores them, but they are
            part of the signature and of the cache key. Use one to make a new
            image for the same content, for example ``{"v": "2"}``.

    Returns:
        The URL, with each value URL-encoded and the signature at the end.

    Raises:
        ValueError: An argument breaks a rule of the instance.
    """
    if not key:
        raise ValueError("key must not be empty")
    if not template_id:
        raise ValueError("template_id must not be empty")
    if format is not None and format not in _FORMATS:
        raise ValueError(f"format must be one of {', '.join(_FORMATS)}, not {format!r}")
    if transparent and format == "jpeg":
        raise ValueError("transparent is not possible with the jpeg format")

    query: dict[str, str] = {"template_id": template_id}
    if format is not None:
        query["format"] = format
    if transparent:
        query["transparent"] = "1"
    for name, value in (params or {}).items():
        query[_check_key(name, query)] = _param_value(name, value)
    if variants is not None:
        query["variants"] = encode_variants(variants)
    return build_signed_url(base_url, query, key)


def build_signed_url(base_url: str, params: Mapping[str, str], key: str) -> str:
    """Sign ``params`` and return the full URL. This function does no checks.

    The URL keeps the order of ``params`` and adds ``signature`` at the end.
    Each value is URL-encoded (RFC 3986), so ``+`` in base64 becomes ``%2B``.
    """
    query = {name: value for name, value in params.items() if name != "signature"}
    query["signature"] = sign(query, key)
    pairs = "&".join(f"{name}={quote(value, safe='')}" for name, value in query.items())
    return f"{normalize_base_url(base_url)}{SIGNED_URL_PATH}?{pairs}"


def _check_key(name: str, query: Mapping[str, str]) -> str:
    if name in _RESERVED_KEYS or name in {"template_id", "variants", "format", "transparent"}:
        raise ValueError(f"params must not contain the key {name!r}. Use the argument instead.")
    if not _KEY_PATTERN.fullmatch(name):
        raise ValueError(
            f"params key {name!r} must contain only letters, digits and underscores, "
            "and must not start with a digit"
        )
    if name in query:
        raise ValueError(f"params key {name!r} occurs two times")
    return name


def _param_value(name: str, value: ParamValue) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (str, int)):
        text = str(value)
        # The app trims each query value before it signs the string.
        if text != text.strip():
            raise ValueError(f"params value of {name!r} must not start or end with whitespace")
        return text
    raise TypeError(f"params value of {name!r} must be str, int or bool")
