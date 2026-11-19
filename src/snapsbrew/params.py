"""The shapes of the request fields for template writes and editor documents.

Each shape is a ``TypedDict``, so you write a plain dict and a type checker
reads its keys::

    groups: list[LayerGroup] = [{"id": "header", "name": "Header", "order": 0}]
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

__all__ = [
    "EditorOperation",
    "LayerDefinition",
    "LayerGroup",
    "LayerProperty",
    "SetLayerProperty",
    "SetLayerType",
]

# Python 3.10 has no `NotRequired`. A base class with the required keys and a
# subclass with `total=False` gives the same shape.


class LayerProperty(TypedDict):
    """One design-time property of a layer, for example ``{"name": "text", "value": "Hi"}``."""

    name: str
    value: Any


class _LayerDefinitionKeys(TypedDict):
    key: str
    properties: list[LayerProperty]


class LayerDefinition(_LayerDefinitionKeys, total=False):
    """One layer of a template write. ``guides.layers()`` gives the vocabulary.

    ``key`` is the name that a variant uses as ``layer``. ``type`` is the editor
    layer type, for example ``"text"``, ``"image"``, ``"qr_code"`` or ``"empty"``.
    """

    type: str


class _LayerGroupKeys(TypedDict):
    id: str


class LayerGroup(_LayerGroupKeys, total=False):
    """One layer group of a template write, in the shape that the editor saves.

    ``id`` has 64 characters maximum. ``name`` has 255 characters maximum.
    """

    name: str | None
    visible: bool
    collapsed: bool
    order: int


class SetLayerProperty(TypedDict):
    """Set one property of one layer. ``value`` is any JSON value that the property accepts."""

    operation: Literal["set_layer_property"]
    layer_key: str
    property: str
    value: Any


class SetLayerType(TypedDict):
    """Change the type of one layer."""

    operation: Literal["set_layer_type"]
    layer_key: str
    type: str


EditorOperation = SetLayerProperty | SetLayerType
"""One operation of ``documents.apply()``."""
