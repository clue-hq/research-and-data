"""Read-only sRGB image-region sampling, not a full-composition accessibility audit.

Uses the subsystem's existing color math. Formula and thresholds:
https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
"""

from __future__ import annotations

import io
import math
import re

from lumen_ingestion.colorspace import contrast_ratio
from PIL import Image


def measure_image_contrast(image_bytes: bytes, foreground_color: str, region: list[float]) -> dict:
    """Measure an opaque foreground over a normalized source-image rectangle.

    Region is [left, top, right, bottom], before placement cropping/transforms.
    A regular bounded grid preserves actual source pixels; no averaging filter
    smooths away a bad contrast patch. Alpha requires composited evidence.
    """
    if not isinstance(foreground_color, str) or not re.fullmatch(
        r"#[0-9a-fA-F]{6}", foreground_color
    ):
        raise ValueError("Use the resolved opaque foreground color as #RRGGBB.")
    if (
        not isinstance(region, list)
        or len(region) != 4
        or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in region)
    ):
        raise ValueError("region must be four finite normalized coordinates.")
    left, top, right, bottom = region
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("region must have positive area inside [0, 0, 1, 1].")
    with Image.open(io.BytesIO(image_bytes)) as source:
        if source.info.get("icc_profile"):
            raise ValueError("Embedded color profile requires a color-managed composite check.")
        width, height = source.size
        box = (
            math.floor(left * width),
            math.floor(top * height),
            math.ceil(right * width),
            math.ceil(bottom * height),
        )
        crop = source.crop(box).convert("RGBA")
    if crop.getchannel("A").getextrema()[0] < 255:
        raise ValueError("The region is transparent; measure its actual composited ground instead.")
    step = max(1, math.ceil(math.sqrt(crop.width * crop.height / 65536)))
    pixels = crop.load()
    by_color: dict[tuple, float] = {}
    ratios = []
    for y in range(0, crop.height, step):
        for x in range(0, crop.width, step):
            color = pixels[x, y][:3]
            if color not in by_color:
                by_color[color] = contrast_ratio(
                    foreground_color, "#{:02x}{:02x}{:02x}".format(*color)
                )
            ratios.append(by_color[color])
    ratios.sort()
    count = len(ratios)
    return {
        "minimum": round(ratios[0], 4),
        "p05": round(ratios[int((count - 1) * 0.05)], 4),
        "median": round(ratios[count // 2], 4),
        "maximum": round(ratios[-1], 4),
        "all_sampled_at_least_3": ratios[0] >= 3,
        "all_sampled_at_least_4_5": ratios[0] >= 4.5,
        "fraction_below_3": sum(r < 3 for r in ratios) / count,
        "fraction_below_4_5": sum(r < 4.5 for r in ratios) / count,
        "sample_count": count,
        "sample_step_px": step,
        "source_size": [width, height],
        "source_pixel_box": list(box),
        "scope": (
            "Opaque foreground over sampled source pixels; excludes glyphs, plates, "
            "opacity, effects and placement crop. Map the actual copy region into "
            "source coordinates and inspect the final render too."
        ),
    }
