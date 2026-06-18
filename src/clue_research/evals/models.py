"""Gold-set fixture format + eval-result/metric shapes (M0.6).

The gold set is the hand-verified ground truth a research run is scored against (substrate §6). M0.6
defines the *shapes* (aligned to `core/` `Claim`/`Entity`); the hand-verified content lands with
M9/M11. The eval-result shape is the verification-health metric shape (Doc C §6): per-rubric
scored/passed counters whose ratio is a pass-rate.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_research.core import EntityId, EntityType, FieldKey, SourceTier


class GoldClaim(BaseModel):
    """One expected fact: the value a correct run should produce for a field, plus the
    provenance bar it must clear (worst source tier; whether an evidence span is required)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    expected_value: JsonValue
    max_source_tier: SourceTier = 3  # the lowest-trust tier still acceptable for this field
    requires_evidence_span: bool = True


class GoldEntity(BaseModel):
    """A hand-verified entity and its expected claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    entity_type: EntityType
    claims: tuple[GoldClaim, ...] = ()


class GoldSet(BaseModel):
    """A named collection of hand-verified entities (the eval ground truth)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    entities: tuple[GoldEntity, ...] = ()


class RubricScore(BaseModel):
    """Per-rubric result: items scored vs passed (the verification-health shape)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rubric: str
    scored: int = 0
    passed: int = 0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.scored if self.scored else 0.0


class EvalReport(BaseModel):
    """The result of one harness run: per-rubric scores + the metrics derived from them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gold_set: str
    judge: str
    rubric_scores: tuple[RubricScore, ...] = ()

    def by_rubric(self) -> dict[str, RubricScore]:
        return {score.rubric: score for score in self.rubric_scores}

    def metrics(self) -> dict[str, float]:
        """Per-rubric pass-rate — the verification-health-shaped metric (Doc C §6)."""
        return {score.rubric: score.pass_rate for score in self.rubric_scores}

    def delta(self, baseline: EvalReport) -> dict[str, float]:
        """Per-rubric pass-rate change vs a baseline report — the regression-on-swap signal."""
        current, prior = self.metrics(), baseline.metrics()
        return {key: current.get(key, 0.0) - prior.get(key, 0.0) for key in sorted(current | prior)}

    def summary(self) -> str:
        scores = ", ".join(f"{s.rubric}={s.pass_rate:.2f}" for s in self.rubric_scores)
        return f"eval[{self.gold_set} judge={self.judge}] {scores}"
