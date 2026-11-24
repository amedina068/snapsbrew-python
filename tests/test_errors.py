"""Each error status maps to one error class under SnapsbrewError."""

from __future__ import annotations

from collections.abc import Callable

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
        client.account()
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
        client.account()
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
        client.account()
    assert caught.value.code == "legacy_edit_rejected_for_v2"
    assert caught.value.message == "legacy_edit_rejected_for_v2"


def test_a_non_json_error_body_uses_the_reason_phrase(api: respx.MockRouter) -> None:
    api.get("/v1/auth").respond(502, text="<html>Bad gateway</html>")
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(ServerError) as caught,
    ):
        client.account()
    assert caught.value.message == "Bad Gateway"
    assert caught.value.body == "<html>Bad gateway</html>"


def test_connection_error(api: respx.MockRouter) -> None:
    api.get("/v1/auth").mock(side_effect=httpx.ConnectError("refused"))
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(APIConnectionError) as caught,
    ):
        client.account()
    assert not isinstance(caught.value, APITimeoutError)
    assert isinstance(caught.value.__cause__, httpx.ConnectError)


def test_timeout_error(api: respx.MockRouter) -> None:
    api.get("/v1/auth").mock(side_effect=httpx.ReadTimeout("slow"))
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(APITimeoutError),
    ):
        client.account()


def test_a_success_body_that_is_not_json_is_an_error(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.get("/v1/auth").respond(200, text="<html>login</html>")
    with pytest.raises(SnapsbrewError, match="base_url"):
        client.account()


# The body of a 403 for a token without the `api_requests` ability.
INVALID_ABILITY_BODY = {"message": "Invalid ability provided."}

DOCUMENT = {"version": 2, "layers": [], "groups": []}

# Each bearer operation of the sync client, as (method, path, call).
BEARER_OPERATIONS: list[tuple[str, str, Callable[[Snapsbrew], object]]] = [
    ("GET", "/v1/auth", lambda c: c.account()),
    ("GET", "/v1/templates", lambda c: c.templates.list()),
    ("GET", "/v1/templates/sizes", lambda c: c.templates.sizes()),
    ("GET", f"/v1/templates/{TEMPLATE_ID}", lambda c: c.templates.get(TEMPLATE_ID)),
    ("POST", "/v1/templates", lambda c: c.templates.create("T", size="open_graph")),
    ("PATCH", f"/v1/templates/{TEMPLATE_ID}", lambda c: c.templates.update(TEMPLATE_ID, title="T")),
    ("DELETE", f"/v1/templates/{TEMPLATE_ID}", lambda c: c.templates.delete(TEMPLATE_ID)),
    ("POST", f"/v1/templates/{TEMPLATE_ID}/publish", lambda c: c.templates.publish(TEMPLATE_ID)),
    ("GET", f"/v1/templates/{TEMPLATE_ID}/preview", lambda c: c.templates.preview(TEMPLATE_ID)),
    ("POST", f"/v1/templates/{TEMPLATE_ID}/tags", lambda c: c.templates.set_tags(TEMPLATE_ID, [])),
    ("GET", f"/v1/templates/{TEMPLATE_ID}/document", lambda c: c.documents.get(TEMPLATE_ID)),
    (
        "PUT",
        f"/v1/templates/{TEMPLATE_ID}/document",
        lambda c: c.documents.replace(TEMPLATE_ID, revision=0, document=DOCUMENT),
    ),
    (
        "PATCH",
        f"/v1/templates/{TEMPLATE_ID}/document",
        lambda c: c.documents.apply(TEMPLATE_ID, revision=0, operations=[]),
    ),
    (
        "GET",
        f"/v1/templates/{TEMPLATE_ID}/document/preflight",
        lambda c: c.documents.preflight(TEMPLATE_ID),
    ),
    ("POST", "/v1/snaps", lambda c: c.snaps.create(TEMPLATE_ID)),
    ("GET", "/v1/snaps/preview", lambda c: c.snaps.preview(TEMPLATE_ID)),
    ("POST", "/v1/snaps/batches", lambda c: c.batches.create(TEMPLATE_ID, [[Text("t", "x")]])),
    ("GET", "/v1/snaps/batches/b1", lambda c: c.batches.get("b1")),
    ("POST", "/v1/snaps/batches/b1/cancel", lambda c: c.batches.cancel("b1")),
    ("GET", "/v1/screenshots", lambda c: c.screenshots.list()),
    ("GET", "/v1/screenshots/s1", lambda c: c.screenshots.get("s1")),
    ("POST", "/v1/screenshots", lambda c: c.screenshots.create("https://example.com")),
    ("GET", "/v1/media", lambda c: c.media.list()),
    ("POST", "/v1/media", lambda c: c.media.upload(b"x", filename="a.png")),
    ("GET", "/v1/tags", lambda c: c.tags.list()),
    ("POST", "/v1/tags", lambda c: c.tags.create("Launch")),
    ("GET", "/v1/guides/design", lambda c: c.guides.design()),
    ("GET", "/v1/guides/layers", lambda c: c.guides.layers()),
    ("GET", "/v1/guides/variant-properties", lambda c: c.guides.variant_properties()),
    ("GET", "/v1/guides/editor-document", lambda c: c.guides.editor_document()),
    ("GET", "/v1/guides/platforms", lambda c: c.guides.platforms()),
    ("GET", "/v1/guides/platforms/instagram", lambda c: c.guides.platform("instagram")),
    ("GET", "/v1/guides/purposes", lambda c: c.guides.purposes()),
    ("GET", "/v1/guides/purposes/link_preview", lambda c: c.guides.purpose("link_preview")),
]


@pytest.mark.parametrize(
    ("method", "path", "call"),
    BEARER_OPERATIONS,
    ids=[f"{method} {path}" for method, path, _ in BEARER_OPERATIONS],
)
def test_a_403_is_an_authorization_error_on_every_operation(
    method: str,
    path: str,
    call: Callable[[Snapsbrew], object],
    client: Snapsbrew,
    api: respx.MockRouter,
) -> None:
    route = api.route(method=method, path=path).respond(403, json=INVALID_ABILITY_BODY)
    with pytest.raises(AuthorizationError) as caught:
        call(client)
    assert caught.value.message == "Invalid ability provided."
    # A 403 is final. The client does not retry it.
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("path", "call"),
    [
        ("/v1/templates", lambda c: c.templates.list(cursor="bad")),
        ("/v1/screenshots", lambda c: c.screenshots.list(cursor="bad")),
    ],
)
def test_a_bad_cursor_is_a_validation_error(
    path: str, call: Callable[[Snapsbrew], object], client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.get(path).respond(
        422, json={"message": "The cursor is not valid.", "errors": {"cursor": ["Not valid."]}}
    )
    with pytest.raises(ValidationError) as caught:
        call(client)
    assert caught.value.errors == {"cursor": ["Not valid."]}


@pytest.mark.parametrize(
    "message",
    ["No query results for model [App\\Models\\Template].", "Not Found", ""],
)
def test_a_404_is_not_found_whatever_the_message(
    message: str, client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.get(f"/v1/templates/{TEMPLATE_ID}").respond(404, json={"message": message})
    with pytest.raises(NotFoundError) as caught:
        client.templates.get(TEMPLATE_ID)
    assert caught.value.available == []


@pytest.mark.parametrize(
    ("path", "call"),
    [
        ("/v1/guides/platforms/myspace", lambda c: c.guides.platform("myspace")),
        ("/v1/guides/purposes/myspace", lambda c: c.guides.purpose("myspace")),
    ],
)
def test_a_guide_404_has_the_available_keys(
    path: str, call: Callable[[Snapsbrew], object], client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.get(path).respond(
        404,
        json={"message": "No platform guide matches `myspace`.", "available": ["instagram", "x"]},
    )
    with pytest.raises(NotFoundError) as caught:
        call(client)
    assert caught.value.available == ["instagram", "x"]
    assert caught.value.message == "No platform guide matches `myspace`."


def test_a_conflict_without_document_fields(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.post("/v1/snaps").respond(409, json={"code": IDEMPOTENCY_KEY_BELONGS_TO_BATCH})
    with pytest.raises(ConflictError) as caught:
        client.snaps.create(TEMPLATE_ID, idempotency_key="k")
    assert caught.value.current_revision is None
    assert caught.value.current_document is None
