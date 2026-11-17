from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import respx

from snapsbrew import AsyncSnapsbrew, Snapsbrew, _client

BASE_URL = "https://snapsbrew.test"
API = f"{BASE_URL}/api"
TOKEN = "test-token"
TEMPLATE_ID = "044ec825-ee2f-4d06-bb77-98663e27f529"

SNAP_BODY: dict[str, Any] = {
    "id": "9f1c2d3e",
    "media_url": "https://snapsbrew.test/storage/snaps/9f1c2d3e.png",
    "width": 1200,
    "height": 630,
    "type": "image",
    "status": "completed",
    "is_async": False,
    "webhook_url": None,
    "completed_at": "2026-05-01T12:00:03.000000Z",
    "last_error": None,
    "variants": [{"layer": "title", "text": "Hello"}],
    "template_id": TEMPLATE_ID,
    "template_title": "Launch card",
    "created_at": "2026-05-01T12:00:00.000000Z",
}

BATCH_BODY: dict[str, Any] = {
    "uuid": "7c1f2a9e-0b44-4a1e-9f2b-5d3c8e1a7b60",
    "title": "October launch",
    "status": "processing",
    "total_rows": 2,
    "processed_rows": 0,
    "completed": 0,
    "pending": 2,
    "failed": 0,
    "canceled": 0,
    "status_url": f"{API}/v1/snaps/batches/7c1f2a9e-0b44-4a1e-9f2b-5d3c8e1a7b60",
}


class SleepRecorder:
    """Records each wait of the client instead of sleeping."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)

    async def async_sleep(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture(autouse=True)
def sleeps(monkeypatch: pytest.MonkeyPatch) -> SleepRecorder:
    recorder = SleepRecorder()
    monkeypatch.setattr(_client, "_sleep", recorder.sleep)
    monkeypatch.setattr(_client, "_async_sleep", recorder.async_sleep)
    return recorder


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=True) as router:
        yield router


@pytest.fixture
def client() -> Iterator[Snapsbrew]:
    with Snapsbrew(base_url=BASE_URL, token=TOKEN) as instance:
        yield instance


@pytest.fixture
async def aclient() -> AsyncIterator[AsyncSnapsbrew]:
    async with AsyncSnapsbrew(base_url=BASE_URL, token=TOKEN) as instance:
        yield instance
