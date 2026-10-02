"""Lossless, provider-free extraction of an integer source-pixel rectangle.

Coordinates refer to the original decoded raster, never a resized preview.
Nonidentity EXIF orientation is refused instead of silently rotating coordinates.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import struct
import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from PIL import Image, PngImagePlugin, UnidentifiedImageError

from .imagery_checks import STUB_MODEL


class ImageCropError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CroppedImage:
    png_bytes: bytes
    receipt: dict[str, Any]


def _crop_receipt(record: dict[str, Any]) -> dict[str, Any] | None:
    """The latest recognized crop receipt bound to this record's output bytes."""
    if (record.get("source") or {}).get("kind") != "manual":
        return None
    digest = (record.get("media") or {}).get("digest") or {}
    if digest.get("algorithm") != "sha256":
        return None
    for note in reversed((record.get("provenance") or {}).get("notes") or []):
        if not isinstance(note, str) or not note.startswith("asset_derivation="):
            continue
        try:
            receipt = json.loads(note.removeprefix("asset_derivation="))
        except (TypeError, ValueError):
            continue
        if (
            isinstance(receipt, dict)
            and receipt.get("operation") == "crop_image"
            and type(receipt.get("version")) is int
            and receipt["version"] == 1
            and receipt.get("output_digest") == digest.get("value")
            and re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("output_digest")))
            and re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("source_digest")))
            and isinstance(receipt.get("source_asset_id"), str)
            and receipt["source_asset_id"]
            and type(receipt.get("source_generated")) is bool
        ):
            return receipt
    return None


def recorded_generated_image_origin(record: dict[str, Any]) -> bool | None:
    """Recorded origin only; digest binding associates a receipt, not advertiser truth.

    None means no recognized origin evidence. In particular, a manual/website/uploaded
    source kind alone cannot prove that its imagery was not generated.
    """
    if (record.get("source") or {}).get("kind") in {"generated", "edited"}:
        return True
    receipt = _crop_receipt(record)
    return bool(receipt["source_generated"]) if receipt is not None else None


def has_generated_image_origin(record: dict[str, Any]) -> bool:
    """Keep the generated-imagery gate across our digest-bound crop receipts."""
    return recorded_generated_image_origin(record) is True


def require_supported_crop_origin(
    record: dict[str, Any], resolve_record: Callable[[str], dict[str, Any] | None]
) -> None:
    """Refuse placeholders, including old crops that erased the model label.

    Follow digest-bound parent records in the authorized context. A missing or
    ambiguous chain cannot establish that this is a real source, so it refuses.
    No recursive blob access or changes to the imagery-quality gate are needed.
    """
    seen: set[tuple[str, str]] = set()
    for _ in range(64):
        if (record.get("source") or {}).get("model") == STUB_MODEL or record.get(
            "kind"
        ) == "placeholder":
            raise ImageCropError(
                "asset.crop_unsupported_source", "Stub or placeholder imagery cannot be cropped."
            )
        identity = (str(record.get("id")), str((record.get("media") or {}).get("digest")))
        if identity in seen:
            break
        seen.add(identity)
        receipt = _crop_receipt(record)
        if receipt is None:
            notes = (record.get("provenance") or {}).get("notes") or []
            if (record.get("source") or {}).get("kind") == "manual" and any(
                isinstance(note, str) and note.startswith("asset_derivation=") for note in notes
            ):
                break
            return
        parent = resolve_record(receipt["source_asset_id"])
        if (
            not isinstance(parent, dict)
            or parent.get("id") != receipt["source_asset_id"]
            or (parent.get("media") or {}).get("digest")
            != {"algorithm": "sha256", "value": receipt["source_digest"]}
        ):
            break
        record = parent
    raise ImageCropError(
        "asset.crop_unsupported_source",
        "Crop ancestry is unavailable or inconsistent; choose an original verified source.",
    )


def validate_frame_index(frame_index: Any) -> None:
    if frame_index is not None and (type(frame_index) is not int or frame_index < 0):
        raise ImageCropError(
            "asset.crop_invalid_frame",
            "frame_index must be a nonnegative integer, never a bool or fraction.",
        )


@contextmanager
def decoded_source_raster(
    source_bytes: bytes,
    *,
    mime_type: str,
    frame_index: int | None = None,
) -> Iterator[tuple[Image.Image, int]]:
    """Bounded shared decode for source viewing and cropping; no persistence.

    Explicit GIF selection yields the composited logical canvas as RGBA, retaining
    transparency. Default cropping retains its single-frame/sample-loss guards.
    Coordinates never refer to a preview or a GIF's smaller local frame patch.
    """
    validate_frame_index(frame_index)
    # Pillow exposes 16-bit RGB/RGBA PNGs as 8-bit RGB/RGBA modes. Inspect the
    # original IHDR before opening: mode validation cannot detect that loss.
    if (
        len(source_bytes) >= 25
        and source_bytes[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        and source_bytes[24] == 16
    ):
        raise ImageCropError(
            "asset.crop_unsupported", "16-bit PNG cropping is unsupported without sample loss."
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source_bytes)) as source:
                if Image.MIME.get(source.format) != mime_type:
                    raise ImageCropError(
                        "asset.crop_invalid_source", "Source bytes do not match their MIME type."
                    )
                if source.getexif().get(274, 1) != 1:
                    raise ImageCropError(
                        "asset.crop_orientation",
                        "Source has EXIF orientation; supply a normalized source first.",
                    )
                frame_count = getattr(source, "n_frames", 1)
                if frame_index is not None:
                    if source.format != "GIF":
                        raise ImageCropError(
                            "asset.crop_unsupported",
                            "Explicit frame selection currently supports GIF only.",
                        )
                    if frame_index >= frame_count:
                        raise ImageCropError(
                            "asset.crop_frame_out_of_range",
                            f"frame_index is outside the source's {frame_count} frames (0-based).",
                        )
                    # Pillow seeks sequentially from the beginning and applies local
                    # palettes, logical-canvas offsets and prior-frame disposal.
                    source.seek(frame_index)
                    source.load()
                    with source.convert("RGBA") as displayed:
                        yield displayed, frame_count
                    return
                if frame_count != 1 or source.mode not in {
                    "1",
                    "L",
                    "LA",
                    "P",
                    "RGB",
                    "RGBA",
                }:
                    raise ImageCropError(
                        "asset.crop_unsupported",
                        "Crop requires a single-frame 8-bit RGB, grayscale or palette raster.",
                    )
                source.load()
                yield source, frame_count
    except ImageCropError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ImageCropError(
            "asset.crop_invalid_source", "Source raster could not be safely decoded."
        ) from error


def crop_source_pixels(
    source_bytes: bytes,
    *,
    source_asset_id: str,
    mime_type: str,
    rect: Any,
    source_generated: bool = False,
    frame_index: int | None = None,
) -> CroppedImage:
    """Copy a bounded half-open [left, top, right, bottom] rectangle to PNG.

    No resize, alpha flattening or inferred missing pixels. Explicit GIF frames
    preserve displayed RGBA; static PNG palette/transparency and ICC data remain
    intact. Only modes PNG can store without sample loss are supported.
    """
    if (
        not isinstance(rect, list)
        or len(rect) != 4
        or any(type(value) is not int for value in rect)
    ):
        raise ImageCropError(
            "asset.crop_invalid_rect", "crop_rect must be four integers [left, top, right, bottom]."
        )
    left, top, right, bottom = rect
    if left < 0 or top < 0 or right <= left or bottom <= top:
        raise ImageCropError(
            "asset.crop_invalid_rect", "crop_rect must be nonempty and nonnegative."
        )
    with decoded_source_raster(
        source_bytes,
        mime_type=mime_type,
        frame_index=frame_index,
    ) as (source, frame_count):
        width, height = source.size
        if right > width or bottom > height:
            raise ImageCropError(
                "asset.crop_invalid_rect",
                f"crop_rect exceeds the original {width}x{height} raster.",
            )
        cropped = source.crop((left, top, right, bottom))
        output = io.BytesIO()
        options = {
            key: source.info[key] for key in ("icc_profile", "transparency") if key in source.info
        }
        if source.format == "PNG":
            # Color interpretation is metadata, not a pixel conversion.
            # Pillow does not copy these chunks when saving a new PNG.
            metadata = PngImagePlugin.PngInfo()
            if "gamma" in source.info:
                metadata.add(b"gAMA", struct.pack(">I", round(source.info["gamma"] * 100000)))
            if "srgb" in source.info:
                metadata.add(b"sRGB", bytes([source.info["srgb"]]))
            if "chromaticity" in source.info:
                metadata.add(
                    b"cHRM",
                    struct.pack(">8I", *(round(v * 100000) for v in source.info["chromaticity"])),
                )
            options["pnginfo"] = metadata
        cropped.save(output, format="PNG", **options)
    png_bytes = output.getvalue()
    return CroppedImage(
        png_bytes,
        {
            "operation": "crop_image",
            "version": 1,
            "source_asset_id": source_asset_id,
            "source_digest": hashlib.sha256(source_bytes).hexdigest(),
            "source_generated": source_generated,
            "source_mime_type": mime_type,
            "source_rect": list(rect),
            "source_dimensions": {"width": width, "height": height},
            "output_dimensions": {"width": right - left, "height": bottom - top},
            "output_digest": hashlib.sha256(png_bytes).hexdigest(),
            "orientation": "decoded_pixels_no_rotation",
            **(
                {
                    "source_frame_index": frame_index,
                    "source_frame_count": frame_count,
                    "coordinate_system": "decoded_composited_frame_pixels",
                }
                if frame_index is not None
                else {}
            ),
        },
    )
