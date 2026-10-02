"""Chat uploads: what a person may attach, and the row that remembers its filename.

The bytes live in the content-addressed artifact store like every turn artifact; this module owns
the two things that store cannot say — the filename the person gave the file and which family it
belongs to — and the validation both the upload route and the submission route apply. Three
families are accepted: text (.md, .txt), image (PNG, JPEG, WebP, GIF) and document (PDF, DOCX,
PPTX, XLSX, CSV, JSON). A document is never converted here — it is checked by size and magic bytes
and stored as-is, for the agent's workspace to read. Specs:
docs/superpowers/specs/2026-09-18-chat-attachments-design.md and
docs/superpowers/specs/2026-09-19-agent-code-execution-and-document-attachments-design.md.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_config import Settings

__all__ = [
    "ALLOWED_DOCUMENT_MEDIA_TYPES",
    "ALLOWED_IMAGE_MEDIA_TYPES",
    "ALLOWED_TEXT_MEDIA_TYPES",
    "DOCX",
    "PPTX",
    "XLSX",
    "ChatUploadRow",
    "UploadRefused",
    "attachment_family",
    "get_chat_uploads",
    "record_chat_upload",
    "resolve_media_type",
    "sanitize_filename",
    "validate_upload_bytes",
]

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ALLOWED_TEXT_MEDIA_TYPES = frozenset({"text/markdown", "text/plain"})
ALLOWED_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
ALLOWED_DOCUMENT_MEDIA_TYPES = frozenset(
    {"application/pdf", DOCX, PPTX, XLSX, "text/csv", "application/json"}
)
_OOXML_TYPES = frozenset({DOCX, PPTX, XLSX})
_EXTENSION_MEDIA_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".docx": DOCX,
    ".pptx": PPTX,
    ".xlsx": XLSX,
    ".csv": "text/csv",
    ".json": "application/json",
}
_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}
_WHITESPACE = re.compile(r"\s+")


class UploadRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def attachment_family(media_type: str) -> Literal["text", "image", "document"] | None:
    lowered = media_type.lower()
    if lowered in ALLOWED_TEXT_MEDIA_TYPES:
        return "text"
    if lowered in ALLOWED_IMAGE_MEDIA_TYPES:
        return "image"
    if lowered in ALLOWED_DOCUMENT_MEDIA_TYPES:
        return "document"
    return None


def sanitize_filename(name: str) -> str:
    segment = name.replace("\\", "/").rsplit("/", 1)[-1]
    segment = _WHITESPACE.sub(" ", segment).strip().lstrip(".")
    if not segment or len(segment) > 255:
        raise UploadRefused("UPLOAD_FILENAME_INVALID", "the file needs a usable name")
    return segment


def resolve_media_type(*, declared: str | None, filename: str) -> str:
    candidate = (declared or "").split(";", 1)[0].strip().lower()
    if attachment_family(candidate) is not None:
        return candidate
    dot = filename.rfind(".")
    by_extension = _EXTENSION_MEDIA_TYPES.get(filename[dot:].lower()) if dot >= 0 else None
    if by_extension is None:
        raise UploadRefused(
            "UPLOAD_UNSUPPORTED_TYPE",
            "attach a .md, .txt, .pdf, .docx, .pptx, .xlsx, .csv or .json file, "
            "or a PNG, JPEG, WebP or GIF image",
        )
    return by_extension


def validate_upload_bytes(*, data: bytes, media_type: str, settings: Settings) -> None:
    family = attachment_family(media_type)
    if family is None:
        raise UploadRefused(
            "UPLOAD_UNSUPPORTED_TYPE", f"{media_type} is not an accepted attachment"
        )
    limits = {
        "text": settings.chat_attachment_text_max_bytes,
        "image": settings.chat_attachment_image_max_bytes,
        "document": settings.chat_attachment_document_max_bytes,
    }
    limit = limits[family]
    if len(data) > limit:
        raise UploadRefused(
            "UPLOAD_TOO_LARGE", f"a {family} attachment may be at most {limit} bytes"
        )
    if family == "document":
        if media_type == "application/pdf" and not data.startswith(b"%PDF-"):
            raise UploadRefused("UPLOAD_NOT_A_DOCUMENT", "the file is not a PDF")
        if media_type in _OOXML_TYPES and not data.startswith(b"PK\x03\x04"):
            raise UploadRefused("UPLOAD_NOT_A_DOCUMENT", "the file is not an Office document")
        if media_type in ("text/csv", "application/json"):
            try:
                text_body = data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise UploadRefused("UPLOAD_NOT_A_DOCUMENT", "the file is not UTF-8") from exc
            if media_type == "application/json":
                try:
                    json.loads(text_body)
                except json.JSONDecodeError as exc:
                    raise UploadRefused(
                        "UPLOAD_NOT_A_DOCUMENT", "the file is not valid JSON"
                    ) from exc
        return
    if family == "text":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadRefused("UPLOAD_NOT_UTF8", "text attachments must be UTF-8") from exc
        return
    if media_type == "image/webp":
        if not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
            raise UploadRefused("UPLOAD_NOT_AN_IMAGE", "the file is not a WebP image")
        return
    if not data.startswith(_MAGIC[media_type]):
        raise UploadRefused("UPLOAD_NOT_AN_IMAGE", f"the file is not a {media_type} image")


@dataclass(frozen=True, slots=True)
class ChatUploadRow:
    upload_id: UUID
    workspace_id: str
    uploaded_by_user_id: str
    filename: str
    media_type: str
    artifact_key: str
    sha256: str
    byte_count: int
    created_at: datetime


_COLUMNS = (
    "upload_id, workspace_id, uploaded_by_user_id, filename, media_type, artifact_key, sha256, "
    "byte_count, created_at"
)


async def record_chat_upload(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    user_id: str,
    filename: str,
    media_type: str,
    ref: ArtifactRef,
) -> ChatUploadRow:
    upload_id = uuid4()
    row = (
        (
            await conn.execute(
                text(
                    "INSERT INTO chat_upload (upload_id, workspace_id, uploaded_by_user_id, "
                    "filename, media_type, artifact_key, sha256, byte_count) "
                    "VALUES (:id, :ws, :user, :name, :media, :key, :sha, :bytes) "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": upload_id,
                    "ws": workspace_id,
                    "user": user_id,
                    "name": filename,
                    "media": media_type,
                    "key": ref.artifact_key,
                    "sha": ref.sha256,
                    "bytes": ref.byte_count,
                },
            )
        )
        .mappings()
        .one()
    )
    return ChatUploadRow(**dict(row))


async def get_chat_uploads(
    conn: AsyncConnection, *, workspace_id: str, upload_ids: Sequence[UUID]
) -> dict[UUID, ChatUploadRow]:
    if not upload_ids:
        return {}
    rows = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM chat_upload WHERE workspace_id = :ws "
                "AND upload_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ws": workspace_id, "ids": [str(value) for value in upload_ids]},
        )
    ).mappings()
    return {row["upload_id"]: ChatUploadRow(**dict(row)) for row in rows}
