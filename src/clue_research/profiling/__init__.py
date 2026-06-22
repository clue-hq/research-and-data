"""`clue_research.profiling` — Deep Profiling (modes M2/M3/M4) (M8).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live
in this package's ``README.md``. Implemented by M8.

Shipped so far — the **tiny seed** (M8.2 part-1 / M8.5): the ``account.resonance.*`` and
``contact.facet.*`` field-classes as ``field_definition`` rows
(:mod:`clue_research.profiling.fields`), registered via ``load_deep_profiling_pack``. The
deep-profiling workers (M8.1–M8.4) build on top.
"""

from __future__ import annotations

from clue_research.profiling.fields import (
    DEEP_PROFILING_PACK,
    FACET_FIELD_KEYS,
    FACET_PACK,
    RESONANCE_FIELD_KEYS,
    RESONANCE_PACK,
    load_deep_profiling_pack,
)

__all__ = [
    "DEEP_PROFILING_PACK",
    "RESONANCE_PACK",
    "FACET_PACK",
    "RESONANCE_FIELD_KEYS",
    "FACET_FIELD_KEYS",
    "load_deep_profiling_pack",
]
