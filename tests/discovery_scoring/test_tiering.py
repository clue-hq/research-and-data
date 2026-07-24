"""M6.4 (ENG-146) — the tiering engine: pure tiering/estimate + the store read/write units.

The pure half (always-run): :func:`assign_tiers` is deterministic and re-tiers on cutoff change;
:func:`tier_distribution` lists every named tier; :func:`estimate_cost` multiplies per-tier band ×
count and excludes unmapped (non-deep) tiers; :func:`cutoff_version` is stable + content-addressed;
:meth:`CheckpointDecision.from_params` parses defensively. The DB half (skip without a migrated DB):
:func:`load_score_views` reads the M6.3 score object back, and :func:`persist_tier` is idempotent on
the cutoff-derived run and ICP-scoped on supersession (one live tier per ICP).
"""

from __future__ import annotations

from decimal import Decimal

from clue_core import (
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    RunId,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.claimstore import WorkspaceScope, claims_for, insert_claim, load_core_pack
from clue_research.discovery_scoring.scoring import FIT_FIELD, INTENT_FIELD
from clue_research.discovery_scoring.tiering import (
    DEFAULT_TIERING_CONFIG,
    TIER_FIELD,
    AccountScoreView,
    CheckpointAction,
    CheckpointDecision,
    TieringConfig,
    assign_tiers,
    cutoff_version,
    estimate_cost,
    load_score_views,
    persist_tier,
    tier_distribution,
)
from clue_research.icp.rubric import TierBand, TierCutoffs
from clue_research.identity import insert_account_entity, mark_merged, stamp_reuse

from .conftest import rollback_conn, run_async

CLIENT = "acme"
ICP = "default"

# bands evaluated most-selective first; fallback = "low".
_CUTOFFS = TierCutoffs(
    bands=(
        TierBand(tier="high", min_fit=0.4, min_intent=0.5),
        TierBand(tier="medium", min_fit=0.2, min_intent=0.0),
    ),
    fallback_tier="low",
)


def _view(fit: float, intent: float) -> AccountScoreView:
    return AccountScoreView(account_id=new_entity_id(), fit=fit, intent=intent)


# --- pure: assign_tiers -----------------------------------------------------
def test_assign_tiers_is_deterministic() -> None:
    views = [_view(0.5, 1.0), _view(0.25, 0.0), _view(0.05, 0.0)]
    first = assign_tiers(views, _CUTOFFS)
    second = assign_tiers(views, _CUTOFFS)
    assert first == second
    tiers = [first[v.account_id] for v in views]
    assert tiers == ["high", "medium", "low"]


def test_assign_tiers_retiers_on_cutoff_change() -> None:
    view = _view(0.5, 1.0)
    assert assign_tiers([view], _CUTOFFS)[view.account_id] == "high"
    # raise the high floor above this account's fit → it drops to medium, no re-score
    stricter = TierCutoffs(
        bands=(
            TierBand(tier="high", min_fit=0.6, min_intent=0.5),
            TierBand(tier="medium", min_fit=0.2, min_intent=0.0),
        ),
        fallback_tier="low",
    )
    assert assign_tiers([view], stricter)[view.account_id] == "medium"


# --- pure: distribution + estimate ------------------------------------------
def test_tier_distribution_lists_every_named_tier() -> None:
    views = [_view(0.5, 1.0), _view(0.05, 0.0)]
    assignments = assign_tiers(views, _CUTOFFS)
    dist = tier_distribution(assignments, _CUTOFFS)
    # every band + the fallback appears, empty tiers as 0 (clear surface)
    assert dist == {"high": 1, "medium": 0, "low": 1}


def test_estimate_cost_multiplies_band_by_count() -> None:
    dist = {"high": 2, "medium": 1, "low": 3, "untiered": 0}
    estimate = estimate_cost(dist, DEFAULT_TIERING_CONFIG)  # bands high=500, medium=200
    assert estimate.discovered_count == 6
    assert estimate.projected_deep_count == 3  # high + medium are deep-eligible; low/untiered not
    assert estimate.estimated_cost_cents == Decimal(1200)  # 2*500 + 1*200
    assert estimate.cost_per_account_cents == Decimal(400)  # 1200 / 3


def test_estimate_cost_unmapped_tier_is_not_deep() -> None:
    # a tier with no configured band contributes zero spend and zero projected-deep
    estimate = estimate_cost({"low": 5}, DEFAULT_TIERING_CONFIG)
    assert estimate.projected_deep_count == 0
    assert estimate.estimated_cost_cents == Decimal(0)
    assert estimate.cost_per_account_cents == Decimal(0)


def test_estimate_cost_band_override() -> None:
    config = TieringConfig(pass_b_bands_cents={"high": Decimal(1000)})
    estimate = estimate_cost({"high": 2, "medium": 3}, config)
    assert estimate.projected_deep_count == 2  # medium no longer mapped → not deep
    assert estimate.estimated_cost_cents == Decimal(2000)


# --- pure: cutoff_version ----------------------------------------------------
def test_cutoff_version_stable_and_distinct() -> None:
    assert cutoff_version(_CUTOFFS) == cutoff_version(_CUTOFFS)  # stable
    other = TierCutoffs(
        bands=(TierBand(tier="high", min_fit=0.9, min_intent=0.9),), fallback_tier="low"
    )
    assert cutoff_version(_CUTOFFS) != cutoff_version(other)  # any change → new version
    assert cutoff_version(_CUTOFFS).startswith("v-")


# --- pure: CheckpointDecision.from_params ------------------------------------
def test_decision_from_params_empty_is_awaiting() -> None:
    decision = CheckpointDecision.from_params({})
    assert decision.action is None and decision.cutoffs is None
    assert decision.budget_cap_cents is None


def test_decision_from_params_parses_action_and_cap() -> None:
    approve = CheckpointDecision.from_params(
        {"checkpoint_decision": {"action": "approve", "budget_cap_cents": "1500"}}
    )
    assert approve.action is CheckpointAction.APPROVE
    assert approve.budget_cap_cents == Decimal(1500)
    pause = CheckpointDecision.from_params({"checkpoint_decision": {"action": "pause"}})
    assert pause.action is CheckpointAction.PAUSE


def test_decision_from_params_degrades_malformed() -> None:
    # unknown action and negative cap degrade to empty rather than raising
    decision = CheckpointDecision.from_params(
        {"checkpoint_decision": {"action": "explode", "budget_cap_cents": -10}}
    )
    assert decision.action is None
    assert decision.budget_cap_cents is None


def test_decision_from_params_parses_cutoffs() -> None:
    decision = CheckpointDecision.from_params(
        {"checkpoint_decision": {"cutoffs": _CUTOFFS.model_dump(mode="json")}}
    )
    assert decision.cutoffs == _CUTOFFS


def test_decision_from_params_degrades_non_finite_cap() -> None:
    # Decimal(str(inf)) SUCCEEDS (yields Infinity); a NaN comparison signals; and CostCents rejects
    # non-finite — so a garbage cap must degrade to None, never crash the durable phase.
    for bad in (float("inf"), float("-inf"), float("nan"), "Infinity", "NaN", "-Infinity"):
        decision = CheckpointDecision.from_params(
            {"checkpoint_decision": {"action": "approve", "budget_cap_cents": bad}}
        )
        assert decision.budget_cap_cents is None  # degraded
        assert decision.action is CheckpointAction.APPROVE  # the rest still parses


# --- DB: load_score_views + persist_tier (skip without a migrated DB) --------
def test_persist_tier_idempotent_and_icp_supersede(require_discovery_db: None) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            eid = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=CLIENT
            )
            view = AccountScoreView(account_id=eid, fit=0.5, intent=1.0, rubric_version=1)
            scope = WorkspaceScope.for_workspace(CLIENT)
            run_a = new_run_id()

            claim1, written1 = await persist_tier(
                conn,
                view=view,
                tier="high",
                cutoff_version="v-aaa",
                run_id=run_a,
                workspace_id=CLIENT,
                icp_key=ICP,
                icp_version=1,
            )
            assert written1 is True
            # replay on the same run → no new claim
            claim1b, written1b = await persist_tier(
                conn,
                view=view,
                tier="high",
                cutoff_version="v-aaa",
                run_id=run_a,
                workspace_id=CLIENT,
                icp_key=ICP,
                icp_version=1,
            )
            assert written1b is False and claim1b == claim1

            # a new cutoff version (new run) supersedes the prior tier for THIS ICP
            run_b = new_run_id()
            _, written2 = await persist_tier(
                conn,
                view=view,
                tier="medium",
                cutoff_version="v-bbb",
                run_id=run_b,
                workspace_id=CLIENT,
                icp_key=ICP,
                icp_version=1,
            )
            assert written2 is True
            live = await claims_for(conn, eid, TIER_FIELD, scope=scope)
            assert len(live) == 1  # one live winner
            assert live[0].value_json["tier"] == "medium"
            assert live[0].value_json["cutoff_version"] == "v-bbb"
            assert live[0].reuse_scope is ReuseScope.TENANT_PRIVATE
            assert live[0].workspace_id == CLIENT
            history = await claims_for(conn, eid, TIER_FIELD, scope=scope, include_superseded=True)
            assert len(history) == 2  # the prior tier is superseded, not deleted

            # invisible to a public-only read (tenant isolation)
            public = await claims_for(conn, eid, TIER_FIELD, scope=WorkspaceScope.public_only())
            assert public == []

    run_async(_run())


def test_persist_tier_other_icp_not_superseded(require_discovery_db: None) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            eid = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=CLIENT
            )
            view = AccountScoreView(account_id=eid, fit=0.5, intent=1.0)
            scope = WorkspaceScope.for_workspace(CLIENT)

            await persist_tier(
                conn,
                view=view,
                tier="high",
                cutoff_version="v-aaa",
                run_id=new_run_id(),
                workspace_id=CLIENT,
                icp_key="icp_one",
                icp_version=1,
            )
            await persist_tier(
                conn,
                view=view,
                tier="low",
                cutoff_version="v-aaa",
                run_id=new_run_id(),
                workspace_id=CLIENT,
                icp_key="icp_two",
                icp_version=1,
            )
            # D5: two ICPs each keep their own live tier on one account (no cross-ICP supersede)
            live = await claims_for(conn, eid, TIER_FIELD, scope=scope)
            assert len(live) == 2
            assert {c.value_json["icp_key"] for c in live} == {"icp_one", "icp_two"}

    run_async(_run())


def test_load_score_views_skips_unscored(require_discovery_db: None) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            # no score claims for this run → empty views (never fabricates a score)
            views = await load_score_views(conn, scoring_run=new_run_id(), workspace_id=CLIENT)
            assert views == []

    run_async(_run())


async def _insert_score(conn, eid: EntityId, field_key: str, value: float, run_id: RunId) -> None:
    """A minimal M6.3-shaped score claim (top-level ``value``), tenant-private."""
    await insert_claim(
        conn,
        stamp_reuse(
            account_claim(
                entity_id=eid,
                field_key=field_key,
                value_json={
                    "value": value,
                    "components": [],
                    "rubric_version": 1,
                    "non_fit_flag": False,
                    "icp_key": ICP,
                    "icp_version": 1,
                },
                source_tier=1,
                extraction_method=ExtractionMethod.HUMAN,
                confidence=1.0,
                run_id=run_id,
                research_mode=ResearchMode.ACCOUNT_PROFILING,
            ),
            workspace_id=CLIENT,
        ),
    )


def test_load_score_views_collapses_merged_survivor(require_discovery_db: None) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            run_id = new_run_id()
            a = await insert_account_entity(
                conn, canonical_name="A", primary_domain="a.example", workspace_id=CLIENT
            )
            b = await insert_account_entity(
                conn, canonical_name="B", primary_domain="b.example", workspace_id=CLIENT
            )
            for eid in (a, b):
                await _insert_score(conn, eid, FIT_FIELD, 0.5, run_id)
                await _insert_score(conn, eid, INTENT_FIELD, 0.8, run_id)
            await mark_merged(conn, EntityType.ACCOUNT, a, b)  # a → b (b is the survivor)

            views = await load_score_views(conn, scoring_run=run_id, workspace_id=CLIENT)
            # the two pre-merge entities collapse to ONE survivor view (b), scored once
            assert len(views) == 1
            assert views[0].account_id == b

    run_async(_run())


def test_load_score_views_skips_claim_on_merged_loser(require_discovery_db: None) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_core_pack(conn)
            run_id = new_run_id()
            a = await insert_account_entity(
                conn, canonical_name="A", primary_domain="a.example", workspace_id=CLIENT
            )
            b = await insert_account_entity(
                conn, canonical_name="B", primary_domain="b.example", workspace_id=CLIENT
            )
            # only A is scored, then A merges INTO B (claims are never re-pointed on merge)
            await _insert_score(conn, a, FIT_FIELD, 0.5, run_id)
            await _insert_score(conn, a, INTENT_FIELD, 0.8, run_id)
            await mark_merged(conn, EntityType.ACCOUNT, a, b)  # a → b (b is the survivor)

            views = await load_score_views(conn, scoring_run=run_id, workspace_id=CLIENT)
            # the live FIT claim is on the merged-away loser, not the survivor → skipped (no crash)
            assert views == []

    run_async(_run())
