"""Per-call receipts for the design runtime's governed model calls (lane 3 slice 5).

The design trio runs on the platform's governed gateway, which stamps every answer with the
answering model, the settled cost and the role (``clue_gateway.metadata``). This handler collects
those stamps into ``CollectedModelCall`` records that ride the turn result; the platform turns
them into ``agent_model_call`` rows on the design leg's own turn. It is synchronous because the
design agent invokes synchronously on a worker thread. It never prices anything itself.

Attachment is at the INVOKE CONFIG, not on the model instances: config-level callbacks see every
model, tool and sub-agent event in the graph, while an instance-level one sees only the
``on_llm_*`` events of that one instance. One collector per turn therefore sees the orchestrator,
the author, the reviewer and anything they delegate to, and a receipt's ``role`` comes from the
gateway's own stamp rather than from which object the handler happened to be bolted to.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from clue_gateway.metadata import ANSWERING_MODEL_KEY, ROLE_KEY, cost_cents_from_metadata
from clue_obs.langfuse import LangfuseRunRegistry
from langchain_core.callbacks import BaseCallbackHandler

from .trace_callbacks import extract_usage


@dataclass(frozen=True)
class CollectedModelCall:
    """One governed model call, exactly as the gateway reported it.

    ``cost_cents`` is ``None`` whenever the gateway did not settle a price (an ``unpriced``
    model, or a call that failed before an answer) — never a zero nobody measured.
    """

    run_id: UUID
    sequence: int
    requested_model: str
    answering_model: str | None
    status: Literal["completed", "failed"]
    role: str | None
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cost_cents: Decimal | None
    cost_source: str | None
    langfuse_trace_id: str | None
    langfuse_observation_id: str | None
    latency_ms: float
    error_code: str | None
    started_at: datetime
    completed_at: datetime

    def as_json(self) -> dict[str, Any]:
        """The JSON-safe shape that rides the turn's ``result_json``.

        ``cost_cents`` becomes a STRING so the ``Decimal`` survives the round trip — the same
        discipline ``clue_gateway.metadata`` uses on the stamp this copied it from.
        """
        data = asdict(self)
        data["run_id"] = str(self.run_id)
        data["cost_cents"] = None if self.cost_cents is None else str(self.cost_cents)
        data["started_at"] = self.started_at.isoformat()
        data["completed_at"] = self.completed_at.isoformat()
        return data


def _error_code(error: BaseException) -> str:
    """``TimeoutError`` -> ``timeout_error``: the exception class, in the ledger's word shape."""
    name = type(error).__name__
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _response_metadata(response: Any) -> dict[str, Any]:
    """The first generation's ``response_metadata`` — where the gateway's stamps live."""
    try:
        generation = response.generations[0][0]
        return dict(getattr(generation.message, "response_metadata", None) or {})
    except (AttributeError, IndexError):
        return {}


class ModelCallCollector(BaseCallbackHandler):
    """Collects one :class:`CollectedModelCall` per model call of a turn.

    ``langfuse_ids`` is the platform's LangChain-run -> Langfuse-ids registry, injected when the
    platform is driving the turn; each receipt then names the observation its money belongs to.
    Absent, the two id fields stay ``None`` — a design process running alone still collects the
    calls, it just cannot point at a trace it never opened.
    """

    #: A callback must never break a run; LangChain swallows handler errors when this is False.
    raise_error = False

    def __init__(self, *, langfuse_ids: LangfuseRunRegistry | None = None) -> None:
        super().__init__()
        self._langfuse_ids = langfuse_ids
        self._pending: dict[UUID, tuple[int, str, datetime, float]] = {}
        self._sequence = 0
        self.calls: list[CollectedModelCall] = []

    def on_chat_model_start(
        self, serialized: Any, messages: Any, *, run_id: UUID, **kwargs: Any
    ) -> None:
        params = kwargs.get("invocation_params") or {}
        model = str(
            params.get("model")
            or (kwargs.get("metadata") or {}).get("ls_model_name")
            or "unknown"
        )
        self._sequence += 1
        self._pending[run_id] = (self._sequence, model, datetime.now(UTC), time.monotonic())

    #: The text-completion path. Same bookkeeping; chat models fire the chat variant instead.
    on_llm_start = on_chat_model_start

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._pending.pop(run_id, None)
        if pending is None:
            # An end with no start we saw — another handler's call, or a graph we joined
            # mid-flight. Never invent a receipt for a call whose beginning we never observed.
            return
        metadata = _response_metadata(response)
        usage = extract_usage(response) or {}
        cents, source = cost_cents_from_metadata(metadata)
        self._append(
            run_id,
            pending,
            status="completed",
            answering_model=str(
                metadata.get(ANSWERING_MODEL_KEY) or metadata.get("model_name") or pending[1]
            ),
            role=metadata.get(ROLE_KEY),
            usage=usage,
            cents=cents,
            source=source,
            error_code=None,
        )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._pending.pop(run_id, None)
        if pending is None:
            return
        self._append(
            run_id,
            pending,
            status="failed",
            answering_model=None,
            role=None,
            usage={},
            cents=None,
            source=None,
            error_code=_error_code(error),
        )

    def _append(
        self,
        run_id: UUID,
        pending: tuple[int, str, datetime, float],
        *,
        status: Literal["completed", "failed"],
        answering_model: str | None,
        role: Any,
        usage: dict,
        cents: Decimal | None,
        source: str | None,
        error_code: str | None,
    ) -> None:
        sequence, requested, started_at, started_clock = pending
        ids = self._langfuse_ids.pop(run_id) if self._langfuse_ids is not None else None
        self.calls.append(
            CollectedModelCall(
                run_id=run_id,
                sequence=sequence,
                requested_model=requested,
                answering_model=answering_model,
                status=status,
                role=role if isinstance(role, str) else None,
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
                cost_cents=cents,
                cost_source=source,
                langfuse_trace_id=getattr(ids, "trace_id", None),
                langfuse_observation_id=getattr(ids, "observation_id", None),
                latency_ms=(time.monotonic() - started_clock) * 1000,
                error_code=error_code,
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
        )


@dataclass(frozen=True)
class TurnCallbacks:
    """What the platform injects into a design run: opaque LangChain handlers and the id registry.

    ``handlers`` ride the invoke config alongside the turn's own collector, so the platform's
    Langfuse handler nests the whole design run under the design-leg observation.
    ``langfuse_ids`` is the registry that handler fills; the collector reads it to stamp each
    receipt with the observation its cost belongs to.
    """

    handlers: tuple[BaseCallbackHandler, ...] = ()
    langfuse_ids: LangfuseRunRegistry | None = None


def turn_collector(callbacks: TurnCallbacks | None) -> tuple[ModelCallCollector, list[Any]]:
    """The turn's ONE collector and the full callback list for its invoke config.

    A caller that wants to read the receipts back (the fleet executors, which stamp them onto the
    run's ``result_json``) supplies its own collector inside ``callbacks.handlers``; this reuses
    it rather than opening a second one that would collect the same calls twice. Every other
    caller — the CLI, the fixtures, the synchronous preview route — passes nothing and gets a
    fresh collector, so a turn ALWAYS collects its calls.
    """
    handlers: list[Any] = list(callbacks.handlers) if callbacks is not None else []
    existing = next((h for h in handlers if isinstance(h, ModelCallCollector)), None)
    if existing is not None:
        return existing, handlers
    collector = ModelCallCollector(
        langfuse_ids=callbacks.langfuse_ids if callbacks is not None else None
    )
    return collector, [collector, *handlers]


__all__ = [
    "CollectedModelCall",
    "ModelCallCollector",
    "TurnCallbacks",
    "turn_collector",
]
