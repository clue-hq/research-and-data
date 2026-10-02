from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from clue_agents.context import ContextCandidate, HistoryLayerSource
from clue_agents.contracts import AgentTurnRequest, ArtifactRef
from clue_agents.ports import HistoryMessageRef
from tests.agents.conftest import constitution

WS = "ws-1"


def _ref(key: str, media: str) -> ArtifactRef:
    return ArtifactRef(
        workspace_id=WS,
        artifact_key=f"{WS}/{key * 64}",
        sha256=key * 64,
        media_type=media,
        byte_count=1,
    )


class _Reader:
    async def read(self, ref: ArtifactRef) -> bytes:
        del ref
        return b"body"


def _user(seq: int, images: tuple[ArtifactRef, ...]) -> HistoryMessageRef:
    return HistoryMessageRef(
        message_id=uuid4(),
        turn_id=uuid4(),
        sequence=seq,
        role="user",
        body_ref=_ref(str(seq), "text/plain"),
        attachment_refs=images,
    )


def _load(
    history: Sequence[HistoryMessageRef],
    images_max: int,
) -> Sequence[ContextCandidate]:
    request = AgentTurnRequest(
        turn_id=uuid4(),
        thread_id="t",
        constitution=constitution(workspace_id=WS),
        user_message_artifact_ref=_ref("e", "text/plain"),
        requested_at=datetime.now(UTC),
    )
    return asyncio.run(
        HistoryLayerSource(_Reader(), images_max=images_max).load(
            request=request,
            profile=None,
            history=history,
        )
    )


def test_prior_user_messages_keep_their_images() -> None:
    a, b = _ref("a", "image/png"), _ref("b", "image/jpeg")
    out = _load([_user(1, (a,)), _user(2, (b,))], images_max=0)
    assert out[0].image_refs == (a,)
    assert out[1].image_refs == (b,)


def test_cap_keeps_the_most_recent_images() -> None:
    a, b, c = _ref("a", "image/png"), _ref("b", "image/png"), _ref("c", "image/png")
    out = _load([_user(1, (a, b)), _user(2, (c,))], images_max=2)
    assert out[0].image_refs == (b,)
    assert out[1].image_refs == (c,)
