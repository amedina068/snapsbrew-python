"""Template writes, the v2 editor document and tags, with a mocked HTTP layer."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from snapsbrew import (
    EDITOR_DOCUMENT_CONFLICT,
    LEGACY_EDIT_REJECTED_FOR_V2,
    AsyncSnapsbrew,
    ConflictError,
    LayerDefinition,
    LayerGroup,
    NotFoundError,
    Snapsbrew,
    Text,
    ValidationError,
)
from tests.conftest import TEMPLATE_ID, SleepRecorder

SUMMARY_BODY: dict[str, Any] = {
    "uuid": TEMPLATE_ID,
    "title": "Launch card",
    "size": "open_graph",
    "width": 1200,
    "height": 630,
    "created_at": "2026-05-01T12:00:00.000000Z",
}

DOCUMENT: dict[str, Any] = {
    "version": 2,
    "layers": [{"key": "headline", "type": "text", "properties": []}],
    "groups": [],
}

TAG = {"id": 1, "name": "Launch", "slug": "launch"}

GROUPS: list[LayerGroup] = [{"id": "g1", "name": "Header", "visible": True, "order": 0}]


def sent_json(route: respx.Route) -> Any:
    return json.loads(route.calls.last.request.content)


def write_document(client: Snapsbrew, method: str, template_id: str = TEMPLATE_ID) -> object:
    """Send one editor document write: ``PUT`` replaces, ``PATCH`` applies."""
    if method == "put":
        return client.documents.replace(template_id, revision=4, document=DOCUMENT)
    return client.documents.apply(template_id, revision=4, operations=[])


def conflict_body(revision: int, document: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "code": "editor_document_conflict",
        "current_revision": revision,
        "current_document": document,
    }


# --- Templates ---------------------------------------------------------------


def test_create_sends_the_fields_and_returns_the_summary(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.post("/v1/templates").respond(
        json={"data": SUMMARY_BODY, "message": "Template created successfully"}
    )
    layers: list[LayerDefinition] = [
        {"key": "headline", "type": "text", "properties": [{"name": "text", "value": "Hi"}]}
    ]
    summary = client.templates.create(
        "Launch card", size="open_graph", layers=layers, groups=GROUPS
    )
    assert sent_json(route) == {
        "title": "Launch card",
        "size": "open_graph",
        "layers": layers,
        "groups": GROUPS,
    }
    assert summary.uuid == TEMPLATE_ID
    assert summary.id == TEMPLATE_ID
    assert summary.size == "open_graph"
    assert (summary.width, summary.height) == (1200, 630)
    assert summary.created_at is not None


def test_create_with_width_and_height(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/templates").respond(json={"data": {**SUMMARY_BODY, "size": "custom"}})
    client.templates.create("Card", width=800, height=400)
    assert sent_json(route) == {"title": "Card", "width": 800, "height": 400}


def test_create_is_not_retried_after_a_server_error(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.post("/v1/templates").respond(500, json={"message": "Server Error"})
    with pytest.raises(Exception, match="500"):
        client.templates.create("Card", size="open_graph")
    assert route.call_count == 1


def test_update_sends_only_the_given_fields(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.patch(f"/v1/templates/{TEMPLATE_ID}").respond(json={"data": SUMMARY_BODY})
    summary = client.templates.update(TEMPLATE_ID, title="New title")
    assert sent_json(route) == {"title": "New title"}
    assert summary.title == "Launch card"


def test_update_sends_groups_and_none_removes_them(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.patch("/v1/templates/42").respond(json={"data": SUMMARY_BODY})
    client.templates.update(42, title="T", groups=GROUPS, width=640)
    assert sent_json(route) == {"title": "T", "width": 640, "groups": GROUPS}
    client.templates.update(42, title="T", groups=None)
    assert sent_json(route) == {"title": "T", "groups": None}


def test_update_of_a_v2_template_raises_a_conflict(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.patch(f"/v1/templates/{TEMPLATE_ID}").respond(
        409, json={"code": "legacy_edit_rejected_for_v2"}
    )
    with pytest.raises(ConflictError) as caught:
        client.templates.update(TEMPLATE_ID, title="T")
    assert caught.value.code == LEGACY_EDIT_REJECTED_FOR_V2
    assert not caught.value.retryable
    assert caught.value.current_revision is None


def test_delete(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.delete(f"/v1/templates/{TEMPLATE_ID}").respond(
        json={"message": "Template deleted successfully"}
    )
    client.templates.delete(TEMPLATE_ID)
    assert route.called


def test_publish_reads_the_data_envelope(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.post(f"/v1/templates/{TEMPLATE_ID}/publish").respond(
        json={
            "data": {"id": TEMPLATE_ID, "uuid": TEMPLATE_ID, "published_version": 3},
            "message": "Template published. New snaps and previews now render this version.",
        }
    )
    published = client.templates.publish(TEMPLATE_ID)
    assert published.uuid == TEMPLATE_ID
    assert published.published_version == 3


def test_publish_is_retried_after_a_server_error(
    client: Snapsbrew, api: respx.MockRouter, sleeps: SleepRecorder
) -> None:
    route = api.post(f"/v1/templates/{TEMPLATE_ID}/publish")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json={"data": {"uuid": TEMPLATE_ID, "published_version": 1}}),
    ]
    assert client.templates.publish(TEMPLATE_ID).published_version == 1
    assert len(sleeps.delays) == 1


def test_template_preview_sends_the_variants_in_php_query_syntax(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.get(f"/v1/templates/{TEMPLATE_ID}/preview").respond(
        text="<!DOCTYPE html><html>preview</html>"
    )
    html = client.templates.preview(TEMPLATE_ID, [Text("title", "Hello")])
    assert html.startswith("<!DOCTYPE html>")
    params = route.calls.last.request.url.params
    assert params["variants[0][layer]"] == "title"
    assert params["variants[0][text]"] == "Hello"
    assert "template_id" not in params


def test_set_tags_replaces_the_tags(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post(f"/v1/templates/{TEMPLATE_ID}/tags").respond(
        json={"message": "Tags updated successfully.", "tags": [TAG]}
    )
    tags = client.templates.set_tags(TEMPLATE_ID, [1])
    assert sent_json(route) == {"tag_ids": [1]}
    assert tags[0].slug == "launch"
    client.templates.set_tags(TEMPLATE_ID, [])
    assert sent_json(route) == {"tag_ids": []}


# --- Editor documents --------------------------------------------------------


def test_document_get(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get(f"/v1/templates/{TEMPLATE_ID}/document").respond(
        json={"document": DOCUMENT, "revision": 4}
    )
    document = client.documents.get(TEMPLATE_ID)
    assert document.revision == 4
    assert document.document == DOCUMENT


def test_document_get_with_no_draft(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get(f"/v1/templates/{TEMPLATE_ID}/document").respond(json={"document": None, "revision": 0})
    document = client.documents.get(TEMPLATE_ID)
    assert document.document is None
    assert document.revision == 0


def test_document_replace(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.put(f"/v1/templates/{TEMPLATE_ID}/document").respond(
        json={"document": DOCUMENT, "revision": 5}
    )
    document = client.documents.replace(TEMPLATE_ID, revision=4, document=DOCUMENT)
    assert sent_json(route) == {"revision": 4, "document": DOCUMENT}
    assert document.revision == 5


def test_document_apply(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.patch(f"/v1/templates/{TEMPLATE_ID}/document").respond(
        json={"document": DOCUMENT, "revision": 5}
    )
    document = client.documents.apply(
        TEMPLATE_ID,
        revision=4,
        operations=[
            {
                "operation": "set_layer_property",
                "layer_key": "headline",
                "property": "fontWeight",
                "value": 700,
            },
            {"operation": "set_layer_type", "layer_key": "logo", "type": "image"},
        ],
    )
    assert sent_json(route)["operations"][1] == {
        "operation": "set_layer_type",
        "layer_key": "logo",
        "type": "image",
    }
    assert document.revision == 5


@pytest.mark.parametrize("method", ["put", "patch"])
def test_a_document_conflict_has_the_current_revision_and_document(
    method: str, client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.route(method=method.upper(), path=f"/v1/templates/{TEMPLATE_ID}/document")
    route.respond(
        409,
        json=conflict_body(5, DOCUMENT),
    )
    with pytest.raises(ConflictError) as caught:
        write_document(client, method, TEMPLATE_ID)
    error = caught.value
    assert error.code == EDITOR_DOCUMENT_CONFLICT
    assert error.current_revision == 5
    assert error.current_document == DOCUMENT
    assert not error.retryable
    assert route.call_count == 1


def test_a_document_conflict_with_no_stored_document(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    # The source sends `null` when the template has no draft. The spec says object.
    api.put(f"/v1/templates/{TEMPLATE_ID}/document").respond(
        409,
        json=conflict_body(0, None),
    )
    with pytest.raises(ConflictError) as caught:
        client.documents.replace(TEMPLATE_ID, revision=3, document=DOCUMENT)
    assert caught.value.current_revision == 0
    assert caught.value.current_document is None


def test_a_rejected_operation_is_a_validation_error_with_a_code(
    client: Snapsbrew, api: respx.MockRouter
) -> None:
    api.patch(f"/v1/templates/{TEMPLATE_ID}/document").respond(
        422, json={"code": "editor_operation_layer_not_found"}
    )
    with pytest.raises(ValidationError) as caught:
        client.documents.apply(
            TEMPLATE_ID,
            revision=4,
            operations=[{"operation": "set_layer_type", "layer_key": "x", "type": "image"}],
        )
    assert caught.value.code == "editor_operation_layer_not_found"
    assert caught.value.errors == {}
    assert str(caught.value) == "422: editor_operation_layer_not_found"


@pytest.mark.parametrize("method", ["put", "patch"])
def test_a_document_write_is_not_retried_after_a_server_error(
    method: str, client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.route(method=method.upper(), path=f"/v1/templates/{TEMPLATE_ID}/document")
    route.respond(502)
    with pytest.raises(Exception, match="502"):
        write_document(client, method, TEMPLATE_ID)
    assert route.call_count == 1


@pytest.mark.parametrize("method", ["put", "patch"])
def test_a_document_write_for_a_missing_template_is_not_found(
    method: str, client: Snapsbrew, api: respx.MockRouter
) -> None:
    route = api.route(method=method.upper(), path="/v1/templates/missing/document")
    route.respond(404, json={"message": "No query results for model [App\\Models\\Template]."})
    with pytest.raises(NotFoundError):
        write_document(client, method, "missing")


def test_document_preflight(client: Snapsbrew, api: respx.MockRouter) -> None:
    api.get(f"/v1/templates/{TEMPLATE_ID}/document/preflight").respond(
        json={
            "issues": [
                {
                    "code": "image_asset_missing",
                    "path": "/layers/0/source",
                    "message": "Image layers require a pinned asset id.",
                }
            ],
            "revision": 4,
        }
    )
    preflight = client.documents.preflight(TEMPLATE_ID)
    assert preflight.revision == 4
    assert not preflight.ok
    assert preflight.issues[0].code == "image_asset_missing"
    assert preflight.issues[0].path == "/layers/0/source"


# --- Tags --------------------------------------------------------------------


def test_tags_list_with_a_search(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.get("/v1/tags").respond(json={"data": [TAG]})
    tags = client.tags.list(search="lau")
    assert route.calls.last.request.url.params["search"] == "lau"
    assert [tag.name for tag in tags] == ["Launch"]
    client.tags.list()
    assert "search" not in route.calls.last.request.url.params


def test_tags_create(client: Snapsbrew, api: respx.MockRouter) -> None:
    route = api.post("/v1/tags").respond(201, json={"data": TAG})
    tag = client.tags.create("Launch")
    assert sent_json(route) == {"name": "Launch"}
    assert tag.id == 1


# --- The async client --------------------------------------------------------


async def test_async_template_writes(aclient: AsyncSnapsbrew, api: respx.MockRouter) -> None:
    api.post("/v1/templates").respond(json={"data": SUMMARY_BODY})
    api.patch(f"/v1/templates/{TEMPLATE_ID}").respond(json={"data": SUMMARY_BODY})
    api.delete(f"/v1/templates/{TEMPLATE_ID}").respond(json={"message": "deleted"})
    api.post(f"/v1/templates/{TEMPLATE_ID}/publish").respond(
        json={"data": {"uuid": TEMPLATE_ID, "published_version": 2}}
    )
    api.get(f"/v1/templates/{TEMPLATE_ID}/preview").respond(text="<html></html>")
    api.post(f"/v1/templates/{TEMPLATE_ID}/tags").respond(json={"tags": [TAG]})

    assert (await aclient.templates.create("Card", size="open_graph")).uuid == TEMPLATE_ID
    assert (await aclient.templates.update(TEMPLATE_ID, title="T", groups=None)).width == 1200
    await aclient.templates.delete(TEMPLATE_ID)
    assert (await aclient.templates.publish(TEMPLATE_ID)).published_version == 2
    assert await aclient.templates.preview(TEMPLATE_ID) == "<html></html>"
    assert (await aclient.templates.set_tags(TEMPLATE_ID, [1]))[0].id == 1


async def test_async_documents_and_tags(aclient: AsyncSnapsbrew, api: respx.MockRouter) -> None:
    path = f"/v1/templates/{TEMPLATE_ID}/document"
    api.get(path).respond(json={"document": DOCUMENT, "revision": 4})
    api.put(path).respond(json={"document": DOCUMENT, "revision": 5})
    api.patch(path).respond(
        409,
        json=conflict_body(6, {}),
    )
    api.get(f"{path}/preflight").respond(json={"issues": [], "revision": 5})
    api.get("/v1/tags").respond(json={"data": [TAG]})
    api.post("/v1/tags").respond(201, json={"data": TAG})

    assert (await aclient.documents.get(TEMPLATE_ID)).revision == 4
    assert (
        await aclient.documents.replace(TEMPLATE_ID, revision=4, document=DOCUMENT)
    ).revision == 5
    with pytest.raises(ConflictError) as caught:
        await aclient.documents.apply(TEMPLATE_ID, revision=5, operations=[])
    assert caught.value.current_revision == 6
    assert (await aclient.documents.preflight(TEMPLATE_ID)).ok
    assert (await aclient.tags.list())[0].slug == "launch"
    assert (await aclient.tags.create("Launch")).name == "Launch"
