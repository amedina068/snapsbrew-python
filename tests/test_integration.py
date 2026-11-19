"""Integration tests against a live instance.

The tests run only when SNAPSBREW_TEST_URL and SNAPSBREW_TEST_TOKEN are set.
They are read-only, except for one preview call. A preview stores nothing.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import pytest

from snapsbrew import Snapsbrew, _client

URL = os.environ.get("SNAPSBREW_TEST_URL")
TOKEN = os.environ.get("SNAPSBREW_TEST_TOKEN")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (URL and TOKEN), reason="Set SNAPSBREW_TEST_URL and SNAPSBREW_TEST_TOKEN."
    ),
]


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> Iterator[Snapsbrew]:
    # The autouse fixture replaces the sleep function. A live retry needs the real one.
    monkeypatch.setattr(_client, "_sleep", time.sleep)
    with Snapsbrew(base_url=URL, token=TOKEN) as client:
        yield client


def test_whoami(live: Snapsbrew) -> None:
    account = live.whoami()
    assert account.email


def test_list_templates_and_preview_the_first(live: Snapsbrew) -> None:
    page = live.templates.list()
    if not page.data:
        pytest.skip("The account has no templates.")
    template = page.data[0]
    assert template.uuid
    html = live.snaps.preview(template.uuid)
    assert "<html" in html.lower()
