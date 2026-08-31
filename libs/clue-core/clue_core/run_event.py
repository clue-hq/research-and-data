"""The durable ``run_event`` outbox's shared shapes and its one replay planner.

**Contract-delta 2026-08-10 — design-integration Part II, slice D8 (outbox consolidation).**
D7 shipped the ``run_event`` stream as *two* thin DALs over one table: the project-run half in
``clue_research.durable.run_events`` and the design/subject half in ``clue_execution.run_events``,
bound together by offline parity tests. The duplication existed for an import-contract reason
(``clue_research`` may not reach ``clue_execution`` transitively — rule F1 — and
``clue_projections`` may not import ``clue_execution`` at all — rule P1), and D7 priced the fix as
exactly this delta.

D8 collapses it. The **shapes** (topic vocabulary, subject vocabulary, the row model, the replay
plan) and the **planner** live here, in the one package every side may import; the **DAL** (the
INSERT/SELECT statements) has a single owner in ``clue_execution.run_events``; and the planner
reaches its rows through the :class:`RunEventReader` seam, whose only concrete implementation is
built at a composition root (``clue_api`` for the project stream, ``lumen_api`` for the design one).
That inversion is what lets ``clue_projections`` keep planning replays over an outbox it is
forbidden from importing the reader for — the dependency-inversion the P1 contract's own comment
already prescribes.

Why here and not in ``clue_projections``: the planner has two consumers on opposite sides of a
mutual import ban (``clue_projections`` ⊥ ``clue_execution``), so ``clue_core`` — which both may
import and which imports nothing internal — is the only home in which "one replay semantics" is a
structural fact rather than a parity test. The reader protocol is deliberately **connection-bound**
(no ``AsyncConnection`` parameter) so the shared kernel keeps its single dependency, pydantic, and
never learns that the outbox is a SQL table.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_core.execution_graph import ExecutionId
from clue_core.primitives import ProjectRunId, UtcDatetime


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


#: The stored-topic allow-list (kept == the enum by a test so a new member cannot silently diverge
#: from the SSE contract vocabulary).
RUN_EVENT_TOPICS: tuple[str, ...] = tuple(t.value for t in RunEventTopic)

#: The subset a design-leg emitter may write (``emit_design_run_event`` refuses anything else — a
#: design leg that could stamp ``run.phase.completed`` would forge project-run lifecycle events on
#: a client's project stream). One definition since D8; D7 restated it in two packages.
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

# The ``payload.kind`` discriminators for Stage-0 recon's ``run.step.progress`` events. Both name
# the *same* ``STEP_PROGRESS`` topic's payload species so a consumer can route without sniffing
# payload shape. ``RECON_TRANSITION_KIND`` names the previously-unnamed inline literal in
# ``clue_api.stage0_tools._emit_recon_transition`` (recorded defect FI-4 B-4) — one constant
# coupling the writer, its readers, and their tests, exactly like NARRATIVE_EMIT_SKIPPED_KEY above.
# ``RECON_FIELD_PROGRESS_KIND`` names the per-field progress event emitted from inside the
# reverse-profiling field loop (statuses: :class:`clue_research.stage0.types.FieldProgressStatus`).
RECON_TRANSITION_KIND = "stage0.recon.transition"
RECON_FIELD_PROGRESS_KIND = "stage0.recon.field"


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


@dataclass(frozen=True, slots=True)
class ReplayPlan:
    """The outcome of a reconnect-replay decision: whether the consumer must be **reset** (its
    cursor is unknown or older than the replay horizon → it re-fetches the projection), the ordered
    backlog to deliver, and the ``effective_cursor`` the live tail must resume from. Duplicates are
    tolerated by ``seq`` — a consumer dedups on the envelope id, so re-sending an event the consumer
    already saw is harmless.

    ``effective_cursor`` is the load-bearing field for the tail: on reset it is **0** (never the
    consumer's bogus cursor — a corrupted/future/cross-environment ``Last-Event-ID`` used as the
    tail floor would silently match nothing forever, a permanently dead "live" stream)."""

    reset: bool
    backlog: tuple[RunEventRow, ...]
    effective_cursor: int


@runtime_checkable
class RunEventReader(Protocol):
    """The two reads :func:`plan_replay` performs, as a seam.

    A reader is **bound** to one connection *and* one stream selection (tenant + optional subject),
    so the planner stays a pure decision over a cursor and never learns how rows are stored or
    scoped. The concrete implementation (``clue_execution.run_events.DbRunEventReader``) is built at
    a composition root and injected — the whole point of the D8 consolidation, since the planner's
    two callers sit on opposite sides of a mutual import ban.
    """

    async def cursor_created_at(self, seq: int) -> UtcDatetime | None:
        """The ``created_at`` of *the tenant's* event at ``seq``, or ``None`` when it has none (an
        unknown/aged-out cursor). Tenant-scoped but **not** subject-scoped: a cursor is a position
        in the workspace's one monotone stream."""
        ...

    async def events_after(self, *, after_seq: int, limit: int) -> Sequence[RunEventRow]:
        """This reader's selection, ``seq > after_seq``, in ``seq`` order, ``limit`` rows max."""
        ...


async def plan_replay(
    reader: RunEventReader,
    *,
    last_event_id: int | None,
    horizon_s: float,
    now: datetime | None = None,
    limit: int = 1000,
) -> ReplayPlan:
    """Plan a reconnecting consumer's replay from ``last_event_id`` (the ``Last-Event-ID`` cursor).

    One implementation, three cases — the project-run SSE surface, the design run stream and any
    future subject all get exactly these semantics because they all call this function:

    * No cursor (a fresh connect) → no reset; backlog is every event so far (``seq > 0``).
    * A cursor whose event is **within** the horizon → no reset; backlog is ``seq > cursor``
      (gapless — duplicates tolerated by seq); the tail resumes from the cursor.
    * A cursor whose event is **older than** the horizon, or is unknown/aged-out (corrupted,
      cross-environment, cross-workspace, future) → **reset**: the surface tells the client (the
      platform stream emits ``stream.reset``; the client re-fetches the projection, which is the
      authority after a reset), the ``effective_cursor`` drops to **0**, and both the backlog and
      the live tail restart from the beginning. The bogus cursor is never reused as the tail floor
      (it would silently match nothing forever — a permanently dead stream).

    Forward-note (slice-1 review F5, answered at D8 — R-D8-4). One ``run_event`` sweep now exists,
    and it cannot create the partial-view case for either stream:

    * **Project runs: untouched.** ``prune_design_run_progress_events`` filters
      ``subject_kind = 'design_run'`` as a SQL literal, so no ``project_run`` row is deletable by
      any caller. This paragraph's original claim — a post-reset backlog is genuinely complete —
      therefore remains literally true for the platform stream.
    * **Design runs: pruned only where a reset cannot see it.** Progress rows are removed only for
      runs that have been terminal longer than a hard 7-day retention floor which strictly exceeds
      that stream's 24h replay horizon, and only while the run's *terminal* row survives. So a
      cursor young enough to be replayed gaplessly points at a run far too young to prune, and a
      cursor older than the horizon resets to 0 — where the backlog is short (the surviving
      terminal row) and still closes the stream correctly. No cursor observes a mid-range hole:
      the deleted rows are a contiguous prefix of the subject's seq range.

    A future sweep that broke either floor — pruning a project subject, or a terminal row, or
    inside the horizon — *would* make reset-then-backlog a partial view, and would owe this
    function the revisit the original note describes (close-after-reset, or a documented
    projection-first re-sync contract).

    Read-only — issues no writes (the D7 MVCC-only discipline the SSE surfaces depend on)."""
    cursor = last_event_id if last_event_id is not None and last_event_id > 0 else 0
    reset = False
    if cursor > 0:
        moment = now if now is not None else datetime.now(UTC)
        cutoff = moment - timedelta(seconds=horizon_s)
        cursor_ts = await reader.cursor_created_at(cursor)
        reset = cursor_ts is None or cursor_ts < cutoff
    effective_cursor = 0 if reset else cursor
    backlog = await reader.events_after(after_seq=effective_cursor, limit=limit)
    return ReplayPlan(reset=reset, backlog=tuple(backlog), effective_cursor=effective_cursor)
