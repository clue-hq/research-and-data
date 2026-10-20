"""Validate a submission's ``attachment_refs`` against the upload rows, fail-closed.

A receipt the browser sends back is a *claim* about an upload, never authority: every field is
re-read from ``chat_upload`` inside the submitting workspace and compared, so a rewritten
``artifact_key``, a borrowed ``upload_id`` from another tenant, or a media type the store never
accepted refuses the turn instead of attaching somebody else's bytes.

Validation is all this module does: every attached file — text, image or document alike — reaches
the agent the one way, as a file the fleet worker syncs into the workspace's read-only
``attachments/`` folder. Nothing here writes a project document. Spec:
docs/superpowers/specs/archive/2026-09-19-agent-code-execution-and-document-attachments-design.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_api.chat.schemas import AttachmentRefRequest
from clue_api.chat.uploads import attachment_family, get_chat_uploads
from clue_config import Settings

__all__ = [
    "AttachmentReferenceError",
    "ValidatedAttachment",
    "validated_attachment_refs",
]


class AttachmentReferenceError(Exception):
    """A refusal with a stable code the route maps to a status; never a partial acceptance."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ValidatedAttachment:
    """One receipt proved against its upload row, carrying the family the composer renders."""

    upload_id: UUID
    ref: ArtifactRef
    filename: str
    family: Literal["text", "image", "document"]


async def validated_attachment_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[AttachmentRefRequest],
    settings: Settings,
) -> tuple[ValidatedAttachment, ...]:
    """Prove every receipt against ``chat_upload``, in the order the human attached them."""

    if not refs:
        return ()
    if len(refs) > settings.chat_attachment_max_files:
        raise AttachmentReferenceError(
            "ATTACHMENT_LIMIT_EXCEEDED",
            f"a message may carry at most {settings.chat_attachment_max_files} attachments",
        )
    ids = [ref.upload_id for ref in refs]
    if len(set(ids)) != len(ids) or len({ref.artifact_key for ref in refs}) != len(refs):
        raise AttachmentReferenceError(
            "ATTACHMENT_DUPLICATE", "the same file may be attached only once per message"
        )
    total = sum(ref.byte_count for ref in refs)
    if total > settings.chat_attachment_max_total_bytes:
        raise AttachmentReferenceError(
            "ATTACHMENT_LIMIT_EXCEEDED",
            f"attachments may total at most {settings.chat_attachment_max_total_bytes} bytes",
        )
    rows = await get_chat_uploads(conn, workspace_id=workspace_id, upload_ids=ids)
    validated: list[ValidatedAttachment] = []
    for ref in refs:
        row = rows.get(ref.upload_id)
        if row is None:
            raise AttachmentReferenceError(
                "ATTACHMENT_NOT_FOUND", "an attachment is not available in this workspace"
            )
        if (
            row.artifact_key != ref.artifact_key
            or row.sha256 != ref.sha256
            or row.media_type != ref.media_type
            or row.byte_count != ref.byte_count
            or row.filename != ref.filename
        ):
            raise AttachmentReferenceError(
                "ATTACHMENT_MISMATCH", "an attachment receipt does not match its upload"
            )
        family = attachment_family(row.media_type)
        if family is None:
            raise AttachmentReferenceError(
                "ATTACHMENT_MISMATCH", "an attachment has an unsupported media type"
            )
        validated.append(
            ValidatedAttachment(
                upload_id=row.upload_id,
                ref=ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=row.artifact_key,
                    sha256=row.sha256,
                    media_type=row.media_type,
                    byte_count=row.byte_count,
                ),
                filename=row.filename,
                family=family,
            )
        )
    return tuple(validated)
