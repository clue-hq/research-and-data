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
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Literal, Optional, Tuple

from py_lumen_config import settings

logger = logging.getLogger("lumen_api.image_provider")

# Default id for the Python-side T2I provider. Anything else (qr, stub-image-v0,
# …) continues to route to the Rust provider registry, untouched.
DEFAULT_PROVIDER_ID = "image-gen-v1"
DEFAULT_MIME = "image/png"
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_RETRIES = 2

# W1.4 — the model id trap, verified live 2026-08-26 against OpenRouter's two
# separate catalogues.
#
# OpenRouter serves image generation from TWO endpoints with DISJOINT model
# catalogues. IMAGE_MODEL_API_STYLE selects the transport:
#
#   * `chat`: `/chat/completions` with `modalities: ["image","text"]`.
#     Catalogue: `GET /api/v1/models` (418 models; 11 with image output).
#   * `images`: `/images` — the dedicated Image API.
#     Catalogue: `GET /api/v1/images/models` (43 models).
#
# `openai/gpt-image-2` IS a real OpenRouter model — but ONLY on the Image API.
# It is absent from the chat catalogue, which is exactly why the Apollo POC's
# call came back `404 "No endpoints found that support the requested output
# modalities: image, text"`: the 404 is about the ENDPOINT, not the model's
# existence. (The spec's W1.4 row says "does not exist on OpenRouter"; that is
# true of the chat path only.)
#
# `openai/gpt-5.4-image-2` is in BOTH catalogues, and is the model the Apollo
# POC actually generated all three backgrounds with. It is the default here.
DEFAULT_IMAGE_MODEL_ID = "openai/gpt-5.4-image-2"

# Chat-path image ids that are really Image-API-only ids — a `404 No endpoints
# found` on one of these is a configuration mistake, not an outage, so we say so.
_IMAGE_API_ONLY_MODEL_IDS = frozenset(
    {
        "openai/gpt-image-2.5-flare",
        "openai/gpt-image-2",
        "openai/gpt-image-1",
        "openai/gpt-image-1-mini",
    }
)

# W1.7(a) — exactly ONE automatic retry when the model answers with text and no
# image (`image_model.no_image`). Observed on 1 of 4 Apollo POC calls; the model
# is non-deterministic about honoring the image modality, and the POC's manual
# re-request succeeded. More than one retry would multiply spend on a genuinely
# refusing prompt, so the budget is deliberately a single extra attempt.
NO_IMAGE_RETRIES = 1

# OpenRouter's documented `aspect_ratio` allowlist (Image API docs; the chat path
# takes the same strings under `image_config`). Providers clamp to their own
# subset, so sending a value off this list risks a 400 — every requested ratio is
# snapped to the nearest member instead.
_SUPPORTED_ASPECT_RATIOS: Tuple[str, ...] = (
    "1:8", "1:4", "9:21", "1:2", "2:3", "3:4", "4:5", "9:16",
    "1:1",
    "16:9", "5:4", "4:3", "3:2", "2:1", "21:9", "4:1", "8:1",
)

# Framing prepended to the instruction when reference images ride a GENERATION
# (not an edit). Reference images are STYLE anchors, not source pixels to modify,
# so the model is told explicitly to synthesize a NEW image rather than copy or
# edit the attachments (edit's "modify THIS image" semantics are the opposite).
STYLE_REFERENCE_FRAMING = (
    "The attached image(s) are STYLE REFERENCES only — match their visual style "
    "(palette, texture, mood, edge character) but generate a NEW image; do not "
    "copy, crop, or edit them."
)

ReferenceRole = Literal["source", "treatment", "composition"]
_REFERENCE_ROLE_DIRECTIONS = {
    "source": "use the depicted subject/content as guidance for a new image",
    "treatment": "use the palette, texture, mood and rendering treatment",
    "composition": "use the layout, spatial hierarchy and framing",
}

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
    # W1.7(b) — the dimensions the model ACTUALLY returned, read from the image
    # header rather than echoed from the request. The Apollo POC asked 16:9 and
    # got 1024×1024 while every surface kept reporting "16:9", so callers were
    # misled by their own request. These are the honest answer; `None` when the
    # format's header could not be read. Compare against `requested_*` to see
    # whether the model honored the ask.
    width: Optional[int] = None
    height: Optional[int] = None
    requested_aspect_ratio: Optional[str] = None
    requested_width: Optional[int] = None
    requested_height: Optional[int] = None
    # The aspect actually sent in the provider request, after snapping. It is
    # not evidence that the provider honored it; width/height remain measured.
    effective_aspect_ratio: Optional[str] = None
    provider_api_style: Optional[str] = None
    request_receipt: Optional[dict] = None

    @property
    def aspect_ratio_honored(self) -> Optional[bool]:
        """True/False when both a requested ratio and real dimensions are known;
        None when the question cannot be answered (no ask, or unreadable header)."""
        parsed = _parse_aspect_ratio(self.requested_aspect_ratio)
        if not parsed or not self.width or not self.height:
            return None
        want = parsed[0] / parsed[1]
        got = self.width / self.height
        return abs(want - got) <= 0.02 * want


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
            # Merge of W1.4 + the v2 transport split: the "default" sentinel
            # still resolves through configured_model_id() (explicit ids pass
            # through untouched), and the id's TRANSPORT rides api_style.
            model_id=configured_model_id(),
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
    cache key + provenance without constructing the full config.

    W1.4: the config layer normalizes a blank `IMAGE_MODEL_ID` to the sentinel
    `"default"`, which is not a real OpenRouter id and 404s exactly like the old
    broken value did. Resolve it here to the verified working model instead, so
    an unset env var yields a working generation rather than a confusing 404."""
    configured = (settings.image_model_id or "").strip()
    if not configured or configured == "default":
        return DEFAULT_IMAGE_MODEL_ID
    return configured


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
    reference_roles: Optional[List[ReferenceRole]] = None,
    reference_framing: Optional[str] = None,
    operation: Optional[str] = None,
) -> ImageGenerationResult:
    """Generate one raster image. Provider-agnostic orchestration:
    config → dimension resolution → prompt assembly → retrying HTTP adapter →
    normalized result.

    `aspect_ratio` ("16:9") + `image_size` ("1k"/"2k"/"4k") translate to concrete
    width/height when explicit dimensions are absent (a 1:1 frame is never stretched
    into 16:9). W1.7(b): `aspect_ratio` ALSO rides the model call structurally, as
    OpenRouter's `image_config.aspect_ratio` — see `_invoke_model`. The returned
    result carries the model's REAL `width`/`height` alongside what was requested,
    so a caller can never be misled by its own ask. `reference_asset_ids` stays
    accepted — the caller (API route) resolves
    those ids into `reference_images`, the bytes channel: (bytes, mime) pairs that ride
    the model call as STYLE references (multimodal content, images first then the
    instruction, framed so the model synthesizes a NEW image rather than editing the
    attachments). Optional `reference_roles` assigns source/treatment/composition
    to each image in order; `reference_framing` replaces the legacy style-only
    instruction. Neither adds provider capabilities or guarantees exact logo/UI
    pixels: use the existing edit or placement path for source preservation.
    `operation` is a caller intent label in the receipt, never a routing override.
    No references → the request body is byte-identical to a bare
    text-to-image call. Raises `ImageGenerationError` (typed) on misconfiguration or
    provider failure. This is the function the route calls and tests patch.
    """
    if not (prompt or "").strip():
        raise ImageGenerationError(
            "image_model.empty_prompt",
            "a non-empty prompt is required for image generation",
            status_code=400,
        )
    effective_framing = resolve_reference_framing(
        reference_images or [], reference_roles, reference_framing,
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
        reference_framing=effective_framing,
    )
    actual_width, actual_height = sniff_dimensions(image_bytes)
    provenance = _generated_provenance(config.model_id, request_id)
    # W1.7(b): when the model ignored the requested ratio, say so IN the durable
    # provenance — the Apollo POC's 1024×1024-for-16:9 was only discoverable by
    # measuring the pixels later. Never a failure: cover-fit placement still
    # crops correctly; the caller just deserves the truth.
    result = ImageGenerationResult(
        image_bytes=image_bytes,
        mime_type=mime_type or DEFAULT_MIME,
        model=config.model_id,
        provenance=provenance,
        license=_generated_license(),
        width=actual_width,
        height=actual_height,
        requested_aspect_ratio=aspect_ratio,
        requested_width=width,
        requested_height=height,
        effective_aspect_ratio=(
            _snap_aspect_ratio(aspect_ratio, width, height)
            if config.api_style == "images" else api_aspect_ratio(aspect_ratio)
        ),
        provider_api_style=config.api_style,
    )
    _record_request_receipt(
        result, provider_operation="generate", operation=operation,
        images=reference_images or [], reference_roles=reference_roles,
        reference_framing=reference_framing, effective_framing=effective_framing,
    )
    if actual_width and actual_height:
        provenance.setdefault("notes", []).append(
            f"output {actual_width}x{actual_height}"
        )
    if result.aspect_ratio_honored is False:
        provenance.setdefault("notes", []).append(
            f"model did not honor requested aspect_ratio {aspect_ratio} "
            f"(returned {actual_width}x{actual_height})"
        )
        logger.warning(
            "image model %s returned %sx%s for requested aspect_ratio %s",
            config.model_id,
            actual_width,
            actual_height,
            aspect_ratio,
        )
    return result


def edit(
    *,
    prompt: str,
    source_images: List[Tuple[bytes, str]],
    brand_notes: Optional[List[str]] = None,
    transparent_background: Optional[bool] = None,
    request_id: Optional[str] = None,
    operation: Optional[str] = None,
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
    edit_width, edit_height = sniff_dimensions(image_bytes)
    result = ImageGenerationResult(
        image_bytes=image_bytes,
        mime_type=mime_type or DEFAULT_MIME,
        model=config.model_id,
        provenance=_generated_provenance(config.model_id, request_id),
        license=_generated_license(),
        width=edit_width,
        height=edit_height,
        provider_api_style=config.api_style,
    )
    _record_request_receipt(
        result, provider_operation="edit", operation=operation,
        images=source_images, reference_roles=["source"] * len(source_images),
        reference_framing=None, effective_framing=None,
    )
    return result


def image_request_receipt_fields(record: dict) -> dict:
    """Project the persisted provider receipt identically on fresh and cache hits.

    Legacy assets have no receipt. Keep their response shape unchanged, and do
    not substitute a current request or transient provider result for stored
    provenance (a concurrent ledger winner may be a different result).
    """
    notes = (record.get("provenance") or {}).get("notes") or []
    for note in reversed(notes):
        if not isinstance(note, str) or not note.startswith("image_request="):
            continue
        try:
            receipt = json.loads(note.removeprefix("image_request="))
        except ValueError:
            continue
        if isinstance(receipt, dict):
            return {"image_request_receipt": receipt}
    return {}


def resolve_reference_framing(
    images: List[Tuple[bytes, str]],
    roles: Optional[List[ReferenceRole]],
    framing: Optional[str],
) -> Optional[str]:
    """Validate and describe ordered inputs without inventing wire capabilities."""
    if roles is not None and (
        len(roles) != len(images) or any(role not in _REFERENCE_ROLE_DIRECTIONS for role in roles)
    ):
        raise ImageGenerationError(
            "image_model.invalid_reference_roles",
            "reference_roles must match reference_images in order and length, using "
            "only source, treatment or composition",
            status_code=400,
        )
    if framing is not None and (not framing.strip() or not images):
        raise ImageGenerationError(
            "image_model.invalid_reference_framing",
            "reference_framing requires reference images and a non-empty instruction",
            status_code=400,
        )
    if not images:
        return None
    if roles is None:
        return framing.strip() if framing is not None else STYLE_REFERENCE_FRAMING
    lines = ["Generate a NEW image guided by these ordered references:"]
    lines.extend(
        f"Reference {index} ({role}): {_REFERENCE_ROLE_DIRECTIONS[role]}."
        for index, role in enumerate(roles, 1)
    )
    if framing is not None:
        lines.append(framing.strip())
    return "\n".join(lines)


def _ledger_receipt_fields() -> dict:
    """Name the `provider_call_ledger` row this generation was priced on, when there is one.

    Read from the open spend scope's buffered ledger immediately after the call, so the last
    ``openrouter`` result row IS this generation's. Absent (an empty dict — the receipt shape is
    unchanged for every legacy reader) when no scope is open, when the buffer holds no result row
    yet, or when the last row belongs to some other provider.
    """
    from . import spend

    scope = spend.current_scope()
    if scope is None:
        return {}
    results = [
        row
        for row in scope.ledger.rows
        if row.phase == "result" and row.provider == "openrouter"
    ]
    if not results:
        return {}
    row = results[-1]
    return {
        "ledger_row_id": row.row_id,
        "cost_usd": None if row.cost_usd is None else str(row.cost_usd),
    }


def _record_request_receipt(
    result: ImageGenerationResult,
    *,
    provider_operation: str,
    operation: Optional[str],
    images: List[Tuple[bytes, str]],
    reference_roles: Optional[List[ReferenceRole]],
    reference_framing: Optional[str],
    effective_framing: Optional[str],
) -> None:
    """Structured runtime receipt, also preserved in schema-compatible notes."""
    result.request_receipt = {
        "provider_operation": provider_operation,
        "operation": operation if operation is not None else provider_operation,
        "reference_roles": list(reference_roles) if reference_roles is not None else None,
        "reference_framing": reference_framing,
        "effective_reference_framing": effective_framing,
        "reference_inputs": [
            {
                "index": index + 1,
                "role": (
                    reference_roles[index] if reference_roles is not None
                    else "treatment" if reference_framing is None else None
                ),
                "mime_type": mime or DEFAULT_MIME,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for index, (data, mime) in enumerate(images)
        ],
        "requested_canvas": {"width": result.requested_width, "height": result.requested_height},
        "requested_aspect_ratio": result.requested_aspect_ratio,
        "effective_aspect_ratio": result.effective_aspect_ratio,
        "provider_api_style": result.provider_api_style,
        "output_dimensions": {"width": result.width, "height": result.height},
        **_ledger_receipt_fields(),
    }
    result.provenance.setdefault("notes", []).append(
        "image_request=" + json.dumps(result.request_receipt, sort_keys=True, separators=(",", ":"))
    )


# --- actual output dimensions (W1.7b: measured, never echoed) --------------

def sniff_dimensions(image_bytes: bytes) -> Tuple[Optional[int], Optional[int]]:
    """Read (width, height) out of a raster image's own header — PNG, JPEG, GIF
    or WebP. Returns (None, None) for anything unrecognized or truncated.

    Deliberately header-only and dependency-free: this runs on every generation,
    the bytes are already in memory, and no image library is (or should become) a
    hard dependency of the provider seam. Never raises — an unreadable header
    means "we don't know", which callers render as an honest absence."""
    data = image_bytes or b""
    try:
        # PNG: 8-byte signature, then an IHDR chunk whose payload starts with
        # big-endian uint32 width, height.
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            return (
                int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"),
            )
        # GIF: 'GIF87a'/'GIF89a', then little-endian uint16 width, height.
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return (
                int.from_bytes(data[6:8], "little"),
                int.from_bytes(data[8:10], "little"),
            )
        # WebP (RIFF container). VP8X carries 24-bit minus-one dimensions; VP8
        # (lossy) and VP8L (lossless) each pack them differently.
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            fourcc = data[12:16]
            if fourcc == b"VP8X":
                return (
                    int.from_bytes(data[24:27], "little") + 1,
                    int.from_bytes(data[27:30], "little") + 1,
                )
            if fourcc == b"VP8 ":
                return (
                    int.from_bytes(data[26:28], "little") & 0x3FFF,
                    int.from_bytes(data[28:30], "little") & 0x3FFF,
                )
            if fourcc == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        # JPEG: walk the marker segments to the first Start-Of-Frame (SOFn),
        # whose payload is [precision][uint16 height][uint16 width]. SOF4 (DHT),
        # SOF8 (reserved) and SOFC/SOFD/SOFE/SOFF are NOT frame headers.
        if data[:2] == b"\xff\xd8":
            index = 2
            end = len(data)
            while index + 9 < end:
                if data[index] != 0xFF:
                    index += 1
                    continue
                marker = data[index + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    index += 2
                    continue
                length = int.from_bytes(data[index + 2 : index + 4], "big")
                if length < 2:
                    break
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    return (
                        int.from_bytes(data[index + 7 : index + 9], "big"),
                        int.from_bytes(data[index + 5 : index + 7], "big"),
                    )
                index += 2 + length
    except Exception:  # noqa: BLE001 - an unreadable header is "unknown", not an error
        return None, None
    return None, None


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


def api_aspect_ratio(value: Optional[str]) -> Optional[str]:
    """Snap a requested ratio onto OpenRouter's documented `aspect_ratio`
    allowlist, so the value we put on the wire is always one the API accepts.

    W1.7(b): our callers speak in whatever the target frame happens to be
    ("16:9", "3x2", "1.78", or a raw frame ratio derived from node geometry),
    while OpenRouter takes a normalized ratio and "providers clamp to their
    supported subset". Nearest-by-log-ratio keeps the snap perceptually even in
    both directions (4:5 is as close to 1:1 as 5:4 is). Unparseable → None,
    which means the parameter is simply omitted."""
    parsed = _parse_aspect_ratio(value)
    if not parsed:
        return None
    target = parsed[0] / parsed[1]

    def distance(candidate: str) -> float:
        ratio_w, ratio_h = (float(part) for part in candidate.split(":"))
        return abs(math.log(target) - math.log(ratio_w / ratio_h))

    return min(_SUPPORTED_ASPECT_RATIOS, key=distance)


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
    reference_framing: Optional[str] = None,
) -> Tuple[bytes, str]:
    """Transport retries (`config.max_retries`) plus W1.7(a)'s ONE extra attempt
    on a text-only answer.

    Two distinct failure shapes, two budgets:

    * A transport error (connection reset, read timeout) is retried up to
      `config.max_retries` times — unchanged behavior.
    * `image_model.no_image` — HTTP 200, but the model replied with prose and no
      image part — is the Apollo POC's 1-in-4 flake, and used to be terminal
      because every `ImageGenerationError` re-raised immediately. It now gets
      exactly ONE more attempt (`NO_IMAGE_RETRIES`) before failing typed.
      Every other typed error (misconfiguration, HTTP 4xx/5xx, undecodable
      base64) still re-raises at once: retrying those just re-buys the same
      answer.
    """
    last_error: Optional[Exception] = None
    no_image_retries_left = NO_IMAGE_RETRIES
    attempt = 0
    while attempt <= config.max_retries:
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
                reference_framing=reference_framing,
            )
        except ImageGenerationError as error:
            if error.code != "image_model.no_image" or no_image_retries_left <= 0:
                raise  # typed/terminal — don't retry config or decode errors
            no_image_retries_left -= 1
            logger.warning(
                "image model %s answered with text and no image; retrying once (%s)",
                config.model_id,
                error,
            )
            continue  # the extra attempt is NOT charged to the transport budget
        except Exception as error:  # transient transport errors
            last_error = error
            attempt += 1
    raise ImageGenerationError(
        "image_model.unavailable",
        f"image model did not return an image after {config.max_retries + 1} "
        f"attempt(s): {last_error}",
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
    reference_framing: Optional[str] = None,
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
            reference_framing=reference_framing,
        )
    return _invoke_chat_completions(
        config,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        transparent_background=transparent_background,
        source_images=source_images,
        reference_images=reference_images,
        reference_framing=reference_framing,
    )


def _openrouter_attribution_headers() -> dict:
    """The optional OpenRouter attribution headers (ranking only; harmless if unset).

    Authorization and Content-Type are no longer built here: `spend.openrouter_call` owns both,
    because it owns the request. These are the only headers that are this caller's alone.
    """
    headers: dict = {}
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
    reference_framing: Optional[str] = None,
) -> Tuple[bytes, str]:
    """Transport A — OpenRouter chat-completions with an image modality.

    OpenRouter runs image generation through the OpenAI-compatible
    chat-completions endpoint with an image modality: POST
    `{base_url}/chat/completions` with `modalities: ["image", "text"]`; the
    generated image comes back as a base64 `data:` URL in
    `choices[0].message.images[*].image_url.url`.

    W1.7(b) — SIZING, corrected. The earlier note here ("the chat image modality
    has no width/height knob, so aspect_ratio is passed as a prompt hint") was
    wrong, and it is why the Apollo POC asked for 16:9 and got 1024×1024: the
    ratio never left the prose. The chat-completions body DOES take a documented
    `image_config` object ("Provider-specific image configuration options",
    example `{"aspect_ratio": "16:9", "quality": "high"}`), so the requested
    ratio now rides the request STRUCTURALLY, snapped to OpenRouter's accepted
    allowlist by `api_aspect_ratio`.

    Two constraints survive, and callers must not be misled about either:

    1. There is still NO width/height knob. `resolve_dimensions`' concrete pixel
       numbers are a LOCAL frame decision — they do not reach the model, and the
       long-edge tier (`image_size`) has no `image_config` equivalent documented
       for the chat path, so it stays a prompt hint. Exact frame dimensions come
       from cover-fit placement, not the model.
    2. `image_config` is provider-specific and providers "clamp to their
       supported subset" — a model that ignores `aspect_ratio` will still return
       its own default geometry. That is why the aspect ALSO stays in the prompt
       hint (belt and braces, ~8 tokens) and why `generate()` measures and
       reports what actually came back instead of echoing the request.

    The call goes through the turn's / request's `spend` scope, so the estimate
    row, the raw body and the priced result row land on `provider_call_ledger`
    like every other paid call the platform makes.
    """
    from . import spend  # lazy: only the real network path needs it

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
            {
                "type": "text",
                "text": f"{reference_framing or STYLE_REFERENCE_FRAMING}\n\n{user_prompt}",
            },
        ]
    else:
        content = user_prompt

    body: dict = {
        "model": config.model_id,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
    }
    # W1.7(b): the requested ratio, structurally. Omitted entirely when there is
    # no ask (or it cannot be parsed), so a plain generation's body is
    # byte-identical to before. (Headers moved to `_openrouter_headers` in the
    # v2 transport split — same content, one home.)
    wire_aspect_ratio = api_aspect_ratio(aspect_ratio)
    if wire_aspect_ratio:
        body["image_config"] = {"aspect_ratio": wire_aspect_ratio}
    response = spend.openrouter_call(
        operation="design.image.edit" if source_images else "design.image.generate",
        body=body,
        label=f"image:{config.model_id}",
        timeout_s=config.timeout_s,
        api_key=config.api_key,
        base_url=config.base_url,
        extra_headers=_openrouter_attribution_headers(),
        extras={"api_style": "chat"},
    )
    if response.status >= 400:
        detail = response.body.decode("utf-8", "replace")[:300]
        _warn_if_model_not_found(config.model_id, response.status, detail)
        raise ImageGenerationError(
            "image_model.http_error",
            f"image model returned HTTP {response.status}: {detail}",
            status_code=502,
        )
    return _decode_openrouter_image(json.loads(response.body))


def _warn_if_model_not_found(model_id: str, status_code: int, detail: str) -> None:
    """W1.4: shout when the FAILURE IS THE CONFIG, not the provider.

    A misconfigured `IMAGE_MODEL_ID` surfaces as a generic `404 No endpoints
    found that support the requested output modalities: image, text` — which
    reads like a provider outage and cost the Apollo POC a restart to diagnose.
    When the id is one we know to be Image-API-only, or the 404 names the
    modality mismatch, name the actual fix in the log."""
    if status_code != 404 and "no endpoints found" not in detail.lower():
        return
    if model_id in _IMAGE_API_ONLY_MODEL_IDS:
        logger.error(
            "IMAGE_MODEL_ID=%r is an OpenRouter IMAGE-API model id and is NOT served "
            "on the configured chat-completions transport. Set "
            "IMAGE_MODEL_API_STYLE=images to keep this model and use the Images API.",
            model_id,
        )
        return
    logger.error(
        "image model %r returned HTTP %s (%s). If this is 'no endpoints found', the "
        "configured IMAGE_MODEL_ID is not served on OpenRouter's chat-completions "
        "image modality; check `GET /api/v1/models?output_modalities=image` and "
        "consider IMAGE_MODEL_ID=%s.",
        model_id,
        status_code,
        detail,
        DEFAULT_IMAGE_MODEL_ID,
    )


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
    reference_framing: Optional[str] = None,
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

    Priced by `spend.image_generation_cost_reader`: an Images-API response carries
    no usage block, so the cost is looked up from the generation id afterwards.
    """
    from . import spend  # lazy: only the real network path needs it

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
        user_prompt = f"{reference_framing or STYLE_REFERENCE_FRAMING}\n\n{user_prompt}"

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

    response = spend.openrouter_call(
        operation="design.image.edit" if source_images else "design.image.generate",
        body=body,
        label=f"image:{config.model_id}",
        timeout_s=config.timeout_s,
        api_key=config.api_key,
        base_url=config.base_url,
        extra_headers=_openrouter_attribution_headers(),
        extras={"api_style": "images"},
        cost_reader=spend.image_generation_cost_reader,
        path="/images",
        include_usage=False,
    )
    if response.status >= 400:
        detail = response.body.decode("utf-8", "replace")[:300]
        raise ImageGenerationError(
            "image_model.http_error",
            f"image model returned HTTP {response.status}: {detail}",
            status_code=502,
        )
    return _decode_images_api_response(json.loads(response.body), timeout_s=config.timeout_s)


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
    propagate (the retry wrapper handles them); an HTTP error is typed.

    Two things this must not do, because both end with a corrupt asset ingested
    under a `generated` provenance stamp — which reads as success and is worse
    than a clean failure:

    - **Not follow redirects.** A by-reference result is typically a signed CDN
      URL, and those redirect; httpx defaults `follow_redirects=False`, so the
      302's empty body would become a zero-byte "image".
    - **Trust the content-type.** An expired signature, an error page, or a login
      interstitial answers 200 with `text/html`. Only `image/*` is an image.
    """
    import httpx  # lazy: only the real network path needs it

    response = httpx.get(url, timeout=timeout_s, follow_redirects=True)
    if response.status_code >= 400:
        raise ImageGenerationError(
            "image_model.http_error",
            f"fetching the generated image returned HTTP {response.status_code}",
            status_code=502,
        )
    mime = (response.headers.get("content-type") or DEFAULT_MIME).split(";", 1)[0].strip()
    if not mime.lower().startswith("image/"):
        raise ImageGenerationError(
            "image_model.bad_response",
            f"the generated-image URL served {mime or 'no content-type'}, not an image",
            status_code=502,
        )
    return response.content, mime


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
