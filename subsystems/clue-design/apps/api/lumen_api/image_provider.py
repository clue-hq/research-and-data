"""Provider-agnostic text-to-image (T2I) generation seam.

This is the single place a real hosted image model is wired into Lumen. Per the
image-model build plan (Slice 0, Step 1) the network call lives in the (async-
capable) Python API layer rather than the sync Rust `lumen-assets` crate, and the
returned bytes are persisted through the same ingest pipeline as uploads — stamped
with a `generated` source — so the rest of the stack (placement, render, export,
validation) needs no change.

Design:
- **Provider-agnostic.** Configuration comes from the environment. The actual HTTP
  request/response mapping is isolated in `_invoke_model` (the *adapter seam*) so a
  specific vendor can be slotted in — or mocked in tests — without touching the
  route or the orchestration logic.
- The route calls `generate(...)`. Tests patch `generate` (or `_invoke_model`); no
  live API key is required to exercise the wiring.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from py_lumen_config import settings

# Default id for the Python-side T2I provider. Anything else (qr, stub-image-v0,
# …) continues to route to the Rust provider registry, untouched.
DEFAULT_PROVIDER_ID = "image-gen-v1"
DEFAULT_MIME = "image/png"
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_RETRIES = 2

# Framing prepended to the instruction when reference images ride a GENERATION
# (not an edit). Reference images are STYLE anchors, not source pixels to modify,
# so the model is told explicitly to synthesize a NEW image rather than copy or
# edit the attachments (edit's "modify THIS image" semantics are the opposite).
STYLE_REFERENCE_FRAMING = (
    "The attached image(s) are STYLE REFERENCES only — match their visual style "
    "(palette, texture, mood, edge character) but generate a NEW image; do not "
    "copy, crop, or edit them."
)

# --- OpenRouter Images API (IMAGE_MODEL_API_STYLE=images) constants ---------
# Straight from the founder-supplied OpenRouter reference for openai/gpt-image-2
# (2026-08-23). `aspect_ratio` is a CLOSED enum — an unsupported string is a 400,
# i.e. a grey stub — so caller ratios are snapped to the nearest member. Values
# are the numeric width/height each member denotes.
IMAGES_API_ASPECT_RATIOS = {
    "1:1": 1.0,
    "3:2": 3 / 2,
    "2:3": 2 / 3,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "21:9": 21 / 9,
}
# `quality` enum is auto|low|medium|high; the founder's sample and our quality
# bar both say high.
IMAGES_API_QUALITY = "high"
# `background` enum is auto|OPAQUE — there is NO "transparent" member, so an
# alpha channel cannot be requested structurally at all. FOUNDER RULE 2026-08-23:
# always send "auto" (which is what both founder sample bodies carry). A
# transparent request additionally gets a prose hint and no promise; see
# `_invoke_images_api`.
IMAGES_API_BACKGROUND = "auto"
# `input_references` is documented 0-16. Our upstream attachment cap is far
# lower (REFERENCE_ASSETS_MAX = 4), so exceeding this is a caller bug — asserted
# rather than assumed, and loud rather than silently truncating the anchors a
# user attached.
IMAGES_API_MAX_INPUT_REFERENCES = 16
# NOT used on this path, deliberately: `n` (default 1 is what we want),
# `output_compression`, `provider.options`, and `stream` (this client is
# synchronous).


class ImageGenerationError(Exception):
    """Typed failure so the route can return a clean HTTP error + diagnostic
    instead of a 500. `status_code` is the HTTP status to surface."""

    def __init__(self, code: str, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass
class ImageGenerationResult:
    image_bytes: bytes
    mime_type: str
    model: str
    provenance: dict
    license: Optional[dict] = None


@dataclass
class ImageModelConfig:
    base_url: str
    api_key: str
    model_id: str
    api_style: str = "chat"
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES

    @classmethod
    def from_env(cls) -> "ImageModelConfig":
        base_url = settings.image_model_base_url.strip()
        api_key = settings.image_model_api_key.strip()
        if not base_url or not api_key:
            raise ImageGenerationError(
                "image_model.not_configured",
                "Image generation is not configured: set IMAGE_MODEL_BASE_URL and "
                "IMAGE_MODEL_API_KEY (and optionally IMAGE_MODEL_ID).",
                status_code=503,
            )
        return cls(
            base_url=base_url,
            api_key=api_key,
            model_id=settings.image_model_id,
            api_style=settings.image_model_api_style,
            timeout_s=settings.image_model_timeout_s,
            max_retries=settings.image_model_max_retries,
        )


def provider_id() -> str:
    return settings.image_model_provider_id


def is_image_model_provider(provider: str) -> bool:
    """True when `provider` routes through the Python T2I path (vs a Rust-
    registered provider such as `qr` or `stub-image-v0`)."""
    return provider == provider_id()


def is_configured() -> bool:
    return settings.image_model_configured()


def configured_model_id() -> str:
    """The text-to-image model id used for generation. Exposed for the generation
    cache key + provenance without constructing the full config."""
    return settings.image_model_id


def generate(
    *,
    prompt: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    brand_notes: Optional[List[str]] = None,
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    transparent_background: Optional[bool] = None,
    reference_asset_ids: Optional[List[str]] = None,
    reference_images: Optional[List[Tuple[bytes, str]]] = None,
    request_id: Optional[str] = None,
) -> ImageGenerationResult:
    """Generate one raster image. Provider-agnostic orchestration:
    config → dimension resolution → prompt assembly → retrying HTTP adapter →
    normalized result.

    `aspect_ratio` ("16:9") + `image_size` ("1k"/"2k"/"4k") translate to concrete
    width/height when explicit dimensions are absent (a 1:1 frame is never stretched
    into 16:9). `reference_asset_ids` stays accepted — the caller (API route) resolves
    those ids into `reference_images`, the bytes channel: (bytes, mime) pairs that ride
    the model call as STYLE references (multimodal content, images first then the
    instruction, framed so the model synthesizes a NEW image rather than editing the
    attachments). No references → the request body is byte-identical to a bare
    text-to-image call. Raises `ImageGenerationError` (typed) on misconfiguration or
    provider failure. This is the function the route calls and tests patch.
    """
    if not (prompt or "").strip():
        raise ImageGenerationError(
            "image_model.empty_prompt",
            "a non-empty prompt is required for image generation",
            status_code=400,
        )
    config = ImageModelConfig.from_env()
    width, height = resolve_dimensions(width, height, aspect_ratio, image_size)
    full_prompt = _compose_prompt(prompt, brand_notes or [])
    image_bytes, mime_type = _invoke_with_retries(
        config,
        prompt=full_prompt,
        width=width,
        height=height,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        transparent_background=transparent_background,
        reference_images=reference_images or None,
    )
    return ImageGenerationResult(
        image_bytes=image_bytes,
        mime_type=mime_type or DEFAULT_MIME,
        model=config.model_id,
        provenance=_generated_provenance(config.model_id, request_id),
        license=_generated_license(),
    )


def edit(
    *,
    prompt: str,
    source_images: List[Tuple[bytes, str]],
    brand_notes: Optional[List[str]] = None,
    transparent_background: Optional[bool] = None,
    request_id: Optional[str] = None,
) -> ImageGenerationResult:
    """Edit an existing raster image with a text instruction (Phase 3b).

    Same orchestration as `generate`, but the source image(s) ride the model
    call as multimodal content and the output geometry follows the source —
    no dimension resolution or aspect hints (asking an edit to change framing
    belongs in the instruction itself). `transparent_background` is how
    remove-background rides this path. Raises `ImageGenerationError` (typed)
    on misconfiguration, empty inputs, or provider failure.
    """
    if not (prompt or "").strip():
        raise ImageGenerationError(
            "image_model.empty_prompt",
            "a non-empty edit instruction is required",
            status_code=400,
        )
    if not source_images:
        raise ImageGenerationError(
            "image_model.missing_source",
            "an image edit requires at least one source image",
            status_code=400,
        )
    config = ImageModelConfig.from_env()
    full_prompt = _compose_prompt(prompt, brand_notes or [])
    image_bytes, mime_type = _invoke_with_retries(
        config,
        prompt=full_prompt,
        width=None,
        height=None,
        aspect_ratio=None,
        image_size=None,
        transparent_background=transparent_background,
        source_images=source_images,
    )
    return ImageGenerationResult(
        image_bytes=image_bytes,
        mime_type=mime_type or DEFAULT_MIME,
        model=config.model_id,
        provenance=_generated_provenance(config.model_id, request_id),
        license=_generated_license(),
    )


# --- dimension resolution (aspect ratio + size tier → width/height) ---------

# Role-appropriate resolution tiers (Brilliant `imageSize`): long-edge pixels.
_SIZE_TIERS = {"1k": 1024, "2k": 2048, "4k": 4096}
_DEFAULT_LONG_EDGE = 1024


def _parse_aspect_ratio(value: Optional[str]) -> Optional[Tuple[float, float]]:
    """Parse '16:9' / '16x9' / '1.78' / '1.78:1' into (w, h) ratio parts, or None."""
    if not value:
        return None
    text = value.strip().lower().replace("x", ":")
    parts = text.split(":") if ":" in text else [text, "1"]
    try:
        ratio_w = float(parts[0])
        ratio_h = float(parts[1]) if len(parts) > 1 and parts[1].strip() else 1.0
    except (ValueError, IndexError):
        return None
    if ratio_w <= 0 or ratio_h <= 0:
        return None
    return ratio_w, ratio_h


def resolve_dimensions(
    width: Optional[int],
    height: Optional[int],
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """Translate an aspect ratio + size tier into concrete (width, height). Explicit
    width AND height always win. With only an aspect ratio, the long edge comes from
    the size tier (default 1k); the short edge is derived from the ratio."""
    if width and height:
        return width, height
    long_edge = _SIZE_TIERS.get((image_size or "").strip().lower(), _DEFAULT_LONG_EDGE)
    parsed = _parse_aspect_ratio(aspect_ratio)
    if parsed:
        ratio_w, ratio_h = parsed
        if ratio_w >= ratio_h:
            return long_edge, max(1, round(long_edge * ratio_h / ratio_w))
        return max(1, round(long_edge * ratio_w / ratio_h)), long_edge
    if width:
        return width, width
    if height:
        return height, height
    return long_edge, long_edge


# --- prompt assembly -------------------------------------------------------

def _compose_prompt(prompt: str, brand_notes: List[str]) -> str:
    """Append brand/style direction as natural-language conditioning (provider-
    agnostic — every T2I model accepts richer prose)."""
    prompt = (prompt or "").strip()
    notes = [note.strip() for note in (brand_notes or []) if note and note.strip()]
    if notes:
        return f"{prompt}\n\nBrand/style direction: " + "; ".join(notes)
    return prompt


def _image_content_parts(images: List[Tuple[bytes, str]]) -> List[dict]:
    """OpenAI-style multimodal `image_url` parts (base64 data: URLs), one per
    (bytes, mime) pair, in order. Shared by the edit (source) and reference-
    conditioned generation paths so both build byte-identical image parts."""
    return [
        {
            "type": "image_url",
            "image_url": {
                "url": "data:"
                + (mime or DEFAULT_MIME)
                + ";base64,"
                + base64.b64encode(image_bytes).decode("ascii")
            },
        }
        for image_bytes, mime in images
    ]


# --- adapter seam (the only vendor-specific code) --------------------------

def _invoke_with_retries(
    config: ImageModelConfig,
    *,
    prompt: str,
    width: Optional[int],
    height: Optional[int],
    aspect_ratio: Optional[str],
    image_size: Optional[str],
    transparent_background: Optional[bool],
    source_images: Optional[List[Tuple[bytes, str]]] = None,
    reference_images: Optional[List[Tuple[bytes, str]]] = None,
) -> Tuple[bytes, str]:
    last_error: Optional[Exception] = None
    for attempt in range(config.max_retries + 1):
        try:
            return _invoke_model(
                config,
                prompt=prompt,
                width=width,
                height=height,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                transparent_background=transparent_background,
                source_images=source_images,
                reference_images=reference_images,
            )
        except ImageGenerationError:
            raise  # typed/terminal — don't retry config or decode errors
        except Exception as error:  # transient transport errors
            last_error = error
    raise ImageGenerationError(
        "image_model.unavailable",
        f"image model did not return an image after {config.max_retries + 1} attempt(s): {last_error}",
        status_code=502,
    )


def _invoke_model(
    config: ImageModelConfig,
    *,
    prompt: str,
    width: Optional[int],
    height: Optional[int],
    aspect_ratio: Optional[str],
    image_size: Optional[str],
    transparent_background: Optional[bool],
    source_images: Optional[List[Tuple[bytes, str]]] = None,
    reference_images: Optional[List[Tuple[bytes, str]]] = None,
) -> Tuple[bytes, str]:
    """ADAPTER SEAM — OpenRouter (raw HTTP), two transports.

    OpenRouter exposes image generation two different ways and a given model
    speaks exactly one of them, so `IMAGE_MODEL_API_STYLE` selects the wire
    shape: `chat` (the OpenAI-compatible chat-completions endpoint with an image
    modality — Gemini-class models) or `images` (the dedicated Images endpoint —
    `openai/gpt-image-2`). Everything above this function is transport-agnostic.
    """
    if config.api_style == "images":
        return _invoke_images_api(
            config,
            prompt=prompt,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            transparent_background=transparent_background,
            source_images=source_images,
            reference_images=reference_images,
        )
    return _invoke_chat_completions(
        config,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        transparent_background=transparent_background,
        source_images=source_images,
        reference_images=reference_images,
    )


def _openrouter_headers(config: ImageModelConfig) -> dict:
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    # Optional OpenRouter attribution headers (ranking only; harmless if unset).
    referer = settings.image_model_http_referer
    title = settings.image_model_app_title
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title
    return headers


def _invoke_chat_completions(
    config: ImageModelConfig,
    *,
    prompt: str,
    aspect_ratio: Optional[str],
    image_size: Optional[str],
    transparent_background: Optional[bool],
    source_images: Optional[List[Tuple[bytes, str]]] = None,
    reference_images: Optional[List[Tuple[bytes, str]]] = None,
) -> Tuple[bytes, str]:
    """Transport A — OpenRouter chat-completions with an image modality.

    OpenRouter runs image generation through the OpenAI-compatible
    chat-completions endpoint with an image modality: POST
    `{base_url}/chat/completions` with `modalities: ["image", "text"]`; the
    generated image comes back as a base64 `data:` URL in
    `choices[0].message.images[*].image_url.url`.

    Output dimensions are model-determined (the chat image modality has no
    width/height knob), so `aspect_ratio` is passed as a prompt hint and exact
    frame dimensions come from cover-fit placement, not the model. `httpx` is
    imported lazily so the module loads without it (tests patch `generate`).
    """
    import httpx  # lazy: only the real network path needs it

    hints = []
    if aspect_ratio:
        hints.append(f"aspect ratio {aspect_ratio}")
    if image_size:
        hints.append(f"{image_size} resolution")
    if transparent_background:
        hints.append("transparent background")
    user_prompt = prompt if not hints else f"{prompt}\n\n(Render with " + ", ".join(hints) + ".)"

    # Image EDIT: source images ride the same chat-completions call as
    # OpenAI-style multimodal content parts (base64 data: URLs) ahead of the
    # instruction text; the model returns the edited image the same way a
    # generation does. Reference-conditioned GENERATION uses the same content
    # shape — reference images first, then the instruction — but prefixes an
    # explicit "these are STYLE references, make a NEW image" framing so the
    # model does not treat them as pixels to edit. Plain generation (no source,
    # no references) keeps the bare-string content, byte-identical to before.
    if source_images:
        content: object = [
            *_image_content_parts(source_images),
            {"type": "text", "text": user_prompt},
        ]
    elif reference_images:
        content = [
            *_image_content_parts(reference_images),
            {"type": "text", "text": f"{STYLE_REFERENCE_FRAMING}\n\n{user_prompt}"},
        ]
    else:
        content = user_prompt

    body = {
        "model": config.model_id,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
    }
    url = config.base_url.rstrip("/") + "/chat/completions"
    response = httpx.post(
        url, json=body, headers=_openrouter_headers(config), timeout=config.timeout_s
    )
    if response.status_code >= 400:
        raise ImageGenerationError(
            "image_model.http_error",
            f"image model returned HTTP {response.status_code}: {response.text[:300]}",
            status_code=502,
        )
    return _decode_openrouter_image(response.json())


# --- Transport B: the dedicated OpenRouter Images API ----------------------


def _snap_aspect_ratio(
    aspect_ratio: Optional[str], width: Optional[int], height: Optional[int]
) -> Optional[str]:
    """The nearest member of the Images API's CLOSED `aspect_ratio` enum, or None
    when the caller expressed no framing at all (omitting beats asserting — the
    endpoint's own default is `auto`).

    The requested ratio wins; failing that the ratio is derived from the resolved
    width/height, which is how `resolve_dimensions` already reasons about frames.
    A ratio outside the enum (5:2, 4:5, …) is snapped rather than forwarded: an
    unsupported string is an HTTP 400, which reaches the user as a grey stub.

    In practice only `edit` reaches the None branch: `generate` always resolves
    concrete dimensions first (defaulting to a 1024-square), so a framing-free
    generation legitimately asks for `1:1` — the square the rest of the stack is
    already going to place into. An edit has no target frame of its own, so it
    stays silent and lets the endpoint follow the source.
    """
    parsed = _parse_aspect_ratio(aspect_ratio)
    if parsed:
        ratio_w, ratio_h = parsed
        value = ratio_w / ratio_h
    elif width and height:
        value = width / height
    else:
        return None
    return min(
        IMAGES_API_ASPECT_RATIOS,
        key=lambda name: abs(IMAGES_API_ASPECT_RATIOS[name] - value),
    )


def _invoke_images_api(
    config: ImageModelConfig,
    *,
    prompt: str,
    width: Optional[int],
    height: Optional[int],
    aspect_ratio: Optional[str],
    transparent_background: Optional[bool],
    source_images: Optional[List[Tuple[bytes, str]]] = None,
    reference_images: Optional[List[Tuple[bytes, str]]] = None,
) -> Tuple[bytes, str]:
    """Transport B — OpenRouter's dedicated Images endpoint.

    `POST {base_url}/images` with a top-level `prompt`, a STRUCTURED
    `aspect_ratio` (no prose hint — the enum is a real parameter here),
    `quality`, `background`, and, for a reference-conditioned call,
    `input_references`. The image comes back base64 in `data[*].b64_json`. This
    is the shape `openai/gpt-image-2` takes; it does not answer the
    chat-completions call at all.

    Note gpt-image-2's references are SUBJECT-composition oriented by design
    ("keep this dog's exact face"), so our style-anchor semantics can only ride
    the prompt — which makes `STYLE_REFERENCE_FRAMING` more load-bearing here
    than on the chat path, not less.
    """
    import httpx  # lazy: only the real network path needs it

    user_prompt = prompt
    if transparent_background:
        # `background` is enum auto|opaque — it has NO transparent member, so
        # asking structurally would be an invalid enum (400 → grey stub), and
        # `background` still goes out as "auto" per the founder rule. Prose is
        # the honest best effort: this model CANNOT honor transparency
        # structurally, so a caller that needs a real alpha channel needs a
        # different model or a downstream cut-out — not a louder prompt.
        user_prompt = f"{user_prompt}\n\n(Render with transparent background.)"

    references = list(reference_images or source_images or [])
    if len(references) > IMAGES_API_MAX_INPUT_REFERENCES:
        raise ImageGenerationError(
            "image_model.too_many_references",
            f"the images API accepts at most {IMAGES_API_MAX_INPUT_REFERENCES} "
            f"input references; got {len(references)}",
            status_code=400,
        )
    if reference_images:
        # Same distinction the chat path draws: a GENERATION's references are
        # style anchors ("make a NEW image"), an EDIT's source is the subject.
        user_prompt = f"{STYLE_REFERENCE_FRAMING}\n\n{user_prompt}"

    body: dict = {
        "model": config.model_id,
        "prompt": user_prompt,
    }
    snapped = _snap_aspect_ratio(aspect_ratio, width, height)
    if snapped:
        body["aspect_ratio"] = snapped
    body["quality"] = IMAGES_API_QUALITY
    body["background"] = IMAGES_API_BACKGROUND
    if references:
        body["input_references"] = _image_content_parts(references)

    url = config.base_url.rstrip("/") + "/images"
    response = httpx.post(
        url, json=body, headers=_openrouter_headers(config), timeout=config.timeout_s
    )
    if response.status_code >= 400:
        raise ImageGenerationError(
            "image_model.http_error",
            f"image model returned HTTP {response.status_code}: {response.text[:300]}",
            status_code=502,
        )
    return _decode_images_api_response(response.json(), timeout_s=config.timeout_s)


def _decode_images_api_response(payload: object, *, timeout_s: float) -> Tuple[bytes, str]:
    """Pull the generated image out of an OpenRouter Images API response.

    Primary — and the shape the API reference's own example loops over —
    `data[0].b64_json`. Defensive fallback: `data[0].url`, either a base64
    `data:` URL (the existing decoder) or a plain https URL, which is FETCHED.
    That fetch is the minimal slice of the URL-result gap this transport needs
    to function; the chat path's identical gap stays W4.1's to close.
    """
    entry: dict = {}
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            entry = data[0]

    b64 = entry.get("b64_json") or entry.get("image_base64")
    if isinstance(b64, str) and b64:
        return _decode_b64(b64, entry.get("mime_type") or DEFAULT_MIME)

    url = entry.get("url")
    if isinstance(url, str) and url:
        if url.startswith("data:"):
            return _decode_data_url(url)
        return _fetch_image_url(url, timeout_s=timeout_s)

    raise ImageGenerationError(
        "image_model.bad_response",
        "images API response contained no data[0].b64_json or data[0].url: "
        f"{str(payload)[:200]}",
        status_code=502,
    )


def _fetch_image_url(url: str, *, timeout_s: float) -> Tuple[bytes, str]:
    """Download an image the Images API returned by reference. Transport errors
    propagate (the retry wrapper handles them); an HTTP error is typed."""
    import httpx  # lazy: only the real network path needs it

    response = httpx.get(url, timeout=timeout_s)
    if response.status_code >= 400:
        raise ImageGenerationError(
            "image_model.http_error",
            f"fetching the generated image returned HTTP {response.status_code}",
            status_code=502,
        )
    mime = (response.headers.get("content-type") or DEFAULT_MIME).split(";", 1)[0].strip()
    return response.content, mime or DEFAULT_MIME


def _decode_openrouter_image(payload: object) -> Tuple[bytes, str]:
    """Pull the generated image out of an OpenRouter chat-completion response.

    Primary: `choices[0].message.images[*].image_url.url` (a base64 data: URL).
    Fallback: top-level `data[0].b64_json` (OpenAI Images compat).
    """
    message: dict = {}
    if isinstance(payload, dict):
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}

    images = message.get("images") if isinstance(message, dict) else None
    if isinstance(images, list) and images and isinstance(images[0], dict):
        image_url = images[0].get("image_url")
        url = image_url.get("url") if isinstance(image_url, dict) else image_url
        if isinstance(url, str) and url:
            return _decode_data_url(url)

    if isinstance(payload, dict):  # OpenAI Images-style fallback
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            b64 = data[0].get("b64_json") or data[0].get("image_base64")
            if isinstance(b64, str) and b64:
                return _decode_b64(b64, data[0].get("mime_type") or DEFAULT_MIME)

    # No image — surface the model's text (often a refusal/error) for debugging.
    text = message.get("content") if isinstance(message, dict) else None
    detail = f"; model said: {str(text)[:200]}" if text else ""
    raise ImageGenerationError(
        "image_model.no_image",
        f"OpenRouter response contained no image{detail}",
        status_code=502,
    )


def _decode_data_url(url: str) -> Tuple[bytes, str]:
    if not url.startswith("data:"):
        # Some models return a plain https URL; Slice 0 does not fetch those.
        raise ImageGenerationError(
            "image_model.bad_response",
            "expected a base64 data: URL image from the model",
            status_code=502,
        )
    head, _, b64 = url.partition(",")
    mime = head[5:].split(";", 1)[0] or DEFAULT_MIME
    return _decode_b64(b64, mime)


def _decode_b64(b64: str, mime: str) -> Tuple[bytes, str]:
    import base64

    try:
        return base64.b64decode(b64), (mime or DEFAULT_MIME)
    except Exception as error:
        raise ImageGenerationError(
            "image_model.bad_response",
            f"image model returned undecodable base64: {error}",
            status_code=502,
        )


# --- record shaping (matches fixtures/assets/generated_raster_asset.json) ---

def _generated_license() -> dict:
    return {
        "name": "generated_commercial_use",
        "allow_export": True,
        "allow_modification": True,
        "allow_embedding": True,
        "allow_subsetting": False,
        "source_url": None,
        "restrictions": [],
    }


def _generated_provenance(model_id: str, request_id: Optional[str]) -> dict:
    notes = [f"model={model_id}", f"provider={provider_id()}"]
    if request_id:
        notes.append(f"request_id={request_id}")
    return {
        "created_by": "agent",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_label": "image generation",
        "confidence": None,
        "notes": notes,
    }
