"""The turn receipt names the model the gateway says answered, not LangChain's merged label.

On a streamed Grok turn through OpenRouter the provider repeats ``finish_reason`` and ``model``
on its trailing usage chunk, and LangChain's chunk merge concatenates equal strings — so the
merged generation's ``model_name`` reads ``x-ai/grok-4.6x-ai/grok-4.6``. The gateway's
``clue_answering_model`` stamp is the platform's own record of who answered; the receipt reads
it first and falls back to ``model_name`` only when the stamp is absent.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from clue_agents.contracts import AgentRole, ArtifactRef
from clue_agents.turns import AgentModelCallReceipt
from clue_api.agent_runtime_wiring import DurableAgentModelCallHandler
from clue_core import ExecutionId


class _Artifacts:
    async def persist_body(self, *, workspace_id: str, data: bytes, media_type: str) -> ArtifactRef:
        return ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=f"key-{len(data)}",
            sha256="0" * 64,
            media_type=media_type,
            byte_count=len(data),
        )


class _Turns:
    def __init__(self) -> None:
        self.receipts: list[AgentModelCallReceipt] = []

    async def record_model_call(self, *, receipt: AgentModelCallReceipt, **kwargs: Any) -> None:
        del kwargs
        self.receipts.append(receipt)


def _record(response_metadata: dict[str, Any], llm_output: dict[str, Any] | None) -> str | None:
    turns = _Turns()
    request = SimpleNamespace(
        turn_id=uuid4(),
        constitution=SimpleNamespace(
            execution_id=ExecutionId(uuid4()),
            workspace_id="ws_test",
            role=AgentRole.HEAD_OF_ABM,
        ),
    )
    handler = DurableAgentModelCallHandler(
        request=request,  # type: ignore[arg-type]
        requested_model="x-ai/grok-4.6",
        initial_sequence=1,
        artifacts=_Artifacts(),  # type: ignore[arg-type]
        turns=turns,  # type: ignore[arg-type]
    )
    run_id = UUID("00000000-0000-0000-0000-00000000a11a")

    async def drive() -> None:
        await handler.on_chat_model_start({}, [[HumanMessage(content="hi")]], run_id=run_id)
        await handler.on_llm_end(
            LLMResult(
                generations=[
                    [
                        ChatGeneration(
                            message=AIMessage(content="ok", response_metadata=response_metadata)
                        )
                    ]
                ],
                llm_output=llm_output,
            ),
            run_id=run_id,
        )

    asyncio.run(drive())
    (receipt,) = turns.receipts
    return receipt.answering_model


def test_the_receipt_prefers_the_gateway_stamp_over_the_merged_model_name() -> None:
    assert (
        _record(
            {
                "model_name": "x-ai/grok-4.6x-ai/grok-4.6",
                "clue_answering_model": "x-ai/grok-4.6",
            },
            None,
        )
        == "x-ai/grok-4.6"
    )


def test_the_receipt_falls_back_to_model_name_without_a_stamp() -> None:
    assert _record({"model_name": "openai/gpt-5-mini"}, None) == "openai/gpt-5-mini"
    assert _record({}, {"model_name": "answering/model"}) == "answering/model"
    assert _record({}, None) == "x-ai/grok-4.6"
