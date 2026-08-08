"""L6 conversation-history retention (FI Lane D D0 — charter §1.1's correctness hazard).

The seven-layer assembler spent every layer's budget in canonical ``stable_key`` order and skipped
whatever no longer fit. For six layers that is a fine convention — they hold independent compiled
cards. For L6 it was a defect: ``stable_key`` there *is* the message sequence, so a thread longer
than its budget handed the model a transcript that stopped before the turn the user had just taken.

Retention for L6 is now newest-first. Emission stays chronological, so the retained window still
reads forwards and nothing else about the layer — stable keys, receipt ordinals, exclusion reason
codes, the body-free receipt — changes. Its own module so the assembler's general contract tests
(``test_context.py``) stay untouched.

Its fixtures deliberately reuse ``test_context``'s, the way ``test_context`` itself reuses
``test_contracts.profile``: one definition of "a valid seven-layer assembly" for both files.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import UUID

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


def test_a_long_thread_keeps_its_newest_messages_and_still_reads_in_order() -> None:
    """Two hundred messages of eleven bytes each against a hundred-byte budget: exactly the last
    nine survive, and they arrive oldest-to-newest so the conversation still reads forwards."""

    receipts = _Receipts()
    layer, messages = _l6_assembly(count=200, budget=100, receipts=receipts)

    kept = [item.artifact_key for item in layer.source_refs]
    assert kept == [f"agent-artifacts/history-{n:03d}.txt" for n in range(192, 201)]
    assert layer.token_count == 99
    assert len(layer.excluded_refs) == 191
    assert set(layer.exclusion_reason_codes) == {"layer_budget_exceeded"}

    l6_bodies = [
        str(message.content) for message in messages if str(message.content).startswith("message ")
    ]
    assert l6_bodies == [f"message {n:03d}" for n in range(192, 201)]
    # The receipt still names what it dropped, in canonical order, and still carries no bodies.
    assert "message 001" not in receipts.values[0].model_dump_json()


def test_a_thread_within_budget_is_untouched_by_the_retention_direction() -> None:
    """Retention direction decides only *what* is dropped. When nothing is dropped, the layer is
    exactly what it was before the inversion."""

    layer, _ = _l6_assembly(count=5, budget=1_000, receipts=_Receipts())

    assert [item.artifact_key for item in layer.source_refs] == [
        f"agent-artifacts/history-{n:03d}.txt" for n in range(1, 6)
    ]
    assert layer.excluded_refs == ()
