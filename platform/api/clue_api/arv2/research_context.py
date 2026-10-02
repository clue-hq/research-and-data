"""One persona selection per research run; children read the same artifact pin."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_store import read_persona_documents
from clue_api.arv2.knowledge_frontmatter import document_identity, parse_front_matter
from clue_storage import StorageBackend, read_verified_artifact


async def pin_persona(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str,
    icp_key: str,
    icp_version: int,
) -> dict[str, Any]:
    documents = await read_persona_documents(
        conn, workspace_id=workspace_id, brand_id=brand_id, project_id=project_id
    )
    unreadable = False
    mismatched = False
    for doc in documents:
        try:
            record, raw = await read_verified_artifact(
                conn, storage, storage_key=doc.artifact_key or "", workspace_id=workspace_id
            )
            front, _ = parse_front_matter(raw.decode())
        except Exception:
            unreadable = True
            continue
        _, key = document_identity(front)
        if key != icp_key:
            continue
        source_version = front.get("icp_version")
        if source_version is not None and str(source_version) != str(icp_version):
            mismatched = True
            continue
        return {
            "version": 1,
            "state": "pinned",
            "document_id": str(doc.document_id),
            "document_version": doc.version,
            "artifact_key": doc.artifact_key,
            "sha256": record.content_sha256,
            "lineage": "matched" if source_version is not None else "unverified",
        }
    return {
        "version": 1,
        "state": "lineage_mismatch" if mismatched else "unreadable" if unreadable else "missing",
    }


async def read_persona_pin(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    pin: dict[str, Any],
) -> str:
    if pin.get("state") != "pinned":
        return f"PERSONA CONTEXT GAP: {pin.get('state', 'missing')}. Use the confirmed ICP."
    record, raw = await read_verified_artifact(
        conn, storage, storage_key=pin["artifact_key"], workspace_id=workspace_id
    )
    if record.content_sha256 != pin["sha256"]:
        raise ValueError("persona artifact differs from the research launch pin")
    _, body = parse_front_matter(raw.decode())
    if pin.get("lineage") != "matched":
        body = "PERSONA LINEAGE GAP: exact ICP version was not declared.\n\n" + body
    return body
