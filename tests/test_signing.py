from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest

from snapsbrew import (
    BackgroundColor,
    Hidden,
    Image,
    Text,
    Variant,
    canonical_string,
    sign,
    signed_url,
)
from snapsbrew.signing import build_signed_url, encode_variants

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "signed-url-vectors.json").read_text(encoding="utf-8")
)
KEY: str = VECTORS["key"]
INSTANCE = VECTORS["base_url"].removesuffix("/signed-url/image.jpg")
CASES: list[dict[str, Any]] = VECTORS["cases"]
CASE_IDS = [case["name"] for case in CASES]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_canonical_string_matches_vector(case: dict[str, Any]) -> None:
    assert canonical_string(case["params"]) == case["canonical_string"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_signature_matches_vector(case: dict[str, Any]) -> None:
    assert sign(case["params"], KEY) == case["signature"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_url_matches_vector(case: dict[str, Any]) -> None:
    assert build_signed_url(INSTANCE, case["params"], KEY) == case["url"]


@pytest.mark.parametrize("case", [c for c in CASES if c["variants_json"]], ids=lambda c: c["name"])
def test_variants_encoding_matches_vector(case: dict[str, Any]) -> None:
    variants = json.loads(case["variants_json"])
    assert encode_variants(variants) == case["params"]["variants"]


def test_signed_url_with_typed_variants_matches_vector() -> None:
    url = signed_url(
        base_url=INSTANCE,
        key=KEY,
        template_id="044ec825-ee2f-4d06-bb77-98663e27f529",
        variants=[
            Text("title", "Dark Avengers"),
            Image("cover", "https://example.com/a/b.jpg?x=1&y=2"),
        ],
    )
    assert url == CASES[1]["url"]


def test_signed_url_with_dict_variants_matches_vector() -> None:
    url = signed_url(
        base_url=INSTANCE + "/",
        key=KEY,
        template_id="044ec825-ee2f-4d06-bb77-98663e27f529",
        variants=[
            {"layer": "title", "text": "Dark Avengers"},
            {"layer": "cover", "image_url": "https://example.com/a/b.jpg?x=1&y=2"},
        ],
    )
    assert url == CASES[1]["url"]


def test_signed_url_without_variants_matches_vector() -> None:
    url = signed_url(base_url=INSTANCE, key=KEY, template_id=CASES[0]["params"]["template_id"])
    assert url == CASES[0]["url"]


def test_unicode_variants_round_trip() -> None:
    variants: list[Variant] = [
        Text("headline", "¿Este sí es tu Hawkeye? 🏹"),
        Hidden("badge"),
        BackgroundColor("bg", "#f0573f"),
    ]
    assert encode_variants(variants) == CASES[2]["params"]["variants"]


def test_variants_use_standard_base64_and_url_encode_it() -> None:
    # This text gives "+" and "/" in base64. URL-safe base64 gives "-" and "_".
    variants = [Text("t", ">>>???")]
    encoded = encode_variants(variants)
    assert "+" in encoded or "/" in encoded
    assert base64.b64decode(encoded) == b'[{"layer":"t","text":">>>???"}]'
    url = signed_url(base_url=INSTANCE, key=KEY, template_id="abc", variants=variants)
    query = urlsplit(url).query
    assert "+" not in query
    assert dict(parse_qsl(query))["variants"] == encoded


def test_format_transparent_and_params_are_signed() -> None:
    url = signed_url(
        base_url=INSTANCE,
        key=KEY,
        template_id="abc",
        format="webp",
        transparent=True,
        params={"v": 2, "retina": True},
    )
    params = dict(parse_qsl(urlsplit(url).query))
    assert params["format"] == "webp"
    assert params["transparent"] == "1"
    assert params["v"] == "2"
    assert params["retina"] == "1"
    signature = params.pop("signature")
    assert sign(params, KEY) == signature
    assert url.endswith(f"&signature={signature}")


def test_base_url_with_api_suffix_is_accepted() -> None:
    url = signed_url(base_url=f"{INSTANCE}/api", key=KEY, template_id="abc")
    assert url.startswith(f"{INSTANCE}/signed-url/image.jpg?")


def test_canonical_string_sorts_by_byte_order() -> None:
    assert canonical_string({"b": "1", "_a": "2", "B": "3", "a": "4"}) == "B=3&_a=2&a=4&b=1"


def test_canonical_string_ignores_signature() -> None:
    assert canonical_string({"signature": "x", "a": "1"}) == "a=1"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"key": ""}, "key"),
        ({"template_id": ""}, "template_id"),
        ({"format": "jpg"}, "format"),
        ({"format": "jpeg", "transparent": True}, "transparent"),
        ({"params": {"signature": "x"}}, "signature"),
        ({"params": {"identifier": "x"}}, "identifier"),
        ({"params": {"format": "png"}}, "format"),
        ({"params": {"a.b": "x"}}, "a.b"),
        ({"params": {"10": "x"}}, "10"),
        ({"params": {"v": " 2"}}, "whitespace"),
    ],
)
def test_signed_url_rejects_values_that_break_the_signature(
    kwargs: dict[str, Any], message: str
) -> None:
    arguments: dict[str, Any] = {"base_url": INSTANCE, "key": KEY, "template_id": "abc"}
    arguments.update(kwargs)
    with pytest.raises(ValueError, match=message):
        signed_url(**arguments)


def test_signed_url_rejects_nested_param_values() -> None:
    with pytest.raises(TypeError):
        signed_url(base_url=INSTANCE, key=KEY, template_id="abc", params={"v": [1]})  # type: ignore[dict-item]


def test_signed_url_rejects_a_relative_base_url() -> None:
    with pytest.raises(ValueError, match="https://"):
        signed_url(base_url="snapsbrew.example", key=KEY, template_id="abc")
