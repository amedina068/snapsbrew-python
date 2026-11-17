"""Typed response models.

Each model is a frozen dataclass. The ``raw`` field keeps the decoded JSON
object, so you can read a field that this version of the package does not know.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

__all__ = [
    "Account",
    "Batch",
    "BatchItem",
    "Layer",
    "Media",
    "MediaPage",
    "Page",
    "Screenshot",
    "Snap",
    "Template",
    "TemplateSize",
]

T = TypeVar("T")

BATCH_TERMINAL_STATUSES = frozenset({"completed", "failed", "canceled"})


@dataclass(frozen=True)
class Account:
    """The account that the token belongs to (``GET /v1/auth``)."""

    email: str
    name: str
    company: str | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Account:
        return cls(
            email=_str(data.get("email")),
            name=_str(data.get("name")),
            company=_opt_str(data.get("company")),
            raw=data,
        )


@dataclass(frozen=True)
class Layer:
    """One addressable layer of a template.

    ``available_modifications`` maps each variant property that the layer
    accepts to its current value, for example ``{"text": "Hello"}``. It is
    empty for a layer that accepts no variant, for example an empty layer.
    The API does not send the layer type.
    """

    layer: str
    available_modifications: Mapping[str, Any]
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Layer:
        modifications = data.get("available_modifications")
        return cls(
            layer=_str(data.get("layer")),
            # The app sends `[]`, not `{}`, for a layer with no modifications.
            available_modifications=dict(modifications) if isinstance(modifications, dict) else {},
            raw=data,
        )


@dataclass(frozen=True)
class Template:
    """A reusable design with addressable layers.

    The list endpoint does not send ``size``, ``published_version`` and
    ``has_unpublished_edits``. For a template from a list, these fields are ``None``.
    """

    uuid: str
    title: str
    width: int
    height: int
    layers: tuple[Layer, ...]
    created_at: datetime | None
    size: str | None = None
    published_version: int | None = None
    has_unpublished_edits: bool | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def id(self) -> str:
        """The same value as ``uuid``. Use it as ``template_id``."""
        return self.uuid

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Template:
        layers = data.get("layers")
        return cls(
            uuid=_str(data.get("uuid")),
            title=_str(data.get("title")),
            width=_int(data.get("width")),
            height=_int(data.get("height")),
            layers=tuple(Layer.from_dict(item) for item in _dicts(layers)),
            created_at=_datetime(data.get("created_at")),
            size=_opt_str(data.get("size")),
            published_version=_opt_int(data.get("published_version")),
            has_unpublished_edits=_opt_bool(data.get("has_unpublished_edits")),
            raw=data,
        )


@dataclass(frozen=True)
class TemplateSize:
    """A canvas size preset (``GET /v1/templates/sizes``)."""

    size: str
    name: str
    platform: str
    width: int
    height: int
    aspect_ratio: str
    safe_margin_px: int
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TemplateSize:
        return cls(
            size=_str(data.get("size")),
            name=_str(data.get("name")),
            platform=_str(data.get("platform")),
            width=_int(data.get("width")),
            height=_int(data.get("height")),
            aspect_ratio=_str(data.get("aspect_ratio")),
            safe_margin_px=_int(data.get("safe_margin_px")),
            raw=data,
        )


@dataclass(frozen=True)
class Snap:
    """A render of a template.

    ``media_url`` is ``None`` until the status is ``completed``.
    ``replayed`` is ``True`` when the server returned an earlier snap for the same
    ``idempotency_key`` and rendered nothing.
    ``variants`` is empty when the request sent no variants. ``template_id``,
    ``template_title``, ``width`` and ``height`` are ``None`` for a snap that
    has no source template.
    """

    id: str
    status: str
    type: str
    media_url: str | None
    is_async: bool
    webhook_url: str | None
    completed_at: datetime | None
    last_error: str | None
    variants: tuple[Mapping[str, Any], ...]
    template_id: str | None
    template_title: str | None
    created_at: datetime | None
    width: int | None = None
    height: int | None = None
    request_id: str | None = None
    replayed: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        request_id: str | None = None,
        replayed: bool = False,
    ) -> Snap:
        return cls(
            id=_str(data.get("id")),
            status=_str(data.get("status")),
            type=_str(data.get("type")) or "image",
            media_url=_opt_str(data.get("media_url")),
            is_async=bool(data.get("is_async")),
            webhook_url=_opt_str(data.get("webhook_url")),
            completed_at=_datetime(data.get("completed_at")),
            last_error=_opt_str(data.get("last_error")),
            variants=tuple(_dicts(data.get("variants"))),
            template_id=_opt_str(data.get("template_id")),
            template_title=_opt_str(data.get("template_title")),
            created_at=_datetime(data.get("created_at")),
            width=_opt_int(data.get("width")),
            height=_opt_int(data.get("height")),
            request_id=request_id,
            replayed=replayed,
            raw=data,
        )


@dataclass(frozen=True)
class BatchItem:
    """One snap of a batch."""

    id: str
    identifier: str | None
    status: str
    media_url: str | None
    last_error: str | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BatchItem:
        return cls(
            id=_str(data.get("id")),
            identifier=_opt_str(data.get("identifier")),
            status=_str(data.get("status")),
            media_url=_opt_str(data.get("media_url")),
            last_error=_opt_str(data.get("last_error")),
            raw=data,
        )


@dataclass(frozen=True)
class Batch:
    """A batch of snaps from one template.

    The status is ``pending``, ``processing``, ``completed``, ``failed`` or
    ``canceled``. ``completed`` means that at least one item rendered, so read
    ``failed`` too. ``items`` is empty in the response of a create.
    """

    uuid: str
    title: str
    status: str
    total_rows: int
    processed_rows: int
    completed: int
    pending: int
    failed: int
    canceled: int
    status_url: str | None
    items: tuple[BatchItem, ...] = ()
    request_id: str | None = None
    replayed: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def id(self) -> str:
        """The same value as ``uuid``."""
        return self.uuid

    @property
    def is_finished(self) -> bool:
        """``True`` when the status is terminal. A terminal status never changes."""
        return self.status in BATCH_TERMINAL_STATUSES

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        request_id: str | None = None,
        replayed: bool = False,
    ) -> Batch:
        return cls(
            uuid=_str(data.get("uuid")),
            title=_str(data.get("title")),
            status=_str(data.get("status")),
            total_rows=_int(data.get("total_rows")),
            processed_rows=_int(data.get("processed_rows")),
            completed=_int(data.get("completed")),
            pending=_int(data.get("pending")),
            failed=_int(data.get("failed")),
            canceled=_int(data.get("canceled")),
            status_url=_opt_str(data.get("status_url")),
            items=tuple(BatchItem.from_dict(item) for item in _dicts(data.get("items"))),
            request_id=request_id,
            replayed=replayed,
            raw=data,
        )


@dataclass(frozen=True)
class Screenshot:
    """A capture of a web page.

    ``image_url`` is the URL of the captured image. The list, the read and the
    create all send it. It is ``None`` when the capture has no stored image.
    """

    id: str
    url: str | None
    image_url: str | None
    width: int
    height: int
    created_at: datetime | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Screenshot:
        # The list endpoint sends `uuid`. The other endpoints send `id`.
        return cls(
            id=_str(data.get("id") or data.get("uuid")),
            url=_opt_str(data.get("url")),
            image_url=_opt_str(data.get("image_url")),
            width=_int(data.get("width")),
            height=_int(data.get("height")),
            created_at=_datetime(data.get("created_at")),
            raw=data,
        )


@dataclass(frozen=True)
class Media:
    """An image in the media library of your account.

    Use ``src`` as the ``image_url`` of a variant. The API sends the stored
    media record, so ``raw`` can hold more fields than this model.
    """

    id: int
    file_name: str
    src: str | None
    uuid: str | None = None
    name: str | None = None
    mime_type: str | None = None
    size: int | None = None
    original_url: str | None = None
    created_at: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Media:
        return cls(
            id=_int(data.get("id")),
            file_name=_str(data.get("file_name")),
            src=_opt_str(data.get("src")),
            uuid=_opt_str(data.get("uuid")),
            name=_opt_str(data.get("name")),
            mime_type=_opt_str(data.get("mime_type")),
            size=_opt_int(data.get("size")),
            original_url=_opt_str(data.get("original_url")),
            created_at=_datetime(data.get("created_at")),
            raw=data,
        )


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page of a cursor-paginated list. Iterate over it to get the items."""

    data: tuple[T, ...]
    next_cursor: str | None
    previous_cursor: str | None

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None

    def __iter__(self) -> Iterator[T]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class MediaPage:
    """One page of the media library (12 items for each page, newest first)."""

    data: tuple[Media, ...]
    current_page: int
    last_page: int | None
    per_page: int | None
    total: int | None

    @property
    def has_more(self) -> bool:
        return self.last_page is not None and self.current_page < self.last_page

    def __iter__(self) -> Iterator[Media]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    @classmethod
    def from_dict(cls, body: Mapping[str, Any]) -> MediaPage:
        # The body is a flat Laravel paginator: the page fields sit next to
        # `data`, and there is no `meta` key.
        return cls(
            data=tuple(Media.from_dict(item) for item in _dicts(body.get("data"))),
            current_page=_int(body.get("current_page")) or 1,
            last_page=_opt_int(body.get("last_page")),
            per_page=_opt_int(body.get("per_page")),
            total=_opt_int(body.get("total")),
        )


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _int(value: Any) -> int:
    parsed = _opt_int(value)
    return 0 if parsed is None else parsed


def _opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)


def _dicts(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
