"""The ``account_run`` persistence seam the deep orchestrator drives (M8A.1).

:class:`AccountDeepOrchestrator` needs four things from the cursor: ensure the row exists,
read its last-completed ``sub_phase`` + folded ``references_index`` + running cost (to resume), and
fold the references + status + the ``sub_phase`` marker. This module is the injectable seam for
exactly that, so the orchestrator is unit-testable with an in-memory fake (no DB) while production
binds the durable M7.1 ``account_run`` repository + the M8A.0 sub-phase setter.

:meth:`DbAccountRunIO.fold` takes the **caller's connection** (M8A.4) and writes the references +
sub-phase advance on it — so a stage's marker + folded references commit in the **same** transaction
as the spend (claim writes + charge + ledger ``succeed``) the orchestrator runs through
:class:`~clue_api.deep.spend.ExactlyOnceSpend` on that connection. It does **not** write
``cost_cents``: :meth:`~clue_research.durable.budget.BudgetEngine.record` is the single live writer
of the per-account spend (the single-writer reconciliation, spec §M8A.4), so the fold must not
clobber it. The orchestrator only ever holds claim-id *references* here, never bodies (§5b).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import CostCents, EntityId, ProjectRunId, RunId
from clue_db import ConnFactory, transaction
from clue_research.durable import (
    AccountRunStatus,
    AccountRunSubPhase,
    ensure_account_run,
    fold_references,
    get_account_run,
    set_account_sub_phase,
)
from clue_research.durable.account_run import ReferencesIndex


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

    ``ensure`` / ``load`` are own-transaction (independent reads/creates — no ``conn`` parameter).
    ``fold`` (M8A.4) takes the **caller's connection** so the references + marker advance commit in
    the same transaction as the stage's spend. The production binding is :class:`DbAccountRunIO`;
    tests supply an in-memory fake."""

    async def ensure(
        self,
        *,
        account_run_id: RunId,
        project_run_id: ProjectRunId,
        entity_id: EntityId,
        tier: str,
    ) -> None:
        """Create the ``account_run`` row if absent (idempotent on re-entry — M7.1)."""
        ...

    async def load(self, account_run_id: RunId) -> DeepRunState:
        """Read the resume snapshot (``sub_phase`` + folded references + cost); a missing row reads
        as the fresh default. ``cost_cents`` is the record-owned running total (the resume seed)."""
        ...

    async def fold(
        self,
        conn: AsyncConnection,
        account_run_id: RunId,
        *,
        references_index: ReferencesIndex,
        status: AccountRunStatus,
        sub_phase: AccountRunSubPhase,
    ) -> None:
        """Fold the references + status and advance the ``sub_phase`` marker **on ``conn``** — so
        the boundary commits in the same transaction as the stage's spend (claim writes + charge +
        ledger ``succeed``) the orchestrator runs on that connection (M8A.4). Does **not** write
        ``cost_cents`` — :meth:`BudgetEngine.record` is its single live writer.

        ``references_index`` REPLACES the stored index wholesale (the durable write SETs the JSONB
        column, it does not deep-merge), so a caller must **load → mutate → fold the full dict** —
        the pattern the orchestrator follows (it seeds ``refs`` from :meth:`load`). A later
        partial-fold writer (e.g. the M8A.5 handoff fold) MUST do the same or it clobbers prior keys
        such as ``committee_contacts``."""
        ...


class DbAccountRunIO:
    """The production :class:`AccountRunIO` — the durable ``account_run`` repository (M7.1) + the
    M8A.0 sub-phase setter. ``ensure`` / ``load`` run in their own ``session_factory`` transaction;
    ``fold`` runs on the caller's connection (the M8A.4 exactly-once boundary)."""

    def __init__(self, *, session_factory: ConnFactory = transaction) -> None:
        self._session_factory = session_factory

    async def ensure(
        self,
        *,
        account_run_id: RunId,
        project_run_id: ProjectRunId,
        entity_id: EntityId,
        tier: str,
    ) -> None:
        async with self._session_factory() as conn:
            await ensure_account_run(
                conn,
                account_run_id=account_run_id,
                project_run_id=project_run_id,
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

    async def fold(
        self,
        conn: AsyncConnection,
        account_run_id: RunId,
        *,
        references_index: ReferencesIndex,
        status: AccountRunStatus,
        sub_phase: AccountRunSubPhase,
    ) -> None:
        await fold_references(
            conn,
            account_run_id,
            references_index=references_index,
            status=status,
        )
        await set_account_sub_phase(conn, account_run_id, sub_phase)


# Static-time conformance (mirroring ``_FAKE_BUDGET_STORE_IS_A_STORE``): the production binding must
# satisfy the protocol, so a test exercising a fake proves the surface DbAccountRunIO implements.
_DB_ACCOUNT_RUN_IO_IS_AN_IO: type[AccountRunIO] = DbAccountRunIO
