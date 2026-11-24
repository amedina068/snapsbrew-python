"""Unit tests for each resource of the async client, with a mocked HTTP layer."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from snapsbrew import AsyncSnapsbrew, NotFoundError, Text, WaitTimeoutError
from tests.conftest import (
    BATCH_BODY,
    MEDIA_BODY,
    MEDIA_PAGE_BODY,
    SCREENSHOT_BODY,
    SCREENSHOT_LIST_ITEM,
    SNAP_BODY,
    TEMPLATE_ID,
    SleepRecorder,
)

TEMPLATE_BODY = {
    "uuid": TEMPLATE_ID,
    "title": "Launch card",
    "width": 1200,
    "height": 630,
    "layers": [{"layer": "title", "available_modifications": {"text": "Hello"}}],
    "created_at": "2026-05-01T12:00:00Z",
}


async def test_account(aclient: AsyncSnapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/auth").respond(json={"data": {"email": "a@b.c", "name": "Ada", "company": None}})
    account = await aclient.account()
    assert account.email == "a@b.c"
    assert account.company is None


async def test_templates(aclient: AsyncSnapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/templates", params={"cursor": "p2"}).respond(
        json={"data": [{**TEMPLATE_BODY, "uuid": "b"}], "meta": {"next_cursor": None}}
    )
    api.get("/v1/templates").respond(
        json={"data": [{**TEMPLATE_BODY, "uuid": "a"}], "meta": {"next_cursor": "p2"}}
    )
    api.get(f"/v1/templates/{TEMPLATE_ID}").respond(json={"data": TEMPLATE_BODY})
    api.get("/v1/templates/sizes").respond(
        json={
            "data": [
                {
                    "size": "open_graph",
                    "name": "Open Graph",
                    "platform": "Web & email",
                    "width": 1200,
                    "height": 630,
                    "aspect_ratio": "1.9:1",
                    "safe_margin_px": 47,
                }
            ]
        }
    )
    page = await aclient.templates.list()
    assert page.next_cursor == "p2"
    assert [t.uuid async for t in aclient.templates.iter()] == ["a", "b"]
    assert (await aclient.templates.get(TEMPLATE_ID)).layers[0].layer == "title"
    assert (await aclient.templates.sizes())[0].size == "open_graph"


async def test_snaps(aclient: AsyncSnapsbrew, api: respx.MockRouter) -> None:
    create = api.post("/v1/snaps").mock(
        side_effect=[
            httpx.Response(201, json=SNAP_BODY),
            httpx.Response(201, json=[SNAP_BODY]),
        ]
    )
    preview = api.get("/v1/snaps/preview").respond(text="<html>preview</html>")
    snap = await aclient.snaps.create(TEMPLATE_ID, [Text("title", "Hello")])
    assert snap.media_url == SNAP_BODY["media_url"]
    assert json.loads(create.calls[0].request.content)["variants"] == [
        {"layer": "title", "text": "Hello"}
    ]
    snaps = await aclient.snaps.create_from_collection("col-1")
    assert len(snaps) == 1
    html = await aclient.snaps.preview(TEMPLATE_ID, [{"layer": "t", "text": "x"}])
    assert html == "<html>preview</html>"
    assert preview.calls.last.request.url.params["variants[0][text]"] == "x"


async def test_batches(
    aclient: AsyncSnapsbrew, api: respx.MockRouter, sleeps: SleepRecorder
) -> None:
    uuid = BATCH_BODY["uuid"]
    api.post("/v1/snaps/batches").respond(202, json=BATCH_BODY)
    api.get(f"/v1/snaps/batches/{uuid}").mock(
        side_effect=[
            httpx.Response(200, json=BATCH_BODY),
            httpx.Response(200, json={**BATCH_BODY, "status": "failed"}),
            httpx.Response(200, json=BATCH_BODY),
        ]
    )
    api.post(f"/v1/snaps/batches/{uuid}/cancel").respond(json={**BATCH_BODY, "status": "canceled"})
    batch = await aclient.batches.create(TEMPLATE_ID, [[Text("t", "1")], [Text("t", "2")]])
    assert batch.total_rows == 2
    finished = await aclient.batches.wait(uuid, interval=1.0)
    assert finished.status == "failed"
    assert sleeps.delays == [1.0]
    with pytest.raises(WaitTimeoutError):
        await aclient.batches.wait(uuid, timeout=0)
    assert (await aclient.batches.cancel(uuid)).status == "canceled"


async def test_screenshots(aclient: AsyncSnapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/screenshots").respond(
        json={"data": [SCREENSHOT_LIST_ITEM], "meta": {"next_cursor": None}}
    )
    api.get("/v1/screenshots/a1b2c3").respond(json={"data": SCREENSHOT_BODY})
    api.post("/v1/screenshots").respond(json={"data": SCREENSHOT_BODY})
    listed = (await aclient.screenshots.list()).data[0]
    assert listed.id == "a1b2c3"
    assert listed.image_url == SCREENSHOT_LIST_ITEM["image_url"]
    assert [s.image_url async for s in aclient.screenshots.iter()] == [listed.image_url]
    assert (await aclient.screenshots.get("a1b2c3")).height == 780
    assert (await aclient.screenshots.create("https://example.com")).url == "https://example.com"


async def test_media(aclient: AsyncSnapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/media").respond(json=MEDIA_PAGE_BODY)
    upload = api.post("/v1/media").respond(json={**MEDIA_BODY, "id": 4, "file_name": "b.png"})
    page = await aclient.media.list()
    assert page.data[0].file_name == "logo.png"
    assert page.data[0].size == 20480
    assert (await aclient.media.upload(b"bytes", filename="b.png")).id == 4
    assert b'filename="b.png"' in upload.calls.last.request.content


async def test_guides(aclient: AsyncSnapsbrew, api: respx.MockRouter) -> None:
    for path in [
        "design",
        "layers",
        "variant-properties",
        "editor-document",
        "platforms",
        "platforms/x",
        "purposes",
        "purposes/og",
    ]:
        api.get(f"/v1/guides/{path}").respond(json={"data": path})
    guides = aclient.guides
    assert await guides.design() == "design"
    assert await guides.layers() == "layers"
    assert await guides.variant_properties() == "variant-properties"
    assert await guides.editor_document() == "editor-document"
    assert await guides.platforms() == "platforms"
    assert await guides.platform("x") == "platforms/x"
    assert await guides.purposes() == "purposes"
    assert await guides.purpose("og") == "purposes/og"


async def test_errors(aclient: AsyncSnapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/screenshots/missing").respond(404, json={"message": "Not found."})
    with pytest.raises(NotFoundError, match="Not found"):
        await aclient.screenshots.get("missing")
