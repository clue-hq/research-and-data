"""Color clustering (§3.1).

Merge colors within OKLab distance 0.03: weighted mean in OKLab re-rendered to
hex, union of role_hints, summed weights, first `name` kept. The exact hex of the
max-weight member is retained as `representative` so brand colors never drift.
Light and dark theme evidence cluster separately. Fully-transparent colors are
ignored. Output is ordered by weight descending (deterministic tie-break on hex).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..colorspace import hex_alpha, hex_to_oklab, hex_to_rgb, oklab_distance, oklab_to_hex, rgb_to_hex
from ..evidence import ColorEvidence

#: The OKLab distance at which two colors are the same color. Public because
#: `bands.py` groups and dedupes measured band backgrounds at the same
#: tolerance, and its dedupe is only correct while the two agree — a band that
#: merged into an evidence cluster must also recognize that cluster's color.
MERGE_DISTANCE = 0.03
_MIN_ALPHA = 0.05


def _composite(color: ColorEvidence) -> ColorEvidence:
    """Flatten alpha to the color's SEEN value before clustering.

    A hero pill at 20% alpha must not win surface.brand with its raw channel
    values — role assignment reasons about what the page actually shows. Light
    evidence composites over white, dark over black (the overwhelmingly common
    page bases per theme; if the true base differs, the opaque swatch will
    usually also exist as its own evidence and outweigh this one).
    """
    alpha = hex_alpha(color.value)
    if alpha >= 1.0:
        return color
    base = (1.0, 1.0, 1.0) if color.theme == "light" else (0.0, 0.0, 0.0)
    rgb = hex_to_rgb(color.value)
    flattened = rgb_to_hex(
        tuple(alpha * c + (1.0 - alpha) * b for c, b in zip(rgb, base))
    )
    return color.model_copy(update={"value": flattened})


@dataclass
class ColorCluster:
    representative: str          # exact hex of the heaviest member
    lab: tuple[float, float, float]  # weighted-mean OKLab
    mean_hex: str                # hex of the weighted mean
    weight: float
    theme: str
    role_hints: list[str] = field(default_factory=list)
    name: str | None = None
    pointer_source: str = ""
    pointer_locator: str = ""

    @property
    def hex(self) -> str:
        return self.representative


@dataclass
class _Accumulator:
    members: list[ColorEvidence]
    lab_sum: tuple[float, float, float]
    weight: float
    theme: str


def cluster_colors(colors: list[ColorEvidence]) -> list[ColorCluster]:
    usable = [_composite(c) for c in colors if hex_alpha(c.value) > _MIN_ALPHA]
    light = [c for c in usable if c.theme == "light"]
    dark = [c for c in usable if c.theme == "dark"]
    return _cluster_theme(light, "light") + _cluster_theme(dark, "dark")


def _cluster_theme(colors: list[ColorEvidence], theme: str) -> list[ColorCluster]:
    accumulators: list[_Accumulator] = []
    for color in colors:
        lab = hex_to_oklab(color.value)
        placed = False
        for acc in accumulators:
            mean = _mean(acc)
            if oklab_distance(mean, lab) <= MERGE_DISTANCE:
                acc.members.append(color)
                acc.lab_sum = _add(acc.lab_sum, _scale(lab, color.weight))
                acc.weight += color.weight
                placed = True
                break
        if not placed:
            accumulators.append(
                _Accumulator(
                    members=[color],
                    lab_sum=_scale(lab, color.weight),
                    weight=color.weight,
                    theme=theme,
                )
            )

    clusters = [_finalize(acc) for acc in accumulators]
    clusters.sort(key=lambda c: (-c.weight, c.representative))
    return clusters


def _finalize(acc: _Accumulator) -> ColorCluster:
    mean_lab = _mean(acc)
    heaviest = max(acc.members, key=lambda m: (m.weight, m.value))
    role_hints: list[str] = []
    name: str | None = None
    for member in acc.members:
        for hint in member.role_hints:
            if hint not in role_hints:
                role_hints.append(hint)
        if name is None and member.name:
            name = member.name
    return ColorCluster(
        representative=heaviest.value,
        lab=mean_lab,
        mean_hex=oklab_to_hex(mean_lab),
        weight=acc.weight,
        theme=acc.theme,
        role_hints=role_hints,
        name=name,
        pointer_source=heaviest.pointer.source,
        pointer_locator=heaviest.pointer.locator,
    )


def _mean(acc: _Accumulator) -> tuple[float, float, float]:
    if acc.weight <= 0:
        return acc.lab_sum
    return _scale(acc.lab_sum, 1.0 / acc.weight)


def _add(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: tuple[float, float, float], k: float) -> tuple[float, float, float]:
    return (a[0] * k, a[1] * k, a[2] * k)
