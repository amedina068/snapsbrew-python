"""Embedded forms: the signed submit URL, multipart layers and the retry rules."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from snapsbrew import AsyncSnapsbrew, NotFoundError, RateLimitError, ServerError, Snap, Snapsbrew
from tests.conftest import API, SNAP_BODY, SleepRecorder

FORM_PATH = "/v1/embedded-forms/5c2a9e1f-0b44-4a1e-9f2b-5d3c8e1a7b60"
FORM_URL = f"{API}{FORM_PATH}?signature=0f3a9c"


def body_of(route: respx.Route) -> bytes:
    return route.calls.last.request.read()


def test_a_template_form_returns_one_snap(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post(FORM_PATH).respond(201, json=SNAP_BODY)

    snap = client.forms.submit(FORM_URL, {"headline": "Hello"})

    assert isinstance(snap, Snap)
    assert snap.id == SNAP_BODY["id"]
    request = route.calls.last.request
    assert request.url.params["signature"] == "0f3a9c"
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="layers[headline]"\r\n\r\nHello\r\n' in body_of(route)


def test_a_collection_form_returns_a_list(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.post(FORM_PATH).respond(201, json=[SNAP_BODY, {**SNAP_BODY, "id": "4b8a7c6d"}])

    snaps = client.forms.submit(FORM_URL, {"141e8454__headline": "Hello"})

    assert isinstance(snaps, list)
    assert [snap.id for snap in snaps] == [SNAP_BODY["id"], "4b8a7c6d"]


def test_an_image_layer_is_a_file(client: Snapsbrew, api: respx.MockRouter, tmp_path: Path) -> None:
    route = api.post(FORM_PATH).respond(201, json=SNAP_BODY)
    photo = tmp_path / "photo.png"
    photo.write_bytes(b"PNG-BYTES")

    client.forms.submit(FORM_URL, {"photo": photo})

    sent = body_of(route)
    assert b'name="layers[photo]"; filename="photo.png"' in sent
    assert b"Content-Type: image/png\r\n\r\nPNG-BYTES\r\n" in sent


def test_the_form_gets_no_token(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post(FORM_PATH).respond(201, json=SNAP_BODY)

    client.forms.submit(FORM_URL, {"headline": "Hello"})

    assert "authorization" not in route.calls.last.request.headers


def test_a_client_with_no_token_submits_a_form(
    api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SNAPSBREW_TOKEN", raising=False)
    route = api.post(FORM_PATH).respond(201, json=SNAP_BODY)

    with Snapsbrew(base_url="https://snapsbrew.test") as client:
        snap = client.forms.submit(FORM_URL, {"headline": "Hello"})

    assert isinstance(snap, Snap)
    assert "authorization" not in route.calls.last.request.headers


async def test_an_async_client_with_no_token_submits_a_form(
    api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SNAPSBREW_TOKEN", raising=False)
    api.post(FORM_PATH).respond(201, json=SNAP_BODY)

    async with AsyncSnapsbrew(base_url="https://snapsbrew.test") as client:
        assert isinstance(await client.forms.submit(FORM_URL, {"headline": "Hello"}), Snap)


def test_the_url_must_be_absolute(client: Snapsbrew) -> None:
    with pytest.raises(ValueError, match="signed submit URL"):
        client.forms.submit(FORM_PATH, {"headline": "Hello"})


def test_a_bad_signature_is_not_found(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.post(FORM_PATH).respond(404, json={"message": ""})

    with pytest.raises(NotFoundError):
        client.forms.submit(FORM_URL, {"headline": "Hello"})


def test_too_many_submissions(api: respx.MockRouter) -> None:
    api.post(FORM_PATH).respond(
        429,
        json={"message": "Too many submissions.", "code": "rate_limited"},
        headers={"Retry-After": "30"},
    )

    with (
        Snapsbrew(base_url="https://snapsbrew.test", token="t", max_retries=0) as client,
        pytest.raises(RateLimitError) as caught,
    ):
        client.forms.submit(FORM_URL, {"headline": "Hello"})

    assert caught.value.code == "rate_limited"
    assert caught.value.retry_after == 30


def test_a_rate_limit_is_retried(
    client: Snapsbrew, api: respx.MockRouter, sleeps: SleepRecorder
) -> None:
    route = api.post(FORM_PATH)
    route.side_effect = [
        httpx.Response(429, json={"code": "rate_limited"}, headers={"Retry-After": "1"}),
        httpx.Response(201, json=SNAP_BODY),
    ]

    snap = client.forms.submit(FORM_URL, {"headline": "Hello"})

    assert isinstance(snap, Snap)
    assert route.call_count == 2
    assert sleeps.delays == [1.0]


def test_a_server_error_is_not_retried(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post(FORM_PATH).respond(500, json={"message": "Server Error"})

    with pytest.raises(ServerError):
        client.forms.submit(FORM_URL, {"headline": "Hello"})

    assert route.call_count == 1


async def test_the_async_client_submits_a_form(
    aclient: AsyncSnapsbrew, api: respx.MockRouter
) -> None:
    api.post(FORM_PATH).respond(201, json=SNAP_BODY)

    snap = await aclient.forms.submit(FORM_URL, {"headline": "Hello"})

    assert isinstance(snap, Snap)
