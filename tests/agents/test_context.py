from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import pytest
import structlog.testing

from clue_agents.context import (
    CompiledContextCard,
    ContextAssemblyPolicy,
    ContextAssemblyReceipt,
    ContextCandidate,
    DeterministicAgentContextAssembler,
    FocusLayerSource,
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
                        ref=(
                            artifact("user-message.txt")
                            if layer is ContextLayer.L7_TURN
                            else domain_ref(
                                f"item-{index}",
                                workspace_id=("ws-2" if cross_workspace and index == 4 else "ws-1"),
                            )
                        ),
                        body=f"layer {index}",
                        materialized_path=(
                            f"context/layer-{index}.md"
                            if layer not in {ContextLayer.L1_IDENTITY, ContextLayer.L6_CONVERSATION}
                            else None
                        ),
                        role="user" if layer is ContextLayer.L7_TURN else "system",
                        origin=(
                            "current_user_instruction"
                            if layer is ContextLayer.L7_TURN
                            else "trusted_context"
                        ),
                        required=layer is ContextLayer.L7_TURN,
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


def test_context_budget_records_an_over_budget_layer_and_keeps_every_item() -> None:
    """A layer well over its budget assembles whole, and says so once (ruling 2026-09-14).

    Five hundred bytes twice against a four-hundred-byte L3: both candidates are included, in
    canonical order, the manifest reports the layer's true 1,000-byte cost, and the only
    consequence of the overrun is one structured warning naming the layer and both numbers.
    """

    sources = list(_sources())
    sources[2] = _Source(
        layer=ContextLayer.L3_PROJECT,
        candidates=(
            ContextCandidate(
                stable_key="a-first",
                ref=domain_ref("first"),
                body="1" * 500,
            ),
            ContextCandidate(
                stable_key="b-second",
                ref=domain_ref("second"),
                body="2" * 500,
            ),
        ),
    )
    receipts = _Receipts()
    with structlog.testing.capture_logs() as events:
        assembled = asyncio.run(
            DeterministicAgentContextAssembler(
                sources=sources,
                policy=_policy(l3_budget=400),
                receipts=receipts,
                clock=lambda: NOW,
            ).assemble(request=request(), profile=profile(), history=())
        )

    layer = assembled.manifest.layers[2]
    assert layer.source_refs == (domain_ref("first"), domain_ref("second"))
    assert layer.excluded_refs == ()
    assert layer.exclusion_reason_codes == ()
    assert layer.token_count == 1_000

    l3_refs = [ref for ref in receipts.values[0].refs if ref.layer is ContextLayer.L3_PROJECT]
    assert [ref.disposition for ref in l3_refs] == ["included", "included"]
    assert [ref.token_count for ref in l3_refs] == [500, 500]
    assert receipts.values[0].budgets == _policy(l3_budget=400).budgets

    over = [item for item in events if item["event"] == "agent_turn.context_layer_over_budget"]
    assert len(over) == 1
    assert over[0]["layer"] == "l3_project"
    assert over[0]["token_count"] == 1_000
    assert over[0]["token_budget"] == 400
    assert over[0]["policy_version"] == "opening-context-v1"
    assert over[0]["log_level"] == "warning"


def test_required_authority_over_budget_assembles_instead_of_failing_the_turn() -> None:
    """The reverse of the old gate: a required candidate that does not fit is carried anyway.

    This is the v54 failure in miniature — a resolved system prompt a few hundred bytes past L1
    used to raise ``required l1_identity context exceeds its hard layer budget`` and take down
    every turn on that profile. The founder's ruling (2026-09-14) is that no budget may do that:
    the identity arrives intact, its true cost is on the receipt, and the overrun is a log line.
    """

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
    receipts = _Receipts()
    with structlog.testing.capture_logs() as events:
        assembled = asyncio.run(
            DeterministicAgentContextAssembler(
                sources=sources,
                policy=policy,
                receipts=receipts,
                clock=lambda: NOW,
            ).assemble(request=request(), profile=profile(), history=())
        )

    layer = assembled.manifest.layers[0]
    assert layer.source_refs == (domain_ref("identity"),)
    assert layer.token_count == len(b"required identity")
    assert "required identity" in [str(message.content) for message in assembled.messages]

    over = [item for item in events if item["event"] == "agent_turn.context_layer_over_budget"]
    assert [(item["layer"], item["token_budget"]) for item in over] == [("l1_identity", 1)]


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


def test_context_assembly_rejects_platform_metadata_after_the_current_instruction() -> None:
    sources = list(_sources())
    sources[-1] = _Source(
        layer=ContextLayer.L7_TURN,
        candidates=(
            ContextCandidate(
                stable_key="100-current",
                ref=request().user_message_artifact_ref,
                body="Answer C.",
                role="user",
                origin="current_user_instruction",
                required=True,
            ),
            ContextCandidate(
                stable_key="900-platform-metadata",
                ref=domain_ref("capture"),
                body="Synthetic capture metadata.",
                role="user",
            ),
        ),
    )

    with pytest.raises(ValueError, match="final opening-context message"):
        asyncio.run(
            DeterministicAgentContextAssembler(
                sources=sources,
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


class _FocusCards:
    async def read(
        self,
        *,
        workspace_id: str,
        object_type: str,
        object_id: str,
    ) -> CompiledContextCard:
        return CompiledContextCard(
            ref={
                "workspace_id": workspace_id,
                "object_type": object_type,
                "object_id": object_id,
                "version": 7,
            },
            body=f"context for {object_id}",
        )


def test_focus_layer_preserves_submission_order_and_accepts_current_revision_refs() -> None:
    source = FocusLayerSource(_FocusCards())
    selected = (
        domain_ref("second").model_copy(update={"version": None}),
        domain_ref("first").model_copy(update={"version": None}),
    )
    values = asyncio.run(
        source.load(
            request=request(
                constitution=constitution(focus_refs=()),
                focus_refs=selected,
            ),
            profile=profile(),
            history=(),
        )
    )

    assert [item.ref.object_id for item in values] == ["second", "first"]
    assert [item.stable_key[:6] for item in values] == ["000000", "000001"]


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
    assert values[0].body.startswith("Attachment reference only:")
    assert values[0].role == "system"
    assert attachment.artifact_key in values[0].body
    assert values[-1].body == "Please inspect the attached file."
    assert values[-1].role == "user"
    assert values[-1].origin == "current_user_instruction"


def test_turn_layer_marks_exact_current_message_context_refs_without_widening() -> None:
    message = artifact("user-message.txt")
    selected = (
        domain_ref("account-2"),
        domain_ref("account-1"),
    )
    reader = _ArtifactReader({message.artifact_key: b"Research the selected accounts."})
    source = TurnLayerSource(reader)

    values = asyncio.run(
        source.load(
            request=request(
                user_message_artifact_ref=message,
                focus_refs=selected,
            ),
            profile=profile(),
            history=(),
        )
    )

    current_refs = values[:-1]
    assert [item.ref for item in current_refs] == list(selected)
    assert [item.stable_key for item in current_refs] == [
        "150-current-context-ref:000000",
        "150-current-context-ref:000001",
    ]
    assert all(item.role == "system" for item in current_refs)
    assert "exact ordered subject on the user's current message" in current_refs[0].body
    assert "ordinal=0 object_type=account object_id=account-2 version=1" in current_refs[0].body
    assert "ordinal=1 object_type=account object_id=account-1 version=1" in current_refs[1].body
    assert values[-1].body == "Research the selected accounts."
    assert values[-1].origin == "current_user_instruction"


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
    It is reference-only trusted context and is ordered before the one current user instruction.
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
    envelope = values[0]
    assert envelope.stable_key == "100-captured-turn"
    assert envelope.role == "system"
    assert envelope.stable_key < values[-1].stable_key
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

    assert [item.stable_key for item in values] == ["999-user-message"]


def test_utf8_byte_counter_is_conservative_and_versioned() -> None:
    counter = Utf8ByteTokenCounter()
    assert counter.version == "utf8-bytes-v1"
    assert counter.count("é") == 2


@pytest.mark.parametrize("over_budget", [True, False])
def test_interrupted_history_and_its_notice_are_counted_as_one_item(over_budget: bool) -> None:
    """The notice and the unfinished body are one candidate, so they are counted — and emitted —
    together, whether or not the pair fits L6. Budgets no longer separate them, or anything."""

    from clue_agents.context import HistoryLayerSource
    from clue_agents.ports import INTERRUPTED_ASSISTANT_NOTICE

    body = "Exact unfinished `answer"
    ref = artifact("partial.txt")
    history = (
        HistoryMessageRef(
            message_id=TURN_ID,
            turn_id=TURN_ID,
            sequence=1,
            role="assistant",
            body_ref=ref,
            interrupted=True,
        ),
    )
    source = HistoryLayerSource(_ArtifactReader({ref.artifact_key: body.encode()}))
    sources = tuple(source if s.layer is ContextLayer.L6_CONVERSATION else s for s in _sources())
    full_cost = len((INTERRUPTED_ASSISTANT_NOTICE + "\n\n" + body).encode())
    policy = _policy().model_copy(
        update={
            "budgets": tuple(
                LayerBudget(
                    layer=b.layer,
                    max_tokens=(len(body) if over_budget else full_cost)
                    if b.layer is ContextLayer.L6_CONVERSATION
                    else b.max_tokens,
                )
                for b in _policy().budgets
            )
        }
    )
    assembled = asyncio.run(
        DeterministicAgentContextAssembler(
            sources=sources,
            policy=policy,
            receipts=_Receipts(),
            clock=lambda: NOW,
        ).assemble(request=request(), profile=profile(), history=history)
    )
    contents = [m.content for m in assembled.messages]
    assert body in contents
    assert INTERRUPTED_ASSISTANT_NOTICE in contents
    index = contents.index(body)
    assert contents[index - 1] == INTERRUPTED_ASSISTANT_NOTICE
    assert assembled.messages[index - 1].type == "system"
    assert assembled.messages[index].type == "ai"
    assert assembled.manifest.layers[5].token_count == full_cost
