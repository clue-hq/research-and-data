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
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from clue_agents.contracts import AgentRole
from clue_api.agent_runtime_wiring import (
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


def _handler(store: _Store) -> DurableAgentModelCallHandler:
    request = SimpleNamespace(
        turn_id=uuid4(),
        constitution=SimpleNamespace(
            workspace_id="ws-req", execution_id=uuid4(), role=AgentRole.ACCOUNT_RESEARCH
        ),
    )
    return DurableAgentModelCallHandler(
        request=request,  # type: ignore[arg-type]
        requested_model="openai/gpt-6.1-sol",
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


async def _call(handler: DurableAgentModelCallHandler, messages: list[Any]) -> None:
    await handler.on_chat_model_start({}, [messages], run_id=uuid4())


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
