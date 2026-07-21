"""The stub-mode fleet worker process for the PB-B1 exit-gate test.

A real, killable OS process (spawned by ``tests/fleet/test_exit_gate.py``) that composes the
*actual* production machinery — ``CampaignRun`` + ``DbCampaignRunStore`` + ``DbIdempotencyStore``
(the M7 state machine and ledger), ``CampaignRunWorker`` + ``DbTaskQueue`` + ``DbLeaseStore``
(the PB-B1 shell), and the ``QueueBackedScheduler`` deep drain — with **stub phase bodies**:
every phase except ``deep`` completes instantly; the ``deep`` phase fans out one stub account
job per account, whose "paid resolver call" is a sleep and whose spend is recorded through the
real M7.4 account-step idempotency ledger.

The stub job mirrors the M8 exactly-once pattern precisely: claim the ``(account, field, tier)``
key, do the "spend", then — in ONE transaction — write the effect (a row in the test's
``exit_gate_spend_journal``) and finish the ledger ``succeeded``. That journal is the test's
double-spend detector: kill -9 at any instant leaves either no row + a re-ownable claim, or
exactly one row + a replayable success — never two rows for one key.

Configured entirely by ``EXIT_GATE_*`` env vars (plus the standard ``CLUE_DATABASE_URL``); the
key/entity derivations live here so the pytest side imports and recomputes the exact same keys.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from clue_fleet import CampaignRunWorker, QueueBackedScheduler, run_worker
from sqlalchemy import text

from clue_core import (
    CampaignPhase,
    CampaignRunId,
    CostCents,
    EntityId,
    FieldKey,
    IdempotencyScope,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    RunId,
    SourceTier,
)
from clue_core.idempotency import account_step_key
from clue_db import db_lifespan, transaction
from clue_research.durable import (
    PHASE_SEQUENCE,
    AccountSpec,
    CampaignRun,
    ClaimOutcome,
    DbCampaignRunStore,
    DbIdempotencyStore,
    IdempotencyStatus,
    PhaseHandlerRegistry,
    claim_idempotency_step,
    finish_idempotency_step,
)

STUB_FIELD = FieldKey("account.stub.field")
STUB_TIER = SourceTier(4)
STUB_COST = Decimal(1)
_TIERS = ("top", "high", "low")

_JOURNAL_INSERT = text(
    "INSERT INTO exit_gate_spend_journal (run_id, step_key, worker) "
    "VALUES (:run_id, :step_key, :worker)"
)


def entity_for(campaign_run_id: CampaignRunId, index: int) -> EntityId:
    """The i-th stub account's entity id — deterministic per run, stable across restarts."""
    return EntityId(uuid5(NAMESPACE_URL, f"exit-gate:{campaign_run_id}:acct:{index}"))


def tier_for(index: int) -> str:
    return _TIERS[index % len(_TIERS)]


def account_run_for(campaign_run_id: CampaignRunId) -> RunId:
    """The stub deep pass's account-run id (one per campaign run, stable across restarts) — the
    first component of every account-step key."""
    return RunId(uuid5(NAMESPACE_URL, f"exit-gate:{campaign_run_id}:account-run"))


def step_key_for(campaign_run_id: CampaignRunId, index: int) -> str:
    """The exact ``(account_run, entity, field, tier)`` ledger key the stub job spends under —
    recomputed identically by the test's exactly-once assertions."""
    return account_step_key(
        account_run_for(campaign_run_id),
        entity_for(campaign_run_id, index),
        STUB_FIELD,
        STUB_TIER,
    )


class InstantHandler:
    """A phase body that completes immediately (every phase except ``deep``): the state machine
    still checkpoints, ledger-brackets, and transitions it for real."""

    def __init__(self, phase: CampaignPhase) -> None:
        self.phase = phase

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(status=PhaseStatus.COMPLETED, payload={"stub": self.phase.value})


class StubDeepHandler:
    """The ``deep`` phase: fan every stub account through the queue-backed tier-priority drain,
    spending exactly once per account through the real account-step ledger."""

    phase = CampaignPhase.DEEP

    def __init__(
        self,
        scheduler: QueueBackedScheduler,
        *,
        accounts: int,
        job_sleep_s: float,
        ledger_stale: timedelta,
        worker_label: str,
    ) -> None:
        self._scheduler = scheduler
        self._accounts = accounts
        self._job_sleep_s = job_sleep_s
        self._ledger_stale = ledger_stale
        self._worker_label = worker_label

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        campaign_run_id = ctx.campaign_run_id
        account_run_id = account_run_for(campaign_run_id)
        specs = [
            AccountSpec(entity_id=entity_for(campaign_run_id, i), tier=tier_for(i))
            for i in range(self._accounts)
        ]

        async def run_one(spec: AccountSpec) -> dict[str, Any]:
            key = account_step_key(account_run_id, spec.entity_id, STUB_FIELD, STUB_TIER)
            # Claim the step (its own transaction, like DbIdempotencyStore.claim). A fresh
            # ``in_progress`` holder (the killed worker's claim not yet stale) is waited out —
            # the M7.4 "back off and retry; the row goes stale or succeeds" guidance.
            while True:
                async with transaction() as conn:
                    claim = await claim_idempotency_step(
                        conn,
                        key=key,
                        scope=IdempotencyScope.ACCOUNT_STEP,
                        stale_after=self._ledger_stale,
                    )
                if claim.outcome is not ClaimOutcome.CONFLICT:
                    break
                await asyncio.sleep(0.2)
            if claim.outcome is ClaimOutcome.REPLAY:
                return {"entity": str(spec.entity_id), "replayed": True}
            # The "paid resolver call".
            await asyncio.sleep(self._job_sleep_s)
            # The M8 exactly-once shape: the effect (journal row) and the ledger ``succeeded``
            # commit in ONE transaction — no kill window can double the spend.
            async with transaction() as conn:
                await conn.execute(
                    _JOURNAL_INSERT,
                    {
                        "run_id": campaign_run_id,
                        "step_key": key,
                        "worker": self._worker_label,
                    },
                )
                await finish_idempotency_step(
                    conn,
                    key=key,
                    status=IdempotencyStatus.SUCCEEDED,
                    result_ref={"entity": str(spec.entity_id)},
                    cost_cents=STUB_COST,
                )
            return {"entity": str(spec.entity_id)}

        results = await self._scheduler.run_accounts(
            specs, campaign_run_id=campaign_run_id, checkpointer=None, run_one=run_one
        )
        executed = sum(1 for r in results if not r.get("replayed"))
        cost: CostCents = STUB_COST * executed
        return PhaseResult(
            status=PhaseStatus.COMPLETED,
            accounts_processed=len(results),
            cost_cents=cost,
            payload={"deep_count": len(results)},
        )


def build_worker() -> CampaignRunWorker:
    """Compose the stub-mode worker from ``EXIT_GATE_*`` env (the test controls every knob)."""
    accounts = int(os.environ["EXIT_GATE_ACCOUNTS"])
    worker_id = os.environ["EXIT_GATE_WORKER_ID"]
    job_sleep_s = float(os.environ.get("EXIT_GATE_JOB_SLEEP_S", "0.1"))
    lease_ttl = timedelta(seconds=float(os.environ.get("EXIT_GATE_LEASE_TTL_S", "2")))
    heartbeat_s = float(os.environ.get("EXIT_GATE_HEARTBEAT_S", "0.5"))
    stale = timedelta(seconds=float(os.environ.get("EXIT_GATE_STALE_S", "2")))
    window = int(os.environ.get("EXIT_GATE_WINDOW", "16"))

    registry = PhaseHandlerRegistry()
    for phase in PHASE_SEQUENCE:
        if phase is not CampaignPhase.DEEP:
            registry.register(InstantHandler(phase))
    scheduler = QueueBackedScheduler(window=window, stale_after=stale, poll_interval=0.05)
    registry.register(
        StubDeepHandler(
            scheduler,
            accounts=accounts,
            job_sleep_s=job_sleep_s,
            ledger_stale=stale,
            worker_label=worker_id,
        )
    )
    driver = CampaignRun(store=DbCampaignRunStore(), registry=registry, ledger=DbIdempotencyStore())
    return CampaignRunWorker(
        driver=driver,
        worker_id=worker_id,
        poll_interval=0.1,
        lease_ttl=lease_ttl,
        heartbeat_interval=heartbeat_s,
        task_stale_after=stale,
    )


async def main() -> None:
    async with db_lifespan():
        await run_worker(build_worker())


if __name__ == "__main__":
    asyncio.run(main())
