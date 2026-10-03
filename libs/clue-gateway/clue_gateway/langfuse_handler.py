"""The Langfuse LangChain handler, adapted for the platform (lane 3 slice 3, design §3.3).

Lives in ``clue_gateway`` since 2026-10-03 (agent-scoped tracing spec, R7): the design subsystem
runs agents too (design turns, the brand-brief agent in the ingestion pool) and may import the
gateway but never ``clue_api``. ``clue_api.langfuse_callbacks`` re-exports it unchanged. The cost
stamp it writes is the gateway's own metadata, so this is its natural home.

The SDK's handler reports the graph — agent, chain nodes, sub-agents, tools, generations — and
keeps each LangChain run's observation in ``self._runs`` from its start event to its end event.
Two things it cannot know are added here: (1) at model-call start, the generation's trace and
observation ids are copied into a :class:`LangfuseRunRegistry` keyed by the LangChain run id, so
the durable recorder (which sees the same run id) stamps them on the ``agent_model_call``
receipt; (2) at model-call end, the gateway's settled cost stamp on the answer is written onto
the generation before the SDK ends it, so Langfuse shows the platform's number (R2), never its
own price-table estimate.

LangChain waits for every handler's start event before the model call proceeds, so the registry
is filled before any end event runs; end events of different handlers run concurrently, which is
why the cost update lives here and not in the recorder.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from langchain_core.outputs import LLMResult
from langfuse.langchain import CallbackHandler

from clue_gateway.metadata import ANSWERING_MODEL_KEY, cost_cents_from_metadata
from clue_obs.langfuse import LangfuseIds, LangfuseRunRegistry, langfuse_is_installed

__all__ = ["ClueLangfuseHandler", "LangfuseCallbacks", "build_langfuse_callbacks"]


class ClueLangfuseHandler(CallbackHandler):
    """The SDK handler plus the registry fill and the cost stamp."""

    # The SDK attaches/detaches the current OTel observation in each callback. LangChain
    # otherwise runs synchronous callbacks in an executor's copied context, so provider
    # calls inside an async tool become siblings of that tool and context tokens cannot
    # be restored. Run in the caller's task; concurrent tools still have isolated contexts.
    run_inline = True

    def __init__(self, registry: LangfuseRunRegistry) -> None:
        super().__init__()
        self._registry = registry

    def _remember(self, run_id: UUID) -> None:
        current = getattr(self, "_runs", {}).get(run_id)
        trace_id = getattr(current, "trace_id", None)
        if not isinstance(trace_id, str):
            return
        observation_id = getattr(current, "id", None)
        self._registry.remember(
            run_id,
            LangfuseIds(
                trace_id=trace_id,
                observation_id=observation_id if isinstance(observation_id, str) else None,
            ),
        )

    def on_chat_model_start(
        self, serialized: Any, messages: Any, *, run_id: UUID, **kwargs: Any
    ) -> Any:
        result = super().on_chat_model_start(serialized, messages, run_id=run_id, **kwargs)
        self._remember(run_id)
        return result

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: UUID, **kwargs: Any) -> Any:
        result = super().on_llm_start(serialized, prompts, run_id=run_id, **kwargs)
        self._remember(run_id)
        return result

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> Any:
        current = getattr(self, "_runs", {}).get(run_id)
        if current is not None:
            update = _cost_update(response)
            if update:
                current.update(**update)
        return super().on_llm_end(response, run_id=run_id, **kwargs)


def _cost_update(response: LLMResult) -> dict[str, Any]:
    """What the gateway stamped on the answer, in the SDK's fields. Empty when there is no stamp."""
    try:
        generation = response.generations[-1][-1]
    except IndexError:
        return {}
    message = getattr(generation, "message", None)
    metadata = getattr(message, "response_metadata", None) or {}
    cents, source = cost_cents_from_metadata(metadata)
    update: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    if cents is not None:
        update["cost_details"] = {"total": float(cents / Decimal(100))}
    if source is not None:
        meta["clue_cost_source"] = source
    served = metadata.get(ANSWERING_MODEL_KEY)
    if isinstance(served, str) and served:
        update["model"] = served
        meta["clue_answering_model"] = served
    if meta:
        update["metadata"] = meta
    return update


@dataclass(frozen=True)
class LangfuseCallbacks:
    handler: ClueLangfuseHandler
    registry: LangfuseRunRegistry


def build_langfuse_callbacks() -> LangfuseCallbacks | None:
    """One handler + registry per graph invocation; ``None`` when Langfuse is not installed, so
    callers leave their callback tuples exactly as they were."""
    if not langfuse_is_installed():
        return None
    registry = LangfuseRunRegistry()
    return LangfuseCallbacks(handler=ClueLangfuseHandler(registry), registry=registry)
