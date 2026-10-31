"""Knock out a plain, single-colour background, exactly: no model, nothing redrawn.

A logo or brand image often ships on a solid tile (white bars on a black square). Placed on a
photo, that tile reads as a box. `knock_out_plain_background` makes the tile's colour transparent
and keeps the rest pixel for pixel, the way a "colour to alpha" tool does:

1. The background colour is read from the image's outer ring of pixels. If that ring is not one
   colour (a photo), it refuses rather than guess.
2. Each pixel gets the LEAST opacity under which it equals "some colour over the background"
   (GIMP's colour-to-alpha). A solid mark stays fully opaque in its own colour; an anti-aliased
   edge becomes its mark's colour at partial opacity, so no halo of the old tile is left behind.
3. The empty margin is trimmed, so the mark sits tightly in its frame.

Design 2026-10-31 (founder go): the design agent's `asset(action="knock_out_background")`.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

__all__ = ["ImageKnockOutError", "KnockedOutImage", "knock_out_plain_background"]

#: How far (RGB distance) a ring pixel may sit from the background colour and still count as it.
RING_TOLERANCE = 24.0
#: The share of the outer ring that must be the background colour for it to count as plain.
RING_PLAIN_SHARE = 0.9
#: A pixel this close to the background is background (JPEG noise, a faint tile gradient).
NOISE_FLOOR = 8.0
#: Below this alpha (0..255) a ring pixel already counts as transparent.
TRANSPARENT_ALPHA = 16

_RASTER_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}


class ImageKnockOutError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class KnockedOutImage:
    png_bytes: bytes
    receipt: dict[str, Any]


def _ring(pixels: np.ndarray) -> np.ndarray:
    """The outer one-pixel ring of an H x W x C array, as N x C."""
    if pixels.shape[0] < 3 or pixels.shape[1] < 3:
        return pixels.reshape(-1, pixels.shape[2])
    return np.concatenate(
        [pixels[0, :], pixels[-1, :], pixels[1:-1, 0], pixels[1:-1, -1]], axis=0
    )


def knock_out_plain_background(
    image_bytes: bytes, *, mime_type: str, source_asset_id: str
) -> KnockedOutImage:
    if (mime_type or "").lower() not in _RASTER_MIMES:
        raise ImageKnockOutError(
            "asset.knockout_unsupported_format",
            f"knock_out_background works on PNG, JPEG, WebP or GIF images, not {mime_type!r}.",
        )
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            if getattr(opened, "is_animated", False):
                raise ImageKnockOutError(
                    "asset.knockout_unsupported_format",
                    "knock_out_background does not work on an animated image.",
                )
            rgba = np.asarray(opened.convert("RGBA"), dtype=np.float64)
    except (UnidentifiedImageError, OSError) as error:
        raise ImageKnockOutError(
            "asset.knockout_unreadable", f"the image could not be decoded ({error})"
        ) from error

    height, width = rgba.shape[:2]
    ring = _ring(rgba)
    if np.mean(ring[:, 3] < TRANSPARENT_ALPHA) >= 0.5:
        raise ImageKnockOutError(
            "asset.knockout_already_transparent",
            "the image's background is already transparent; place it as it is.",
        )
    opaque_ring = ring[ring[:, 3] >= TRANSPARENT_ALPHA][:, :3]
    background = np.median(opaque_ring, axis=0)
    ring_distance = np.sqrt(((opaque_ring - background) ** 2).sum(axis=1))
    if np.mean(ring_distance <= RING_TOLERANCE) < RING_PLAIN_SHARE:
        raise ImageKnockOutError(
            "asset.knockout_background_not_plain",
            "the image's background is not one plain colour; for a photo use "
            "edit_image with remove_background.",
        )

    colour = rgba[:, :, :3]
    # Colour to alpha: per channel, how far the pixel is from the background towards the far end
    # of that channel's range; the pixel needs at least the largest of those as its opacity.
    above = np.where(
        background < 255, (colour - background) / np.maximum(255 - background, 1e-9), 0.0
    )
    below = np.where(background > 0, (background - colour) / np.maximum(background, 1e-9), 0.0)
    per_channel = np.where(colour > background, above, np.where(colour < background, below, 0.0))
    alpha = np.clip(per_channel.max(axis=2), 0.0, 1.0)
    distance = np.sqrt(((colour - background) ** 2).sum(axis=2))
    alpha[distance <= NOISE_FLOOR] = 0.0

    safe = np.where(alpha > 0, alpha, 1.0)[:, :, None]
    foreground = np.clip(background + (colour - background) / safe, 0, 255)
    out_alpha = alpha * (rgba[:, :, 3] / 255.0)
    result = np.dstack([foreground, out_alpha * 255.0])
    result[out_alpha <= 0] = 0.0
    result = np.rint(result).astype(np.uint8)

    visible = np.argwhere(result[:, :, 3] > 0)
    if visible.size == 0:
        raise ImageKnockOutError(
            "asset.knockout_nothing_left",
            "nothing but the background colour is in this image; there is nothing to keep.",
        )
    top, left = visible.min(axis=0)
    bottom, right = visible.max(axis=0) + 1
    trimmed = result[top:bottom, left:right]

    buffer = io.BytesIO()
    Image.fromarray(trimmed).save(buffer, format="PNG")
    png_bytes = buffer.getvalue()
    receipt = {
        "operation": "knock_out_background",
        "version": 1,
        "source_asset_id": source_asset_id,
        "source_digest": hashlib.sha256(image_bytes).hexdigest(),
        "output_digest": hashlib.sha256(png_bytes).hexdigest(),
        "background_rgb": [int(round(v)) for v in background],
        "source_dimensions": {"width": int(width), "height": int(height)},
        "output_dimensions": {
            "width": int(right - left),
            "height": int(bottom - top),
        },
        "trim_box": [int(left), int(top), int(right), int(bottom)],
    }
    return KnockedOutImage(png_bytes=png_bytes, receipt=receipt)
