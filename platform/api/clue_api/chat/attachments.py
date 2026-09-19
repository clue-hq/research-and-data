"""Validate a submission's ``attachment_refs`` against the upload rows, fail-closed.

A receipt the browser sends back is a *claim* about an upload, never authority: every field is
re-read from ``chat_upload`` inside the submitting workspace and compared, so a rewritten
``artifact_key``, a borrowed ``upload_id`` from another tenant, or a media type the store never
accepted refuses the turn instead of attaching somebody else's bytes. Spec:
docs/superpowers/specs/2026-09-18-chat-attachments-design.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import yaml
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_agents.ports import AgentArtifactReader
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.project_documents import (
    ProjectDocumentWrite,
    WrittenDocument,
    current_document_version,
    list_project_documents,
    read_project_document,
    workspace_path_of,
    write_project_document,
)
from clue_api.chat.schemas import AttachmentRefRequest
from clue_api.chat.uploads import attachment_family, get_chat_uploads
from clue_config import Settings
from clue_storage import StorageBackend

__all__ = [
    "AttachmentReferenceError",
    "ValidatedAttachment",
    "materialize_text_attachments",
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


#: Every text attachment lands in one folder of the project's own tree, so a file a human dropped
#: into the conversation is legible as such beside the documents the agent wrote itself.
ATTACHMENT_FOLDER = "attachments"


def _attachment_document(upload_text: str, *, filename: str, upload_id: UUID) -> tuple[str, str]:
    """The whole file to write and its body, with anything the upload itself said preserved.

    A dropped markdown file may carry front matter of its own, and every word of it survives: only
    the four facts about *being an attachment* are stamped over it, and the project-document store
    then stamps the facts it owns (version, status, scope, authorship) over that.
    """

    try:
        front, body = parse_front_matter(upload_text, preserve_body=True)
    except ValueError:
        # No front matter, or one that is not a mapping: the whole upload is the body.
        front, body = {}, upload_text
    stamped = dict(front)
    stamped.update(
        {
            "kind": "attachment",
            "title": filename,
            "source": "user_upload",
            "upload_id": str(upload_id),
        }
    )
    header = yaml.safe_dump(stamped, sort_keys=True, allow_unicode=True).strip()
    body = body.lstrip()
    return f"---\n{header}\n---\n{body}", body


async def materialize_text_attachments(
    conn: AsyncConnection,
    storage: StorageBackend,
    artifacts: AgentArtifactReader,
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str,
    turn_id: UUID,
    user_id: str,
    attachments: Sequence[ValidatedAttachment],
) -> tuple[WrittenDocument, ...]:
    """Write each text attachment as the next version of ``attachments/<filename>``.

    A file a person attaches is a document this project now has: it is listed in the Gallery, it is
    readable at ``project/attachments/<filename>`` on every later turn, and re-attaching a newer
    draft of the same file appends a version to the same chain rather than making a second file.
    Images are deliberately skipped — they are shown in the transcript, not written into the tree.

    Re-attaching *identical* bytes under the same name is a no-op: the version at rest is returned
    as a replay instead of minting a version whose words nobody changed.

    The path is built from the upload row's filename, which
    :func:`clue_api.chat.uploads.sanitize_filename` already reduced to a single path segment at
    upload time — the only writer of ``chat_upload`` — so an attachment cannot name a document
    outside its own folder.
    """

    written: list[WrittenDocument] = []
    for item in attachments:
        if item.family != "text":
            continue
        path = f"{ATTACHMENT_FOLDER}/{item.filename}"
        upload_text = (await artifacts.read(item.ref)).decode("utf-8")
        document_text, body = _attachment_document(
            upload_text, filename=item.filename, upload_id=item.upload_id
        )
        # The version the store compares ``expected_version`` against: every row at this path,
        # servable or retired, exactly as :func:`write_project_document` reads it.
        current = await current_document_version(
            conn, workspace_id=workspace_id, project_id=project_id, path=path
        )
        if current is not None:
            served = next(
                (
                    row
                    for row in await list_project_documents(
                        conn, workspace_id=workspace_id, project_id=project_id
                    )
                    if row.path == path
                ),
                None,
            )
            if served is not None:
                existing = await read_project_document(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    document_id=served.document_id,
                )
                if existing is not None and existing[2].strip() == body.strip():
                    written.append(
                        WrittenDocument(
                            document_id=served.document_id,
                            path=path,
                            version=served.version,
                            workspace_path=workspace_path_of(path),
                            replayed=True,
                        )
                    )
                    continue
        written.append(
            await write_project_document(
                conn,
                storage,
                ProjectDocumentWrite(
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    project_id=project_id,
                    turn_id=turn_id,
                    user_id=user_id,
                    path=path,
                    document_text=document_text,
                    expected_version=current,
                ),
            )
        )
    return tuple(written)
