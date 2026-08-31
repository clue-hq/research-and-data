"""Measured brand geometry → scale steps (design-brief plan, slice 2).

`scales.py` owns the BASE scale — the platform's fallback rhythm. This module
owns the part that comes off the brand's own site: it clusters the measured
`NumberSample` / `ShadowSample` evidence the capture layer now harvests and says
which named steps that evidence can honestly claim. Whatever it cannot claim
stays derived, provenance intact.

Clustering follows `cluster.py`'s idiom exactly — accumulate members while the
running mean stays inside a tolerance, keep the heaviest member's exact value as
the cluster's representative (so a brand's real 6px radius never drifts to 5.5),
sum the weights, order by weight descending with a deterministic tie-break.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..evidence import NumberSample, ShadowSample

# Confidence for a measured value. Above the derived 0.6 because the number was
# read off the brand's own rendered page rather than invented by a default
# scale; below the 0.9 reserved for a directly-observed atomic value (a hex, a
# font family) because a scale step is a CLUSTER REPRESENTATIVE over many
# observations — one inference step away from any single measurement.
MEASURED_CONFIDENCE = 0.8

# Radii at or above this are "fully round", not a scale step.
PILL_RADIUS_PX = 9999.0
# A shadow whose color drifts this far off grey is the brand's colored elevation.
_CHROMATIC_SPREAD = 24


@dataclass
class NumberCluster:
    """One candidate scale value, with the pointer of its heaviest member."""

    value: float
    weight: float
    count: int
    role_hints: list[str] = field(default_factory=list)
    pointer_source: str = ""
    pointer_locator: str = ""

    @property
    def provenance(self) -> str:
        return f"{self.pointer_source}:{self.pointer_locator}"


@dataclass
class _Accumulator:
    members: list[NumberSample]
    value_sum: float
    weight: float


def cluster_numbers(
    samples: list[NumberSample],
    kind: str,
    *,
    hints: tuple[str, ...] = (),
    any_hints: tuple[str, ...] = (),
    abs_tolerance: float = 1.0,
    rel_tolerance: float = 0.0,
) -> list[NumberCluster]:
    """Cluster same-kind samples into candidate scale values.

    `hints` is an ALL-OF filter (`("padding", "card")` selects a card's own
    padding, not every sample a card happened to produce); `any_hints` is an
    ANY-OF family filter (the layout spacing family).
    """
    usable = [
        s
        for s in samples
        if s.kind == kind
        and math.isfinite(s.value)
        and s.value > 0
        and all(hint in s.role_hints for hint in hints)
        and (not any_hints or any(hint in s.role_hints for hint in any_hints))
    ]
    accumulators: list[_Accumulator] = []
    for sample in usable:
        placed = False
        for acc in accumulators:
            mean = acc.value_sum / acc.weight if acc.weight > 0 else acc.value_sum
            tolerance = max(abs_tolerance, mean * rel_tolerance)
            if abs(mean - sample.value) <= tolerance:
                acc.members.append(sample)
                acc.value_sum += sample.value * sample.weight
                acc.weight += sample.weight
                placed = True
                break
        if not placed:
            accumulators.append(
                _Accumulator(
                    members=[sample],
                    value_sum=sample.value * sample.weight,
                    weight=sample.weight,
                )
            )

    clusters = [_finalize(acc) for acc in accumulators]
    clusters.sort(key=lambda c: (-c.weight, c.value))
    return clusters


def _finalize(acc: _Accumulator) -> NumberCluster:
    # The representative is the cluster's MOST-OBSERVED exact value, not its
    # mean: a brand that draws 4px corners on 43 surfaces and 5px on two has a
    # 4px radius, and a merged mean of 4.04 would be a value it never uses.
    # (`cluster.py` keeps the heaviest member's exact hex for the same reason;
    # numbers repeat where hexes do not, so the tally is by value.)
    tally: dict[float, tuple[float, int]] = {}
    for member in acc.members:
        weight, count = tally.get(member.value, (0.0, 0))
        tally[member.value] = (weight + member.weight, count + 1)
    representative = min(
        tally.items(), key=lambda item: (-item[1][0], -item[1][1], item[0])
    )[0]
    heaviest = max(
        (m for m in acc.members if m.value == representative),
        key=lambda m: m.weight,
    )
    hints: list[str] = []
    for member in acc.members:
        for hint in member.role_hints:
            if hint not in hints:
                hints.append(hint)
    return NumberCluster(
        value=heaviest.value,
        weight=acc.weight,
        count=len(acc.members),
        role_hints=hints,
        pointer_source=heaviest.pointer.source,
        pointer_locator=heaviest.pointer.locator,
    )


def assign_steps(
    steps: dict[str, float], clusters: list[NumberCluster]
) -> dict[str, NumberCluster]:
    """Claim named scale steps with measured clusters, monotonically.

    The heaviest clusters compete for the ladder (there are only as many seats as
    distinct step values), but the seating itself walks both lists in ascending
    order so the emitted scale can never invert — a brand whose most-used gap is
    96px must not end up with `space.10 = 96` above `space.12 = 32`. Steps that
    share a default value (`stroke.width.thin` and `.default` are both 1px) are
    claimed together: they name one rung of the ladder, not two.
    """
    distinct = sorted({value for value in steps.values() if value > 0})
    if not distinct or not clusters:
        return {}

    seats = clusters[: len(distinct)]
    ascending = sorted(seats, key=lambda c: (c.value, -c.weight))

    claimed: dict[str, NumberCluster] = {}
    cursor = 0
    for cluster in ascending:
        available = distinct[cursor:]
        if not available:
            break
        target = min(available, key=lambda step: abs(math.log(cluster.value / step)))
        cursor = distinct.index(target) + 1
        for path, default in steps.items():
            if default == target:
                claimed[path] = cluster
    return claimed


def hinted_cluster(
    samples: list[NumberSample], kind: str, *hints: str, **kwargs
) -> NumberCluster | None:
    """The dominant measured value for one semantic role, or None."""
    clusters = cluster_numbers(samples, kind, hints=tuple(hints), **kwargs)
    return clusters[0] if clusters else None


def pill_cluster(samples: list[NumberSample]) -> NumberCluster | None:
    """The measured evidence that this brand draws fully-round surfaces."""
    for cluster in cluster_numbers(samples, "radius", abs_tolerance=1.0):
        if cluster.value >= PILL_RADIUS_PX:
            return cluster
    return None


def scale_clusters(
    samples: list[NumberSample], kind: str, **kwargs
) -> list[NumberCluster]:
    """Ladder candidates for one kind — pill radii excluded (they are not steps)."""
    return [
        cluster
        for cluster in cluster_numbers(samples, kind, **kwargs)
        if cluster.value < PILL_RADIUS_PX
    ]


# --- shadows --------------------------------------------------------------------


@dataclass
class ShadowCluster:
    sample: ShadowSample
    count: int

    @property
    def elevation(self) -> float:
        return abs(self.sample.y) + self.sample.blur + max(0.0, self.sample.spread)

    @property
    def chromatic(self) -> bool:
        body = self.sample.color.lstrip("#")[:6]
        try:
            channels = [int(body[i : i + 2], 16) for i in (0, 2, 4)]
        except ValueError:
            return False
        return max(channels) - min(channels) >= _CHROMATIC_SPREAD

    @property
    def provenance(self) -> str:
        return f"{self.sample.pointer.source}:{self.sample.pointer.locator}"


def cluster_shadows(shadows: list[ShadowSample]) -> list[ShadowCluster]:
    """Fold identical elevations together, ordered lightest → heaviest.

    Shadows are already discrete authored values (one CSS declaration reused
    across a component), so the signature is the rounded geometry + color rather
    than a distance merge.
    """
    groups: dict[tuple, ShadowCluster] = {}
    for sample in shadows:
        key = (
            round(sample.x),
            round(sample.y),
            round(sample.blur),
            round(sample.spread),
            sample.color,
            round(sample.opacity, 2),
        )
        existing = groups.get(key)
        if existing is None:
            groups[key] = ShadowCluster(sample=sample, count=1)
        else:
            existing.count += 1
    clusters = list(groups.values())
    clusters.sort(key=lambda c: (c.elevation, c.sample.blur, c.sample.color))
    return clusters


def build_shadows(shadows: list[ShadowSample]) -> dict[str, tuple[dict, str]]:
    """Measured elevation tokens: path → (shadow value, provenance pointer).

    Returns `{}` for a site with no box-shadows anywhere. That is not a gap — a
    flat brand IS the finding, and inventing an elevation for it would be the
    only real failure here.
    """
    clusters = cluster_shadows(shadows)
    if not clusters:
        return {}

    names = ("shadow.sm", "shadow.md", "shadow.lg")
    emitted: dict[str, tuple[dict, str]] = {}
    for index, cluster in enumerate(clusters[: len(names)]):
        emitted[names[index]] = (_shadow_value(cluster.sample), cluster.provenance)

    chromatic = [c for c in clusters if c.chromatic]
    if chromatic:
        brand = max(chromatic, key=lambda c: (c.count, c.elevation))
        emitted["shadow.brand"] = (_shadow_value(brand.sample), brand.provenance)
    return emitted


def _shadow_value(sample: ShadowSample) -> dict:
    alpha = max(0, min(255, round(sample.opacity * 255)))
    color = sample.color[:7].upper()
    if alpha < 255:
        color = f"{color}{alpha:02X}"
    return {
        "x": float(sample.x),
        "y": float(sample.y),
        "blur": float(sample.blur),
        "spread": float(sample.spread),
        "color": color,
    }
