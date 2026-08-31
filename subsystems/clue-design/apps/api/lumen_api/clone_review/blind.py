"""The blind side-by-side — the founder acceptance artifact for CP1 (F3.3).

CP1's acceptance is *"a published page a reviewer cannot reliably distinguish from the client's
real homepage"*, and that sentence only means anything if the reviewer genuinely cannot tell
which picture is which. A labelled comparison tests nothing: shown "ours" and "theirs", a human
finds the differences they already expect to find.

So this composes ONE image carrying both full-page screenshots under the neutral captions **A**
and **B**, in an order derived from a seed, and returns the answer key **separately**. Nothing in
the image says which panel is the clone. The walk (T21) shows the image, records a judgement,
and only then opens the key.

**The key is sealed to the image it answers for.** It carries the sha256 of the composed PNG, so
a key read against a different (or later) artifact can be caught rather than quietly believed.

**The order is seeded, not random.** A random order cannot be reproduced, and an acceptance
artifact nobody can regenerate is an anecdote. The same seed always yields the same arrangement,
so a disputed walk can be rebuilt exactly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Any

BLIND_SCHEMA_VERSION = 1

#: The two captions, and the whole vocabulary the image is allowed to contain.
PANEL_LABELS = ("A", "B")

#: What each panel actually is. These strings appear ONLY in the key.
SIDE_PUBLISHED = "published"
SIDE_REFERENCE = "reference"

#: How wide each panel is drawn. Wide enough to judge type and spacing on a normal screen;
#: bounded so a 12,000px page pair does not compose a 40 MB artifact.
PANEL_WIDTH = 720

#: How tall a panel may be before it is cropped from the top. A full homepage pair at full height
#: is unreadable on any screen; the top 3600px is the part a "can you tell which is which"
#: judgement is actually made on. A cropped panel SAYS it was cropped, in the key.
PANEL_MAX_HEIGHT = 3600

_HEADER_HEIGHT = 44
_GUTTER = 24
_MARGIN = 16
_BACKGROUND = (244, 244, 246)
_INK = (24, 24, 27)


@dataclass(frozen=True)
class BlindComparison:
    """The artifact and its sealed key — two objects, deliberately never one."""

    image_png: bytes
    #: ``{"A": "published"|"reference", "B": ...}`` plus the artifact digest. The caller writes
    #: this somewhere the judge does not look until afterwards.
    key: dict[str, Any]

    @property
    def image_sha256(self) -> str:
        return str(self.key["artifact_sha256"])


def build_blind_side_by_side(
    *,
    published_png: bytes,
    reference_png: bytes,
    seed: str,
    published_caption: str = "page A",
) -> BlindComparison:
    """Compose the unlabelled pair, and answer separately for which is which.

    ``published_caption`` exists so a caller can record what it MEANT by "published" (a preview,
    a published slug) in the key; it never reaches the image.
    """
    from PIL import Image, ImageDraw, ImageFont

    order = _order(seed)
    panels = {SIDE_PUBLISHED: published_png, SIDE_REFERENCE: reference_png}
    images = []
    cropped: dict[str, bool] = {}
    for side in order:
        prepared, was_cropped = _prepare(Image, panels[side])
        images.append(prepared)
        cropped[side] = was_cropped

    body_height = max(image.height for image in images)
    width = _MARGIN * 2 + PANEL_WIDTH * 2 + _GUTTER
    height = _MARGIN * 2 + _HEADER_HEIGHT + body_height
    canvas = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:  # Pillow < 10.1 — the bitmap default, small but present
        font = ImageFont.load_default()

    for index, image in enumerate(images):
        x = _MARGIN + index * (PANEL_WIDTH + _GUTTER)
        draw.text((x, _MARGIN), PANEL_LABELS[index], fill=_INK, font=font)
        canvas.paste(image, (x, _MARGIN + _HEADER_HEIGHT))

    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    data = buffer.getvalue()

    key = {
        "schema_version": BLIND_SCHEMA_VERSION,
        "panels": {PANEL_LABELS[index]: side for index, side in enumerate(order)},
        "artifact_sha256": hashlib.sha256(data).hexdigest(),
        "seed": seed,
        "published_is": published_caption,
        "cropped": cropped,
        "panel_width_px": PANEL_WIDTH,
        "panel_max_height_px": PANEL_MAX_HEIGHT,
    }
    return BlindComparison(image_png=data, key=key)


def _order(seed: str) -> tuple[str, str]:
    """Which side goes on the left, decided by the seed and by nothing else."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    if digest[0] % 2 == 0:
        return (SIDE_PUBLISHED, SIDE_REFERENCE)
    return (SIDE_REFERENCE, SIDE_PUBLISHED)


def _prepare(image_module: Any, data: bytes) -> tuple[Any, bool]:
    with image_module.open(BytesIO(data)) as opened:
        rgb = opened.convert("RGB")
        scale = PANEL_WIDTH / float(max(rgb.width, 1))
        resized = rgb.resize(
            (PANEL_WIDTH, max(1, int(round(rgb.height * scale)))),
            image_module.Resampling.LANCZOS,
        )
        if resized.height > PANEL_MAX_HEIGHT:
            return resized.crop((0, 0, PANEL_WIDTH, PANEL_MAX_HEIGHT)), True
        return resized.copy(), False


def key_matches(key: dict[str, Any], image_png: bytes) -> bool:
    """Is this key the key for THIS artifact? The seal, checked."""
    return str(key.get("artifact_sha256") or "") == hashlib.sha256(image_png).hexdigest()


__all__ = [
    "BLIND_SCHEMA_VERSION",
    "PANEL_LABELS",
    "PANEL_MAX_HEIGHT",
    "PANEL_WIDTH",
    "SIDE_PUBLISHED",
    "SIDE_REFERENCE",
    "BlindComparison",
    "build_blind_side_by_side",
    "key_matches",
]
