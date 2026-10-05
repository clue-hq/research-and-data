"""Replay the 2026-10-05 lease spin: ARV2 quality continuations behind one held work lease.

On trenton, quality-reconciliation tasks queued behind a running one were re-claimed every poll
(one task 883 times in four minutes). This replays that shape against a THROWAWAY Postgres so a
change to the fleet queue, the worker's held-lease path, or the quality sweep can be measured
before and after, with no LLM and no provider calls.

Real: ``LeasedWorkWorker``, ``DbWorkQueue``, ``DbWorkLeaseStore``, the ``fleet_task`` and lease
tables. Stand-ins: the reconciliation (it sleeps ``--hold`` seconds instead of calling the LLM)
and the quality sweep (it offers exactly what ``sweep_quality`` offers — kind, the account's
work id, one dedup key per revision — every 10 s from each of the four "processes").

    uv run python scripts/fleet_lease_spin_replay.py \\
        --dsn postgresql+asyncpg://clue:clue@127.0.0.1:55171/replay_fix --label with-fix

The database must be migrated and hold no fleet tasks except earlier replays' (which each run
deletes first) — a running stack on it would claim the replay's tasks. ``--offer old`` offers
the pre-fix way on the current code, which exercises the worker's held-lease safety net on its
own. To measure the code before a change, check that commit out with ``git worktree add`` and
run this file from inside it (pass this file's path; it adapts to a queue without
``only_if_work_idle``). The record of the first run is in
``_memory/2026-10-05-fleet-lease-spin-fix.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import uuid4

import structlog
from sqlalchemy import text

from clue_db import db_lifespan, transaction
from clue_fleet import DbWorkQueue, FleetTaskKind, LeasedWorkWorker, WorkId, WorkResult

# The incident's shape: 4 fleet processes x 3 slots at the production fleet timings, one account
# whose write-up is being caught up while claim-change signals keep arriving.
WORKERS = 4
SLOTS = 3
POLL_S = 1.0
LEASE_TTL = timedelta(seconds=30)
HEARTBEAT_S = 10.0
STALE_AFTER = timedelta(seconds=60)
SIGNAL_EVERY_S = 8.0  # a claim change lands this often...
SIGNAL_FOR_S = 120.0  # ...for this long
SWEEP_EVERY_S = 10.0  # CLUE_ARV2_QUALITY_RECONCILE_INTERVAL_S; every fleet process sweeps
MAX_RUN_S = 360.0

KIND = FleetTaskKind.ARV2_ACCOUNT_RESEARCH
WORK = WorkId(uuid4())
GENERATION = uuid4()
QUEUE_HAS_IDLE_OFFER = "only_if_work_idle" in inspect.signature(DbWorkQueue.enqueue).parameters


@dataclass
class State:
    hold_s: float
    idle_offer: bool
    t0: float = field(default_factory=time.monotonic)
    input_revision: int = 1
    reconciled: int = 0
    claims: int = 0
    handed_back: int = 0
    applied: list[tuple[float, float]] = field(default_factory=list)
    superseded: int = 0
    max_live: int = 0
    last_signal_at: float = 0.0
    caught_up_at: float | None = None

    def now(self) -> float:
        return time.monotonic() - self.t0


class CountingQueue(DbWorkQueue):
    """The real queue, counting this replay's claims and hand-backs."""

    def __init__(self, state: State) -> None:
        super().__init__()
        self._state = state

    async def claim_next(self, **kwargs):  # type: ignore[no-untyped-def]
        row = await super().claim_next(**kwargs)
        if row is not None and row.kind is KIND:
            self._state.claims += 1
        return row

    async def requeue(self, **kwargs):  # type: ignore[no-untyped-def]
        self._state.handed_back += 1
        return await super().requeue(**kwargs)


class Reconcile:
    """Stand-in for the quality continuation: skip a revision already caught up, else hold the
    account's lease for one LLM pass and catch up to whatever input exists when it finishes (as
    on trenton, where the holder's three queued siblings all found themselves superseded)."""

    kind = KIND

    def __init__(self, state: State) -> None:
        self._state = state

    async def handle(self, context):  # type: ignore[no-untyped-def]
        state = self._state
        if state.reconciled >= int(context.payload["input_revision"]):
            state.superseded += 1
            return WorkResult(outcome="completed", references={"superseded": True})
        started = state.now()
        await asyncio.sleep(state.hold_s)
        state.reconciled = state.input_revision
        state.applied.append((started, state.now()))
        return WorkResult(outcome="completed", references={"applied": True})


async def signals(state: State) -> None:
    while state.now() < SIGNAL_FOR_S:
        await asyncio.sleep(SIGNAL_EVERY_S)
        state.input_revision += 1
        state.last_signal_at = state.now()


async def sweep(state: State, queue: DbWorkQueue, offset: float) -> None:
    await asyncio.sleep(offset)
    extra = {"only_if_work_idle": True} if state.idle_offer else {}
    while True:
        if state.input_revision > state.reconciled:
            await queue.enqueue(
                kind=KIND,
                work_id=WORK,
                dedup_key=f"arv2:quality-editorial:{GENERATION}:{state.input_revision}",
                payload={
                    "continuation": "quality_reconciliation",
                    "input_revision": state.input_revision,
                    "replay": True,
                },
                **extra,
            )
        await asyncio.sleep(SWEEP_EVERY_S)


async def monitor(state: State) -> None:
    while True:
        async with transaction() as conn:
            live = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM fleet_task WHERE kind = CAST(:k AS fleet_task_kind)"
                        " AND work_id = :w AND status IN ('queued', 'claimed')"
                    ),
                    {"k": KIND.value, "w": WORK},
                )
            ).scalar_one()
        state.max_live = max(state.max_live, live)
        if (
            state.caught_up_at is None
            and state.now() > SIGNAL_FOR_S
            and state.reconciled >= state.input_revision
        ):
            state.caught_up_at = state.now()
        await asyncio.sleep(0.5)


async def start_clean() -> None:
    """Refuse a database that is not a throwaway; drop earlier replays' tasks, whose leftover
    queued rows this run's workers would otherwise claim and count."""
    async with transaction() as conn:
        foreign = (
            await conn.execute(
                text("SELECT count(*) FROM fleet_task WHERE NOT (payload_json ? 'replay')")
            )
        ).scalar_one()
        if foreign:
            raise SystemExit(
                f"refusing: fleet_task holds {foreign} non-replay task(s) — this is not a "
                "throwaway database, and its workers would claim the replay's tasks"
            )
        await conn.execute(text("DELETE FROM fleet_task WHERE payload_json ? 'replay'"))


async def replay(dsn: str, label: str, state: State) -> dict[str, object]:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    async with db_lifespan(dsn):
        await start_clean()
        state.t0 = time.monotonic()
        queue = CountingQueue(state)
        workers = [
            LeasedWorkWorker(
                handlers=(Reconcile(state),),
                queue=queue,
                worker_id=f"replay-worker-{i}",
                poll_interval=POLL_S,
                lease_ttl=LEASE_TTL,
                heartbeat_interval=HEARTBEAT_S,
                task_stale_after=STALE_AFTER,
                concurrency=SLOTS,
            )
            for i in range(WORKERS)
        ]
        background = [
            asyncio.create_task(signals(state)),
            asyncio.create_task(monitor(state)),
            *(
                asyncio.create_task(sweep(state, queue, i * SWEEP_EVERY_S / WORKERS))
                for i in range(WORKERS)
            ),
        ]
        running = [asyncio.create_task(w.run()) for w in workers]
        while state.now() < MAX_RUN_S and (
            state.caught_up_at is None or state.now() < state.caught_up_at + 5
        ):
            await asyncio.sleep(1)
        for w in workers:
            w.stop()
        await asyncio.gather(*running, return_exceptions=True)
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        async with transaction() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT dedup_key, status, attempts, result_ref_json FROM fleet_task"
                        " WHERE work_id = :w ORDER BY enqueue_seq"
                    ),
                    {"w": WORK},
                )
            ).all()

    return {
        "label": label,
        "offers_only_if_work_idle": state.idle_offer,
        "revisions_signalled": state.input_revision,
        "reconciled_to": state.reconciled,
        "tasks_created": len(rows),
        "max_live_tasks_on_the_lease": state.max_live,
        "claims": state.claims,
        "claims_handed_back_unrun": state.handed_back,
        "reconciliations_applied": len(state.applied),
        "runs_superseded": state.superseded,
        "still_queued_at_stop": sum(r.status == "queued" for r in rows),
        "recorded_attempts_total": sum(r.attempts for r in rows),
        "recorded_attempts_max": max((r.attempts for r in rows), default=0),
        "caught_up_after_last_signal_s": (
            None
            if state.caught_up_at is None
            else round(state.caught_up_at - state.last_signal_at, 1)
        ),
        "wall_s": round(state.now(), 1),
        "tasks": [
            {
                "revision": int(r.dedup_key.rsplit(":", 1)[1]),
                "status": r.status,
                "attempts": r.attempts,
                "result": r.result_ref_json,
            }
            for r in rows
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dsn", required=True, help="a migrated, throwaway database")
    parser.add_argument("--label", default="replay")
    parser.add_argument(
        "--offer",
        choices=("current", "old"),
        default="current",
        help="current: only_if_work_idle when the queue has it; old: always offer a new task",
    )
    parser.add_argument("--hold", type=float, default=60.0, help="seconds one reconciliation runs")
    args = parser.parse_args()
    state = State(hold_s=args.hold, idle_offer=QUEUE_HAS_IDLE_OFFER and args.offer == "current")
    report = asyncio.run(replay(args.dsn, args.label, state))
    print(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
