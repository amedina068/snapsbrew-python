"""Retry rules: 429, 5xx and connection errors, with backoff and Retry-After."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
import respx

from snapsbrew import (
    APIConnectionError,
    APITimeoutError,
    AsyncSnapsbrew,
    RateLimitError,
    ServerError,
    Snapsbrew,
    ValidationError,
)
from snapsbrew._base import BACKOFF_MAX, backoff, parse_retry_after
from tests.conftest import BATCH_BODY, SNAP_BODY, TEMPLATE_ID, SleepRecorder

AUTH_BODY = {"data": {"email": "a@b.c", "name": "Ada"}}


def ok_auth() -> httpx.Response:
    return httpx.Response(200, json=AUTH_BODY)


def test_get_retries_a_5xx_then_succeeds(
    client: Snapsbrew, api: respx.MockRouter, sleeps: SleepRecorder
) -> None:
    route = api.get("/v1/auth").mock(
        side_effect=[httpx.Response(503), httpx.Response(500), ok_auth()]
    )
    assert client.whoami().name == "Ada"
    assert route.call_count == 3
    assert len(sleeps.delays) == 2


def test_retries_stop_at_max_retries(
    client: Snapsbrew, api: respx.MockRouter, sleeps: SleepRecorder
) -> None:
    route = api.get("/v1/auth").respond(500)
    with pytest.raises(ServerError):
        client.whoami()
    assert route.call_count == 3
    assert len(sleeps.delays) == 2


def test_max_retries_zero_sends_once(api: respx.MockRouter) -> None:
    route = api.get("/v1/auth").respond(500)
    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(ServerError),
    ):
        client.whoami()
    assert route.call_count == 1


def test_post_is_not_retried_on_5xx(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/snaps").respond(500, json={"message": "Render failed."})
    with pytest.raises(ServerError):
        client.snaps.create(TEMPLATE_ID)
    assert route.call_count == 1


def test_post_with_idempotency_key_is_retried_on_5xx(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.post("/v1/snaps").mock(
        side_effect=[httpx.Response(502), httpx.Response(201, json=SNAP_BODY)]
    )
    snap = client.snaps.create(TEMPLATE_ID, idempotency_key="k-1")
    assert snap.id == SNAP_BODY["id"]
    assert route.call_count == 2


def test_batch_cancel_is_retried_on_5xx(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post(f"/v1/snaps/batches/{BATCH_BODY['uuid']}/cancel").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=BATCH_BODY)]
    )
    client.batches.cancel(BATCH_BODY["uuid"])
    assert route.call_count == 2


def test_post_is_retried_on_429_with_retry_after(
    client: Snapsbrew, api: respx.MockRouter, sleeps: SleepRecorder
) -> None:
    route = api.post("/v1/snaps").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(201, json=SNAP_BODY),
        ]
    )
    client.snaps.create(TEMPLATE_ID)
    assert route.call_count == 2
    assert sleeps.delays == [3.0]


def test_429_with_a_long_retry_after_is_not_retried(
    client: Snapsbrew, api: respx.MockRouter, sleeps: SleepRecorder
) -> None:
    route = api.get("/v1/auth").respond(429, headers={"Retry-After": "3600"})
    with pytest.raises(RateLimitError) as caught:
        client.whoami()
    assert route.call_count == 1
    assert caught.value.retry_after == 3600.0
    assert sleeps.delays == []


def test_429_without_retry_after_uses_backoff(
    client: Snapsbrew, api: respx.MockRouter, sleeps: SleepRecorder
) -> None:
    api.get("/v1/auth").mock(side_effect=[httpx.Response(429), ok_auth()])
    client.whoami()
    assert len(sleeps.delays) == 1
    assert 0.25 <= sleeps.delays[0] <= 0.5


def test_post_is_retried_on_connect_error(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/snaps").mock(
        side_effect=[httpx.ConnectError("refused"), httpx.Response(201, json=SNAP_BODY)]
    )
    client.snaps.create(TEMPLATE_ID)
    assert route.call_count == 2


def test_post_is_not_retried_on_read_timeout(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/snaps").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(APITimeoutError):
        client.snaps.create(TEMPLATE_ID)
    assert route.call_count == 1


def test_get_is_retried_on_read_timeout(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.get("/v1/auth").mock(side_effect=[httpx.ReadTimeout("slow"), ok_auth()])
    client.whoami()
    assert route.call_count == 2


def test_post_is_not_retried_on_a_dropped_connection(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.post("/v1/screenshots").mock(side_effect=httpx.RemoteProtocolError("closed"))
    with pytest.raises(APIConnectionError):
        client.screenshots.create("https://example.com")
    assert route.call_count == 1


def test_media_upload_retry_sends_the_same_bytes(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/media").mock(
        side_effect=[
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"id": 1, "file_name": "a.png", "src": None}),
        ]
    )
    client.media.upload(b"image bytes", filename="a.png")
    assert route.call_count == 2
    assert b"image bytes" in route.calls[1].request.content


def test_validation_errors_are_never_retried(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.get("/v1/auth").respond(422, json={"message": "Bad."})
    with pytest.raises(ValidationError):
        client.whoami()
    assert route.call_count == 1


async def test_async_client_retries(
    aclient: AsyncSnapsbrew, api: respx.MockRouter, sleeps: SleepRecorder
) -> None:
    route = api.get("/v1/auth").mock(
        side_effect=[httpx.ConnectError("refused"), httpx.Response(503), ok_auth()]
    )
    assert (await aclient.whoami()).name == "Ada"
    assert route.call_count == 3
    assert len(sleeps.delays) == 2


async def test_async_post_is_not_retried_on_5xx(
    aclient: AsyncSnapsbrew, api: respx.MockRouter
) -> None:
    route = api.post("/v1/snaps").respond(500)
    with pytest.raises(ServerError):
        await aclient.snaps.create(TEMPLATE_ID)
    assert route.call_count == 1


def test_backoff_grows_and_has_a_ceiling() -> None:
    for attempt in range(10):
        delay = backoff(attempt)
        ceiling = min(BACKOFF_MAX, 0.5 * 2**attempt)
        assert ceiling / 2 <= delay <= ceiling


def test_parse_retry_after() -> None:
    assert parse_retry_after(None) is None
    assert parse_retry_after("7") == 7.0
    assert parse_retry_after("-3") == 0.0
    assert parse_retry_after("soon") is None
    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    parsed = parse_retry_after(format_datetime(future, usegmt=True))
    assert parsed is not None
    assert 25 <= parsed <= 31
