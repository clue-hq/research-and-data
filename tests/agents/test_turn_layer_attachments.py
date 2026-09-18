"""L7 names a turn's attachments in plain words (spec 2026-09-18 §3.4)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

from clue_agents.context import TurnLayerSource
from clue_agents.contracts import AgentTurnRequest, ArtifactRef
from tests.agents.conftest import constitution

#: The conftest constitution's own artifact refs live in ``ws-1``; a turn may not cross
#: workspaces, so the whole fixture is that one workspace.
WS = "ws-1"


class _Reader:
    def __init__(self, bodies: Mapping[str, bytes]) -> None:
        self._bodies = bodies

    async def read(self, ref: ArtifactRef) -> bytes:
        return self._bodies[ref.artifact_key]


class _Desc:
    def __init__(self, filename: str, workspace_path: str | None) -> None:
        self.filename = filename
        self.workspace_path = workspace_path


class _Describer:
    def __init__(self, table: Mapping[str, _Desc]) -> None:
        self._table = table

    async def describe(self, request: AgentTurnRequest) -> Mapping[str, _Desc]:
        del request
        return self._table


def _ref(key: str, media: str, size: int) -> ArtifactRef:
    return ArtifactRef(
        workspace_id=WS,
        artifact_key=f"{WS}/{key * 64}",
        sha256=key * 64,
        media_type=media,
        byte_count=size,
    )


def test_l7_names_text_and_image_attachments_in_plain_words() -> None:
    message = _ref("a", "text/plain", 5)
    doc = _ref("b", "text/markdown", 120)
    shot = _ref("c", "image/png", 4096)
    request = AgentTurnRequest(
        turn_id=uuid4(),
        thread_id="thr_l7",
        constitution=constitution(workspace_id=WS),
        user_message_artifact_ref=message,
        attachment_refs=(doc, shot),
        requested_at=datetime.now(UTC),
    )
    source = TurnLayerSource(
        _Reader(
            {
                message.artifact_key: b"hello",
                doc.artifact_key: b"# d",
                shot.artifact_key: b"png",
            }
        ),
        attachments=_Describer(
            {
                doc.artifact_key: _Desc("brief.md", "project/attachments/brief.md"),
                shot.artifact_key: _Desc("shot.png", None),
            }
        ),
    )
    candidates = asyncio.run(source.load(request=request, profile=None, history=()))
    bodies = [c.body for c in candidates]
    assert any(
        'Attachment "brief.md" (text/markdown, 120 bytes) is readable at '
        "project/attachments/brief.md" in b
        for b in bodies
    )
    assert any(
        'Attachment "shot.png" (image/png, 4,096 bytes) is attached to this message as an image'
        in b
        for b in bodies
    )
    assert candidates[-1].body == "hello" and candidates[-1].role == "user"
