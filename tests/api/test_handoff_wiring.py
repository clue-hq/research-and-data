"""M12.3 — the api-root handoff wiring: the durable-backed readiness reader + the HANDOFF phase
handler (the emit driver).

Exercises the production seams over **real** ``campaign_run`` / ``account_run`` rows: the readiness
reader maps the run phase + ICP coords and filters ready accounts (status DONE + sub_phase
CONTACTS_COMPLETE), is tenant-scoped, and the phase handler assembles + materialises + emits a
durable ``handoff_event`` per ready account, idempotently (a re-entered phase never double-emits).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.api import (
    DurableHandoffReadinessReader,
    HandoffPhaseHandler,
    build_handoff_service,
)
from clue_research.core import (
    AccountStatus,
    CampaignPhase,
    CampaignRunId,
    EntityId,
    PhaseContext,
    PhaseStatus,
    new_campaign_run_id,
    new_run_id,
)
from clue_research.durable import (
    AccountRunStatus,
    AccountRunSubPhase,
    ensure_campaign_run,
    insert_account_run,
    list_account_runs,
    set_account_sub_phase,
    set_status,
)
from clue_research.identity import insert_account_entity
from clue_research.narrative import (
    HandoffAssembler,
    HandoffService,
    InMemoryHandoffCommitteeReader,
    RecordingHandoffPublisher,
    list_handoff_events,
)
from clue_research.review import ensure_review_session, finalize_review_session
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

_CLIENT = "client-acme"
_OTHER = "client-other"
_ICP_KEY = "enterprise"
_ICP_VERSION = 1
_AT = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


async def _account(conn: AsyncConnection, name: str) -> EntityId:
    return await insert_account_entity(
        conn, canonical_name=name, primary_domain=f"{name}.com", status=AccountStatus.ACTIVE
    )


async def _seed_run(conn: AsyncConnection, *, client: str = _CLIENT) -> CampaignRunId:
    run = new_campaign_run_id()
    await ensure_campaign_run(
        conn,
        campaign_run_id=run,
        client_id=client,
        icp_key=_ICP_KEY,
        icp_version=_ICP_VERSION,
        phase=CampaignPhase.HANDOFF,
    )
    return run


async def _add_account_run(
    conn: AsyncConnection,
    *,
    run: CampaignRunId,
    entity: EntityId,
    status: AccountRunStatus,
    sub_phase: AccountRunSubPhase | None,
) -> None:
    arid = new_run_id()
    await insert_account_run(
        conn, account_run_id=arid, campaign_run_id=run, entity_id=entity, tier="top"
    )
    await set_status(conn, arid, status)
    if sub_phase is not None:
        await set_account_sub_phase(conn, arid, sub_phase)


def test_run_readiness_maps_phase_and_is_tenant_scoped() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn)
            reader = DurableHandoffReadinessReader(conn_factory=_factory(conn))
            rr = await reader.run_readiness(campaign_run_id=run, client_id=_CLIENT)
            assert rr is not None
            assert rr.phase is CampaignPhase.HANDOFF
            assert rr.icp_key == _ICP_KEY and rr.icp_version == _ICP_VERSION
            assert rr.is_terminal is False  # ACTIVE
            # cross-tenant: another client cannot see the run
            assert await reader.run_readiness(campaign_run_id=run, client_id=_OTHER) is None

    run_async(_run())


def test_ready_accounts_filters_to_m12_ready() -> None:
    """Only ``status=DONE`` AND ``sub_phase=CONTACTS_COMPLETE`` accounts are handoff-ready (AC2)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn)
            done = await _account(conn, "ready")
            running = await _account(conn, "running")
            done_no_subphase = await _account(conn, "donebutearly")
            await _add_account_run(
                conn,
                run=run,
                entity=done,
                status=AccountRunStatus.DONE,
                sub_phase=AccountRunSubPhase.CONTACTS_COMPLETE,
            )
            await _add_account_run(
                conn, run=run, entity=running, status=AccountRunStatus.RUNNING, sub_phase=None
            )
            await _add_account_run(
                conn,
                run=run,
                entity=done_no_subphase,
                status=AccountRunStatus.DONE,
                sub_phase=AccountRunSubPhase.ACCOUNT_PROFILED,
            )
            assert len(await list_account_runs(conn, run)) == 3
            reader = DurableHandoffReadinessReader(conn_factory=_factory(conn))
            ready = await reader.ready_accounts(campaign_run_id=run, client_id=_CLIENT)
            assert {r.account_entity_id for r in ready} == {done}
            assert all(r.is_ready for r in ready)
            # cross-tenant: no ready accounts for another client
            assert await reader.ready_accounts(campaign_run_id=run, client_id=_OTHER) == ()

    run_async(_run())


def test_require_finalized_review_gates_handoff_readiness() -> None:
    """M13.1 gate: with ``require_finalized_review=True`` a M12-ready account is handoff-ready ONLY
    after its Tier-1 review session is finalized (finalize unblocks; un-finalized stays pending).
    The flag defaults OFF, so the plain reader is unaffected (back-compat)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn)
            acct = await _account(conn, "reviewed")
            await _add_account_run(
                conn,
                run=run,
                entity=acct,
                status=AccountRunStatus.DONE,
                sub_phase=AccountRunSubPhase.CONTACTS_COMPLETE,
            )
            gated = DurableHandoffReadinessReader(
                conn_factory=_factory(conn), require_finalized_review=True
            )
            # M12-ready, but the Tier-1 review is not finalized → gated out (handoff pending).
            assert await gated.ready_accounts(campaign_run_id=run, client_id=_CLIENT) == ()
            # the default reader (gate OFF) still sees it ready — back-compat.
            ungated = DurableHandoffReadinessReader(conn_factory=_factory(conn))
            ready_ungated = await ungated.ready_accounts(campaign_run_id=run, client_id=_CLIENT)
            assert {r.account_entity_id for r in ready_ungated} == {acct}
            # finalize the review session → the gated reader now lets the account through.
            session = await ensure_review_session(
                conn, account_entity_id=acct, campaign_run_id=run, client_id=_CLIENT
            )
            await finalize_review_session(conn, session.id)
            ready = await gated.ready_accounts(campaign_run_id=run, client_id=_CLIENT)
            assert {r.account_entity_id for r in ready} == {acct}

    run_async(_run())


def test_phase_handler_emits_idempotently() -> None:
    """AC3: the HANDOFF phase handler emits one durable event per ready account; a re-entry of the
    phase never double-emits and never re-publishes."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run = await _seed_run(conn)
            acc = await _account(conn, "ready")
            await _add_account_run(
                conn,
                run=run,
                entity=acc,
                status=AccountRunStatus.DONE,
                sub_phase=AccountRunSubPhase.CONTACTS_COMPLETE,
            )
            pub = RecordingHandoffPublisher()
            handler = HandoffPhaseHandler(
                assembler=HandoffAssembler(committee_reader=InMemoryHandoffCommitteeReader()),
                readiness_reader=DurableHandoffReadinessReader(conn_factory=_factory(conn)),
                publisher=pub,
                conn_factory=_factory(conn),
                clock=lambda: _AT,
            )
            ctx = PhaseContext(
                campaign_run_id=run,
                phase=CampaignPhase.HANDOFF,
                client_id=_CLIENT,
                icp_key=_ICP_KEY,
                icp_version=_ICP_VERSION,
            )
            first = await handler.run(ctx)
            assert first.status is PhaseStatus.COMPLETED
            assert first.accounts_processed == 1
            assert first.payload["newly_emitted"] == 1
            assert len(pub.published) == 1
            rows = await list_handoff_events(conn, campaign_run_id=run, client_id=_CLIENT)
            assert len(rows) == 1
            assert rows[0].account_entity_id == acc
            assert rows[0].icp_spec_version == _ICP_VERSION and rows[0].icp_key == _ICP_KEY

            # end-to-end: the account_run tier ("top") is stamped onto the materialised handoff and
            # surfaced on the list summary (spec §M12.3 tier filter).
            page = await HandoffService(
                readiness_reader=DurableHandoffReadinessReader(conn_factory=_factory(conn))
            ).list_handoffs(conn, client_id=_CLIENT, campaign_run_id=run)
            assert page.total == 1 and page.items[0].tier == "top"

            second = await handler.run(ctx)  # phase re-entry / crash-resume
            assert second.accounts_processed == 1 and second.payload["newly_emitted"] == 0
            assert len(pub.published) == 1  # not re-published
            assert len(await list_handoff_events(conn, campaign_run_id=run, client_id=_CLIENT)) == 1

    run_async(_run())


def test_build_handoff_service_smoke() -> None:
    """The api-root service builder wires the durable readiness reader by default (construction)."""
    svc = build_handoff_service()
    assert svc is not None
