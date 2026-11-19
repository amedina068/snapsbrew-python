# Changelog

All notable changes to this package are in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The package uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - Unreleased

This version adopts the OpenAPI spec of Snapsbrew PR #93 and the webhook signatures of Snapsbrew PR #95.

### Added

- Template writes: `templates.create()`, `templates.update()`, `templates.delete()`, `templates.publish()`, `templates.preview()` and `templates.set_tags()`.
- The `groups` field of `templates.create()` and `templates.update()`. In `update()`, `groups=None` removes each group.
- The editor document resource `client.documents`: `get()`, `replace()`, `apply()` and `preflight()`.
- The tag resource `client.tags`: `list()` and `create()`.
- The models `TemplateSummary`, `PublishedTemplate`, `EditorDocument`, `Preflight`, `PreflightIssue` and `Tag`.
- The request shapes `LayerDefinition`, `LayerProperty`, `LayerGroup`, `SetLayerProperty`, `SetLayerType` and `EditorOperation`, as `TypedDict` classes.
- `ConflictError.current_revision` and `ConflictError.current_document`, for an editor document conflict.
- The conflict code constants `EDITOR_DOCUMENT_CONFLICT` and `LEGACY_EDIT_REJECTED_FOR_V2`.
- `NotFoundError.available`: the valid keys when `guides.platform()` or `guides.purpose()` gets a key that does not exist.
- The `last_error` code constants `RENDER_FAILED`, `WEBHOOK_REDIRECT_REFUSED`, `WEBHOOK_UNREACHABLE` and `WEBHOOK_HTTP_PREFIX`.
- The webhook verifier `verify_webhook()`. It checks `X-Snapsbrew-Signature` in constant time and refuses a timestamp more than `tolerance` seconds (300 by default) from the current time. It returns a `WebhookEvent` with `type`, `delivery_id`, `timestamp`, `data`, `snap` and `batch`.
- `WebhookVerificationError`, with the `reason` `"signature"`, `"timestamp"` or `"delivery"`.
- The webhook event constants `SNAP_COMPLETED`, `SNAP_FAILED`, `SNAP_IMPORT_COMPLETED`, `SNAP_IMPORT_FAILED` and `SNAP_IMPORT_CANCELED`.
- `snapsbrew.webhooks.sign()`, to make a signed webhook in a test.
- The webhook vectors of the app in the test suite.
- README sections for template writes, editor documents, tags and webhooks, and webhook receivers for Django and FastAPI.

### Changed

- `Snap.media_url` is `None` when the instance sends an empty string. The webhook of a failed snap sends an empty string.
- `ValidationError` documents a 422 with a `code` and no field errors. `documents.apply()` sends it when the document refuses an operation.
- `AuthorizationError` documents that each operation can send 403 with the message `Invalid ability provided.`
- `NotFoundError` documents that the text of a 404 message can change.
- The docstrings and the README document the request rules of `media.upload()` and `screenshots.create()`. The client does not check them.
- The README says that a signed URL accepts any active key of the company of the template, and that the builder refuses the reserved parameters `identifier` and `api_log_uuid`.
- The README links to the SDK overview at <https://snapsbrew.com/docs/sdks/overview>.

### Removed

- The text that says that a render costs a credit. The instance keeps a usage log with no balance.

## [0.1.0] - Unreleased

### Added

- The sync client `Snapsbrew` and the async client `AsyncSnapsbrew`, built on httpx. Both clients have the same resources and methods.
- The settings `base_url`, `token`, `timeout`, `max_retries` and `http_client`. `SNAPSBREW_URL` and `SNAPSBREW_TOKEN` are the defaults.
- The account endpoint: `whoami()`.
- Templates: `list()`, `iter()`, `get()` and `sizes()`.
- Snaps: `create()`, `create_from_collection()` and `preview()`.
- Batches: `create()`, `get()`, `cancel()` and `wait()`.
- Screenshots: `list()`, `iter()`, `get()` and `create()`.
- Media: `list()` and `upload()`.
- Guides: `design()`, `layers()`, `variant_properties()`, `editor_document()`, `platforms()`, `platform()`, `purposes()` and `purpose()`.
- Typed variants: `Text`, `Image`, `BackgroundColor`, `QRCode`, `Barcode` and `Hidden`. Plain dicts also work.
- Frozen dataclass response models with a `raw` field.
- The signed URL builder `signed_url()`, with `sign()`, `canonical_string()` and `encode_variants()`.
- An error class for each failure, under `SnapsbrewError`.
- Retries for 429, 5xx and connection errors, with exponential backoff, jitter and `Retry-After`.
- Type hints and a `py.typed` file.
- `ConflictError.retryable` and the code constants `IDEMPOTENCY_KEY_IN_PROGRESS`, `IDEMPOTENCY_KEY_BELONGS_TO_SNAP`, `IDEMPOTENCY_KEY_BELONGS_TO_BATCH` and `INTERNAL_ERROR`.
- `RateLimitError.limit` and `RateLimitError.remaining`, from the `X-RateLimit-Limit` and `X-RateLimit-Remaining` headers.
- The `Media` fields `uuid`, `name`, `mime_type`, `size`, `original_url` and `created_at`.

### Changed

- The client retries a 409 with the code `idempotency_key_in_progress` when the request has an `idempotency_key`. The wait is the normal backoff, as for a 429. The client does not retry the codes `idempotency_key_belongs_to_snap` and `idempotency_key_belongs_to_batch`.
- `snaps.create()` raises `ConflictError` with the code `idempotency_key_belongs_to_batch` for a key that a batch owns. Before Snapsbrew PR #88, the instance sent a 500.
- `snaps.create()` raises `AuthorizationError` when the instance sends 403. Before Snapsbrew PR #88, the instance sent 401 for a failed authorization.
- `ServerError` reads the new 500 body of `POST /v1/snaps`, with the code `internal_error` and no exception text.
- `Screenshot.image_url` is set for each item of `screenshots.list()`. Before Snapsbrew PR #88, the list read an `image_url` column that the table does not have.
- `MediaPage` reads only the flat Laravel paginator. The `meta` shape of the old spec is gone.
- The `Media` docstring says that the upload and the list send the nine fields of the model and no other field. Before Snapsbrew PR #89, the instance also sent internal fields of the media record, for example `model_type` and `disk`.
- `Screenshot.image_url` is `None` when the capture has no stored image. Before Snapsbrew PR #89, the instance sent an empty string.
- `ServerError` reads the 500 body of `POST /v1/snaps/batches`, with the code `internal_error`. The `INTERNAL_ERROR` docstring names both endpoints.
- The docstrings and the README say that a `template_id` that does not exist raises `ValidationError`, not `NotFoundError`.
- The README says that a signed URL with a bad signature returns the placeholder image with the status 200.

### Removed

- `Layer.type`. The API does not send a layer type.
