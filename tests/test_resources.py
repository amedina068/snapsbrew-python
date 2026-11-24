"""Unit tests for each resource of the sync client, with a mocked HTTP layer."""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from snapsbrew import (
    RENDER_FAILED,
    WEBHOOK_HTTP_PREFIX,
    WEBHOOK_REDIRECT_REFUSED,
    WEBHOOK_UNREACHABLE,
    Hidden,
    Image,
    Media,
    Snapsbrew,
    Text,
    ValidationError,
    WaitTimeoutError,
)
from tests.conftest import (
    BATCH_BODY,
    MEDIA_BODY,
    MEDIA_PAGE_BODY,
    SCREENSHOT_BODY,
    SCREENSHOT_LIST_ITEM,
    SNAP_BODY,
    TEMPLATE_ID,
    TOKEN,
    SleepRecorder,
)

TEMPLATE_BODY = {
    "uuid": TEMPLATE_ID,
    "title": "Launch card",
    "size": "open_graph",
    "width": 1200,
    "height": 630,
    "layers": [
        {"layer": "title", "available_modifications": {"text": "Hello"}},
        {"layer": "frame", "available_modifications": []},
    ],
    "published_version": 2,
    "has_unpublished_edits": True,
    "created_at": "2026-05-01T12:00:00.000000Z",
}


def sent_json(route: respx.Route, index: int = -1) -> object:
    return json.loads(route.calls[index].request.content)


def test_every_request_sends_the_token_and_accepts_json(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.get("/v1/auth").respond(json={"data": {"email": "a@b.c", "name": "Ada"}})
    client.account()
    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["accept"] == "application/json"
    assert request.headers["user-agent"].startswith("snapsbrew-python/")


def test_account(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/auth").respond(
        json={"data": {"email": "dev@example.com", "name": "Ada", "company": "Engines"}}
    )
    account = client.account()
    assert account.email == "dev@example.com"
    assert account.name == "Ada"
    assert account.company == "Engines"


def test_templates_list(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.get("/v1/templates").respond(
        json={
            "data": [{k: v for k, v in TEMPLATE_BODY.items() if k != "size"}],
            "meta": {"previous_cursor": None, "next_cursor": "eyJpZCI6MTB9"},
        }
    )
    page = client.templates.list()
    assert len(page) == 1
    assert page.has_more
    assert page.next_cursor == "eyJpZCI6MTB9"
    template = next(iter(page))
    assert template.uuid == TEMPLATE_ID
    assert template.id == TEMPLATE_ID
    assert template.size is None
    assert "cursor" not in route.calls.last.request.url.params


def test_templates_list_sends_the_cursor(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.get("/v1/templates", params={"cursor": "abc"}).respond(
        json={"data": [], "meta": {"previous_cursor": "x", "next_cursor": None}}
    )
    page = client.templates.list(cursor="abc")
    assert route.called
    assert not page.has_more
    assert page.previous_cursor == "x"


def test_templates_iter_follows_the_cursor(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/templates", params={"cursor": "page2"}).respond(
        json={"data": [{**TEMPLATE_BODY, "uuid": "b"}], "meta": {"next_cursor": None}}
    )
    api.get("/v1/templates").respond(
        json={"data": [{**TEMPLATE_BODY, "uuid": "a"}], "meta": {"next_cursor": "page2"}}
    )
    assert [template.uuid for template in client.templates.iter()] == ["a", "b"]


def test_templates_get(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get(f"/v1/templates/{TEMPLATE_ID}").respond(json={"data": TEMPLATE_BODY})
    template = client.templates.get(TEMPLATE_ID)
    assert template.title == "Launch card"
    assert template.size == "open_graph"
    assert (template.width, template.height) == (1200, 630)
    assert template.published_version == 2
    assert template.has_unpublished_edits is True
    assert template.created_at == datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    assert template.layers[0].layer == "title"
    assert template.layers[0].available_modifications == {"text": "Hello"}
    # The app sends `[]` for a layer with no modifications.
    assert template.layers[1].available_modifications == {}
    assert template.raw["title"] == "Launch card"


def test_templates_get_encodes_the_path_segment(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.get("/v1/templates/a%2Fb").respond(json={"data": TEMPLATE_BODY})
    client.templates.get("a/b")
    assert route.called


def test_templates_get_rejects_an_empty_id(client: Snapsbrew) -> None:
    with pytest.raises(ValueError, match="template_id"):
        client.templates.get("")


def test_templates_sizes(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/templates/sizes").respond(
        json={
            "data": [
                {
                    "size": "instagram_story",
                    "name": "Instagram Story (1080x1920)",
                    "platform": "Instagram",
                    "width": 1080,
                    "height": 1920,
                    "aspect_ratio": "9:16",
                    "safe_margin_px": 97,
                }
            ]
        }
    )
    sizes = client.templates.sizes()
    assert sizes[0].size == "instagram_story"
    assert sizes[0].safe_margin_px == 97


def test_snaps_create(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/snaps").respond(201, json=SNAP_BODY, headers={"X-Request-Uuid": "req-1"})
    snap = client.snaps.create(
        TEMPLATE_ID,
        variants=[Text("title", "Hello"), Image("cover", "https://example.com/a.jpg")],
        format="webp",
    )
    assert sent_json(route) == {
        "template_id": TEMPLATE_ID,
        "variants": [
            {"layer": "title", "text": "Hello"},
            {"layer": "cover", "image_url": "https://example.com/a.jpg"},
        ],
        "format": "webp",
    }
    assert snap.id == "9f1c2d3e"
    assert snap.is_completed
    assert snap.media_url == SNAP_BODY["media_url"]
    assert snap.width == 1200
    assert snap.request_id == "req-1"
    assert snap.replayed is False
    assert snap.variants == ({"layer": "title", "text": "Hello"},)


def test_snaps_create_accepts_plain_dicts(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/snaps").respond(201, json=SNAP_BODY)
    client.snaps.create(TEMPLATE_ID, [{"layer": "title", "text": "Hi"}])
    assert sent_json(route) == {
        "template_id": TEMPLATE_ID,
        "variants": [{"layer": "title", "text": "Hi"}],
    }


def test_snaps_create_with_webhook_is_async(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/snaps").respond(
        202, json={**SNAP_BODY, "status": "pending", "media_url": None, "is_async": True}
    )
    snap = client.snaps.create(TEMPLATE_ID, webhook_url="https://example.com/hook")
    body = sent_json(route)
    assert isinstance(body, dict)
    assert body["async"] is True
    assert body["webhook_url"] == "https://example.com/hook"
    assert snap.status == "pending"
    assert snap.media_url is None


def test_snaps_create_reads_the_replay_header(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/snaps").respond(
        201, json=SNAP_BODY, headers={"X-Idempotent-Replay": "true"}
    )
    snap = client.snaps.create(TEMPLATE_ID, idempotency_key="order-42")
    body = sent_json(route)
    assert isinstance(body, dict)
    assert body["idempotency_key"] == "order-42"
    assert snap.replayed is True


def test_snaps_create_from_collection(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/snaps").respond(201, json=[SNAP_BODY, {**SNAP_BODY, "id": "second"}])
    snaps = client.snaps.create_from_collection("col-1", [Text("title", "Hi")], type="pdf")
    assert [snap.id for snap in snaps] == ["9f1c2d3e", "second"]
    body = sent_json(route)
    assert isinstance(body, dict)
    assert body["collection_id"] == "col-1"
    assert body["type"] == "pdf"
    assert "template_id" not in body


def test_snaps_preview_encodes_variants_as_query(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.get("/v1/snaps/preview").respond(
        200, text="<!DOCTYPE html><p>preview</p>", headers={"Content-Type": "text/html"}
    )
    html = client.snaps.preview(TEMPLATE_ID, [Text("title", "Hello"), Hidden("badge")])
    assert html.startswith("<!DOCTYPE html>")
    params = list(route.calls.last.request.url.params.multi_items())
    assert params == [
        ("template_id", TEMPLATE_ID),
        ("variants[0][layer]", "title"),
        ("variants[0][text]", "Hello"),
        ("variants[1][layer]", "badge"),
        # The Laravel boolean rule rejects "true".
        ("variants[1][hidden]", "1"),
    ]


def test_batches_create(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/snaps/batches").respond(
        202, json=BATCH_BODY, headers={"X-Request-Uuid": "req-2"}
    )
    batch = client.batches.create(
        TEMPLATE_ID,
        items=[
            {"identifier": "row-1", "variants": [Text("title", "One")]},
            [Text("title", "Two")],
        ],
        title="October launch",
        format="png",
    )
    assert sent_json(route) == {
        "template_id": TEMPLATE_ID,
        "items": [
            {"variants": [{"layer": "title", "text": "One"}], "identifier": "row-1"},
            {"variants": [{"layer": "title", "text": "Two"}]},
        ],
        "title": "October launch",
        "format": "png",
    }
    assert batch.uuid == BATCH_BODY["uuid"]
    assert batch.id == batch.uuid
    assert batch.pending == 2
    assert not batch.is_finished
    assert batch.items == ()
    assert batch.request_id == "req-2"


def test_batches_create_rejects_a_flat_variant_list(client: Snapsbrew) -> None:
    with pytest.raises(TypeError, match="variant"):
        client.batches.create(TEMPLATE_ID, items=[{"layer": "title", "text": "x"}])


def test_batches_create_rejects_empty_and_too_many_items(client: Snapsbrew) -> None:
    with pytest.raises(ValueError, match="at least one"):
        client.batches.create(TEMPLATE_ID, items=[])
    with pytest.raises(ValueError, match="100"):
        client.batches.create(TEMPLATE_ID, items=[[Text("t", "x")]] * 101)


def test_batches_get(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get(f"/v1/snaps/batches/{BATCH_BODY['uuid']}").respond(
        json={
            **BATCH_BODY,
            "status": "completed",
            "completed": 1,
            "failed": 1,
            "pending": 0,
            "items": [
                {
                    "id": "a",
                    "identifier": "row-1",
                    "status": "completed",
                    "media_url": "https://x/a.png",
                    "last_error": None,
                },
                {
                    "id": "b",
                    "identifier": "row-2",
                    "status": "failed",
                    "media_url": None,
                    "last_error": "render_failed",
                },
            ],
        }
    )
    batch = client.batches.get(BATCH_BODY["uuid"])
    assert batch.is_finished
    assert [item.status for item in batch.items] == ["completed", "failed"]
    assert batch.items[1].last_error == RENDER_FAILED


def test_batches_cancel(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.post(f"/v1/snaps/batches/{BATCH_BODY['uuid']}/cancel").respond(
        json={**BATCH_BODY, "status": "canceled", "canceled": 2, "pending": 0, "items": []}
    )
    batch = client.batches.cancel(BATCH_BODY["uuid"])
    assert batch.status == "canceled"
    assert batch.is_finished


def test_batches_wait_polls_until_finished(
    client: Snapsbrew, api: respx.MockRouter, sleeps: SleepRecorder
) -> None:
    api.get(f"/v1/snaps/batches/{BATCH_BODY['uuid']}").mock(
        side_effect=[
            httpx.Response(200, json=BATCH_BODY),
            httpx.Response(200, json=BATCH_BODY),
            httpx.Response(200, json={**BATCH_BODY, "status": "completed"}),
        ]
    )
    batch = client.batches.wait(BATCH_BODY["uuid"], interval=2.0)
    assert batch.status == "completed"
    assert sleeps.delays == [2.0, 2.0]


def test_batches_wait_raises_after_the_timeout(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get(f"/v1/snaps/batches/{BATCH_BODY['uuid']}").respond(json=BATCH_BODY)
    with pytest.raises(WaitTimeoutError):
        client.batches.wait(BATCH_BODY["uuid"], timeout=0)


def test_screenshots_list_reads_uuid_as_id_and_the_image_url(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.get("/v1/screenshots").respond(
        json={
            "data": [SCREENSHOT_LIST_ITEM],
            "meta": {"previous_cursor": None, "next_cursor": None},
        }
    )
    page = client.screenshots.list()
    shot = page.data[0]
    assert shot.id == "a1b2c3"
    assert shot.image_url == SCREENSHOT_LIST_ITEM["image_url"]
    assert shot.created_at == datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    assert next(iter(client.screenshots.iter())).width == 1330


def test_screenshots_get(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get("/v1/screenshots/a1b2c3").respond(json={"data": SCREENSHOT_BODY})
    assert client.screenshots.get("a1b2c3").image_url == SCREENSHOT_BODY["image_url"]


def test_screenshots_give_none_when_the_capture_has_no_image(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.get("/v1/screenshots").respond(
        json={
            "data": [{**SCREENSHOT_LIST_ITEM, "image_url": None}],
            "meta": {"previous_cursor": None, "next_cursor": None},
        }
    )
    api.get("/v1/screenshots/a1b2c3").respond(json={"data": {**SCREENSHOT_BODY, "image_url": None}})
    api.post("/v1/screenshots").respond(json={"data": {**SCREENSHOT_BODY, "image_url": None}})
    assert client.screenshots.list().data[0].image_url is None
    assert client.screenshots.get("a1b2c3").image_url is None
    assert client.screenshots.create("https://example.com").image_url is None


def test_screenshots_create(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/screenshots").respond(json={"data": SCREENSHOT_BODY})
    shot = client.screenshots.create("https://example.com", width=800)
    assert sent_json(route) == {"url": "https://example.com", "width": 800}
    assert shot.id == "a1b2c3"


def test_media_list_reads_the_flat_laravel_paginator(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.get("/v1/media").respond(json=MEDIA_PAGE_BODY)
    page = client.media.list()
    assert (page.current_page, page.last_page, page.per_page, page.total) == (1, 1, 12, 1)
    assert not page.has_more
    media = page.data[0]
    assert media.id == 12
    assert media.uuid == MEDIA_BODY["uuid"]
    assert media.name == "logo"
    assert media.file_name == "logo.png"
    assert media.mime_type == "image/png"
    assert media.size == 20480
    assert media.original_url == MEDIA_BODY["original_url"]
    assert media.src == MEDIA_BODY["src"]
    assert media.created_at == datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def test_media_model_has_a_field_for_each_field_of_the_body() -> None:
    # The instance sends nine fields and no other field.
    assert set(MEDIA_BODY) == {
        "id",
        "uuid",
        "name",
        "file_name",
        "mime_type",
        "size",
        "original_url",
        "src",
        "created_at",
    }
    assert {item.name for item in fields(Media)} - {"raw"} == set(MEDIA_BODY)


def test_media_list_sends_the_page(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.get("/v1/media", params={"page": "2"}).respond(
        json={**MEDIA_PAGE_BODY, "current_page": 2, "last_page": 3, "total": 30}
    )
    page = client.media.list(page=2)
    assert route.called
    assert page.current_page == 2
    assert page.has_more


def test_media_upload_from_a_path(client: Snapsbrew, api: respx.MockRouter, tmp_path: Path) -> None:
    image = tmp_path / "logo.png"
    image.write_bytes(b"\x89PNG fake")
    route = api.post("/v1/media").respond(json=MEDIA_BODY)
    media = client.media.upload(image)
    assert media.id == 12
    assert media.mime_type == "image/png"
    assert media.raw == MEDIA_BODY
    request = route.calls.last.request
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'filename="logo.png"' in request.content
    assert b"Content-Type: image/png" in request.content
    assert b"\x89PNG fake" in request.content


def test_media_upload_from_bytes_and_file(
    client: Snapsbrew, api: respx.MockRouter, tmp_path: Path
) -> None:
    route = api.post("/v1/media").respond(json={"id": 1, "file_name": "a.jpg", "src": None})
    client.media.upload(b"jpeg bytes", filename="a.jpg")
    assert b'filename="a.jpg"' in route.calls.last.request.content
    path = tmp_path / "b.webp"
    path.write_bytes(b"webp bytes")
    with path.open("rb") as handle:
        client.media.upload(handle)
    assert b'filename="b.webp"' in route.calls.last.request.content


@pytest.mark.parametrize(
    ("method", "args", "path"),
    [
        ("design", (), "/v1/guides/design"),
        ("layers", (), "/v1/guides/layers"),
        ("variant_properties", (), "/v1/guides/variant-properties"),
        ("editor_document", (), "/v1/guides/editor-document"),
        ("platforms", (), "/v1/guides/platforms"),
        ("platform", ("instagram",), "/v1/guides/platforms/instagram"),
        ("purposes", (), "/v1/guides/purposes"),
        ("purpose", ("og",), "/v1/guides/purposes/og"),
    ],
)
def test_guides(
    client: Snapsbrew, api: respx.MockRouter, method: str, args: tuple[str, ...], path: str
) -> None:
    api.get(path).respond(json={"data": {"key": method}})
    assert getattr(client.guides, method)(*args) == {"key": method}


@pytest.mark.parametrize(
    "code",
    ["render_failed", "webhook_redirect_refused", "webhook_unreachable", "webhook_http_500"],
)
def test_snap_last_error_is_a_code(code: str, client: Snapsbrew, api: respx.MockRouter) -> None:
    api.post("/v1/snaps").respond(201, json={**SNAP_BODY, "last_error": code})
    assert client.snaps.create(TEMPLATE_ID).last_error == code


def test_the_last_error_constants_match_the_app() -> None:
    assert (RENDER_FAILED, WEBHOOK_REDIRECT_REFUSED, WEBHOOK_UNREACHABLE) == (
        "render_failed",
        "webhook_redirect_refused",
        "webhook_unreachable",
    )
    assert f"{WEBHOOK_HTTP_PREFIX}503" == "webhook_http_503"


def test_snap_create_reads_a_body_with_no_data_wrapper(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.post("/v1/snaps").respond(201, json=SNAP_BODY)
    assert client.snaps.create(TEMPLATE_ID).id == SNAP_BODY["id"]


def test_screenshots_create_sends_width_and_height_without_checks(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    # The instance accepts 1 to 4000. The SDK sends any value and lets the instance decide.
    route = api.post("/v1/screenshots").respond(
        422, json={"message": "Too wide.", "errors": {"width": ["Too wide."]}}
    )
    with pytest.raises(ValidationError) as caught:
        client.screenshots.create("https://example.com", width=5000, height=1)
    assert sent_json(route) == {"url": "https://example.com", "width": 5000, "height": 1}
    assert caught.value.errors["width"] == ["Too wide."]


def test_media_upload_of_an_svg_is_a_validation_error(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.post("/v1/media").respond(
        422, json={"message": "Wrong type.", "errors": {"file": ["Wrong type."]}}
    )
    with pytest.raises(ValidationError) as caught:
        client.media.upload(b"<svg/>", filename="logo.svg")
    assert "file" in caught.value.errors
