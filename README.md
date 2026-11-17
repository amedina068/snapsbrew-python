# snapsbrew

The Python client for Snapsbrew. Snapsbrew renders images ("snaps") from templates.

Snapsbrew is self-hosted. Each client connects to one Snapsbrew instance, so the URL of your instance is a required setting.

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
- [Errors](#errors)
- [Retries](#retries)
- [Django and FastAPI](#django-and-fastapi)
- [Supported Python versions](#supported-python-versions)

## Install

The package is not on PyPI yet. Install it from the repository:

```bash
pip install "git+https://github.com/amedina068/snapsbrew-python.git"
# or
uv add "git+https://github.com/amedina068/snapsbrew-python.git"
```

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

3. Preview the snap. A preview is free. It returns watermarked HTML and stores nothing:

   ```python
   html = client.snaps.preview(template_id, variants=[Text("title", "Hello")])
   ```

4. Render the snap. Each render costs one credit:

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
    timeout=30.0,  # seconds, or an httpx.Timeout. None: no timeout
    max_retries=2,  # 0 stops all retries
)
```

| Setting | Default | Description |
|---|---|---|
| `base_url` | `$SNAPSBREW_URL` | The URL of your instance. The client removes a trailing `/` and a trailing `/api`. |
| `token` | `$SNAPSBREW_TOKEN` | An API token. The client sends it as `Authorization: Bearer <token>`. |
| `timeout` | 30 seconds | The timeout of each request. |
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
account = client.whoami()  # GET /v1/auth
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

### Snaps

```python
# Render now. The response has the image URL.
snap = client.snaps.create(template_id, variants, format="webp")

# Queue the render. The instance posts the result to the webhook.
snap = client.snaps.create(template_id, variants, webhook_url="https://example.com/hooks/snap")

# Render one snap for each template of a collection.
snaps = client.snaps.create_from_collection(collection_id, variants)

# Free, watermarked HTML preview. The instance allows 10 previews a minute.
html = client.snaps.preview(template_id, variants)
```

`format` is `"png"` (default), `"jpeg"` or `"webp"`. `type` is `"image"` (default) or `"pdf"`. `transparent=True` works with PNG and WebP only.

If a request can time out, give an `idempotency_key`. The instance keeps the key for 24 hours. A second request with the same key returns the same snap and renders nothing. Then `snap.replayed` is `True`.

```python
snap = client.snaps.create(template_id, variants, idempotency_key="order-1042-card")
```

A key belongs to one kind of request. A key that a batch used raises `ConflictError` on `snaps.create()`, and the reverse is also true. Use a new key for each kind.

A `template_id` that does not exist in your company raises `ValidationError` with `errors["template_id"]`, not `NotFoundError`.

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

The list, the read and the create all give `image_url`, the URL of the captured image.

### Media

```python
media = client.media.upload("logo.png")  # a path
media = client.media.upload(data, filename="logo.png")  # bytes
page = client.media.list(page=1)  # 12 images for each page
print(media.src)  # use this URL as the image_url of a variant
```

A `Media` has `id`, `uuid`, `name`, `file_name`, `mime_type`, `size`, `original_url`, `src` and `created_at`.

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

### Response models

Each response is a frozen dataclass: `Account`, `Template`, `Layer`, `TemplateSize`, `Snap`, `Batch`, `BatchItem`, `Screenshot`, `Media`, `Page` and `MediaPage`. The `raw` field of a model holds the JSON object from the instance. Use it to read a field that this version of the package does not know.

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
| `params` | Other query parameters. The renderer ignores them, but they are part of the signature and of the cache key. To get a new image for the same content, add a value, for example `{"v": 2}`. |

The instance keeps each image in a cache by its full URL. The same URL returns the same image and costs no new credit. If you publish a new version of the template, the instance renders the image again.

A URL with a bad signature, or for a template that does not exist, does not return an error status. The instance returns its placeholder image with the status 200. If you see the placeholder, make sure that the key belongs to the owner of the template.

The signature is the HMAC-SHA256 hex digest of the query parameters, without `signature`. The parameters are sorted by key and joined as `key=value` with `&`. The `variants` value is standard base64 of the JSON array. `sign()`, `canonical_string()` and `encode_variants()` give each step, if you need them.

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
│   ├── NotFoundError         404
│   ├── ConflictError         409: .code tells the cause, .retryable tells if a repeat can work
│   ├── ValidationError       422: .errors has the field errors
│   ├── RateLimitError        429: .retry_after, .limit and .remaining
│   └── ServerError           5xx
└── WaitTimeoutError          batches.wait() did not see a terminal status in time
```

Each `APIError` has `status_code`, `message`, `body`, `code`, `request_id` and `response`. Give `request_id` to support when you report a problem.

`AuthorizationError` (403) means that the token has no `api_requests` ability, or that a permission check refused the action. `POST /v1/snaps` sends 403 for both cases.

`ConflictError` (409) has a `code`. The package exports a constant for each code:

| `code` | Cause | Can a repeat work? |
|---|---|---|
| `IDEMPOTENCY_KEY_IN_PROGRESS` | Another request with the same key runs now. | Yes, with the same key. The client retries it. |
| `IDEMPOTENCY_KEY_BELONGS_TO_BATCH` | `snaps.create()` sent a key that a batch owns. | No. Send a new key. |
| `IDEMPOTENCY_KEY_BELONGS_TO_SNAP` | `batches.create()` sent a key that a single snap owns. | No. Send a new key. |

In each case, the instance created nothing and used no credit.

`ServerError` (5xx) from `POST /v1/snaps` has the code `INTERNAL_ERROR` and a fixed message. The body holds no details of the fault. Give `request_id` to support.

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

The client retries a failed request two times by default. The wait before each retry grows exponentially (0.5, 1, 2 ... seconds, 8 seconds maximum) and has random jitter.

| Failure | GET, and POST with `idempotency_key` | POST without `idempotency_key` |
|---|---|---|
| 429 | Retry | Retry |
| 409 `idempotency_key_in_progress` | Retry (POST with a key only) | No retry |
| Other 409 | No retry | No retry |
| 5xx | Retry | No retry |
| Connection not made (DNS, refused, pool timeout) | Retry | Retry |
| Read timeout or dropped connection | Retry | No retry |
| Other 4xx | No retry | No retry |

- If a response has a `Retry-After` header, the client waits for that time.
- If `Retry-After` is more than 60 seconds, the client does not wait. It raises `RateLimitError` at once.
- The API allows 60 requests per minute for one user. A preview also has a limit of 10 per minute. Each response has the headers `X-RateLimit-Limit` and `X-RateLimit-Remaining`.
- If another request holds the same idempotency key, the client waits with the normal backoff and sends the request again. If the other request does not finish before the last retry, the client raises `ConflictError`.
- `batches.cancel()` is idempotent, so the client retries it like a GET.
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

## Supported Python versions

The package supports Python 3.10, 3.11, 3.12, 3.13 and 3.14. CI runs the tests, the lint and the type check on each version.

The package has full type hints and a `py.typed` file. `mypy --strict` passes on the package.

## Development

Read [CONTRIBUTING.md](CONTRIBUTING.md).
