"""Value-equality primitives — canonical JSON + type-aware agreement (the substrate's one contract).

The single, shared answer to *"do two ``value_json`` payloads mean the same thing?"*. Two surfaces
need it and must never diverge:

* the **merge** conflict / distinctness check (``claimstore.merge`` — "two tier≤2 sources
  disagree");
* the **corroboration** grouping (``verification.corroboration`` — "N independent sources agree").

Each originally owned a copy: the merge used exact :func:`canonical_json`, while the corroborator
used a type-aware :class:`EqualityMode` (numeric tolerance / semantic overlap). For a
``numeric_tol`` / ``semantic`` field the two then disagreed — the merge raised a ``conflict`` on two
authoritative sources the corroborator considered *in agreement* (headcount 1000 vs 1024;
"Snowflake" vs "uses Snowflake"). That is the [M9.2×M1.2] backlog: the merge over-flagged.

Relocating both here makes the merge mode-aware and gives the M12/M13 conflict consumers one
equality contract. ``core`` is the consistent home (it sits alongside ``ReuseScope`` / ``PassKind``
/ ``FieldClass`` and imports nothing internal), so a value primitive belongs here, not in a worker.

:func:`values_agree` takes its tolerances as **explicit args** (never a ``CorroborationPolicy`` —
``core`` must not depend on a worker's policy type). The corroborator passes its policy's tolerances
and the merge passes ``MergePolicy``'s; both default to the constants here, and a no-DB drift guard
asserts the three stay aligned.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum

from pydantic import JsonValue

# Default equality tolerances — the single source both ``claimstore.MergePolicy`` and
# ``verification.CorroborationPolicy`` default from (DRY; a no-DB drift guard asserts alignment).
DEFAULT_NUMERIC_REL_TOLERANCE = 0.05
DEFAULT_NUMERIC_ABS_TOLERANCE = 0.0
DEFAULT_SEMANTIC_JACCARD_THRESHOLD = 0.5

# Tokeniser for semantic equality: lowercase alphanumeric runs ("uses Snowflake!" -> {uses, snow}).
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class EqualityMode(StrEnum):
    """How two ``value_json`` payloads are decided to *agree* — type-aware equality derived from the
    field's M1.3 type/validation. Mirrored by the ``field_definition.equality_mode`` DB enum
    (parity-tested).

    * ``EXACT`` — canonical-JSON equality (enums, ids, structured payloads): the safe default.
    * ``NUMERIC_TOL`` — two numbers agree within tolerance (headcount 1000 vs 1024 corroborate);
      non-numeric values fall back to exact.
    * ``SEMANTIC`` — normalized text overlap ("Snowflake" vs "uses Snowflake" corroborate;
      "Snowflake" vs "Databricks" conflict); non-string values fall back to exact.
    """

    EXACT = "exact"
    NUMERIC_TOL = "numeric_tol"
    SEMANTIC = "semantic"


def canonical_json(value: JsonValue) -> str:
    """A canonical string for value equality / distinctness (order-independent for objects).

    The one place exact ``value_json`` equality is decided in the substrate — the merge layer's
    conflict / distinctness check and the corroborator's exact-equality mode both call this, so
    "same value" means the same thing on both surfaces. (It is NOT
    :func:`core.serialize_value_json`, whose Pydantic dump does not sort object keys.)"""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _as_number(value: JsonValue) -> float | None:
    """The numeric value of a JSON number, or ``None`` (booleans are not numbers here)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _within_tolerance(a: float, b: float, *, rel_tolerance: float, abs_tolerance: float) -> bool:
    diff = abs(a - b)
    if diff <= abs_tolerance:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and diff <= rel_tolerance * scale


def _tokens(value: JsonValue) -> frozenset[str]:
    if not isinstance(value, str):
        return frozenset()
    return frozenset(_TOKEN_RE.findall(value.lower()))


def values_agree(
    a: JsonValue,
    b: JsonValue,
    *,
    mode: EqualityMode,
    numeric_rel_tolerance: float = DEFAULT_NUMERIC_REL_TOLERANCE,
    numeric_abs_tolerance: float = DEFAULT_NUMERIC_ABS_TOLERANCE,
    semantic_jaccard_threshold: float = DEFAULT_SEMANTIC_JACCARD_THRESHOLD,
) -> bool:
    """Whether two ``value_json`` payloads *agree* under ``mode`` (the substrate's equality).

    ``NUMERIC_TOL``: two numbers agree if ``|a-b| <= abs_tol`` or ``<= rel_tol * max(|a|,|b|)``;
    non-numeric values fall back to exact. ``SEMANTIC``: two strings agree on token-set containment
    or Jaccard ``>= threshold``; non-string values fall back to exact. ``EXACT``: canonical-JSON
    equality."""
    if mode is EqualityMode.NUMERIC_TOL:
        na, nb = _as_number(a), _as_number(b)
        if na is not None and nb is not None:
            return _within_tolerance(
                na, nb, rel_tolerance=numeric_rel_tolerance, abs_tolerance=numeric_abs_tolerance
            )
        return canonical_json(a) == canonical_json(b)  # non-numeric → exact fallback
    if mode is EqualityMode.SEMANTIC:
        if isinstance(a, str) and isinstance(b, str):
            ta, tb = _tokens(a), _tokens(b)
            if not ta or not tb:
                return canonical_json(a) == canonical_json(b)
            if ta <= tb or tb <= ta:  # containment: "snowflake" ⊆ "uses snowflake"
                return True
            inter = len(ta & tb)
            union = len(ta | tb)
            return union > 0 and inter / union >= semantic_jaccard_threshold
        return canonical_json(a) == canonical_json(b)  # non-text → exact fallback
    return canonical_json(a) == canonical_json(b)  # EXACT
