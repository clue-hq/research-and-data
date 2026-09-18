"""The sending turn's images ride the user message as image parts (spec 2026-09-18, ruling 1)."""

from __future__ import annotations

import asyncio
import base64
import dataclasses

import pytest
from langchain_core.messages import HumanMessage

from clue_agents.context import (
    IMAGE_TOKEN_ALLOWANCE,
    ContextCandidate,
    DeterministicAgentContextAssembler,
    _message,
)
from clue_agents.contracts import ArtifactRef
from tests.agents.conftest import NOW
from tests.agents.test_context import _policy, _Receipts, _sources, request
from tests.agents.test_contracts import profile

WS = "ws-img"


def _ref(key: str, media: str) -> ArtifactRef:
    return ArtifactRef(
        workspace_id=WS,
        artifact_key=f"{WS}/{key * 64}",
        sha256=key * 64,
        media_type=media,
        byte_count=3,
    )


def test_user_candidate_with_images_becomes_multipart() -> None:
    shot = _ref("a", "image/png")
    candidate = ContextCandidate(
        stable_key="999-user-message",
        ref=_ref("b", "text/plain"),
        body="what is this?",
        role="user",
        origin="current_user_instruction",
        image_refs=(shot,),
    )
    message = _message(candidate, {shot.artifact_key: b"png"})
    assert isinstance(message, HumanMessage)
    assert message.content[0] == {"type": "text", "text": "what is this?"}
    assert message.content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + base64.b64encode(b"png").decode("ascii")},
    }


def test_candidate_without_images_is_unchanged() -> None:
    candidate = ContextCandidate(
        stable_key="k", ref=_ref("c", "text/plain"), body="plain", role="user"
    )
    assert _message(candidate, {}).content == "plain"


def test_budget_text_counts_an_allowance_per_image() -> None:
    shot = _ref("a", "image/png")
    candidate = ContextCandidate(
        stable_key="k",
        ref=_ref("c", "text/plain"),
        body="x",
        role="user",
        image_refs=(shot, shot),
    )
    assert candidate.image_token_allowance == 2 * IMAGE_TOKEN_ALLOWANCE


class _Reader:
    """The turn's artifact reader; it counts reads so a duplicated one is visible."""

    def __init__(self, data: dict[str, bytes]) -> None:
        self._data = data
        self.reads: list[str] = []

    async def read(self, ref: ArtifactRef) -> bytes:
        self.reads.append(ref.artifact_key)
        return self._data[ref.artifact_key]


def _sources_with_image(shot: ArtifactRef) -> tuple[object, ...]:
    """The seven-layer harness of ``test_context``, with an image on the L7 user message."""

    sources = list(_sources())
    turn = sources[-1]
    candidate = turn.candidates[0].model_copy(update={"image_refs": (shot,)})
    sources[-1] = dataclasses.replace(turn, candidates=(candidate,))
    return tuple(sources)


def _image_ref() -> ArtifactRef:
    return ArtifactRef(
        workspace_id="ws-1",
        artifact_key="agent-artifacts/shot.png",
        sha256="d" * 64,
        media_type="image/png",
        byte_count=3,
    )


def test_assembled_turn_ends_with_the_multipart_user_message() -> None:
    shot = _image_ref()
    reader = _Reader({shot.artifact_key: b"png"})
    receipts = _Receipts()
    assembler = DeterministicAgentContextAssembler(
        sources=_sources_with_image(shot),
        policy=_policy(),
        receipts=receipts,
        clock=lambda: NOW,
        artifacts=reader,
    )

    assembled = asyncio.run(assembler.assemble(request=request(), profile=profile(), history=()))

    final = assembled.messages[-1]
    assert isinstance(final, HumanMessage)
    assert final.content[0] == {"type": "text", "text": "layer 7"}
    assert final.content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    # The bytes are read once for the turn, not once per message built.
    assert reader.reads == [shot.artifact_key]
    l7 = assembled.manifest.layers[-1]
    assert l7.token_count == IMAGE_TOKEN_ALLOWANCE + len(b"layer 7")


def test_an_image_candidate_without_a_reader_fails_composition() -> None:
    assembler = DeterministicAgentContextAssembler(
        sources=_sources_with_image(_image_ref()),
        policy=_policy(),
        receipts=_Receipts(),
        clock=lambda: NOW,
    )

    with pytest.raises(ValueError, match="image candidates need an artifact reader"):
        asyncio.run(assembler.assemble(request=request(), profile=profile(), history=()))
