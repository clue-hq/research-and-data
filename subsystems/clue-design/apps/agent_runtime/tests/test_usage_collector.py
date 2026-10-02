"""The design runtime's per-call receipts (lane 3 slice 5).

The collector copies what the governed gateway already stamped on the answer — the answering
model, the settled cost, the role — and never prices anything itself. These tests drive the
LangChain callback directly with the `LLMResult` shape the harness's models return.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from lumen_agent.usage_collector import ModelCallCollector


def _result(**metadata):
    message = AIMessage(
        content="ok",
        response_metadata={
            "model_name": "x-ai/grok-4.6",
            "clue_role": "design_author",
            "clue_cost_cents": "1.23",
            "clue_cost_source": "metered",
            "clue_answering_model": "x-ai/grok-4.6",
            **metadata,
        },
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 7,
            "total_tokens": 107,
            "input_token_details": {"cache_read": 40},
        },
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_collects_one_priced_call_per_llm_end() -> None:
    collector = ModelCallCollector()
    run_id = uuid4()
    collector.on_chat_model_start(
        {}, [[]], run_id=run_id, invocation_params={"model": "x-ai/grok-4.6"}
    )
    collector.on_llm_end(_result(), run_id=run_id)
    (call,) = collector.calls
    assert call.sequence == 1 and call.run_id == run_id
    assert call.requested_model == "x-ai/grok-4.6" and call.answering_model == "x-ai/grok-4.6"
    assert call.role == "design_author" and call.status == "completed"
    assert call.input_tokens == 100 and call.output_tokens == 7
    assert call.cache_read_input_tokens == 40
    assert call.cost_cents == Decimal("1.23") and call.cost_source == "metered"
    assert call.error_code is None and call.latency_ms >= 0


def test_a_failed_call_is_collected_with_its_error_code() -> None:
    collector = ModelCallCollector()
    run_id = uuid4()
    collector.on_chat_model_start({}, [[]], run_id=run_id, invocation_params={"model": "m"})
    collector.on_llm_error(TimeoutError("slow"), run_id=run_id)
    (call,) = collector.calls
    assert call.status == "failed" and call.error_code == "timeout_error"
    assert call.answering_model is None


def test_as_json_round_trips_decimals_as_strings() -> None:
    collector = ModelCallCollector()
    run_id = uuid4()
    collector.on_chat_model_start({}, [[]], run_id=run_id, invocation_params={"model": "m"})
    collector.on_llm_end(_result(), run_id=run_id)
    payload = collector.calls[0].as_json()
    assert payload["cost_cents"] == "1.23" and payload["run_id"] == str(run_id)


def test_an_unpriced_answer_carries_no_cost_and_says_so() -> None:
    """``unpriced`` is the gateway's "the model is on no price sheet" word. It must never read
    as a measured zero — ``cost_cents`` stays None while the source word survives."""
    collector = ModelCallCollector()
    run_id = uuid4()
    collector.on_chat_model_start({}, [[]], run_id=run_id, invocation_params={"model": "m"})
    collector.on_llm_end(
        _result(clue_cost_source="unpriced", clue_cost_cents="0"), run_id=run_id
    )
    (call,) = collector.calls
    assert call.cost_cents is None and call.cost_source == "unpriced"


def test_langfuse_ids_ride_the_receipt_when_a_registry_is_injected() -> None:
    from clue_obs.langfuse import LangfuseIds, LangfuseRunRegistry

    registry = LangfuseRunRegistry()
    run_id = uuid4()
    registry.remember(run_id, LangfuseIds(trace_id="t-1", observation_id="o-1"))
    collector = ModelCallCollector(langfuse_ids=registry)
    collector.on_chat_model_start({}, [[]], run_id=run_id, invocation_params={"model": "m"})
    collector.on_llm_end(_result(), run_id=run_id)
    (call,) = collector.calls
    assert call.langfuse_trace_id == "t-1" and call.langfuse_observation_id == "o-1"


def test_an_end_with_no_matching_start_is_ignored() -> None:
    collector = ModelCallCollector()
    collector.on_llm_end(_result(), run_id=uuid4())
    assert collector.calls == []
