"""The rubric battery — pluggable scorers behind a seam (M0.6).

The standard rubrics from substrate §6: factual accuracy (does the value match the gold value?),
citation validity (is the required evidence present?), and source quality (is the source trustworthy
enough for this field?). Each is a :class:`Scorer`; the set is swappable, so a new rubric is a
registration, not a harness fork. Scorers are deterministic — faithfulness is the judge's job.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clue_core import Claim
from clue_research.evals.models import GoldClaim


@runtime_checkable
class Scorer(Protocol):
    """A single rubric: the produced claim matched to ``gold`` (``None`` if absent)."""

    name: str

    def passed(self, actual: Claim | None, gold: GoldClaim) -> bool: ...


class FactualAccuracyScorer:
    name = "factual_accuracy"

    def passed(self, actual: Claim | None, gold: GoldClaim) -> bool:
        return actual is not None and actual.value_json == gold.expected_value


class CitationValidityScorer:
    name = "citation_validity"

    def passed(self, actual: Claim | None, gold: GoldClaim) -> bool:
        if actual is None:
            return False
        return bool(actual.evidence_span) if gold.requires_evidence_span else True


class SourceQualityScorer:
    name = "source_quality"

    def passed(self, actual: Claim | None, gold: GoldClaim) -> bool:
        return actual is not None and actual.source_tier <= gold.max_source_tier


def default_scorers() -> tuple[Scorer, ...]:
    """The standard rubric battery (substrate §6)."""
    return (FactualAccuracyScorer(), CitationValidityScorer(), SourceQualityScorer())
