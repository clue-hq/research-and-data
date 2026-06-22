"""The ``account_run`` persistence seam the deep orchestrator drives (M8A.1).

:class:`AccountDeepOrchestrator` needs four things from the cursor: ensure the row exists,
read its last-completed ``sub_phase`` + folded ``references_index`` (to resume), and persist the
references + cost + status + the ``sub_phase`` marker. This module is the injectable seam for
exactly that, so the orchestrator is unit-testable with an in-memory fake (no DB) while production
binds the durable M7.1 ``account_run`` repository + the M8A.0 sub-phase setter.

:class:`DbAccountRunIO.save` writes the references + sub-phase advance in **one** transaction — so
a stage's marker commits atomically with its folded references (the boundary M8A.4 tightens to also
enclose the spend). The orchestrator only ever holds claim-id *references* here, never claim bodies
(substrate §5b).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from clue_research.core import CampaignRunId, CostCents, EntityId, RunId
from clue_research.db import transaction
from clue_research.durable import (
    AccountRunStatus,
    AccountRunSubPhase,
    ensure_account_run,
    get_account_run,
    save_references,
    set_account_sub_phase,
)
from clue_research.durable.account_run import ReferencesIndex
from clue_research.profiling.runtime import SessionFactory


class DeepRunState(BaseModel):
    """The resume snapshot of one ``account_run`` the orchestrator reads on (re-)entry (M8A.1).

    A fresh / not-started run reads ``sub_phase=None`` and an empty index; a resumed run reads its
    last-completed boundary + the references folded so far (the member work-list lives under
    the ``committee_contacts`` key, so the contact fan-out resumes without re-discovering the
    committee). ``cost_cents`` is the spend booked by completed stages, so the run keeps a running
    total across a crash-and-resume."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sub_phase: AccountRunSubPhase | None = None
    references_index: ReferencesIndex = {}
    cost_cents: CostCents = Decimal(0)


class AccountRunIO(Protocol):
    """The account_run operations the deep orchestrator drives (M8A.1) — injected for fake-testing.

    Own-transaction (no ``conn`` parameter): each call manages its own commit, so the orchestrator
    stays free of connection plumbing for its execution cursor. The production binding is
    :class:`DbAccountRunIO`; tests supply an in-memory fake."""

    async def ensure(
        self,
        *,
        account_run_id: RunId,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId,
        tier: str,
    ) -> None:
        """Create the ``account_run`` row if absent (idempotent on re-entry — M7.1)."""
        ...

    async def load(self, account_run_id: RunId) -> DeepRunState:
        """Read the resume snapshot (``sub_phase`` + folded references + cost); a missing row reads
        as the fresh default."""
        ...

    async def save(
        self,
        account_run_id: RunId,
        *,
        references_index: ReferencesIndex,
        cost_cents: CostCents,
        status: AccountRunStatus,
        sub_phase: AccountRunSubPhase,
    ) -> None:
        """Persist the folded references + running cost + status, and advance the ``sub_phase``
        marker — committed together so the boundary is never recorded ahead of its references.

        ``references_index`` REPLACES the stored index wholesale (the durable write SETs the JSONB
        column, it does not deep-merge), so a caller must **load → mutate → save the full dict** —
        the pattern the orchestrator follows (it seeds ``refs`` from :meth:`load`). A later
        partial-fold writer (e.g. the M8A.5 handoff fold) MUST do the same or it clobbers prior keys
        such as ``committee_contacts``."""
        ...


class DbAccountRunIO:
    """The production :class:`AccountRunIO` — the durable ``account_run`` repository (M7.1) + the
    M8A.0 sub-phase setter, each call in its own ``session_factory`` transaction."""

    def __init__(self, *, session_factory: SessionFactory = transaction) -> None:
        self._session_factory = session_factory

    async def ensure(
        self,
        *,
        account_run_id: RunId,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId,
        tier: str,
    ) -> None:
        async with self._session_factory() as conn:
            await ensure_account_run(
                conn,
                account_run_id=account_run_id,
                campaign_run_id=campaign_run_id,
                entity_id=entity_id,
                tier=tier,
            )

    async def load(self, account_run_id: RunId) -> DeepRunState:
        async with self._session_factory() as conn:
            row = await get_account_run(conn, account_run_id)
        if row is None:
            return DeepRunState()
        return DeepRunState(
            sub_phase=row.sub_phase,
            references_index=row.references_index,
            cost_cents=row.cost_cents,
        )

    async def save(
        self,
        account_run_id: RunId,
        *,
        references_index: ReferencesIndex,
        cost_cents: CostCents,
        status: AccountRunStatus,
        sub_phase: AccountRunSubPhase,
    ) -> None:
        async with self._session_factory() as conn:
            await save_references(
                conn,
                account_run_id,
                references_index=references_index,
                cost_cents=cost_cents,
                status=status,
            )
            await set_account_sub_phase(conn, account_run_id, sub_phase)


# Static-time conformance (mirroring ``_FAKE_BUDGET_STORE_IS_A_STORE``): the production binding must
# satisfy the protocol, so a test exercising a fake proves the surface DbAccountRunIO implements.
_DB_ACCOUNT_RUN_IO_IS_AN_IO: type[AccountRunIO] = DbAccountRunIO
