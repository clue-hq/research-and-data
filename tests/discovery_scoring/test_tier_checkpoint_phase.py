"""M6.4 (ENG-146) — the integrated TIER_CHECKPOINT PhaseHandler, against a live Postgres.

End to end: seed an active ICP (rubric + cutoffs) + admitted accounts, run the M6.3 SCORING phase to
produce the score object, then drive the TIER_CHECKPOINT phase through its durable states — the
initial suspension with a review payload + cost estimate; a cutoff adjustment that re-tiers and
re-estimates without re-spending Pass A; a projected-over-cap graceful stop; and an approve that
persists the per-account tier decision and completes (advancing the run to `deep`). Replay is
idempotent (the resume applies at most once). One test per acceptance criterion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EntityId,
    EntityType,
    ExtractionMethod,
    ICPCreatedFrom,
    PhaseContext,
    PhaseStatus,
    ProjectPhase,
    ProjectRunId,
    ResearchMode,
    account_claim,
    discovery_claim,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import WorkspaceScope, claims_for, insert_claim, load_core_pack
from clue_research.discovery_scoring import ScoringPhaseHandler, TierCheckpointPhaseHandler
from clue_research.discovery_scoring.phases import discovery_run_id
from clue_research.discovery_scoring.scoring import FIT_FIELD
from clue_research.discovery_scoring.tiering import TIER_FIELD, cutoff_version
from clue_research.icp import (
    RubricEntry,
    ScoringRubric,
    ScoringTransform,
    SubRubric,
    create_icp_spec,
    rubric_to_slot,
)
from clue_research.icp.rubric import TierBand, TierCutoffs
from clue_research.identity import insert_account_entity

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_discovery_db")

CLIENT = "acme"
ICP = "default"
_EMP = "core.employee_count"
_FUND = "account.recent_funding"

# bands most-selective first; fallback = "low".
_CUTOFFS = TierCutoffs(
    bands=(
        TierBand(tier="high", min_fit=0.4, min_intent=0.5),
        TierBand(tier="medium", min_fit=0.2, min_intent=0.0),
    ),
    fallback_tier="low",
)
# tighten the high floor so the high account (fit 0.5) drops to medium (a cutoff-only re-tier).
_TIGHTER = TierCutoffs(
    bands=(
        TierBand(tier="high", min_fit=0.6, min_intent=0.5),
        TierBand(tier="medium", min_fit=0.2, min_intent=0.0),
    ),
    fallback_tier="low",
)


def _session_factory(
    conn: AsyncConnection,
) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncConnection]:
        yield conn

    return _session


def _rubric() -> ScoringRubric:
    """Fit = employee_count (linear 0..1000); Intent = recent_funding present; + tier cutoffs."""
    return ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(
                    field_key=_EMP,
                    transform=ScoringTransform.LINEAR,
                    params={"lo": 0, "hi": 1000},
                ),
            )
        ),
        intent=SubRubric(
            entries=(RubricEntry(field_key=_FUND, transform=ScoringTransform.BOOLEAN),)
        ),
        tier_cutoffs=_CUTOFFS,
    )


def _ctx(
    project_run_id: ProjectRunId,
    *,
    params: dict[str, JsonValue] | None = None,
    budget_cap_cents: int | None = None,
    phase: ProjectPhase = ProjectPhase.TIER_CHECKPOINT,
) -> PhaseContext:
    return PhaseContext(
        project_run_id=project_run_id,
        project_id="prj-test",
        brand_id="brd-test",
        phase=phase,
        workspace_id=CLIENT,
        icp_key=ICP,
        icp_version=1,
        budget_cap_cents=budget_cap_cents,
        params=params or {},
    )


def _decision(**fields: JsonValue) -> dict[str, JsonValue]:
    return {"checkpoint_decision": fields}


async def _seed_active_icp(conn: AsyncConnection, *, with_rubric: bool = True) -> None:
    await create_icp_spec(
        conn,
        workspace_id=CLIENT,
        icp_key=ICP,
        created_from=ICPCreatedFrom.SYNTHESIS,
        field_keys=(_EMP, _FUND),
        scoring_rubric=rubric_to_slot(_rubric()) if with_rubric else None,
        activate=True,
    )


async def _seed_admitted(
    conn: AsyncConnection,
    ctx: PhaseContext,
    *,
    name: str,
    domain: str,
    employee_count: int,
    funding: bool,
) -> EntityId:
    """An admitted account: an entity + its discovery-provenance for the run + scoring inputs."""
    eid = await insert_account_entity(
        conn, canonical_name=name, primary_domain=domain, workspace_id=CLIENT
    )
    await insert_claim(
        conn,
        discovery_claim(
            entity_id=eid,
            entity_type=EntityType.ACCOUNT,
            field_key="core.discovery_provenance",
            value_json={
                "matched_channel": "exa",
                "matched_signal": "saas",
                "discovery_confidence": 0.8,
            },
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.8,
            run_id=discovery_run_id(ctx),
            research_mode=ResearchMode.ACCOUNT_DISCOVERY,
            found_via="exa",
            matched_signal="saas",
            discovery_confidence=0.8,
            source_url=f"https://exa/{domain}",
        ),
    )
    await insert_claim(
        conn,
        account_claim(
            entity_id=eid,
            field_key=_EMP,
            value_json=employee_count,
            source_tier=1,
            extraction_method=ExtractionMethod.API,
            confidence=0.9,
            run_id=new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="https://src/emp",
        ),
    )
    if funding:
        await insert_claim(
            conn,
            account_claim(
                entity_id=eid,
                field_key=_FUND,
                value_json={"amount_usd": 5_000_000, "round": "B"},
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://src/fund",
            ),
        )
    return eid


async def _seed_and_score(conn: AsyncConnection) -> ProjectRunId:
    """Seed + run the M6.3 SCORING phase; return the shared project_run_id.

    Three accounts spanning the cutoffs: high (emp 500/funded → fit 0.5, intent 1.0), medium
    (emp 250/unfunded → fit 0.25, intent 0.0), low (emp 50/unfunded → fit 0.05) — a non-trivial
    distribution {high:1, medium:1, low:1}.
    """
    project_run_id = new_project_run_id()
    await load_core_pack(conn)
    await _seed_active_icp(conn)
    scoring_ctx = _ctx(project_run_id, phase=ProjectPhase.SCORING)
    await _seed_admitted(
        conn, scoring_ctx, name="High", domain="high.example", employee_count=500, funding=True
    )
    await _seed_admitted(
        conn, scoring_ctx, name="Med", domain="med.example", employee_count=250, funding=False
    )
    await _seed_admitted(
        conn, scoring_ctx, name="Low", domain="low.example", employee_count=50, funding=False
    )
    scoring_result = await ScoringPhaseHandler(session_factory=_session_factory(conn)).run(
        scoring_ctx
    )
    assert scoring_result.status is PhaseStatus.COMPLETED
    assert scoring_result.accounts_processed == 3
    return project_run_id


async def _live_count(conn: AsyncConnection, field_key: str) -> int:
    """Live (non-superseded) claim count for a field across the test client's data."""
    row = await conn.execute(
        text("SELECT count(*) FROM claim WHERE field_key = :fk AND superseded_by IS NULL"),
        {"fk": field_key},
    )
    return int(row.scalar_one())


async def _history_count(conn: AsyncConnection, field_key: str) -> int:
    """All claims for a field, including superseded (append-only history)."""
    row = await conn.execute(
        text("SELECT count(*) FROM claim WHERE field_key = :fk"), {"fk": field_key}
    )
    return int(row.scalar_one())


async def _account_id(conn: AsyncConnection, domain: str) -> EntityId:
    row = await conn.execute(
        text("SELECT id FROM account_entity WHERE primary_domain = :d"), {"d": domain}
    )
    return EntityId(row.scalar_one())


# --- AC2: durable suspension + review payload -------------------------------
def test_checkpoint_suspends_with_review_payload() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            project_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))
            result = await handler.run(_ctx(project_run_id))

            assert result.status is PhaseStatus.PAUSED
            assert result.payload["checkpoint_status"] == "awaiting"
            assert result.payload["scored_count"] == 3
            review = result.payload["review"]
            assert isinstance(review, dict)
            # per-account provisional fit/intent with working evidence links
            accounts = review["accounts"]
            assert isinstance(accounts, list) and len(accounts) == 3
            for row in accounts:
                assert isinstance(row, dict)
                assert {"fit", "intent", "tier"} <= row.keys()
                assert row["fit_claim_id"] is not None  # inspectable back to its score claim
                assert row["evidence_claim_ids"]  # backing proxy claim ids
            # proposed cutoffs + tier distribution + cost estimate (the EXACT cutoffs surfaced)
            assert review["proposed_cutoffs"] == _CUTOFFS.model_dump(mode="json")
            assert result.payload["cutoff_version"] == cutoff_version(_CUTOFFS)
            assert review["tier_distribution"] == {"high": 1, "medium": 1, "low": 1}
            estimate = review["estimate"]
            assert isinstance(estimate, dict)
            assert estimate["projected_deep_count"] == 2  # high + medium are deep-eligible
            # no tier claims persisted on a review-only (no decision) suspension
            assert await _live_count(conn, TIER_FIELD) == 0

    run_async(_run())


# --- AC3: estimate updates on cutoff adjustment, without re-spending Pass A --
def test_cutoff_adjustment_retiers_and_reestimates_without_respend() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            project_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))

            base = await handler.run(_ctx(project_run_id))
            base_dist = base.payload["tier_distribution"]
            base_estimate = base.payload["estimate"]
            fit_before = await _live_count(conn, FIT_FIELD)

            adjusted = await handler.run(
                _ctx(project_run_id, params=_decision(cutoffs=_TIGHTER.model_dump(mode="json")))
            )
            assert adjusted.status is PhaseStatus.PAUSED  # still awaiting (cutoff-only adjustment)
            assert adjusted.payload["tier_distribution"] == {"high": 0, "medium": 2, "low": 1}
            assert adjusted.payload["tier_distribution"] != base_dist
            # the surfaced cutoffs + version are the adjusted ones (not the rubric default)
            adj_review = adjusted.payload["review"]
            assert isinstance(adj_review, dict)
            assert adj_review["proposed_cutoffs"] == _TIGHTER.model_dump(mode="json")
            assert adjusted.payload["cutoff_version"] == cutoff_version(_TIGHTER)
            assert adjusted.payload["cutoff_version"] != base.payload["cutoff_version"]
            # the estimate changed (now only medium is deep-eligible → fewer go deep, less spend)
            adj_estimate = adjusted.payload["estimate"]
            assert isinstance(base_estimate, dict) and isinstance(adj_estimate, dict)
            assert adj_estimate["estimated_cost_cents"] != base_estimate["estimated_cost_cents"]
            assert adj_estimate["projected_deep_count"] == 2  # both medium accounts go deep
            # NO Pass-A re-spend: the score (fit) claims are unchanged, and no tier claim written
            assert await _live_count(conn, FIT_FIELD) == fit_before
            assert await _live_count(conn, TIER_FIELD) == 0

    run_async(_run())


# --- AC4 + AC6: approve → completed (deep); persists the decision ------------
def test_resume_approve_completes_and_persists_tiers() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            project_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))
            result = await handler.run(_ctx(project_run_id, params=_decision(action="approve")))
            assert result.status is PhaseStatus.COMPLETED  # advances to `deep`
            assert result.payload["checkpoint_status"] == "resumed"
            assert result.payload["tiered"] == 3
            assert result.payload["errors"] == 0  # every account persisted, none isolated out
            assert result.accounts_processed == 3
            # the per-account tier is persisted, tenant-private, with the approved cutoff version
            assert await _live_count(conn, TIER_FIELD) == 3
            scope = WorkspaceScope.for_workspace(CLIENT)
            eid = await _account_id(conn, "high.example")
            tier_claims = await claims_for(conn, eid, TIER_FIELD, scope=scope)
            assert len(tier_claims) == 1
            value = tier_claims[0].value_json
            assert isinstance(value, dict)
            assert value["tier"] == "high"
            assert value["cutoff_version"] == result.payload["cutoff_version"]
            assert "fit_score" in value and "intent_score" in value
            # invisible to a public read (tenant isolation)
            public = await claims_for(conn, eid, TIER_FIELD, scope=WorkspaceScope.public_only())
            assert public == []

    run_async(_run())


# --- AC4: pause stays suspended ---------------------------------------------
def test_resume_pause_stays_suspended() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            project_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))
            result = await handler.run(_ctx(project_run_id, params=_decision(action="pause")))
            assert result.status is PhaseStatus.PAUSED
            assert result.payload["checkpoint_status"] == "awaiting"
            assert await _live_count(conn, TIER_FIELD) == 0  # pause persists nothing

    run_async(_run())


# --- AC4: projected-over-cap halts gracefully, then a raised cap resumes -----
def test_projected_over_cap_halts_then_raise_cap_resumes() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            project_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))
            # default bands: high=500 + medium=200 = 700 cents projected; cap 100 → over cap
            over = await handler.run(
                _ctx(project_run_id, params=_decision(action="approve"), budget_cap_cents=100)
            )
            assert over.status is PhaseStatus.PAUSED  # graceful stop, not completed
            assert over.payload["projected_over_cap"] is True
            assert await _live_count(conn, TIER_FIELD) == 0  # nothing persisted over cap

            # raise the cap in the decision → approve now proceeds
            resumed = await handler.run(
                _ctx(
                    project_run_id,
                    params=_decision(action="approve", budget_cap_cents=10_000),
                    budget_cap_cents=100,
                )
            )
            assert resumed.status is PhaseStatus.COMPLETED
            assert resumed.payload["projected_over_cap"] is False
            assert await _live_count(conn, TIER_FIELD) == 3

    run_async(_run())


# --- AC5: crash re-entry re-presents identical state; resume applied once ----
def test_reentry_is_idempotent() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            project_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))
            approve = _ctx(project_run_id, params=_decision(action="approve"))
            first = await handler.run(approve)
            second = await handler.run(approve)  # crash re-entry → same cutoff-derived run

            assert first.payload["tiered"] == 3
            assert second.status is PhaseStatus.COMPLETED
            assert second.payload["tiered"] == 0  # nothing re-written
            assert second.payload["replayed"] == 3
            assert second.payload["cutoff_version"] == first.payload["cutoff_version"]
            assert await _live_count(conn, TIER_FIELD) == 3  # no duplicate tier claims

    run_async(_run())


# --- AC1 + AC5: approve with adjusted cutoffs supersedes the prior approve ----
def test_approve_with_adjusted_cutoffs_supersedes_prior() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            project_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))

            first = await handler.run(_ctx(project_run_id, params=_decision(action="approve")))
            assert first.status is PhaseStatus.COMPLETED
            assert await _live_count(conn, TIER_FIELD) == 3
            cversion_a = first.payload["cutoff_version"]

            # re-approve with tightened cutoffs → a NEW cutoff version supersedes the prior tiers
            second = await handler.run(
                _ctx(
                    project_run_id,
                    params=_decision(action="approve", cutoffs=_TIGHTER.model_dump(mode="json")),
                )
            )
            assert second.status is PhaseStatus.COMPLETED
            cversion_b = second.payload["cutoff_version"]
            assert cversion_b != cversion_a  # the handler threaded the adjusted cutoffs through
            assert second.payload["tiered"] == 3  # 3 new tier claims written
            # one live winner per account (3, not 6); every prior tier superseded (history = 6)
            assert await _live_count(conn, TIER_FIELD) == 3
            assert await _history_count(conn, TIER_FIELD) == 6
            scope = WorkspaceScope.for_workspace(CLIENT)
            for domain in ("high.example", "med.example", "low.example"):
                eid = await _account_id(conn, domain)
                live = await claims_for(conn, eid, TIER_FIELD, scope=scope)
                assert len(live) == 1
                assert live[0].value_json["cutoff_version"] == cversion_b

    run_async(_run())


# --- AC4: the over-cap boundary (estimated == cap is WITHIN cap) --------------
def test_over_cap_boundary_equal_is_within_cap() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            project_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))
            # distribution {high:1, medium:1, low:1} × default bands → 700 cents projected.
            # cap exactly 1 below → over cap → graceful stop, nothing persisted.
            just_over = await handler.run(
                _ctx(project_run_id, params=_decision(action="approve"), budget_cap_cents=699)
            )
            assert just_over.status is PhaseStatus.PAUSED
            assert just_over.payload["projected_over_cap"] is True
            assert await _live_count(conn, TIER_FIELD) == 0
            # cap exactly equal to projected → within cap (strict >) → approve completes
            at_cap = await handler.run(
                _ctx(project_run_id, params=_decision(action="approve"), budget_cap_cents=700)
            )
            assert at_cap.status is PhaseStatus.COMPLETED
            assert at_cap.payload["projected_over_cap"] is False
            assert await _live_count(conn, TIER_FIELD) == 3

    run_async(_run())


# --- a garbage (non-finite) cap from secure-input must degrade, not crash -----
def test_non_finite_cap_degrades_and_does_not_crash() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            project_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))
            # an inf cap degrades to None (no cap) → approve proceeds rather than crashing the phase
            result = await handler.run(
                _ctx(
                    project_run_id,
                    params=_decision(action="approve", budget_cap_cents=float("inf")),
                )
            )
            assert result.status is PhaseStatus.COMPLETED
            assert await _live_count(conn, TIER_FIELD) == 3

    run_async(_run())


def test_review_is_deterministic_across_reentry() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            project_run_id = await _seed_and_score(conn)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))
            ctx = _ctx(project_run_id)
            first = await handler.run(ctx)
            second = await handler.run(ctx)
            # re-presents byte-identical review state on crash re-entry
            assert first.payload["review"] == second.payload["review"]
            assert first.payload["cutoff_version"] == second.payload["cutoff_version"]

    run_async(_run())


def test_checkpoint_fails_without_a_rubric() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            await _seed_active_icp(conn, with_rubric=False)
            handler = TierCheckpointPhaseHandler(session_factory=_session_factory(conn))
            result = await handler.run(_ctx(new_project_run_id()))
            assert result.status is PhaseStatus.FAILED
            assert "no scoring rubric" in str(result.payload["error"])

    run_async(_run())
