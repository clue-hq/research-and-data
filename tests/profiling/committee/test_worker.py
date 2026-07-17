"""M8.3 committee discovery worker — end-to-end (DB-gated) + AspectWorker conformance.

Exercises the full ``discover_committee`` flow (admit → role-infer → gate → write role/persona) and
the bounded-discovery termination, against fake people-sources + a fake gateway.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AspectContext,
    AspectWorker,
    IdentityBinding,
    Persona,
    ResearchMode,
    UseClass,
    WorkerStatus,
)
from clue_research.claimstore import TenantScope, claims_for, entities_with_field_claim
from clue_research.profiling.committee import (
    PERSONA,
    ROLE_ON_COMMITTEE,
    CommitteeAspectWorker,
    CommitteeConfig,
    CommitteeStoppingConfig,
    discover_committee,
)
from clue_research.profiling.committee.coverage import CommitteeStopReason

from ..conftest import (
    FakeCommitteeSource,
    FakeGateway,
    insert_test_account,
    make_candidate,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = UUID("22222222-2222-2222-2222-222222222222")
_TENANT = "acme"


def _cfo() -> object:
    return make_candidate(
        source_key="apollo_people",
        linkedin_url="https://linkedin.com/in/jane-cfo",
        full_name="Jane CFO",
        title="Chief Financial Officer",
        source_url="https://acme.example/team",
    )


def _vp_eng() -> object:
    return make_candidate(
        source_key="apollo_people",
        linkedin_url="https://linkedin.com/in/sam-vp",
        full_name="Sam VP",
        title="VP of Engineering",
        source_url="https://acme.example/team",
    )


def _ghost() -> object:
    # No strong key → dropped at the gate.
    return make_candidate(source_url="https://acme.example/team", full_name="Ghost", title="CTO")


def test_aspect_worker_conformance() -> None:
    worker = CommitteeAspectWorker(
        session_factory=rollback_conn, sources=[], gateway=FakeGateway(), role_model="m"
    )
    assert isinstance(worker, AspectWorker)
    assert worker.aspect == "committee"


def test_discover_committee_end_to_end(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            source = FakeCommitteeSource(
                source_key="apollo_people", tier=2, candidates=[_cfo(), _vp_eng(), _ghost()]
            )
            gateway = FakeGateway()  # returns economic_buyer (plausible for both executives)
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                tenant_id=_TENANT,
                sources=[source],
                gateway=gateway,
                role_model="model-x",
            )

            assert result.admitted == 2
            assert result.dropped == 1
            assert len(result.members) == 2
            assert len(result.claim_refs) == 6  # discovery + role + persona per member
            assert gateway.complete_calls == 2  # role inference per admitted member

            scope = TenantScope.for_tenant(_TENANT)
            for member in result.members:
                role_claims = await claims_for(
                    conn, member.contact_entity_id, ROLE_ON_COMMITTEE, scope=scope
                )
                persona_claims = await claims_for(
                    conn, member.contact_entity_id, PERSONA, scope=scope
                )
                assert len(role_claims) == 1
                assert len(persona_claims) == 1
                for claim in (role_claims[0], persona_claims[0]):
                    assert claim.research_mode is ResearchMode.COMMITTEE_DISCOVERY
                    assert claim.identity_binding is IdentityBinding.STRONG
                    assert claim.use_class is UseClass.PROFESSIONAL_PUBLIC
                    assert claim.reuse_scope.value == "tenant_private"
                    assert claim.tenant_id == _TENANT
                # role claim value carries the plausibility verdict.
                role_value = role_claims[0].value_json
                assert isinstance(role_value, dict)
                assert role_value["role"] in {p.value for p in Persona}
                assert role_value["plausible"] is True
                assert persona_claims[0].value_json in {p.value for p in Persona}

            # the handoff projection carries personas.
            committee = result.committee()
            assert len(committee) == 2
            assert all(isinstance(m.persona, Persona) for m in committee)
            assert "not a completeness guarantee" in result.coverage.framing

    run_async(scenario())


def test_worker_flags_implausible_junior_role(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            intern = make_candidate(
                source_key="apollo_people",
                linkedin_url="https://linkedin.com/in/junior-intern",
                full_name="Pat Intern",
                title="Engineering Intern",
                source_url="https://acme.example/team",
            )
            source = FakeCommitteeSource(source_key="apollo_people", tier=2, candidates=[intern])
            gateway = FakeGateway()  # returns economic_buyer — implausible for an intern
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                tenant_id=_TENANT,
                sources=[source],
                gateway=gateway,
                role_model="model-x",
            )
            assert result.admitted == 1
            member = result.members[0]
            assert member.role_plausible is False  # flagged
            scope = TenantScope.for_tenant(_TENANT)
            role_claim = (
                await claims_for(conn, member.contact_entity_id, ROLE_ON_COMMITTEE, scope=scope)
            )[0]
            value = role_claim.value_json
            assert isinstance(value, dict)
            assert value["plausible"] is False
            assert value["confidence"] <= 0.15  # flagged, not promotable (below the floor)

    run_async(scenario())


def test_duplicate_candidates_deduped_and_bounded(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            # Same person returned twice → admitted once; source consulted once (bounded).
            source = FakeCommitteeSource(
                source_key="apollo_people", tier=2, candidates=[_cfo(), _cfo()]
            )
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                tenant_id=_TENANT,
                sources=[source],
                gateway=FakeGateway(),
                role_model="model-x",
            )
            assert result.admitted == 1
            assert source.calls == 1  # single pass — no unbounded re-querying

    run_async(scenario())


def test_marginal_yield_stops_before_redundant_source(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            productive = FakeCommitteeSource(
                source_key="apollo_people", tier=2, candidates=[_cfo(), _vp_eng()]
            )
            redundant = FakeCommitteeSource(
                source_key="zoominfo_people", tier=3, candidates=[_cfo(), _vp_eng()]
            )
            never = FakeCommitteeSource(
                source_key="team_page",
                tier=4,
                candidates=[
                    make_candidate(
                        linkedin_url="https://linkedin.com/in/new-person",
                        full_name="New",
                        title="CTO",
                    )
                ],
            )
            config = CommitteeConfig(stopping=CommitteeStoppingConfig(window_size=1))
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                tenant_id=_TENANT,
                sources=[productive, redundant, never],
                gateway=FakeGateway(),
                role_model="model-x",
                config=config,
            )
            # productive admits 2; redundant adds 0 new → yield drops → stop before `never`.
            assert result.admitted == 2
            assert productive.calls == 1
            assert redundant.calls == 1
            assert never.calls == 0  # not consulted — stopped early
            assert result.coverage.stopping_reason is CommitteeStopReason.MARGINAL_YIELD
            assert "team_page" in result.coverage.channels_not_searched

    run_async(scenario())


def test_budget_cap_stops_discovery(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            costly = FakeCommitteeSource(
                source_key="apollo_people",
                tier=2,
                candidates=[
                    make_candidate(
                        linkedin_url="https://linkedin.com/in/jane-cfo",
                        title="CFO",
                        source_url="https://acme.example/team",
                        cost_cents=Decimal(50),
                    )
                ],
            )
            never = FakeCommitteeSource(
                source_key="zoominfo_people", tier=3, candidates=[_vp_eng()]
            )
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                tenant_id=_TENANT,
                sources=[costly, never],
                gateway=FakeGateway(),
                role_model="model-x",
                budget_cap_cents=Decimal(10),
            )
            assert result.coverage.stopping_reason is CommitteeStopReason.BUDGET_CAP
            assert never.calls == 0

    run_async(scenario())


def test_missing_role_model_fails_loud(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            raised = False
            try:
                await discover_committee(
                    conn,
                    account_entity_id=account.id,
                    run_id=_RUN,
                    tenant_id=_TENANT,
                    sources=[],
                    gateway=FakeGateway(),
                )  # no role_model and config default is None
            except ValueError:
                raised = True
            assert raised

    run_async(scenario())


def test_aspect_worker_research_bridges_context(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            source = FakeCommitteeSource(source_key="apollo_people", tier=2, candidates=[_cfo()])

            # The worker opens a connection from the injected factory; hand it the shared rollback
            # connection so all writes stay in the test's transaction (no spec persisted →
            # get_icp_version returns None → discover_committee proceeds with default personas).
            @asynccontextmanager
            async def session_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            worker = CommitteeAspectWorker(
                session_factory=session_factory,
                sources=[source],
                gateway=FakeGateway(),
                role_model="model-x",
            )
            ctx = AspectContext(
                entity_id=account.id,
                campaign_run_id="33333333-3333-3333-3333-333333333333",
                run_id=_RUN,
                tier="top",
                aspect="committee",
                params={"client_id": _TENANT, "icp_key": "default", "icp_version": 1},
            )
            result = await worker.research(ctx)
            assert result.status is WorkerStatus.OK
            assert result.aspect == "committee"
            assert len(result.claim_refs) == 3  # one admitted member × (discovery+role+persona)
            assert result.detail["admitted"] == 1
            # with no ICP spec persisted the worker defaults to all personas; the persona claim is
            # still written with a value in the canonical set.
            scope = TenantScope.for_tenant(_TENANT)
            persona_contacts = await entities_with_field_claim(
                conn, PERSONA, run_id=_RUN, scope=scope
            )
            assert len(persona_contacts) == 1
            persona_claim = (await claims_for(conn, persona_contacts[0], PERSONA, scope=scope))[0]
            assert persona_claim.value_json in {p.value for p in Persona}

    run_async(scenario())


def test_exhausted_stop_reason(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            source = FakeCommitteeSource(
                source_key="apollo_people", tier=2, candidates=[_cfo(), _vp_eng()]
            )
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                tenant_id=_TENANT,
                sources=[source],
                gateway=FakeGateway(),
                role_model="model-x",
            )
            # Single productive source consulted once; no budget/yield stop → tiers exhausted.
            assert result.coverage.stopping_reason is CommitteeStopReason.EXHAUSTED
            assert result.admitted == 2
            assert source.calls == 1

    run_async(scenario())


def test_all_candidates_without_strong_keys_stop_gracefully(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            ghosts = [
                make_candidate(source_url="https://acme.example/team", full_name=f"Ghost {i}")
                for i in range(3)
            ]
            source = FakeCommitteeSource(source_key="apollo_people", tier=2, candidates=ghosts)
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                tenant_id=_TENANT,
                sources=[source],
                gateway=FakeGateway(),
                role_model="model-x",
            )
            assert result.admitted == 0
            assert result.dropped == 3
            assert result.members == ()
            from clue_research.profiling.committee.coverage import CommitteeCoverageConfidence

            assert result.coverage.confidence is CommitteeCoverageConfidence.NONE

    run_async(scenario())


def test_role_fallback_on_unparseable_gateway(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            engineer = make_candidate(
                source_key="apollo_people",
                linkedin_url="https://linkedin.com/in/staff-eng",
                full_name="Sam Engineer",
                title="Staff Software Engineer",
                source_url="https://acme.example/team",
            )
            source = FakeCommitteeSource(source_key="apollo_people", tier=2, candidates=[engineer])
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                tenant_id=_TENANT,
                sources=[source],
                gateway=FakeGateway(reply="stub:deadbeef not json"),  # unparseable → fail-safe
                role_model="model-x",
            )
            assert result.admitted == 1
            member = result.members[0]
            # the title heuristic routes an engineer → technical_evaluator (plausible), low conf.
            assert member.persona is Persona.TECHNICAL_EVALUATOR
            assert member.role_plausible is True
            assert member.role_confidence <= 0.2  # fallback confidence

    run_async(scenario())
