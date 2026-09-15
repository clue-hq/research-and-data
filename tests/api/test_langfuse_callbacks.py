"""Lane 3 slice 3a, Task 5: the LangChain handler fills the run registry at model-call start
and writes the gateway's settled cost onto the generation before it ends."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from clue_api.langfuse_callbacks import build_langfuse_callbacks
from clue_gateway.metadata import ANSWERING_MODEL_KEY, COST_CENTS_KEY, COST_SOURCE_KEY
from clue_obs.langfuse import propagate_trace
from tests._langfuse import finished_spans, langfuse_installed
from tests.db.conftest import run_async


def _model(metadata: dict[str, Any]) -> GenericFakeChatModel:
    return GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content="hi",
                    response_metadata=metadata,
                    usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
                )
            ]
        )
    )


def test_not_installed_builds_nothing() -> None:
    assert build_langfuse_callbacks() is None


def test_the_generation_carries_the_settled_cost_and_the_registry_its_ids() -> None:
    with langfuse_installed() as (exporter, _provider):
        callbacks = build_langfuse_callbacks()
        assert callbacks is not None
        model = _model(
            {
                "model_name": "x-ai/grok-4.6",
                ANSWERING_MODEL_KEY: "x-ai/grok-4.6",
                COST_CENTS_KEY: "1.25",
                COST_SOURCE_KEY: "metered",
            }
        )
        run_ids: list[Any] = []
        original = callbacks.handler.on_chat_model_start

        def spy(*args: Any, run_id: Any, **kwargs: Any) -> Any:
            run_ids.append(run_id)
            return original(*args, run_id=run_id, **kwargs)

        callbacks.handler.on_chat_model_start = spy  # type: ignore[method-assign]

        async def go() -> None:
            with propagate_trace(trace_name="t", session_id="s", user_id="u"):
                await model.ainvoke("hello", config={"callbacks": [callbacks.handler]})

        run_async(go())
        spans = finished_spans(exporter)
    generation = next(
        s for s in spans if (s.attributes or {}).get("langfuse.observation.type") == "generation"
    )
    attrs = dict(generation.attributes or {})
    assert attrs["langfuse.observation.cost_details"] == '{"total": 0.0125}'
    assert attrs["langfuse.observation.metadata.clue_cost_source"] == "metered"
    assert attrs["langfuse.observation.model.name"] == "x-ai/grok-4.6"
    assert len(run_ids) == 1
    ids = callbacks.registry.get(run_ids[0])
    assert ids is not None
    assert ids.trace_id == format(generation.context.trace_id, "032x")
    assert ids.observation_id == format(generation.context.span_id, "016x")


def test_an_unpriced_answer_leaves_cost_alone() -> None:
    with langfuse_installed() as (exporter, _provider):
        callbacks = build_langfuse_callbacks()
        assert callbacks is not None
        model = _model({"model_name": "m", COST_CENTS_KEY: "0", COST_SOURCE_KEY: "unpriced"})

        async def go() -> None:
            await model.ainvoke("hello", config={"callbacks": [callbacks.handler]})

        run_async(go())
        spans = finished_spans(exporter)
    attrs = dict(spans[-1].attributes or {})
    assert "langfuse.observation.cost_details" not in attrs
    assert attrs["langfuse.observation.metadata.clue_cost_source"] == "unpriced"
