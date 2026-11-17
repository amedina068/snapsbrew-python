"""Each error status maps to one error class under SnapsbrewError."""

from __future__ import annotations

import httpx
import pytest
import respx

from snapsbrew import (
    IDEMPOTENCY_KEY_BELONGS_TO_BATCH,
    IDEMPOTENCY_KEY_BELONGS_TO_SNAP,
    IDEMPOTENCY_KEY_IN_PROGRESS,
    INTERNAL_ERROR,
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncSnapsbrew,
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ServerError,
    Snapsbrew,
    SnapsbrewError,
    Text,
    ValidationError,
)
from tests.conftest import TEMPLATE_ID, create_with_key

# The bodies that the app sends at commit 4d008a5.
FORBIDDEN_BODY = {"message": "This action is unauthorized."}
INTERNAL_ERROR_BODY = {
    "message": (
        "The server could not create the snap. Try again later. If the error continues, "
        "contact support and give the X-Request-Uuid header of this response."
    ),
    "code": "internal_error",
}


@pytest.mark.parametrize(
    ("status", "error_class"),
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, AuthorizationError),
        (404, NotFoundError),
        (409, ConflictError),
        (418, APIError),
        (422, ValidationError),
        (429, RateLimitError),
        (500, ServerError),
        (503, ServerError),
    ],
)
def test_status_maps_to_error_class(
    status: int, error_class: type[APIError], api: respx.MockRouter
) -> None:
    api.get("/v1/auth").respond(
        status, json={"message": "Nope."}, headers={"X-Request-Uuid": "req-9"}
    )
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(error_class) as caught,
    ):
        client.whoami()
    error = caught.value
    assert type(error) is error_class
    assert isinstance(error, SnapsbrewError)
    assert error.status_code == status
    assert error.message == "Nope."
    assert error.request_id == "req-9"
    assert str(error) == f"{status}: Nope."


def test_validation_error_has_field_errors(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.post("/v1/snaps").respond(
        422,
        json={
            "message": "The template id field is required when collection id is not present.",
            "errors": {"template_id": ["The template id field is required."], "x": "flat"},
        },
    )
    with pytest.raises(ValidationError) as caught:
        client.snaps.create(TEMPLATE_ID)
    assert caught.value.errors == {
        "template_id": ["The template id field is required."],
        "x": ["flat"],
    }


def test_validation_error_without_errors_key(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get(f"/v1/guides/platforms/{'x' * 65}").respond(
        422, json={"message": "The platform field must not be greater than 64 characters."}
    )
    with pytest.raises(ValidationError) as caught:
        client.guides.platform("x" * 65)
    assert caught.value.errors == {}


def test_rate_limit_error_has_retry_after_and_the_limit(api: respx.MockRouter) -> None:
    api.get("/v1/snaps/preview").respond(
        429,
        json={"message": "Too Many Attempts."},
        headers={"Retry-After": "42", "X-RateLimit-Limit": "10", "X-RateLimit-Remaining": "0"},
    )
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(RateLimitError) as caught,
    ):
        client.snaps.preview(TEMPLATE_ID)
    assert caught.value.retry_after == 42.0
    assert caught.value.limit == 10
    assert caught.value.remaining == 0


def test_rate_limit_error_without_limit_headers(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/auth").respond(429, headers={"Retry-After": "3600", "X-RateLimit-Limit": "x"})
    with pytest.raises(RateLimitError) as caught:
        client.whoami()
    assert caught.value.limit is None
    assert caught.value.remaining is None


def test_a_403_on_snap_create_is_an_authorization_error(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.post("/v1/snaps").respond(403, json=FORBIDDEN_BODY)
    with pytest.raises(AuthorizationError) as caught:
        client.snaps.create(TEMPLATE_ID, [Text("title", "Hi")], idempotency_key="k-1")
    assert caught.value.status_code == 403
    assert caught.value.message == "This action is unauthorized."
    assert route.call_count == 1


async def test_a_403_on_snap_create_is_an_authorization_error_async(
    aclient: AsyncSnapsbrew, api: respx.MockRouter
) -> None:
    api.post("/v1/snaps").respond(403, json=FORBIDDEN_BODY)
    with pytest.raises(AuthorizationError):
        await aclient.snaps.create(TEMPLATE_ID)


@pytest.mark.parametrize(
    ("path", "code", "retryable"),
    [
        ("/v1/snaps", IDEMPOTENCY_KEY_IN_PROGRESS, True),
        ("/v1/snaps", IDEMPOTENCY_KEY_BELONGS_TO_BATCH, False),
        ("/v1/snaps/batches", IDEMPOTENCY_KEY_IN_PROGRESS, True),
        ("/v1/snaps/batches", IDEMPOTENCY_KEY_BELONGS_TO_SNAP, False),
    ],
)
def test_a_409_conflict_error_has_the_code(
    path: str, code: str, retryable: bool, api: respx.MockRouter
) -> None:
    api.post(path).respond(
        409, json={"message": "Nothing was created.", "code": code}, headers={"X-Request-Uuid": "r"}
    )
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(ConflictError) as caught,
    ):
        create_with_key(client, path)
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert caught.value.message == "Nothing was created."
    assert caught.value.request_id == "r"


def test_the_conflict_codes_match_the_app() -> None:
    assert IDEMPOTENCY_KEY_IN_PROGRESS == "idempotency_key_in_progress"
    assert IDEMPOTENCY_KEY_BELONGS_TO_SNAP == "idempotency_key_belongs_to_snap"
    assert IDEMPOTENCY_KEY_BELONGS_TO_BATCH == "idempotency_key_belongs_to_batch"
    assert INTERNAL_ERROR == "internal_error"


def test_a_500_on_snap_create_is_a_server_error_with_the_generic_code(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.post("/v1/snaps").respond(
        500, json=INTERNAL_ERROR_BODY, headers={"X-Request-Uuid": "req-500"}
    )
    with pytest.raises(ServerError) as caught:
        client.snaps.create(TEMPLATE_ID)
    error = caught.value
    assert error.status_code == 500
    assert error.code == INTERNAL_ERROR
    assert error.message == INTERNAL_ERROR_BODY["message"]
    assert error.request_id == "req-500"
    assert str(error).startswith("500: The server could not create the snap.")
    # A POST without an idempotency key is not retried after a 5xx.
    assert route.call_count == 1


def test_a_500_on_batch_create_is_a_server_error_with_the_generic_code(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    body = {
        "message": "The server could not create the batch. Try again later. If the error "
        "continues, contact support and give the X-Request-Uuid header of this response.",
        "code": "internal_error",
    }
    route = api.post("/v1/snaps/batches").respond(
        500, json=body, headers={"X-Request-Uuid": "req-batch"}
    )
    with pytest.raises(ServerError) as caught:
        client.batches.create(TEMPLATE_ID, items=[[Text("title", "A")]])
    error = caught.value
    assert error.status_code == 500
    assert error.code == INTERNAL_ERROR
    assert error.message == body["message"]
    assert error.request_id == "req-batch"
    # A POST without an idempotency key is not retried after a 5xx.
    assert route.call_count == 1


def test_editor_style_code_is_kept(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/auth").respond(409, json={"code": "legacy_edit_rejected_for_v2"})
    with pytest.raises(ConflictError) as caught:
        client.whoami()
    assert caught.value.code == "legacy_edit_rejected_for_v2"
    assert caught.value.message == "legacy_edit_rejected_for_v2"


def test_a_non_json_error_body_uses_the_reason_phrase(api: respx.MockRouter) -> None:
    api.get("/v1/auth").respond(502, text="<html>Bad gateway</html>")
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(ServerError) as caught,
    ):
        client.whoami()
    assert caught.value.message == "Bad Gateway"
    assert caught.value.body == "<html>Bad gateway</html>"


def test_connection_error(api: respx.MockRouter) -> None:
    api.get("/v1/auth").mock(side_effect=httpx.ConnectError("refused"))
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(APIConnectionError) as caught,
    ):
        client.whoami()
    assert not isinstance(caught.value, APITimeoutError)
    assert isinstance(caught.value.__cause__, httpx.ConnectError)


def test_timeout_error(api: respx.MockRouter) -> None:
    api.get("/v1/auth").mock(side_effect=httpx.ReadTimeout("slow"))
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(APITimeoutError),
    ):
        client.whoami()


def test_a_success_body_that_is_not_json_is_an_error(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.get("/v1/auth").respond(200, text="<html>login</html>")
    with pytest.raises(SnapsbrewError, match="base_url"):
        client.whoami()
