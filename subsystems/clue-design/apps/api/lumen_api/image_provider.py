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
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

# Default id for the Python-side T2I provider. Anything else (qr, stub-image-v0,
# …) continues to route to the Rust provider registry, untouched.
DEFAULT_PROVIDER_ID = "image-gen-v1"
DEFAULT_MIME = "image/png"
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_RETRIES = 2


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
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES

    @classmethod
    def from_env(cls) -> "ImageModelConfig":
        base_url = os.environ.get("IMAGE_MODEL_BASE_URL", "").strip()
        api_key = os.environ.get("IMAGE_MODEL_API_KEY", "").strip()
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
            model_id=os.environ.get("IMAGE_MODEL_ID", "default"),
            timeout_s=_env_float("IMAGE_MODEL_TIMEOUT_S", DEFAULT_TIMEOUT_S),
            max_retries=_env_int("IMAGE_MODEL_MAX_RETRIES", DEFAULT_MAX_RETRIES),
        )


def provider_id() -> str:
    return os.environ.get("IMAGE_MODEL_PROVIDER_ID", DEFAULT_PROVIDER_ID)


def is_image_model_provider(provider: str) -> bool:
    """True when `provider` routes through the Python T2I path (vs a Rust-
    registered provider such as `qr` or `stub-image-v0`)."""
    return provider == provider_id()


def is_configured() -> bool:
    return bool(
        os.environ.get("IMAGE_MODEL_BASE_URL", "").strip()
        and os.environ.get("IMAGE_MODEL_API_KEY", "").strip()
    )


def configured_model_id() -> str:
    """The text-to-image model id used for generation. Exposed for the generation
    cache key + provenance without constructing the full config. Tolerates stray
    surrounding quotes in a `.env` value."""
    value = os.environ.get("IMAGE_MODEL_ID", "default").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value or "default"


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
    request_id: Optional[str] = None,
) -> ImageGenerationResult:
    """Generate one raster image. Provider-agnostic orchestration:
    config → dimension resolution → prompt assembly → retrying HTTP adapter →
    normalized result.

    `aspect_ratio` ("16:9") + `image_size` ("1k"/"2k"/"4k") translate to concrete
    width/height when explicit dimensions are absent (a 1:1 frame is never stretched
    into 16:9). `reference_asset_ids` lands now for forward-compat; reference-image
    *use* is Slice 1. Raises `ImageGenerationError` (typed) on misconfiguration or
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
) -> Tuple[bytes, str]:
    """ADAPTER SEAM — OpenRouter (raw HTTP).

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
    # generation does. Plain generation keeps the bare-string content.
    if source_images:
        content: object = [
            *(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:"
                        + (mime or DEFAULT_MIME)
                        + ";base64,"
                        + base64.b64encode(image_bytes).decode("ascii")
                    },
                }
                for image_bytes, mime in source_images
            ),
            {"type": "text", "text": user_prompt},
        ]
    else:
        content = user_prompt

    body = {
        "model": config.model_id,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
    }
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    # Optional OpenRouter attribution headers (ranking only; harmless if unset).
    referer = os.environ.get("IMAGE_MODEL_HTTP_REFERER")
    title = os.environ.get("IMAGE_MODEL_APP_TITLE")
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title

    url = config.base_url.rstrip("/") + "/chat/completions"
    response = httpx.post(url, json=body, headers=headers, timeout=config.timeout_s)
    if response.status_code >= 400:
        raise ImageGenerationError(
            "image_model.http_error",
            f"image model returned HTTP {response.status_code}: {response.text[:300]}",
            status_code=502,
        )
    return _decode_openrouter_image(response.json())


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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
