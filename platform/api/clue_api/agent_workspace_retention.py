"""The expiry job: a cold chat's raw inputs and working files lose their bytes (WS-24, WS-26).

F3 Phase 2 (docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md;
rulings AW-2, AW-22, AW-24 as amended 2026-10-23). Once a day the fleet walks the chats nothing has
touched for a while and, for each, publishes a new snapshot version whose due entries are marked
expired and keep only their :class:`~clue_agents.workspace_snapshot.Receipt`. ``reads/`` and the
other raw inputs go 48 hours after the chat's last activity, the agent's own rough work after 7
days, and ``outputs/`` never.

**The job deletes nothing itself.** Marking an entry expired drops it out of
:meth:`~clue_agents.workspace_snapshot.SnapshotManifest.live`, so the next save does not hold its
key, and :class:`~clue_api.agent_workspace_snapshots.DbWorkspaceSnapshotStore` erases and purges
every own-area key the new version released that no other snapshot holds (ruling AW-26). One
``save`` is therefore the whole of the job's write.

**What counts as activity** (WS-24) is the newest of the snapshot row's ``last_activity_at`` and the
chat's newest ``agent_turn_submission``. A folder id that is not a chat — a research run, a
delegation — has no submissions and answers with its own column.

**A busy chat is skipped, never raced.** A queued or claimed ``agent_turn`` task for the thread's
work id, or a live ``work_lease`` on it, means a turn is about to save or is saving; the chat is
counted as skipped and left for tomorrow. That check is a courtesy, not the guarantee: a turn can
complete between the candidate scan and the expiry and leave nothing for it to see. The guarantee
is that the decision and the write are anchored to one read — the chat's activity and version
taken together, as late as possible, with the save compare-and-setting on that same version. The
job never acts on a chat whose state has moved since it looked; it records a ``stale`` and leaves
it for tomorrow, and it never retries inside the run.

**The job's own save is not activity.** It passes ``activity=False``, so the version moves and the
chat's ``last_activity_at`` stays exactly where the chat left it. Stamping it would restart the
48-hour clock every pass and the 7-day window would never elapse.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.workspace_snapshot import (
    UNKNOWN_RECEIPT,
    SnapshotEntry,
    SnapshotManifest,
    SnapshotTier,
)
from clue_api.agent_turn_submission import thread_work_id
from clue_api.agent_workspace_snapshots import DbWorkspaceSnapshotStore
from clue_db import ConnFactory, transaction
from clue_obs import get_logger

__all__ = [
    "RETENTION_SWEEP",
    "AgentWorkspaceRetentionJob",
    "RetentionReport",
    "run_retention_if_due",
]

log = get_logger("clue_api.agent_workspace_retention")

#: The ``maintenance_run`` row and advisory-lock key of the fleet-wide expiry job.
RETENTION_SWEEP = "agent_workspace_retention"
_RETENTION_LOCK = "agent-workspace-retention"

# WS-24's definition of a chat's activity, written once and read by both the scan and the expiry:
# ``GREATEST`` over the snapshot row's own stamp and the chat's newest submission. The correlated
# max rides ``agent_turn_submission_thread_order (workspace_id, thread_id, requested_at, turn_id)``.
_ACTIVITY_EXPR = """
        GREATEST(
            s.last_activity_at,
            COALESCE(
                (SELECT max(t.requested_at) FROM agent_turn_submission t
                  WHERE t.workspace_id = s.workspace_id AND t.thread_id = s.thread_id),
                s.last_activity_at
            )
        )
"""

# The chats whose newest activity is at or before the cutoff, coldest first, one page at a time.
# ``:after_*`` is the previous page's last row — the keyset the walk resumes from, so a backlog of
# any size is read in bounded bites and the pass is restartable rather than one huge result set.
_CANDIDATES = text(
    f"""
    SELECT workspace_id, thread_id, project_id, version, last_activity
    FROM (
        SELECT s.workspace_id, s.thread_id, s.project_id, s.version,
               {_ACTIVITY_EXPR} AS last_activity
        FROM agent_workspace_snapshot s
    ) AS chat
    WHERE last_activity <= :cutoff
      AND (
          CAST(:after_activity AS timestamptz) IS NULL
          OR (last_activity, workspace_id, thread_id)
             > (CAST(:after_activity AS timestamptz), :after_ws, :after_thread)
      )
    ORDER BY last_activity, workspace_id, thread_id
    LIMIT :limit
    """
)

# The same chat's activity and version read together, as late as possible — the one read the
# expiry decision is actually made on. The candidate scan's copy is minutes old by the time a chat
# comes up (review I2): a turn can have completed since, leaving no queued task and no live lease
# for ``_BUSY`` to see, and expiring on the stale value would destroy files written since.
_ACTIVITY = text(
    f"""
    SELECT s.version, {_ACTIVITY_EXPR} AS last_activity
    FROM agent_workspace_snapshot s
    WHERE s.workspace_id = :ws AND s.thread_id = :thread
    """
)

_BUSY = text(
    """
    SELECT EXISTS (
            SELECT 1 FROM fleet_task
             WHERE kind = CAST('agent_turn' AS fleet_task_kind)
               AND work_id = :work_id
               AND status IN ('queued', 'claimed')
           )
        OR EXISTS (
            SELECT 1 FROM work_lease WHERE work_id = :work_id AND expires_at > :now
           )
    """
)


@dataclass(frozen=True, slots=True)
class RetentionReport:
    """What one pass of the job did, for the fleet's log line."""

    chats_checked: int = 0
    chats_expired: int = 0
    files_expired: int = 0
    skipped_busy: int = 0
    stale: int = 0
    #: Chats this pass could not read or save. Each one is logged and stepped over; a chat that
    #: fails every day shows up here every day, which is what an operator watches (runbook).
    failed: int = 0


@dataclass(frozen=True, slots=True)
class _Chat:
    workspace_id: str
    thread_id: str
    project_id: str
    version: int
    last_activity: datetime


class AgentWorkspaceRetentionJob:
    """Expire the due files of every cold chat, one snapshot save each."""

    def __init__(
        self,
        *,
        store: DbWorkspaceSnapshotStore,
        conn_factory: ConnFactory = transaction,
        raw_s: float,
        working_s: float,
        page_size: int = 500,
    ) -> None:
        self._store = store
        self._conn_factory = conn_factory
        self._page_size = max(1, page_size)
        self._windows: dict[SnapshotTier, timedelta | None] = {
            "raw_input": timedelta(seconds=raw_s),
            "working_file": timedelta(seconds=working_s),
            # AW-2: finished work is never expired, so this tier has no window at all.
            "work_product": None,
        }

    async def run_once(self, *, now: datetime | None = None) -> RetentionReport:
        """Sweep every cold chat, one page of candidates and one chat at a time.

        **No single chat may end the pass** (review I1). A manifest blob the rows still name but
        storage has lost raises :class:`SnapshotCorrupt`, and before this that raise left the
        whole fleet's retention off: ``run_retention_if_due`` records nothing when ``run_once``
        raises, so the next pass re-read the same deterministic ordering and died on the same
        chat, for ever, behind one warning. A chat that cannot be read is counted in ``failed``,
        logged with its ids, and stepped over.
        """

        now = now or datetime.now(UTC)
        soonest = min(window for window in self._windows.values() if window is not None)
        checked = expired_chats = expired_files = busy = stale = failed = 0
        async for chat in self._candidates(cutoff=now - soonest):
            checked += 1
            try:
                if await self._busy(chat, now=now):
                    busy += 1
                    continue
                count, outcome = await self._expire(chat, now=now)
            except Exception as exc:  # noqa: BLE001 — one bad chat may not stop the others
                failed += 1
                log.warning(
                    "agent_workspace.retention.chat_failed",
                    workspace_id=chat.workspace_id,
                    thread_id=chat.thread_id,
                    error=type(exc).__name__,
                    detail=str(exc),
                )
                continue
            if outcome == "stale":
                stale += 1
            elif count:
                expired_chats += 1
                expired_files += count
        return RetentionReport(
            chats_checked=checked,
            chats_expired=expired_chats,
            files_expired=expired_files,
            skipped_busy=busy,
            stale=stale,
            failed=failed,
        )

    # --- internals ------------------------------------------------------------------------------

    async def _candidates(self, *, cutoff: datetime) -> AsyncIterator[_Chat]:
        """Every cold chat, read a page at a time and resumed by its ordering key.

        The pass still reaches them all — paging bounds what one query costs and what is held in
        memory, never the sweep's reach. An expiry does not move a chat's activity (WS-24), so a
        swept chat stays in the candidate set and answers "nothing due" cheaply; a page is
        therefore a window on the ordering, and the keyset is what walks it forward.
        """

        after: tuple[datetime, str, str] | None = None
        while True:
            async with self._conn_factory() as conn:
                rows = (
                    (
                        await conn.execute(
                            _CANDIDATES,
                            {
                                "cutoff": cutoff,
                                "limit": self._page_size,
                                "after_activity": None if after is None else after[0],
                                "after_ws": None if after is None else after[1],
                                "after_thread": None if after is None else after[2],
                            },
                        )
                    )
                    .mappings()
                    .all()
                )
            for row in rows:
                after = (row["last_activity"], str(row["workspace_id"]), str(row["thread_id"]))
                yield _Chat(
                    workspace_id=str(row["workspace_id"]),
                    thread_id=str(row["thread_id"]),
                    project_id=str(row["project_id"]),
                    version=int(row["version"]),
                    last_activity=row["last_activity"],
                )
            if len(rows) < self._page_size:
                return

    async def _busy(self, chat: _Chat, *, now: datetime) -> bool:
        work_id = thread_work_id(workspace_id=chat.workspace_id, thread_id=chat.thread_id)
        async with self._conn_factory() as conn:
            return bool((await conn.execute(_BUSY, {"work_id": work_id, "now": now})).scalar_one())

    async def _expire(self, chat: _Chat, *, now: datetime) -> tuple[int, str]:
        """Mark this chat's due entries expired and publish the new version.

        Returns how many entries were expired and the save's status (``"skipped"`` when there was
        nothing due, so no version is burned on a chat that only has outputs left).

        **Due-ness is judged on the activity read here, never on the candidate scan's** (review
        I2). The scan's value is minutes old at scale, and a turn that completed since has left no
        queued task and no live lease for :meth:`_busy` to find — expiring on the stale value
        would mark the files that turn had just written and erase their bytes. The version read in
        the same statement is what the save compare-and-sets on, so the decision and the write are
        anchored to one and the same state of the chat: anything that moves it loses the race
        loudly and is retried tomorrow.
        """

        pointer = await self._store.current(
            workspace_id=chat.workspace_id, thread_id=chat.thread_id
        )
        if pointer is None:
            return 0, "skipped"
        fresh = await self._activity(chat)
        if fresh is None:
            return 0, "skipped"
        version, last_activity = fresh
        if version != pointer.version:
            # A turn saved between the two reads: the file list just read is already superseded.
            return 0, "stale"
        manifest = await self._store.read_manifest(workspace_id=chat.workspace_id, pointer=pointer)
        entries = tuple(
            self._maybe_expire(entry, last_activity=last_activity, now=now)
            for entry in manifest.entries
        )
        count = sum(
            1
            for before, after in zip(manifest.entries, entries, strict=True)
            if before is not after
        )
        if not count:
            return 0, "skipped"
        status, _ = await self._store.save(
            workspace_id=chat.workspace_id,
            project_id=chat.project_id,
            thread_id=chat.thread_id,
            expected_version=version,
            manifest=SnapshotManifest(entries=entries),
            fence=None,
            # Housekeeping on a cold chat is not the chat being used: the version moves and the
            # activity stamp stays exactly where the chat left it. Stamping it and putting the
            # old value back afterwards would revert a ``touch()`` landing in between (I3), and
            # not stamping at all would restart the 48-hour clock every pass.
            activity=False,
        )
        if status != "saved":
            # A turn beat us to the version record. Nothing was expired; tomorrow's pass retries.
            log.info(
                "agent_workspace.retention.not_saved",
                workspace_id=chat.workspace_id,
                thread_id=chat.thread_id,
                status=status,
            )
            return 0, "stale"
        log.info(
            "agent_workspace.retention.expired",
            workspace_id=chat.workspace_id,
            thread_id=chat.thread_id,
            files=count,
        )
        return count, status

    async def _activity(self, chat: _Chat) -> tuple[int, datetime] | None:
        """This chat's version and newest activity, read together — ``None`` when it is gone."""

        async with self._conn_factory() as conn:
            row = (
                await conn.execute(_ACTIVITY, {"ws": chat.workspace_id, "thread": chat.thread_id})
            ).first()
        return None if row is None else (int(row[0]), row[1])

    def _maybe_expire(
        self, entry: SnapshotEntry, *, last_activity: datetime, now: datetime
    ) -> SnapshotEntry:
        """``entry`` itself when it stays, else a copy stamped expired with a receipt.

        An entry saved before Phase 2, or one whose source could not be named, carries no receipt —
        it is expired with :data:`~clue_agents.workspace_snapshot.UNKNOWN_RECEIPT`, because a file
        whose bytes are gone must never read as a blank.
        """

        window = self._windows[entry.tier]
        if entry.expired_at is not None or window is None:
            return entry
        if last_activity + window > now:
            return entry
        return replace(entry, expired_at=now, receipt=entry.receipt or UNKNOWN_RECEIPT)


async def run_retention_if_due(
    conn: AsyncConnection,
    *,
    job: AgentWorkspaceRetentionJob,
    every: timedelta,
    now: datetime | None = None,
) -> RetentionReport | None:
    """Run ``job`` for the whole fleet when the last run is ``every`` old, else ``None``.

    Every fleet worker calls this on its check interval, exactly as
    :func:`~clue_api.storage_wiring.run_orphan_blob_sweep_if_due` is called: the last run's time
    lives in ``maintenance_run`` so a deploy never resets it, and a transaction-scoped advisory
    lock on ``conn`` means one process runs while the others skip. ``None`` means nothing ran —
    not due, or another process has it.

    Unlike the orphan sweep, the work does *not* share ``conn``: the job writes through the
    snapshot store's own transactions. A job that raises therefore propagates with ``conn`` rolled
    back, so the new timestamp is never recorded and tomorrow's check retries; whatever it managed
    to expire before failing simply stays expired, which is the same answer the retry reaches.
    """

    now = now or datetime.now(UTC)
    won = (
        await conn.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": _RETENTION_LOCK},
        )
    ).scalar_one()
    if not won:
        return None
    last = (
        await conn.execute(
            text("SELECT last_run_at FROM maintenance_run WHERE name = :name"),
            {"name": RETENTION_SWEEP},
        )
    ).scalar_one_or_none()
    if last is not None and now - last < every:
        return None
    report = await job.run_once(now=now)
    await conn.execute(
        text(
            "INSERT INTO maintenance_run (name, last_run_at) VALUES (:name, :at) "
            "ON CONFLICT (name) DO UPDATE SET last_run_at = EXCLUDED.last_run_at"
        ),
        {"name": RETENTION_SWEEP, "at": now},
    )
    return report
