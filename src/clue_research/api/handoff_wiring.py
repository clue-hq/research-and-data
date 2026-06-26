"""M12.3 — the api-root wiring for the output/handoff boundary (the terminal seam).

The composition root (only ``api`` may import both ``narrative`` and ``durable`` — the import-linter
independence contract) wires:

* the **durable-backed readiness reader** — the production
  :class:`~clue_research.narrative.readiness.HandoffReadinessReader` over the M7 ``campaign_run`` /
  ``account_run`` tables (``narrative`` may not import ``durable``, so this lands here, like the
  M12.1 positioner's committee reader and the M12.2 assembler's committee reader);
* the :class:`~clue_research.narrative.HandoffService` (the read API) over that reader;
* the **handoff phase handler** — a :class:`~clue_research.core.PhaseHandler` for
  ``CampaignPhase.HANDOFF`` that, when the campaign-run state machine enters the handoff phase,
  assembles + materialises + emits a durable ``handoff_event`` for every ready account (the M12.3
  emit/notify path), registered into the M7.3 :class:`PhaseHandlerRegistry`
  (``durable.register_phase_handler``) — so the state machine dispatches it by phase without
  importing ``narrative``.

The FastAPI HTTP surface itself is ``api/handoff_app.py``; this module supplies the dependencies it
serves. Read/emit only — never a write-back path into the claim store (conventions §6).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    CampaignPhase,
    CampaignRunId,
    EntityId,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    UnitInterval,
    UtcDatetime,
)
from clue_research.db import connection, transaction
from clue_research.durable import (
    AccountRunStatus,
    AccountRunSubPhase,
    CampaignRunStatus,
    get_campaign_run,
    list_account_runs,
    register_phase_handler,
)
from clue_research.narrative import (
    AccountReadiness,
    HandoffAssembler,
    HandoffPublisher,
    HandoffReadinessReader,
    HandoffService,
    OutboxHandoffPublisher,
    RunReadiness,
    emit_ready_handoffs,
)
from clue_research.review import finalized_review_account_ids

_ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
_Clock = Callable[[], UtcDatetime]

# A campaign run past these statuses will produce no further handoffs (the API tells consumers to
# stop polling).
_TERMINAL_RUN_STATUSES = frozenset({CampaignRunStatus.COMPLETED, CampaignRunStatus.FAILED})


def _utc_now() -> UtcDatetime:
    return datetime.now(UTC)


class DurableHandoffReadinessReader:
    """The production :class:`HandoffReadinessReader` over the M7 ``campaign_run`` / ``account_run``
    tables. Manages its own short read transaction (the seam carries no connection, like the M12.1
    retriever stub). Tenant-scoped: a run whose ``client_id`` is not the caller's resolves to
    ``None`` / no ready accounts (cross-tenant isolation — substrate §2)."""

    def __init__(
        self, *, conn_factory: _ConnFactory = connection, require_finalized_review: bool = False
    ) -> None:
        self._conn_factory = conn_factory
        # M13.1 handoff gate: when True, an account is handoff-ready only if its Tier-1 review
        # session is FINALIZED (a finalized session unblocks that account's handoff; un-finalized
        # leaves it pending). Default OFF so existing M12 flows / tests are unaffected; the full M13
        # flow opts in at the composition root.
        self._require_finalized_review = require_finalized_review

    async def run_readiness(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> RunReadiness | None:
        async with self._conn_factory() as conn:
            run = await get_campaign_run(conn, campaign_run_id)
        if run is None or run.client_id != client_id:
            return None
        return RunReadiness(
            campaign_run_id=campaign_run_id,
            client_id=client_id,
            phase=run.phase,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
            is_terminal=run.status in _TERMINAL_RUN_STATUSES,
        )

    async def ready_accounts(
        self, *, campaign_run_id: CampaignRunId, client_id: str
    ) -> tuple[AccountReadiness, ...]:
        async with self._conn_factory() as conn:
            run = await get_campaign_run(conn, campaign_run_id)
            if run is None or run.client_id != client_id:
                return ()
            rows = await list_account_runs(conn, campaign_run_id)
            finalized_review = (
                await finalized_review_account_ids(conn, campaign_run_id)
                if self._require_finalized_review
                else None
            )
        ready: list[AccountReadiness] = []
        for row in rows:
            is_ready = (
                row.status is AccountRunStatus.DONE
                and row.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
            )
            if not is_ready:
                continue  # account still in deep/verification — not handoff-ready (AC2)
            if finalized_review is not None and EntityId(row.entity_id) not in finalized_review:
                continue  # M13.1: Tier-1 review not finalized for this account — handoff pending
            ready.append(
                AccountReadiness(
                    account_entity_id=EntityId(row.entity_id),
                    is_ready=True,
                    status=row.status.value,
                    sub_phase=row.sub_phase.value if row.sub_phase is not None else None,
                    tier=row.tier,
                )
            )
        return tuple(ready)


def build_handoff_readiness_reader(
    *, conn_factory: _ConnFactory = connection, require_finalized_review: bool = False
) -> HandoffReadinessReader:
    """The api-root :class:`HandoffReadinessReader` (durable-backed) to inject into the service +
    the emit path. ``require_finalized_review`` (M13.1) gates handoff on a finalized Tier-1 review
    session — default OFF (back-compat); the full M13 flow passes ``True`` for the HANDOFF path."""
    return DurableHandoffReadinessReader(
        conn_factory=conn_factory, require_finalized_review=require_finalized_review
    )


def build_handoff_service(
    *, readiness_reader: HandoffReadinessReader | None = None
) -> HandoffService:
    """Construct the M12.3 :class:`HandoffService` (the read API). Defaults to the durable-backed
    readiness reader (used only to expose the run phase on the list view); pass a fake in tests."""
    return HandoffService(readiness_reader=readiness_reader or build_handoff_readiness_reader())


class HandoffPhaseHandler:
    """The ``CampaignPhase.HANDOFF`` :class:`~clue_research.core.PhaseHandler` (M12.3 emit path).

    When the campaign-run state machine enters the handoff phase, :meth:`run` assembles +
    materialises
    + emits a durable ``handoff_event`` for every handoff-ready account in the run (via
    :func:`~clue_research.narrative.emit_ready_handoffs`) — idempotent on
    ``(campaign_run, account, icp_spec_version, icp_key)`` so a re-entry / crash-resume never
    double-emits (mirrors the campaign-phase idempotency, Doc C §4 / M7.4). The optional push fires
    once per newly-emitted row through the injected :class:`HandoffPublisher` (default: the durable
    outbox, pull). It reads the ICP segment off the run, so segment A never assembles under segment
    B's
    version (D5)."""

    phase: CampaignPhase = CampaignPhase.HANDOFF

    def __init__(
        self,
        *,
        assembler: HandoffAssembler,
        readiness_reader: HandoffReadinessReader,
        publisher: HandoffPublisher | None = None,
        conn_factory: _ConnFactory = transaction,
        clock: _Clock = _utc_now,
        coverage_confidence: UnitInterval | None = None,
    ) -> None:
        self._assembler = assembler
        self._readiness_reader = readiness_reader
        self._publisher = publisher or OutboxHandoffPublisher()
        self._conn_factory = conn_factory
        self._clock = clock
        self._coverage_confidence = coverage_confidence

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        report = await emit_ready_handoffs(
            conn_factory=self._conn_factory,
            assembler=self._assembler,
            readiness_reader=self._readiness_reader,
            publisher=self._publisher,
            campaign_run_id=ctx.campaign_run_id,
            client_id=ctx.client_id,
            assembled_at=self._clock(),
            coverage_confidence=self._coverage_confidence,
        )
        return PhaseResult(
            status=PhaseStatus.COMPLETED,
            accounts_processed=report.accounts_processed,
            payload={"newly_emitted": report.newly_emitted, "refs": list(report.refs)},
        )


def build_handoff_phase_handler(
    *,
    assembler: HandoffAssembler,
    readiness_reader: HandoffReadinessReader | None = None,
    publisher: HandoffPublisher | None = None,
    conn_factory: _ConnFactory = transaction,
    clock: _Clock = _utc_now,
    require_finalized_review: bool = False,
) -> HandoffPhaseHandler:
    """Construct the handoff phase handler (the emit driver). ``assembler`` is the M12.2 assembler
    (its committee reader injected at this root); ``readiness_reader`` defaults to the
    durable-backed reader. ``require_finalized_review`` (M13.1) gates the emit on a finalized review
    — the full M13 flow passes ``True`` so HANDOFF only emits reviewed accounts."""
    return HandoffPhaseHandler(
        assembler=assembler,
        readiness_reader=readiness_reader
        or build_handoff_readiness_reader(require_finalized_review=require_finalized_review),
        publisher=publisher,
        conn_factory=conn_factory,
        clock=clock,
    )


def register_handoff_phase_handler(handler: HandoffPhaseHandler) -> None:
    """Register the handoff phase handler into the M7.3 process-default
    :class:`PhaseHandlerRegistry` (``CampaignPhase.HANDOFF`` → ``handler``), so the campaign-run
    state
    machine dispatches the emit path by phase without importing ``narrative`` (mirrors
    ``register_profiling_workers`` / ``register_aspect_worker``)."""
    register_phase_handler(handler)
