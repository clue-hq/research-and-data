"""Name a turn's attachments for L7 from the submission rows (spec 2026-09-19 §3.2).

L7 may say only what the durable rows prove. The filename comes from
``agent_turn_submission_attachment`` — written at submit from the upload row, never from anything
the browser retyped — and the path is ``attachments/<filename>``, the one place the fleet worker's
sync puts every file attached to this project, whatever its family. The family itself is read
from the row's media type and only chooses which tool L7 names for opening the file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from clue_agents.contracts import AgentTurnRequest
from clue_api.agent_turn_submission import submission_attachment_refs
from clue_api.chat.uploads import attachment_family
from clue_db import ConnFactory, transaction

__all__ = ["DbAttachmentDescriber", "DescribedAttachment"]


@dataclass(frozen=True, slots=True)
class DescribedAttachment:
    """One attachment as L7 names it: what it is called, where it sits, and what kind it is."""

    filename: str
    workspace_path: str | None
    family: str


class DbAttachmentDescriber:
    """Describe this turn's attachments from the submission rows, keyed by ``artifact_key``."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def describe(self, request: AgentTurnRequest) -> Mapping[str, DescribedAttachment]:
        workspace_id = request.constitution.workspace_id
        result: dict[str, DescribedAttachment] = {}
        async with self._conn_factory() as conn:
            rows = await submission_attachment_refs(
                conn, workspace_id=workspace_id, turn_id=request.turn_id
            )
            for row in rows:
                family = attachment_family(row.ref.media_type)
                if family is None:
                    # Upload validation accepts no other media type, so this is a row from
                    # outside that gate: leave it undescribed and let L7 print the pointer line
                    # rather than invent a family for it.
                    continue
                result[row.ref.artifact_key] = DescribedAttachment(
                    filename=row.filename,
                    workspace_path=f"attachments/{row.filename}",
                    family=family,
                )
        return result
