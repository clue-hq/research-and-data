"""Lane 3 slice 1, Task 3: the durable model-call handler stamps the gateway's measured cost on
the receipt. Drives the callback with fakes; no database, no model."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from clue_agents.contracts import AgentRole
from clue_api.agent_runtime_wiring import DurableAgentModelCallHandler
from clue_gateway.metadata import COST_CENTS_KEY, COST_SOURCE_KEY
from tests.db.conftest import run_async


class _Artifacts:
    async def persist_body(self, *, workspace_id: str, data: bytes, media_type: str) -> Any:
        return SimpleNamespace(
            workspace_id=workspace_id,
            artifact_key=f"{workspace_id}/{len(data)}",
            sha256="0" * 64,
            media_type=media_type,
            byte_count=len(data),
        )


class _Turns:
    def __init__(self) -> None:
        self.receipts: list[Any] = []

    async def record_model_call(
        self, *, receipt: Any, input_ref: Any = None, output_ref: Any = None
    ) -> None:
        self.receipts.append(receipt)


def _handler(turns: _Turns, langfuse_ids: Any = None) -> DurableAgentModelCallHandler:
    request = SimpleNamespace(
        turn_id=uuid4(),
        constitution=SimpleNamespace(
            workspace_id="ws-cost", execution_id=uuid4(), role=AgentRole.HEAD_OF_ABM
        ),
    )
    return DurableAgentModelCallHandler(
        request=request,  # type: ignore[arg-type]
        requested_model="x-ai/grok-4.6",
        initial_sequence=1,
        artifacts=_Artifacts(),  # type: ignore[arg-type]
        turns=turns,  # type: ignore[arg-type]
        langfuse_ids=langfuse_ids,
    )


def _answer(metadata: dict[str, Any]) -> LLMResult:
    message = AIMessage(
        content="ok",
        response_metadata=metadata,
        usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]], llm_output={})


async def _drive(metadata: dict[str, Any]) -> Any:
    turns = _Turns()
    handler = _handler(turns)
    run_id = uuid4()
    await handler.on_chat_model_start({}, [[AIMessage(content="hi")]], run_id=run_id)
    await handler.on_llm_end(_answer(metadata), run_id=run_id)
    return turns.receipts[0]


def test_metered_answer_lands_its_usd_and_source_on_the_receipt() -> None:
    receipt = run_async(
        _drive(
            {
                COST_CENTS_KEY: "1.2345",
                COST_SOURCE_KEY: "metered",
                "model_name": "x-ai/grok-4.6",
            }
        )
    )
    assert receipt.cost_usd == Decimal("0.012345")
    assert receipt.cost_source == "metered"
    assert receipt.cost_millicredits == 0  # untouched: the credits milestone's policy


def test_unpriced_answer_is_blank_not_zero() -> None:
    receipt = run_async(_drive({COST_CENTS_KEY: "0", COST_SOURCE_KEY: "unpriced"}))
    assert receipt.cost_usd is None
    assert receipt.cost_source == "unpriced"


def test_answer_without_a_stamp_is_blank() -> None:
    receipt = run_async(_drive({"model_name": "x-ai/grok-4.6"}))
    assert receipt.cost_usd is None
    assert receipt.cost_source is None


def test_failed_call_records_no_cost() -> None:
    async def scenario() -> Any:
        turns = _Turns()
        handler = _handler(turns)
        run_id = uuid4()
        await handler.on_chat_model_start({}, [[AIMessage(content="hi")]], run_id=run_id)
        await handler.on_llm_error(RuntimeError("boom"), run_id=run_id)
        return turns.receipts[0]

    receipt = run_async(scenario())
    assert receipt.cost_usd is None and receipt.cost_source is None


def test_the_receipt_carries_the_registry_ids_for_its_run() -> None:
    from clue_obs.langfuse import LangfuseIds, LangfuseRunRegistry

    async def scenario() -> Any:
        turns = _Turns()
        registry = LangfuseRunRegistry()
        handler = _handler(turns, langfuse_ids=registry)
        run_id = uuid4()
        registry.remember(run_id, LangfuseIds(trace_id="t" * 32, observation_id="o" * 16))
        await handler.on_chat_model_start({}, [[AIMessage(content="hi")]], run_id=run_id)
        await handler.on_llm_end(_answer({"model_name": "x-ai/grok-4.6"}), run_id=run_id)
        return turns.receipts[0], registry.get(run_id)

    receipt, left = run_async(scenario())
    assert receipt.langfuse_trace_id == "t" * 32
    assert receipt.langfuse_observation_id == "o" * 16
    assert left is None  # popped: the registry does not grow with the turn


def test_without_a_registry_the_ids_are_blank() -> None:
    receipt = run_async(_drive({"model_name": "x-ai/grok-4.6"}))
    assert receipt.langfuse_trace_id is None and receipt.langfuse_observation_id is None


def test_the_gateway_stamp_names_the_answering_model_before_the_provider_field() -> None:
    from clue_gateway.metadata import ANSWERING_MODEL_KEY

    receipt = run_async(
        _drive({ANSWERING_MODEL_KEY: "served/model", "model_name": "served/modelserved/model"})
    )
    assert receipt.answering_model == "served/model"
