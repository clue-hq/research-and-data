"""Pixel census over the rendered capture — the ground truth for palette election.

The stylesheet can only say what a color COULD be; the screenshot says what the
page actually shows. This module turns the rendered tier's full-page screenshot
plus the render-probe harvest (element boxes, media boxes, gradient stops,
resolved tokens) into a :class:`~lumen_ingestion.evidence.RenderTruth`: census
clusters with rendered share, per-role region colors (buttons), chromatic
accent-text families, and gradient-stop families.

Method notes, each learned from a live failure:

* **Quantize-then-merge.** Channels are bucketed (``QUANT_STEP``) through a PIL
  point LUT and counted with ``getcolors`` — both C-speed — then the buckets are
  greedily merged in OKLab at the same ``MERGE_DISTANCE`` the evidence
  clustering uses, heaviest first, so census clusters and evidence clusters
  agree about what "the same color" means.
* **Photo masking is diversity-aware.** A photograph (skin, sky, scene) is
  high-diversity and must not vote — it is not brand chrome. But a brand wash /
  aurora served as an image is a LOW-diversity smooth ramp and is exactly the
  brand surface (live finding: sarvam.ai). A media box is subtracted from the
  census only when its own mini-census looks photographic.
* **Gradients cannot win a census** — every row is a different blend, so no
  bucket accumulates share. Their resolved endpoint stops arrive via the
  render probe and are grouped here into area-weighted families.
* **Overlap caveat:** photo boxes that overlap are each subtracted, so a pixel
  under two photos is subtracted twice; counts clamp at zero. The error is
  bounded, always in the safe direction (under-counts imagery regions), and
  costs far less than a real mask raster at these image sizes.

Pure over bytes + dicts; PIL is imported lazily so importing this module (and
everything that imports it) stays dependency-light.
"""

from __future__ import annotations

import io
from collections import Counter

from .colorspace import PASTEL_C, hex_to_oklab, hex_to_oklch, oklab_distance
from .evidence import (
    AccentTextFamily,
    CensusCluster,
    GradientStopFamily,
    RegionColorFamily,
    RenderTruth,
)
from .normalizer.cluster import MERGE_DISTANCE

#: Channel bucket width for the census histogram. Coupled to MERGE_DISTANCE:
#: adjacent buckets must merge (bucket ΔE < merge distance) or quantization
#: noise survives as separate "colors".
QUANT_STEP = 8
#: Buckets fed to the perceptual merge, heaviest first.
TOP_BUCKETS = 400
#: "Above the fold"-ish: the first two 1200px viewports of CSS pixels.
FOLD_CSS_PX = 2400
#: A media region whose top-5 mini-census clusters cover at least this much is
#: brand art (smooth ramp / flat art), not photography, and stays in the census.
ART_TOP5_SHARE = 0.6
ART_MAX_CLUSTERS = 25
#: A button region must be at least this pure (modal bucket share) to speak for
#: the button's surface — busier regions are icon/label soup, not a swatch.
REGION_PURITY = 0.3
#: Gradient families below this fraction of page area are decorative noise.
GRADIENT_MIN_AREA = 0.01

_LUT = bytes(min(255, (v // QUANT_STEP) * QUANT_STEP + QUANT_STEP // 2) for v in range(256)) * 3


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _counts(img) -> Counter:
    """Bucket-color counts of a (pre-quantized) RGB image, as a Counter."""
    got = img.getcolors(maxcolors=1_000_000) or []
    return Counter({color: count for count, color in got})


def merge_counts(counts: Counter) -> list[dict]:
    """Greedy OKLab merge of bucket counts, heaviest first; shares of the total."""
    total = sum(counts.values())
    if total <= 0:
        return []
    clusters: list[dict] = []
    for color, n in counts.most_common(TOP_BUCKETS):
        hx = _hex(color)
        lab = hex_to_oklab(hx)
        for cl in clusters:
            if oklab_distance(cl["lab"], lab) <= MERGE_DISTANCE:
                cl["count"] += n
                break
        else:
            clusters.append({"hex": hx, "lab": lab, "count": n})
    clusters.sort(key=lambda c: -c["count"])
    return [
        {"hex": c["hex"], "lab": c["lab"], "share": c["count"] / total}
        for c in clusters
    ]


def _box_pixels(box: dict, scale: float, width: int, height: int) -> tuple[int, int, int, int] | None:
    x0 = max(0, int(box["l"] * scale)); y0 = max(0, int(box["t"] * scale))
    x1 = min(width, int((box["l"] + box["w"]) * scale))
    y1 = min(height, int((box["t"] + box["h"]) * scale))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return x0, y0, x1, y1


def _is_photograph(crop_counts: Counter) -> bool:
    clusters = merge_counts(crop_counts)
    if not clusters:
        return False
    top5 = sum(c["share"] for c in clusters[:5])
    return top5 < ART_TOP5_SHARE and len(clusters) > ART_MAX_CLUSTERS


def _family_add(families: dict[str, float], hx: str, amount: float) -> None:
    lab = hex_to_oklab(hx)
    for key in families:
        if oklab_distance(hex_to_oklab(key), lab) <= MERGE_DISTANCE:
            families[key] += amount
            return
    families[hx] = amount


def build_render_truth(snapshot, parse_color) -> RenderTruth | None:
    """Compute :class:`RenderTruth` from a rendered snapshot, or ``None``.

    ``parse_color`` is :func:`lumen_ingestion.capture.parse.parse_color_value`
    partially applied by the caller — injected so this module does not import
    the capture package (which must stay importable without PIL, while this
    function is exactly the PIL-using code).

    Returns ``None`` when the snapshot has no render probe or no screenshot —
    every pre-probe fixture and every static-tier capture — in which case the
    normalizer keeps its evidence-cluster path.
    """
    probe = getattr(snapshot, "render_probe", None)
    if not probe:
        return None
    shot_sha = next(
        (d.sha256 for d in snapshot.downloads if d.kind == "screenshot"), None
    )
    shot = snapshot.download_bytes(shot_sha) if shot_sha else None
    if shot is None:
        return None

    from PIL import Image  # lazy: keeps module import PIL-free

    img = Image.open(io.BytesIO(shot)).convert("RGB").point(_LUT)
    width, height = img.size
    css_width = float(probe.get("viewport_width") or 1440)
    scale = width / css_width

    # Whole-page counts, then subtract photographic media regions.
    counts = _counts(img)
    total = sum(counts.values())
    masked = 0
    for box in probe.get("media") or []:
        px = _box_pixels(box, scale, width, height)
        if px is None:
            continue
        crop_counts = _counts(img.crop(px))
        if not _is_photograph(crop_counts):
            continue  # brand art stays in the census
        masked += sum(crop_counts.values())
        counts.subtract(crop_counts)
        counts += Counter()  # drop non-positive entries (overlap clamp)
    page_clusters = merge_counts(counts)

    fold = img.crop((0, 0, width, min(height, int(FOLD_CSS_PX * scale))))
    fold_clusters = merge_counts(_counts(fold))

    # Per-role region truth: the modal rendered color inside real button boxes.
    samples = probe.get("samples") or []
    button_counts: dict[str, float] = {}
    for sample in samples:
        if sample.get("kind") != "button":
            continue
        px = _box_pixels(sample.get("box") or {}, scale, width, height)
        if px is None:
            continue
        region = merge_counts(_counts(img.crop(px)))
        if region and region[0]["share"] >= REGION_PURITY:
            _family_add(button_counts, region[0]["hex"], 1)

    def _flat(hx: str | None) -> str | None:
        """Composite a #RRGGBBAA over the page white; pass #RRGGBB through."""
        if not hx:
            return None
        if len(hx) == 7:
            return hx
        if len(hx) == 9:
            alpha = int(hx[7:9], 16) / 255.0
            rgb = tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))
            return _hex(tuple(round(alpha * c + (1 - alpha) * 255) for c in rgb))
        return None

    body = next((s for s in samples if s.get("kind") == "body"), {})
    body_bg = _flat(parse_color(str(body.get("bg") or ""))) if body.get("bg") else None
    body_text = _flat(parse_color(str(body.get("color") or ""))) if body.get("color") else None

    # Chromatic accent text: links/eyebrows/tabs colored unlike the body text.
    body_text_lab = hex_to_oklab(body_text) if body_text else None
    text_counts: dict[str, float] = {}
    for sample in samples:
        if sample.get("kind") not in ("link", "heading", "chrome"):
            continue
        hx = parse_color(str(sample.get("color") or "")) if sample.get("color") else None
        if not hx or len(hx) != 7 or hex_to_oklch(hx)[1] < PASTEL_C:
            continue
        if body_text_lab is not None and oklab_distance(hex_to_oklab(hx), body_text_lab) <= MERGE_DISTANCE:
            continue
        _family_add(text_counts, hx, 1)

    # Gradient stops, area-weighted (fraction of page CSS area).
    page_area = (width / scale) * (height / scale)
    gradient_area: dict[str, float] = {}
    for grad in probe.get("gradients") or []:
        box = grad.get("box") or {}
        area = float(box.get("w") or 0) * float(box.get("h") or 0)
        for stop in grad.get("stops") or []:
            hx = parse_color(str(stop))
            if not hx or len(hx) != 7 or hex_to_oklch(hx)[1] < PASTEL_C:
                continue
            _family_add(gradient_area, hx, area / page_area)

    tokens: dict[str, str] = {}
    for name, value in (probe.get("tokens") or {}).items():
        hx = parse_color(str(value))
        if hx and len(hx) == 7:
            tokens[name] = hx

    return RenderTruth(
        page_clusters=[CensusCluster(hex=c["hex"], share=c["share"]) for c in page_clusters[:40]],
        fold_clusters=[CensusCluster(hex=c["hex"], share=c["share"]) for c in fold_clusters[:40]],
        button_families=[
            RegionColorFamily(hex=hx, count=int(n))
            for hx, n in sorted(button_counts.items(), key=lambda kv: -kv[1])
        ],
        accent_text=[
            AccentTextFamily(hex=hx, count=int(n))
            for hx, n in sorted(text_counts.items(), key=lambda kv: -kv[1])
        ],
        gradient_stops=[
            GradientStopFamily(hex=hx, area_fraction=frac)
            for hx, frac in sorted(gradient_area.items(), key=lambda kv: -kv[1])
            if frac >= GRADIENT_MIN_AREA
        ],
        body_bg=body_bg,
        body_text=body_text,
        resolved_tokens=tokens,
        masked_fraction=(masked / total) if total else 0.0,
        canvas_viewport_fraction=float(probe.get("canvas_viewport_fraction") or 0.0),
    )
