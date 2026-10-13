"""Each model request is saved as its messages once, plus a short manifest per call.

Until 2026-10-13 every model call saved the whole request: call 100 re-saved the messages of calls
1-99 (run 5: 183 calls, 93 MB of 116 MB stored). A conversation is append-only, so each message is
now saved once, content-addressed, and a call saves only the ordered message keys; the original
request bytes are rebuilt exactly from them.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from clue_agents.contracts import AgentRole
from clue_api.agent_runtime_wiring import (
    LONG_CONTEXT_INPUT_TOKENS,
    MESSAGE_MEDIA_TYPE,
    MODEL_INPUT_MEDIA_TYPE,
    DurableAgentModelCallHandler,
    rebuild_model_input,
)
from tests.db.conftest import run_async


class _Store:
    """Content-addressed in-memory artifact store; records every save."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.saves: list[tuple[str, str]] = []

    async def persist_body(self, *, workspace_id: str, data: bytes, media_type: str) -> Any:
        digest = hashlib.sha256(data).hexdigest()
        key = f"{workspace_id}/{digest}"
        self.blobs[key] = data
        self.saves.append((key, media_type))
        return SimpleNamespace(
            workspace_id=workspace_id,
            artifact_key=key,
            sha256=digest,
            media_type=media_type,
            byte_count=len(data),
        )

    async def read(self, key: str) -> bytes:
        return self.blobs[key]

    def saved(self, media_type: str) -> list[str]:
        return [key for key, kind in self.saves if kind == media_type]


class _Turns:
    async def record_model_call(self, **_: Any) -> None:
        return None


def _handler(store: _Store, model: str = "openai/gpt-6.1-sol") -> DurableAgentModelCallHandler:
    request = SimpleNamespace(
        turn_id=uuid4(),
        constitution=SimpleNamespace(
            workspace_id="ws-req", execution_id=uuid4(), role=AgentRole.ACCOUNT_RESEARCH
        ),
    )
    return DurableAgentModelCallHandler(
        request=request,  # type: ignore[arg-type]
        requested_model=model,
        initial_sequence=1,
        artifacts=store,  # type: ignore[arg-type]
        turns=_Turns(),  # type: ignore[arg-type]
    )


def _old_format(messages: list[list[Any]]) -> bytes:
    """The request bytes the handler saved before 2026-10-13."""
    return json.dumps(
        [[message.model_dump(mode="json") for message in batch] for batch in messages],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()


def _conversation(rounds: int) -> list[Any]:
    messages: list[Any] = [SystemMessage("system " * 200), HumanMessage("Research Dialpad.")]
    for i in range(rounds):
        call = {"id": f"c{i}", "name": "read_file", "args": {"file_path": f"/r/{i}.json"}}
        messages += [
            AIMessage("", tool_calls=[call], id=f"ai-{i}"),
            ToolMessage(f"result {i} " + "é" * 300, tool_call_id=f"c{i}", id=f"tool-{i}"),
        ]
    return messages


async def _call(
    handler: DurableAgentModelCallHandler, messages: list[Any], run_id: Any = None
) -> None:
    await handler.on_chat_model_start({}, [messages], run_id=run_id or uuid4())


async def _end(handler: DurableAgentModelCallHandler, run_id: Any, sent: int, cached: int) -> None:
    """The provider's reply: ``sent`` input tokens, ``cached`` of them read from its cache."""
    message = AIMessage(
        content="",
        usage_metadata={
            "input_tokens": sent,
            "output_tokens": 1,
            "total_tokens": sent + 1,
            "input_token_details": {"cache_read": cached},
        },
    )
    await handler.on_llm_end(
        LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id
    )


def test_each_message_is_saved_once_across_calls() -> None:
    async def case() -> None:
        store = _Store()
        handler = _handler(store)
        for rounds in range(5):
            await _call(handler, _conversation(rounds))
        assert len(store.saved(MODEL_INPUT_MEDIA_TYPE)) == 5
        message_saves = store.saved(MESSAGE_MEDIA_TYPE)
        assert len(message_saves) == len(set(message_saves)) == 2 + 2 * 4
        whole = sum(len(_old_format([_conversation(r)])) for r in range(5))
        stored = sum(len(body) for body in store.blobs.values())
        assert stored < whole / 2

    run_async(case())


def test_the_manifest_rebuilds_the_exact_request_bytes() -> None:
    async def case() -> None:
        store = _Store()
        handler = _handler(store)
        conversations = [_conversation(r) for r in range(4)]
        for messages in conversations:
            await _call(handler, messages)
        for messages, manifest_key in zip(
            conversations, store.saved(MODEL_INPUT_MEDIA_TYPE), strict=True
        ):
            rebuilt = await rebuild_model_input(store.blobs[manifest_key], store.read)
            assert rebuilt == _old_format([messages])

    run_async(case())


def test_a_message_changed_by_clearing_is_saved_as_a_new_message() -> None:
    async def case() -> None:
        store = _Store()
        handler = _handler(store)
        messages = _conversation(2)
        await _call(handler, messages)
        cleared = [
            m.model_copy(update={"content": "[Earlier result removed. Re-read /r/0.json.]"})
            if isinstance(m, ToolMessage) and m.tool_call_id == "c0"
            else m
            for m in messages
        ]
        before = len(store.saved(MESSAGE_MEDIA_TYPE))
        await _call(handler, cleared)
        assert len(store.saved(MESSAGE_MEDIA_TYPE)) == before + 1
        manifest = store.blobs[store.saved(MODEL_INPUT_MEDIA_TYPE)[-1]]
        assert await rebuild_model_input(manifest, store.read) == _old_format([cleared])

    run_async(case())


def test_a_new_turn_saves_each_message_once_again_and_no_more() -> None:
    async def case() -> None:
        store = _Store()
        await _call(_handler(store), _conversation(3))
        first = len(store.saved(MESSAGE_MEDIA_TYPE))
        handler = _handler(store)
        await _call(handler, _conversation(3))
        await _call(handler, _conversation(3))
        assert len(store.saved(MESSAGE_MEDIA_TYPE)) == 2 * first

    run_async(case())


def test_an_old_full_request_snapshot_is_returned_as_it_is() -> None:
    async def case() -> None:
        old = _old_format([_conversation(1)])
        assert await rebuild_model_input(old, _Store().read) == old

    run_async(case())


def test_a_manifest_whose_messages_do_not_match_is_refused() -> None:
    async def case() -> None:
        store = _Store()
        handler = _handler(store)
        await _call(handler, _conversation(1))
        manifest_key = store.saved(MODEL_INPUT_MEDIA_TYPE)[0]
        message_key = store.saved(MESSAGE_MEDIA_TYPE)[0]
        store.blobs[message_key] = b'{"tampered":true}'
        with pytest.raises(ValueError, match="do not match"):
            await rebuild_model_input(store.blobs[manifest_key], store.read)

    run_async(case())


def test_each_call_reports_a_request_the_provider_did_not_serve_from_its_cache() -> None:
    """Run 6 (2026-10-12) paid $9.49 in cache re-writes nobody saw until the bill. Each call
    now says whether it appended to the previous request and how much of it was cached."""

    async def case() -> None:
        handler = _handler(_Store())
        ids = [uuid4() for _ in range(4)]
        with structlog.testing.capture_logs() as events:
            await _call(handler, _conversation(2), ids[0])
            await _end(handler, ids[0], 30_000, 0)  # the first request: nothing to compare
            await _call(handler, _conversation(3), ids[1])
            await _end(handler, ids[1], 40_000, 30_000)  # an append served from the cache
            await _call(handler, _conversation(4), ids[2])
            await _end(handler, ids[2], 50_000, 5_000)  # an append the provider re-wrote
            edited = [  # an earlier message changed (what result clearing does)
                m.model_copy(update={"content": "[Earlier result removed. Re-read /r/0.json.]"})
                if isinstance(m, ToolMessage) and m.tool_call_id == "c0"
                else m
                for m in _conversation(5)
            ]
            await _call(handler, edited, ids[3])
            await _end(handler, ids[3], 60_000, 10_000)
        warnings = [(e["event"], e["sequence"]) for e in events if e["log_level"] == "warning"]
        assert warnings == [
            ("model_call.cache_miss_on_append", 3),
            ("model_call.request_not_append", 4),
        ]
        changed = next(e for e in events if e["event"] == "model_call.request_not_append")
        assert changed["changed_at"] == 3 and changed["previous_messages"] == 10
        assert changed["cache_read_input_tokens"] == 10_000 and changed["input_tokens"] == 60_000
        assert [e["shape"] for e in events if e["event"] == "model_call.cache"] == [
            "first",
            "append",
        ]

    run_async(case())


def test_a_request_past_the_long_context_price_tier_is_reported() -> None:
    async def case() -> None:
        limit = LONG_CONTEXT_INPUT_TOKENS["openai/gpt-6.1-sol"]
        handler = _handler(_Store())
        run_id = uuid4()
        with structlog.testing.capture_logs() as events:
            await _call(handler, _conversation(1), run_id)
            await _end(handler, run_id, limit + 1, limit)
        tier = [e for e in events if e["event"] == "model_call.long_context_tier"]
        assert len(tier) == 1 and tier[0]["limit"] == limit and tier[0]["input_tokens"] == limit + 1
        other = _handler(_Store(), model="x-ai/grok-4.6")
        with structlog.testing.capture_logs() as events:
            await _call(other, _conversation(1), run_id)
            await _end(other, run_id, limit + 1, limit)
        assert not [e for e in events if e["event"] == "model_call.long_context_tier"]

    run_async(case())
