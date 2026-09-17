"""Read projection over the detached research a *conversation turn* launched.

FI Lane D slice **D5-close**, charter §3.4's ``task`` floor. The gate projection
(:mod:`clue_projections.gates`) answers "which run did this approval authorize?"; this one answers
the question that follows it and that a task card actually renders: *how is that run going, right
now, counted over its jobs.*

Everything here is a join over rows that already exist, and the join key is the same durable receipt
the launcher persisted — the ``turn-action:<turn_id>`` reference the confirming turn made durable.
A conversation turn therefore asks "what did **I** launch?" without the agent, the toolbelt or the
stream having to carry a run id around: the receipt on the launch-control row *is* the link.

Two launch-control tables, one union, because both launchers stamp the same receipt: account
research writes ``entity_research_account_fleet`` (M8D R6), contact research writes
``entity_research_contact_launch`` (M8D R7). A caller asking about a turn gets whichever the turn
actually produced, and a turn that launched nothing gets an empty tuple — never a fabricated card.

The counts are over ``entity_research_job``, which is the only place a per-subject outcome exists.
"Partial" is a *finalization outcome*, not a state: a job that exhausted its budget finished, but
not with everything asked of it, and reporting it as ``completed`` would be the one lie a progress
card must never tell. ``needs_review`` is counted separately from ``partial`` for the same reason
they are separate outcomes: a reviewable subject is work a *human* can pick up, not a shortfall to
be re-run, and folding the two made them indistinguishable to every consumer downstream.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from clue_db import ConnFactory, transaction

__all__ = [
    "ResearchTaskCounts",
    "ResearchTaskView",
    "research_tasks_for_action_refs",
]


class ResearchTaskCounts(BaseModel):
    """Per-subject job tally of one run — §3.4's ``task`` counts, projected from durable rows.

    Mirrors ``clue_api.chat.turn_parts.TaskCounts`` member for member. It is spelled twice on
    purpose: the projections package may not import the API package (the read side is downstream of
    nothing), and a shared dict would give up the typing that makes the mapping checkable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int = Field(default=0, ge=0)
    queued: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    partial: int = Field(default=0, ge=0)
    #: Finished, reviewable, and *actionable by a human* — the one terminal outcome that names a
    #: queue rather than a shortfall, which is why it is counted apart from ``partial``.
    needs_review: int = Field(default=0, ge=0)
    blocked: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)


class ResearchTaskView(BaseModel):
    """One launched research run as one visible task, at 1 subject or at 500."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    research_run_id: str
    run_kind: str
    #: ``entity_research_run.state`` verbatim — ``queued``/``running``/``waiting_external``/
    #: ``terminal``. Mapped onto the §3.4 vocabulary by the surface that renders it, never here.
    run_state: str
    source_action_ref: str
    counts: ResearchTaskCounts


#: Both launch-control tables carry ``(workspace_id, source_action_ref)``; the union is what makes
#: "what did this turn launch?" one question rather than one question per run kind.
_TASKS_SQL = text(
    """
    WITH launched AS (
        SELECT research_run_id, workspace_id, source_action_ref
        FROM entity_research_account_fleet
        WHERE workspace_id = :workspace_id
          AND source_action_ref = ANY(CAST(:action_refs AS text[]))
        UNION ALL
        SELECT research_run_id, workspace_id, source_action_ref
        FROM entity_research_contact_launch
        WHERE workspace_id = :workspace_id
          AND source_action_ref = ANY(CAST(:action_refs AS text[]))
    )
    SELECT r.research_run_id,
           r.run_kind,
           r.state AS run_state,
           l.source_action_ref,
           count(j.job_id) AS total,
           count(*) FILTER (WHERE j.state = 'queued') AS queued,
           count(*) FILTER (WHERE j.state IN ('leased', 'running')) AS running,
           count(*) FILTER (WHERE j.state = 'waiting_external') AS blocked,
           count(*) FILTER (
               WHERE j.state = 'terminal' AND j.finalization_outcome = 'completed'
           ) AS completed,
           count(*) FILTER (
               WHERE j.state = 'terminal'
                 AND j.finalization_outcome IN ('exhausted', 'budget_stopped')
           ) AS partial,
           count(*) FILTER (
               WHERE j.state = 'terminal' AND j.finalization_outcome = 'needs_review'
           ) AS needs_review,
           count(*) FILTER (
               WHERE j.state = 'terminal'
                 AND j.finalization_outcome IN ('cancelled', 'failed')
           ) AS failed
    FROM launched l
    JOIN entity_research_run r
      ON r.research_run_id = l.research_run_id AND r.workspace_id = l.workspace_id
    LEFT JOIN entity_research_job j
      ON j.research_run_id = r.research_run_id AND j.workspace_id = r.workspace_id
    GROUP BY r.research_run_id, r.run_kind, r.state, l.source_action_ref, r.created_at
    ORDER BY r.created_at, r.research_run_id
    """
)


async def research_tasks_for_action_refs(
    *,
    workspace_id: str,
    action_refs: tuple[str, ...],
    conn_factory: ConnFactory = transaction,
) -> tuple[ResearchTaskView, ...]:
    """Every research run those human-action receipts launched, oldest first.

    One query for a set of receipts rather than one per receipt, for the same reason
    :func:`~clue_projections.gates.open_gate_kinds_for_threads` batches: the caller usually holds a
    page of turns, and a per-turn read would cost a query per message.
    """

    if not action_refs:
        return ()
    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    _TASKS_SQL,
                    {"workspace_id": workspace_id, "action_refs": list(action_refs)},
                )
            )
            .mappings()
            .all()
        )
    return tuple(
        ResearchTaskView(
            research_run_id=str(row["research_run_id"]),
            run_kind=str(row["run_kind"]),
            run_state=str(row["run_state"]),
            source_action_ref=str(row["source_action_ref"]),
            counts=ResearchTaskCounts(
                total=int(row["total"]),
                queued=int(row["queued"]),
                running=int(row["running"]),
                completed=int(row["completed"]),
                partial=int(row["partial"]),
                needs_review=int(row["needs_review"]),
                blocked=int(row["blocked"]),
                failed=int(row["failed"]),
            ),
        )
        for row in rows
    )
