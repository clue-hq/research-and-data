"""Default claim-extraction strategies (M4.3).

``extract`` (text → typed :class:`~clue_research.core.ClaimDraft`s) is inherently field/source-
specific — an LLM-backed extractor (M8/M11) or a structured parser (M4.5) plugs into the
:class:`~clue_research.adapters.seams.ClaimExtractor` seam. M4.3 ships the seam plus the small,
deterministic helpers that prove the framework and serve simple sources: a callable wrapper (so a
plain function is a valid extractor) and a span helper that guarantees an ``evidence_span`` is an
exact slice of the normalized text (substrate §4 — grounded, never invented).
"""

from __future__ import annotations

from collections.abc import Callable

from clue_research.core import ClaimDraft, Entity, FieldDef, NormalizedText

# A plain extraction function (the duck-typed body of a ClaimExtractor).
ExtractFn = Callable[[NormalizedText, Entity, FieldDef], list[ClaimDraft]]


class CallableClaimExtractor:
    """Adapt a plain function into a :class:`~clue_research.adapters.seams.ClaimExtractor`.

    Lets a source supply its extraction logic as a closure (the common case for M4.5's structured
    field parsers and the framework's tests) without authoring a class per source.
    """

    def __init__(self, fn: ExtractFn) -> None:
        self._fn = fn

    def extract(
        self, normalized: NormalizedText, entity: Entity, field: FieldDef
    ) -> list[ClaimDraft]:
        return self._fn(normalized, entity, field)


def span_for(text: str, needle: str) -> str:
    """Return ``needle`` only if it is an exact substring of ``text`` — else raise.

    The guard an extractor uses to keep an ``evidence_span`` provably grounded in the normalized
    text (substrate §4): a value's span must be lifted *from* the source, never paraphrased.
    """
    if not needle or needle not in text:
        raise ValueError(f"evidence span {needle!r} is not a substring of the normalized text")
    return needle
