"""R1 quarantine of the retired M8A composition plus retained high-tier resolver tests."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.deep import (
    build_deep_phase_handler,
    build_high_tier_resolver,
    register_deep_phase_handler,
)
from clue_api.deep.composition import _live_tier_for_project
from clue_api.entity_research_quarantine import EntityResearchAgentNotComposed
from clue_core import (
    Claim,
    ExtractionMethod,
    ICPCreatedFrom,
    ICPSpec,
    PhaseContext,
    ProjectPhase,
    ResearchMode,
    account_claim,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import insert_claim
from clue_research.discovery_scoring.tiering import (
    TIER_FIELD,
    DiscoverySelectionPolicy,
    cutoff_version,
)
from clue_research.icp.rubric import TierBand, TierCutoffs
from clue_research.identity import stamp_reuse
from tests.profiling.conftest import (
    FakeCommitteeSource,
    FakeGateway,
    conn_session_factory,
    insert_test_account,
    rollback_conn,
    run_async,
    seed_packs,
)

_CLIENT = "acme"
_ICP = "seg1"
_COMMITTEE = [FakeCommitteeSource(source_key="apollo_people", tier=2)]


def _spec(*, icp_key: str = _ICP) -> ICPSpec:
    return ICPSpec(workspace_id=_CLIENT, icp_key=icp_key, created_from=ICPCreatedFrom.SYNTHESIS)


def _composition(**kwargs: object) -> object:
    return build_deep_phase_handler(
        spec=_spec(),
        gateway=FakeGateway(),
        committee_sources=_COMMITTEE,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "kwargs",
    ({}, {"lock_factory": None}, {"scheduler": object()}, {"committee_preparer": object()}),
)
def test_retired_builder_fails_loud_for_every_former_composition_variant(
    kwargs: dict[str, object],
) -> None:
    """No public constructor variant may reconstruct the quarantined provider pipeline."""

    with pytest.raises(EntityResearchAgentNotComposed):
        _composition(**kwargs)


def test_retired_registration_fails_before_registering_a_handler() -> None:
    registered: list[object] = []
    with pytest.raises(EntityResearchAgentNotComposed):
        register_deep_phase_handler(
            spec=_spec(),
            gateway=FakeGateway(),
            committee_sources=_COMMITTEE,
            storage=None,
            register=registered.append,
        )
    assert registered == []


# --- the high-tier resolver (D-B) reads tier claims by the committed cutoff_version --------------


async def _write_tier_claim(
    conn: AsyncConnection,
    account_id: UUID,
    *,
    tier: str,
    cversion: str,
    icp_key: str,
) -> None:
    claim = stamp_reuse(
        account_claim(
            entity_id=account_id,
            field_key=TIER_FIELD,
            value_json={
                "tier": tier,
                "cutoff_version": cversion,
                "icp_key": icp_key,
                "icp_version": 1,
            },
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            run_id=new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
        ),
        workspace_id=_CLIENT,
    )
    await insert_claim(conn, claim)


def test_high_tier_resolver_selects_named_band_at_committed_cutoff(
    require_profiling_db: None,
) -> None:
    """Only accounts whose live ``account.scoring.tier`` claim names a (non-fallback) band, at the
    committed ``cutoff_version``, for THIS ICP, resolve to an ``AccountSpec`` (D-B): a fallback-tier
    account, a wrong-version account, and a wrong-ICP account are all excluded."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            factory = conn_session_factory(conn)
            cutoffs = TierCutoffs(
                bands=(TierBand(tier="high", min_fit=0.5, min_intent=0.5),),
                fallback_tier="untiered",
            )
            committed = cutoff_version(cutoffs)

            high = await insert_test_account(conn, name="High Co", domain="high.example")
            fallback = await insert_test_account(conn, name="Low Co", domain="low.example")
            wrong_ver = await insert_test_account(conn, name="Stale Co", domain="stale.example")
            wrong_icp = await insert_test_account(conn, name="Other Co", domain="other.example")
            await _write_tier_claim(conn, high.id, tier="high", cversion=committed, icp_key=_ICP)
            await _write_tier_claim(
                conn, fallback.id, tier="untiered", cversion=committed, icp_key=_ICP
            )
            await _write_tier_claim(
                conn, wrong_ver.id, tier="high", cversion="v-other", icp_key=_ICP
            )
            await _write_tier_claim(
                conn, wrong_icp.id, tier="high", cversion=committed, icp_key="seg2"
            )

            resolver = build_high_tier_resolver(spec=_spec(), session_factory=factory)
            ctx = PhaseContext(
                project_run_id=new_project_run_id(),
                project_id="prj-test",
                brand_id="brd-test",
                phase=ProjectPhase.DEEP,
                workspace_id=_CLIENT,
                icp_key=_ICP,
                icp_version=1,
                params={"tier_cutoffs": cutoffs.model_dump(mode="json")},
            )
            # Production now fails closed until a confirmed directive is explicitly launched.
            specs = tuple(await resolver(ctx))

            assert specs == ()

    run_async(scenario())


def test_high_tier_resolver_selects_only_current_run_human_approved_criteria_account(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            factory = conn_session_factory(conn)
            strategy = {
                "scoring_mode": "disabled",
                "selection_mode": "discovery_criteria",
                "must_have_criteria": ["Independent practice"],
                "approved_tier": "high",
            }
            spec = ICPSpec(
                workspace_id=_CLIENT,
                icp_key=_ICP,
                created_from=ICPCreatedFrom.SYNTHESIS,
                discovery_strategy=strategy,
            )
            policy = DiscoverySelectionPolicy.from_slot(strategy)
            current_run = new_project_run_id()
            stale_run = new_project_run_id()
            approved = await insert_test_account(
                conn, name="Approved Co", domain="approved.example"
            )
            stale = await insert_test_account(
                conn, name="Stale Co", domain="stale-selection.example"
            )

            async def write(account_id: UUID, project_run_id) -> None:
                await insert_claim(
                    conn,
                    stamp_reuse(
                        account_claim(
                            entity_id=account_id,
                            field_key=TIER_FIELD,
                            value_json={
                                "tier": "high",
                                "decision_basis": "discovery_criteria",
                                "selection_policy_version": policy.policy_version,
                                "cutoff_version": "criteria-decision",
                                "project_run_id": str(project_run_id),
                                "icp_key": _ICP,
                                "icp_version": 1,
                            },
                            source_tier=1,
                            extraction_method=ExtractionMethod.HUMAN,
                            confidence=1.0,
                            run_id=new_run_id(),
                            research_mode=ResearchMode.ACCOUNT_PROFILING,
                        ),
                        workspace_id=_CLIENT,
                    ),
                )

            await write(approved.id, current_run)
            await write(stale.id, stale_run)
            resolver = build_high_tier_resolver(spec=spec, session_factory=factory)
            ctx = PhaseContext(
                project_run_id=current_run,
                project_id="prj-test",
                brand_id="brd-test",
                phase=ProjectPhase.DEEP,
                workspace_id=_CLIENT,
                icp_key=_ICP,
                icp_version=1,
            )
            specs = tuple(await resolver(ctx))
            assert specs == ()

    run_async(scenario())


# --- FI-2 §6.4: the resolver reads ITS OWN project's live tier ---------------
def test_live_tier_for_project_picks_this_projects_tier() -> None:
    """Since §6.4 stopped cross-project supersession, one account can carry several live tier
    claims — one per project. The resolver must read its own (not whichever landed last), skip
    another project's entirely, and still honour an unstamped legacy tier."""
    account_id = new_entity_id()

    def _claim(**extra: JsonValue) -> Claim:
        value_json: dict[str, JsonValue] = {
            "tier": "high",
            "cutoff_version": "v-a",
            "icp_key": _ICP,
        }
        value_json.update(extra)
        return account_claim(
            entity_id=account_id,
            field_key=TIER_FIELD,
            value_json=value_json,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            run_id=new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
        )

    p2 = _claim(project_id="prj-two", tier="low")
    p1 = _claim(project_id="prj-one")
    legacy = _claim()

    # P2's claim is the most recent, but P1's phase must read P1's tier.
    mine = _live_tier_for_project([p2, p1], project_id="prj-one")
    assert mine is not None and mine["tier"] == "high"
    # Only another project's tier is live → this project selects nothing (never P2's).
    assert _live_tier_for_project([p2], project_id="prj-one") is None
    # An unstamped legacy tier belongs to no project's lens, so any project may read it.
    fallback = _live_tier_for_project([p2, legacy], project_id="prj-one")
    assert fallback is not None and fallback["tier"] == "high"
