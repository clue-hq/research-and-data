"""A continued Head-of-ABM turn appends to the resumed conversation (spec 2026-09-29 §3.1)."""

from __future__ import annotations

import asyncio
from uuid import UUID

from clue_agents.context import DeterministicAgentContextAssembler, HistoryLayerSource
from clue_agents.contracts import ContextLayer, ContinuationRef
from clue_agents.ports import HistoryMessageRef
from clue_core import ExecutionId
from tests.agents.conftest import NOW, artifact
from tests.agents.test_context import (
    TURN_ID,
    _ArtifactReader,
    _policy,
    _Receipts,
    _sources,
    request,
)
from tests.agents.test_contracts import profile

RESUMED_TURN = UUID("00000000-0000-0000-0000-00000000a001")
RESUMED_EXECUTION = ExecutionId(UUID("00000000-0000-0000-0000-00000000e001"))
GAP_IDS = (
    UUID("00000000-0000-0000-0000-00000000b001"),
    UUID("00000000-0000-0000-0000-00000000b002"),
)
GAP_BODIES = ("What did the stopped turn ask?", "It was stopped before it answered.")


def _gap() -> tuple[HistoryMessageRef, ...]:
    return tuple(
        HistoryMessageRef(
            message_id=message_id,
            turn_id=UUID("00000000-0000-0000-0000-00000000c001"),
            sequence=index,
            role="user" if index == 3 else "assistant",
            body_ref=artifact(f"gap-{index}.txt"),
        )
        for index, message_id in zip((3, 4), GAP_IDS, strict=True)
    )


def _assembler(receipts: _Receipts | None = None) -> DeterministicAgentContextAssembler:
    reader = _ArtifactReader(
        {
            artifact(f"gap-{index}.txt").artifact_key: body.encode()
            for index, body in zip((3, 4), GAP_BODIES, strict=True)
        }
    )
    sources = tuple(
        HistoryLayerSource(reader) if s.layer is ContextLayer.L6_CONVERSATION else s
        for s in _sources()
    )
    return DeterministicAgentContextAssembler(
        sources=sources, policy=_policy(), receipts=receipts or _Receipts(), clock=lambda: NOW
    )


def _continuation() -> ContinuationRef:
    return ContinuationRef(
        turn_id=RESUMED_TURN, execution_id=RESUMED_EXECUTION, gap_message_ids=GAP_IDS
    )


def test_without_continuation_the_opening_context_is_unchanged() -> None:
    before = asyncio.run(
        _assembler().assemble(request=request(), profile=profile(), history=_gap())
    )
    after = asyncio.run(
        _assembler().assemble(
            request=request(), profile=profile(), history=_gap(), continuation=None
        )
    )
    assert [m.content for m in after.messages] == [m.content for m in before.messages]
    assert after.messages[0].content == "layer 1"
    assert after.manifest.aggregate_sha256 == before.manifest.aggregate_sha256
    assert after.continuation is None


def test_a_continued_turn_sends_gap_then_cards_then_the_message() -> None:
    receipts = _Receipts()
    assembler = _assembler(receipts)
    ctx = asyncio.run(
        assembler.assemble(
            request=request(), profile=profile(), history=_gap(), continuation=_continuation()
        )
    )

    assert [m.content for m in ctx.messages] == [
        *GAP_BODIES,
        "layer 2",
        "layer 3",
        "layer 4",
        "layer 5",
        "layer 7",
    ]
    # The system prompt is already in the resumed state; its manifest still names it, so a
    # prompt change stays visible in the receipt.
    assert tuple(layer.layer for layer in ctx.manifest.layers) == tuple(ContextLayer)
    assert ctx.manifest.layers[0].source_refs
    assert ctx.continuation == _continuation()
    assert receipts.values[0].manifest.aggregate_sha256 == ctx.manifest.aggregate_sha256


def test_the_receipt_of_a_continued_turn_differs_from_a_fresh_one() -> None:
    fresh = asyncio.run(_assembler().assemble(request=request(), profile=profile(), history=_gap()))
    continued = asyncio.run(
        _assembler().assemble(
            request=request(), profile=profile(), history=_gap(), continuation=_continuation()
        )
    )
    assert continued.manifest.aggregate_sha256 != fresh.manifest.aggregate_sha256
    assert request().turn_id == TURN_ID
