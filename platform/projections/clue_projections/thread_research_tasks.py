"""The durable research-task read of one *thread* — Slice C **C2**, the live source a card polls.

:mod:`clue_projections.research_tasks` answers "what did this **turn** launch, and how is it
going?", and D5 emits exactly that once, at turn close, as a ``task`` part on the turn's SSE stream.
Then the stream ends and the fleet keeps working — for minutes, across dozens of accounts. Without a
read like this one, the progress card the founder is watching is frozen at whatever the last frame
said, and the only way to refresh it is to start another turn.

So this module widens the same join from one turn to a whole thread and adds the two facts a
*poller* needs that a single stream frame does not:

* **``revision``** — the run's high-water mark in ``entity_research_job_event``, whose ``event_seq``
  is a globally monotonic identity column (migration ``022b1154b3aa``). The transcript reducer
  merges parts highest-revision-wins, so the number must rise whenever the fleet actually moved,
  and it must be comparable against the revision the turn-close snapshot carried. The job-event
  ledger is the only thing in the schema with both properties: the job rows carry no version, and
  a timestamp is neither dense nor comparable across clocks. Launch writes each job's initial
  queued event in the same transaction, so a visible task always has a revision of at least one;
  a missing ledger row is corruption and fails the read rather than emitting a task the frontend's
  canonical ``revision >= 1`` schema would refuse.
* **``field_progress``** — the per-account field tally summed over the *latest* coverage row of
  each settled job. It is what makes a five-minute account feel alive: the job is still one job,
  but the fields inside it are landing. ``None`` — not zero — until a job has published coverage,
  and ``None`` for a contact run, whose coverage surface Slice F owns; a zeroed progress reading
  and "nothing published yet" are different facts and a card must not conflate them.

Everything is still a join over rows that already exist, and the join key is unchanged: the
``turn-action:<turn_id>`` receipt the launcher persisted. The thread contributes only the *set* of
turns to ask about, taken from both halves of a turn's identity (``agent_turn``, written by the
worker, and ``agent_turn_submission``, written by the route) — because a launch is routinely
authorized by a human gate-answer turn that has a submission and no ``agent_turn`` row of its own,
and asking only the worker's half would silently lose exactly the runs this card exists to show.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from clue_db import ConnFactory, transaction
from clue_projections.research_tasks import ResearchTaskView, research_tasks_for_action_refs

__all__ = [
    "ResearchFieldProgress",
    "ThreadResearchTaskView",
    "thread_research_tasks",
]

#: Mirrors ``clue_api.turn_action.TURN_ACTION_PREFIX``. Spelled twice for the same reason
#: :class:`~clue_projections.research_tasks.ResearchTaskCounts` mirrors ``TaskCounts``: the
#: projections package may not import the API package. The canonical lowercase-hyphenated spelling
#: of :class:`~uuid.UUID` is the one ``derive_turn_action_ref`` mints, so a ref built here and a ref
#: built at the tool seam are the same string — pinned by a drift test in the C2 suite.
_TURN_ACTION_PREFIX = "turn-action:"

#: Both halves of a turn's identity (Lane D2 split it in two), because a launch's authorizing turn
#: may exist in either. ``UNION`` rather than ``UNION ALL``: the same turn usually appears in both.
_THREAD_TURN_IDS_SQL = text(
    """
    SELECT id AS turn_id
    FROM agent_turn
    WHERE workspace_id = :workspace_id
      AND project_id = :project_id
      AND thread_id = :thread_id
    UNION
    SELECT turn_id
    FROM agent_turn_submission
    WHERE workspace_id = :workspace_id
      AND project_id = :project_id
      AND thread_id = :thread_id
    """
)

#: One statement for every run on the page, keyed off the run ids the task projection already
#: resolved — a per-run read would cost two round trips per card on a three-second poll.
#:
#: The coverage lateral is ``DISTINCT ON (job_id) … ORDER BY job_id, created_at DESC, coverage_id
#: DESC``: ``entity_research_account_coverage`` has no uniqueness beyond its primary key, and a job
#: that re-finalizes *appends* a row rather than updating one. That is the same latest-wins ordering
#: ``clue_api.account_research_coverage.read_account_coverage_in_run`` and the R6 projection use, so
#: the per-account read and this aggregate can never disagree about which row is current.
_DECORATIONS_SQL = text(
    """
    SELECT run.research_run_id,
           events.revision,
           COALESCE(coverage.jobs_covered, 0) AS jobs_covered,
           COALESCE(coverage.fields_completed, 0) AS fields_completed,
           COALESCE(coverage.fields_unresolved, 0) AS fields_unresolved
    FROM unnest(CAST(:run_ids AS uuid[])) AS run(research_run_id)
    LEFT JOIN LATERAL (
        SELECT max(e.event_seq) AS revision
        FROM entity_research_job_event e
        JOIN entity_research_job j ON j.job_id = e.job_id
        WHERE j.research_run_id = run.research_run_id
          AND j.workspace_id = :workspace_id
    ) events ON TRUE
    LEFT JOIN LATERAL (
        SELECT count(*) AS jobs_covered,
               sum(cardinality(latest.completed_field_keys)) AS fields_completed,
               sum(cardinality(latest.unresolved_field_keys)) AS fields_unresolved
        FROM (
            SELECT DISTINCT ON (c.job_id)
                   c.completed_field_keys, c.unresolved_field_keys
            FROM entity_research_account_coverage c
            JOIN entity_research_job j
              ON j.job_id = c.job_id AND j.workspace_id = c.workspace_id
            WHERE c.research_run_id = run.research_run_id
              AND c.workspace_id = :workspace_id
              AND j.state = 'terminal'
            ORDER BY c.job_id, c.created_at DESC, c.coverage_id DESC
        ) latest
    ) coverage ON TRUE
    """
)

#: Field-level coverage exists only for account research; the contact surface is Slice F's.
_FIELD_PROGRESS_RUN_KIND = "account_research"


class ResearchFieldProgress(BaseModel):
    """Fields landed vs. fields honestly given up on, summed across a run's settled subjects.

    ``unresolved`` is not a failure count. A supported provider that returned nothing is a correct
    empty field, and saying so is the whole point of reporting it next to ``completed`` rather than
    reporting a percentage that quietly rounds it away.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    completed: int = Field(default=0, ge=0)
    unresolved: int = Field(default=0, ge=0)


class ThreadResearchTaskView(BaseModel):
    """One launched run as one pollable task: the D5 task view, plus what a poller needs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task: ResearchTaskView
    #: ``max(entity_research_job_event.event_seq)`` over the run's jobs; launch guarantees >= 1.
    revision: int = Field(ge=1)
    #: ``None`` before any coverage exists, and for a contact run — never a fabricated zero.
    field_progress: ResearchFieldProgress | None = None


async def thread_research_tasks(
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    conn_factory: ConnFactory = transaction,
) -> tuple[ThreadResearchTaskView, ...]:
    """Every research run this thread's turns launched, oldest first, decorated for polling.

    Three statements, not one per turn and not one per run: the thread's turn ids, the C1 task
    projection over their receipts, and one aggregate over the runs it found. A thread that
    launched nothing returns an empty tuple — the honest answer, and the reason the HTTP surface
    can serve an empty list rather than a not-found.
    """

    async with conn_factory() as conn:
        turn_ids = (
            await conn.execute(
                _THREAD_TURN_IDS_SQL,
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "thread_id": thread_id,
                },
            )
        ).scalars()
        action_refs = tuple(_turn_action_ref(turn_id) for turn_id in turn_ids)

    tasks = await research_tasks_for_action_refs(
        workspace_id=workspace_id,
        action_refs=action_refs,
        conn_factory=conn_factory,
    )
    if not tasks:
        return ()

    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    _DECORATIONS_SQL,
                    {
                        "workspace_id": workspace_id,
                        "run_ids": [task.research_run_id for task in tasks],
                    },
                )
            )
            .mappings()
            .all()
        )
    decorations = {str(row["research_run_id"]): row for row in rows}

    views: list[ThreadResearchTaskView] = []
    for task in tasks:
        row = decorations.get(task.research_run_id)
        if row is None or row["revision"] is None:
            raise RuntimeError(
                f"research task {task.research_run_id} has no durable job-event revision"
            )
        covered = int(row["jobs_covered"])
        views.append(
            ThreadResearchTaskView(
                task=task,
                revision=int(row["revision"]),
                field_progress=(
                    ResearchFieldProgress(
                        completed=int(row["fields_completed"]),
                        unresolved=int(row["fields_unresolved"]),
                    )
                    if row is not None and covered > 0 and task.run_kind == _FIELD_PROGRESS_RUN_KIND
                    else None
                ),
            )
        )
    return tuple(views)


def _turn_action_ref(turn_id: UUID | str) -> str:
    """The canonical ``turn-action:<uuid>`` receipt for a turn id read out of a durable row."""

    return f"{_TURN_ACTION_PREFIX}{UUID(str(turn_id))}"
