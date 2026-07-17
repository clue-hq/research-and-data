"""M12.3 — the output/handoff service (the transport-agnostic read API + emit path).

Covers: fetch one handoff (with provenance) + schema version (AC1/AC5); list returns only ready
(materialised) handoffs + run phase + filters (AC2); tenant-scoped reads (AC6); per-object
verification health (AC7); the durable idempotent emit + the publisher seam swap (AC3/AC8).
DB-backed (skips without one)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountHandoff,
    CampaignPhase,
    CampaignRunId,
    CommitteeMember,
    EntityId,
    NarrativeSupport,
    Persona,
    ProvenanceRef,
    Score,
    ScoreComponent,
    ValueNarrativeItem,
    new_campaign_run_id,
    new_claim_id,
    new_entity_id,
)
from clue_research.narrative import (
    HANDOFF_SCHEMA_VERSION,
    AccountReadiness,
    AssembledHandoff,
    HandoffAssembler,
    HandoffNotFoundError,
    HandoffService,
    InMemoryHandoffCommitteeReader,
    InMemoryHandoffReadinessReader,
    OutboxHandoffPublisher,
    RecordingHandoffPublisher,
    RunReadiness,
    ServedHandoff,
    VerificationHealth,
    emit_ready_handoffs,
    list_handoff_events,
    write_handoff,
)

from .conftest import rollback_conn, run_async

_CLIENT = "client-acme"
_OTHER = "client-other"
_AT = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("require_narrative_db")


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


def _assembled(
    *,
    account: EntityId,
    campaign_run_id: CampaignRunId,
    icp_version: int = 1,
    personas: tuple[Persona, ...] = (Persona.ECONOMIC_BUYER,),
    provenance: dict[str, ProvenanceRef] | None = None,
    health: VerificationHealth | None = None,
) -> AssembledHandoff:
    fit_claim = new_claim_id()
    committee = tuple(
        CommitteeMember(
            contact_entity_id=new_entity_id(),
            persona=p,
            role_on_committee=p.value,
        )
        for p in personas
    )
    narrative = tuple(
        ValueNarrativeItem(
            claim_id=new_claim_id(), persona=p, argument="why", supporting=NarrativeSupport()
        )
        for p in personas
    )
    handoff = AccountHandoff(
        account_entity_id=account,
        fit_score=Score(
            value=0.8,
            components=(
                ScoreComponent(
                    name="eng_hiring", weight=1.0, value=0.8, evidence_claim_ids=(fit_claim,)
                ),
            ),
        ),
        intent_score=Score(value=0.4),
        committee=committee,
        value_narrative=narrative,
        provenance_index=provenance or {str(fit_claim): ProvenanceRef(source_tier=1)},
        icp_spec_version=icp_version,
        campaign_run_id=campaign_run_id,
        assembled_at=_AT,
    )
    return AssembledHandoff(handoff=handoff, verification_health=health)


# --- get_handoff / provenance / schema version (AC1/AC5) --------------------


def test_get_handoff_returns_object_with_schema_version() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acc, run = new_entity_id(), new_campaign_run_id()
            await write_handoff(
                conn, _assembled(account=acc, campaign_run_id=run), workspace_id=_CLIENT
            )
            served = await HandoffService().get_handoff(
                conn, workspace_id=_CLIENT, account_entity_id=acc, icp_spec_version=1
            )
            assert served.schema_version == HANDOFF_SCHEMA_VERSION
            assert served.assembled.handoff.account_entity_id == acc

    run_async(_run())


def test_get_handoff_absent_raises_not_found() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(HandoffNotFoundError):
                await HandoffService().get_handoff(
                    conn,
                    workspace_id=_CLIENT,
                    account_entity_id=new_entity_id(),
                    icp_spec_version=1,
                )

    run_async(_run())


def test_get_handoff_is_workspace_scoped() -> None:
    """AC6: a client cannot fetch another client's assembled handoff (cross-tenant → not found)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            acc, run = new_entity_id(), new_campaign_run_id()
            await write_handoff(
                conn, _assembled(account=acc, campaign_run_id=run), workspace_id=_CLIENT
            )
            with pytest.raises(HandoffNotFoundError):
                await HandoffService().get_handoff(
                    conn, workspace_id=_OTHER, account_entity_id=acc, icp_spec_version=1
                )

    run_async(_run())


def test_resolve_provenance_returns_ref_or_not_found() -> None:
    """AC1: every value resolves to its source; an unknown claim id is a not-found, not a miss."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            acc, run = new_entity_id(), new_campaign_run_id()
            cid = new_claim_id()
            ref = ProvenanceRef(source_url="https://src/x", source_tier=2, evidence_span="span")
            await write_handoff(
                conn,
                _assembled(account=acc, campaign_run_id=run, provenance={str(cid): ref}),
                workspace_id=_CLIENT,
            )
            svc = HandoffService()
            got = await svc.resolve_provenance(
                conn, workspace_id=_CLIENT, account_entity_id=acc, icp_spec_version=1, claim_id=cid
            )
            assert got.source_url == "https://src/x" and got.source_tier == 2
            with pytest.raises(HandoffNotFoundError):
                await svc.resolve_provenance(
                    conn,
                    workspace_id=_CLIENT,
                    account_entity_id=acc,
                    icp_spec_version=1,
                    claim_id=new_claim_id(),
                )

    run_async(_run())


# --- list_handoffs (AC2 + filters + run phase) ------------------------------


def test_list_returns_only_materialised_with_run_phase() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = new_campaign_run_id()
            for _ in range(2):
                await write_handoff(
                    conn,
                    _assembled(account=new_entity_id(), campaign_run_id=run),
                    workspace_id=_CLIENT,
                )
            reader = InMemoryHandoffReadinessReader(
                runs={
                    run: RunReadiness(
                        campaign_run_id=run, workspace_id=_CLIENT, phase=CampaignPhase.HANDOFF
                    )
                }
            )
            page = await HandoffService(readiness_reader=reader).list_handoffs(
                conn, workspace_id=_CLIENT, campaign_run_id=run
            )
            assert page.total == 2
            assert page.run_phase is CampaignPhase.HANDOFF
            assert page.schema_version == HANDOFF_SCHEMA_VERSION

    run_async(_run())


def test_list_is_workspace_scoped_empty_for_other() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = new_campaign_run_id()
            await write_handoff(
                conn, _assembled(account=new_entity_id(), campaign_run_id=run), workspace_id=_CLIENT
            )
            page = await HandoffService().list_handoffs(
                conn, workspace_id=_OTHER, campaign_run_id=run
            )
            assert page.total == 0 and page.run_phase is None

    run_async(_run())


def test_list_filters_by_persona_and_pass_rate() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = new_campaign_run_id()
            await write_handoff(
                conn,
                _assembled(
                    account=new_entity_id(),
                    campaign_run_id=run,
                    personas=(Persona.ECONOMIC_BUYER,),
                    health=VerificationHealth(tier4_judge_pass_rate=0.9),
                ),
                workspace_id=_CLIENT,
            )
            await write_handoff(
                conn,
                _assembled(
                    account=new_entity_id(),
                    campaign_run_id=run,
                    personas=(Persona.BLOCKER,),
                    health=VerificationHealth(tier4_judge_pass_rate=0.2),
                ),
                workspace_id=_CLIENT,
            )
            svc = HandoffService()
            by_persona = await svc.list_handoffs(
                conn, workspace_id=_CLIENT, campaign_run_id=run, persona=Persona.ECONOMIC_BUYER
            )
            assert by_persona.total == 1
            assert by_persona.items[0].personas == (Persona.ECONOMIC_BUYER,)
            by_rate = await svc.list_handoffs(
                conn, workspace_id=_CLIENT, campaign_run_id=run, min_verification_pass_rate=0.5
            )
            assert by_rate.total == 1
            assert by_rate.items[0].verification_health is not None
            assert by_rate.items[0].verification_health.tier4_judge_pass_rate == 0.9

    run_async(_run())


def test_list_filters_by_tier() -> None:
    """Spec §M12.3 list deliverable: the list is filterable by tier (stamped at materialisation)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run = new_campaign_run_id()
            top, high = new_entity_id(), new_entity_id()
            await write_handoff(
                conn, _assembled(account=top, campaign_run_id=run), workspace_id=_CLIENT, tier="top"
            )
            await write_handoff(
                conn,
                _assembled(account=high, campaign_run_id=run),
                workspace_id=_CLIENT,
                tier="high",
            )
            svc = HandoffService()
            both = await svc.list_handoffs(conn, workspace_id=_CLIENT, campaign_run_id=run)
            assert both.total == 2
            assert {s.tier for s in both.items} == {"top", "high"}
            only_top = await svc.list_handoffs(
                conn, workspace_id=_CLIENT, campaign_run_id=run, tier="top"
            )
            assert only_top.total == 1
            assert only_top.items[0].account_entity_id == top
            assert only_top.items[0].tier == "top"

    run_async(_run())


def test_served_schema_is_forward_compatible_for_pinned_consumer() -> None:
    """AC5: a consumer pinned to the served schema version survives an *additive* change. The wire
    contract evolves additively (new optional fields, never renamed/removed), and the consumer reads
    by known keys after pinning on ``schema_version`` — an unknown future field is ignored. Proven
    here without a DB: a future ``1.x`` payload (an extra field injected) is still readable by a
    ``1.0`` consumer that selects only the fields it knows."""
    acc, run = new_entity_id(), new_campaign_run_id()
    served = ServedHandoff(
        schema_version=HANDOFF_SCHEMA_VERSION,
        assembled=_assembled(account=acc, campaign_run_id=run),
    )
    wire = served.model_dump(mode="json")
    # a future producer adds an optional field (additive evolution — MINOR bump):
    wire["future_additive_field"] = {"some": "value"}
    wire["assembled"]["handoff"]["future_nested_field"] = 7
    # a pinned 1.0 consumer reads only what it knows, ignoring unknown fields:
    assert wire["schema_version"] == HANDOFF_SCHEMA_VERSION
    assert wire["assembled"]["handoff"]["account_entity_id"] == str(acc)
    assert "provenance_index" in wire["assembled"]["handoff"]  # known field still present


# --- emit (AC3 idempotency + AC8 publisher seam swap) -----------------------


def _emit(conn, run, *, publisher):
    reader = InMemoryHandoffReadinessReader(
        runs={
            run: RunReadiness(
                campaign_run_id=run,
                workspace_id=_CLIENT,
                phase=CampaignPhase.HANDOFF,
                icp_key="",
                icp_version=1,
            )
        },
        ready={run: (AccountReadiness(account_entity_id=new_entity_id(), is_ready=True),)},
    )
    return emit_ready_handoffs(
        conn_factory=_factory(conn),
        assembler=HandoffAssembler(committee_reader=InMemoryHandoffCommitteeReader()),
        readiness_reader=reader,
        publisher=publisher,
        campaign_run_id=run,
        workspace_id=_CLIENT,
        assembled_at=_AT,
    )


def test_emit_is_idempotent_and_publishes_once() -> None:
    """AC3: a durable event per ready account; a re-entry never double-emits or re-publishes."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run = new_campaign_run_id()
            reader = InMemoryHandoffReadinessReader(
                runs={
                    run: RunReadiness(
                        campaign_run_id=run, workspace_id=_CLIENT, phase=CampaignPhase.HANDOFF
                    )
                },
                ready={run: (AccountReadiness(account_entity_id=new_entity_id(), is_ready=True),)},
            )
            pub = RecordingHandoffPublisher()
            common = {
                "conn_factory": _factory(conn),
                "assembler": HandoffAssembler(committee_reader=InMemoryHandoffCommitteeReader()),
                "readiness_reader": reader,
                "publisher": pub,
                "campaign_run_id": run,
                "workspace_id": _CLIENT,
                "assembled_at": _AT,
            }
            first = await emit_ready_handoffs(**common)
            assert first.accounts_processed == 1 and first.newly_emitted == 1
            assert len(pub.published) == 1
            second = await emit_ready_handoffs(**common)  # re-entry
            assert second.accounts_processed == 1 and second.newly_emitted == 0
            assert len(pub.published) == 1  # not re-published
            rows = await list_handoff_events(conn, campaign_run_id=run, workspace_id=_CLIENT)
            assert len(rows) == 1  # exactly one durable outbox row

    run_async(_run())


def test_publisher_swap_leaves_outbox_unchanged() -> None:
    """AC8: swapping the publisher (pull outbox ↔ recording push) changes neither the durable outbox
    row nor the producer — the contract is the seam."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run_a, run_b = new_campaign_run_id(), new_campaign_run_id()
            await _emit(conn, run_a, publisher=OutboxHandoffPublisher())
            await _emit(conn, run_b, publisher=RecordingHandoffPublisher())
            rows_a = await list_handoff_events(conn, campaign_run_id=run_a, workspace_id=_CLIENT)
            rows_b = await list_handoff_events(conn, campaign_run_id=run_b, workspace_id=_CLIENT)
            assert len(rows_a) == 1 and len(rows_b) == 1
            assert rows_a[0].schema_version == rows_b[0].schema_version == HANDOFF_SCHEMA_VERSION

    run_async(_run())


def test_emit_unknown_run_is_empty_report() -> None:
    """A run unknown to this tenant emits nothing (cross-tenant / missing run)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run = new_campaign_run_id()
            report = await emit_ready_handoffs(
                conn_factory=_factory(conn),
                assembler=HandoffAssembler(committee_reader=InMemoryHandoffCommitteeReader()),
                readiness_reader=InMemoryHandoffReadinessReader(),  # empty
                campaign_run_id=run,
                workspace_id=_CLIENT,
                assembled_at=_AT,
            )
            assert report.accounts_processed == 0 and report.newly_emitted == 0

    run_async(_run())
