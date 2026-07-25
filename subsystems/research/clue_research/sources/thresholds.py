"""Per-field-class confidence thresholds — the waterfall's stop knob (M4.1, locked decision #1).

The canonical shape now lives in the config seam (:mod:`clue_config.schema`) so it is a
*layered, per-client/ICP, versioned* config surface like every other "policy as data" tunable
(conventions §2) — the M8 deep workers read it off the merged :class:`~clue_config.Config`
and pass it to :func:`clue_research.sources.resolve_field`. This module re-exports it so the
waterfall and its existing importers keep a stable ``clue_research.sources`` entry point; there is
exactly one definition.
"""

from __future__ import annotations

from clue_config import DEFAULT_CONFIDENCE_THRESHOLDS, ConfidenceThresholds

__all__ = ["ConfidenceThresholds", "DEFAULT_CONFIDENCE_THRESHOLDS"]
