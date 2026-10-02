"""Attachment-ref validation: the fail-closed check between a receipt and its upload row."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from clue_api.chat import attachments as module
from clue_api.chat.attachments import (
    AttachmentReferenceError,
    ValidatedAttachment,
    validated_attachment_refs,
)
from clue_api.chat.router import _validated_submission_attachments
from clue_api.chat.schemas import AttachmentRefRequest
from clue_api.chat.uploads import ChatUploadRow
from clue_config import Settings

WS = "ws-attach"


def _settings(**overrides: int) -> Settings:
    return Settings(_env_file=None, **overrides)


def _row(
    upload_id: UUID, *, media: str = "image/png", size: int = 10, name: str = "a.png"
) -> ChatUploadRow:
    # One sha per upload: distinct uploads are distinct files, so the byte-total limit is what
    # the tight-settings case below meets — not the same-file duplicate refusal.
    sha = upload_id.hex + "d" * (64 - len(upload_id.hex))
    return ChatUploadRow(
        upload_id=upload_id,
        workspace_id=WS,
        uploaded_by_user_id="usr",
        filename=name,
        media_type=media,
        artifact_key=f"{WS}/{sha}",
        sha256=sha,
        byte_count=size,
        created_at=datetime.now(UTC),
    )


def _request(row: ChatUploadRow, **overrides: object) -> AttachmentRefRequest:
    payload: dict[str, object] = {
        "upload_id": row.upload_id,
        "artifact_key": row.artifact_key,
        "sha256": row.sha256,
        "media_type": row.media_type,
        "byte_count": row.byte_count,
        "filename": row.filename,
    }
    payload.update(overrides)
    return AttachmentRefRequest(**payload)  # type: ignore[arg-type]


def _run(
    monkeypatch: pytest.MonkeyPatch,
    refs: Sequence[AttachmentRefRequest],
    rows: Sequence[ChatUploadRow],
    settings: Settings | None = None,
) -> tuple[ValidatedAttachment, ...]:
    async def fake_get(
        conn: object, *, workspace_id: str, upload_ids: Sequence[UUID]
    ) -> dict[UUID, ChatUploadRow]:
        return {r.upload_id: r for r in rows if r.workspace_id == workspace_id}

    monkeypatch.setattr(module, "get_chat_uploads", fake_get)
    return asyncio.run(
        validated_attachment_refs(
            object(),  # type: ignore[arg-type]
            workspace_id=WS,
            refs=refs,
            settings=settings if settings is not None else _settings(),
        )
    )


def test_matching_ref_validates_and_classifies(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row(uuid4())
    (validated,) = _run(monkeypatch, [_request(row)], [row])
    assert validated.family == "image" and validated.filename == "a.png"
    assert validated.ref.artifact_key == row.artifact_key


def test_a_document_upload_validates_as_the_document_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One mechanism for every family: a PDF is carried as an attachment like any other file."""

    row = _row(uuid4(), media="application/pdf", name="brief.pdf")
    (validated,) = _run(monkeypatch, [_request(row)], [row])
    assert validated.family == "document" and validated.filename == "brief.pdf"


def test_mismatch_and_absence_refuse_by_code(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row(uuid4())
    with pytest.raises(AttachmentReferenceError) as missing:
        _run(monkeypatch, [_request(row)], [])
    assert missing.value.code == "ATTACHMENT_NOT_FOUND"
    with pytest.raises(AttachmentReferenceError) as mismatch:
        _run(monkeypatch, [_request(row, byte_count=99)], [row])
    assert mismatch.value.code == "ATTACHMENT_MISMATCH"


def test_limits_and_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_row(uuid4(), size=60) for _ in range(3)]
    small = _settings(chat_attachment_max_files=2)
    with pytest.raises(AttachmentReferenceError) as too_many:
        _run(monkeypatch, [_request(r) for r in rows], rows, small)
    assert too_many.value.code == "ATTACHMENT_LIMIT_EXCEEDED"
    tight = _settings(chat_attachment_max_total_bytes=100)
    with pytest.raises(AttachmentReferenceError) as too_big:
        _run(monkeypatch, [_request(r) for r in rows[:2]], rows, tight)
    assert too_big.value.code == "ATTACHMENT_LIMIT_EXCEEDED"
    with pytest.raises(AttachmentReferenceError) as dup:
        _run(monkeypatch, [_request(rows[0]), _request(rows[0])], rows)
    assert dup.value.code == "ATTACHMENT_DUPLICATE"


def test_attachments_need_artifact_storage() -> None:
    """Spec §3.2: without a store to hold the bytes the turn is refused 503, never half-accepted.

    Asserted on the router helper directly because the branch is unreachable over HTTP — both
    submission routes register only when the deployment composed a storage backend.
    """

    row = _row(uuid4())
    with pytest.raises(HTTPException) as refusal:
        asyncio.run(
            _validated_submission_attachments(
                object(),  # type: ignore[arg-type]
                workspace_id=WS,
                refs=(_request(row),),
                settings=_settings(),
                storage=None,
            )
        )
    assert refusal.value.status_code == 503
    assert refusal.value.detail["code"] == "CAPABILITY_UNAVAILABLE"  # type: ignore[index]
