"""The ``run_event`` outbox — the platform's one durable run-visibility DAL (PB-B4 slice 3; D7; D8).

This is the **write and read layer** for the per-workspace SSE run-event log (REQ-11 / A5). Every
run-lifecycle event any drive path observes — a project phase started, a per-step timeline tick, a
design turn's progress frame, a run finishing — is appended here as one durable row, and the SSE
surfaces (``clue_api`` for project runs, ``lumen_api`` for design runs) fan those rows out with
gapless ``Last-Event-ID`` replay.

**Single ownership (Part II D8).** D7 shipped this as *two* thin DALs over one table — the
project-run half in ``clue_research.durable.run_events``, the design/subject half here — because
``clue_research`` may not reach ``clue_execution`` transitively (rule F1: ``clue_execution``'s
``__init__`` imports the fleet) and ``clue_projections`` may not import it at all (rule P1). D8
collapses the duplication by *inverting* the read dependency instead of relocating code: the shared
shapes and the replay planner moved to ``clue_core.run_event`` (the contract-delta D7 priced), the
statements live here and nowhere else, and ``plan_replay`` reaches its rows through the
:class:`~clue_core.RunEventReader` seam whose only concrete implementation is
:class:`DbRunEventReader` below, injected at a composition root.
``clue_research.durable.run_events`` is deleted; nothing in ``clue_research`` ever called it.

**Ordering + replay.** ``seq`` is a plain ``bigserial`` — **globally** monotone, so a workspace's
rows form a strictly-increasing subsequence (the documented **per-workspace ordering** guarantee).
The SSE envelope's ``id`` is this ``seq``; a reconnecting consumer replays with ``seq > cursor``
within one ``(workspace_id[, subject])``. Emission is **at-least-once** and **seq-idempotent** (a
consumer dedups by ``seq``); a crash between the drive commit and the emit simply drops that event
(the durable ``project_run`` / projection stays the authoritative truth a consumer can re-read).

**Subjects (Part II D7).** The stream's key used to *be* a project run (``run_id uuid NOT NULL``).
It is now a **subject** — ``(subject_kind, subject_id)``. ``subject_kind = 'project_run'`` keeps
``run_id`` populated with ``subject_id = run_id::text`` (a DB CHECK, so a project-run event can
never lie about its subject); every other kind carries ``run_id IS NULL`` (so a non-project event
can never fake a project run). ``subject_id`` is ``text`` because subject id *shapes* differ — a
design run id is ``run_<uuid4 hex>``, not a uuid.

**What is enforced here.** A design emitter may write only ``design.*`` topics — the guard is loud,
because a design leg that could stamp ``run.phase.completed`` would inject a fake project-run
lifecycle event into a client's project stream. The DB CHECK stops it from *also* claiming a
project-run subject; :func:`emit_design_run_event` stops it from claiming a project-run *topic*.

**One-directional (run machinery → transport).** Nothing a consumer does writes back through here
(conventions §6 — never a claim-store write-back path).

**Retention (Part II D8, ruling R-D8-4).** The table still has no FK to a subject and no CASCADE,
and **project-run rows are never deleted by anything**. The one sweep that exists is deliberately
narrow: :func:`prune_design_run_progress_events` deletes the *progress* rows
(``topic = 'design.run.event'``) of one **design** subject, and only when that subject still holds a
terminal row. It exists because design payloads are heavy (a compile event carries its whole
applied-``operations`` array) and a chatty turn emits dozens, so the design half of the table is the
only half that grows without bound.

Two constraints the sweep is built around, both structural rather than configurable:

* **A terminal row must never be deleted.** The design SSE serve loop closes a stream only on the
  terminal event it reads from this table — D8 deleted the run-row liveness net that used to cover
  for a missing one — so removing one would silently reintroduce hang-forever streams with nothing
  left to catch them. The statement below cannot express that deletion: it filters on the progress
  topic and additionally *requires* a surviving terminal row.
* **The standing [B4×SSE] reset-then-backlog question is settled by scope, not by argument.** The
  project stream is untouched, so its post-reset backlog stays complete. On the design stream the
  eligibility floors (only terminal runs, only after a retention window that strictly exceeds the
  replay horizon) mean a cursor young enough to be replayed gaplessly points at a run too young to
  prune — and a cursor older than the horizon is reset to 0 anyway, where the surviving terminal row
  still closes the stream correctly. See ``lumen_api.event_pruner`` for the eligibility half and the
  floors it enforces.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    DESIGN_RUN_EVENT_TOPICS,
    DESIGN_RUN_SUBJECT_KIND,
    PROJECT_RUN_SUBJECT_KIND,
    ExecutionId,
    ProjectRunId,
    RunEventRow,
    RunEventTopic,
    UtcDatetime,
    decode_jsonb,
    serialize_value_json,
)

_EVENT_COLUMNS = (
    "seq, workspace_id, subject_kind, subject_id, run_id, execution_id, topic, payload, created_at"
)

_EMIT_SQL = text(
    f"""
    INSERT INTO run_event
        (workspace_id, subject_kind, subject_id, run_id, execution_id, topic, payload)
    VALUES (
        :workspace_id, '{PROJECT_RUN_SUBJECT_KIND}', :subject_id, :run_id, :execution_id,
        :topic, CAST(:payload AS jsonb)
    )
    RETURNING {_EVENT_COLUMNS}
    """
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


class InvalidRunEventSubject(ValueError):
    """A subject emitter was handed a topic or an id it may not write."""


# --- writing --------------------------------------------------------------------------------


async def emit_run_event(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: ProjectRunId,
    topic: str,
    payload: dict[str, JsonValue] | None = None,
    execution_id: ExecutionId | None = None,
) -> RunEventRow:
    """Append one **project-run** event to the durable outbox and return the persisted row.

    Called by composition-root run/execution writers. Transactional in the caller's connection;
    ``seq`` is assigned by the DB (globally monotone → per-workspace ordering). Emission is
    at-least-once / seq-idempotent.

    D7 left this signature and its semantics **exactly** as they were: every existing project-run
    call site is untouched, and the widened subject columns are stamped here
    (``subject_kind='project_run'``, ``subject_id=str(run_id)``) rather than being a caller's
    concern. D8 moved the function to this module without touching the statement."""
    row = (
        (
            await conn.execute(
                _EMIT_SQL,
                {
                    "workspace_id": workspace_id,
                    "subject_id": str(run_id),
                    "run_id": run_id,
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
    blank ``design_run_id`` or a topic outside ``DESIGN_RUN_EVENT_TOPICS`` — a design emitter that
    could write ``run.phase.completed`` would forge project-run lifecycle events on a client's
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


# --- reading --------------------------------------------------------------------------------


async def list_run_events(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: ProjectRunId | None = None,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    execution_id: ExecutionId | None = None,
    after_seq: int = 0,
    limit: int = 1000,
) -> list[RunEventRow]:
    """Read a tenant's run events in ``seq`` order (the SSE replay surface).

    Filters ``seq > after_seq`` (the ``Last-Event-ID`` cursor; ``0`` ⇒ from the beginning) within
    ``workspace_id``, optionally narrowed to one **subject**. ``limit`` bounds one page.
    Read-only — issues no writes (the D7 MVCC-only discipline the SSE surface depends on).

    Two ways to name a subject, both back-compatible:

    * ``run_id=`` — the pre-D7 per-project-run stream, unchanged (index-served by
      ``run_event_workspace_run_seq``).
    * ``subject_kind=`` / ``subject_id=`` — the D7 general form, served by
      ``run_event_workspace_subject_seq``. Passing ``subject_kind`` alone narrows to a whole
      kind (every design leg in the workspace); passing ``subject_id`` alone is refused, because
      subject ids are only unique *within* a kind and an unkinded id filter would silently
      collide across taxonomies.

    Tenant scoping is not optional: the subject filter alone would still be cross-tenant.
    """
    if subject_id is not None and subject_kind is None:
        raise ValueError("subject_id filter requires subject_kind (ids are unique per kind only)")
    clauses = "".join(
        (
            "AND run_id = :run_id " if run_id is not None else "",
            "AND subject_kind = :subject_kind " if subject_kind is not None else "",
            "AND subject_id = :subject_id " if subject_id is not None else "",
            "AND execution_id = :execution_id " if execution_id is not None else "",
        )
    )
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_EVENT_COLUMNS} FROM run_event "
                    "WHERE workspace_id = :ws AND seq > :after_seq "
                    f"{clauses}"
                    "ORDER BY seq LIMIT :limit"
                ),
                {
                    "ws": workspace_id,
                    "after_seq": after_seq,
                    "limit": limit,
                    **({"run_id": run_id} if run_id is not None else {}),
                    **({"subject_kind": subject_kind} if subject_kind is not None else {}),
                    **({"subject_id": subject_id} if subject_id is not None else {}),
                    **({"execution_id": execution_id} if execution_id is not None else {}),
                },
            )
        )
        .mappings()
        .all()
    )
    return [_row_to_event(dict(r)) for r in rows]


async def event_created_at(
    conn: AsyncConnection, *, workspace_id: str, seq: int
) -> UtcDatetime | None:
    """The ``created_at`` of the tenant's event at ``seq`` (the replay-horizon check: a reconnecting
    cursor whose event is older than the horizon gets a reset). ``None`` when the tenant has no such
    event — an unknown / aged-out cursor, which every surface treats conservatively as a reset."""
    row = (
        await conn.execute(
            text("SELECT created_at FROM run_event WHERE workspace_id = :ws AND seq = :seq"),
            {"ws": workspace_id, "seq": seq},
        )
    ).one_or_none()
    return row[0] if row is not None else None


# --- retention ------------------------------------------------------------------------------

#: The design leg's PROGRESS topic — the only topic this module will ever delete.
_DESIGN_PROGRESS_TOPIC = RunEventTopic.DESIGN_RUN_EVENT.value

#: The two design terminal topics. Never deleted, and their *presence* is a precondition of the
#: delete: pruning a subject that has no terminal row would leave a stream that never closes.
_DESIGN_TERMINAL_TOPICS = tuple(t for t in DESIGN_RUN_EVENT_TOPICS if t != _DESIGN_PROGRESS_TOPIC)

# Workspace-leading, like every index on this table. The EXISTS is the terminal-row precondition;
# the topic equality is the never-delete-a-terminal floor. Neither is a parameter — a caller cannot
# widen this statement into one that removes a terminal row or another subject kind's rows.
_PRUNE_DESIGN_PROGRESS_SQL = text(
    f"""
    DELETE FROM run_event AS victim
    WHERE victim.workspace_id = :ws
      AND victim.subject_kind = '{DESIGN_RUN_SUBJECT_KIND}'
      AND victim.subject_id   = :subject_id
      AND victim.topic        = '{_DESIGN_PROGRESS_TOPIC}'
      AND EXISTS (
        SELECT 1 FROM run_event AS terminal
        WHERE terminal.workspace_id = victim.workspace_id
          AND terminal.subject_kind = victim.subject_kind
          AND terminal.subject_id   = victim.subject_id
          AND terminal.topic IN ({", ".join(f"'{t}'" for t in _DESIGN_TERMINAL_TOPICS)})
      )
    """
)


async def prune_design_run_progress_events(
    conn: AsyncConnection, *, workspace_id: str, subject_id: str
) -> int:
    """Delete one **design** subject's progress rows, keeping its terminal row(s); return the count.

    The row-deletion half of the D8 design-event pruner (``lumen_api.event_pruner`` owns the
    eligibility half — which runs are terminal, and terminal for long enough). Split that way so
    the outbox keeps exactly one SQL owner (R-D8-1) while the "is this run prunable?" question
    stays in the design domain, which is the only place that can answer it.

    **What this cannot do, by construction rather than by convention:** it cannot delete a terminal
    row (the topic filter is a literal, not a parameter), cannot touch a ``project_run`` subject (so
    the platform stream's reset-then-backlog completeness is untouched), and cannot leave a subject
    with no terminal row (the ``EXISTS`` refuses the whole delete for a subject that has none —
    which for a design run means it is not finished, or finished before the D7 outbox existed).

    Because the terminal event is a design run's *last* durable write, the rows removed here are a
    contiguous **prefix** of the subject's seq range: no mid-range hole is ever created, so a
    reader replaying this subject sees progress-then-terminal or terminal-only, never a gap
    followed by more progress.

    Idempotent: a second call on the same subject deletes nothing. Transactional in the caller's
    connection.
    """
    result = await conn.execute(
        _PRUNE_DESIGN_PROGRESS_SQL, {"ws": workspace_id, "subject_id": subject_id}
    )
    return int(result.rowcount)


@dataclass(frozen=True, slots=True)
class DbRunEventReader:
    """The one concrete :class:`~clue_core.RunEventReader` — this DAL, bound to a connection and a
    stream selection, so ``clue_core.plan_replay`` can plan a replay without knowing either.

    Built at a composition root (``clue_api``'s SSE endpoint for a project run; ``lumen_api``'s
    ``run_stream`` for a design run) and injected. That injection is what lets ``clue_projections``
    re-export the planner it is forbidden from importing a reader for (rule P1), and what makes
    "one replay semantics" structural rather than parity-tested.

    Name the selection exactly as :func:`list_run_events` does — ``run_id=`` or
    ``subject_kind=``/``subject_id=``; naming neither plans over the whole workspace stream."""

    conn: AsyncConnection
    workspace_id: str
    run_id: ProjectRunId | None = None
    subject_kind: str | None = None
    subject_id: str | None = None

    async def cursor_created_at(self, seq: int) -> UtcDatetime | None:
        return await event_created_at(self.conn, workspace_id=self.workspace_id, seq=seq)

    async def events_after(self, *, after_seq: int, limit: int) -> Sequence[RunEventRow]:
        return await list_run_events(
            self.conn,
            workspace_id=self.workspace_id,
            run_id=self.run_id,
            subject_kind=self.subject_kind,
            subject_id=self.subject_id,
            after_seq=after_seq,
            limit=limit,
        )


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
