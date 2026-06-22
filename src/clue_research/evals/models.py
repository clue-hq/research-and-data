"""Gold-set fixture format + eval-result/metric shapes (M0.6 frame, M9.6 verification battery).

The gold set is the hand-verified ground truth a research run is scored against (substrate §6). M0.6
defined the *shapes* (aligned to `core/` `Claim`/`Entity`); M9.6 (ENG-156) extends them additively
with the *verification battery* shapes — negative-fixture kinds, the research mode a fixture
targets, the per-mechanism metric, and the regression record — keeping this module **core-only**
(the DB/LLM-backed behaviour lives in `clue_research.verification`, which may import `evals`).

The eval-result shape is the verification-health metric shape (Doc C §6): per-rubric scored/passed
counters whose ratio is a pass-rate, plus per-mechanism detected/expected counters whose ratio is a
recall (the negative fixtures each mechanism must catch).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_research.core import EntityId, EntityType, FieldKey, ResearchMode, SourceTier


class FixtureKind(StrEnum):
    """What a gold fixture exercises (M9.6). A ``POSITIVE`` is a correct fact the rubric battery
    scores; each ``NEGATIVE_*`` is a planted defect a *specific* verification mechanism must catch —
    its "documented expected catch" (M09 §M9.6 acceptance). Mirrored by the ``fixture_kind`` DB enum
    (parity-tested).

    * ``NEGATIVE_FABRICATION`` — a tier-4 synthesized value its span does not support (M9.3 judge).
    * ``NEGATIVE_SAMENAME`` — a contact claim on a name-only / look-alike match (M9.4 binding).
    * ``NEGATIVE_STALE`` — a fact past its field TTL (M9.5 freshness).
    * ``NEGATIVE_UNSUPPORTED`` — a value not entailed by its cited evidence span (M9.3 judge).
    """

    POSITIVE = "positive"
    NEGATIVE_FABRICATION = "negative_fabrication"
    NEGATIVE_SAMENAME = "negative_samename"
    NEGATIVE_STALE = "negative_stale"
    NEGATIVE_UNSUPPORTED = "negative_unsupported"


_NEGATIVE_KINDS: frozenset[FixtureKind] = frozenset(
    {
        FixtureKind.NEGATIVE_FABRICATION,
        FixtureKind.NEGATIVE_SAMENAME,
        FixtureKind.NEGATIVE_STALE,
        FixtureKind.NEGATIVE_UNSUPPORTED,
    }
)


class GoldClaim(BaseModel):
    """One expected fact: the value a correct run should produce for a field, plus the provenance
    bar it must clear (worst source tier; whether an evidence span is required). M9.6 adds the
    ``fixture_kind`` (positive vs which negative-mechanism trap), the research ``mode`` it targets,
    and the ``expected_source_url`` for citation-validity scoring."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    expected_value: JsonValue
    max_source_tier: SourceTier = 3  # the lowest-trust tier still acceptable for this field
    requires_evidence_span: bool = True
    # --- M9.6 verification-battery extensions (additive; default = an M0.6 positive fixture) ---
    fixture_kind: FixtureKind = FixtureKind.POSITIVE
    mode: ResearchMode | None = None  # the research mode (M1-M4) this fixture exercises
    expected_source_url: str | None = None  # the source a correct run should cite

    @property
    def is_negative(self) -> bool:
        """Whether this fixture is a planted defect a verification mechanism must catch."""
        return self.fixture_kind in _NEGATIVE_KINDS


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


class MechanismMetric(BaseModel):
    """Per-mechanism result over the negative fixtures (M9.6): how many planted defects the
    mechanism *caught* (``detected``) of those it should (``expected``) — the recall — plus how many
    positives it wrongly flagged (``false_positive``) for precision. The mechanism is one of the M9
    gates (``pre_spend_gate`` / ``corroboration`` / ``faithfulness`` / ``identity_binding`` /
    ``freshness``) and the metric is the regression-gated number the battery defends (substrate §6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mechanism: str
    detected: int = 0
    expected: int = 0
    false_positive: int = 0

    @property
    def recall(self) -> float:
        """Share of planted defects the mechanism caught (1.0 when there are none to catch)."""
        return self.detected / self.expected if self.expected else 1.0

    @property
    def precision(self) -> float:
        """Share of flags that were true defects (1.0 when nothing was flagged)."""
        flagged = self.detected + self.false_positive
        return self.detected / flagged if flagged else 1.0


class Regression(BaseModel):
    """One metric's movement vs a baseline (M9.6): a *drop* beyond ``tolerance`` is a regression the
    CI gate fails on. ``metric`` is a rubric name (a pass-rate) or a mechanism name (a recall)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    baseline: float
    current: float
    tolerance: float = 0.0

    @property
    def delta(self) -> float:
        return self.current - self.baseline

    @property
    def regressed(self) -> bool:
        """A drop strictly beyond tolerance (an improvement or a within-tolerance move is fine)."""
        return (self.baseline - self.current) > self.tolerance


class EvalReport(BaseModel):
    """The result of one harness run: per-rubric scores + per-mechanism metrics + any regressions.

    M0.6 shipped ``rubric_scores`` (the rubric battery + faithfulness judge); M9.6 adds
    ``mechanism_metrics`` (the per-gate recall over negative fixtures), ``regressions`` (the
    regression-on-swap verdict vs a baseline), and ``config_snapshot`` (the judge model / prompt /
    thresholds / resolver set the run scored — recorded so a regression traces to the exact swap).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gold_set: str
    judge: str
    rubric_scores: tuple[RubricScore, ...] = ()
    mechanism_metrics: tuple[MechanismMetric, ...] = ()
    regressions: tuple[Regression, ...] = ()
    config_snapshot: dict[str, JsonValue] = {}

    def by_rubric(self) -> dict[str, RubricScore]:
        return {score.rubric: score for score in self.rubric_scores}

    def by_mechanism(self) -> dict[str, MechanismMetric]:
        return {metric.mechanism: metric for metric in self.mechanism_metrics}

    def metrics(self) -> dict[str, float]:
        """Per-rubric pass-rate — the verification-health-shaped metric (Doc C §6)."""
        return {score.rubric: score.pass_rate for score in self.rubric_scores}

    def mechanism_recalls(self) -> dict[str, float]:
        """Per-mechanism recall over the negative fixtures (Doc C §6 verification health)."""
        return {metric.mechanism: metric.recall for metric in self.mechanism_metrics}

    def scoreboard(self) -> dict[str, float]:
        """The full regression surface: every rubric pass-rate AND mechanism recall, keyed so a
        ``check_regressions`` pass compares the whole battery (a mechanism regressing must fail the
        gate just as a rubric regressing does). Mechanism keys are namespaced ``mechanism:<name>``
        so a rubric and a mechanism that share a name (``faithfulness`` is both a rubric and a gate)
        never collide and mask each other's regression."""
        board = self.metrics()
        for mechanism, recall in self.mechanism_recalls().items():
            board[f"mechanism:{mechanism}"] = recall
        return board

    @property
    def has_regression(self) -> bool:
        return any(reg.regressed for reg in self.regressions)

    def delta(self, baseline: EvalReport) -> dict[str, float]:
        """Per-metric change vs a baseline report — the regression-on-swap signal (rubrics +
        mechanisms)."""
        current, prior = self.scoreboard(), baseline.scoreboard()
        return {key: current.get(key, 0.0) - prior.get(key, 0.0) for key in sorted(current | prior)}

    def summary(self) -> str:
        scores = ", ".join(f"{s.rubric}={s.pass_rate:.2f}" for s in self.rubric_scores)
        mechs = ", ".join(f"{m.mechanism}={m.recall:.2f}" for m in self.mechanism_metrics)
        tail = f" | {mechs}" if mechs else ""
        flag = " REGRESSED" if self.has_regression else ""
        return f"eval[{self.gold_set} judge={self.judge}] {scores}{tail}{flag}"
