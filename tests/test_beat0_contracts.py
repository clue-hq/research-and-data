"""Beat-0 contract-freeze smoke tests (M5–M9 parallelisation).

These guard the *shared seam* the four milestone branches fork against: the cross-milestone
protocols and value types added to ``core`` (``core.execution`` + ``core.verification``), the
campaign-phase enum, and the pure idempotency-key helpers. They assert the contracts are importable
from the ``core`` public surface, that the protocols are structurally checkable, that the phase
vocabulary has a single source of truth, and that key derivation is deterministic. Implementations
(``durable`` / ``verification``) and DB tables are built on the milestone branches; nothing here
needs a database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from clue_core import (
    AspectContext,
    AspectWorker,
    Binding,
    BudgetDecision,
    BudgetEngine,
    BudgetScope,
    BudgetVerdict,
    BurnDown,
    EntityType,
    Estimate,
    FaithfulnessJudge,
    Freshness,
    FreshnessState,
    IdempotencyScope,
    IdentityBinding,
    IdentityBindingGate,
    JudgeResult,
    JudgeVerdict,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    PhaseStatus,
    PreSpendDecision,
    PreSpendGate,
    PreSpendRequest,
    PreSpendVerdict,
    ProjectPhase,
    ReResearchCandidate,
    Staleness,
    TargetLock,
    WorkerResult,
    WorkerStatus,
    account_step_key,
    idempotency_key,
    new_claim_id,
    new_entity_id,
    new_project_run_id,
    new_run_id,
    phase_key,
)
from clue_obs.otel.spans import PROJECT_PHASES

_NOW = datetime(2026, 6, 20, tzinfo=UTC)


# --- the phase vocabulary has one source of truth ---------------------------


def test_project_phase_is_the_canonical_source_for_obs_phase_tokens() -> None:
    # obs.PROJECT_PHASES is derived from the enum: same tokens, same order, both directions.
    assert tuple(phase.value for phase in ProjectPhase) == PROJECT_PHASES
    assert ProjectPhase.TIER_CHECKPOINT.value == "tier_checkpoint"
    assert ProjectPhase.HANDOFF.value == "handoff"


def test_new_enums_carry_their_expected_members() -> None:
    assert {s.value for s in PhaseStatus} == {"completed", "paused", "failed"}
    assert {s.value for s in WorkerStatus} == {"ok", "partial", "failed", "budget_exceeded"}
    assert {s.value for s in PreSpendVerdict} == {"pass", "reject"}
    assert {s.value for s in JudgeVerdict} == {
        "supported",
        "partial",
        "unsupported",
        "contradicted",
    }
    assert {s.value for s in BudgetVerdict} == {"allow", "deny", "graceful_stop"}
    assert {s.value for s in BudgetScope} == {"account", "pass", "run"}
    assert {s.value for s in IdempotencyScope} == {"account_step", "campaign_phase"}


# --- the cross-milestone protocols are structurally checkable ---------------


def test_phase_handler_is_runtime_checkable() -> None:
    class _Handler:
        phase = ProjectPhase.DISCOVERY

        async def run(self, ctx: PhaseContext) -> PhaseResult:
            return PhaseResult(status=PhaseStatus.COMPLETED)

    assert isinstance(_Handler(), PhaseHandler)
    assert not isinstance(object(), PhaseHandler)


def test_aspect_worker_is_runtime_checkable() -> None:
    class _Worker:
        aspect = "firmographics"

        async def research(self, ctx: AspectContext) -> WorkerResult:
            return WorkerResult(aspect="firmographics", status=WorkerStatus.OK)

    assert isinstance(_Worker(), AspectWorker)
    assert not isinstance(object(), AspectWorker)


def test_verification_gate_protocols_are_runtime_checkable() -> None:
    # Presence-only structural checks (runtime_checkable); mypy checks the full signatures.
    for proto in (PreSpendGate, FaithfulnessJudge, IdentityBindingGate, Freshness, BudgetEngine):
        assert not isinstance(object(), proto)


# --- value types construct and are frozen -----------------------------------


def test_execution_value_types_construct() -> None:
    ctx = PhaseContext(
        project_run_id=new_project_run_id(),
        project_id="prj-test",
        brand_id="brd-test",
        phase=ProjectPhase.SCORING,
        workspace_id="acme",
        icp_key="default",
        icp_version=1,
    )
    assert ctx.phase is ProjectPhase.SCORING
    assert PhaseResult(status=PhaseStatus.PAUSED).cost_cents == Decimal(0)
    assert WorkerResult(aspect="hiring", status=WorkerStatus.BUDGET_EXCEEDED).claim_refs == ()
    AspectContext(
        entity_id=new_entity_id(),
        project_run_id=new_project_run_id(),
        run_id=new_run_id(),
        tier="tier_2",
        aspect="hiring",
    )
    BudgetDecision(
        verdict=BudgetVerdict.GRACEFUL_STOP,
        scope=BudgetScope.RUN,
        projected_cents=Decimal(150),
        cap_cents=Decimal(100),
    )
    Estimate(
        discovered_count=100,
        projected_deep_count=20,
        estimated_cost_cents=Decimal(5000),
        cost_per_account_cents=Decimal(250),
    )
    BurnDown(
        spent_cents=Decimal(10),
        estimated_cents=Decimal(50),
        cap_cents=Decimal(100),
        remaining_cents=Decimal(90),
    )


def test_verification_value_types_construct() -> None:
    PreSpendRequest(
        entity_id=new_entity_id(),
        entity_type=EntityType.ACCOUNT,
        field_key="core.employee_count",
        source_tier=1,
        run_id=new_run_id(),
    )
    assert PreSpendDecision(verdict=PreSpendVerdict.REJECT, reasons=("field unknown",)).reasons
    TargetLock(entity_id=new_entity_id(), no_drift_instruction="only acme.com")
    JudgeResult(claim_id=new_claim_id(), verdict=JudgeVerdict.SUPPORTED, score=0.95)
    Binding(
        claim_id=new_claim_id(),
        contact_entity_id=new_entity_id(),
        strength=IdentityBinding.STRONG,
        strength_score=0.8,
    )
    Staleness(claim_id=new_claim_id(), state=FreshnessState.STALE, age_days=400.0, ttl_days=180.0)
    # M9.5 retention age-out: the freshness value type accepts the EXPIRED disposition (Doc D §4).
    expired = Staleness(
        claim_id=new_claim_id(), state=FreshnessState.EXPIRED, age_days=900.0, ttl_days=365.0
    )
    assert expired.state is FreshnessState.EXPIRED
    ReResearchCandidate(
        entity_id=new_entity_id(), field_key="account.recent_funding", due_at=_NOW, priority=1
    )


def test_value_types_are_frozen() -> None:
    result = PhaseResult(status=PhaseStatus.COMPLETED)
    with pytest.raises(ValidationError):
        result.status = PhaseStatus.FAILED  # type: ignore[misc]


# --- idempotency key derivation is deterministic and distinct ---------------


def test_idempotency_key_is_deterministic_and_scope_prefixed() -> None:
    a = idempotency_key(IdempotencyScope.PROJECT_PHASE, "run-1", "discovery")
    b = idempotency_key(IdempotencyScope.PROJECT_PHASE, "run-1", "discovery")
    assert a == b
    # The prefix is the scope VALUE — frozen durable ledger data ("campaign_phase"), deliberately
    # NOT renamed at §1a stage 2 (PB-rename playbook §4.5); only the member NAME is PROJECT_PHASE.
    assert a.startswith("campaign_phase:")
    assert a != idempotency_key(IdempotencyScope.PROJECT_PHASE, "run-1", "scoring")
    # No concatenation collisions: ("ab","c") and ("a","bc") must differ.
    assert idempotency_key(IdempotencyScope.ACCOUNT_STEP, "ab", "c") != idempotency_key(
        IdempotencyScope.ACCOUNT_STEP, "a", "bc"
    )


def test_account_step_and_phase_keys_are_stable() -> None:
    run_id = new_run_id()
    entity_id = new_entity_id()
    k1 = account_step_key(run_id, entity_id, "core.employee_count", 1)
    k2 = account_step_key(run_id, entity_id, "core.employee_count", 1)
    assert k1 == k2
    assert k1.startswith("account_step:")
    assert k1 != account_step_key(run_id, entity_id, "core.employee_count", 2)

    project_run_id = new_project_run_id()
    p1 = phase_key(project_run_id, ProjectPhase.DEEP)
    assert p1 == phase_key(project_run_id, ProjectPhase.DEEP)
    assert p1 != phase_key(project_run_id, ProjectPhase.VERIFICATION)
