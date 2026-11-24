"""Client settings: base URL, token, environment variables, timeout, custom HTTP clients."""

from __future__ import annotations

import httpx
import pytest
import respx

from snapsbrew import AsyncSnapsbrew, Snapsbrew
from tests.conftest import TOKEN

AUTH_BODY = {"data": {"email": "a@b.c", "name": "Ada", "company": None}}


@pytest.mark.parametrize(
    "base_url",
    [
        "https://snapsbrew.test",
        "https://snapsbrew.test/",
        "https://snapsbrew.test/api",
        "https://snapsbrew.test/api/",
        "  https://snapsbrew.test  ",
    ],
)
def test_base_url_is_normalized(base_url: str) -> None:
    with Snapsbrew(base_url=base_url, token=TOKEN) as client:
        assert client.base_url == "https://snapsbrew.test"


def test_base_url_keeps_a_sub_path() -> None:
    with Snapsbrew(base_url="https://example.com/snapsbrew/", token=TOKEN) as client:
        assert client.base_url == "https://example.com/snapsbrew"


def test_base_url_needs_a_scheme() -> None:
    with pytest.raises(ValueError, match="https://"):
        Snapsbrew(base_url="snapsbrew.test", token=TOKEN)


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNAPSBREW_URL", "https://env.test")
    monkeypatch.setenv("SNAPSBREW_TOKEN", "env-token")
    with Snapsbrew() as client:
        assert client.base_url == "https://env.test"


def test_missing_settings_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAPSBREW_URL", raising=False)
    monkeypatch.delenv("SNAPSBREW_TOKEN", raising=False)
    with pytest.raises(ValueError, match="SNAPSBREW_URL"):
        Snapsbrew(token=TOKEN)


@pytest.mark.parametrize("token", [None, "", "  "])
def test_a_call_with_no_token_fails_before_the_send(
    monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    monkeypatch.delenv("SNAPSBREW_TOKEN", raising=False)
    with (
        respx.mock(assert_all_called=False) as router,
        Snapsbrew(base_url="https://snapsbrew.test", token=token) as client,
    ):
        route = router.get("https://snapsbrew.test/api/v1/auth").respond(200, json={"data": {}})
        with pytest.raises(ValueError, match="no API token"):
            client.account()
        assert route.call_count == 0


async def test_an_async_call_with_no_token_fails_before_the_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SNAPSBREW_TOKEN", raising=False)
    async with AsyncSnapsbrew(base_url="https://snapsbrew.test") as client:
        with pytest.raises(ValueError, match="no API token"):
            await client.account()


def test_negative_max_retries_raises() -> None:
    with pytest.raises(ValueError, match="max_retries"):
        Snapsbrew(base_url="https://snapsbrew.test", token=TOKEN, max_retries=-1)


def test_repr_does_not_show_the_token() -> None:
    with Snapsbrew(base_url="https://snapsbrew.test", token="secret-value") as client:
        assert "secret-value" not in repr(client)
        assert repr(client) == "Snapsbrew(base_url='https://snapsbrew.test')"


def test_default_timeout_is_60_seconds() -> None:
    with Snapsbrew(base_url="https://snapsbrew.test", token=TOKEN) as client:
        assert client._http.timeout == httpx.Timeout(60.0)


def test_custom_timeout_goes_on_each_request() -> None:
    with (
        respx.mock(base_url="https://snapsbrew.test/api") as api,
        Snapsbrew(base_url="https://snapsbrew.test", token=TOKEN, timeout=5.0) as client,
    ):
        route = api.get("/v1/auth").respond(json=AUTH_BODY)
        client.account()
        assert route.calls.last.request.extensions["timeout"]["read"] == 5.0


def test_custom_http_client_is_used_and_not_closed() -> None:
    http = httpx.Client(headers={"X-Custom": "yes"}, timeout=12.0)
    with (
        respx.mock(base_url="https://snapsbrew.test/api") as api,
        Snapsbrew(base_url="https://snapsbrew.test", token=TOKEN, http_client=http) as client,
    ):
        route = api.get("/v1/auth").respond(json=AUTH_BODY)
        client.account()
        request = route.calls.last.request
        assert request.headers["x-custom"] == "yes"
        # The client keeps the timeout of your http_client.
        assert request.extensions["timeout"]["read"] == 12.0
    assert not http.is_closed
    http.close()


def test_own_http_client_is_closed_on_exit() -> None:
    with Snapsbrew(base_url="https://snapsbrew.test", token=TOKEN) as client:
        pass
    assert client._http.is_closed


async def test_async_custom_http_client_is_not_closed() -> None:
    http = httpx.AsyncClient()
    async with AsyncSnapsbrew(base_url="https://snapsbrew.test", token=TOKEN, http_client=http):
        pass
    assert not http.is_closed
    await http.aclose()


async def test_async_own_http_client_is_closed_on_exit() -> None:
    async with AsyncSnapsbrew(base_url="https://snapsbrew.test", token=TOKEN) as client:
        pass
    assert client._http.is_closed
