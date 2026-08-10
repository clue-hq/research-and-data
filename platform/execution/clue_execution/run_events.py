"""The **non-project-run** half of the durable ``run_event`` stream (Part II D7).

One transport, one auth model, one replay semantics — but *two* thin DALs over the one table, for
an import-contract reason worth stating precisely rather than rediscovering.

**Why this module exists at all (the D7 placement finding).** The project-run writer and the
subject-aware reader live in ``clue_research.durable.run_events`` (run machinery;
``clue_projections`` may import research *read* surfaces by contract, and ``plan_replay`` does).
The design API (``lumen_api``) must also emit onto this stream, and may not import
``clue_research``. The
obvious fix — promote the whole module here and re-export from ``clue_research.durable`` — was
tried and **breaks a contract**: ``clue_execution/__init__`` imports ``clue_execution.worker`` which
imports ``clue_fleet``, so ``clue_research → clue_execution`` is an indirect
``clue_research → clue_fleet`` edge and import-linter rule F1 ("research never imports the fleet
shell (one-way drive seam)") fails. Targeting the submodule instead would keep the linter quiet
while *still* executing ``clue_execution/__init__`` — i.e. importing the fleet — inside a research
import path, which games the rule rather than honouring it. Moving the module here outright is no
better: ``clue_projections`` is contractually forbidden from importing ``clue_execution`` at all
(rule P1, direct imports), so ``plan_replay`` could not read its own stream.

So the seam splits by *who is allowed to import what*, and the duplication is deliberate and
bounded: two INSERT/SELECT statements, one row model, one replay planner. **D8 owns the
consolidation** — the clean end state is a single owner for the whole outbox with ``plan_replay``
taking an injected reader (the dependency inversion rule P1's own comment already endorses), which
costs a frozen-``clue_core`` contract-delta for the row model and so did not belong in this round.
Until then, the parity tests in ``tests/execution/test_run_event_subjects.py`` bind the two DALs
field-for-field, topic-for-topic and plan-for-plan, so they cannot drift silently.

**What is enforced here.** A design emitter may write only ``design.*`` topics — the guard is loud,
because a design leg that could stamp ``run.phase.completed`` would inject a fake project-run
lifecycle event into a client's project stream. The DB CHECK stops it from *also* claiming a
project-run subject; this stops it from claiming a project-run *topic*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ExecutionId, ProjectRunId, UtcDatetime, decode_jsonb, serialize_value_json

#: Mirrors ``clue_research.durable.run_events`` (which this package may not import). A parity test
#: binds the two.
PROJECT_RUN_SUBJECT_KIND = "project_run"
DESIGN_RUN_SUBJECT_KIND = "design_run"

#: The only topics :func:`emit_design_run_event` will write. The fine-grained design ``event_type``
#: rides in the payload; these three are the coarse routing classes.
DESIGN_RUN_EVENT_TOPICS: tuple[str, ...] = (
    "design.run.event",
    "design.run.completed",
    "design.run.failed",
)

_EVENT_COLUMNS = (
    "seq, workspace_id, subject_kind, subject_id, run_id, execution_id, topic, payload, created_at"
)

_EMIT_SUBJECT_SQL = text(
    f"""
    INSERT INTO run_event
        (workspace_id, subject_kind, subject_id, run_id, execution_id, topic, payload)
    VALUES (
        :workspace_id, :subject_kind, :subject_id, NULL, :execution_id,
        :topic, CAST(:payload AS jsonb)
    )
    RETURNING {_EVENT_COLUMNS}
    """
)


class RunEventRow(BaseModel):
    """One persisted ``run_event`` row, as this DAL sees it — field-identical to
    ``clue_research.durable.RunEventRow`` (pinned by a parity test), because it is the same row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    workspace_id: str
    subject_kind: str
    subject_id: str
    run_id: ProjectRunId | None = None
    execution_id: ExecutionId | None = None
    topic: str
    payload: dict[str, JsonValue]
    created_at: UtcDatetime


class InvalidRunEventSubject(ValueError):
    """A subject emitter was handed a topic or an id it may not write."""


async def emit_design_run_event(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    design_run_id: str,
    topic: str,
    payload: dict[str, JsonValue] | None = None,
    execution_id: ExecutionId | None = None,
) -> RunEventRow:
    """Append one **design-leg** event to the durable outbox and return the persisted row.

    Stamps ``subject_kind='design_run'``, ``subject_id=design_run_id``, ``run_id=NULL`` — the shape
    the ``run_event_subject_coherent`` CHECK requires of every non-project subject, so a design
    event can never be mistaken for (or masquerade as) a project run.

    Transactional in the caller's connection; ``seq`` is assigned by the DB. Refuses loudly on a
    blank ``design_run_id`` or a topic outside :data:`DESIGN_RUN_EVENT_TOPICS` — a design emitter
    that could write ``run.phase.completed`` would forge project-run lifecycle events on a client's
    project stream, so this is a refusal, not a coercion."""
    if not design_run_id.strip():
        raise InvalidRunEventSubject("design_run_id must be a non-empty subject id")
    if topic not in DESIGN_RUN_EVENT_TOPICS:
        raise InvalidRunEventSubject(
            f"topic {topic!r} is not a design run-event topic "
            f"(allowed: {', '.join(DESIGN_RUN_EVENT_TOPICS)})"
        )
    row = (
        (
            await conn.execute(
                _EMIT_SUBJECT_SQL,
                {
                    "workspace_id": workspace_id,
                    "subject_kind": DESIGN_RUN_SUBJECT_KIND,
                    "subject_id": design_run_id,
                    "execution_id": execution_id,
                    "topic": topic,
                    "payload": serialize_value_json(payload if payload is not None else {}),
                },
            )
        )
        .mappings()
        .one()
    )
    return _row_to_event(dict(row))


async def list_subject_run_events(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_kind: str,
    subject_id: str,
    after_seq: int = 0,
    limit: int = 1000,
) -> list[RunEventRow]:
    """Read one subject's events in ``seq`` order — the replay/tail surface, index-served by
    ``run_event_workspace_subject_seq``. Filters ``seq > after_seq`` within ``workspace_id``
    (tenant scoping is not optional here: the subject filter alone would still be cross-tenant).
    Read-only."""
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_EVENT_COLUMNS} FROM run_event "
                    "WHERE workspace_id = :ws AND subject_kind = :kind AND subject_id = :sid "
                    "AND seq > :after_seq ORDER BY seq LIMIT :limit"
                ),
                {
                    "ws": workspace_id,
                    "kind": subject_kind,
                    "sid": subject_id,
                    "after_seq": after_seq,
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return [_row_to_event(dict(r)) for r in rows]


async def subject_event_created_at(
    conn: AsyncConnection, *, workspace_id: str, seq: int
) -> UtcDatetime | None:
    """The ``created_at`` of the tenant's event at ``seq`` (the replay-horizon check). ``None`` when
    the tenant has no such event — an unknown/aged-out cursor, treated conservatively as a reset."""
    row = (
        await conn.execute(
            text("SELECT created_at FROM run_event WHERE workspace_id = :ws AND seq = :seq"),
            {"ws": workspace_id, "seq": seq},
        )
    ).one_or_none()
    return row[0] if row is not None else None


@dataclass(frozen=True, slots=True)
class SubjectReplayPlan:
    """The subject-stream twin of ``clue_projections.ReplayPlan`` — same three fields, same
    meanings, same reset rule (on reset ``effective_cursor`` is **0**, never the consumer's bogus
    cursor, which as a tail floor would silently match nothing forever)."""

    reset: bool
    backlog: tuple[RunEventRow, ...]
    effective_cursor: int


async def plan_subject_replay(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_kind: str,
    subject_id: str,
    last_event_id: int | None,
    horizon_s: float,
    now: datetime | None = None,
    limit: int = 1000,
) -> SubjectReplayPlan:
    """Plan a reconnecting consumer's replay over one subject's stream.

    Semantics are identical to ``clue_projections.plan_replay`` by construction (and by a parity
    test): no cursor ⇒ full backlog, no reset; a cursor within the horizon ⇒ gapless
    ``seq > cursor``; a cursor older than the horizon or unknown ⇒ reset, cursor drops to 0, and
    both backlog and tail restart from the beginning. Read-only."""
    cursor = last_event_id if last_event_id is not None and last_event_id > 0 else 0
    reset = False
    if cursor > 0:
        moment = now if now is not None else datetime.now(UTC)
        cutoff = moment - timedelta(seconds=horizon_s)
        cursor_ts = await subject_event_created_at(conn, workspace_id=workspace_id, seq=cursor)
        reset = cursor_ts is None or cursor_ts < cutoff
    effective_cursor = 0 if reset else cursor
    backlog = await list_subject_run_events(
        conn,
        workspace_id=workspace_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        after_seq=effective_cursor,
        limit=limit,
    )
    return SubjectReplayPlan(reset=reset, backlog=tuple(backlog), effective_cursor=effective_cursor)


def _row_to_event(row: dict[str, object]) -> RunEventRow:
    return RunEventRow.model_validate(
        {
            "seq": row["seq"],
            "workspace_id": row["workspace_id"],
            "subject_kind": row["subject_kind"],
            "subject_id": row["subject_id"],
            "run_id": row["run_id"],
            "execution_id": row["execution_id"],
            "topic": row["topic"],
            "payload": decode_jsonb(row["payload"]),
            "created_at": row["created_at"],
        }
    )
