"""Each error status maps to one error class under SnapsbrewError."""

from __future__ import annotations

import httpx
import pytest
import respx

from snapsbrew import (
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
    Snapsbrew,
    SnapsbrewError,
    ValidationError,
)
from tests.conftest import TEMPLATE_ID


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


def test_rate_limit_error_has_retry_after(api: respx.MockRouter) -> None:
    api.get("/v1/snaps/preview").respond(
        429, json={"message": "Too Many Attempts."}, headers={"Retry-After": "42"}
    )
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(RateLimitError) as caught,
    ):
        client.snaps.preview(TEMPLATE_ID)
    assert caught.value.retry_after == 42.0


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
