from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import respx

from snapsbrew import AsyncSnapsbrew, Snapsbrew, Text, _client

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


# The list item of GET /v1/screenshots. The list names the id `uuid`.
SCREENSHOT_LIST_ITEM: dict[str, Any] = {
    "uuid": "a1b2c3",
    "url": "https://example.com",
    "image_url": "https://snapsbrew.test/storage/12/a1b2c3.png",
    "width": 1330,
    "height": 780,
    "created_at": "2026-05-01T12:00:00.000000Z",
}

# The read and the create of a screenshot name the same value `id`.
SCREENSHOT_BODY: dict[str, Any] = {
    "id": "a1b2c3",
    **{key: value for key, value in SCREENSHOT_LIST_ITEM.items() if key != "uuid"},
}

# The exact body of POST /v1/media and of each item of GET /v1/media. The
# instance sends these nine fields and no other field.
MEDIA_BODY: dict[str, Any] = {
    "id": 12,
    "uuid": "0d4c3a1e-5b2f-4e8a-9c7d-1f2e3a4b5c6d",
    "name": "logo",
    "file_name": "logo.png",
    "mime_type": "image/png",
    "size": 20480,
    "original_url": "https://snapsbrew.test/storage/12/logo.png",
    "src": "https://snapsbrew.test/storage/12/conversions/logo-image.jpg",
    "created_at": "2026-05-01T12:00:00.000000Z",
}

# GET /v1/media sends a flat Laravel paginator with no `meta` key.
MEDIA_PAGE_BODY: dict[str, Any] = {
    "current_page": 1,
    "data": [MEDIA_BODY],
    "first_page_url": f"{API}/v1/media?page=1",
    "from": 1,
    "last_page": 1,
    "last_page_url": f"{API}/v1/media?page=1",
    "links": [
        {"url": None, "label": "&laquo; Previous", "active": False},
        {"url": f"{API}/v1/media?page=1", "label": "1", "active": True},
        {"url": None, "label": "Next &raquo;", "active": False},
    ],
    "next_page_url": None,
    "path": f"{API}/v1/media",
    "per_page": 12,
    "prev_page_url": None,
    "to": 1,
    "total": 1,
}


def create_with_key(client: Snapsbrew, path: str) -> object:
    """Send ``POST {path}`` with an idempotency key, for a snap or for a batch."""
    if path == "/v1/snaps":
        return client.snaps.create(TEMPLATE_ID, idempotency_key="k-1")
    return client.batches.create(TEMPLATE_ID, [[Text("t", "x")]], idempotency_key="k-1")


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
