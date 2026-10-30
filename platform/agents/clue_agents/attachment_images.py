"""What a model is shown of an attached image (spec 2026-10-30 §3.6).

One rule for every agent. PNG, JPEG, WebP and GIF go to the model as they are. HEIC/HEIF, AVIF,
TIFF, BMP and ICO are formats vision models do not take, so the model is shown a PNG copy made
here; the person's file is never changed. SVG is a drawing written as text: it is never sent as a
picture, the agent opens it as a file.
"""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

__all__ = [
    "CONVERTIBLE_IMAGE_TYPES",
    "MODEL_NATIVE_IMAGE_TYPES",
    "is_shown_as_picture",
    "viewable_image",
]

MODEL_NATIVE_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
CONVERTIBLE_IMAGE_TYPES = frozenset(
    {"image/heic", "image/heif", "image/avif", "image/tiff", "image/bmp", "image/x-icon"}
)

_heif_registered = False


def _register_heif() -> None:
    global _heif_registered
    if not _heif_registered:
        import pillow_heif

        pillow_heif.register_heif_opener()
        _heif_registered = True


def is_shown_as_picture(media_type: str) -> bool:
    """Whether a model is shown this attachment as a picture (directly or as a PNG copy)."""

    lowered = media_type.lower()
    return lowered in MODEL_NATIVE_IMAGE_TYPES or lowered in CONVERTIBLE_IMAGE_TYPES


def viewable_image(data: bytes, media_type: str) -> tuple[bytes, str] | None:
    """The bytes and type a model is shown, or ``None`` when it is shown no picture.

    A convertible image becomes a PNG of its first frame, transparency kept. Bytes that do not
    decode give ``None``: the file is still in the agent's folder, it is just not shown.
    """

    lowered = media_type.lower()
    if lowered in MODEL_NATIVE_IMAGE_TYPES:
        return data, lowered
    if lowered not in CONVERTIBLE_IMAGE_TYPES:
        return None
    if lowered in ("image/heic", "image/heif"):
        _register_heif()
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.seek(0)
            frame = image.convert("RGBA" if _has_alpha(image) else "RGB")
            out = io.BytesIO()
            frame.save(out, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    return out.getvalue(), "image/png"


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
