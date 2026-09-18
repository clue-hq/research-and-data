"""Name a turn's attachments for L7 from the submission rows (spec 2026-09-18 §3.4).

L7 may say only what the durable rows prove. The filename comes from
``agent_turn_submission_attachment`` — written at submit from the upload row, never from anything
the browser retyped — and a workspace path is named only when a servable document really sits at
``attachments/<filename>`` in this project, so the agent is never told to open a file that is not
there. An image gets no path at all: it is shown in the transcript, not written into the tree.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import text

from clue_agents.contracts import AgentTurnRequest
from clue_api.agent_turn_submission import submission_attachment_refs
from clue_api.chat.uploads import attachment_family
from clue_db import ConnFactory, transaction

__all__ = ["DbAttachmentDescriber", "DescribedAttachment"]


@dataclass(frozen=True, slots=True)
class DescribedAttachment:
    """One attachment as L7 names it: what it is called, and where it is readable when it is."""

    filename: str
    workspace_path: str | None


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
                path: str | None = None
                if attachment_family(row.ref.media_type) == "text":
                    # The servable statuses and the ``artifact_key IS NOT NULL`` clause are the
                    # project-document store's own definition of "this version owns its path";
                    # anything else is a document whose words nobody can read yet.
                    served = (
                        await conn.execute(
                            text(
                                "SELECT 1 FROM brand_knowledge_document WHERE workspace_id = :ws "
                                "AND project_id = :project AND path = :path "
                                "AND status IN ('ready', 'proposed', 'confirmed') "
                                "AND artifact_key IS NOT NULL LIMIT 1"
                            ),
                            {
                                "ws": workspace_id,
                                "project": request.constitution.project_id,
                                "path": f"attachments/{row.filename}",
                            },
                        )
                    ).first()
                    path = f"project/attachments/{row.filename}" if served else None
                result[row.ref.artifact_key] = DescribedAttachment(row.filename, path)
        return result
