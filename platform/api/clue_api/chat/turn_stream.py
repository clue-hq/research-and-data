"""The turn stream emitter — durable receipts projected into §3.2 events, live.

FI Lane D slice **D3**, charter §3-P4 and §§3.2-3.5. This is the *write* half of the turn stream:
the object a running turn holds, which turns everything the platform durably records into frames on
:mod:`clue_api.chat.turn_events`'s outbox. The read half (the SSE endpoint) never imports this
module — it must stay free of the model plane — and the two meet only at the table.

Three ideas carry the whole design.

**1. Parts are projections (Doc A §3a).** Nothing here is a store. A tool card is the durable plan
operation and its receipt; a reasoning card is the observable fact that a model round is running; an
activity card is the ordered list of things that were journaled; a task card is a run row and its
job states. If a durable receipt does not exist, no part is emitted — an honest gap beats an
invented card.

**2. Text is genuinely incremental (ratified §6-D2).** Because the surface binds
``tool_choice="required"``, the assistant's prose exists only inside the streamed
``finalize_turn.user_message`` argument. :class:`TurnStreamCallbackHandler` attaches to the model
call, feeds the raw tool-call chunks to the pure
:class:`~clue_api.chat.finalize_stream.FinalizeTextDeltaExtractor`, and appends only newly decoded
characters. Post-hoc animation of a finished string is exactly what the charter forbids, and
nothing in this module can produce it: the deltas are written while the model is still generating,
and their indices are the order they were produced in.

**3. The stream is never authoritative.** Every emission is wrapped so an outbox failure cannot
fail a turn (§3-P4's "stream loss never changes the durable outcome"); failures are counted and
logged loudly instead. At finalization the deltas the *outbox* actually holds are joined and
compared byte-for-byte with the durable assistant message (§3.3(5)); a mismatch emits
``stream.reset`` and tells consumers to re-fetch the canonical message. It never rewrites the turn.

**How the model is made to stream at all.** LangChain decides to use a chat model's ``_astream``
when a callback handler attached to the run is *structurally* a streaming handler — a runtime
checkable protocol whose members are ``tap_output_aiter`` / ``tap_output_iter``. This handler
implements both (as pass-throughs) and therefore opts this one turn into the streaming path,
without changing the shared runtime, the gateway, or any other agent's behaviour: a turn with no
stream attached still takes the single-shot path it always did. The behaviour is pinned by a test
that would fail loudly if a LangChain upgrade changed the mechanism, rather than by a comment.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any
from uuid import UUID, uuid5

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import ChatGenerationChunk, GenerationChunk, LLMResult
from pydantic import JsonValue
from sqlalchemy import text as sql_text

from clue_api.agent_gate import (
    GATE_OBJECT_TYPE,
    KIND_ICP_CONFIRMATION,
    KIND_PRODUCT_SET_SELECTION,
)
from clue_api.chat.finalize_stream import FinalizeTextDeltaExtractor
from clue_api.chat.turn_events import (
    TurnEventType,
    emit_turn_event,
    next_generation_attempt,
    turn_stream_has_event,
    turn_text_deltas,
)
from clue_api.chat.turn_parts import (
    ActivityStep,
    ActivityStepStatus,
    AgentActivityPart,
    ClarificationPart,
    ClarificationQuestion,
    GatePart,
    PartKind,
    PlanPart,
    ReasoningPart,
    ReasoningState,
    SourceItem,
    SourcesPart,
    TaskCounts,
    ToolPart,
    ToolPartState,
    TurnPart,
    activity_part_id,
    assistant_message_id,
    clarification_part_id,
    gate_part_id,
    object_ref_wire,
    plan_part_id,
    reasoning_part_id,
    sources_part_id,
    task_part_from_run,
    text_part_id,
    tool_part_id,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_projections import (
    GateView,
    ResearchTaskView,
    research_tasks_for_action_refs,
    thread_gates,
)

log = get_logger("clue_api.chat.turn_stream")

__all__ = [
    "TurnStreamCallbackHandler",
    "TurnStreamEmitter",
    "TurnStreamPolicy",
    "generation_attempt_id_for",
    "reasoning_deltas_from_chunk",
]


def generation_attempt_id_for(*, turn_id: UUID, ordinal: int) -> UUID:
    """The derived id of one generation attempt of one turn.

    Derived rather than minted so a worker that re-claims a crashed task computes the *same* id for
    the same ordinal, and so an attempt id is meaningful in a log without a lookup.
    """

    return uuid5(turn_id, f"generation-attempt:{ordinal}")


@dataclass(frozen=True, slots=True)
class TurnStreamPolicy:
    """The bounded micro-batching of §3.3(3).

    Batching exists for transport and database efficiency only. Two rules keep it honest: the
    **first** delta of a part is always flushed immediately (so a consumer sees text while the model
    is still generating, which is the whole ratified requirement), and a batch may never wait for
    model completion — it is bounded by a character count and a short interval, both small.
    """

    batch_max_chars: int = 256
    batch_interval_s: float = 0.05
    #: The **dev-only** raw-reasoning lens (``CLUE_CHAT_REASONING_TRACE_MODE=raw``). ``False`` — the
    #: only value a production process can hold, because the setting is refused at startup outside a
    #: dev deployment — is charter §3.3's ratified contract: whatever the provider says it was
    #: thinking is discarded here and never reaches the outbox. ``True`` routes it onto the round's
    #: own ``reasoning`` part. The gate lives on the emitter rather than only on the callback
    #: handler so that *every* path to a reasoning delta, present and future, passes one check.
    reasoning_trace: bool = False
    #: ``Settings.budget_controls_enabled`` (FI pilot budget-controls, ratified 2026-08-11).
    #: ``False`` is the pilot posture: the rich ``gate`` part leaves ``amount_cents``/``currency``
    #: unset, so no cost number reaches a human surface. §3.4's contract already declares both
    #: optional (the thin gate part has always omitted them), so this is an allowed payload, not a
    #: contract change. The amount stays on the immutable gate row either way.
    gate_amount_visible: bool = True


@dataclass(slots=True)
class _TextPartState:
    part_id: str
    round_ordinal: int
    call_index: int
    next_delta_index: int = 0
    pending: list[str] = field(default_factory=list)
    accepted_text: list[str] = field(default_factory=list)
    started: bool = False
    ended: bool = False
    last_flush: float = 0.0


@dataclass(slots=True)
class _ReasoningTextState:
    """One round's accumulated reasoning trace (dev lens only)."""

    part_id: str
    next_delta_index: int = 0
    pending: list[str] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    last_flush: float = 0.0


class TurnStreamEmitter:
    """One generation attempt's live projection onto the durable outbox.

    Constructed by :meth:`open`, which is also where attempt identity is decided: the outbox itself
    says how many attempts a turn has already had, so a re-claimed task after a crash opens attempt
    2 with a different id and different part ids, and closes attempt 1's still-open parts with
    ``part.reset`` (§3.3(6) — deltas from two generations are never spliced).
    """

    def __init__(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        turn_id: UUID,
        generation_attempt_id: UUID,
        attempt_ordinal: int,
        conn_factory: ConnFactory = transaction,
        policy: TurnStreamPolicy | None = None,
        monotonic: Any = time.monotonic,
    ) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.thread_id = thread_id
        self.turn_id = turn_id
        self.generation_attempt_id = generation_attempt_id
        self.attempt_ordinal = attempt_ordinal
        self.message_id = assistant_message_id(turn_id)
        self._conn_factory = conn_factory
        self._policy = policy or TurnStreamPolicy()
        self._monotonic = monotonic
        self._revisions: dict[str, int] = {}
        self._activity: list[ActivityStep] = []
        self._text: _TextPartState | None = None
        self._reasoning: dict[int, _ReasoningTextState] = {}
        self._rounds = 0
        self._active_rounds: set[int] = set()
        #: Emission failures, counted rather than raised: the stream may never fail a turn.
        self.emission_failures: list[str] = []

    # -- lifecycle ------------------------------------------------------------------------------

    @classmethod
    async def open(
        cls,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        turn_id: UUID,
        conn_factory: ConnFactory = transaction,
        policy: TurnStreamPolicy | None = None,
    ) -> TurnStreamEmitter:
        """Open the next generation attempt of ``turn_id`` and announce it."""

        async with conn_factory() as conn:
            ordinal, prior = await next_generation_attempt(
                conn, workspace_id=workspace_id, turn_id=turn_id
            )
            # The HTTP route announces acceptance the moment the turn is durable, which is the
            # honest moment — the platform accepted it there, not here. This stays as the fallback
            # for a turn accepted off-route (the dev trial, a test harness), and it is a check
            # rather than an unconditional emit so no turn is ever announced twice.
            announced = await turn_stream_has_event(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
                event_type=TurnEventType.TURN_ACCEPTED,
            )
        emitter = cls(
            workspace_id=workspace_id,
            project_id=project_id,
            thread_id=thread_id,
            turn_id=turn_id,
            generation_attempt_id=generation_attempt_id_for(turn_id=turn_id, ordinal=ordinal),
            attempt_ordinal=ordinal,
            conn_factory=conn_factory,
            policy=policy,
        )
        if ordinal == 1:
            if not announced:
                await emitter._emit(
                    TurnEventType.TURN_ACCEPTED,
                    payload={"attempt_ordinal": ordinal, "source": "worker"},
                )
        else:
            await emitter._reset_prior_attempt(prior[-1] if prior else None)
        return emitter

    async def _reset_prior_attempt(self, superseded: UUID | None) -> None:
        """Close whatever the crashed attempt left open, then announce the retry.

        The order matters to a consumer: it must be told the old cards are void *before* it is told
        a new generation is under way, so no interleaving can make the two look like one stream.
        """

        for part_id, part_kind in await self._open_parts_of(superseded):
            await self._emit(
                TurnEventType.PART_RESET,
                part_id=part_id,
                part_kind=part_kind,
                generation_attempt_id=superseded,
                payload={"reason": "generation_attempt_superseded"},
            )
        await self._emit(
            TurnEventType.TURN_RETRYING,
            payload={
                "attempt_ordinal": self.attempt_ordinal,
                "superseded_attempt_id": None if superseded is None else str(superseded),
            },
        )

    async def _open_parts_of(self, attempt_id: UUID | None) -> tuple[tuple[str, str], ...]:
        """Parts of ``attempt_id`` that were opened and never closed — what a retry must reset."""

        if attempt_id is None:
            return ()
        async with self._conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        sql_text(
                            """
                            SELECT part_id, max(part_kind) AS part_kind
                            FROM agent_turn_event_stream
                            WHERE workspace_id = :workspace_id
                              AND turn_id = :turn_id
                              AND generation_attempt_id = :attempt_id
                              AND part_id IS NOT NULL
                            GROUP BY part_id
                            HAVING bool_or(event_type IN ('part.created', 'part.updated',
                                                          'text.start'))
                               AND NOT bool_or(event_type IN ('part.completed', 'part.failed',
                                                              'part.reset', 'text.end'))
                            ORDER BY part_id
                            """
                        ),
                        {
                            "workspace_id": self.workspace_id,
                            "turn_id": self.turn_id,
                            "attempt_id": attempt_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            (str(row["part_id"]), str(row["part_kind"] or PartKind.TEXT.value)) for row in rows
        )

    async def turn_started(self) -> None:
        await self._emit(
            TurnEventType.TURN_STARTED,
            payload={"attempt_ordinal": self.attempt_ordinal},
        )

    async def turn_finished(
        self,
        *,
        status: str,
        failure_code: str | None = None,
        replayed: bool = False,
    ) -> None:
        """Announce the turn's terminal state, mapped onto the §3.2 vocabulary."""

        event = _TERMINAL_EVENTS.get(status, TurnEventType.TURN_FAILED)
        payload: dict[str, JsonValue] = {"status": status, "replayed": replayed}
        if failure_code is not None:
            payload["failure_code"] = failure_code
        await self._emit(event, message_id=self.message_id, payload=payload)

    async def turn_cancelled(self, *, reason: str = "stop_requested") -> None:
        """A stopped attempt is terminal *and* honest: whatever text was emitted stays visible for
        audit, and no ``text.end`` is ever emitted for it — a cancelled generation must not be able
        to masquerade as a completed assistant message (§3.3(8))."""

        for ordinal in tuple(self._active_rounds):
            await self.round_finished(round_ordinal=ordinal, failed=True)
        await self._flush_text()
        if self._text is not None and self._text.started and not self._text.ended:
            await self._emit(
                TurnEventType.PART_FAILED,
                part_id=self._text.part_id,
                part_kind=PartKind.TEXT.value,
                payload={"reason": reason, "partial": True},
            )
            self._text.ended = True
        await self._emit(
            TurnEventType.TURN_CANCELLED,
            payload={"reason": reason, "attempt_ordinal": self.attempt_ordinal},
        )

    # -- model rounds ---------------------------------------------------------------------------

    @property
    def reasoning_trace_enabled(self) -> bool:
        """Whether this emitter will accept a provider reasoning delta at all (dev lens only)."""

        return self._policy.reasoning_trace

    def _reasoning_part_id(self, round_ordinal: int) -> str:
        return reasoning_part_id(
            generation_attempt_id=self.generation_attempt_id,
            round_ordinal=round_ordinal,
        )

    async def round_started(self, *, round_ordinal: int) -> None:
        self._active_rounds.add(round_ordinal)
        self._rounds = max(self._rounds, round_ordinal)
        part_id = self._reasoning_part_id(round_ordinal)
        await self._part(
            TurnEventType.PART_CREATED,
            ReasoningPart(
                part_id=part_id,
                revision=self._revision(part_id),
                state=ReasoningState.ACTIVE,
                round_ordinal=round_ordinal,
                started_at=_now(),
            ),
        )
        await self._activity_step(
            step_id=f"round:{round_ordinal}",
            kind="model_round",
            status=ActivityStepStatus.ACTIVE,
            label=f"Model round {round_ordinal}",
        )

    async def reasoning_delta(self, *, round_ordinal: int, delta: str) -> None:
        """Route one provider reasoning delta onto this round's ``reasoning`` part — **dev only**.

        Refused outright unless :attr:`TurnStreamPolicy.reasoning_trace` is on, which a production
        process cannot hold: ``CLUE_CHAT_REASONING_TRACE_MODE=raw`` fails settings construction
        outside a dev deployment. In ``summary`` mode this method is the drain the ratified §3.3
        contract requires — the delta is dropped here, not filtered later.

        **The frame is a ``text.delta`` targeting the reasoning part's id.** No new event type, no
        new part kind, and therefore no migration: the outbox's ``(event_type = 'text.delta') =
        (delta_index IS NOT NULL)`` CHECK and its ``part_kind`` CHECK both already admit this shape,
        and a consumer that accumulates deltas per part id already knows what to do with it. The
        one thing it must *not* do is treat the accumulation as assistant prose, which is why the
        frame carries ``part_kind='reasoning'`` and no ``message_id``: this text belongs to no
        message, and :meth:`reconcile_text` — which is scoped to the *text* part's id — never sees
        it, because there is deliberately no durable reasoning message to reconcile against.
        """

        if not self._policy.reasoning_trace or not delta:
            return
        state = self._reasoning.get(round_ordinal)
        if state is None:
            state = _ReasoningTextState(
                part_id=self._reasoning_part_id(round_ordinal),
                last_flush=self._monotonic(),
            )
            self._reasoning[round_ordinal] = state
        state.pending.append(delta)
        state.text.append(delta)
        pending_chars = sum(len(item) for item in state.pending)
        first = state.next_delta_index == 0
        elapsed = self._monotonic() - state.last_flush
        if (
            first
            or pending_chars >= self._policy.batch_max_chars
            or elapsed >= self._policy.batch_interval_s
        ):
            await self._flush_reasoning(state)

    async def _flush_reasoning(self, state: _ReasoningTextState) -> None:
        if not state.pending:
            return
        delta = "".join(state.pending)
        state.pending.clear()
        index = state.next_delta_index
        state.next_delta_index += 1
        state.last_flush = self._monotonic()
        await self._emit(
            TurnEventType.TEXT_DELTA,
            part_id=state.part_id,
            part_kind=PartKind.REASONING.value,
            delta_index=index,
            payload={"delta": delta},
        )

    async def round_finished(
        self,
        *,
        round_ordinal: int,
        requested_tool_calls: int = 0,
        failed: bool = False,
    ) -> None:
        part_id = self._reasoning_part_id(round_ordinal)
        self._active_rounds.discard(round_ordinal)
        trace = self._reasoning.pop(round_ordinal, None)
        if trace is not None:
            await self._flush_reasoning(trace)
        text = "".join(trace.text) if trace is not None and trace.text else None
        part = ReasoningPart(
            part_id=part_id,
            revision=self._revision(part_id),
            state=ReasoningState.ERROR if failed else ReasoningState.COMPLETE,
            round_ordinal=round_ordinal,
            requested_tool_calls=requested_tool_calls,
            started_at=_now(),
            completed_at=_now(),
            # The closing snapshot carries the whole accumulated trace so a consumer that attached
            # late (or replayed from a cursor past the deltas) still sees it — and carries the
            # ephemerality marker with it, because nothing durable will ever confirm this text.
            text=text,
            text_ephemeral=None if text is None else True,
        )
        await self._part(
            TurnEventType.PART_FAILED if failed else TurnEventType.PART_COMPLETED,
            part,
        )
        await self._activity_step(
            step_id=f"round:{round_ordinal}",
            kind="model_round",
            status=ActivityStepStatus.ERROR if failed else ActivityStepStatus.COMPLETE,
            label=f"Model round {round_ordinal}",
        )

    # -- governed tool calls --------------------------------------------------------------------

    async def tool_started(
        self,
        *,
        node_key: str,
        tool_name: str,
        tool_version: str | None,
        tool_call_id: str,
        arguments: dict[str, JsonValue] | None = None,
    ) -> None:
        part_id = tool_part_id(node_key=node_key)
        await self._part(
            TurnEventType.PART_CREATED,
            ToolPart(
                part_id=part_id,
                revision=self._revision(part_id),
                state=ToolPartState.INPUT_AVAILABLE,
                tool_name=tool_name,
                tool_version=tool_version,
                tool_call_id=tool_call_id,
                node_key=node_key,
                input=arguments,
            ),
        )
        await self._activity_step(
            step_id=f"tool:{node_key}",
            kind="tool_call",
            status=ActivityStepStatus.ACTIVE,
            label=tool_name if tool_version is None else f"{tool_name}@{tool_version}",
        )

    async def tool_finished(
        self,
        *,
        node_key: str,
        tool_name: str,
        tool_version: str | None,
        tool_call_id: str,
        operation_id: UUID | None,
        output: dict[str, JsonValue] | None = None,
    ) -> None:
        part_id = tool_part_id(node_key=node_key)
        await self._part(
            TurnEventType.PART_COMPLETED,
            ToolPart(
                part_id=part_id,
                revision=self._revision(part_id),
                state=ToolPartState.OUTPUT_AVAILABLE,
                tool_name=tool_name,
                tool_version=tool_version,
                tool_call_id=tool_call_id,
                node_key=node_key,
                operation_id=operation_id,
                output=output,
            ),
        )
        await self._activity_step(
            step_id=f"tool:{node_key}",
            kind="tool_call",
            status=ActivityStepStatus.COMPLETE,
            label=tool_name if tool_version is None else f"{tool_name}@{tool_version}",
        )

    async def tool_failed(
        self,
        *,
        node_key: str,
        tool_name: str,
        tool_version: str | None,
        tool_call_id: str,
        error_code: str,
        reasons: Sequence[str] = (),
    ) -> None:
        part_id = tool_part_id(node_key=node_key)
        await self._part(
            TurnEventType.PART_FAILED,
            ToolPart(
                part_id=part_id,
                revision=self._revision(part_id),
                state=ToolPartState.OUTPUT_ERROR,
                tool_name=tool_name,
                tool_version=tool_version,
                tool_call_id=tool_call_id,
                node_key=node_key,
                error_code=error_code,
                error_reasons=tuple(reasons),
            ),
        )
        await self._activity_step(
            step_id=f"tool:{node_key}",
            kind="tool_call",
            status=ActivityStepStatus.ERROR,
            label=tool_name if tool_version is None else f"{tool_name}@{tool_version}",
            description=reasons[0] if reasons else None,
        )

    # -- assistant text -------------------------------------------------------------------------

    async def text_delta(self, *, round_ordinal: int, call_index: int, delta: str) -> None:
        """Buffer newly decoded assistant text and flush it under the §3.3(3) bounds."""

        if not delta:
            return
        state = await self._text_state(round_ordinal=round_ordinal, call_index=call_index)
        state.accepted_text.append(delta)
        state.pending.append(delta)
        pending_chars = sum(len(item) for item in state.pending)
        first = state.next_delta_index == 0
        elapsed = self._monotonic() - state.last_flush
        if (
            first
            or pending_chars >= self._policy.batch_max_chars
            or elapsed >= self._policy.batch_interval_s
        ):
            await self._flush_text()

    async def _text_state(self, *, round_ordinal: int, call_index: int) -> _TextPartState:
        """The open text part for this finalize call, opening (and resetting) as needed.

        A *second* ``finalize_turn`` call — the bounded repair round — is a different continuation,
        not a continuation of the first. So the first part is reset and a new part id begins; a
        consumer never sees two attempts' prose concatenated into one card.
        """

        part_id = text_part_id(
            generation_attempt_id=self.generation_attempt_id,
            round_ordinal=round_ordinal,
            call_index=call_index,
        )
        current = self._text
        if current is not None and current.part_id == part_id:
            return current
        if current is not None:
            await self._flush_text()
            if current.started and not current.ended:
                await self._emit(
                    TurnEventType.PART_RESET,
                    part_id=current.part_id,
                    part_kind=PartKind.TEXT.value,
                    payload={"reason": "finalize_call_superseded"},
                )
                current.ended = True
        state = _TextPartState(
            part_id=part_id,
            round_ordinal=round_ordinal,
            call_index=call_index,
            last_flush=self._monotonic(),
        )
        self._text = state
        await self._emit(
            TurnEventType.TEXT_START,
            part_id=part_id,
            part_kind=PartKind.TEXT.value,
            message_id=self.message_id,
            payload={"round_ordinal": round_ordinal},
        )
        state.started = True
        return state

    def interrupted_answer(self) -> str:
        """Only the latest finalize-call answer prefix, including its unflushed tail."""
        return "" if self._text is None else "".join(self._text.accepted_text)

    async def _flush_text(self) -> None:
        state = self._text
        if state is None or not state.pending:
            return
        delta = "".join(state.pending)
        state.pending.clear()
        index = state.next_delta_index
        state.next_delta_index += 1
        state.last_flush = self._monotonic()
        await self._emit(
            TurnEventType.TEXT_DELTA,
            part_id=state.part_id,
            part_kind=PartKind.TEXT.value,
            message_id=self.message_id,
            delta_index=index,
            payload={"delta": delta},
        )

    async def reconcile_text(self, *, assistant_message: str | None) -> bool:
        """Join what the outbox actually holds and compare it to the durable message (§3.3(5)).

        Returns ``True`` when the projection is faithful. The comparison is against the persisted
        deltas rather than an in-memory buffer, because the claim being proved is about *what a
        consumer received*, and it is on UTF-8 bytes, because that is what "byte-identical" means.

        A mismatch is a loud failure of the projection and nothing else: ``stream.reset`` instructs
        every consumer to re-fetch the canonical message, and the durable turn is untouched.
        """

        await self._flush_text()
        state = self._text
        if state is None:
            # No text was streamed. That is only correct if the turn produced no assistant message
            # either (a failed or purely gate-opening turn).
            if assistant_message:
                await self._stream_reset(reason="text_stream_missing")
                return False
            return True
        if assistant_message is None:
            await self._stream_reset(reason="durable_message_missing")
            return False
        async with self._conn_factory() as conn:
            deltas = await turn_text_deltas(
                conn,
                workspace_id=self.workspace_id,
                turn_id=self.turn_id,
                part_id=state.part_id,
                generation_attempt_id=self.generation_attempt_id,
            )
        streamed = "".join(deltas).encode()
        durable = assistant_message.encode()
        if streamed != durable:
            log.error(
                "chat.turn_stream.reconciliation_mismatch",
                turn_id=str(self.turn_id),
                workspace_id=self.workspace_id,
                part_id=state.part_id,
                streamed_bytes=len(streamed),
                durable_bytes=len(durable),
            )
            await self._emit(
                TurnEventType.PART_RESET,
                part_id=state.part_id,
                part_kind=PartKind.TEXT.value,
                payload={"reason": "delta_reconciliation_mismatch"},
            )
            state.ended = True
            await self._stream_reset(reason="delta_reconciliation_mismatch")
            return False
        await self._emit(
            TurnEventType.TEXT_END,
            part_id=state.part_id,
            part_kind=PartKind.TEXT.value,
            message_id=self.message_id,
            payload={
                "byte_count": len(durable),
                "delta_count": len(deltas),
                "sha256": hashlib.sha256(durable).hexdigest(),
            },
        )
        state.ended = True
        return True

    async def rehydrate(self, *, reason: str) -> None:
        """Tell every consumer to re-fetch the canonical message instead of trusting the stream.

        The one honest answer whenever this attempt cannot prove what it showed: a replayed turn
        (whose text was generated in an earlier process and never streamed here), or a projection
        that failed. §3.6's repair path, and it never touches the durable turn.
        """

        await self._stream_reset(reason=reason)

    async def _stream_reset(self, *, reason: str) -> None:
        await self._emit(
            TurnEventType.STREAM_RESET,
            message_id=self.message_id,
            payload={"reason": reason, "rehydrate": "message"},
        )

    # -- projections of durable objects ---------------------------------------------------------

    async def emit_plan_part(self, *, ref: object, title: str, revision_label: str | None) -> None:
        wire = object_ref_wire(ref)
        part_id = plan_part_id(
            object_type=str(wire.get("object_type", "plan")),
            object_id=str(wire.get("object_id", "")),
        )
        await self._part(
            TurnEventType.PART_CREATED,
            PlanPart(
                part_id=part_id,
                revision=self._revision(part_id),
                plan_ref=wire,
                revision_label=revision_label,
                title=title,
            ),
        )

    async def emit_gate_parts(self, *, refs: Sequence[object]) -> None:
        """Project a finalization's ``open_gate_refs`` — richly when they name a durable gate.

        One read of :func:`~clue_projections.gates.thread_gates` for the whole finalization, not one
        per ref: that projection is the transcript's own gate question (gate + answer + the run its
        approval launched), and re-deriving any of it here would be a second, drifting copy of a
        join D4 already owns.

        A ref with no matching row falls back to :meth:`emit_gate_part`'s thin shape rather than
        failing the stream. That is not a defensive hedge — ``open_gate_refs`` is an open
        ``DomainObjectRef`` vocabulary, so a future gate flavour that is not an ``agent_gate`` row
        stays renderable as "a gate exists here" instead of vanishing.
        """

        if not refs:
            return
        by_id: dict[str, GateView] = {}
        try:
            for view in await thread_gates(
                workspace_id=self.workspace_id,
                thread_id=self.thread_id,
                conn_factory=self._conn_factory,
            ):
                by_id[view.gate_id] = view
        except Exception as error:  # noqa: BLE001 — a read failure may not fail a turn
            self.emission_failures.append(f"gate_projection: {type(error).__name__}")
            log.exception(
                "chat.turn_stream.gate_projection_failed",
                turn_id=str(self.turn_id),
                workspace_id=self.workspace_id,
            )
        for ref in refs:
            wire = object_ref_wire(ref)
            found = by_id.get(str(wire.get("object_id", "")))
            if found is None:
                await self.emit_gate_part(ref=ref, gate_kind=str(wire.get("object_type", "gate")))
            else:
                await self._emit_durable_gate_part(wire=wire, view=found)

    async def _emit_durable_gate_part(self, *, wire: dict[str, JsonValue], view: GateView) -> None:
        """The §3.4 ``gate`` floor, every field of it read off the immutable row and its answer.

        Two absences are deliberate. **``title``/``summary`` stay unset** — §3.1/§3.4's standing
        rule is that the backend sends semantic state and the adapter chooses the words, and a gate
        kind plus an amount is exactly the semantic state a card needs to write its own heading.
        **``permitted_decisions`` is the full vocabulary even on a closed gate**: what a gate
        *permits* is a property of the gate, and "this one is finished" is said by ``decision`` and
        ``state``, not by silently emptying the option list.

        A third absence is conditional: with FI pilot budget-controls off
        (``TurnStreamPolicy.gate_amount_visible`` False) ``amount_cents`` and ``currency`` are left
        unset too. Everything the card needs to be *answerable* — the ref, the kind, the subject ref
        and its digest, the addressee, the permitted decisions — is unaffected; only the price
        disappears.
        """

        part_id = gate_part_id(
            object_type=str(wire.get("object_type", GATE_OBJECT_TYPE)),
            object_id=view.gate_id,
        )
        answer = view.answer
        unavailable = view.snapshot_erased_at is not None
        await self._part(
            (
                TurnEventType.PART_COMPLETED
                if answer is not None or unavailable or view.withdrawn
                else TurnEventType.PART_CREATED
            ),
            GatePart(
                part_id=part_id,
                revision=self._revision(part_id),
                gate_ref=wire,
                # The *real* kind (``directive_confirmation``), never the ref's object type: a card
                # told its kind is "agent_gate" knows only that a gate exists, which is the very
                # gap this method closes.
                gate_kind=view.kind,
                state=(
                    "unavailable"
                    if unavailable
                    else "responded"
                    if answer is not None
                    # A CRM write card a newer card replaced, or a reconnect closed: it can no
                    # longer be answered, so it asks nothing.
                    else "withdrawn"
                    if view.withdrawn
                    else "requested"
                ),
                subject_refs=() if unavailable else (_gate_subject_ref(view),),
                expected_subject_sha256=view.expected_subject_sha256,
                amount_cents=(
                    _cent_ceiling(view.max_spend_cents)
                    if self._policy.gate_amount_visible and view.max_spend_cents is not None
                    else None
                ),
                currency=(
                    view.currency
                    if self._policy.gate_amount_visible and view.max_spend_cents is not None
                    else None
                ),
                addressee_user_id=view.addressee_user_id,
                permitted_decisions=() if unavailable else view.permitted_decisions,
                decision=None if answer is None else answer.decision,
                answered_by_user_id=None if answer is None else answer.answered_by_user_id,
                answered_at=None if answer is None else answer.answered_at.isoformat(),
            ),
        )

    async def emit_gate_part(
        self, *, ref: object, gate_kind: str, state: str = "requested"
    ) -> None:
        """The thin gate projection: a ref exists, and nothing durable was found behind it.

        Kept as the honest floor for a ref that names no ``agent_gate`` row. The rich payload is
        :meth:`emit_gate_parts`, which is what every production turn-close goes through.
        """

        wire = object_ref_wire(ref)
        part_id = gate_part_id(
            object_type=str(wire.get("object_type", "gate")),
            object_id=str(wire.get("object_id", "")),
        )
        await self._part(
            TurnEventType.PART_CREATED,
            GatePart(
                part_id=part_id,
                revision=self._revision(part_id),
                gate_ref=wire,
                gate_kind=gate_kind,
                state=state,
            ),
        )

    async def emit_clarification_part(
        self,
        *,
        document_id: str,
        document_title: str,
        doc_kind: str,
        account_name: str | None,
        run_id: str,
        questions: Sequence[Mapping[str, Any]],
    ) -> None:
        """Spec 2026-09-20 §2.1: the questions a document's run asked, as one part per document."""

        part_id = clarification_part_id(document_id)
        await self._part(
            TurnEventType.PART_CREATED,
            ClarificationPart(
                part_id=part_id,
                revision=self._revision(part_id),
                document_id=document_id,
                document_title=document_title,
                doc_kind=doc_kind,
                account_name=account_name,
                run_id=run_id,
                questions=tuple(
                    ClarificationQuestion(
                        id=str(q["id"]),
                        question=str(q["question"]),
                        why_it_matters=str(q.get("why_it_matters") or ""),
                        options=tuple(str(o) for o in (q.get("options") or ())),
                        default=str(q["default"]),
                        allow_freeform=bool(q.get("allow_freeform", True)),
                    )
                    for q in questions
                ),
            ),
        )

    async def emit_sources_part(self, *, items: Sequence[SourceItem]) -> None:
        if not items:
            return
        part_id = sources_part_id(message_id=self.message_id)
        await self._part(
            TurnEventType.PART_COMPLETED,
            SourcesPart(
                part_id=part_id,
                revision=self._revision(part_id),
                items=tuple(items),
            ),
        )

    async def emit_launched_task_parts(self) -> None:
        """Project whatever detached research **this turn's own authority** launched (§3.4 task).

        The join key is the turn's canonical ``turn-action:`` receipt: the launcher persists it as
        the launch-control row's ``source_action_ref``, so "what did this turn launch?" is a read of
        a durable receipt rather than anything the emitter, the agent or the toolbelt had to carry.
        A turn that launched nothing emits nothing — an honest gap, not an empty card.

        It runs at turn close (once, on the completed attempt) because that is the first moment the
        launch is committed *and* the run's jobs exist to be counted. The card is a snapshot of that
        moment, not a live feed: a run outlives its turn by design, and the surface that follows it
        afterwards is the run projection, not this stream.
        """

        try:
            tasks = await research_tasks_for_action_refs(
                workspace_id=self.workspace_id,
                action_refs=(derive_turn_action_ref(self.turn_id),),
                conn_factory=self._conn_factory,
            )
        except Exception as error:  # noqa: BLE001 — a read failure may not fail a turn
            self.emission_failures.append(f"task_projection: {type(error).__name__}")
            log.exception(
                "chat.turn_stream.task_projection_failed",
                turn_id=str(self.turn_id),
                workspace_id=self.workspace_id,
            )
            return
        for task in tasks:
            await self._emit_task_part(task)

    async def _emit_task_part(self, task: ResearchTaskView) -> None:
        await self.emit_task_part(
            run_id=UUID(task.research_run_id),
            run_kind=task.run_kind,
            state=task.run_state,
            counts=TaskCounts(**task.counts.model_dump()),
            completed=task.run_state == "terminal",
        )

    async def emit_task_part(
        self,
        *,
        run_id: UUID,
        run_kind: str,
        state: str,
        counts: TaskCounts,
        completed: bool = False,
    ) -> None:
        part_id = f"task:{run_id}"
        await self._part(
            TurnEventType.PART_COMPLETED if completed else TurnEventType.PART_CREATED,
            task_part_from_run(
                run_id=run_id,
                run_kind=run_kind,
                state=state,
                counts=counts,
                revision=self._revision(part_id),
                workspace_id=self.workspace_id,
            ),
            run_id=run_id,
        )

    # -- plumbing -------------------------------------------------------------------------------

    async def _activity_step(
        self,
        *,
        step_id: str,
        kind: str,
        status: ActivityStepStatus,
        label: str,
        description: str | None = None,
    ) -> None:
        """Append or replace one step and re-send the whole activity snapshot (§3.2 replacement)."""

        step = ActivityStep(
            id=step_id,
            kind=kind,
            status=status,
            label=label,
            description=description,
            started_at=_now() if status is ActivityStepStatus.ACTIVE else None,
            completed_at=(
                _now()
                if status in {ActivityStepStatus.COMPLETE, ActivityStepStatus.ERROR}
                else None
            ),
        )
        for index, existing in enumerate(self._activity):
            if existing.id == step_id:
                self._activity[index] = step
                break
        else:
            self._activity.append(step)
        part_id = activity_part_id(generation_attempt_id=self.generation_attempt_id)
        revision = self._revision(part_id)
        await self._part(
            TurnEventType.PART_CREATED if revision == 1 else TurnEventType.PART_UPDATED,
            AgentActivityPart(
                part_id=part_id,
                revision=revision,
                title="Agent activity",
                steps=tuple(self._activity),
            ),
        )

    def _revision(self, part_id: str) -> int:
        revision = self._revisions.get(part_id, 0) + 1
        self._revisions[part_id] = revision
        return revision

    async def _part(
        self,
        event_type: TurnEventType,
        part: TurnPart,
        *,
        run_id: UUID | None = None,
    ) -> None:
        await self._emit(
            event_type,
            part_id=part.part_id,
            part_kind=part.kind.value,
            message_id=self.message_id,
            run_id=run_id,
            payload={"part": part.wire()},
        )

    async def _emit(
        self,
        event_type: TurnEventType,
        *,
        part_id: str | None = None,
        part_kind: str | None = None,
        message_id: UUID | None = None,
        run_id: UUID | None = None,
        delta_index: int | None = None,
        generation_attempt_id: UUID | None = None,
        payload: dict[str, JsonValue] | None = None,
    ) -> None:
        """Append one frame — and never let the attempt to do so fail the turn.

        §3-P4's rule is absolute: *stream loss never changes the durable outcome*. A failed append
        is therefore counted and logged with its exception, not raised. ``emission_failures`` is
        public so a test can assert the happy path really was clean rather than quietly degraded.
        """

        try:
            async with self._conn_factory() as conn:
                await emit_turn_event(
                    conn,
                    workspace_id=self.workspace_id,
                    project_id=self.project_id,
                    thread_id=self.thread_id,
                    turn_id=self.turn_id,
                    event_type=event_type,
                    generation_attempt_id=(
                        generation_attempt_id
                        if generation_attempt_id is not None
                        else self.generation_attempt_id
                    ),
                    part_id=part_id,
                    part_kind=part_kind,
                    message_id=message_id,
                    run_id=run_id,
                    delta_index=delta_index,
                    payload=payload,
                )
        except Exception as error:  # noqa: BLE001 — a transport failure must not fail a turn
            self.emission_failures.append(f"{event_type.value}: {type(error).__name__}")
            log.exception(
                "chat.turn_stream.emit_failed",
                turn_id=str(self.turn_id),
                workspace_id=self.workspace_id,
                event_type=event_type.value,
            )


#: Terminal ``AgentExecutionStatus``/``FinalizeStatus`` value → the §3.2 turn event.
_TERMINAL_EVENTS: dict[str, TurnEventType] = {
    "completed": TurnEventType.TURN_COMPLETED,
    "awaiting_input": TurnEventType.TURN_AWAITING_INPUT,
    "blocked": TurnEventType.TURN_AWAITING_INPUT,
    "failed": TurnEventType.TURN_FAILED,
    "cancelled": TurnEventType.TURN_CANCELLED,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _cent_ceiling(amount: Decimal) -> int:
    """A ``numeric(20,4)`` cent amount as the integer §3.4 asks for — rounded **up**.

    The column holds sub-cent precision the wire's ``amount_cents`` cannot carry. Truncating would
    render a *maximum spend* as smaller than it is, so the one safe direction is the ceiling: the
    card never promises a lower cap than the gate stored. The authoritative amount an approval
    echoes back is still the durable ``max_spend_cents``, read through the gates route.
    """

    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def _gate_subject_ref(view: GateView) -> dict[str, JsonValue]:
    """The gate's subject as a typed ref (§3.4's "subject refs, expected revision/hash").

    ``subject_ref`` is a versioned display reference (``research-directive:<id>:v<n>``); the bare
    identifier lives in the immutable snapshot precisely so a consumer never has to parse that
    string. Parsing is the fallback, not the path.
    """

    if view.kind == KIND_ICP_CONFIRMATION:
        if view.subject_snapshot.get("subject_kind") == "brand_knowledge_document":
            # ARV2 onboarding O6: the subject is a file the human can open, so the ref names the
            # document rather than the ICP key — the key is one of the document's own facts.
            identifier = view.subject_snapshot.get("document_id")
            object_type = "brand_knowledge_document"
        else:
            identifier = view.subject_snapshot.get("icp_key")
            object_type = "icp_spec"
    elif view.kind == KIND_PRODUCT_SET_SELECTION:
        # The subject is the brand's catalog as a whole — the candidates are its products — so the
        # ref names the brand, and the exact catalog document lives in the snapshot beside it.
        identifier = view.subject_snapshot.get("brand_id")
        object_type = "brand_product_catalog"
    else:
        identifier = view.subject_snapshot.get("research_directive_id")
        object_type = "research_directive"
    object_id = str(identifier) if isinstance(identifier, str) else view.subject_ref
    ref: dict[str, JsonValue] = {
        "workspace_id": view.workspace_id,
        "object_type": object_type,
        "object_id": object_id,
        "sha256": view.expected_subject_sha256,
    }
    if view.subject_revision is not None:
        ref["version"] = view.subject_revision
    return ref


def reasoning_deltas_from_chunk(message: Any) -> tuple[str, ...]:
    """Choose one displayable reasoning representation per delta, never answer/tool text.

    Standard content blocks and Responses summaries take precedence over provider
    aliases. Never deduplicate by value: repeated words in separate deltas are real.
    Encrypted continuation fields are deliberately absent from this allowlist.
    """
    for content in (getattr(message, "content", None), getattr(message, "content_blocks", None)):
        fragments: list[str] = []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "reasoning":
                continue
            standard = block.get("reasoning")
            if isinstance(standard, str) and standard:
                fragments.append(standard)
                continue
            for member in ("summary", "content"):
                items = block.get(member)
                if not isinstance(items, list):
                    continue
                fragments.extend(
                    item["text"]
                    for item in items
                    if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"]
                )
        if fragments:
            return tuple(fragments)
    extra = getattr(message, "additional_kwargs", None)
    if not isinstance(extra, dict):
        return ()
    piece = extra.get("reasoning_content")
    if isinstance(piece, str) and piece:
        return (piece,)
    details = extra.get("reasoning_details")
    if not isinstance(details, list):
        return ()
    return tuple(
        piece
        for detail in details
        if isinstance(detail, dict)
        for key in (
            "text"
            if detail.get("type") == "reasoning.text"
            else "summary"
            if detail.get("type") == "reasoning.summary"
            else "",
        )
        if key and isinstance(piece := detail.get(key), str) and piece
    )


class TurnStreamCallbackHandler(AsyncCallbackHandler):
    """Attach one emitter to one turn's model calls.

    Two responsibilities, and deliberately nothing else:

    * **Opt this run into streaming.** ``tap_output_aiter`` / ``tap_output_iter`` are how LangChain
      recognises a streaming consumer; implementing them (as pass-throughs) is what makes the chat
      model take its ``_astream`` path for *this* turn only. Attaching no such handler leaves every
      other agent on the single-shot path unchanged.
    * **Project model rounds and finalize text.** Round starts/ends become safe ``reasoning``
      status; the tool-call chunks of ``finalize_turn`` are fed to the pure extractor and their
      newly decoded characters become ``text.delta``.

    What it never does: emit the model's plain ``content`` token. On this surface any content
    outside the finalize argument is provider chatter, and §3.3's closing rule is that none of it
    reaches the wire. The only assistant text this handler can produce is text the extractor decoded
    out of ``finalize_turn.user_message``.

    The one exception is opt-in, dev-only, and separately gated: when the emitter's policy carries
    the raw-reasoning lens, *reasoning* content blocks (never ordinary content, never tool
    arguments) are routed onto the round's own ``reasoning`` part. With the lens off — the only
    state a production process can be in — the blocks are not even read.
    """

    def __init__(self, *, emitter: TurnStreamEmitter) -> None:
        self._emitter = emitter
        self._rounds: dict[UUID, int] = {}
        self._extractors: dict[UUID, FinalizeTextDeltaExtractor] = {}
        self._next_round = 0

    # -- the streaming opt-in (a runtime-checkable LangChain protocol) --------------------------

    def tap_output_aiter(self, run_id: UUID, output: Any) -> Any:
        del run_id
        return output

    def tap_output_iter(self, run_id: UUID, output: Any) -> Any:
        del run_id
        return output

    # -- model rounds ---------------------------------------------------------------------------

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del serialized, messages, kwargs
        self._next_round += 1
        self._rounds[run_id] = self._next_round
        self._extractors[run_id] = FinalizeTextDeltaExtractor()
        await self._emitter.round_started(round_ordinal=self._next_round)

    async def on_llm_new_token(
        self,
        token: str | list[str | dict[str, Any]],
        *,
        chunk: GenerationChunk | ChatGenerationChunk | None = None,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        # The signature is LangChain's exactly (``token`` really can be a content-block list on a
        # v1 model). ``token`` is then discarded on purpose: on this surface any content outside
        # the finalize argument is provider chatter, and §3.3's closing rule keeps all of it off
        # the wire. The only assistant text this handler can emit is text the extractor decoded.
        del token, parent_run_id, tags, kwargs
        if chunk is None:
            return
        message = getattr(chunk, "message", None)
        round_ordinal = self._rounds.get(run_id, 1)
        # The dev lens runs *before* the finalize extractor is looked up, and independently of it:
        # a provider can stream reasoning in a round that never produces a finalize call, and the
        # two surfaces have nothing to do with each other. With the lens off — the only state a
        # production process can be in — the chunk's blocks are not read at all.
        if self._emitter.reasoning_trace_enabled:
            for fragment in reasoning_deltas_from_chunk(message):
                await self._emitter.reasoning_delta(round_ordinal=round_ordinal, delta=fragment)
        extractor = self._extractors.get(run_id)
        if extractor is None:
            return
        chunks = getattr(message, "tool_call_chunks", None) or ()
        for item in chunks:
            delta = extractor.feed_tool_call_chunk(
                index=_chunk_field(item, "index"),
                name=_chunk_field(item, "name"),
                args=_chunk_field(item, "args"),
            )
            if delta:
                await self._emitter.text_delta(
                    round_ordinal=round_ordinal,
                    call_index=int(_chunk_field(item, "index") or 0),
                    delta=delta,
                )

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        del kwargs
        extractor = self._extractors.pop(run_id, None)
        round_ordinal = self._rounds.pop(run_id, 1)
        if extractor is not None and extractor.failed:
            log.error(
                "chat.turn_stream.finalize_arguments_malformed",
                turn_id=str(self._emitter.turn_id),
                round_ordinal=round_ordinal,
            )
        requested = 0
        generations = response.generations[0] if response.generations else []
        if generations:
            message = getattr(generations[0], "message", None)
            requested = len(getattr(message, "tool_calls", None) or ())
        await self._emitter.round_finished(
            round_ordinal=round_ordinal,
            requested_tool_calls=requested,
        )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        del error, kwargs
        self._extractors.pop(run_id, None)
        round_ordinal = self._rounds.pop(run_id, 1)
        await self._emitter.round_finished(round_ordinal=round_ordinal, failed=True)


def _chunk_field(item: Any, name: str) -> Any:
    """Read one field off a tool-call chunk, whichever shape the provider adapter produced.

    LangChain models emit ``ToolCallChunk`` typed dicts today; some adapters emit small objects with
    the same attribute names. Both are the *normalized* shape — no provider wire format reaches
    here — so accepting either is compatibility, not leniency about untrusted input.
    """

    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)
