"""M8.3 committee discovery worker — end-to-end (DB-gated) + AspectWorker conformance.

Exercises the full ``discover_committee`` flow (admit → role-infer → gate → write role/persona) and
the bounded-discovery termination, against fake people-sources + a fake gateway.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AspectContext,
    AspectWorker,
    Completion,
    ExtractionMethod,
    IdentityBinding,
    Message,
    Persona,
    ResearchMode,
    SourceTier,
    UseClass,
    WorkerStatus,
    canonical_json,
    new_claim_id,
    new_entity_id,
)
from clue_research.claimstore import WorkspaceScope, claims_for, entities_with_field_claim
from clue_research.profiling.committee import (
    CURRENT_TITLE,
    PERSONA,
    ROLE_ON_COMMITTEE,
    CandidateFactProvenance,
    CandidateProfessionalFact,
    CommitteeAspectWorker,
    CommitteeConfig,
    CommitteeStoppingConfig,
    discover_committee,
)
from clue_research.profiling.committee.admission import DISCOVERY_PROVENANCE_FIELD
from clue_research.profiling.committee.coverage import (
    CommitteeStopReason,
    estimate_committee_coverage,
)
from clue_research.profiling.committee.results import CommitteeMemberRef, CommitteeResult
from clue_spine import create_brand, create_product
from clue_storage import artifact_key, content_address, record_artifact

from ..conftest import (
    FakeCommitteeSource,
    FakeGateway,
    icp_spec,
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
            brand = await create_brand(conn, workspace_id=_TENANT, name="Acme")
            product = await create_product(
                conn,
                brand_id=brand.brand_id,
                workspace_id=_TENANT,
                name="Product A",
            )
            source = FakeCommitteeSource(
                source_key="apollo_people", tier=2, candidates=[_cfo(), _vp_eng(), _ghost()]
            )
            gateway = FakeGateway()  # returns economic_buyer (plausible for both executives)
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                workspace_id=_TENANT,
                sources=[source],
                gateway=gateway,
                spec=icp_spec(product_id=product.product_id),
                role_model="model-x",
            )

            assert result.admitted == 2
            assert result.dropped == 1
            assert len(result.members) == 2
            assert len(result.claim_refs) == 6  # discovery + role + persona per member
            assert gateway.complete_calls == 2  # role inference per admitted member

            scope = WorkspaceScope.for_workspace(_TENANT)
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
                    assert claim.workspace_id == _TENANT
                    assert claim.product_id == product.product_id
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
                workspace_id=_TENANT,
                sources=[source],
                gateway=gateway,
                role_model="model-x",
            )
            assert result.admitted == 1
            member = result.members[0]
            assert member.role_plausible is False  # flagged
            scope = WorkspaceScope.for_workspace(_TENANT)
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
                workspace_id=_TENANT,
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
                workspace_id=_TENANT,
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
                workspace_id=_TENANT,
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
                    workspace_id=_TENANT,
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
                project_run_id="33333333-3333-3333-3333-333333333333",
                run_id=_RUN,
                tier="top",
                aspect="committee",
                params={"workspace_id": _TENANT, "icp_key": "default", "icp_version": 1},
            )
            result = await worker.research(ctx)
            assert result.status is WorkerStatus.OK
            assert result.aspect == "committee"
            assert len(result.claim_refs) == 3  # one admitted member × (discovery+role+persona)
            assert result.detail["admitted"] == 1
            # with no ICP spec persisted the worker defaults to all personas; the persona claim is
            # still written with a value in the canonical set.
            scope = WorkspaceScope.for_workspace(_TENANT)
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
                workspace_id=_TENANT,
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
                workspace_id=_TENANT,
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


_ARTIFACT_BODY = b"d1 ungrounded-candidate people response"


async def _seed_professional_artifact(conn: AsyncConnection) -> str:
    """Seed the snapshot artifact a professional fact must cite, returning its storage key."""
    digest = content_address(_ARTIFACT_BODY)
    key = artifact_key(_TENANT, digest)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=_TENANT,
        content_sha256=digest,
        media_type="application/json",
        size_bytes=len(_ARTIFACT_BODY),
        source_key="fixture_people",
        source_url="https://sumble.example/fixture_people",
    )
    return key


def _professional_fact(value: JsonValue, *, key: str) -> CandidateProfessionalFact:
    return CandidateProfessionalFact(
        field_key=CURRENT_TITLE,
        value_json=value,
        provenance_kind=CandidateFactProvenance.PROVIDER_RETURNED,
        source_key="fixture_people",
        source_tier=1,
        source_url="https://sumble.example/fixture_people/person-1",
        evidence_span=f"provider_returned {CURRENT_TITLE}: {value}",
        artifact_key=key,
        source_operation_ref="d1-operation:operation-1",
        source_snapshot_ref="d1-snapshot:operation-1:fixture_people:fingerprint-1",
        source_request_ref="d1-request:fixture_people:fingerprint-1",
        confidence=0.9,
    )


async def _committee_claims(
    conn: AsyncConnection, contact_entity_id: UUID, field_key: str
) -> list[object]:
    return list(
        await claims_for(
            conn,
            contact_entity_id,
            field_key,
            scope=WorkspaceScope.for_workspace(_TENANT),
        )
    )


def test_ungrounded_candidate_gets_no_role_or_persona_claim(require_profiling_db: None) -> None:
    """A candidate with a title but no grounding URL writes NO role/persona claim.

    The role is an LLM judgment; without a grounding URL a tier-4 claim is unconstructible (the
    frozen ``core.Claim`` validator requires a ``source_url`` for ``llm_synthesis``). The old code
    fell back to ``HUMAN``/tier-1 — stamping an agent guess as a human-asserted fact. Contract §5.2:
    that false human provenance is forbidden, so the role/persona pair is honestly absent while the
    member itself survives via its discovery + professional-fact claims."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            key = await _seed_professional_artifact(conn)
            # verified_email is a strong key (admitted), but there is NO grounding URL:
            # no source_url and no linkedin_url.
            emailed = make_candidate(
                source_key="apollo_people",
                verified_email="jane.cfo@acme.example",
                full_name="Jane CFO",
                title="Chief Financial Officer",
                professional_facts=(_professional_fact("Chief Financial Officer", key=key),),
            )
            source = FakeCommitteeSource(source_key="apollo_people", tier=2, candidates=[emailed])
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                workspace_id=_TENANT,
                sources=[source],
                gateway=FakeGateway(),
                role_model="model-x",
            )

            assert result.admitted == 1  # the existence gate admitted a real person
            assert result.dropped == 0

            scope = WorkspaceScope.for_workspace(_TENANT)
            contacts = await entities_with_field_claim(
                conn, DISCOVERY_PROVENANCE_FIELD, run_id=_RUN, scope=scope
            )
            assert len(contacts) == 1  # the member survives — its discovery claim exists
            contact_id = contacts[0]

            assert await _committee_claims(conn, contact_id, ROLE_ON_COMMITTEE) == []
            assert await _committee_claims(conn, contact_id, PERSONA) == []
            # ...but the professional facts are materialized exactly as before.
            titles = await _committee_claims(conn, contact_id, CURRENT_TITLE)
            assert len(titles) == 1

    run_async(scenario())


def test_titleless_candidate_gets_no_role_or_persona_claim(require_profiling_db: None) -> None:
    """A candidate with a grounding URL but no title also writes NO role/persona claim.

    A tier-4 claim with a null ``evidence_span`` can never be promoted (``core.can_be_promoted``),
    and the title IS the evidence span for a role judgment — so a title-less candidate has nothing
    to ground the inference on. Honestly empty beats a HUMAN-stamped guess."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            for title in (None, "   "):
                blank = make_candidate(
                    source_key="apollo_people",
                    linkedin_url=f"https://linkedin.com/in/no-title-{title!r}",
                    full_name="Nameless Role",
                    title=title,
                    source_url="https://acme.example/team",
                )
                source = FakeCommitteeSource(source_key="apollo_people", tier=2, candidates=[blank])
                result = await discover_committee(
                    conn,
                    account_entity_id=account.id,
                    run_id=_RUN,
                    workspace_id=_TENANT,
                    sources=[source],
                    gateway=FakeGateway(),
                    role_model="model-x",
                )
                assert result.admitted == 1
                assert result.dropped == 0

            scope = WorkspaceScope.for_workspace(_TENANT)
            contacts = await entities_with_field_claim(
                conn, DISCOVERY_PROVENANCE_FIELD, run_id=_RUN, scope=scope
            )
            assert len(contacts) == 2  # both members survive via their discovery claims
            for contact_id in contacts:
                assert await _committee_claims(conn, contact_id, ROLE_ON_COMMITTEE) == []
                assert await _committee_claims(conn, contact_id, PERSONA) == []

    run_async(scenario())


def test_no_committee_claim_is_ever_stamped_human(require_profiling_db: None) -> None:
    """Across a mixed run (grounded + ungrounded members), ``ExtractionMethod.HUMAN`` never
    appears — no code path in the committee worker may manufacture human provenance."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            key = await _seed_professional_artifact(conn)
            candidates = [
                _cfo(),  # grounded: url + title
                make_candidate(  # ungrounded: no url
                    source_key="apollo_people",
                    verified_email="pat.ops@acme.example",
                    full_name="Pat Ops",
                    title="VP of Operations",
                    professional_facts=(_professional_fact("VP of Operations", key=key),),
                ),
                make_candidate(  # grounded url, no title
                    source_key="apollo_people",
                    linkedin_url="https://linkedin.com/in/untitled",
                    full_name="Untitled Person",
                    source_url="https://acme.example/team",
                ),
                _ghost(),  # dropped at the gate
            ]
            source = FakeCommitteeSource(source_key="apollo_people", tier=2, candidates=candidates)
            await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                workspace_id=_TENANT,
                sources=[source],
                gateway=FakeGateway(),
                role_model="model-x",
            )

            scope = WorkspaceScope.for_workspace(_TENANT)
            contacts = await entities_with_field_claim(
                conn, DISCOVERY_PROVENANCE_FIELD, run_id=_RUN, scope=scope
            )
            assert len(contacts) == 3
            seen = 0
            for contact_id in contacts:
                for field_key in (
                    DISCOVERY_PROVENANCE_FIELD,
                    ROLE_ON_COMMITTEE,
                    PERSONA,
                    CURRENT_TITLE,
                ):
                    for claim in await claims_for(conn, contact_id, field_key, scope=scope):
                        seen += 1
                        assert claim.extraction_method is not ExtractionMethod.HUMAN
            assert seen > 0  # the assertion above actually ran over real claims

    run_async(scenario())


def test_grounded_candidate_keeps_tier4_llm_synthesis_provenance(
    require_profiling_db: None,
) -> None:
    """The kept path is unchanged: a candidate with BOTH a grounding URL and a title still gets
    tier-4 ``llm_synthesis`` role/persona claims spanned on its title.

    (``test_professional_materialization_c1.py`` asserts the extraction method too; this pins the
    full tuple — method, tier, span and url — so the surviving branch cannot silently drift.)"""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            source = FakeCommitteeSource(source_key="apollo_people", tier=2, candidates=[_cfo()])
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                workspace_id=_TENANT,
                sources=[source],
                gateway=FakeGateway(),
                role_model="model-x",
            )
            assert len(result.members) == 1
            member = result.members[0]
            scope = WorkspaceScope.for_workspace(_TENANT)
            for field_key in (ROLE_ON_COMMITTEE, PERSONA):
                claims = await claims_for(conn, member.contact_entity_id, field_key, scope=scope)
                assert len(claims) == 1
                claim = claims[0]
                assert claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
                assert claim.source_tier == SourceTier(4)
                assert claim.source_url == "https://acme.example/team"
                assert claim.evidence_span == "title: Chief Financial Officer"

    run_async(scenario())


_ROLE_FIELD_NAMES = (
    "persona",
    "role_on_committee",
    "role_confidence",
    "role_plausible",
    "role_claim_id",
    "persona_claim_id",
)


@dataclass
class RecordingGateway(FakeGateway):
    """``FakeGateway`` + the prompts it saw, so a test can prove *which* candidate a call was for.

    ``complete_calls`` alone proves how many role inferences ran; ``prompts`` proves the ungrounded
    candidate's title never reached the model (D2: the ungrounded branch spends nothing)."""

    prompts: list[str] = field(default_factory=list)

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.prompts.append(messages[-1].content)
        return super().complete(model=model, messages=messages, **opts)


def _emailed_vp(email: str = "pat.ops@acme.example", *, key: str) -> object:
    """An ungrounded candidate: a strong key (verified email) but NO grounding URL, so it can never
    carry a tier-4 agent-derived role — plus one professional fact so its survival is observable."""
    return make_candidate(
        source_key="apollo_people",
        verified_email=email,
        full_name="Pat Ops",
        title="VP of Operations",
        professional_facts=(_professional_fact("VP of Operations", key=key),),
    )


def _is_roleless(member: object) -> bool:
    return all(getattr(member, name) is None for name in _ROLE_FIELD_NAMES)


def _has_full_role(member: object) -> bool:
    return all(getattr(member, name) is not None for name in _ROLE_FIELD_NAMES)


async def _discovery_and_professional_fingerprints(
    conn: AsyncConnection, run_id: UUID
) -> set[tuple[object, ...]]:
    """Every discovery-provenance + professional-fact claim written in ``run_id``, keyed on content
    (never on entity/claim ids, which differ between two independent runs)."""
    scope = WorkspaceScope.for_workspace(_TENANT)
    contacts = await entities_with_field_claim(
        conn, DISCOVERY_PROVENANCE_FIELD, run_id=run_id, scope=scope
    )
    fingerprints: set[tuple[object, ...]] = set()
    for contact_id in contacts:
        for field_key in (DISCOVERY_PROVENANCE_FIELD, CURRENT_TITLE):
            for claim in await claims_for(conn, contact_id, field_key, scope=scope):
                fingerprints.add(
                    (
                        claim.field_key,
                        canonical_json(claim.value_json),
                        claim.source_url,
                        claim.evidence_span,
                        claim.extraction_method,
                        int(claim.source_tier),
                        claim.source_key,
                    )
                )
    return fingerprints


def test_agent_deferred_mode_discovers_without_any_role_work(require_profiling_db: None) -> None:
    """``role_inference="agent_deferred"`` discovers + identity-resolves and stops there.

    Contract §5.2 steps 1-2: discovery/identity is the worker's job, the role judgment is the
    account agent's (D3 writes it back). So the deferred run makes ZERO gateway calls, writes no
    role/persona claim at all, and every admitted member — grounded or not — is returned with its
    six role fields absent and counted in ``needs_review``."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            key = await _seed_professional_artifact(conn)
            candidates = [_cfo(), _emailed_vp(key=key)]  # grounded + ungrounded
            source = FakeCommitteeSource(source_key="apollo_people", tier=2, candidates=candidates)
            gateway = RecordingGateway()
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                workspace_id=_TENANT,
                sources=[source],
                gateway=gateway,
                role_model="model-x",
                role_inference="agent_deferred",
            )

            assert result.admitted == 2
            assert result.dropped == 0
            assert len(result.members) == 2
            # No role judgment happened anywhere — not for the grounded candidate either.
            assert gateway.complete_calls == 0
            assert gateway.prompts == []
            assert all(_is_roleless(member) for member in result.members)
            assert result.needs_review == len(result.members) == 2

            scope = WorkspaceScope.for_workspace(_TENANT)
            for member in result.members:
                assert (
                    await _committee_claims(conn, member.contact_entity_id, ROLE_ON_COMMITTEE) == []
                )
                assert await _committee_claims(conn, member.contact_entity_id, PERSONA) == []
                # ...while the member's own discovery claim is durable and referenced.
                discovery = await claims_for(
                    conn, member.contact_entity_id, DISCOVERY_PROVENANCE_FIELD, scope=scope
                )
                assert [claim.id for claim in discovery] == [member.discovery_claim_id]
                assert member.discovery_claim_id in result.claim_refs
            # the ungrounded member's professional fact is materialized and referenced too.
            professional = [
                claim_id for member in result.members for claim_id in member.professional_claim_ids
            ]
            assert len(professional) == 1
            assert professional[0] in result.claim_refs
            assert result.committee() == ()  # nothing is handoff-shaped without a role

    run_async(scenario())


def test_agent_deferred_writes_the_same_discovery_and_professional_claims(
    require_profiling_db: None,
) -> None:
    """Deferred mode changes only the role layer: the discovery-provenance + professional-fact
    claims it writes are byte-for-byte what ``worker_llm`` mode writes for the same candidates."""

    async def run_mode(mode: str, run_id: UUID) -> set[tuple[object, ...]]:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            key = await _seed_professional_artifact(conn)
            source = FakeCommitteeSource(
                source_key="apollo_people", tier=2, candidates=[_cfo(), _emailed_vp(key=key)]
            )
            await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=run_id,
                workspace_id=_TENANT,
                sources=[source],
                gateway=FakeGateway(),
                role_model="model-x",
                role_inference=mode,  # type: ignore[arg-type]
            )
            return await _discovery_and_professional_fingerprints(conn, run_id)

    async def scenario() -> None:
        deferred = await run_mode("agent_deferred", _RUN)
        worker_llm = await run_mode("worker_llm", _RUN)
        assert deferred == worker_llm
        assert len(deferred) == 3  # two discovery claims + the ungrounded member's title fact

    run_async(scenario())


def test_worker_llm_mode_admits_an_ungrounded_member_without_role_fields(
    require_profiling_db: None,
) -> None:
    """An ungrounded candidate is now *representable*: it enters ``members`` with its role fields
    absent instead of vanishing (D1's temporary skip), spends nothing on a role it can never write,
    and keeps its claim ids in ``claim_refs`` — while its grounded neighbour is untouched."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            key = await _seed_professional_artifact(conn)
            source = FakeCommitteeSource(
                source_key="apollo_people", tier=2, candidates=[_cfo(), _emailed_vp(key=key)]
            )
            gateway = RecordingGateway()
            result = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                workspace_id=_TENANT,
                sources=[source],
                gateway=gateway,
                role_model="model-x",
            )

            assert result.admitted == 2
            assert len(result.members) == 2
            grounded = [member for member in result.members if _has_full_role(member)]
            roleless = [member for member in result.members if _is_roleless(member)]
            assert len(grounded) == 1
            assert len(roleless) == 1
            assert result.needs_review == 1

            # The grounded neighbour still gets exactly one role inference; the ungrounded
            # candidate's title never reaches the model (no verdict computed and discarded).
            assert gateway.complete_calls == 1
            assert any("Chief Financial Officer" in prompt for prompt in gateway.prompts)
            assert not any("VP of Operations" in prompt for prompt in gateway.prompts)

            member = roleless[0]
            assert await _committee_claims(conn, member.contact_entity_id, ROLE_ON_COMMITTEE) == []
            assert await _committee_claims(conn, member.contact_entity_id, PERSONA) == []
            assert member.discovery_claim_id in result.claim_refs
            assert len(member.professional_claim_ids) == 1
            assert member.professional_claim_ids[0] in result.claim_refs
            # the handoff committee carries the role-tagged member only.
            assert len(result.committee()) == 1
            assert result.committee()[0].contact_entity_id == grounded[0].contact_entity_id

    run_async(scenario())


def _full_role_member() -> CommitteeMemberRef:
    return CommitteeMemberRef(
        contact_entity_id=new_entity_id(),
        persona=Persona.ECONOMIC_BUYER,
        role_on_committee=Persona.ECONOMIC_BUYER.value,
        role_confidence=0.9,
        role_plausible=True,
        discovery_claim_id=new_claim_id(),
        role_claim_id=new_claim_id(),
        persona_claim_id=new_claim_id(),
    )


def _roleless_member() -> CommitteeMemberRef:
    return CommitteeMemberRef(
        contact_entity_id=new_entity_id(),
        discovery_claim_id=new_claim_id(),
        professional_claim_ids=(new_claim_id(),),
    )


def test_member_role_fields_are_all_or_none() -> None:
    """A half-role member is unrepresentable: either the full role set or none of it.

    A partial mix would be a member that carries, say, a persona with no claim id behind it — a
    role assertion with no provenance, which is exactly what the contract forbids."""
    assert _full_role_member().persona is Persona.ECONOMIC_BUYER
    assert _roleless_member().persona is None

    with pytest.raises(ValidationError, match="all-or-none"):
        CommitteeMemberRef(
            contact_entity_id=new_entity_id(),
            persona=Persona.CHAMPION,  # a persona with no role claim behind it
            discovery_claim_id=new_claim_id(),
        )
    with pytest.raises(ValidationError, match="all-or-none"):
        CommitteeMemberRef(
            contact_entity_id=new_entity_id(),
            role_claim_id=new_claim_id(),  # a claim id with no role
            discovery_claim_id=new_claim_id(),
        )


def test_handoff_projection_covers_role_carrying_members_only() -> None:
    """``committee()`` is the handoff shape (persona required), so it yields role-carrying members
    only; projecting a roleless member is a loud programming error, never a fabricated persona."""
    full = _full_role_member()
    roleless = _roleless_member()
    result = CommitteeResult(
        account_entity_id=new_entity_id(),
        members=(full, roleless),
        coverage=estimate_committee_coverage(
            channels_searched=["apollo_people"],
            all_channels=["apollo_people"],
            stopping_reason=CommitteeStopReason.EXHAUSTED,
            candidates_seen=2,
            admitted=2,
        ),
        admitted=2,
        needs_review=1,
    )
    projected = result.committee()
    assert len(projected) == 1
    assert projected[0].contact_entity_id == full.contact_entity_id
    assert projected[0].persona is Persona.ECONOMIC_BUYER
    # both members' discovery + professional claims stay in the reference index.
    assert full.discovery_claim_id in result.claim_refs
    assert roleless.discovery_claim_id in result.claim_refs
    assert roleless.professional_claim_ids[0] in result.claim_refs
    assert full.role_claim_id in result.claim_refs
    assert None not in result.claim_refs

    with pytest.raises(ValueError, match="role"):
        roleless.as_committee_member()


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
                workspace_id=_TENANT,
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
