"""The queue-backed deep-phase scheduler (PB-B1) — the REQ-10 tier-priority account queue.

:class:`QueueBackedScheduler` implements the exact ``run_accounts(specs, *, campaign_run_id,
checkpointer, run_one)`` seam the M8A deep handler is typed against
(``clue_api.deep.handler.DeepAccountScheduler`` — asserted structurally in ``tests/fleet/``), so
swapping it for :class:`~clue_research.durable.AccountScheduler` at the composition root is a
constructor-argument change with **zero** handler edits (conventions §2). What changes under the
seam:

* every account becomes a durable ``account_job`` row in ``fleet_task`` (idempotent enqueue), so
  a killed run's deep progress is *visible* and *resumable* — ``done`` jobs are skipped by the
  drain and replayed idempotently, ``claimed``-stale jobs are re-owned, ``queued`` jobs proceed;
* execution order is **tier-priority** (`ORDER BY priority, enqueued_at`): budget exhaustion or
  a mid-run kill still researched the best accounts first (REQ-10);
* the concurrency window (~16–32 in flight) is the drain width.

What deliberately does **not** change (the "no new research behavior" treaty rule): ``run_one``
is still the M8A per-account pipeline, exactly-once *spend* is still the M7.4 account-step
ledger's guarantee (a replayed job is spend-free via the sub-phase markers + ledger, exactly like
today's resume path), and one account's failure semantics still belong to the caller — the deep
handler's ``_isolated`` wrapper — mirroring ``AccountScheduler``'s "one account raising
propagates" contract. The queue adds ordering, visibility, and at-most-one concurrent executor
per job; it is not a second idempotency layer.

**Per-entity single-flight (Doc C §4).** This scheduler carries the *same* guarantee as the
``AccountScheduler`` it replaces: two campaign runs never deep-research the same ``entity_id`` at
once (substrate §5c). The queue's dedup key is ``(kind, campaign_run_id, dedup_key)``, so two runs
holding one entity are two *distinct* rows — the queue alone cannot serialize them. So, exactly
like ``AccountScheduler._run_one``, every ``run_one`` (both the drain and the done-replay paths)
runs inside an injected per-entity lock (M2.4 :func:`~clue_locks.entity_lock` in prod, wired from
``clue_research.durable.account_entity_lock_factory`` at the api root), acquired inside the
semaphore slot (semaphore → entity lock → ``run_one``). The lock covers ``run_one`` only, not the
queue ``finish`` bookkeeping. The ``lock_factory`` is a **required** constructor argument — never
defaulted — so a composition site cannot silently omit it and turn single-flight off (the baseline
api composition already did exactly that for ``AccountScheduler``, where the factory is optional;
making it required here turns that omission into a construction-time ``TypeError``). An explicit
opt-out is still possible by passing a null context-manager factory, but it must be *written*.

Single-driver context: the run's driver lease (``clue_fleet.lease``) guarantees only one process
drains a run's account jobs at a time, so a ``claimed``-but-unfinished job either belongs to a
live sibling drainer in this process (its result lands here) or to a killed driver (re-owned
after the staleness window — the drain waits it out rather than deadlocking).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterable, Sequence
from datetime import timedelta
from typing import Any
from uuid import uuid4

from clue_core import CampaignRunId
from clue_fleet.enums import FleetTaskKind, FleetTaskStatus
from clue_fleet.queue import DEFAULT_TASK_STALE_AFTER, DbTaskQueue, TaskQueue
from clue_obs import get_logger
from clue_research.durable import AccountSpec, LockFactory, RunOne

log = get_logger("clue_fleet.scheduler")

# Tier → claim priority (smaller = sooner). Injectable policy (policy-as-data): the default
# understands the repo's two tier spellings — a numeric rank ("1", "2", "tier_2") and the
# ordered names the fixtures use — and pushes anything unknown to the back rather than failing
# (an unknown tier is still researched, just last).
_TIER_NAME_RANK = {"top": 0, "high": 1, "mid": 2, "medium": 2, "low": 3}
_UNKNOWN_TIER_PRIORITY = 100

TierPriority = Callable[[str], int]


def default_tier_priority(tier: str) -> int:
    """Rank a tier label for the claim order: numeric rank if the label carries one, else the
    conventional name ladder (``top`` < ``high`` < ``mid`` < ``low``), else last."""
    lowered = tier.strip().lower()
    if lowered in _TIER_NAME_RANK:
        return _TIER_NAME_RANK[lowered]
    digits = re.search(r"\d+", lowered)
    if digits is not None:
        return int(digits.group())
    return _UNKNOWN_TIER_PRIORITY


class QueueBackedScheduler:
    """Drain a run's account jobs from the durable tier-priority queue (PB-B1).

    Construct with the :class:`~clue_fleet.queue.TaskQueue` (Postgres by default), the
    concurrency ``window``, the **required** per-entity ``lock_factory`` (single-flight, below),
    and optionally a tier-priority policy; the deep handler drives :meth:`run_accounts` exactly as
    it drives ``AccountScheduler``. ``checkpointer`` is accepted for seam parity and unused on the
    ``run_one`` path (the same note as the deep handler's ``CheckpointerFactory``).

    ``lock_factory`` is a :data:`~clue_research.durable.LockFactory` (same seam as
    ``AccountScheduler``) called per ``entity_id`` to obtain the in-flight lock; every ``run_one``
    runs inside it, so two campaign runs never deep-research the same entity at once (Doc C §4 —
    module docstring). It is **required, not optional**: unlike ``AccountScheduler`` (where it
    defaults to ``None`` and the baseline api composition *forgot* to pass it —
    ``platform/api/clue_api/deep/composition.py:345`` — silently disabling single-flight), omitting
    it here is a construction-time ``TypeError``. Prod wires
    ``clue_research.durable.account_entity_lock_factory(get_redis())`` at the api root; an explicit
    Redis-free opt-out passes a null context-manager factory (written, never defaulted)."""

    def __init__(
        self,
        *,
        queue: TaskQueue | None = None,
        window: int = 16,
        lock_factory: LockFactory,
        priority_for: TierPriority = default_tier_priority,
        stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
        poll_interval: float = 0.2,
    ) -> None:
        if window < 1:
            raise ValueError(f"window must be >= 1 (got {window})")
        self._queue: TaskQueue = queue if queue is not None else DbTaskQueue()
        self._window = window
        self._lock_factory = lock_factory
        self._priority_for = priority_for
        self._stale_after = stale_after
        self._poll_interval = poll_interval
        # The claimant id: one per scheduler instance, so a restarted driver is a *different*
        # claimant and the old instance's claims age out instead of being confusable with ours.
        self._claimant_id = f"deep-drain:{uuid4()}"

    async def run_accounts(
        self,
        specs: Iterable[AccountSpec],
        *,
        campaign_run_id: CampaignRunId,
        checkpointer: Any,
        run_one: RunOne[Any],
    ) -> list[Any]:
        """Run every account through ``run_one``, at most ``window`` at a time, best tier first.

        Results come back in input order (the ``AccountScheduler`` contract). Jobs already
        ``done`` from a previous (killed) drive are **replayed** through ``run_one`` without
        re-claiming — idempotent and spend-free (the M8A sub-phase markers + account-step
        ledger), exactly like today's resume path — so the caller still receives one result per
        spec. An exception from ``run_one`` marks that job ``FAILED`` and propagates (the caller
        owns isolation, per the seam contract).

        Every ``run_one`` (both the drain and the replay paths) runs inside the per-entity
        ``lock_factory`` lock, in the semaphore slot (semaphore → entity lock → ``run_one``),
        mirroring ``AccountScheduler._run_one`` — the Doc C §4 single-flight guarantee that two
        campaign runs never deep-research the same entity at once (class/module docstrings)."""
        ordered: Sequence[AccountSpec] = tuple(specs)
        by_key: dict[str, AccountSpec] = {str(spec.entity_id): spec for spec in ordered}
        if len(by_key) != len(ordered):
            raise ValueError("duplicate entity_id in specs (dedup keys would collide)")
        if not ordered:
            return []

        # (Re-)offer the work, idempotently: fresh specs insert; re-entered specs are no-ops;
        # FAILED jobs from a previous drive are explicitly re-opened for retry.
        for spec in ordered:
            await self._queue.enqueue(
                kind=FleetTaskKind.ACCOUNT_JOB,
                campaign_run_id=campaign_run_id,
                dedup_key=str(spec.entity_id),
                priority=self._priority_for(spec.tier),
                payload={"tier": spec.tier},
            )
        requeued = await self._queue.requeue_failed(
            kind=FleetTaskKind.ACCOUNT_JOB, campaign_run_id=campaign_run_id
        )
        if requeued:
            log.info(
                "deep_drain.requeued_failed",
                campaign_run_id=str(campaign_run_id),
                count=requeued,
            )

        results: dict[str, Any] = {}
        semaphore = asyncio.Semaphore(self._window)
        # Set when any executor raised: the sibling drainers must stop waiting for the failed
        # key's result (it will never land) instead of poll-looping forever while ``gather``
        # propagates the exception.
        aborted = asyncio.Event()
        # Keys a sibling drainer is executing RIGHT NOW. A job running longer than the staleness
        # window looks orphaned to claim-next, and — single-driver: the only other claimants are
        # this process's siblings — would get re-claimed and double-run without this guard. A
        # guarded re-claim is harmless: it merely re-stamped ``claimed_at`` (a de-facto claim
        # heartbeat, same claimant id), and the executing drainer's finish still holds.
        in_flight: set[str] = set()

        # Jobs a previous drive already finished: replay for their results, off-queue.
        done_keys = {
            task.dedup_key
            for task in await self._queue.list_tasks(
                campaign_run_id=campaign_run_id, kind=FleetTaskKind.ACCOUNT_JOB
            )
            if task.status is FleetTaskStatus.DONE and task.dedup_key in by_key
        }

        async def _replay(key: str) -> None:
            async with semaphore:
                try:
                    # Single-flight (Doc C §4): a replay still holds the entity lock, so it can't
                    # race a live drain of the same entity in a sibling campaign run.
                    async with self._lock_factory(by_key[key].entity_id):
                        results[key] = await run_one(by_key[key])
                except Exception:
                    aborted.set()
                    raise

        async def _drain() -> None:
            while len(results) < len(by_key) and not aborted.is_set():
                async with semaphore:
                    task = await self._queue.claim_next(
                        kind=FleetTaskKind.ACCOUNT_JOB,
                        worker_id=self._claimant_id,
                        campaign_run_id=campaign_run_id,
                        stale_after=self._stale_after,
                    )
                    if task is None:
                        # Nothing claimable *now*: the remaining jobs are running in sibling
                        # drainers, replaying, or held by a killed driver whose claim has not yet
                        # gone stale — wait, don't deadlock (module docstring).
                        pass
                    elif task.dedup_key not in by_key:
                        # A job from an earlier spec set (e.g. cutoffs adjusted mid-run) — not in
                        # the currently approved set, so it must not run: park it as done-skipped
                        # (visible in the queue history, spend-free).
                        await self._queue.finish(
                            task_id=task.task_id,
                            worker_id=self._claimant_id,
                            status=FleetTaskStatus.DONE,
                            result_ref={"skipped": "not in current spec set"},
                        )
                        continue
                    elif task.dedup_key in in_flight or task.dedup_key in results:
                        # A stale-looking claim on a job a sibling is executing (or just
                        # finished): the re-claim above already re-stamped it — do NOT run it a
                        # second time; wait for the sibling's result to land.
                        pass
                    else:
                        key = task.dedup_key
                        # Mark in-flight BEFORE awaiting the entity lock: while this drainer blocks
                        # on a lock held by another run, its claimed row can cross the staleness
                        # window and look orphaned to a sibling's claim-next; the in_flight guard
                        # must cover the lock wait so the sibling's stale re-claim can't double-run
                        # this job. The lock (Doc C §4 single-flight) covers run_one only — not the
                        # queue ``finish`` bookkeeping below.
                        in_flight.add(key)
                        try:
                            async with self._lock_factory(by_key[key].entity_id):
                                result = await run_one(by_key[key])
                        except Exception:
                            aborted.set()
                            await self._queue.finish(
                                task_id=task.task_id,
                                worker_id=self._claimant_id,
                                status=FleetTaskStatus.FAILED,
                            )
                            raise
                        finally:
                            in_flight.discard(key)
                        results[key] = result
                        await self._queue.finish(
                            task_id=task.task_id,
                            worker_id=self._claimant_id,
                            status=FleetTaskStatus.DONE,
                            result_ref={"ok": True},
                        )
                        continue
                await asyncio.sleep(self._poll_interval)

        drainers = [_drain() for _ in range(min(self._window, len(by_key)))]
        replays = [_replay(key) for key in done_keys]
        await asyncio.gather(*drainers, *replays)
        return [results[str(spec.entity_id)] for spec in ordered]
