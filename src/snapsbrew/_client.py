"""The sync client ``Snapsbrew`` and the async client ``AsyncSnapsbrew``.

The two clients have the same resources and the same methods. The functions
at the top of this module build the requests and read the responses, so the
two clients share all logic except the I/O.
"""

from __future__ import annotations

import asyncio
import builtins
import mimetypes
import os
import time
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Literal, TypeVar
from urllib.parse import quote

import httpx

from snapsbrew._base import (
    DEFAULT_MAX_RETRIES,
    NOT_GIVEN,
    BaseClient,
    FilePart,
    NotGiven,
    RequestSpec,
    TimeoutTypes,
    connection_error,
    decode_body,
    error_from_response,
    response_retry_delay,
    transport_retry_delay,
    unwrap_data,
)
from snapsbrew.errors import SnapsbrewError, WaitTimeoutError
from snapsbrew.models import (
    Account,
    Batch,
    EditorDocument,
    Media,
    MediaPage,
    Page,
    Preflight,
    PublishedTemplate,
    Screenshot,
    Snap,
    Tag,
    Template,
    TemplateSize,
    TemplateSummary,
)
from snapsbrew.params import EditorOperation, LayerDefinition, LayerGroup
from snapsbrew.variants import VariantLike, to_dicts

__all__ = ["AsyncSnapsbrew", "Snapsbrew"]

SnapType = Literal["image", "pdf"]
ImageFormat = Literal["png", "jpeg", "webp"]
FileInput = str | os.PathLike[str] | bytes | IO[bytes]
BatchItemInput = Mapping[str, Any] | Sequence[VariantLike]
# The typed shapes, or plain dicts, for example from a JSON file.
Layers = Sequence[LayerDefinition | Mapping[str, Any]]
Groups = Sequence[LayerGroup | Mapping[str, Any]]
Operations = Sequence[EditorOperation | Mapping[str, Any]]

MAX_BATCH_ITEMS = 100

_SyncClient = TypeVar("_SyncClient", bound="Snapsbrew")
_AsyncClient = TypeVar("_AsyncClient", bound="AsyncSnapsbrew")


# The tests replace these two functions, so that a retry does not wait.
def _sleep(seconds: float) -> None:
    time.sleep(seconds)


async def _async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


# --- Request builders and response readers, shared by both clients ----------


def _segment(value: str, name: str) -> str:
    if not value:
        raise ValueError(f"{name} must not be empty")
    return quote(value, safe="")


def _cursor_params(cursor: str | None) -> list[tuple[str, str]] | None:
    return [("cursor", cursor)] if cursor else None


def _object(body: Any) -> Mapping[str, Any]:
    if not isinstance(body, dict):
        raise SnapsbrewError(
            "The instance sent a response that is not a JSON object. "
            "Make sure that base_url is the URL of a Snapsbrew instance."
        )
    return body


def _objects(body: Any) -> list[Mapping[str, Any]]:
    if not isinstance(body, list):
        raise SnapsbrewError("The instance sent a response that is not a JSON list.")
    return [item for item in body if isinstance(item, dict)]


def _templates_page(body: Any) -> Page[Template]:
    body = _object(body)
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    return Page(
        data=tuple(Template.from_dict(item) for item in _objects(body.get("data", []))),
        next_cursor=meta.get("next_cursor"),
        previous_cursor=meta.get("previous_cursor"),
    )


def _screenshots_page(body: Any) -> Page[Screenshot]:
    body = _object(body)
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    return Page(
        data=tuple(Screenshot.from_dict(item) for item in _objects(body.get("data", []))),
        next_cursor=meta.get("next_cursor"),
        previous_cursor=meta.get("previous_cursor"),
    )


def _snap_body(
    *,
    target: tuple[str, str],
    variants: Iterable[VariantLike] | None,
    type: SnapType | None,
    format: ImageFormat | None,
    transparent: bool | None,
    webhook_url: str | None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {target[0]: target[1]}
    if variants is not None:
        body["variants"] = to_dicts(variants)
    if type is not None:
        body["type"] = type
    if format is not None:
        body["format"] = format
    if transparent is not None:
        body["transparent"] = transparent
    if webhook_url is not None:
        body["async"] = True
        body["webhook_url"] = webhook_url
    if idempotency_key is not None:
        body["idempotency_key"] = idempotency_key
    return body


def _snap_from_response(response: httpx.Response) -> Snap:
    return Snap.from_dict(
        _object(unwrap_data(decode_body(response))),
        request_id=response.headers.get("x-request-uuid"),
        replayed=response.headers.get("x-idempotent-replay") == "true",
    )


def _snaps_from_response(response: httpx.Response) -> list[Snap]:
    request_id = response.headers.get("x-request-uuid")
    return [
        Snap.from_dict(item, request_id=request_id)
        for item in _objects(unwrap_data(decode_body(response)))
    ]


def _batch_from_response(response: httpx.Response) -> Batch:
    return Batch.from_dict(
        _object(unwrap_data(decode_body(response))),
        request_id=response.headers.get("x-request-uuid"),
        replayed=response.headers.get("x-idempotent-replay") == "true",
    )


def _batch_items(items: Iterable[BatchItemInput]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if isinstance(item, Mapping):
            if "layer" in item and "variants" not in item:
                raise TypeError(
                    f"items[{index}] is a variant. Each item is a list of variants, "
                    'or a dict like {"identifier": "row-1", "variants": [...]}.'
                )
            entry: dict[str, Any] = {"variants": to_dicts(item.get("variants"))}
            if item.get("identifier") is not None:
                entry["identifier"] = str(item["identifier"])
        else:
            entry = {"variants": to_dicts(item)}
        result.append(entry)
    if not result:
        raise ValueError("items must contain at least one item")
    if len(result) > MAX_BATCH_ITEMS:
        raise ValueError(
            f"A batch accepts at most {MAX_BATCH_ITEMS} items, not {len(result)}. "
            "Split the items into more batches."
        )
    return result


def _batch_body(
    *,
    template_id: str,
    items: Iterable[BatchItemInput],
    title: str | None,
    webhook_url: str | None,
    type: SnapType | None,
    format: ImageFormat | None,
    transparent: bool | None,
    idempotency_key: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"template_id": template_id, "items": _batch_items(items)}
    optional = {
        "title": title,
        "webhook_url": webhook_url,
        "type": type,
        "format": format,
        "transparent": transparent,
        "idempotency_key": idempotency_key,
    }
    body.update({key: value for key, value in optional.items() if value is not None})
    return body


def _variant_params(variants: Iterable[VariantLike] | None) -> list[tuple[str, str]]:
    params = []
    for index, variant in enumerate(to_dicts(variants)):
        for key, value in variant.items():
            if value is None:
                continue
            # The Laravel `boolean` rule accepts "1" and "0", not "true" and "false".
            text = ("1" if value else "0") if isinstance(value, bool) else str(value)
            params.append((f"variants[{index}][{key}]", text))
    return params


def _preview_params(
    template_id: str, variants: Iterable[VariantLike] | None
) -> list[tuple[str, str]]:
    return [("template_id", template_id), *_variant_params(variants)]


def _template_path(template_id: str | int, suffix: str = "") -> str:
    # The update and the delete also accept the numeric id of the template.
    return f"/v1/templates/{_segment(str(template_id), 'template_id')}{suffix}"


def _template_body(
    *,
    title: str,
    size: str | None,
    width: int | None,
    height: int | None,
    layers: Layers | None,
    groups: Groups | NotGiven | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"title": title}
    optional = {"size": size, "width": width, "height": height}
    body.update({key: value for key, value in optional.items() if value is not None})
    if layers is not None:
        body["layers"] = [dict(layer) for layer in layers]
    # On an update, `groups=None` removes each group, so None is sent.
    if not isinstance(groups, NotGiven):
        body["groups"] = None if groups is None else [dict(group) for group in groups]
    return body


def _summary(body: Any) -> TemplateSummary:
    return TemplateSummary.from_dict(_object(unwrap_data(body)))


def _tags(items: Any) -> list[Tag]:
    return [Tag.from_dict(item) for item in _objects(items)]


def _screenshot_body(url: str, width: int | None, height: int | None) -> dict[str, Any]:
    body: dict[str, Any] = {"url": url}
    if width is not None:
        body["width"] = width
    if height is not None:
        body["height"] = height
    return body


def _upload_files(file: FileInput, filename: str | None) -> dict[str, FilePart]:
    # The client reads the whole file before the first attempt, so that a retry
    # sends the same bytes.
    if isinstance(file, (str, os.PathLike)):
        path = Path(file)
        content = path.read_bytes()
        name = filename or path.name
    elif isinstance(file, bytes):
        content = file
        name = filename or "upload"
    else:
        content = file.read()
        name = filename or Path(str(getattr(file, "name", "upload"))).name
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return {"file": (name, content, mime)}


FormValue = str | os.PathLike[str] | bytes | IO[bytes]
"""A form layer value. A ``str`` is text. A path, bytes or a binary file object is an image."""


def _form_spec(url: str, layers: Mapping[str, FormValue]) -> RequestSpec:
    if not url.startswith(("https://", "http://")):
        raise ValueError(
            "Give the signed submit URL of the form, for example "
            "https://snapsbrew.example.com/api/v1/embedded-forms/...?signature=..."
        )
    # Each part goes in ``files``, so that the body is multipart also when all
    # the layers are text. A text part has no filename.
    files: dict[str, FilePart] = {}
    for key, value in layers.items():
        field = f"layers[{key}]"
        if isinstance(value, str):
            files[field] = (None, value.encode("utf-8"))
        else:
            files[field] = _upload_files(value, None)["file"]
    return RequestSpec("POST", url, files=files, signed=True)


def _form_result(response: httpx.Response) -> Snap | list[Snap]:
    body = decode_body(response)
    if isinstance(body, list):
        return _snaps_from_response(response)
    return _snap_from_response(response)


# --- The sync client ---------------------------------------------------------


class Snapsbrew(BaseClient):
    """A client for one Snapsbrew instance.

    Example::

        with Snapsbrew(base_url="https://snapsbrew.example.com", token="...") as client:
            snap = client.snaps.create(template_id, variants=[Text("title", "Hello")])
            print(snap.media_url)

    Args:
        base_url: The URL of your instance. The default is ``$SNAPSBREW_URL``.
        token: An API token with the ``api_requests`` ability. The default is
            ``$SNAPSBREW_TOKEN``. Only ``forms.submit()`` works without a token.
        timeout: Seconds, or an ``httpx.Timeout``. The default is 60 seconds,
            because a synchronous render can take that long.
            ``None`` means no timeout.
        max_retries: The number of retries after a 429, a 5xx or a connection
            error. The default is 2. Use 0 to stop all retries.
        http_client: Your own ``httpx.Client``, for example with a proxy. The
            client does not close it.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        timeout: TimeoutTypes | NotGiven = NOT_GIVEN,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(base_url, token, timeout=timeout, max_retries=max_retries)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=self._default_timeout)
        self.templates = Templates(self)
        self.documents = Documents(self)
        self.tags = Tags(self)
        self.snaps = Snaps(self)
        self.batches = Batches(self)
        self.screenshots = Screenshots(self)
        self.media = MediaLibrary(self)
        self.guides = Guides(self)
        self.forms = Forms(self)

    def account(self) -> Account:
        """Return the account of the token (``GET /v1/auth``)."""
        body = self._json(RequestSpec("GET", "/v1/auth", idempotent=True))
        return Account.from_dict(_object(unwrap_data(body)))

    def close(self) -> None:
        """Close the connections. The client does not close an ``http_client`` that you gave."""
        if self._owns_http:
            self._http.close()

    def __enter__(self: _SyncClient) -> _SyncClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _send(self, spec: RequestSpec) -> httpx.Response:
        attempt = 0
        while True:
            try:
                response = self._http.send(self._build_request(self._http, spec))
            except httpx.TransportError as exc:
                delay = transport_retry_delay(exc, spec, attempt, self.max_retries)
                if delay is None:
                    raise connection_error(exc) from exc
            else:
                if response.is_success:
                    return response
                delay = response_retry_delay(response, spec, attempt, self.max_retries)
                if delay is None:
                    raise error_from_response(response)
                response.close()
            _sleep(delay)
            attempt += 1

    def _json(self, spec: RequestSpec) -> Any:
        return decode_body(self._send(spec))


class Templates:
    """Read, write and publish templates."""

    def __init__(self, client: Snapsbrew) -> None:
        self._client = client

    def list(self, *, cursor: str | None = None) -> Page[Template]:
        """Return one page of templates. Give ``page.next_cursor`` to get the next page."""
        spec = RequestSpec("GET", "/v1/templates", params=_cursor_params(cursor), idempotent=True)
        return _templates_page(self._client._json(spec))

    def iter(self) -> Iterator[Template]:
        """Iterate over all templates. The client gets the pages one at a time."""
        cursor: str | None = None
        while True:
            page = self.list(cursor=cursor)
            yield from page
            if not page.next_cursor:
                return
            cursor = page.next_cursor

    def get(self, template_id: str) -> Template:
        """Return one template, with its layers and its publish state."""
        path = f"/v1/templates/{_segment(template_id, 'template_id')}"
        body = self._client._json(RequestSpec("GET", path, idempotent=True))
        return Template.from_dict(_object(unwrap_data(body)))

    def sizes(self) -> builtins.list[TemplateSize]:
        """Return all canvas size presets."""
        body = self._client._json(RequestSpec("GET", "/v1/templates/sizes", idempotent=True))
        return [TemplateSize.from_dict(item) for item in _objects(unwrap_data(body))]

    def create(
        self,
        title: str,
        *,
        size: str | None = None,
        width: int | None = None,
        height: int | None = None,
        layers: Layers | None = None,
        groups: Groups | None = None,
    ) -> TemplateSummary:
        """Create a template. Give a ``size`` preset, or a ``width`` and a ``height``.

        ``guides.layers()`` gives the layer vocabulary. With no ``layers``, the
        canvas is empty. Snaps render a template only after :meth:`publish`.
        """
        body = _template_body(
            title=title,
            size=size,
            width=width,
            height=height,
            layers=layers,
            groups=NOT_GIVEN if groups is None else groups,
        )
        return _summary(self._client._json(RequestSpec("POST", "/v1/templates", json=body)))

    def update(
        self,
        template_id: str | int,
        *,
        title: str,
        size: str | None = None,
        width: int | None = None,
        height: int | None = None,
        layers: Layers | None = None,
        groups: Groups | NotGiven | None = NOT_GIVEN,
    ) -> TemplateSummary:
        """Change a template. The instance requires ``title`` on each update.

        A field that you do not give keeps its value. ``groups=None`` removes
        each group. ``template_id`` is the UUID or the numeric id.

        Raises:
            ConflictError: The template uses the v2 editor document. The code is
                ``legacy_edit_rejected_for_v2``. Use :attr:`Snapsbrew.documents`.
        """
        body = _template_body(
            title=title, size=size, width=width, height=height, layers=layers, groups=groups
        )
        spec = RequestSpec("PATCH", _template_path(template_id), json=body)
        return _summary(self._client._json(spec))

    def delete(self, template_id: str | int) -> None:
        """Delete a template. You cannot undo a delete.

        The instance also deletes the snaps, the images, the versions and the
        forms of the template. ``template_id`` is the UUID or the numeric id.
        """
        self._client._send(RequestSpec("DELETE", _template_path(template_id), idempotent=True))

    def publish(self, template_id: str) -> PublishedTemplate:
        """Publish the draft as a new version. Snaps and previews render only this version.

        A repeat with no new edits returns the live version and creates no new version.
        """
        spec = RequestSpec("POST", _template_path(template_id, "/publish"), idempotent=True)
        return PublishedTemplate.from_dict(_object(unwrap_data(self._client._json(spec))))

    def preview(self, template_id: str, variants: Iterable[VariantLike] | None = None) -> str:
        """Return a watermarked HTML preview of the published version. A preview stores nothing."""
        spec = RequestSpec(
            "GET",
            _template_path(template_id, "/preview"),
            params=_variant_params(variants),
            idempotent=True,
        )
        return self._client._send(spec).text

    def set_tags(self, template_id: str, tag_ids: Iterable[int]) -> builtins.list[Tag]:
        """Replace all tags of a template. An empty list removes each tag."""
        spec = RequestSpec(
            "POST",
            _template_path(template_id, "/tags"),
            json={"tag_ids": list(tag_ids)},
            idempotent=True,
        )
        return _tags(_object(self._client._json(spec)).get("tags"))


class Documents:
    """Read and write the v2 editor document of a template.

    Each write sends the ``revision`` of your last read. If another write
    changed the document after that read, the instance saves nothing and the
    client raises :class:`ConflictError` with ``current_revision`` and
    ``current_document``. The client does not retry a write.
    """

    def __init__(self, client: Snapsbrew) -> None:
        self._client = client

    def get(self, template_id: str) -> EditorDocument:
        """Return the document and its revision. Read it before each write."""
        spec = RequestSpec("GET", _template_path(template_id, "/document"), idempotent=True)
        return EditorDocument.from_dict(_object(self._client._json(spec)))

    def replace(
        self, template_id: str, *, revision: int, document: Mapping[str, Any]
    ) -> EditorDocument:
        """Replace the whole document. A layer or a property that you leave out is removed."""
        spec = RequestSpec(
            "PUT",
            _template_path(template_id, "/document"),
            json={"revision": revision, "document": dict(document)},
        )
        return EditorDocument.from_dict(_object(self._client._json(spec)))

    def apply(self, template_id: str, *, revision: int, operations: Operations) -> EditorDocument:
        """Apply 1 to 100 operations. They all apply, or none applies.

        Raises:
            ValidationError: The document refused an operation. Read ``code``,
                for example ``"editor_operation_layer_not_found"``.
        """
        spec = RequestSpec(
            "PATCH",
            _template_path(template_id, "/document"),
            json={"revision": revision, "operations": [dict(item) for item in operations]},
        )
        return EditorDocument.from_dict(_object(self._client._json(spec)))

    def preflight(self, template_id: str) -> Preflight:
        """Return the known problems of the stored document. Run it before you publish."""
        path = _template_path(template_id, "/document/preflight")
        return Preflight.from_dict(
            _object(self._client._json(RequestSpec("GET", path, idempotent=True)))
        )


class Tags:
    """List and create the tags of your company."""

    def __init__(self, client: Snapsbrew) -> None:
        self._client = client

    def list(self, *, search: str | None = None) -> builtins.list[Tag]:
        """Return up to 15 tags, sorted by name. ``search`` matches a part of the name."""
        params = [("search", search)] if search else None
        body = self._client._json(RequestSpec("GET", "/v1/tags", params=params, idempotent=True))
        return _tags(unwrap_data(body))

    def create(self, name: str) -> Tag:
        """Create a tag. The instance makes the slug from the name."""
        body = self._client._json(RequestSpec("POST", "/v1/tags", json={"name": name}))
        return Tag.from_dict(_object(unwrap_data(body)))


class Snaps:
    """Render snaps and preview them."""

    def __init__(self, client: Snapsbrew) -> None:
        self._client = client

    def create(
        self,
        template_id: str,
        variants: Iterable[VariantLike] | None = None,
        *,
        type: SnapType | None = None,
        format: ImageFormat | None = None,
        transparent: bool | None = None,
        webhook_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> Snap:
        """Render a snap from the published version of a template.

        If you give ``webhook_url``, the instance queues the render and returns
        at once with the status ``pending``. Then it posts the result to the webhook.

        If you give ``idempotency_key``, a retry with the same key returns the
        same snap and renders nothing. The client then also retries after a 5xx,
        after a read timeout and after a 409 with the code
        ``idempotency_key_in_progress``.

        Raises:
            ValidationError: A field is not valid. A ``template_id`` that does not
                exist in your company is a validation error, not a 404.
            ConflictError: The ``idempotency_key`` belongs to a batch, or another
                request still holds it after all retries. Read ``code``.
            AuthorizationError: The token or a permission check refused the request.
        """
        body = _snap_body(
            target=("template_id", template_id),
            variants=variants,
            type=type,
            format=format,
            transparent=transparent,
            webhook_url=webhook_url,
            idempotency_key=idempotency_key,
        )
        spec = RequestSpec(
            "POST",
            "/v1/snaps",
            json=body,
            idempotent=idempotency_key is not None,
            idempotency_key=idempotency_key,
        )
        return _snap_from_response(self._client._send(spec))

    def create_from_collection(
        self,
        collection_id: str,
        variants: Iterable[VariantLike] | None = None,
        *,
        type: SnapType | None = None,
        format: ImageFormat | None = None,
        transparent: bool | None = None,
        webhook_url: str | None = None,
    ) -> list[Snap]:
        """Render one snap for each template of a collection.

        A collection with no templates raises :class:`NotFoundError`. This
        request does not accept an ``idempotency_key``.
        """
        body = _snap_body(
            target=("collection_id", collection_id),
            variants=variants,
            type=type,
            format=format,
            transparent=transparent,
            webhook_url=webhook_url,
        )
        response = self._client._send(RequestSpec("POST", "/v1/snaps", json=body))
        return _snaps_from_response(response)

    def preview(self, template_id: str, variants: Iterable[VariantLike] | None = None) -> str:
        """Return a watermarked HTML preview. A preview stores nothing.

        The instance allows 10 previews a minute for each account.
        """
        spec = RequestSpec(
            "GET",
            "/v1/snaps/preview",
            params=_preview_params(template_id, variants),
            idempotent=True,
        )
        return self._client._send(spec).text


class Batches:
    """Render up to 100 snaps from one template in the background."""

    def __init__(self, client: Snapsbrew) -> None:
        self._client = client

    def create(
        self,
        template_id: str,
        items: Iterable[BatchItemInput],
        *,
        title: str | None = None,
        webhook_url: str | None = None,
        type: SnapType | None = None,
        format: ImageFormat | None = None,
        transparent: bool | None = None,
        idempotency_key: str | None = None,
    ) -> Batch:
        """Start a batch.

        Each item is a list of variants, or a dict with ``variants`` and an
        optional ``identifier``. The instance posts one webhook to
        ``webhook_url`` when the batch finishes.

        If you give ``idempotency_key``, a retry with the same key returns the
        same batch and starts nothing. The client then retries like
        :meth:`Snaps.create`. A key that belongs to a single snap raises
        :class:`ConflictError` with the code ``idempotency_key_belongs_to_snap``.
        """
        body = _batch_body(
            template_id=template_id,
            items=items,
            title=title,
            webhook_url=webhook_url,
            type=type,
            format=format,
            transparent=transparent,
            idempotency_key=idempotency_key,
        )
        spec = RequestSpec(
            "POST",
            "/v1/snaps/batches",
            json=body,
            idempotent=idempotency_key is not None,
            idempotency_key=idempotency_key,
        )
        return _batch_from_response(self._client._send(spec))

    def get(self, batch_id: str) -> Batch:
        """Return the counts of a batch and each item with its status and image URL."""
        path = f"/v1/snaps/batches/{_segment(batch_id, 'batch_id')}"
        return _batch_from_response(self._client._send(RequestSpec("GET", path, idempotent=True)))

    def cancel(self, batch_id: str) -> Batch:
        """Stop the items that did not start. You cannot undo a cancel."""
        path = f"/v1/snaps/batches/{_segment(batch_id, 'batch_id')}/cancel"
        # The server returns a finished batch unchanged, so a retry is safe.
        return _batch_from_response(self._client._send(RequestSpec("POST", path, idempotent=True)))

    def wait(self, batch_id: str, *, interval: float = 5.0, timeout: float | None = 600.0) -> Batch:
        """Get the batch again each ``interval`` seconds until its status is terminal.

        Raises:
            WaitTimeoutError: The batch did not finish in ``timeout`` seconds.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            batch = self.get(batch_id)
            if batch.is_finished:
                return batch
            if deadline is not None and time.monotonic() >= deadline:
                raise WaitTimeoutError(f"Batch {batch_id} did not finish in {timeout} seconds.")
            _sleep(interval)


class Screenshots:
    """Capture web pages as images."""

    def __init__(self, client: Snapsbrew) -> None:
        self._client = client

    def list(self, *, cursor: str | None = None) -> Page[Screenshot]:
        """Return one page of screenshots."""
        spec = RequestSpec("GET", "/v1/screenshots", params=_cursor_params(cursor), idempotent=True)
        return _screenshots_page(self._client._json(spec))

    def iter(self) -> Iterator[Screenshot]:
        """Iterate over all screenshots."""
        cursor: str | None = None
        while True:
            page = self.list(cursor=cursor)
            yield from page
            if not page.next_cursor:
                return
            cursor = page.next_cursor

    def get(self, screenshot_id: str) -> Screenshot:
        """Return one screenshot."""
        path = f"/v1/screenshots/{_segment(screenshot_id, 'screenshot_id')}"
        body = self._client._json(RequestSpec("GET", path, idempotent=True))
        return Screenshot.from_dict(_object(unwrap_data(body)))

    def create(
        self, url: str, *, width: int | None = None, height: int | None = None
    ) -> Screenshot:
        """Capture a page. The default viewport is 1330 x 780 pixels.

        The instance accepts a ``width`` and a ``height`` of 1 to 4000 pixels.
        It sends :class:`ValidationError` for another value.
        """
        spec = RequestSpec("POST", "/v1/screenshots", json=_screenshot_body(url, width, height))
        return Screenshot.from_dict(_object(unwrap_data(self._client._json(spec))))


class MediaLibrary:
    """Upload images to the media library and list them."""

    def __init__(self, client: Snapsbrew) -> None:
        self._client = client

    def list(self, *, page: int = 1) -> MediaPage:
        """Return one page of images, 12 for each page, newest first."""
        spec = RequestSpec("GET", "/v1/media", params=[("page", str(page))], idempotent=True)
        return MediaPage.from_dict(_object(self._client._json(spec)))

    def upload(self, file: FileInput, *, filename: str | None = None) -> Media:
        """Upload an image. ``file`` is a path, the bytes or a binary file object.

        Give ``filename`` with bytes, so that the instance knows the image type.
        The instance accepts JPG, JPEG, PNG, GIF, WebP and BMP files of 10 MB
        maximum. It refuses SVG. It sends :class:`ValidationError` for a file
        that breaks a rule.
        """
        spec = RequestSpec("POST", "/v1/media", files=_upload_files(file, filename))
        return Media.from_dict(_object(unwrap_data(self._client._json(spec))))


class Guides:
    """Read the static guide catalogs. A guide call does not go into the usage log."""

    def __init__(self, client: Snapsbrew) -> None:
        self._client = client

    def _get(self, path: str) -> Any:
        return unwrap_data(self._client._json(RequestSpec("GET", path, idempotent=True)))

    def design(self) -> Any:
        """Return the design guide: canvas presets, layer order, typography and color rules."""
        return self._get("/v1/guides/design")

    def layers(self) -> Any:
        """Return the layer schema for a template ``layers`` array."""
        return self._get("/v1/guides/layers")

    def variant_properties(self) -> Any:
        """Return each property that a variant can set, with its value type."""
        return self._get("/v1/guides/variant-properties")

    def editor_document(self) -> Any:
        """Return the contract of the v2 editor document."""
        return self._get("/v1/guides/editor-document")

    def platforms(self) -> Any:
        """Return one line for each platform, with its default size preset."""
        return self._get("/v1/guides/platforms")

    def platform(self, key: str) -> Any:
        """Return the full guide of one platform, for example ``"instagram"``.

        A key that does not exist raises :class:`NotFoundError`. Its
        ``available`` lists the valid keys.
        """
        return self._get(f"/v1/guides/platforms/{_segment(key, 'key')}")

    def purposes(self) -> Any:
        """Return one line for each image purpose."""
        return self._get("/v1/guides/purposes")

    def purpose(self, key: str) -> Any:
        """Return the full guide of one image purpose, for example ``"link_preview"``."""
        return self._get(f"/v1/guides/purposes/{_segment(key, 'key')}")


class Forms:
    """Submit an embedded form.

    A form renders on the account of its owner, so the client sends no token
    to the submit URL. Copy the submit URL of the form from your instance. The
    URL carries its own signature.
    """

    def __init__(self, client: Snapsbrew) -> None:
        self._client = client

    def submit(self, url: str, layers: Mapping[str, FormValue]) -> Snap | builtins.list[Snap]:
        """Send the layers of a form and return the snap.

        A template form returns one snap. A collection form returns a list of
        snaps, and its layer keys are ``"{template uuid}__{layer key}"``. A
        ``str`` value is text. A path, bytes or a binary file object is an image.

        Raises:
            NotFoundError: The signature is not valid, or the form does not exist.
            RateLimitError: Too many submissions. ``code`` is ``"rate_limited"``.
            ValueError: ``url`` is not an absolute URL.
        """
        return _form_result(self._client._send(_form_spec(url, layers)))


# --- The async client --------------------------------------------------------


class AsyncSnapsbrew(BaseClient):
    """The async client. It has the same resources and methods as :class:`Snapsbrew`.

    Example::

        async with AsyncSnapsbrew(base_url="https://snapsbrew.example.com", token="...") as client:
            snap = await client.snaps.create(template_id, variants=[Text("title", "Hello")])
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        timeout: TimeoutTypes | NotGiven = NOT_GIVEN,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(base_url, token, timeout=timeout, max_retries=max_retries)
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=self._default_timeout)
        self.templates = AsyncTemplates(self)
        self.documents = AsyncDocuments(self)
        self.tags = AsyncTags(self)
        self.snaps = AsyncSnaps(self)
        self.batches = AsyncBatches(self)
        self.screenshots = AsyncScreenshots(self)
        self.media = AsyncMediaLibrary(self)
        self.guides = AsyncGuides(self)
        self.forms = AsyncForms(self)

    async def account(self) -> Account:
        """Return the account of the token (``GET /v1/auth``)."""
        body = await self._json(RequestSpec("GET", "/v1/auth", idempotent=True))
        return Account.from_dict(_object(unwrap_data(body)))

    async def aclose(self) -> None:
        """Close the connections. The client does not close an ``http_client`` that you gave."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self: _AsyncClient) -> _AsyncClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def _send(self, spec: RequestSpec) -> httpx.Response:
        attempt = 0
        while True:
            try:
                response = await self._http.send(self._build_request(self._http, spec))
            except httpx.TransportError as exc:
                delay = transport_retry_delay(exc, spec, attempt, self.max_retries)
                if delay is None:
                    raise connection_error(exc) from exc
            else:
                if response.is_success:
                    return response
                delay = response_retry_delay(response, spec, attempt, self.max_retries)
                if delay is None:
                    raise error_from_response(response)
                await response.aclose()
            await _async_sleep(delay)
            attempt += 1

    async def _json(self, spec: RequestSpec) -> Any:
        return decode_body(await self._send(spec))


class AsyncTemplates:
    """Read, write and publish templates."""

    def __init__(self, client: AsyncSnapsbrew) -> None:
        self._client = client

    async def list(self, *, cursor: str | None = None) -> Page[Template]:
        """Return one page of templates. Give ``page.next_cursor`` to get the next page."""
        spec = RequestSpec("GET", "/v1/templates", params=_cursor_params(cursor), idempotent=True)
        return _templates_page(await self._client._json(spec))

    async def iter(self) -> AsyncIterator[Template]:
        """Iterate over all templates. The client gets the pages one at a time."""
        cursor: str | None = None
        while True:
            page = await self.list(cursor=cursor)
            for template in page:
                yield template
            if not page.next_cursor:
                return
            cursor = page.next_cursor

    async def get(self, template_id: str) -> Template:
        """Return one template, with its layers and its publish state."""
        path = f"/v1/templates/{_segment(template_id, 'template_id')}"
        body = await self._client._json(RequestSpec("GET", path, idempotent=True))
        return Template.from_dict(_object(unwrap_data(body)))

    async def sizes(self) -> builtins.list[TemplateSize]:
        """Return all canvas size presets."""
        body = await self._client._json(RequestSpec("GET", "/v1/templates/sizes", idempotent=True))
        return [TemplateSize.from_dict(item) for item in _objects(unwrap_data(body))]

    async def create(
        self,
        title: str,
        *,
        size: str | None = None,
        width: int | None = None,
        height: int | None = None,
        layers: Layers | None = None,
        groups: Groups | None = None,
    ) -> TemplateSummary:
        """Create a template. See :meth:`Templates.create`."""
        body = _template_body(
            title=title,
            size=size,
            width=width,
            height=height,
            layers=layers,
            groups=NOT_GIVEN if groups is None else groups,
        )
        return _summary(await self._client._json(RequestSpec("POST", "/v1/templates", json=body)))

    async def update(
        self,
        template_id: str | int,
        *,
        title: str,
        size: str | None = None,
        width: int | None = None,
        height: int | None = None,
        layers: Layers | None = None,
        groups: Groups | NotGiven | None = NOT_GIVEN,
    ) -> TemplateSummary:
        """Change a template. See :meth:`Templates.update`."""
        body = _template_body(
            title=title, size=size, width=width, height=height, layers=layers, groups=groups
        )
        spec = RequestSpec("PATCH", _template_path(template_id), json=body)
        return _summary(await self._client._json(spec))

    async def delete(self, template_id: str | int) -> None:
        """Delete a template and its snaps, images, versions and forms. You cannot undo it."""
        spec = RequestSpec("DELETE", _template_path(template_id), idempotent=True)
        await self._client._send(spec)

    async def publish(self, template_id: str) -> PublishedTemplate:
        """Publish the draft as a new version. See :meth:`Templates.publish`."""
        spec = RequestSpec("POST", _template_path(template_id, "/publish"), idempotent=True)
        return PublishedTemplate.from_dict(_object(unwrap_data(await self._client._json(spec))))

    async def preview(self, template_id: str, variants: Iterable[VariantLike] | None = None) -> str:
        """Return a watermarked HTML preview of the published version."""
        spec = RequestSpec(
            "GET",
            _template_path(template_id, "/preview"),
            params=_variant_params(variants),
            idempotent=True,
        )
        return (await self._client._send(spec)).text

    async def set_tags(self, template_id: str, tag_ids: Iterable[int]) -> builtins.list[Tag]:
        """Replace all tags of a template. An empty list removes each tag."""
        spec = RequestSpec(
            "POST",
            _template_path(template_id, "/tags"),
            json={"tag_ids": list(tag_ids)},
            idempotent=True,
        )
        return _tags(_object(await self._client._json(spec)).get("tags"))


class AsyncDocuments:
    """Read and write the v2 editor document of a template. See :class:`Documents`."""

    def __init__(self, client: AsyncSnapsbrew) -> None:
        self._client = client

    async def get(self, template_id: str) -> EditorDocument:
        """Return the document and its revision. Read it before each write."""
        spec = RequestSpec("GET", _template_path(template_id, "/document"), idempotent=True)
        return EditorDocument.from_dict(_object(await self._client._json(spec)))

    async def replace(
        self, template_id: str, *, revision: int, document: Mapping[str, Any]
    ) -> EditorDocument:
        """Replace the whole document. See :meth:`Documents.replace`."""
        spec = RequestSpec(
            "PUT",
            _template_path(template_id, "/document"),
            json={"revision": revision, "document": dict(document)},
        )
        return EditorDocument.from_dict(_object(await self._client._json(spec)))

    async def apply(
        self, template_id: str, *, revision: int, operations: Operations
    ) -> EditorDocument:
        """Apply 1 to 100 operations. See :meth:`Documents.apply`."""
        spec = RequestSpec(
            "PATCH",
            _template_path(template_id, "/document"),
            json={"revision": revision, "operations": [dict(item) for item in operations]},
        )
        return EditorDocument.from_dict(_object(await self._client._json(spec)))

    async def preflight(self, template_id: str) -> Preflight:
        """Return the known problems of the stored document."""
        path = _template_path(template_id, "/document/preflight")
        body = await self._client._json(RequestSpec("GET", path, idempotent=True))
        return Preflight.from_dict(_object(body))


class AsyncTags:
    """List and create the tags of your company."""

    def __init__(self, client: AsyncSnapsbrew) -> None:
        self._client = client

    async def list(self, *, search: str | None = None) -> builtins.list[Tag]:
        """Return up to 15 tags, sorted by name."""
        params = [("search", search)] if search else None
        spec = RequestSpec("GET", "/v1/tags", params=params, idempotent=True)
        return _tags(unwrap_data(await self._client._json(spec)))

    async def create(self, name: str) -> Tag:
        """Create a tag. The instance makes the slug from the name."""
        body = await self._client._json(RequestSpec("POST", "/v1/tags", json={"name": name}))
        return Tag.from_dict(_object(unwrap_data(body)))


class AsyncSnaps:
    """Render snaps and preview them."""

    def __init__(self, client: AsyncSnapsbrew) -> None:
        self._client = client

    async def create(
        self,
        template_id: str,
        variants: Iterable[VariantLike] | None = None,
        *,
        type: SnapType | None = None,
        format: ImageFormat | None = None,
        transparent: bool | None = None,
        webhook_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> Snap:
        """Render a snap. See :meth:`Snaps.create`."""
        body = _snap_body(
            target=("template_id", template_id),
            variants=variants,
            type=type,
            format=format,
            transparent=transparent,
            webhook_url=webhook_url,
            idempotency_key=idempotency_key,
        )
        spec = RequestSpec(
            "POST",
            "/v1/snaps",
            json=body,
            idempotent=idempotency_key is not None,
            idempotency_key=idempotency_key,
        )
        return _snap_from_response(await self._client._send(spec))

    async def create_from_collection(
        self,
        collection_id: str,
        variants: Iterable[VariantLike] | None = None,
        *,
        type: SnapType | None = None,
        format: ImageFormat | None = None,
        transparent: bool | None = None,
        webhook_url: str | None = None,
    ) -> list[Snap]:
        """Render one snap for each template. See :meth:`Snaps.create_from_collection`."""
        body = _snap_body(
            target=("collection_id", collection_id),
            variants=variants,
            type=type,
            format=format,
            transparent=transparent,
            webhook_url=webhook_url,
        )
        response = await self._client._send(RequestSpec("POST", "/v1/snaps", json=body))
        return _snaps_from_response(response)

    async def preview(self, template_id: str, variants: Iterable[VariantLike] | None = None) -> str:
        """Return a watermarked HTML preview. A preview stores nothing."""
        spec = RequestSpec(
            "GET",
            "/v1/snaps/preview",
            params=_preview_params(template_id, variants),
            idempotent=True,
        )
        return (await self._client._send(spec)).text


class AsyncBatches:
    """Render up to 100 snaps from one template in the background."""

    def __init__(self, client: AsyncSnapsbrew) -> None:
        self._client = client

    async def create(
        self,
        template_id: str,
        items: Iterable[BatchItemInput],
        *,
        title: str | None = None,
        webhook_url: str | None = None,
        type: SnapType | None = None,
        format: ImageFormat | None = None,
        transparent: bool | None = None,
        idempotency_key: str | None = None,
    ) -> Batch:
        """Start a batch. See :meth:`Batches.create`."""
        body = _batch_body(
            template_id=template_id,
            items=items,
            title=title,
            webhook_url=webhook_url,
            type=type,
            format=format,
            transparent=transparent,
            idempotency_key=idempotency_key,
        )
        spec = RequestSpec(
            "POST",
            "/v1/snaps/batches",
            json=body,
            idempotent=idempotency_key is not None,
            idempotency_key=idempotency_key,
        )
        return _batch_from_response(await self._client._send(spec))

    async def get(self, batch_id: str) -> Batch:
        """Return the counts of a batch and each item with its status and image URL."""
        path = f"/v1/snaps/batches/{_segment(batch_id, 'batch_id')}"
        response = await self._client._send(RequestSpec("GET", path, idempotent=True))
        return _batch_from_response(response)

    async def cancel(self, batch_id: str) -> Batch:
        """Stop the items that did not start. You cannot undo a cancel."""
        path = f"/v1/snaps/batches/{_segment(batch_id, 'batch_id')}/cancel"
        response = await self._client._send(RequestSpec("POST", path, idempotent=True))
        return _batch_from_response(response)

    async def wait(
        self, batch_id: str, *, interval: float = 5.0, timeout: float | None = 600.0
    ) -> Batch:
        """Get the batch again each ``interval`` seconds until its status is terminal.

        Raises:
            WaitTimeoutError: The batch did not finish in ``timeout`` seconds.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            batch = await self.get(batch_id)
            if batch.is_finished:
                return batch
            if deadline is not None and time.monotonic() >= deadline:
                raise WaitTimeoutError(f"Batch {batch_id} did not finish in {timeout} seconds.")
            await _async_sleep(interval)


class AsyncScreenshots:
    """Capture web pages as images."""

    def __init__(self, client: AsyncSnapsbrew) -> None:
        self._client = client

    async def list(self, *, cursor: str | None = None) -> Page[Screenshot]:
        """Return one page of screenshots."""
        spec = RequestSpec("GET", "/v1/screenshots", params=_cursor_params(cursor), idempotent=True)
        return _screenshots_page(await self._client._json(spec))

    async def iter(self) -> AsyncIterator[Screenshot]:
        """Iterate over all screenshots."""
        cursor: str | None = None
        while True:
            page = await self.list(cursor=cursor)
            for screenshot in page:
                yield screenshot
            if not page.next_cursor:
                return
            cursor = page.next_cursor

    async def get(self, screenshot_id: str) -> Screenshot:
        """Return one screenshot."""
        path = f"/v1/screenshots/{_segment(screenshot_id, 'screenshot_id')}"
        body = await self._client._json(RequestSpec("GET", path, idempotent=True))
        return Screenshot.from_dict(_object(unwrap_data(body)))

    async def create(
        self, url: str, *, width: int | None = None, height: int | None = None
    ) -> Screenshot:
        """Capture a page. The default viewport is 1330 x 780 pixels.

        The instance accepts a ``width`` and a ``height`` of 1 to 4000 pixels.
        It sends :class:`ValidationError` for another value.
        """
        spec = RequestSpec("POST", "/v1/screenshots", json=_screenshot_body(url, width, height))
        return Screenshot.from_dict(_object(unwrap_data(await self._client._json(spec))))


class AsyncMediaLibrary:
    """Upload images to the media library and list them."""

    def __init__(self, client: AsyncSnapsbrew) -> None:
        self._client = client

    async def list(self, *, page: int = 1) -> MediaPage:
        """Return one page of images, 12 for each page, newest first."""
        spec = RequestSpec("GET", "/v1/media", params=[("page", str(page))], idempotent=True)
        return MediaPage.from_dict(_object(await self._client._json(spec)))

    async def upload(self, file: FileInput, *, filename: str | None = None) -> Media:
        """Upload an image. See :meth:`MediaLibrary.upload`."""
        spec = RequestSpec("POST", "/v1/media", files=_upload_files(file, filename))
        return Media.from_dict(_object(unwrap_data(await self._client._json(spec))))


class AsyncGuides:
    """Read the static guide catalogs. A guide call does not go into the usage log."""

    def __init__(self, client: AsyncSnapsbrew) -> None:
        self._client = client

    async def _get(self, path: str) -> Any:
        return unwrap_data(await self._client._json(RequestSpec("GET", path, idempotent=True)))

    async def design(self) -> Any:
        """Return the design guide."""
        return await self._get("/v1/guides/design")

    async def layers(self) -> Any:
        """Return the layer schema."""
        return await self._get("/v1/guides/layers")

    async def variant_properties(self) -> Any:
        """Return each property that a variant can set."""
        return await self._get("/v1/guides/variant-properties")

    async def editor_document(self) -> Any:
        """Return the contract of the v2 editor document."""
        return await self._get("/v1/guides/editor-document")

    async def platforms(self) -> Any:
        """Return one line for each platform."""
        return await self._get("/v1/guides/platforms")

    async def platform(self, key: str) -> Any:
        """Return the full guide of one platform."""
        return await self._get(f"/v1/guides/platforms/{_segment(key, 'key')}")

    async def purposes(self) -> Any:
        """Return one line for each image purpose."""
        return await self._get("/v1/guides/purposes")

    async def purpose(self, key: str) -> Any:
        """Return the full guide of one image purpose."""
        return await self._get(f"/v1/guides/purposes/{_segment(key, 'key')}")


class AsyncForms:
    """Submit an embedded form.

    A form renders on the account of its owner, so the client sends no token
    to the submit URL. Copy the submit URL of the form from your instance. The
    URL carries its own signature.
    """

    def __init__(self, client: AsyncSnapsbrew) -> None:
        self._client = client

    async def submit(self, url: str, layers: Mapping[str, FormValue]) -> Snap | builtins.list[Snap]:
        """Send the layers of a form and return the snap.

        A template form returns one snap. A collection form returns a list of
        snaps, and its layer keys are ``"{template uuid}__{layer key}"``. A
        ``str`` value is text. A path, bytes or a binary file object is an image.

        Raises:
            NotFoundError: The signature is not valid, or the form does not exist.
            RateLimitError: Too many submissions. ``code`` is ``"rate_limited"``.
            ValueError: ``url`` is not an absolute URL.
        """
        return _form_result(await self._client._send(_form_spec(url, layers)))
