"""Webhook verification, with the vectors of the app (webhook-vectors.json)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from snapsbrew import (
    RENDER_FAILED,
    SNAP_COMPLETED,
    SNAP_FAILED,
    SNAP_IMPORT_CANCELED,
    SNAP_IMPORT_COMPLETED,
    SNAP_IMPORT_FAILED,
    WebhookEvent,
    WebhookVerificationError,
    verify_webhook,
)
from snapsbrew.webhooks import DEFAULT_TOLERANCE, sign

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "webhook-vectors.json").read_text("utf-8")
)
SECRET: str = VECTORS["secret"]
NOW: int = VECTORS["now"]
CASES: list[dict[str, Any]] = VECTORS["cases"]
VALID = [case for case in CASES if case["valid"]]
INVALID = [case for case in CASES if not case["valid"]]
DELIVERY_ID = "3f2b6c1e-8a4d-4e5f-9b0a-1c2d3e4f5a6b"


def case_named(name: str) -> dict[str, Any]:
    return next(case for case in CASES if case["name"] == name)


def signed_headers(body: str, timestamp: str) -> dict[str, str]:
    return {
        "X-Snapsbrew-Delivery": DELIVERY_ID,
        "X-Snapsbrew-Timestamp": timestamp,
        "X-Snapsbrew-Signature": sign(timestamp, body, SECRET),
    }


def test_the_vectors_have_valid_and_invalid_cases() -> None:
    assert len(VALID) == 7
    assert len(INVALID) == 11
    assert VECTORS["tolerance_seconds"] == DEFAULT_TOLERANCE


@pytest.mark.parametrize("case", VALID, ids=[case["name"] for case in VALID])
def test_valid_vector_is_accepted(case: dict[str, Any]) -> None:
    event = verify_webhook(case["body"].encode("utf-8"), case["headers"], SECRET, now=NOW)
    assert isinstance(event, WebhookEvent)
    assert event.type == json.loads(case["body"])["event"]
    assert event.data == json.loads(case["body"])
    assert event.delivery_id == case["delivery_id"]
    assert event.timestamp == int(case["headers"]["X-Snapsbrew-Timestamp"])


@pytest.mark.parametrize("case", INVALID, ids=[case["name"] for case in INVALID])
def test_invalid_vector_is_refused(case: dict[str, Any]) -> None:
    with pytest.raises(WebhookVerificationError) as caught:
        verify_webhook(case["body"], case["headers"], SECRET, now=NOW)
    assert caught.value.reason == case["reason"]


@pytest.mark.parametrize("case", VALID[:3], ids=[case["name"] for case in VALID[:3]])
def test_sign_matches_the_app(case: dict[str, Any]) -> None:
    timestamp = case["headers"]["X-Snapsbrew-Timestamp"]
    assert case["signed_string"] == f"{timestamp}.{case['body']}"
    assert sign(timestamp, case["body"], SECRET) == case["headers"]["X-Snapsbrew-Signature"]


def test_a_body_encoded_again_fails() -> None:
    case = case_named("snap.completed")
    assert "\\/" in case["body"]
    assert "\\u00bf" in case["body"]
    encoded_again = json.dumps(json.loads(case["body"]), ensure_ascii=False)
    with pytest.raises(WebhookVerificationError):
        verify_webhook(encoded_again, case["headers"], SECRET, now=NOW)


def test_snap_completed_gives_the_snap() -> None:
    case = case_named("snap.completed")
    event = verify_webhook(case["body"], case["headers"], SECRET, now=NOW)
    assert event.type == SNAP_COMPLETED
    assert event.snap is not None
    assert event.snap.is_completed
    assert event.snap.template_title == "¿Launch card?"
    assert event.snap.media_url == "https://snapsbrew.example/storage/snaps/9f1c2d3e.png"
    assert event.batch is None


def test_snap_failed_gives_a_failed_snap_with_an_empty_media_url() -> None:
    case = case_named("snap.failed")
    event = verify_webhook(case["body"], case["headers"], SECRET, now=NOW)
    assert event.type == SNAP_FAILED
    assert event.snap is not None
    assert event.snap.status == "failed"
    assert event.snap.last_error == RENDER_FAILED
    # The app sends an empty string. The SDK gives it as it is, as the other SDKs do.
    assert event.snap.media_url == ""


def test_snap_import_gives_the_batch_counts_and_the_template() -> None:
    case = case_named("snap-import.completed")
    event = verify_webhook(case["body"], case["headers"], SECRET, now=NOW)
    assert event.type == SNAP_IMPORT_COMPLETED
    assert event.snap is None
    assert event.batch is not None
    assert event.batch.uuid == "7c1f2a9e-0b44-4a1e-9f2b-5d3c8e1a7b60"
    assert event.batch.completed == 2
    assert event.batch.is_finished
    assert event.data["template"]["title"] == "Launch card"


def test_the_event_type_constants_match_the_app() -> None:
    assert (SNAP_IMPORT_FAILED, SNAP_IMPORT_CANCELED) == (
        "snap-import.failed",
        "snap-import.canceled",
    )


def test_header_names_are_not_case_sensitive() -> None:
    case = VALID[0]
    headers = {name.lower(): value for name, value in case["headers"].items()}
    assert verify_webhook(case["body"], headers, SECRET, now=NOW).delivery_id == DELIVERY_ID


def test_headers_with_a_get_method_work() -> None:
    class Headers:
        """A case-insensitive header object, like the one of Django or Starlette."""

        def __init__(self, values: dict[str, str]) -> None:
            self._values = {name.lower(): value for name, value in values.items()}

        def get(self, name: str) -> str | None:
            return self._values.get(name.lower())

    case = VALID[0]
    event = verify_webhook(case["body"], Headers(case["headers"]), SECRET, now=NOW)
    assert event.type == SNAP_COMPLETED


@pytest.mark.parametrize(
    ("missing", "reason"),
    [
        ("X-Snapsbrew-Signature", "signature"),
        ("X-Snapsbrew-Timestamp", "timestamp"),
    ],
)
def test_a_missing_header_is_refused(missing: str, reason: str) -> None:
    case = VALID[0]
    headers = {name: value for name, value in case["headers"].items() if name != missing}
    with pytest.raises(WebhookVerificationError) as caught:
        verify_webhook(case["body"], headers, SECRET, now=NOW)
    assert caught.value.reason == reason


@pytest.mark.parametrize("timestamp", ["yesterday", "-1", "1.5", ""])
def test_a_timestamp_that_is_not_unix_seconds_is_refused(timestamp: str) -> None:
    body = '{"event":"snap.completed"}'
    with pytest.raises(WebhookVerificationError) as caught:
        verify_webhook(body, signed_headers(body, timestamp), SECRET, now=NOW)
    assert caught.value.reason == "timestamp"


@pytest.mark.parametrize("signature", ["é", "sha256=abc", "", "0" * 63])
def test_a_malformed_signature_is_refused(signature: str) -> None:
    case = VALID[0]
    headers = {**case["headers"], "X-Snapsbrew-Signature": signature}
    with pytest.raises(WebhookVerificationError) as caught:
        verify_webhook(case["body"], headers, SECRET, now=NOW)
    assert caught.value.reason == "signature"


@pytest.mark.parametrize("offset", [DEFAULT_TOLERANCE + 1, -(DEFAULT_TOLERANCE + 1)])
def test_a_timestamp_outside_the_tolerance_is_refused(offset: int) -> None:
    case = VALID[0]
    with pytest.raises(WebhookVerificationError) as caught:
        verify_webhook(case["body"], case["headers"], SECRET, now=NOW + offset)
    assert caught.value.reason == "timestamp"


@pytest.mark.parametrize("offset", [DEFAULT_TOLERANCE, -DEFAULT_TOLERANCE])
def test_the_tolerance_limit_is_inclusive(offset: int) -> None:
    case = VALID[0]
    assert verify_webhook(case["body"], case["headers"], SECRET, now=NOW + offset)


def test_the_tolerance_is_a_setting() -> None:
    case = VALID[0]
    assert verify_webhook(case["body"], case["headers"], SECRET, tolerance=600, now=NOW + 600)
    with pytest.raises(WebhookVerificationError):
        verify_webhook(case["body"], case["headers"], SECRET, tolerance=10, now=NOW + 11)


def test_the_signature_is_checked_before_the_timestamp() -> None:
    case = case_named("signed with another secret")
    with pytest.raises(WebhookVerificationError) as caught:
        verify_webhook(case["body"], case["headers"], SECRET, now=NOW + 3600)
    assert caught.value.reason == "signature"


def test_the_default_now_is_the_current_time() -> None:
    body = '{"event":"snap-import.canceled","import":{},"template":{}}'
    event = verify_webhook(body, signed_headers(body, str(int(time.time()))), SECRET)
    assert event.type == SNAP_IMPORT_CANCELED


def test_an_unknown_event_type_is_accepted() -> None:
    body = '{"event":"snap.archived","snap":{"id":"x"}}'
    event = verify_webhook(body, signed_headers(body, str(NOW)), SECRET, now=NOW)
    assert event.type == "snap.archived"


@pytest.mark.parametrize(
    ("secret", "tolerance", "message"), [("", 300, "secret"), (SECRET, -1, "tolerance")]
)
def test_bad_arguments_raise_value_error(secret: str, tolerance: int, message: str) -> None:
    case = VALID[0]
    with pytest.raises(ValueError, match=message):
        verify_webhook(case["body"], case["headers"], secret, tolerance=tolerance, now=NOW)


def test_a_missing_delivery_header_gives_none() -> None:
    case = VALID[0]
    headers = {k: v for k, v in case["headers"].items() if k != "X-Snapsbrew-Delivery"}
    assert verify_webhook(case["body"], headers, SECRET, now=NOW).delivery_id is None


def test_a_header_list_gives_its_first_value() -> None:
    case = VALID[0]
    headers: Any = {name: [value] for name, value in case["headers"].items()}
    assert verify_webhook(case["body"], headers, SECRET, now=NOW).delivery_id == DELIVERY_ID


@pytest.mark.parametrize("body", ["{", "[]", '"text"', "\xff"])
def test_a_body_that_is_not_a_json_object_fails_on_the_payload(body: str) -> None:
    with pytest.raises(WebhookVerificationError) as caught:
        verify_webhook(body, signed_headers(body, str(NOW)), SECRET, now=NOW)
    assert caught.value.reason == "payload"
