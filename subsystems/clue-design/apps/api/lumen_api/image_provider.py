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


def generate(
    *,
    prompt: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    brand_notes: Optional[List[str]] = None,
    aspect_ratio: Optional[str] = None,
    transparent_background: Optional[bool] = None,
    request_id: Optional[str] = None,
) -> ImageGenerationResult:
    """Generate one raster image. Provider-agnostic orchestration:
    config → prompt assembly → retrying HTTP adapter → normalized result.

    Raises `ImageGenerationError` (typed) on misconfiguration or provider failure.
    This is the function the route calls and tests patch.
    """
    if not (prompt or "").strip():
        raise ImageGenerationError(
            "image_model.empty_prompt",
            "a non-empty prompt is required for image generation",
            status_code=400,
        )
    config = ImageModelConfig.from_env()
    full_prompt = _compose_prompt(prompt, brand_notes or [])
    image_bytes, mime_type = _invoke_with_retries(
        config,
        prompt=full_prompt,
        width=width,
        height=height,
        aspect_ratio=aspect_ratio,
        transparent_background=transparent_background,
    )
    return ImageGenerationResult(
        image_bytes=image_bytes,
        mime_type=mime_type or DEFAULT_MIME,
        model=config.model_id,
        provenance=_generated_provenance(config.model_id, request_id),
        license=_generated_license(),
    )


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
    transparent_background: Optional[bool],
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
                transparent_background=transparent_background,
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
    transparent_background: Optional[bool],
) -> Tuple[bytes, str]:
    """ADAPTER SEAM — the only provider-specific code.

    Default shape: HTTP POST `{base_url}` with a Bearer key and a JSON body, and a
    response that is either raw image bytes (Content-Type image/*) or JSON
    carrying base64 in one of the common keys. Replace/extend this body for a
    specific vendor; everything above is vendor-neutral.

    `httpx` is imported lazily so this module imports cleanly even where httpx is
    not installed (e.g. test environments that patch `generate`).
    """
    import httpx  # lazy: only the real network path needs it

    body = {
        "model": config.model_id,
        "prompt": prompt,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "transparent_background": transparent_background,
        "response_format": "b64_json",
    }
    body = {key: value for key, value in body.items() if value is not None}
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    response = httpx.post(
        config.base_url, json=body, headers=headers, timeout=config.timeout_s
    )
    if response.status_code >= 400:
        raise ImageGenerationError(
            "image_model.http_error",
            f"image model returned HTTP {response.status_code}: {response.text[:300]}",
            status_code=502,
        )
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("image/"):
        return response.content, content_type.split(";", 1)[0].strip()
    return _decode_json_image(response.json())


def _decode_json_image(payload: object) -> Tuple[bytes, str]:
    """Extract base64 image bytes from common JSON response shapes."""
    import base64

    b64: Optional[str] = None
    mime = DEFAULT_MIME
    if isinstance(payload, dict):
        if isinstance(payload.get("image_base64"), str):
            b64 = payload["image_base64"]
        elif isinstance(payload.get("b64_json"), str):
            b64 = payload["b64_json"]
        else:
            data = payload.get("data") or payload.get("images")
            if isinstance(data, list) and data and isinstance(data[0], dict):
                first = data[0]
                b64 = first.get("b64_json") or first.get("image_base64") or first.get("b64")
                mime = first.get("mime_type") or first.get("mime") or mime
    if not isinstance(b64, str) or not b64:
        raise ImageGenerationError(
            "image_model.bad_response",
            "image model response did not contain a base64 image (adapt _decode_json_image for this vendor)",
            status_code=502,
        )
    if b64.startswith("data:"):  # tolerate data URLs
        head, _, tail = b64.partition(",")
        mime = head[5:].split(";", 1)[0] or mime
        b64 = tail
    try:
        return base64.b64decode(b64), mime
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
