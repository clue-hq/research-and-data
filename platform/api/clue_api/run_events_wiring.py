"""The run-event **emitter** wired into the drive path (PB-B4 slice 3, D8).

The composition root owns writes, so the SSE emitter lives here — not in the read-only
``clue_projections`` package. :class:`DbRunEventEmitter` translates one ``advance`` phase transition
(the before/after ``project_run`` rows the :class:`~clue_api.run_composition.ComposingRunDriver`
observes) into the durable ``run_event`` rows an SSE consumer reads, calling the run-machinery write
helper ``clue_research.durable.emit_run_event``.

**At-least-once, best-effort, post-advance.** Emission runs *after* the phase transition has durably
committed, in its own short transaction (the drive path holds no ambient txn). It is deliberately
**best-effort**: a crash or a DB blip between the advance-commit and the emit drops that event (the
durable ``project_run`` + the projection stay the authoritative truth a consumer can always
re-read), and a raising emit is logged and swallowed — visibility must never sink a run
(pre-mortem #2's inverse: the run's correctness never depends on the convenience stream). Duplicates
are tolerated by the consumer's ``seq`` idempotence.

Topics emitted (D8): ``run.step.progress`` every advance that makes progress (the A6 minimal
phase-level timeline tick), ``run.phase.completed`` when a phase commits, ``run.phase.started`` when
the next phase begins, and ``run.done`` at terminal completion.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import JsonValue

from clue_core import ProjectPhase
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_research.durable import (
    ProjectRunRow,
    ProjectRunStatus,
    RunEventTopic,
    emit_run_event,
)

log = get_logger("clue_api.run_events_wiring")

_PHASES = tuple(ProjectPhase)
_PHASE_TOTAL = len(_PHASES)


def plan_phase_events(
    before: ProjectRunRow, after: ProjectRunRow
) -> list[tuple[str, dict[str, JsonValue]]]:
    """The (topic, payload) events one ``advance`` transition emits (a pure mapping).

    Returns ``[]`` for a true no-op advance (phase *and* status unchanged — e.g. a repeated advance
    of a paused/awaiting run), so a no-op never spams the stream. Otherwise: a per-advance
    ``run.step.progress`` tick, plus ``run.phase.completed`` when a phase commits (phase changed,
    or the run reached terminal completion on the last phase), ``run.phase.started`` when a fresh
    non-terminal phase begins, and ``run.done`` at completion."""
    if before.phase == after.phase and before.status == after.status:
        return []
    events: list[tuple[str, dict[str, JsonValue]]] = []
    phase_index = _PHASES.index(after.phase) + 1
    events.append(
        (
            RunEventTopic.STEP_PROGRESS.value,
            {
                "from_phase": before.phase.value,
                "to_phase": after.phase.value,
                "status": after.status.value,
                "phase_index": phase_index,
                "phase_total": _PHASE_TOTAL,
            },
        )
    )
    advanced = after.phase != before.phase
    completed = after.status == ProjectRunStatus.COMPLETED
    failed = after.status == ProjectRunStatus.FAILED
    if advanced or completed:
        events.append((RunEventTopic.PHASE_COMPLETED.value, {"phase": before.phase.value}))
    if advanced and not completed and not failed:
        events.append((RunEventTopic.PHASE_STARTED.value, {"phase": after.phase.value}))
    if completed:
        events.append((RunEventTopic.DONE.value, {"phase": after.phase.value}))
    return events


@runtime_checkable
class RunEventEmitter(Protocol):
    """The drive-path emission seam. The composing driver calls :meth:`phase_transition` after each
    ``advance``; a test injects a fake, production binds :class:`DbRunEventEmitter`."""

    async def phase_transition(self, before: ProjectRunRow, after: ProjectRunRow) -> None: ...


class NullRunEventEmitter:
    """A no-op :class:`RunEventEmitter` — the safe default when no SSE outbox is wired (e.g. a unit
    test driving the composer against an in-memory store). Emits nothing."""

    async def phase_transition(self, before: ProjectRunRow, after: ProjectRunRow) -> None:
        return None


class DbRunEventEmitter:
    """The production :class:`RunEventEmitter` — appends the transition's ``run_event`` rows to the
    durable outbox (best-effort, post-advance, own transaction). Never raises to the drive path."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def phase_transition(self, before: ProjectRunRow, after: ProjectRunRow) -> None:
        events = plan_phase_events(before, after)
        if not events:
            return
        try:
            async with self._conn_factory() as conn:
                for topic, payload in events:
                    await emit_run_event(
                        conn,
                        workspace_id=after.workspace_id,
                        run_id=after.id,
                        topic=topic,
                        payload=payload,
                    )
        except Exception:  # noqa: BLE001 — visibility is best-effort; never sink the run
            log.warning(
                "run_events.emit_failed",
                project_run_id=str(after.id),
                workspace_id=after.workspace_id,
                exc_info=True,
            )


def build_run_event_emitter(*, conn_factory: ConnFactory = transaction) -> RunEventEmitter:
    """The api-root production emitter over the durable ``run_event`` outbox."""
    return DbRunEventEmitter(conn_factory=conn_factory)


# Static conformance — mypy proves each concrete satisfies the seam.
_DB_EMITTER_IS: type[RunEventEmitter] = DbRunEventEmitter
_NULL_EMITTER_IS: type[RunEventEmitter] = NullRunEventEmitter
