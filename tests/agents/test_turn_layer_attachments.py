"""L7 names a turn's attachments in plain words (spec 2026-09-19 §3.2)."""

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

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _Reader:
    def __init__(self, bodies: Mapping[str, bytes]) -> None:
        self._bodies = bodies

    async def read(self, ref: ArtifactRef) -> bytes:
        return self._bodies[ref.artifact_key]


class _Desc:
    def __init__(self, filename: str, workspace_path: str | None, family: str) -> None:
        self.filename = filename
        self.workspace_path = workspace_path
        self.family = family


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


def test_l7_names_every_attachment_family_with_its_one_path() -> None:
    message = _ref("a", "text/plain", 5)
    brief = _ref("b", "text/markdown", 120)
    sheet = _ref("c", XLSX, 412010)
    shot = _ref("d", "image/png", 4096)
    request = AgentTurnRequest(
        turn_id=uuid4(),
        thread_id="thr_l7",
        constitution=constitution(workspace_id=WS),
        user_message_artifact_ref=message,
        attachment_refs=(brief, sheet, shot),
        requested_at=datetime.now(UTC),
    )
    source = TurnLayerSource(
        _Reader(
            {
                message.artifact_key: b"hello",
                brief.artifact_key: b"# d",
                sheet.artifact_key: b"xlsx",
                shot.artifact_key: b"png",
            }
        ),
        attachments=_Describer(
            {
                brief.artifact_key: _Desc("brief.md", "attachments/brief.md", "text"),
                sheet.artifact_key: _Desc("q3.xlsx", "attachments/q3.xlsx", "document"),
                shot.artifact_key: _Desc("shot.png", "attachments/shot.png", "image"),
            }
        ),
    )
    candidates = asyncio.run(source.load(request=request, profile=None, history=()))
    bodies = [c.body for c in candidates]
    assert (
        'Attachment "brief.md" (text/markdown, 120 bytes) was attached to this message. '
        "It is at attachments/brief.md; open it with read_file."
    ) in bodies
    assert (
        f'Attachment "q3.xlsx" ({XLSX}, 412,010 bytes) was attached to this message. '
        "It is at attachments/q3.xlsx; open it with run_python."
    ) in bodies
    assert (
        'Attachment "shot.png" (image/png, 4,096 bytes) was attached to this message. '
        "It is at attachments/shot.png; it is also shown to you as an image in this message."
    ) in bodies
    assert candidates[-1].body == "hello" and candidates[-1].role == "user"


def test_an_undescribed_attachment_keeps_the_pointer_line() -> None:
    """Naming nothing is better than naming it wrong: no describer, no words."""

    message = _ref("a", "text/plain", 5)
    brief = _ref("b", "text/markdown", 120)
    request = AgentTurnRequest(
        turn_id=uuid4(),
        thread_id="thr_l7_pointer",
        constitution=constitution(workspace_id=WS),
        user_message_artifact_ref=message,
        attachment_refs=(brief,),
        requested_at=datetime.now(UTC),
    )
    source = TurnLayerSource(_Reader({message.artifact_key: b"hello", brief.artifact_key: b"# d"}))
    candidates = asyncio.run(source.load(request=request, profile=None, history=()))
    assert (
        f"Attachment reference only: artifact_key={brief.artifact_key} "
        f"sha256={brief.sha256} media_type=text/markdown byte_count=120"
    ) in [c.body for c in candidates]


def test_an_svg_is_opened_as_a_file_and_a_tiff_is_shown() -> None:
    """Spec 2026-10-30 §3.6: SVG is never sent as a picture; TIFF is shown (as a PNG copy)."""

    message = _ref("a", "text/plain", 5)
    drawing = _ref("b", "image/svg+xml", 300)
    scan = _ref("c", "image/tiff", 900)
    request = AgentTurnRequest(
        turn_id=uuid4(),
        thread_id="thr_l7_svg",
        constitution=constitution(workspace_id=WS),
        user_message_artifact_ref=message,
        attachment_refs=(drawing, scan),
        requested_at=datetime.now(UTC),
    )
    source = TurnLayerSource(
        _Reader({message.artifact_key: b"hello"}),
        attachments=_Describer(
            {
                drawing.artifact_key: _Desc("logo.svg", "attachments/logo.svg", "image"),
                scan.artifact_key: _Desc("scan.tif", "attachments/scan.tif", "image"),
            }
        ),
    )
    candidates = asyncio.run(source.load(request=request, profile=None, history=()))
    assert (
        'Attachment "logo.svg" (image/svg+xml, 300 bytes) was attached to this message. '
        "It is at attachments/logo.svg; open it with read_file."
    ) in [c.body for c in candidates]
    assert candidates[-1].image_refs == (scan,)
