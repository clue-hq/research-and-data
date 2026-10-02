"""The turn receipt names the model the gateway says answered, not LangChain's merged label.

On a streamed Grok turn through OpenRouter the provider repeats ``finish_reason`` and ``model``
on its trailing usage chunk, and LangChain's chunk merge concatenates equal strings — so the
merged generation's ``model_name`` reads ``x-ai/grok-4.6x-ai/grok-4.6``. The gateway's
``clue_answering_model`` stamp is the platform's own record of who answered; the receipt reads
it first and falls back to ``model_name`` only when the stamp is absent.

The same handler is where a chat turn meets the provider, so the provider-incident tests live
here too: a refused call names the refusal on the receipt and opens an incident, a served call
closes one, and a handler built without a database still names the refusal.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
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


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        turn_id=uuid4(),
        constitution=SimpleNamespace(
            execution_id=ExecutionId(uuid4()),
            workspace_id="ws_test",
            role=AgentRole.HEAD_OF_ABM,
        ),
    )


def _record(response_metadata: dict[str, Any], llm_output: dict[str, Any] | None) -> str | None:
    turns = _Turns()
    handler = DurableAgentModelCallHandler(
        request=_request(),  # type: ignore[arg-type]
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


def test_inherited_parent_callback_does_not_charge_a_child_call():
    async def drive():
        parent, child = _request(), _request()
        journals = [_Turns(), _Turns()]
        handlers = [
            DurableAgentModelCallHandler(
                request=request,
                requested_model="fixture/model",
                initial_sequence=1,
                artifacts=_Artifacts(),
                turns=journal,
            )
            for request, journal in zip((parent, child), journals, strict=True)
        ]
        run_id = uuid4()
        for handler in handlers:
            await handler.on_chat_model_start(
                {},
                [[HumanMessage(content="source reference")]],
                run_id=run_id,
                metadata={"agent_execution_id": str(child.constitution.execution_id)},
            )
        result = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="done"))]])
        for handler in handlers:
            await handler.on_llm_end(result, run_id=run_id)
            await handler.on_llm_end(result, run_id=run_id)  # duplicate end is also harmless
        assert journals[0].receipts == []
        assert len(journals[1].receipts) == 1
        assert journals[1].receipts[0].execution_id == child.constitution.execution_id

    asyncio.run(drive())


class _Denied(Exception):
    """What the OpenAI-compatible SDK raises when OpenRouter refuses on a weekly key cap."""

    status_code = 403

    def __init__(self) -> None:
        super().__init__(
            "Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit)', "
            "'code': 403}}"
        )


def _handler_with_incidents(turns: _Turns) -> DurableAgentModelCallHandler:
    @asynccontextmanager
    async def factory() -> AsyncIterator[object]:
        yield object()

    return DurableAgentModelCallHandler(
        request=_request(),  # type: ignore[arg-type]
        requested_model="x-ai/grok-4.6",
        initial_sequence=1,
        artifacts=_Artifacts(),  # type: ignore[arg-type]
        turns=turns,  # type: ignore[arg-type]
        incidents_conn_factory=factory,  # type: ignore[arg-type]
    )


def _watch_the_recorder(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    """Both recorder entry points, replaced by what they were asked to record."""
    calls: list[tuple[str, object]] = []

    async def fake_failure(
        conn: object, failure: Any, *, surface: str, workspace_id: str | None, now: Any
    ) -> None:
        calls.append(("failed", (failure.reason, surface, workspace_id)))

    async def fake_success(conn: object, provider: str, *, now: Any) -> None:
        calls.append(("succeeded", provider))

    monkeypatch.setattr("clue_api.agent_runtime_wiring.record_failure", fake_failure)
    monkeypatch.setattr("clue_api.agent_runtime_wiring.record_success", fake_success)
    return calls


def test_a_refused_model_call_records_the_provider_code_and_an_incident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _watch_the_recorder(monkeypatch)
    turns = _Turns()
    handler = _handler_with_incidents(turns)
    run_id = UUID("00000000-0000-0000-0000-00000000b22b")

    async def drive() -> None:
        await handler.on_chat_model_start({}, [[HumanMessage(content="hi")]], run_id=run_id)
        await handler.on_llm_error(_Denied(), run_id=run_id)

    asyncio.run(drive())
    (receipt,) = turns.receipts
    assert receipt.error_code == "provider_refused:openrouter:key_limit"
    assert calls == [("failed", ("key_limit", "chat_turn", "ws_test"))]


def test_a_completed_model_call_closes_the_providers_incidents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _watch_the_recorder(monkeypatch)
    turns = _Turns()
    handler = _handler_with_incidents(turns)
    run_id = UUID("00000000-0000-0000-0000-00000000b33b")

    async def drive() -> None:
        await handler.on_chat_model_start({}, [[HumanMessage(content="hi")]], run_id=run_id)
        await handler.on_llm_end(
            LLMResult(
                generations=[
                    [
                        ChatGeneration(
                            message=AIMessage(
                                content="ok",
                                response_metadata={"clue_answering_model": "x-ai/grok-4.6"},
                            )
                        )
                    ]
                ]
            ),
            run_id=run_id,
        )

    asyncio.run(drive())
    assert calls == [("succeeded", "openrouter")]


def _error_code_without_a_factory(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> tuple[str | None, list[tuple[str, object]]]:
    calls = _watch_the_recorder(monkeypatch)
    turns = _Turns()
    handler = DurableAgentModelCallHandler(
        request=_request(),  # type: ignore[arg-type]
        requested_model="x-ai/grok-4.6",
        initial_sequence=1,
        artifacts=_Artifacts(),  # type: ignore[arg-type]
        turns=turns,  # type: ignore[arg-type]
    )
    run_id = UUID("00000000-0000-0000-0000-00000000b44b")

    async def drive() -> None:
        await handler.on_chat_model_start({}, [[HumanMessage(content="hi")]], run_id=run_id)
        await handler.on_llm_error(error, run_id=run_id)

    asyncio.run(drive())
    (receipt,) = turns.receipts
    return receipt.error_code, calls


def test_without_a_factory_the_handler_records_nothing_but_still_names_the_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Classification is the receipt's business and does not need a database; only the incident
    # does. A handler built without a connection factory still tells the truth on the row.
    error_code, calls = _error_code_without_a_factory(monkeypatch, _Denied())
    assert error_code == "provider_refused:openrouter:key_limit"
    assert calls == []


def test_an_unclassified_failure_keeps_the_class_name_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_code, calls = _error_code_without_a_factory(monkeypatch, RuntimeError("boom"))
    assert error_code == "runtime_error"
    assert calls == []


@asynccontextmanager
async def _a_database_that_refuses() -> AsyncIterator[object]:
    raise RuntimeError("db down")
    yield object()  # pragma: no cover - unreachable, kept so the function is a generator


def _handler_over_a_refusing_database(turns: _Turns) -> DurableAgentModelCallHandler:
    return DurableAgentModelCallHandler(
        request=_request(),  # type: ignore[arg-type]
        requested_model="x-ai/grok-4.6",
        initial_sequence=1,
        artifacts=_Artifacts(),  # type: ignore[arg-type]
        turns=turns,  # type: ignore[arg-type]
        incidents_conn_factory=_a_database_that_refuses,  # type: ignore[arg-type]
    )


def test_a_database_that_refuses_a_connection_cannot_fail_the_model_callback() -> None:
    # The incident is the observation, never the event. If the connection itself cannot be
    # opened, the turn carries on and the receipt still says what the provider did.
    turns = _Turns()
    handler = _handler_over_a_refusing_database(turns)
    failed_run = UUID("00000000-0000-0000-0000-00000000b55b")
    served_run = UUID("00000000-0000-0000-0000-00000000b66b")

    async def drive() -> None:
        await handler.on_chat_model_start({}, [[HumanMessage(content="hi")]], run_id=failed_run)
        await handler.on_llm_error(_Denied(), run_id=failed_run)
        await handler.on_chat_model_start({}, [[HumanMessage(content="hi")]], run_id=served_run)
        await handler.on_llm_end(
            LLMResult(
                generations=[
                    [
                        ChatGeneration(
                            message=AIMessage(
                                content="ok",
                                response_metadata={"clue_answering_model": "x-ai/grok-4.6"},
                            )
                        )
                    ]
                ]
            ),
            run_id=served_run,
        )

    asyncio.run(drive())
    failed, served = turns.receipts
    assert failed.error_code == "provider_refused:openrouter:key_limit"
    assert served.answering_model == "x-ai/grok-4.6"
