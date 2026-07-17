"""Tests for the M3.4 scoring-rubric model + pure score function (ENG-121).

One test per acceptance criterion. The scoring *math* is exercised DB-free with hand-built
``CurrentValue`` fixtures (fast, always run); the seam tests (validate against a compiled field
plan, the rubric-as-ICP-spec-slot versioning, and ``score_entity`` over the live merge read) use
the migrated-DB harness and skip without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from clue_core import (
    ClaimId,
    CurrentValue,
    EntityId,
    ExtractionMethod,
    FieldDef,
    FreshnessState,
    ICPCreatedFrom,
    ICPSpec,
    PassKind,
    ResearchMode,
    Score,
    WinningProvenance,
    account_claim,
    new_claim_id,
    new_entity_id,
    new_run_id,
)
from clue_research.claimstore import ALL_TENANTS, insert_claim, register_field
from clue_research.icp import (
    Contribution,
    ContributionFlag,
    FieldPlan,
    FieldPlanEntry,
    RubricEntry,
    RubricValidationError,
    ScoreDimension,
    ScoringRubric,
    ScoringTransform,
    SubRubric,
    TierBand,
    TierCutoffs,
    assign_tier,
    compile_field_plan,
    create_icp_spec,
    get_active_rubric,
    get_rubric_version,
    reweighted,
    rubric_from_slot,
    rubric_to_slot,
    score,
    score_entity,
    validate_rubric,
)

from .conftest import rollback_conn, run_async

_COLLECTED = datetime(2026, 1, 1, tzinfo=UTC)


def _cv(
    field_key: str,
    value_json: object,
    *,
    claim_id: ClaimId | None = None,
    confidence: float = 0.9,
    freshness: FreshnessState = FreshnessState.FRESH,
    source_tier: int = 1,
    entity_id: EntityId | None = None,
) -> CurrentValue:
    """Build a CurrentValue fixture (the merge result the rubric reads)."""
    return CurrentValue(
        entity_id=entity_id or new_entity_id(),
        field_key=field_key,
        value_json=value_json,
        provenance=WinningProvenance(
            claim_id=claim_id or new_claim_id(),
            source_tier=source_tier,
            confidence=confidence,
            collected_at=_COLLECTED,
        ),
        freshness_state=freshness,
    )


def _fit_intent_rubric() -> ScoringRubric:
    """A small rubric: Fit over two firmographic fields, Intent over two scoring proxies."""
    return ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(
                    field_key="core.employee_count",
                    weight=2.0,
                    transform=ScoringTransform.LINEAR,
                    params={"lo": 0, "hi": 1000},
                ),
                RubricEntry(
                    field_key="core.primary_tech_stack",
                    weight=1.0,
                    transform=ScoringTransform.CATEGORICAL,
                    params={"weights": {"python": 1.0, "java": 0.5}},
                ),
            )
        ),
        intent=SubRubric(
            entries=(
                RubricEntry(
                    field_key="account.recent_funding",
                    weight=1.0,
                    transform=ScoringTransform.BOOLEAN,
                ),
                RubricEntry(
                    field_key="account.job_openings_delta",
                    weight=3.0,
                    transform=ScoringTransform.THRESHOLD,
                    params={"threshold": 10},
                ),
            )
        ),
        tier_cutoffs=TierCutoffs(
            bands=(
                TierBand(tier="high", min_fit=0.6, min_intent=0.6),
                TierBand(tier="medium", min_fit=0.3, min_intent=0.0),
            ),
            fallback_tier="low",
        ),
    )


# --- AC1: Fit and Intent are separate, never collapsed ----------------------
def test_fit_and_intent_are_distinct_scores() -> None:
    rubric = _fit_intent_rubric()
    entity = new_entity_id()
    values = {
        "core.employee_count": _cv("core.employee_count", 500),  # linear 0.5
        "core.primary_tech_stack": _cv("core.primary_tech_stack", "python"),  # categorical 1.0
        "account.recent_funding": _cv("account.recent_funding", {"amount_usd": 1}),  # boolean 1.0
        "account.job_openings_delta": _cv("account.job_openings_delta", 40),  # threshold 1.0
    }
    result = score(rubric, values, entity_id=entity)
    # Fit = (2*0.5 + 1*1.0) / 3 = 0.6666...; Intent = (1*1.0 + 3*1.0) / 4 = 1.0 — distinct values.
    assert result.fit_score == pytest.approx(2.0 / 3.0)
    assert result.intent_score == pytest.approx(1.0)
    assert result.fit_score != result.intent_score
    # There is no single collapsed "overall" attribute on the result.
    assert not hasattr(result, "overall_score")
    assert {c.dimension for c in result.fit_contributions} == {ScoreDimension.FIT}
    assert {c.dimension for c in result.intent_contributions} == {ScoreDimension.INTENT}


# --- AC2: contributions enumerate (field_key, claim_id, value, weight, contribution) -------
def test_contributions_are_fully_decomposed_and_evidence_linked() -> None:
    rubric = _fit_intent_rubric()
    cids = {
        "core.employee_count": new_claim_id(),
        "core.primary_tech_stack": new_claim_id(),
        "account.recent_funding": new_claim_id(),
        "account.job_openings_delta": new_claim_id(),
    }
    values = {
        "core.employee_count": _cv(
            "core.employee_count", 1000, claim_id=cids["core.employee_count"]
        ),
        "core.primary_tech_stack": _cv(
            "core.primary_tech_stack", "java", claim_id=cids["core.primary_tech_stack"]
        ),
        "account.recent_funding": _cv(
            "account.recent_funding", {"amount_usd": 5}, claim_id=cids["account.recent_funding"]
        ),
        "account.job_openings_delta": _cv(
            "account.job_openings_delta", 40, claim_id=cids["account.job_openings_delta"]
        ),
    }
    result = score(rubric, values, entity_id=new_entity_id())
    assert len(result.contributions) == 4
    for c in result.contributions:
        assert isinstance(c, Contribution)
        # the explainability tuple ENG-121 mandates is all present
        assert c.field_key
        assert c.value_json is not None
        assert c.weight >= 0.0
        assert c.contribution == pytest.approx(c.factor * c.weight)
        # every nonzero contribution links a real claim_id
        if c.contribution > 0:
            assert c.claim_id == cids[c.field_key]
            assert c.flag is ContributionFlag.OK
    # employee_count=1000 -> linear (1000-0)/1000 = 1.0; tech=java -> 0.5
    fit = {c.field_key: c for c in result.fit_contributions}
    assert fit["core.employee_count"].factor == pytest.approx(1.0)
    assert fit["core.primary_tech_stack"].factor == pytest.approx(0.5)


# --- AC7: reproducibility (pure) -------------------------------------------
def test_score_is_pure_and_deterministic() -> None:
    rubric = _fit_intent_rubric()
    entity = new_entity_id()
    values = {
        "core.employee_count": _cv("core.employee_count", 250, claim_id=ClaimId(new_claim_id())),
        "account.job_openings_delta": _cv(
            "account.job_openings_delta", 12, claim_id=ClaimId(new_claim_id())
        ),
    }
    first = score(rubric, values, entity_id=entity)
    second = score(rubric, values, entity_id=entity)
    assert first == second  # identical scores AND identical contribution provenance


# --- AC3: missing / stale / low-confidence contribute per the rule, flagged --
def test_missing_value_contributes_zero_and_is_flagged() -> None:
    rubric = _fit_intent_rubric()
    # supply only one of the four fields; the rest are MISSING
    values = {"core.employee_count": _cv("core.employee_count", 1000)}
    result = score(rubric, values, entity_id=new_entity_id())
    by_key = {c.field_key: c for c in result.contributions}
    missing = by_key["account.job_openings_delta"]
    assert missing.flag is ContributionFlag.MISSING
    assert missing.contribution == 0.0
    assert missing.claim_id is None and missing.value_json is None
    # the missing fields still drag the normalized score down (divided by total weight)
    assert result.intent_score == 0.0  # both intent inputs missing
    assert result.fit_score == pytest.approx(2.0 / 3.0)  # only employee_count (w=2) of 3 present


def test_stale_value_is_discounted_and_flagged() -> None:
    rubric = ScoringRubric(
        intent=SubRubric(
            entries=(
                RubricEntry(field_key="account.recent_funding", transform=ScoringTransform.BOOLEAN),
            )
        )
    )
    stale = {
        "account.recent_funding": _cv(
            "account.recent_funding", {"amount_usd": 9}, freshness=FreshnessState.STALE
        )
    }
    result = score(rubric, stale, entity_id=new_entity_id())
    (c,) = result.contributions
    assert c.flag is ContributionFlag.STALE
    assert c.contribution == 0.0
    assert c.claim_id is not None  # the stale claim_id is surfaced, not dropped
    assert result.intent_score == 0.0
    # discount_stale=False makes the same stale value count
    counted = score(
        rubric.model_copy(update={"discount_stale": False}), stale, entity_id=new_entity_id()
    )
    assert counted.contributions[0].flag is ContributionFlag.OK
    assert counted.intent_score == pytest.approx(1.0)


def test_low_confidence_value_is_flagged_zero() -> None:
    rubric = ScoringRubric(
        min_confidence=0.5,
        fit=SubRubric(
            entries=(
                RubricEntry(field_key="core.employee_count", transform=ScoringTransform.BOOLEAN),
            )
        ),
    )
    values = {"core.employee_count": _cv("core.employee_count", 10, confidence=0.2)}
    result = score(rubric, values, entity_id=new_entity_id())
    (c,) = result.contributions
    assert c.flag is ContributionFlag.LOW_CONFIDENCE
    assert c.contribution == 0.0


@pytest.mark.parametrize(
    ("confidence", "expected_flag"),
    [
        (0.5, ContributionFlag.OK),  # == floor is allowed (strict-less-than gates)
        (0.49, ContributionFlag.LOW_CONFIDENCE),  # just below -> flagged
    ],
)
def test_min_confidence_boundary_is_strict_less_than(
    confidence: float, expected_flag: ContributionFlag
) -> None:
    rubric = ScoringRubric(
        min_confidence=0.5,
        fit=SubRubric(
            entries=(
                RubricEntry(field_key="core.employee_count", transform=ScoringTransform.BOOLEAN),
            )
        ),
    )
    values = {"core.employee_count": _cv("core.employee_count", 10, confidence=confidence)}
    (c,) = score(rubric, values, entity_id=new_entity_id()).contributions
    assert c.flag is expected_flag


def test_flag_precedence_stale_beats_low_confidence_and_missing_beats_all() -> None:
    """The _score_entry if/elif chain: MISSING first, then STALE, then LOW_CONFIDENCE."""
    rubric = ScoringRubric(
        min_confidence=0.9,
        fit=SubRubric(
            entries=(
                RubricEntry(field_key="core.employee_count", transform=ScoringTransform.BOOLEAN),
            )
        ),
    )
    # stale AND low-confidence -> STALE wins (stale is checked first)
    both = {
        "core.employee_count": _cv(
            "core.employee_count", 1, confidence=0.1, freshness=FreshnessState.STALE
        )
    }
    (c,) = score(rubric, both, entity_id=new_entity_id()).contributions
    assert c.flag is ContributionFlag.STALE
    # with stale discounting off, the same value then surfaces as LOW_CONFIDENCE
    (c2,) = score(
        rubric.model_copy(update={"discount_stale": False}), both, entity_id=new_entity_id()
    ).contributions
    assert c2.flag is ContributionFlag.LOW_CONFIDENCE
    # a missing field beats both flags
    (c3,) = score(rubric, {}, entity_id=new_entity_id()).contributions
    assert c3.flag is ContributionFlag.MISSING


def test_non_finite_weight_is_rejected_and_non_finite_value_does_not_raise() -> None:
    """Hardening: an inf/nan weight is rejected at construction (else normalization yields NaN);
    a non-finite current value degrades to a 0.0 factor and score() stays total (never raises)."""
    with pytest.raises(ValueError):
        RubricEntry(field_key="core.employee_count", weight=float("inf"))
    with pytest.raises(ValueError):
        RubricEntry(field_key="core.employee_count", weight=float("nan"))
    # a NaN-valued current_value must not raise; it contributes 0.0, flagged OK (it is present)
    rubric = ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(field_key="core.employee_count", transform=ScoringTransform.IDENTITY),
            )
        )
    )
    result = score(
        rubric,
        {"core.employee_count": _cv("core.employee_count", float("nan"))},
        entity_id=new_entity_id(),
    )
    assert result.fit_score == 0.0
    assert result.contributions[0].factor == 0.0


# --- transforms (pure math) -------------------------------------------------
@pytest.mark.parametrize(
    ("transform", "params", "value", "expected"),
    [
        (ScoringTransform.BOOLEAN, {}, {"x": 1}, 1.0),
        (ScoringTransform.BOOLEAN, {}, 0, 0.0),
        (ScoringTransform.THRESHOLD, {"threshold": 10}, 10, 1.0),
        (ScoringTransform.THRESHOLD, {"threshold": 10}, 9, 0.0),
        (ScoringTransform.THRESHOLD, {"threshold": 10}, "oops", 0.0),
        (ScoringTransform.LINEAR, {"lo": 0, "hi": 100}, 50, 0.5),
        (ScoringTransform.LINEAR, {"lo": 0, "hi": 100}, 250, 1.0),  # clamped
        (ScoringTransform.LINEAR, {"lo": 0, "hi": 100}, -5, 0.0),  # clamped
        (ScoringTransform.LINEAR, {"lo": 5, "hi": 5}, 5, 0.0),  # degenerate range
        (ScoringTransform.CATEGORICAL, {"weights": {"a": 0.7}}, "a", 0.7),
        (ScoringTransform.CATEGORICAL, {"weights": {"a": 0.7}}, "b", 0.0),
        (ScoringTransform.CATEGORICAL, {"weights": {"1": 0.8}}, 1, 0.8),  # str() coercion of value
        (ScoringTransform.CATEGORICAL, {"weights": {"a": 5.0}}, "a", 1.0),  # factor clamped
        (ScoringTransform.CATEGORICAL, {}, "a", 0.0),  # missing/non-Mapping weights
        (ScoringTransform.IDENTITY, {}, 0.42, 0.42),
        (ScoringTransform.IDENTITY, {}, 2.0, 1.0),  # clamped
        (ScoringTransform.IDENTITY, {}, "nope", 0.0),
        # bool is NOT a number for numeric transforms (must use BOOLEAN) — deliberate, regressable
        (ScoringTransform.THRESHOLD, {"threshold": 0}, True, 0.0),
        (ScoringTransform.IDENTITY, {}, True, 0.0),
        # non-finite value/param degrades to 0.0 (never a NaN factor) — empty-is-correct, no raise
        (ScoringTransform.IDENTITY, {}, float("nan"), 0.0),
        (ScoringTransform.IDENTITY, {}, float("inf"), 0.0),
        (ScoringTransform.LINEAR, {"lo": 0, "hi": float("inf")}, 50, 0.0),
        (ScoringTransform.THRESHOLD, {"threshold": float("nan")}, 10, 0.0),
    ],
)
def test_transform_factor(
    transform: ScoringTransform, params: dict[str, object], value: object, expected: float
) -> None:
    rubric = ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(field_key="core.employee_count", transform=transform, params=params),
            ),
            normalize=False,
        )
    )
    result = score(
        rubric,
        {"core.employee_count": _cv("core.employee_count", value)},
        entity_id=new_entity_id(),
    )
    assert result.contributions[0].factor == pytest.approx(expected)


def test_normalize_false_returns_raw_weighted_sum() -> None:
    rubric = ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(
                    field_key="core.employee_count", weight=2.0, transform=ScoringTransform.IDENTITY
                ),
            ),
            normalize=False,
        )
    )
    result = score(
        rubric, {"core.employee_count": _cv("core.employee_count", 0.5)}, entity_id=new_entity_id()
    )
    assert result.fit_score == pytest.approx(1.0)  # 2.0 * 0.5, not divided by total weight


# --- projection onto the M0.2 Score the handoff embeds (M12) ----------------
def test_projects_onto_core_score_with_relative_weights() -> None:
    rubric = _fit_intent_rubric()
    cid = new_claim_id()
    values = {
        "core.employee_count": _cv("core.employee_count", 1000, claim_id=cid),
        "core.primary_tech_stack": _cv("core.primary_tech_stack", "python"),
    }
    result = score(rubric, values, entity_id=new_entity_id())
    fit_score = result.as_fit_score()
    assert isinstance(fit_score, Score)
    assert 0.0 <= fit_score.value <= 1.0
    # relative weights sum to ~1 across the two fit components
    assert sum(c.weight for c in fit_score.components) == pytest.approx(1.0)
    emp = next(c for c in fit_score.components if c.name == "core.employee_count")
    assert emp.evidence_claim_ids == (cid,)  # evidence carried through


def test_projection_carries_intent_and_zeroed_flags() -> None:
    """as_intent_score projects too; a STALE input surfaces its claim_id at value 0.0, a MISSING one
    carries no evidence — the explainability invariant survives the projection (M12 handoff)."""
    stale_cid = new_claim_id()
    rubric = ScoringRubric(
        intent=SubRubric(
            entries=(
                RubricEntry(field_key="account.recent_funding", transform=ScoringTransform.BOOLEAN),
                RubricEntry(
                    field_key="account.job_openings_delta", transform=ScoringTransform.BOOLEAN
                ),
            )
        )
    )
    values = {
        "account.recent_funding": _cv(
            "account.recent_funding",
            {"amount_usd": 9},
            claim_id=stale_cid,
            freshness=FreshnessState.STALE,
        ),
        # job_openings_delta absent -> MISSING
    }
    intent_score = score(rubric, values, entity_id=new_entity_id()).as_intent_score()
    assert isinstance(intent_score, Score)
    funding = next(c for c in intent_score.components if c.name == "account.recent_funding")
    assert funding.value == 0.0 and funding.evidence_claim_ids == (stale_cid,)  # surfaced, zeroed
    delta = next(c for c in intent_score.components if c.name == "account.job_openings_delta")
    assert delta.evidence_claim_ids == ()  # missing -> no evidence


def test_projection_with_zero_total_weight_does_not_divide_by_zero() -> None:
    """All contributions zeroed (here: a single all-missing entry) -> components get weight 0.0, not
    a ZeroDivisionError, and the score is 0.0."""
    rubric = ScoringRubric(
        fit=SubRubric(entries=(RubricEntry(field_key="core.employee_count", weight=0.0),))
    )
    result = score(rubric, {}, entity_id=new_entity_id())  # missing -> no contribution
    fit_score = result.as_fit_score()
    assert fit_score.value == 0.0
    assert all(c.weight == 0.0 for c in fit_score.components)


# --- AC6: default tier cutoffs, adjustable without mutating the rubric -------
def test_assign_tier_uses_cutoffs_and_is_adjustable() -> None:
    rubric = _fit_intent_rubric()
    cutoffs = rubric.tier_cutoffs
    assert assign_tier(cutoffs, 0.7, 0.7) == "high"
    assert assign_tier(cutoffs, 0.4, 0.1) == "medium"
    assert assign_tier(cutoffs, 0.1, 0.1) == "low"  # fallback
    # the human adjusts cutoffs at the checkpoint WITHOUT mutating the rubric
    stricter = TierCutoffs(
        bands=(TierBand(tier="high", min_fit=0.95, min_intent=0.95),), fallback_tier="low"
    )
    assert assign_tier(stricter, 0.7, 0.7) == "low"
    assert rubric.tier_cutoffs == cutoffs  # rubric untouched


# --- slot serialization round-trip -----------------------------------------
def test_rubric_slot_roundtrip() -> None:
    rubric = _fit_intent_rubric()
    slot = rubric_to_slot(rubric)
    assert isinstance(slot, dict)
    assert ScoringRubric.model_validate(slot) == rubric
    assert rubric_from_slot(slot) == rubric
    assert rubric_from_slot({}) is None  # empty slot is a valid "no rubric yet" state
    # AC7 through serialization: the round-tripped rubric re-scores byte-identically (this is what
    # makes a campaign pinned to a stored ICP-spec version reproducible) — no DB required.
    entity = new_entity_id()
    values = {
        "core.employee_count": _cv("core.employee_count", 500, claim_id=new_claim_id()),
        "account.job_openings_delta": _cv(
            "account.job_openings_delta", 40, claim_id=new_claim_id()
        ),
    }
    assert score(rubric_from_slot(slot), values, entity_id=entity) == score(
        rubric, values, entity_id=entity
    )


# --- AC4 (DB-free): validate against an in-memory field plan -----------------
def _plan(*fields: FieldDef) -> FieldPlan:
    """Build a FieldPlan in-memory (mirrors compile_field_plan's scoring/deep partition) so the
    validate_rubric acceptance criterion is exercised in the always-run gate, not only with a DB."""
    entries = tuple(FieldPlanEntry(field=f) for f in fields)
    return FieldPlan(
        client_id="acme",
        icp_key="default",
        icp_version=1,
        fields=entries,
        scoring_fields=tuple(e for e in entries if e.field.pass_kind is PassKind.SCORING),
        deep_fields=tuple(e for e in entries if e.field.pass_kind is PassKind.DEEP),
    )


def test_validate_rubric_db_free() -> None:
    plan = _plan(
        FieldDef(field_key="core.employee_count", value_type="int", pass_kind=PassKind.SCORING),
        FieldDef(
            field_key="account.job_openings_delta",
            value_type="number",
            pass_kind=PassKind.SCORING,
            signal_class="intent",
        ),
        FieldDef(
            field_key="account.why_in_market",
            value_type="str",
            pass_kind=PassKind.DEEP,
            signal_class="intent",
        ),
    )
    # valid: fit over a scoring field, intent over the scoring proxy
    validate_rubric(
        ScoringRubric(
            fit=SubRubric(entries=(RubricEntry(field_key="core.employee_count"),)),
            intent=SubRubric(entries=(RubricEntry(field_key="account.job_openings_delta"),)),
        ),
        plan,
    )
    # AC4: a deep-tagged field is not a valid Pass-A Intent input
    with pytest.raises(RubricValidationError) as e1:
        validate_rubric(
            ScoringRubric(
                intent=SubRubric(entries=(RubricEntry(field_key="account.why_in_market"),))
            ),
            plan,
        )
    assert "account.why_in_market" in str(e1.value)
    assert any("deep-pass" in d for d in e1.value.diagnostics)
    # a field absent from the plan is named
    with pytest.raises(RubricValidationError) as e2:
        validate_rubric(
            ScoringRubric(fit=SubRubric(entries=(RubricEntry(field_key="account.ghost_metric"),))),
            plan,
        )
    assert "account.ghost_metric" in str(e2.value)


# --- disposition-feedback hook (model only) --------------------------------
def test_reweighted_bumps_version_and_records_basis() -> None:
    rubric = _fit_intent_rubric()
    new = reweighted(
        rubric,
        fit_weights={"core.employee_count": 5.0},
        feedback_basis={"accepted": 12, "rejected": 3},
    )
    assert new.version == rubric.version + 1
    assert next(e for e in new.fit.entries if e.field_key == "core.employee_count").weight == 5.0
    assert new.feedback_basis == {"accepted": 12, "rejected": 3}
    # original is untouched (pure) and unlisted entries keep their weight
    assert rubric.version == 1
    orig = {e.field_key: e.weight for e in rubric.fit.entries}
    after = {e.field_key: e.weight for e in new.fit.entries}
    assert orig["core.employee_count"] == 2.0  # original untouched
    assert after["core.primary_tech_stack"] == 1.0  # unlisted entry keeps its weight


# =========================== DB-backed seam tests ===========================
pytestmark_db = pytest.mark.usefixtures("require_icp_db")


def _icp(**overrides: object) -> ICPSpec:
    base: dict[str, object] = {
        "client_id": "acme",
        "icp_key": "default",
        "created_from": ICPCreatedFrom.SYNTHESIS,
    }
    base.update(overrides)
    return ICPSpec(**base)


@pytestmark_db
def test_validate_rubric_rejects_deep_intent_and_unknown_field() -> None:
    """AC4: Intent inputs must be scoring-tagged proxies; a deep-tagged field is not a Pass-A input.
    Also rejects a field absent from the plan — naming every offender, no silent drop."""

    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            # a deep narrative field sharing the "intent" signal class with a scoring proxy
            await register_field(
                conn,
                FieldDef(
                    field_key="account.job_openings_delta",
                    value_type="number",
                    tier_plan=("linkedin_jobs",),
                    pass_kind=PassKind.SCORING,
                    signal_class="intent",
                ),
            )
            await register_field(
                conn,
                FieldDef(
                    field_key="account.why_in_market",
                    value_type="str",
                    tier_plan=("exa",),
                    pass_kind=PassKind.DEEP,
                    signal_class="intent",
                ),
            )
            plan = await compile_field_plan(
                conn,
                _icp(
                    field_keys=(
                        "core.employee_count",
                        "account.job_openings_delta",
                        "account.why_in_market",
                    )
                ),
            )
            # a valid rubric: fit over a scoring field, intent over the scoring proxy
            ok = ScoringRubric(
                fit=SubRubric(entries=(RubricEntry(field_key="core.employee_count"),)),
                intent=SubRubric(entries=(RubricEntry(field_key="account.job_openings_delta"),)),
            )
            validate_rubric(ok, plan)  # does not raise

            # intent on the DEEP narrative field -> rejected
            deep_intent = ScoringRubric(
                intent=SubRubric(entries=(RubricEntry(field_key="account.why_in_market"),))
            )
            with pytest.raises(RubricValidationError) as exc1:
                validate_rubric(deep_intent, plan)
            assert "account.why_in_market" in str(exc1.value)
            assert any("deep-pass" in d for d in exc1.value.diagnostics)

            # a field not in the plan at all -> rejected
            ghost = ScoringRubric(
                fit=SubRubric(entries=(RubricEntry(field_key="account.ghost_metric"),))
            )
            with pytest.raises(RubricValidationError) as exc2:
                validate_rubric(ghost, plan)
            assert "account.ghost_metric" in str(exc2.value)

    run_async(_run())


@pytestmark_db
def test_rubric_is_a_versioned_icp_spec_slot() -> None:
    """AC5: editing weights appends a new ICP-spec version; a pinned prior version re-reads (and so
    re-scores) the original rubric identically."""

    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            rubric_v1 = ScoringRubric(
                fit=SubRubric(entries=(RubricEntry(field_key="core.employee_count", weight=1.0),)),
                version=1,
            )
            await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.SYNTHESIS,
                field_keys=("core.employee_count",),
                scoring_rubric=rubric_to_slot(rubric_v1),
                activate=True,
            )
            # edit weights -> append a new ICP-spec version carrying the new rubric
            rubric_v2 = reweighted(rubric_v1, fit_weights={"core.employee_count": 9.0})
            await create_icp_spec(
                conn,
                client_id="acme",
                icp_key="default",
                created_from=ICPCreatedFrom.CLIENT_EDIT,
                field_keys=("core.employee_count",),
                scoring_rubric=rubric_to_slot(rubric_v2),
                activate=True,
            )
            active = await get_active_rubric(conn, "acme", "default")
            assert active is not None and active.version == 2
            assert active.fit.entries[0].weight == 9.0
            # the pinned prior version is unchanged (append-only)
            pinned = await get_rubric_version(conn, "acme", "default", 1)
            assert pinned == rubric_v1
            assert pinned is not None and pinned.fit.entries[0].weight == 1.0

    run_async(_run())


@pytestmark_db
def test_score_entity_end_to_end_and_reproducible() -> None:
    """AC2 + AC7 over the live merge read: score_entity fetches current_value, links real claim_ids,
    flags the missing field, and re-scores a pinned rubric version identically."""

    async def _run() -> None:
        async with rollback_conn(seed_core=True) as conn:
            entity = new_entity_id()
            run_id = new_run_id()
            emp_claim = account_claim(
                entity_id=entity,
                field_key="core.employee_count",
                value_json=800,
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.95,
                run_id=run_id,
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://api.example.com/acme",
            )
            fund_claim = account_claim(
                entity_id=entity,
                field_key="account.recent_funding",
                value_json={"amount_usd": 5_000_000},
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.9,
                run_id=run_id,
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://api.example.com/acme/funding",
            )
            emp_id = await insert_claim(conn, emp_claim)
            fund_id = await insert_claim(conn, fund_claim)

            rubric = ScoringRubric(
                fit=SubRubric(
                    entries=(
                        RubricEntry(
                            field_key="core.employee_count",
                            transform=ScoringTransform.LINEAR,
                            params={"lo": 0, "hi": 1000},
                        ),
                    )
                ),
                intent=SubRubric(
                    entries=(
                        RubricEntry(
                            field_key="account.recent_funding",
                            transform=ScoringTransform.BOOLEAN,
                        ),
                        # no claim for this field -> MISSING
                        RubricEntry(field_key="core.primary_tech_stack"),
                    )
                ),
            )
            result = await score_entity(conn, rubric, entity, scope=ALL_TENANTS)
            by_key = {c.field_key: c for c in result.contributions}
            assert by_key["core.employee_count"].claim_id == emp_id
            assert by_key["core.employee_count"].factor == pytest.approx(0.8)
            assert by_key["account.recent_funding"].claim_id == fund_id
            assert by_key["core.primary_tech_stack"].flag is ContributionFlag.MISSING
            assert result.fit_score == pytest.approx(0.8)
            # intent = (1*1.0 + 1*0.0) / 2 = 0.5  (funding present, tech_stack missing)
            assert result.intent_score == pytest.approx(0.5)

            again = await score_entity(conn, rubric, entity, scope=ALL_TENANTS)
            assert again == result  # reproducible: same scores + same provenance

    run_async(_run())
