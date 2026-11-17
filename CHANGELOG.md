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
