"""C7.6 production committee reader and real HANDOFF cutover.

These DB-gated integration tests exercise the API-root resolver over real identity, account-run
references, claims, use decisions, materialization, and the durable outbox. No in-memory committee
reader participates in the production path under test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import (
    DurableHandoffReadinessReader,
    HandoffPhaseHandler,
    build_contact_eligibility_resolver,
    build_governed_committee_view_reader,
    build_handoff_assembler,
    build_production_handoff_committee_reader,
)
from clue_core import (
    AccountStatus,
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    Persona,
    PhaseContext,
    ProjectPhase,
    ProjectRunId,
    ResearchMode,
    ResearchSubjectRef,
    ResearchViewReadRequest,
    RunId,
    UseClass,
    VerificationStatus,
    account_claim,
    contact_claim,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import insert_claim
from clue_research.compliance import DataSubjectRightsImpl
from clue_research.durable import (
    AccountRunStatus,
    AccountRunSubPhase,
    ensure_project_run,
    insert_account_run,
    save_references,
    set_account_sub_phase,
)
from clue_research.identity import (
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
    stamp_reuse,
)
from clue_research.narrative import (
    NARRATIVE_REUSE_POLICY,
    VALUE_NARRATIVE,
    RecordingHandoffPublisher,
    list_handoff_events,
    load_narrative_pack,
    read_handoff,
)
from clue_research.profiling.committee import (
    CURRENT_TITLE,
    PERSONA,
    ROLE_ON_COMMITTEE,
    load_committee_pack,
)
from clue_research.profiling.fields import FACET_NICKNAME
from clue_spine import create_brand, create_product, create_project
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WORKSPACE = "c7-handoff-ws"
_PRODUCT_A = "prd-c7-a"
_PRODUCT_B = "prd-c7-b"
_ICP_KEY = "enterprise"
_ICP_VERSION = 1
_AT = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


async def _seed_run(
    conn: AsyncConnection,
    *,
    product_id: str = _PRODUCT_A,
) -> tuple[str, ProjectRunId, EntityId, RunId]:
    await seed_workspace(conn, _WORKSPACE)
    brand = await create_brand(conn, workspace_id=_WORKSPACE, name="C7 brand")
    await create_product(
        conn,
        workspace_id=_WORKSPACE,
        brand_id=brand.brand_id,
        product_id=_PRODUCT_A,
        name="Product A",
    )
    await create_product(
        conn,
        workspace_id=_WORKSPACE,
        brand_id=brand.brand_id,
        product_id=_PRODUCT_B,
        name="Product B",
    )
    project = await create_project(
        conn,
        workspace_id=_WORKSPACE,
        brand_id=brand.brand_id,
        product_id=product_id,
        name="C7 project",
    )
    run = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=run,
        project_id=project.project_id,
        workspace_id=_WORKSPACE,
        icp_key=_ICP_KEY,
        icp_version=_ICP_VERSION,
        phase=ProjectPhase.HANDOFF,
    )
    account = await insert_account_entity(
        conn,
        canonical_name="C7 Target",
        primary_domain="c7-target.example",
        status=AccountStatus.ACTIVE,
        workspace_id=_WORKSPACE,
    )
    account_run = new_run_id()
    await insert_account_run(
        conn,
        account_run_id=account_run,
        project_run_id=run,
        entity_id=account,
        tier="top",
    )
    return project.project_id, run, account, account_run


async def _contact(
    conn: AsyncConnection,
    account: EntityId,
    *,
    name: str,
    suffix: str,
) -> EntityId:
    return await insert_contact_entity(
        conn,
        account_entity_id=account,
        full_name=name,
        linkedin_url=f"https://linkedin.com/in/{suffix}",
        status=AccountStatus.ACTIVE,
    )


async def _committee_claim(
    conn: AsyncConnection,
    *,
    contact: EntityId,
    field_key: str,
    value: JsonValue,
    account_run: RunId,
    binding: IdentityBinding,
    product_id: str,
    use_class: UseClass = UseClass.PROFESSIONAL_PUBLIC,
) -> Claim:
    claim = stamp_reuse(
        contact_claim(
            entity_id=contact,
            field_key=field_key,
            value_json=value,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            run_id=account_run,
            research_mode=ResearchMode.COMMITTEE_DISCOVERY,
            identity_binding=binding,
            use_class=use_class,
            evidence_span=f"evidence for {field_key}",
        ),
        workspace_id=_WORKSPACE,
    ).model_copy(
        update={
            "product_id": product_id,
            "verification_status": (
                VerificationStatus.VERIFIED
                if binding is IdentityBinding.STRONG
                else VerificationStatus.UNVERIFIED
            ),
        }
    )
    await insert_claim(conn, claim)
    return claim


async def _member_claims(
    conn: AsyncConnection,
    *,
    contact: EntityId,
    account_run: RunId,
    binding: IdentityBinding = IdentityBinding.STRONG,
    product_id: str = _PRODUCT_A,
    facet_allowed: bool | None = True,
) -> tuple[Claim, ...]:
    role = await _committee_claim(
        conn,
        contact=contact,
        field_key=ROLE_ON_COMMITTEE,
        value={
            "role": Persona.ECONOMIC_BUYER.value,
            "confidence": 1.0,
            "plausible": True,
            "rationale": "budget owner",
        },
        account_run=account_run,
        binding=binding,
        product_id=product_id,
    )
    persona = await _committee_claim(
        conn,
        contact=contact,
        field_key=PERSONA,
        value=Persona.ECONOMIC_BUYER.value,
        account_run=account_run,
        binding=binding,
        product_id=product_id,
    )
    facet = await _committee_claim(
        conn,
        contact=contact,
        field_key=FACET_NICKNAME,
        value="Jay",
        account_run=account_run,
        binding=binding,
        product_id=product_id,
        use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
    )
    if facet_allowed is not None:
        await conn.execute(
            text(
                """
                INSERT INTO use_decision
                    (claim_id, usable_for_outreach, reason, regime, policy_version)
                VALUES
                    (:claim_id, :allowed,
                     CAST(:reason AS use_reason), 'gdpr', 1)
                """
            ),
            {
                "claim_id": str(facet.id),
                "allowed": facet_allowed,
                "reason": ("allowed" if facet_allowed else "use_class_disallowed_for_regime"),
            },
        )
    return role, persona, facet


async def _narrative(
    conn: AsyncConnection,
    *,
    account: EntityId,
    account_run: RunId,
    product_id: str,
) -> Claim:
    claim = stamp_reuse(
        account_claim(
            entity_id=account,
            field_key=VALUE_NARRATIVE,
            value_json={
                "persona": Persona.ECONOMIC_BUYER.value,
                "argument": f"Grounded narrative for {product_id}",
                "angle_label": "roi",
                "icp_spec_version": _ICP_VERSION,
                "icp_key": _ICP_KEY,
                "product_id": product_id,
            },
            source_tier=4,
            extraction_method=ExtractionMethod.LLM_SYNTHESIS,
            confidence=0.9,
            run_id=account_run,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="clue://narrative/positioning",
            evidence_span="account evidence joined to client capability",
        ),
        workspace_id=_WORKSPACE,
        policy=NARRATIVE_REUSE_POLICY,
    ).model_copy(
        update={
            "product_id": product_id,
            "verification_status": VerificationStatus.VERIFIED,
        }
    )
    await insert_claim(conn, claim)
    return claim


async def _ready(
    conn: AsyncConnection,
    *,
    account_run: RunId,
    refs: tuple[Claim, ...],
) -> None:
    await save_references(
        conn,
        account_run,
        references_index={"committee": [str(ref.id) for ref in refs]},
        cost_cents=Decimal(0),
        status=AccountRunStatus.DONE,
    )
    await set_account_sub_phase(conn, account_run, AccountRunSubPhase.CONTACTS_COMPLETE)


def _ctx(project_id: str, run: ProjectRunId) -> PhaseContext:
    return PhaseContext(
        project_run_id=run,
        project_id=project_id,
        brand_id="unused-by-handler",
        phase=ProjectPhase.HANDOFF,
        workspace_id=_WORKSPACE,
        icp_key=_ICP_KEY,
        icp_version=_ICP_VERSION,
    )


def test_real_committee_materializes_narrative_and_c7_references() -> None:
    """Eligible real claims drive M12 and C7; denied hooks display but cannot personalize."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            await load_narrative_pack(conn)
            project_id, run, account, account_run = await _seed_run(conn)
            contact = await _contact(conn, account, name="Jordan Buyer", suffix="jordan-buyer")
            role, persona, denied_facet = await _member_claims(
                conn,
                contact=contact,
                account_run=account_run,
                facet_allowed=False,
            )
            professional_title = await _committee_claim(
                conn,
                contact=contact,
                field_key=CURRENT_TITLE,
                value="VP of Operations",
                account_run=account_run,
                binding=IdentityBinding.STRONG,
                product_id=_PRODUCT_A,
            )
            narrative = await _narrative(
                conn,
                account=account,
                account_run=account_run,
                product_id=_PRODUCT_A,
            )
            await _ready(
                conn,
                account_run=account_run,
                refs=(role, persona, denied_facet, professional_title),
            )

            resolver = build_contact_eligibility_resolver(
                project_run_id=run,
                product_id=_PRODUCT_A,
                conn_factory=_factory(conn),
            )
            governed = await resolver.resolve_account(
                account_entity_id=account,
                workspace_id=_WORKSPACE,
            )
            assert len(governed) == 1
            assert denied_facet.id in {item.claim.id for item in governed[0].display_claims}
            assert professional_title.id in {
                item.claim.id for item in governed[0].display_claims
            }
            assert denied_facet.id not in {
                item.claim.id for item in governed[0].personalization_claims
            }

            reader = build_production_handoff_committee_reader(resolver)
            publisher = RecordingHandoffPublisher()
            handler = HandoffPhaseHandler(
                assembler=build_handoff_assembler(committee_reader=reader),
                readiness_reader=DurableHandoffReadinessReader(conn_factory=_factory(conn)),
                publisher=publisher,
                conn_factory=_factory(conn),
                clock=lambda: _AT,
                product_id=_PRODUCT_A,
            )
            result = await handler.run(_ctx(project_id, run))
            assert result.accounts_processed == 1
            assert result.payload["newly_emitted"] == 1
            assert "narrative_emit_skipped" not in result.payload

            assembled = await read_handoff(
                conn,
                workspace_id=_WORKSPACE,
                account_entity_id=account,
                icp_spec_version=_ICP_VERSION,
                icp_key=_ICP_KEY,
                product_id=_PRODUCT_A,
            )
            assert assembled is not None
            assert [member.contact_entity_id for member in assembled.handoff.committee] == [contact]
            # The member remains visible, but the denied personal hook is absent from the legacy
            # outreach-eligible handoff surface.
            legacy_claim_ids = {
                item.claim_id for item in assembled.handoff.committee[0].profile_claims
            }
            assert {role.id, persona.id, professional_title.id}.issubset(legacy_claim_ids)
            assert denied_facet.id not in legacy_claim_ids
            assert [item.claim_id for item in assembled.handoff.value_narrative] == [narrative.id]
            assert len(publisher.published) == 1

            c7_reader = build_governed_committee_view_reader(resolver)
            c7_seed = await c7_reader.read_committee(
                ResearchViewReadRequest(
                    workspace_id=_WORKSPACE,
                    project_id=project_id,
                    project_run_id=run,
                    subject_entity_id=account,
                    product_id=_PRODUCT_A,
                ),
                ResearchSubjectRef(
                    entity_id=account,
                    entity_type=EntityType.ACCOUNT,
                    canonical_entity_version=1,
                ),
            )
            assert len(c7_seed.references) == 1
            assert c7_seed.references[0].subject.entity_id == contact
            assert c7_seed.references[0].product_id == _PRODUCT_A
            assert set(c7_seed.references[0].evidence_claim_ids) == {
                item.claim.id for item in governed[0].display_claims
            }
            # Legacy and C7 are adapters over one member/product authority. C7 retains the denied
            # claim reference for restricted display; legacy is its outreach-safe subset.
            assert legacy_claim_ids.issubset(set(c7_seed.references[0].evidence_claim_ids))

            # Real-reader re-entry is idempotent: one materialization scope, one event, one push.
            replay = await handler.run(_ctx(project_id, run))
            assert replay.payload["newly_emitted"] == 0
            assert len(publisher.published) == 1
            assert (
                len(
                    await list_handoff_events(
                        conn,
                        project_run_id=run,
                        workspace_id=_WORKSPACE,
                    )
                )
                == 1
            )

    run_async(scenario())


def test_weak_merged_and_erased_contacts_fail_closed() -> None:
    """Weak members are excluded, merged losers redirect, and erasure removes the shared result."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            project_id, run, account, account_run = await _seed_run(conn)
            weak = await _contact(conn, account, name="Weak Person", suffix="weak-person")
            weak_refs = await _member_claims(
                conn,
                contact=weak,
                account_run=account_run,
                binding=IdentityBinding.WEAK,
            )
            loser = await _contact(conn, account, name="Merged Person", suffix="merged-loser")
            survivor = await _contact(
                conn,
                account,
                name="Canonical Person",
                suffix="merged-survivor",
            )
            loser_refs = await _member_claims(
                conn,
                contact=loser,
                account_run=account_run,
            )
            await mark_merged(conn, EntityType.CONTACT, loser, survivor)
            await _ready(conn, account_run=account_run, refs=(*weak_refs, *loser_refs))

            resolver = build_contact_eligibility_resolver(
                project_run_id=run,
                product_id=_PRODUCT_A,
                conn_factory=_factory(conn),
            )
            initial = await resolver.resolve_account(
                account_entity_id=account,
                workspace_id=_WORKSPACE,
            )
            assert [item.contact_entity_id for item in initial] == [survivor]
            assert (
                await resolver.resolve_contact(
                    contact_entity_id=loser,
                    account_entity_id=account,
                    workspace_id=_WORKSPACE,
                )
                == initial[0]
            )

            rights = DataSubjectRightsImpl(
                _WORKSPACE,
                conn_factory=_factory(conn),
            )
            await rights.erase(loser)
            assert (
                await resolver.resolve_account(
                    account_entity_id=account,
                    workspace_id=_WORKSPACE,
                )
                == ()
            )

            # The run still completes honestly with an empty committee; no placeholder marker.
            handler = HandoffPhaseHandler(
                assembler=build_handoff_assembler(
                    committee_reader=build_production_handoff_committee_reader(resolver)
                ),
                readiness_reader=DurableHandoffReadinessReader(conn_factory=_factory(conn)),
                conn_factory=_factory(conn),
                clock=lambda: _AT,
                product_id=_PRODUCT_A,
            )
            result = await handler.run(_ctx(project_id, run))
            assert result.accounts_processed == 1
            assert "narrative_emit_skipped" not in result.payload
            assembled = await read_handoff(
                conn,
                workspace_id=_WORKSPACE,
                account_entity_id=account,
                icp_spec_version=_ICP_VERSION,
                icp_key=_ICP_KEY,
                product_id=_PRODUCT_A,
            )
            assert assembled is not None and assembled.handoff.committee == ()

    run_async(scenario())


def test_product_isolation_and_after_commit_crash_replay() -> None:
    """Product A relevance never enters B; a post-commit publisher crash cannot duplicate outbox."""

    class CrashOncePublisher:
        def __init__(self) -> None:
            self.calls = 0

        async def publish(self, event: object) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated post-commit crash")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            await load_narrative_pack(conn)
            project_id, run, account, account_run = await _seed_run(conn)
            contact = await _contact(conn, account, name="Product A Buyer", suffix="product-a")
            refs = await _member_claims(
                conn,
                contact=contact,
                account_run=account_run,
                product_id=_PRODUCT_A,
            )
            await _narrative(
                conn,
                account=account,
                account_run=account_run,
                product_id=_PRODUCT_A,
            )
            await _ready(conn, account_run=account_run, refs=refs)

            product_b = build_contact_eligibility_resolver(
                project_run_id=run,
                product_id=_PRODUCT_B,
                conn_factory=_factory(conn),
            )
            assert (
                await product_b.resolve_account(
                    account_entity_id=account,
                    workspace_id=_WORKSPACE,
                )
                == ()
            )
            b_reader = build_governed_committee_view_reader(product_b)
            mismatch = await b_reader.read_committee(
                ResearchViewReadRequest(
                    workspace_id=_WORKSPACE,
                    project_id=project_id,
                    project_run_id=run,
                    subject_entity_id=account,
                    product_id=_PRODUCT_A,
                ),
                ResearchSubjectRef(
                    entity_id=account,
                    entity_type=EntityType.ACCOUNT,
                    canonical_entity_version=1,
                ),
            )
            assert mismatch.references == ()
            assert mismatch.reason_codes == ("product_scope_mismatch",)

            # Assembling explicitly for B returns honest emptiness; A's narrative is not inherited.
            b_assembled = await build_handoff_assembler(
                committee_reader=build_production_handoff_committee_reader(product_b)
            ).assemble(
                conn,
                account,
                icp_spec_version=_ICP_VERSION,
                icp_key=_ICP_KEY,
                workspace_id=_WORKSPACE,
                assembled_at=_AT,
                project_run_id=run,
                product_id=_PRODUCT_B,
            )
            assert b_assembled.handoff.committee == ()
            assert b_assembled.handoff.value_narrative == ()

            product_a = build_contact_eligibility_resolver(
                project_run_id=run,
                product_id=_PRODUCT_A,
                conn_factory=_factory(conn),
            )
            crashing = CrashOncePublisher()
            handler = HandoffPhaseHandler(
                assembler=build_handoff_assembler(
                    committee_reader=build_production_handoff_committee_reader(product_a)
                ),
                readiness_reader=DurableHandoffReadinessReader(conn_factory=_factory(conn)),
                publisher=crashing,
                conn_factory=_factory(conn),
                clock=lambda: _AT,
                product_id=_PRODUCT_A,
            )
            with pytest.raises(RuntimeError, match="simulated post-commit crash"):
                await handler.run(_ctx(project_id, run))
            rows = await list_handoff_events(
                conn,
                project_run_id=run,
                workspace_id=_WORKSPACE,
            )
            assert len(rows) == 1
            assert (
                await read_handoff(
                    conn,
                    workspace_id=_WORKSPACE,
                    account_entity_id=account,
                    icp_spec_version=_ICP_VERSION,
                    icp_key=_ICP_KEY,
                    product_id=_PRODUCT_A,
                )
                is not None
            )

            replay = await handler.run(_ctx(project_id, run))
            assert replay.payload["newly_emitted"] == 0
            assert (
                len(
                    await list_handoff_events(
                        conn,
                        project_run_id=run,
                        workspace_id=_WORKSPACE,
                    )
                )
                == 1
            )

    run_async(scenario())
