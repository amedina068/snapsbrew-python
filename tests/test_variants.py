from __future__ import annotations

from typing import Any

import pytest

from snapsbrew import BackgroundColor, Barcode, Hidden, Image, QRCode, Text
from snapsbrew.variants import to_dicts


def test_typed_variants_convert_to_api_dicts() -> None:
    assert to_dicts(
        [
            Text("title", "Hello"),
            Image("cover", "https://example.com/a.jpg"),
            BackgroundColor("bg", "#fff"),
            QRCode("qr", "https://example.com"),
            Barcode("code", "4006381333931"),
            Hidden("badge"),
        ]
    ) == [
        {"layer": "title", "text": "Hello"},
        {"layer": "cover", "image_url": "https://example.com/a.jpg"},
        {"layer": "bg", "background_color": "#fff"},
        {"layer": "qr", "qr_content": "https://example.com"},
        {"layer": "code", "barcode_content": "4006381333931"},
        {"layer": "badge", "hidden": True},
    ]


def test_plain_dicts_pass_through() -> None:
    assert to_dicts([{"layer": "title", "text": "Hi"}, Text("sub", "There")]) == [
        {"layer": "title", "text": "Hi"},
        {"layer": "sub", "text": "There"},
    ]


def test_none_gives_an_empty_list() -> None:
    assert to_dicts(None) == []


def test_variants_are_frozen() -> None:
    variant = Text("title", "Hello")
    with pytest.raises(AttributeError):
        variant.text = "Other"  # type: ignore[misc]


@pytest.mark.parametrize("value", [{"layer": "x", "text": "y"}, "title"])
def test_a_single_value_is_rejected(value: Any) -> None:
    with pytest.raises(TypeError, match="list"):
        to_dicts(value)


def test_a_dict_without_layer_is_rejected() -> None:
    with pytest.raises(ValueError, match="layer"):
        to_dicts([{"text": "Hello"}])


def test_an_unknown_item_is_rejected() -> None:
    with pytest.raises(TypeError, match="int"):
        to_dicts([1])  # type: ignore[list-item]
