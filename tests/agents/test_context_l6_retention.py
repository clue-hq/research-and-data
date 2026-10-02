"""L6 conversation history — the whole thread arrives, and its size is recorded.

Two rulings meet in this file. FI Lane D D0 (charter §1.1) found the first defect: the assembler
spent every layer's budget in canonical ``stable_key`` order and skipped whatever no longer fit,
which for L6 — where ``stable_key`` *is* the message sequence — handed the model a transcript that
stopped before the turn the user had just taken. Retention was inverted to newest-first.

The founder's ruling of 2026-09-14 removed the drop entirely: no layer budget may fail a turn or
cost it context. So L6 now keeps **every** message, emits them chronologically as it always did,
reports the thread's true cost on the manifest, and — when that cost is over the policy number —
logs one warning. These tests hold that: the long thread is complete, in order, fully receipted.

Its fixtures deliberately reuse ``test_context``'s, the way ``test_context`` itself reuses
``test_contracts.profile``: one definition of "a valid seven-layer assembly" for both files.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import UUID

import structlog.testing
from langchain_core.messages import BaseMessage

from clue_agents.context import (
    DeterministicAgentContextAssembler,
    HistoryLayerSource,
    LayerBudget,
)
from clue_agents.contracts import ContextLayer, ContextLayerManifest
from clue_agents.ports import HistoryMessageRef
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


def _history(
    count: int, *, body: Callable[[int], str] = lambda n: f"message {n:03d}"
) -> tuple[tuple[HistoryMessageRef, ...], _ArtifactReader]:
    """``count`` thread messages, sequence 1..count, each with a readable body."""

    refs: list[HistoryMessageRef] = []
    bodies: dict[str, bytes] = {}
    for sequence in range(1, count + 1):
        ref = artifact(f"history-{sequence:03d}.txt")
        bodies[ref.artifact_key] = body(sequence).encode("utf-8")
        refs.append(
            HistoryMessageRef(
                message_id=UUID(int=sequence),
                turn_id=TURN_ID,
                sequence=sequence,
                role="user" if sequence % 2 else "assistant",
                body_ref=ref,
            )
        )
    return tuple(refs), _ArtifactReader(bodies)


def _l6_assembly(
    *, count: int, budget: int, receipts: _Receipts
) -> tuple[ContextLayerManifest, tuple[BaseMessage, ...]]:
    """Assemble a request whose only interesting layer is L6, and return that layer + messages."""

    history, reader = _history(count)
    sources = list(_sources())
    sources[5] = HistoryLayerSource(reader)  # type: ignore[call-overload]
    policy = _policy().model_copy(
        update={
            "budgets": tuple(
                LayerBudget(
                    layer=layer,
                    max_tokens=budget if layer is ContextLayer.L6_CONVERSATION else 1_000,
                )
                for layer in ContextLayer
            )
        }
    )
    assembled = asyncio.run(
        DeterministicAgentContextAssembler(
            sources=sources,
            policy=policy,
            receipts=receipts,
            clock=lambda: NOW,
        ).assemble(request=request(), profile=profile(), history=history)
    )
    return assembled.manifest.layers[5], assembled.messages


def test_a_long_thread_keeps_every_message_in_order_and_records_its_size() -> None:
    """Forty messages of eleven bytes each against a budget that fits five: all forty survive,
    oldest-to-newest, each one receipted, and the overrun is reported rather than enforced."""

    receipts = _Receipts()
    with structlog.testing.capture_logs() as events:
        layer, messages = _l6_assembly(count=40, budget=55, receipts=receipts)

    kept = [item.artifact_key for item in layer.source_refs]
    assert kept == [f"agent-artifacts/history-{n:03d}.txt" for n in range(1, 41)]
    assert layer.token_count == 40 * 11
    assert layer.excluded_refs == ()
    assert layer.exclusion_reason_codes == ()

    l6_refs = [ref for ref in receipts.values[0].refs if ref.layer is ContextLayer.L6_CONVERSATION]
    assert len(l6_refs) == 40
    assert {ref.disposition for ref in l6_refs} == {"included"}

    l6_bodies = [
        str(message.content) for message in messages if str(message.content).startswith("message ")
    ]
    assert l6_bodies == [f"message {n:03d}" for n in range(1, 41)]
    # The receipt still names every message it carried, and still carries no bodies.
    assert "message 001" not in receipts.values[0].model_dump_json()

    over = [item for item in events if item["event"] == "agent_turn.context_layer_over_budget"]
    assert [(item["layer"], item["token_count"], item["token_budget"]) for item in over] == [
        ("l6_conversation", 440, 55)
    ]


def test_a_thread_within_budget_is_untouched_by_the_retention_direction() -> None:
    """A short thread reads exactly as it always did — canonical order, nothing excluded — and no
    overrun is reported, which is what distinguishes it from the long thread above."""

    layer, _ = _l6_assembly(count=5, budget=1_000, receipts=_Receipts())

    assert [item.artifact_key for item in layer.source_refs] == [
        f"agent-artifacts/history-{n:03d}.txt" for n in range(1, 6)
    ]
    assert layer.excluded_refs == ()
