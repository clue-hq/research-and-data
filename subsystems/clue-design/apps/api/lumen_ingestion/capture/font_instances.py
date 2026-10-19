"""Static instances of a harvested VARIABLE font (Editor Quality Plan 1, item B, 2026-09-04).

A site that ships one variable file (Apollo: ``soehne`` and ``seasonMix``, both with a ``wght``
axis) used to land in the kit as ONE face at weight 400. Neither renderer synthesises bold, so
Bold selected the same face and changed nothing. This module pins the axis at each named
weight with the SAME instancer the Google font library uses (``font_library._instance_bytes``:
OS/2 weight, name table, and RIBBI bits all rewritten to describe the instance), so every
instance is a static face both Skia runtimes match on.

Pure: bytes in, bytes out, no I/O. The evidence builder decides what to do with the plan.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from io import BytesIO

from lumen_api.font_containers import FontContainerError, decode_web_font
from lumen_ingestion.font_library import FontLibraryError, _instance_bytes

#: The named weights a kit face can be asked for by the type roles and the editor's Bold.
INSTANCE_WEIGHTS: tuple[int, ...] = (400, 500, 600, 700)


def instance_weights(family: str, samples) -> tuple[int, ...]:
    """The named weights plus every weight the site was measured using this family.

    Stripe sets its headings in sohne-var at weight 300; with only 400-700 instanced the kit had no
    300 face and every role snapped to 400. Weights outside the font's axis are skipped later by
    :func:`plan_font_instances`, so an over-wide list costs nothing.
    """
    wanted = family.strip().lower()
    measured = {
        int(sample.weight)
        for sample in samples
        if sample.family and sample.family.strip().lower() == wanted
        and sample.weight and 1 <= int(sample.weight) <= 1000
    }
    return tuple(sorted(set(INSTANCE_WEIGHTS) | measured))


@dataclass(frozen=True)
class FontInstance:
    weight: int
    italic: bool
    data: bytes
    sha256: str


@dataclass
class FontInstancePlan:
    family: str
    variable: bool
    wght_range: tuple[float, float] | None
    instances: list[FontInstance] = field(default_factory=list)
    skipped_weights: list[int] = field(default_factory=list)
    error: str | None = None


def _sfnt_bytes(data: bytes) -> bytes:
    decoded = decode_web_font(data)
    return decoded.data if decoded is not None else data


def _wght_axis(data: bytes) -> tuple[float, float] | None:
    from fontTools.ttLib import TTFont

    try:
        font = TTFont(BytesIO(data), recalcTimestamp=False, recalcBBoxes=False, lazy=True)
        fvar = font.get("fvar")
    except Exception:  # noqa: BLE001 — not a font we can read: then it is not variable
        return None
    if fvar is None:
        return None
    for axis in fvar.axes:
        if axis.axisTag == "wght":
            return (float(axis.minValue), float(axis.maxValue))
    return None


def plan_font_instances(
    family: str,
    data: bytes,
    *,
    italic: bool = False,
    weights: tuple[int, ...] = INSTANCE_WEIGHTS,
) -> FontInstancePlan:
    """One static instance per weight in ``weights`` that the font's ``wght`` axis covers.

    A static font (no ``fvar``/``wght``) returns ``variable=False`` and no instances. Undecodable
    bytes, or an instancer failure on any weight, return ``error`` and NO instances — the
    caller keeps the original face; a half-instanced family would be worse than none.
    """
    try:
        source = _sfnt_bytes(data)
    except FontContainerError as error:
        return FontInstancePlan(family, False, None, error=str(error))
    axis = _wght_axis(source)
    if axis is None:
        return FontInstancePlan(family, False, None)
    plan = FontInstancePlan(family, True, axis)
    low, high = axis
    for weight in weights:
        if not (low <= weight <= high):
            plan.skipped_weights.append(weight)
            continue
        try:
            instance = _instance_bytes(source, weight, family, italic=italic)
        except (FontLibraryError, Exception) as error:  # noqa: BLE001 — fontTools raises a zoo
            plan.error = f"weight {weight}: {type(error).__name__}: {error}"
            plan.instances.clear()
            return plan
        plan.instances.append(
            FontInstance(weight, italic, instance, hashlib.sha256(instance).hexdigest())
        )
    return plan
