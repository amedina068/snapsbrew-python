# snapsbrew

[![CI](https://github.com/amedina068/snapsbrew-python/actions/workflows/ci.yml/badge.svg)](https://github.com/amedina068/snapsbrew-python/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/amedina068/snapsbrew-python/badge)](https://scorecard.dev/viewer/?uri=github.com/amedina068/snapsbrew-python)

The Python client for Snapsbrew. Snapsbrew renders images ("snaps") from templates.

Snapsbrew is self-hosted. Each client connects to one Snapsbrew instance, so the URL of your instance is a required setting.

Read the overview of all Snapsbrew SDKs at <https://snapsbrew.com/docs/sdks/overview>.

```python
from snapsbrew import Snapsbrew, Text, Image

client = Snapsbrew(base_url="https://snapsbrew.example.com", token="...")

snap = client.snaps.create(
    "044ec825-ee2f-4d06-bb77-98663e27f529",
    variants=[Text("title", "Hello"), Image("cover", "https://example.com/cover.jpg")],
)
print(snap.media_url)
```

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Variants](#variants)
- [Resources](#resources)
- [Async client](#async-client)
- [Signed URLs](#signed-urls)
- [Webhooks](#webhooks)
- [Errors](#errors)
- [Retries](#retries)
- [Django and FastAPI](#django-and-fastapi)
- [Supported Python versions](#supported-python-versions)
- [Related projects](#related-projects)
- [Community](#community)
- [License](#license)

## Install

The package is not on PyPI yet. Install it from the repository:

```bash
pip install "git+https://github.com/amedina068/snapsbrew-python.git"
# or
uv add "git+https://github.com/amedina068/snapsbrew-python.git"
```

To install a fixed commit, add `@<commit>` to the URL.

The package has one dependency: [httpx](https://www.python-httpx.org/).

## Quick start

1. Open your Snapsbrew instance and create an API token. The token must have the `api_requests` ability.
2. Find the ID of a template and the keys of its layers:

   ```python
   from snapsbrew import Snapsbrew

   with Snapsbrew(base_url="https://snapsbrew.example.com", token="...") as client:
       for template in client.templates.iter():
           print(template.uuid, template.title)
           for layer in template.layers:
               print("  ", layer.layer, layer.available_modifications)
   ```

3. Preview the snap. A preview returns watermarked HTML and stores nothing:

   ```python
   html = client.snaps.preview(template_id, variants=[Text("title", "Hello")])
   ```

4. Render the snap:

   ```python
   snap = client.snaps.create(template_id, variants=[Text("title", "Hello")])
   print(snap.media_url)
   ```

The instance always renders the **published** version of a template. A draft edit does not show until you publish the template.

## Configuration

```python
import httpx
from snapsbrew import Snapsbrew

client = Snapsbrew(
    base_url="https://snapsbrew.example.com",  # default: $SNAPSBREW_URL
    token="...",  # default: $SNAPSBREW_TOKEN
    timeout=60.0,  # seconds, or an httpx.Timeout. None: no timeout
    max_retries=2,  # 0 stops all retries
)
```

| Setting | Default | Description |
|---|---|---|
| `base_url` | `$SNAPSBREW_URL` | The URL of your instance. The client removes a trailing `/` and a trailing `/api`. |
| `token` | `$SNAPSBREW_TOKEN` | An API token. The client sends it as `Authorization: Bearer <token>`. Each API call needs it. Only `forms.submit()` works without a token. If the client has no token, each other call raises `ValueError` before it sends the request. |
| `timeout` | 60 seconds | The timeout of each request. A synchronous render can take that long. The other SDKs use the same value. |
| `max_retries` | 2 | The number of retries. Read [Retries](#retries). |
| `http_client` | a new `httpx.Client` | Your own `httpx.Client`. |

Use the client as a context manager. The context manager closes the connections. If you do not use it, call `client.close()`.

To use a proxy, custom headers or other transport settings, give your own `httpx.Client`. The client uses the timeout of your `httpx.Client`, unless you also give `timeout`. The client does not close an `httpx.Client` that you give:

```python
http = httpx.Client(proxy="http://proxy.internal:3128", timeout=60.0)
client = Snapsbrew(base_url="https://snapsbrew.example.com", token="...", http_client=http)
```

## Variants

A variant changes one layer of the template. Use the typed classes:

| Class | API field | Example |
|---|---|---|
| `Text(layer, text)` | `text` | `Text("title", "Hello")` |
| `Image(layer, url)` | `image_url` | `Image("cover", "https://example.com/a.jpg")` |
| `BackgroundColor(layer, color)` | `background_color` | `BackgroundColor("bg", "#f0573f")` |
| `QRCode(layer, content)` | `qr_content` | `QRCode("qr", "https://example.com")` |
| `Barcode(layer, content)` | `barcode_content` | `Barcode("code", "4006381333931")` |
| `Hidden(layer)` | `hidden` | `Hidden("badge")` |

You can also give plain dicts in the format of the API. You can mix the two:

```python
variants = [Text("title", "Hello"), {"layer": "cover", "image_url": "https://example.com/a.jpg"}]
```

An image URL must be public. The instance refuses a private, loopback or link-local address.

## Resources

### Account

```python
account = client.account()  # GET /v1/auth
print(account.email, account.company)
```

### Templates

```python
page = client.templates.list()  # one page
page = client.templates.list(cursor=page.next_cursor)
for template in client.templates.iter():  # all pages
    ...
template = client.templates.get(template_id)  # layers and publish state
sizes = client.templates.sizes()  # canvas size presets
```

Write and publish a template:

```python
summary = client.templates.create(
    "Launch card",
    size="open_graph",  # or width=1200, height=630
    layers=[{"key": "title", "type": "text", "properties": [{"name": "text", "value": "Hi"}]}],
    groups=[{"id": "header", "name": "Header", "visible": True, "order": 0}],
)
summary = client.templates.update(summary.uuid, title="Launch card v2")  # title is required
summary = client.templates.update(summary.uuid, title="Launch card v2", groups=None)  # no groups
published = client.templates.publish(summary.uuid)  # snaps render this version
html = client.templates.preview(summary.uuid, [Text("title", "Hello")])
tags = client.templates.set_tags(summary.uuid, [1, 2])  # replaces all tags
client.templates.delete(summary.uuid)
```

- `guides.layers()` gives the layer vocabulary. `LayerDefinition` and `LayerGroup` give the shapes for a type checker.
- `create()` and `update()` return a `TemplateSummary` with `uuid`, `title`, `size`, `width`, `height` and `created_at`. A write that sends `size` sets the width and the height.
- In `update()`, a field that you do not give keeps its value. `groups=None` removes each group.
- `update()` and `delete()` accept the UUID or the numeric id of the template.
- `update()` raises `ConflictError` with the code `LEGACY_EDIT_REJECTED_FOR_V2` for a template that uses the v2 editor document. Use `client.documents` for it.
- Snaps render only the published version. A repeat of `publish()` with no new edits creates no new version.

> **CAUTION:** `delete()` also deletes the snaps, the images, the versions and the forms of the template. You cannot undo it.

### Editor documents

`client.documents` reads and writes the v2 editor document of a template. Each write sends the `revision` of your last read:

```python
from snapsbrew import ConflictError

current = client.documents.get(template_id)  # current.document is None when there is no draft
try:
    current = client.documents.apply(
        template_id,
        revision=current.revision,
        operations=[
            {
                "operation": "set_layer_property",
                "layer_key": "title",
                "property": "fontWeight",
                "value": 700,
            },
            {"operation": "set_layer_type", "layer_key": "logo", "type": "image"},
        ],
    )
except ConflictError as error:
    # Another write changed the document. Apply your change again to error.current_document.
    print(error.current_revision, error.current_document)

current = client.documents.replace(template_id, revision=current.revision, document=new_document)
preflight = client.documents.preflight(template_id)
for issue in preflight.issues:  # preflight.ok is True when the list is empty
    print(issue.code, issue.path, issue.message)
```

- `apply()` takes 1 to 100 operations. They all apply, or none applies.
- `replace()` sends the whole document. A layer or a property that you leave out is removed.
- If the document refuses an operation, `apply()` raises `ValidationError`. Its `code` names the rule, for example `editor_operation_layer_not_found`, and `errors` is empty.
- The client does not retry a document write.
- Run `preflight()` before `templates.publish()`. An empty list does not prove that the render looks correct.

### Tags

```python
tags = client.tags.list(search="launch")  # up to 15 tags, sorted by name
tag = client.tags.create("Launch")  # the instance makes the slug
client.templates.set_tags(template_id, [tag.id])
```

### Snaps

```python
# Render now. The response has the image URL.
snap = client.snaps.create(template_id, variants, format="webp")

# Queue the render. The instance posts the result to the webhook.
snap = client.snaps.create(template_id, variants, webhook_url="https://example.com/hooks/snap")

# Render one snap for each template of a collection.
snaps = client.snaps.create_from_collection(collection_id, variants)

# Watermarked HTML preview. It stores nothing. The instance allows 10 previews a minute.
html = client.snaps.preview(template_id, variants)
```

`format` is `"png"` (default), `"jpeg"` or `"webp"`. `type` is `"image"` (default) or `"pdf"`. `transparent=True` works with PNG and WebP only.

If a request can time out, give an `idempotency_key`. The instance keeps the key for 24 hours. A second request with the same key returns the same snap and renders nothing. Then `snap.replayed` is `True`.

```python
snap = client.snaps.create(template_id, variants, idempotency_key="order-1042-card")
```

A key belongs to one kind of request. A key that a batch used raises `ConflictError` on `snaps.create()`, and the reverse is also true. Use a new key for each kind.

A `template_id` that does not exist in your company raises `ValidationError` with `errors["template_id"]`, not `NotFoundError`.

`snap.last_error` is `None`, or one of these codes:

| Code | Constant | Cause |
|---|---|---|
| `render_failed` | `RENDER_FAILED` | The render failed. The status is `failed`. |
| `webhook_redirect_refused` | `WEBHOOK_REDIRECT_REFUSED` | The webhook receiver sent a redirect. The instance does not follow it. |
| `webhook_unreachable` | `WEBHOOK_UNREACHABLE` | The instance did not get a response from the webhook receiver. |
| `webhook_http_<status>` | `WEBHOOK_HTTP_PREFIX` | The webhook receiver sent this error status, for example `webhook_http_500`. |

A webhook code means that the snap rendered, but the webhook did not arrive. `batch_item.last_error` is `None` or `render_failed`.

### Batches

A batch renders up to 100 snaps from one template in the background:

```python
batch = client.batches.create(
    template_id,
    items=[
        {"identifier": "row-1", "variants": [Text("title", "One")]},
        [Text("title", "Two")],  # an item can also be a list of variants
    ],
    webhook_url="https://example.com/hooks/batch",
)

batch = client.batches.wait(batch.uuid)  # gets the batch every 5 seconds
for item in batch.items:
    print(item.identifier, item.status, item.media_url)

client.batches.cancel(batch.uuid)  # stops the items that did not start
```

A batch with the status `completed` rendered at least one item. Read `batch.failed` too.

### Screenshots

```python
shot = client.screenshots.create("https://example.com", width=1280, height=720)
shot = client.screenshots.get(shot.id)
for shot in client.screenshots.iter():
    print(shot.id, shot.image_url)
```

The list, the read and the create all give `image_url`, the URL of the captured image. It is `None` when the capture has no stored image.

The instance accepts a `width` and a `height` of 1 to 4000 pixels. The client does not check them. The instance sends `ValidationError` for another value.

### Media

```python
media = client.media.upload("logo.png")  # a path
media = client.media.upload(data, filename="logo.png")  # bytes
page = client.media.list(page=1)  # 12 images for each page
print(media.src)  # use this URL as the image_url of a variant
```

A `Media` has `id`, `uuid`, `name`, `file_name`, `mime_type`, `size`, `original_url`, `src` and `created_at`.

The instance accepts JPG, JPEG, PNG, GIF, WebP and BMP files of 10 MB maximum. It refuses SVG. The client does not check the file. The instance sends `ValidationError` for a file that breaks a rule.

### Embedded forms

An embedded form renders a snap from the values that a visitor sends. The form renders on the account of its owner, so the client sends no token to the submit URL. A client with no token can submit a form. Copy the submit URL of the form from your instance. The URL carries its own signature.

```python
snap = client.forms.submit(submit_url, {"headline": "Hello", "photo": Path("photo.png")})
snaps = client.forms.submit(collection_submit_url, {"141e8454-...__headline": "Hello"})  # A list
```

- A `str` value is text. A path, bytes or a binary file object is an image.
- A template form uses the layer key, for example `headline`. A collection form uses `{template uuid}__{layer key}` and returns a list of snaps.
- If the signature is not valid, or the form does not exist, `submit()` raises `NotFoundError`.
- If one IP address or one form sends too many submissions in one minute, `submit()` raises `RateLimitError` with the code `rate_limited`. The client retries it.
- The client does not retry a submit after a 5xx, because each submit renders a snap.

### Guides

The guides are static catalogs. You can keep a response in a cache.

```python
client.guides.design()
client.guides.layers()
client.guides.variant_properties()
client.guides.editor_document()
client.guides.platforms()
client.guides.platform("instagram")
client.guides.purposes()
client.guides.purpose("link_preview")
```

A platform or a purpose that does not exist raises `NotFoundError`. Its `available` has the valid keys:

```python
from snapsbrew import NotFoundError

try:
    client.guides.platform("myspace")
except NotFoundError as error:
    print(error.available)  # ["instagram", "facebook", "x", ...]
```

### Response models

Each response is a frozen dataclass: `Account`, `Template`, `TemplateSummary`, `PublishedTemplate`, `Layer`, `TemplateSize`, `EditorDocument`, `Preflight`, `PreflightIssue`, `Tag`, `Snap`, `Batch`, `BatchItem`, `Screenshot`, `Media`, `Page` and `MediaPage`. The `raw` field of a model holds the JSON object from the instance. Use it to read a field that this version of the package does not know.

## Async client

`AsyncSnapsbrew` has the same resources and methods as `Snapsbrew`:

```python
import asyncio
from snapsbrew import AsyncSnapsbrew, Text


async def main() -> None:
    async with AsyncSnapsbrew(base_url="https://snapsbrew.example.com", token="...") as client:
        snap = await client.snaps.create(template_id, [Text("title", "Hello")])
        async for template in client.templates.iter():
            print(template.title)


asyncio.run(main())
```

Close an async client with `await client.aclose()`, or use `async with`. You can give your own `httpx.AsyncClient` as `http_client`.

## Signed URLs

A signed URL renders an image from a plain `<img src>` or an `og:image` tag. The page does not call the API. The instance renders the image on the first request and keeps it in a cache.

> **WARNING:** The signing key is a secret. Make signed URLs only on your server. Do not send the key to a browser.

1. Open your instance and create a signed URL key.
2. Keep the key in a server setting, for example `SNAPSBREW_SIGNING_KEY`.
3. Make the URL on the server:

```python
import os
from snapsbrew import signed_url, Text, Image

url = signed_url(
    base_url="https://snapsbrew.example.com",
    key=os.environ["SNAPSBREW_SIGNING_KEY"],
    template_id="044ec825-ee2f-4d06-bb77-98663e27f529",
    variants=[Text("title", "Dark Avengers"), Image("cover", "https://example.com/b.jpg")],
    format="webp",
)
# https://snapsbrew.example.com/signed-url/image.jpg?template_id=...&format=webp&variants=...&signature=...
```

| Argument | Description |
|---|---|
| `format` | `"png"` (default), `"jpeg"` or `"webp"`. |
| `transparent` | `True` for a transparent background. PNG and WebP only. |
| `params` | Other query parameters. The renderer ignores them, but they are part of the signature and of the cache key. To get a new image for the same content, add a value, for example `{"v": 2}`. The names `identifier` and `api_log_uuid` are reserved. The builder refuses them. |

The instance keeps each image in a cache by its full URL. The same URL returns the same image and does not render it again. If you publish a new version of the template, the instance renders the image again.

A signed URL accepts any active signed URL key of the company that owns the template.

A URL with a bad signature, or for a template that does not exist, does not return an error status. The instance returns its placeholder image with the status 200. If you see the placeholder, make sure that the key belongs to the company of the template. A reserved parameter in the URL gets the status 400. Too many requests get the status 429.

The signature is the HMAC-SHA256 hex digest of the query parameters, without `signature`. The parameters are sorted by key and joined as `key=value` with `&`. The `variants` value is standard base64 of the JSON array. `sign()`, `canonical_string()` and `encode_variants()` give each step, if you need them.

## Webhooks

An async snap and a batch post a webhook to their `webhook_url`. The instance signs each webhook with the webhook signing secret of your company. **Account > Developers** shows the secret and rotates it.

> **WARNING:** The webhook signing secret is a secret. Verify webhooks only on your server. Do not send the secret to a browser.

```python
from snapsbrew import SNAP_COMPLETED, SNAP_FAILED, WebhookVerificationError, verify_webhook

try:
    event = verify_webhook(raw_body, headers, secret)
except WebhookVerificationError as error:
    print(error.reason)  # "signature", "timestamp" or "payload"
    raise

if event.type == SNAP_COMPLETED:
    print(event.snap.media_url)
elif event.type == SNAP_FAILED:
    print(event.snap.last_error)  # "render_failed"
```

1. Give the raw request body, byte for byte. Do not parse the JSON and encode it again. The instance escapes `/` and non-ASCII characters, so a new encoding gives other bytes.
2. Give the request headers. The header names are not case-sensitive.
3. Give the full secret, with its `whsec_` prefix.

`error.reason` tells why the verification failed. The JS, PHP and Ruby SDKs use the same three reasons:

| `reason` | Cause |
|---|---|
| `"signature"` | The signature header is missing, or the signature does not match the body. |
| `"timestamp"` | The timestamp header is missing, is not Unix seconds, or is outside the tolerance. |
| `"payload"` | The signature is valid, but the body is not a JSON object. |

The signature can be lowercase or uppercase hex.

`verify_webhook()` compares the signature in constant time. It refuses a timestamp that is more than 300 seconds from the current time. To change this limit, give `tolerance` in seconds. In a test, give `now` as the current Unix time:

```python
event = verify_webhook(raw_body, headers, secret, tolerance=600)
event = verify_webhook(raw_body, headers, secret, now=1767225600)
```

`verify_webhook()` returns a `WebhookEvent`:

| Field | Value |
|---|---|
| `type` | The `event` field of the body. |
| `delivery_id` | The `X-Snapsbrew-Delivery` header. All attempts of one delivery have the same value. `None` when an older instance sends no delivery header. |
| `timestamp` | The `X-Snapsbrew-Timestamp` header, in Unix seconds. |
| `data` | The decoded body. |
| `snap` | A `Snap`, for a `snap.*` event. Else `None`. |
| `batch` | A `Batch` with the counts, for a `snap-import.*` event. Else `None`. |

The instance can send one delivery more than one time. Keep each `delivery_id` and ignore a delivery that you received before.

| Event | Constant | Body |
|---|---|---|
| `snap.completed` | `SNAP_COMPLETED` | `snap` |
| `snap.failed` | `SNAP_FAILED` | `snap`, with `status` `failed`, `last_error` `render_failed` and an empty `media_url` |
| `snap-import.completed` | `SNAP_IMPORT_COMPLETED` | `import` (the batch counts) and `template` (`uuid` and `title`) |
| `snap-import.failed` | `SNAP_IMPORT_FAILED` | `import` and `template` |
| `snap-import.canceled` | `SNAP_IMPORT_CANCELED` | `import` and `template` |

For a failed snap, `event.snap.media_url` is an empty string, the value that the instance sends. A new instance version can send a new event. Make your code accept an event type that it does not know.

To make a signed webhook in your own tests, use `sign()`:

```python
from snapsbrew.webhooks import sign

headers = {
    "X-Snapsbrew-Delivery": "3f2b6c1e-8a4d-4e5f-9b0a-1c2d3e4f5a6b",
    "X-Snapsbrew-Timestamp": "1767225600",
    "X-Snapsbrew-Signature": sign("1767225600", body, "whsec_test"),
}
```

## Errors

All errors come from `SnapsbrewError`:

```text
SnapsbrewError
├── APIConnectionError        the client did not get a response
│   └── APITimeoutError       the request took more time than the timeout
├── APIError                  the instance sent an error response
│   ├── BadRequestError       400
│   ├── AuthenticationError   401: the token is missing or not valid
│   ├── AuthorizationError    403: the token cannot do this action
│   ├── NotFoundError         404: .available has the valid guide keys
│   ├── ConflictError         409: .code, .retryable, .current_revision, .current_document
│   ├── ValidationError       422: .errors has the field errors, .code has a rule code
│   ├── RateLimitError        429: .retry_after, .limit and .remaining
│   └── ServerError           5xx
├── WaitTimeoutError          batches.wait() did not see a terminal status in time
└── WebhookVerificationError  .reason is "signature", "timestamp" or "delivery"
```

Each `APIError` has `status_code`, `message`, `body`, `code`, `request_id` and `response`. Give `request_id` to support when you report a problem.

`AuthorizationError` (403) means that the token has no `api_requests` ability, or that a permission check refused the action. Each operation can send 403. For a token without the ability, the message is `Invalid ability provided.`

`NotFoundError` (404) means that the record does not exist in your company. Do not read its message to find the cause. The text can change.

`ConflictError` (409) has a `code`. The package exports a constant for each code:

| `code` | Cause | Can a repeat work? |
|---|---|---|
| `IDEMPOTENCY_KEY_IN_PROGRESS` | Another request with the same key runs now. | Yes, with the same key. The client retries it. |
| `IDEMPOTENCY_KEY_BELONGS_TO_BATCH` | `snaps.create()` sent a key that a batch owns. | No. Send a new key. |
| `IDEMPOTENCY_KEY_BELONGS_TO_SNAP` | `batches.create()` sent a key that a single snap owns. | No. Send a new key. |
| `EDITOR_DOCUMENT_CONFLICT` | Another write changed the editor document after your last read. | Yes, after you apply your change to `current_document` and send `current_revision`. |
| `LEGACY_EDIT_REJECTED_FOR_V2` | `templates.update()` on a template that uses the v2 editor document. | No. Use `client.documents`. |

In each case, the instance saved nothing.

`ServerError` (5xx) from `POST /v1/snaps` or `POST /v1/snaps/batches` has the code `INTERNAL_ERROR` and a fixed message. The body holds no details of the fault. Give `request_id` to support.

```python
from snapsbrew import ConflictError, RateLimitError, ValidationError

try:
    snap = client.snaps.create(template_id, variants, idempotency_key=key)
except ValidationError as error:
    for field, messages in error.errors.items():
        print(field, messages)
except ConflictError as error:
    if not error.retryable:
        print("Use a new key:", error.code)
except RateLimitError as error:
    print("Wait", error.retry_after, "seconds")
```

An argument that breaks a rule of the API before the request, for example an empty template ID, raises `ValueError` or `TypeError`.

## Retries

The client retries a failed request two times by default. The wait before retry 1, 2, 3 and more is 0.5, 1, 2 ... seconds, to a maximum of 8 seconds. Half of each wait is random. The JS, PHP and Ruby SDKs use the same rules.

| Failure | Idempotent request | Other request |
|---|---|---|
| 429 | Retry | Retry |
| 409 `idempotency_key_in_progress` | Retry (a request with a key only) | No retry |
| Other 409 | No retry | No retry |
| 5xx | Retry | No retry |
| Connection not made (DNS, refused, connect timeout, pool timeout) | Retry | Retry |
| Read timeout or dropped connection | Retry | No retry |
| Other 4xx | No retry | No retry |

These requests are idempotent:

- Each `GET` and each `DELETE`, for example `templates.delete()`. After a lost response, a retried `templates.delete()` raises `NotFoundError`, because the first request removed the template.
- `templates.publish()`, `templates.set_tags()` and `batches.cancel()`.
- `snaps.create()` and `batches.create()` with an `idempotency_key`.

The other requests are not idempotent: `templates.create()`, `templates.update()`, `snaps.create()` and `batches.create()` with no key, `screenshots.create()`, `media.upload()`, `tags.create()` and `forms.submit()`. An editor document write (`documents.replace()` and `documents.apply()`) is never retried after a 5xx or a timeout, because a repeat gets a 409.

- If a response has a `Retry-After` header, the client waits for that time.
- If `Retry-After` is more than 60 seconds, the client does not wait. It raises the error at once.
- The API allows 60 requests per minute for one user. A preview also has a limit of 10 per minute. Each response has the headers `X-RateLimit-Limit` and `X-RateLimit-Remaining`.
- If another request holds the same idempotency key, the client waits with the normal backoff and sends the request again. If the other request does not finish before the last retry, the client raises `ConflictError`.
- Set `max_retries=0` to stop all retries.

## Django and FastAPI

The package has no framework code. The examples below show how to connect it.

### Django: a template tag for an `og:image`

Put the instance URL and the signing key in `settings.py`:

```python
# settings.py
SNAPSBREW_URL = env("SNAPSBREW_URL")
SNAPSBREW_SIGNING_KEY = env("SNAPSBREW_SIGNING_KEY")
```

Make a template tag in one of your apps, for example `blog/templatetags/snapsbrew.py`:

```python
from django import template
from django.conf import settings
from snapsbrew import Text, signed_url

register = template.Library()


@register.simple_tag
def snap_image(template_id: str, **layers: str) -> str:
    return signed_url(
        base_url=settings.SNAPSBREW_URL,
        key=settings.SNAPSBREW_SIGNING_KEY,
        template_id=template_id,
        variants=[Text(layer, value) for layer, value in layers.items()],
    )
```

Use the tag in a template. Django escapes the URL in the attribute:

```django
{% load snapsbrew %}
<meta property="og:image" content="{% snap_image 'TEMPLATE_UUID' title=post.title %}">
```

### Django: a view that receives webhooks

Put the secret in `settings.py` as `SNAPSBREW_WEBHOOK_SECRET`. The instance does not send a CSRF token, so the view must be `csrf_exempt`:

```python
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from snapsbrew import SNAP_COMPLETED, WebhookVerificationError, verify_webhook


@csrf_exempt
@require_POST
def snapsbrew_webhook(request: HttpRequest) -> HttpResponse:
    try:
        event = verify_webhook(request.body, request.headers, settings.SNAPSBREW_WEBHOOK_SECRET)
    except WebhookVerificationError:
        return HttpResponseBadRequest()

    # delivery_id is None when an older instance sends no delivery header.
    if event.type == SNAP_COMPLETED and not already_seen(event.delivery_id):
        save_image(event.snap.id, event.snap.media_url)
    return HttpResponse(status=204)
```

`request.body` is the raw body, and `request.headers` is not case-sensitive.

### FastAPI: one client for the application

Make one `AsyncSnapsbrew` when the application starts, and close it when the application stops. Then give it to each route with dependency injection:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from snapsbrew import AsyncSnapsbrew, Text


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Reads SNAPSBREW_URL and SNAPSBREW_TOKEN from the environment.
    async with AsyncSnapsbrew() as client:
        app.state.snapsbrew = client
        yield


app = FastAPI(lifespan=lifespan)


def get_snapsbrew(request: Request) -> AsyncSnapsbrew:
    return request.app.state.snapsbrew


SnapsbrewClient = Annotated[AsyncSnapsbrew, Depends(get_snapsbrew)]


@app.post("/cards")
async def create_card(title: str, snapsbrew: SnapsbrewClient) -> dict[str, str | None]:
    snap = await snapsbrew.snaps.create("TEMPLATE_UUID", [Text("title", title)])
    return {"url": snap.media_url}
```

In a test, replace the dependency with `app.dependency_overrides[get_snapsbrew]`.

Receive webhooks in a route. Read the raw body with `await request.body()`:

```python
import os

from fastapi import HTTPException, Request, Response
from snapsbrew import SNAP_COMPLETED, WebhookVerificationError, verify_webhook

WEBHOOK_SECRET = os.environ["SNAPSBREW_WEBHOOK_SECRET"]


@app.post("/hooks/snapsbrew", status_code=204)
async def snapsbrew_webhook(request: Request) -> Response:
    try:
        event = verify_webhook(await request.body(), request.headers, WEBHOOK_SECRET)
    except WebhookVerificationError as error:
        raise HTTPException(status_code=400, detail=error.reason) from error

    # delivery_id is None when an older instance sends no delivery header.
    if event.type == SNAP_COMPLETED and not already_seen(event.delivery_id):
        save_image(event.snap.id, event.snap.media_url)
    return Response(status_code=204)
```

## Supported Python versions

The package supports Python 3.10, 3.11, 3.12, 3.13 and 3.14. CI runs the tests, the lint and the type check on each version.

The package has full type hints and a `py.typed` file. `mypy --strict` passes on the package.

## Related projects

- [Snapsbrew](https://github.com/amedina068/snapsbrew): the self-hosted app that this SDK calls. It uses the AGPL-3.0.
- [Documentation](https://snapsbrew.com/docs): the guides for the app and the SDKs. The source is in [snapsbrew-docs](https://github.com/amedina068/snapsbrew-docs).
- [SDK overview](https://snapsbrew.com/docs/sdks/overview): the install steps and the features of each SDK.
- SDKs for other languages: [TypeScript](https://github.com/amedina068/snapsbrew-js), [PHP](https://github.com/amedina068/snapsbrew-php), [Ruby](https://github.com/amedina068/snapsbrew-ruby).

## Community

- [CONTRIBUTING.md](CONTRIBUTING.md): how to set up the code and open a pull request.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md): the rules for issues, pull requests, and reviews.
- [SECURITY.md](SECURITY.md): how to report a security problem in private.
- [CHANGELOG.md](CHANGELOG.md): the changes in each version.

Report a problem with the SDK in the issues of this repository. Report a problem with the app in the [Snapsbrew issues](https://github.com/amedina068/snapsbrew/issues).

## License

This SDK is available under the [MIT License](LICENSE). You can use it in closed source code. The Snapsbrew app uses the AGPL-3.0. That license does not cover this SDK.
