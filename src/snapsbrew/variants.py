"""Variants: the per-layer changes that you apply to a template.

Each variant names one layer of the template and gives one change::

    from snapsbrew import Text, Image, BackgroundColor, Hidden

    variants = [
        Text("title", "Hello"),
        Image("cover", "https://example.com/cover.jpg"),
        BackgroundColor("bg", "#f0573f"),
        Hidden("badge"),
    ]

You can also give plain dicts, in the format of the API::

    variants = [{"layer": "title", "text": "Hello"}]
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

__all__ = [
    "BackgroundColor",
    "Barcode",
    "Hidden",
    "Image",
    "QRCode",
    "Text",
    "Variant",
    "VariantLike",
    "to_dicts",
]


@dataclass(frozen=True)
class Text:
    """Replace the content of a text layer."""

    layer: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "text": self.text}


@dataclass(frozen=True)
class Image:
    """Replace the image of an image layer. The URL must be public."""

    layer: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "image_url": self.url}


@dataclass(frozen=True)
class BackgroundColor:
    """Replace the background color of a layer, for example ``"#f0573f"``."""

    layer: str
    color: str

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "background_color": self.color}


@dataclass(frozen=True)
class QRCode:
    """Set the content of a QR code layer."""

    layer: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "qr_content": self.content}


@dataclass(frozen=True)
class Barcode:
    """Set the content of a barcode layer (1000 characters maximum)."""

    layer: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "barcode_content": self.content}


@dataclass(frozen=True)
class Hidden:
    """Remove a layer from the render."""

    layer: str

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "hidden": True}


Variant: TypeAlias = Text | Image | BackgroundColor | QRCode | Barcode | Hidden
"""One of the typed variant classes."""

VariantLike: TypeAlias = Variant | Mapping[str, Any]
"""A typed variant, or a dict in the format of the API."""

_VARIANT_TYPES = (Text, Image, BackgroundColor, QRCode, Barcode, Hidden)


def to_dicts(variants: Iterable[VariantLike] | None) -> list[dict[str, Any]]:
    """Convert typed variants and dicts to the list of dicts that the API reads.

    Raises:
        TypeError: An item is not a variant and not a mapping.
        ValueError: A dict has no string ``layer`` key.
    """
    if variants is None:
        return []
    if isinstance(variants, (str, bytes, Mapping)):
        raise TypeError("variants must be a list of variants, not a single value")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(variants):
        if isinstance(item, _VARIANT_TYPES):
            result.append(item.to_dict())
        elif isinstance(item, Mapping):
            if not isinstance(item.get("layer"), str):
                raise ValueError(f"variants[{index}] must have a string 'layer' key")
            result.append(dict(item))
        else:
            raise TypeError(
                f"variants[{index}] must be a variant (for example Text) or a dict, "
                f"not {type(item).__name__}"
            )
    return result
