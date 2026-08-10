"""The ``run_event`` outbox — the durable per-workspace SSE run-event log (PB-B4 slice 3, D8).

This generalizes the M12.3 ``handoff_event`` outbox (``narrative/handoff_events.py``) from a single
terminal seam into the platform's **run visibility** substrate (REQ-11 / A5). Every run-lifecycle
event the drive path observes — a phase started, a phase completed, a per-step timeline tick, the
run finishing — is appended here as one durable row, and the SSE surface (``clue_api``) fans those
rows out to a client's ``EventSource`` with gapless ``Last-Event-ID`` replay.

**Why it lives in ``durable`` (run-machinery), not in projections.** ``run_event`` is written at
the run-drive boundary and by C5's execution-journal transport adapter — writes, so it cannot live
in the read-only ``clue_projections`` package. It is genuine run machinery — the same species as
``project_run`` / ``project_phase_checkpoint`` this module's sibling owns — so the write helper
(:func:`emit_run_event`) and the read helpers
(:func:`list_run_events` / :func:`event_created_at`) live here, exactly mirroring where the
``handoff_event`` outbox lives (in ``narrative``, a research package). ``clue_api`` (the composition
root) calls :func:`emit_run_event` from the drive path; ``clue_projections`` imports the *read*
helpers (a research read surface — allowed by its import contract). The emitter therefore never
enters ``clue_projections``.

**Ordering + replay.** ``seq`` is a plain ``bigserial`` — **globally** monotone, so a workspace's
rows form a strictly-increasing subsequence (the documented **per-workspace ordering** guarantee).
The SSE envelope's ``id`` is this ``seq``; a reconnecting consumer replays with ``seq > cursor``
within one ``(workspace_id[, run_id])``. Emission is **at-least-once** and **seq-idempotent** (a
consumer dedups by ``seq``); a crash between the drive commit and the emit simply drops that event
(the durable ``project_run`` / projection stays the authoritative truth a consumer can re-read).

**Durability boundary.** Legacy phase-event emission remains a post-drive best-effort append. C5
execution events use the same caller connection for authoritative ``execution_event``, cursor CAS,
and this transport row, so those three writes commit or roll back together.

**One-directional (run machinery → transport).** Nothing a consumer does writes back through here
(conventions §6 — never a claim-store write-back path).

**Subjects (Part II D7).** The stream's key used to *be* a project run (``run_id uuid NOT NULL``).
It is now a **subject** — ``(subject_kind, subject_id)`` — so a design leg is a first-class stream
subject rather than something forced to borrow a project-run id. ``subject_kind = 'project_run'``
keeps ``run_id`` populated and ``subject_id = run_id::text`` (a DB CHECK, so a project-run event can
never lie about its subject); every other kind carries ``run_id IS NULL`` (so a non-project event
can never fake a project run). ``subject_id`` is ``text`` because subject id *shapes* differ — a
design run id is ``run_<uuid4 hex>``, not a uuid.

This module keeps owning the **project-run** writer (:func:`emit_run_event`, whose signature and
semantics are unchanged) and the **subject-aware read** surface the SSE replay planner runs on.
The *design* writer deliberately does **not** live here — see
``clue_execution.run_events`` and the placement note there.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ExecutionId, ProjectRunId, UtcDatetime, decode_jsonb, serialize_value_json


class RunEventTopic(StrEnum):
    """The v1 PB-B4 phase topics, plus the D7 ``design.*`` routing classes.

    C5 execution rows use the closed ``ExecutionEventType`` string vocabulary at their owner and
    deliberately cross this dependency boundary as strings. ``stream.*`` topics remain generated
    at connect and are never stored.

    The three ``design.*`` members are **coarse routing classes**, not the design event vocabulary:
    a design leg's fine-grained ``event_type`` (the free vocabulary the retired ``design_run_event``
    table carried) rides *in the payload*. That keeps this closed enum from having to track an
    open, subsystem-owned vocabulary — the stream routes, the payload describes.
    """

    PHASE_STARTED = "run.phase.started"
    PHASE_COMPLETED = "run.phase.completed"
    STEP_PROGRESS = "run.step.progress"  # A6 minimal phase-level timeline mapping
    DONE = "run.done"
    RESEARCH_VIEW_UPDATED = "research_view.updated"
    RESEARCH_VIEW_SECTION_STALE = "research_view.section_stale"
    RESEARCH_VIEW_RECHECK_COMPLETED = "research_view.recheck_completed"
    DOSSIER_UPDATED = "dossier.updated"
    DOSSIER_SECTION_STALE = "dossier.section.stale"
    DESIGN_RUN_EVENT = "design.run.event"
    DESIGN_RUN_COMPLETED = "design.run.completed"
    DESIGN_RUN_FAILED = "design.run.failed"


# The stored-topic allow-list (kept == the enum by a durable test so a new member cannot silently
# diverge from the SSE contract vocabulary).
RUN_EVENT_TOPICS: tuple[str, ...] = tuple(t.value for t in RunEventTopic)

#: The subset a design-leg emitter may write. Pinned here (next to the enum that defines them) and
#: re-stated by ``clue_execution.run_events`` — which cannot import this package — with a parity
#: test binding the two so the vocabularies can never drift.
DESIGN_RUN_EVENT_TOPICS: tuple[str, ...] = (
    RunEventTopic.DESIGN_RUN_EVENT.value,
    RunEventTopic.DESIGN_RUN_COMPLETED.value,
    RunEventTopic.DESIGN_RUN_FAILED.value,
)

#: The ``subject_kind`` vocabulary — mirrored by the ``run_event_subject_kind_known`` DB CHECK
#: (a DB-parity test binds the two). Deliberately ``text`` + CHECK rather than a PG enum: the
#: subject taxonomy grows at Part III+, and a CHECK swap is cheaper than an enum rebuild.
PROJECT_RUN_SUBJECT_KIND = "project_run"
DESIGN_RUN_SUBJECT_KIND = "design_run"
RUN_EVENT_SUBJECT_KINDS: tuple[str, ...] = (PROJECT_RUN_SUBJECT_KIND, DESIGN_RUN_SUBJECT_KIND)

# The HANDOFF checkpoint-payload key marking a gap-completed handoff (the slice-1 composer's
# documented narrative-emit gap). ONE constant coupling the writer (clue_api.run_composition's
# gap handler), both readers (the run-overview projection; the compose_handoff tool), and their
# tests — a rename here fails them all together instead of silently reading False (review F4).
NARRATIVE_EMIT_SKIPPED_KEY = "narrative_emit_skipped"


class RunEventRow(BaseModel):
    """One persisted ``run_event`` row — the durable SSE envelope. ``seq`` is the monotone id the
    consumer's ``Last-Event-ID`` tracks; ``topic`` is the ``event:`` field; ``payload`` is the
    ``data:`` object; ``workspace_id`` is the owning tenant (a consumer is served only its own rows,
    substrate §2).

    ``(subject_kind, subject_id)`` is the D7 stream subject. ``run_id`` is populated **only** for
    ``subject_kind == 'project_run'`` (where it equals ``subject_id``) and is ``None`` for every
    other kind — the DB CHECK ``run_event_subject_coherent`` makes the two states the only two
    representable ones, so a reader never has to reconcile them."""

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


async def emit_run_event(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: ProjectRunId,
    topic: str,
    payload: dict[str, JsonValue] | None = None,
    execution_id: ExecutionId | None = None,
) -> RunEventRow:
    """Append one run event to the durable outbox and return the persisted row (with its ``seq``).

    Called by composition-root run/execution writers. Transactional in the caller's connection;
    ``seq`` is assigned by the DB (globally monotone → per-workspace ordering). Emission is
    at-least-once / seq-idempotent.

    D7 left this signature and its semantics **exactly** as they were: every existing project-run
    call site is untouched, and the widened subject columns are stamped here
    (``subject_kind='project_run'``, ``subject_id=str(run_id)``) rather than being a caller's
    concern."""
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
    cursor whose event is older than ``CLUE_SSE_REPLAY_HORIZON_S`` gets ``stream.reset``). ``None``
    when the tenant has no such event (an unknown / aged-out cursor — the surface treats that
    conservatively as a reset)."""
    row = (
        await conn.execute(
            text("SELECT created_at FROM run_event WHERE workspace_id = :ws AND seq = :seq"),
            {"ws": workspace_id, "seq": seq},
        )
    ).one_or_none()
    return row[0] if row is not None else None


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
