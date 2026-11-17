# Changelog

All notable changes to this package are in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The package uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- The docstrings and the README say that a `template_id` that does not exist raises `ValidationError`, not `NotFoundError`.
- The README says that a signed URL with a bad signature returns the placeholder image with the status 200.

### Removed

- `Layer.type`. The API does not send a layer type.
