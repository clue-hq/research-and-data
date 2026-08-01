from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import pytest

from clue_agents.context import (
    ContextAssemblyPolicy,
    ContextAssemblyReceipt,
    ContextCandidate,
    DeterministicAgentContextAssembler,
    LayerBudget,
    TurnLayerSource,
    Utf8ByteTokenCounter,
)
from clue_agents.contracts import (
    AgentProfile,
    AgentTurnRequest,
    ArtifactRef,
    ContextLayer,
)
from clue_agents.ports import HistoryMessageRef
from tests.agents.conftest import NOW, SHA_A, artifact, constitution, domain_ref
from tests.agents.test_contracts import profile

TURN_ID = UUID("00000000-0000-0000-0000-000000000631")


def request(**overrides: object) -> AgentTurnRequest:
    values: dict[str, object] = {
        "turn_id": TURN_ID,
        "thread_id": "thread-1",
        "constitution": constitution(),
        "user_message_artifact_ref": artifact("user-message.txt"),
        "requested_at": NOW,
    }
    values.update(overrides)
    return AgentTurnRequest.model_validate(values)


@dataclass
class _Source:
    layer: ContextLayer
    candidates: tuple[ContextCandidate, ...]

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del request, profile, history
        return self.candidates


class _Receipts:
    def __init__(self) -> None:
        self.values: list[ContextAssemblyReceipt] = []

    async def record(
        self,
        *,
        request: AgentTurnRequest,
        receipt: ContextAssemblyReceipt,
    ) -> None:
        assert request.turn_id == TURN_ID
        self.values.append(receipt)


def _policy(*, l3_budget: int = 1_000) -> ContextAssemblyPolicy:
    return ContextAssemblyPolicy(
        version="opening-context-v1",
        token_counter_version="utf8-bytes-v1",
        budgets=tuple(
            LayerBudget(
                layer=layer,
                max_tokens=l3_budget if layer is ContextLayer.L3_PROJECT else 1_000,
            )
            for layer in ContextLayer
        ),
    )


def _sources(*, cross_workspace: bool = False) -> tuple[_Source, ...]:
    values: list[_Source] = []
    for index, layer in enumerate(ContextLayer, start=1):
        values.append(
            _Source(
                layer=layer,
                candidates=(
                    ContextCandidate(
                        stable_key=f"{index:02d}",
                        ref=domain_ref(
                            f"item-{index}",
                            workspace_id="ws-2" if cross_workspace and index == 4 else "ws-1",
                        ),
                        body=f"layer {index}",
                        materialized_path=(
                            f"context/layer-{index}.md"
                            if layer not in {ContextLayer.L1_IDENTITY, ContextLayer.L6_CONVERSATION}
                            else None
                        ),
                        role="user" if layer is ContextLayer.L7_TURN else "system",
                    ),
                ),
            )
        )
    return tuple(values)


def test_context_assembly_is_deterministic_body_free_and_exactly_seven_layers() -> None:
    receipts = _Receipts()
    assembler = DeterministicAgentContextAssembler(
        sources=_sources(),
        policy=_policy(),
        receipts=receipts,
        clock=lambda: NOW,
    )

    first = asyncio.run(assembler.assemble(request=request(), profile=profile(), history=()))
    second = asyncio.run(assembler.assemble(request=request(), profile=profile(), history=()))

    assert first.manifest == second.manifest
    assert tuple(layer.layer for layer in first.manifest.layers) == tuple(ContextLayer)
    assert len(first.messages) == 7
    assert len(first.materializations) == 5
    assert receipts.values[0].manifest.aggregate_sha256 == first.manifest.aggregate_sha256
    assert receipts.values[0].budgets == _policy().budgets
    dump = receipts.values[0].model_dump_json()
    assert "layer 1" not in dump
    assert "layer 7" not in dump


def test_context_budget_excludes_atomic_items_with_stable_reason() -> None:
    sources = list(_sources())
    sources[2] = _Source(
        layer=ContextLayer.L3_PROJECT,
        candidates=(
            ContextCandidate(
                stable_key="a-first",
                ref=domain_ref("first"),
                body="1234",
            ),
            ContextCandidate(
                stable_key="b-second",
                ref=domain_ref("second"),
                body="5678",
            ),
        ),
    )
    receipts = _Receipts()
    assembled = asyncio.run(
        DeterministicAgentContextAssembler(
            sources=sources,
            policy=_policy(l3_budget=4),
            receipts=receipts,
            clock=lambda: NOW,
        ).assemble(request=request(), profile=profile(), history=())
    )

    layer = assembled.manifest.layers[2]
    assert layer.source_refs == (domain_ref("first"),)
    assert layer.excluded_refs == (domain_ref("second"),)
    assert layer.exclusion_reason_codes == ("layer_budget_exceeded",)
    assert layer.token_count == 4


def test_required_authority_fails_instead_of_running_with_truncated_context() -> None:
    sources = list(_sources())
    sources[0] = _Source(
        layer=ContextLayer.L1_IDENTITY,
        candidates=(
            ContextCandidate(
                stable_key="identity",
                ref=domain_ref("identity"),
                body="required identity",
                required=True,
            ),
        ),
    )
    policy = _policy().model_copy(
        update={
            "budgets": tuple(
                LayerBudget(
                    layer=layer,
                    max_tokens=1 if layer is ContextLayer.L1_IDENTITY else 1_000,
                )
                for layer in ContextLayer
            )
        }
    )
    with pytest.raises(ValueError, match="required l1_identity"):
        asyncio.run(
            DeterministicAgentContextAssembler(
                sources=sources,
                policy=policy,
                receipts=_Receipts(),
                clock=lambda: NOW,
            ).assemble(request=request(), profile=profile(), history=())
        )


def test_context_assembly_rejects_cross_workspace_source() -> None:
    with pytest.raises(ValueError, match="cross-workspace"):
        asyncio.run(
            DeterministicAgentContextAssembler(
                sources=_sources(cross_workspace=True),
                policy=_policy(),
                receipts=_Receipts(),
                clock=lambda: NOW,
            ).assemble(request=request(), profile=profile(), history=())
        )


class _ArtifactReader:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.read_keys: list[str] = []

    async def read(self, ref: ArtifactRef) -> bytes:
        self.read_keys.append(ref.artifact_key)
        return self.bodies[ref.artifact_key]


def test_turn_layer_reads_message_but_never_raw_attachment_bytes() -> None:
    message = artifact("user-message.txt")
    attachment = artifact("private-upload.pdf")
    reader = _ArtifactReader({message.artifact_key: b"Please inspect the attached file."})
    source = TurnLayerSource(reader)

    values = asyncio.run(
        source.load(
            request=request(
                user_message_artifact_ref=message,
                attachment_refs=(attachment,),
            ),
            profile=profile(),
            history=(),
        )
    )

    assert reader.read_keys == [message.artifact_key]
    assert values[0].body == "Please inspect the attached file."
    assert values[1].body.startswith("Attachment reference only:")
    assert attachment.artifact_key in values[1].body


@dataclass(frozen=True)
class _CapturedTurn:
    onboarding_input_id: str
    artifact_key: str
    sha256: str
    byte_count: int


class _Capture:
    """The api-root binding, reduced to what L7 reads (PC-C8 §6b)."""

    def __init__(self, identity: _CapturedTurn | None) -> None:
        self.identity = identity
        self.requests: list[str] = []

    async def describe(self, request: AgentTurnRequest) -> _CapturedTurn | None:
        self.requests.append(request.user_message_artifact_ref.artifact_key)
        return self.identity


def test_the_turn_layer_names_this_turns_capture_as_a_reference_the_model_cannot_author() -> None:
    """L7 carries the capture's identity so the model can *refer* to it, never supply it.

    The trusted values are injected at the tool seam (PC-C8 §6a); this envelope exists so the
    agent can talk about the turn it is answering without the platform handing it an id to retype.
    It is reference-only and ordered last, after the message and any attachments.
    """

    message = artifact("user-message.txt")
    reader = _ArtifactReader({message.artifact_key: b"We target neurosurgery practices."})
    capture = _Capture(
        _CapturedTurn(
            onboarding_input_id="00000000-0000-0000-0000-0000000000a1",
            artifact_key=message.artifact_key,
            sha256=SHA_A,
            byte_count=33,
        )
    )
    source = TurnLayerSource(reader, captured_turn=capture)

    values = asyncio.run(
        source.load(
            request=request(user_message_artifact_ref=message),
            profile=profile(),
            history=(),
        )
    )

    assert capture.requests == [message.artifact_key]
    envelope = values[-1]
    assert envelope.stable_key == "900-captured-turn"
    assert values[0].stable_key < envelope.stable_key
    assert envelope.required is False
    assert "onboarding_input_id=00000000-0000-0000-0000-0000000000a1" in envelope.body
    assert f"artifact_key={message.artifact_key}" in envelope.body
    assert f"sha256={SHA_A}" in envelope.body
    assert "byte_count=33" in envelope.body
    assert "never author or retype them" in envelope.body


def test_a_turn_with_no_capture_emits_no_envelope_rather_than_failing() -> None:
    """Most surfaces capture no onboarding input; L7 must still assemble for them."""

    message = artifact("user-message.txt")
    reader = _ArtifactReader({message.artifact_key: b"Where should this campaign start?"})
    source = TurnLayerSource(reader, captured_turn=_Capture(None))

    values = asyncio.run(
        source.load(
            request=request(user_message_artifact_ref=message),
            profile=profile(),
            history=(),
        )
    )

    assert [item.stable_key for item in values] == ["000-user-message"]


def test_utf8_byte_counter_is_conservative_and_versioned() -> None:
    counter = Utf8ByteTokenCounter()
    assert counter.version == "utf8-bytes-v1"
    assert counter.count("é") == 2
