"""Source URLs and existing read paths for one acquisition; no extra provider purchase."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.evidence_paths import source_path
from clue_api.arv2.quality_evidence import EvidenceGrant, list_sources


def source_navigation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep original locators and separate synthesized reports from returned source excerpts."""
    return {
        "evidence_index_path": "/evidence/index.json",
        "sources": [
            {
                "source_id": row["source_id"],
                "path": source_path(row),
                "kind": row["kind"],
                "url": row.get("source_url"),
                "origin_locator": row["origin_locator"],
                "title": row.get("metadata", {}).get("title"),
                "content_kind": row.get("metadata", {}).get("content_kind"),
                "published_at": row.get("metadata", {}).get("published_at"),
            }
            for row in rows
            if row.get("available")
        ],
        "unavailable_source_count": sum(not row.get("available") for row in rows),
    }


async def operation_source_navigation(
    conn: AsyncConnection, grant: EvidenceGrant, operation_id: UUID
) -> dict[str, Any]:
    """Use the existing grant/erasure checks and paginate beyond the first source-index page."""
    rows: list[dict[str, Any]] = []
    after = 0
    while True:
        page = await list_sources(conn, grant, after=after, limit=100, operation_id=operation_id)
        rows.extend(page["sources"])
        after = page["next_after"]
        if after is None:
            return {"operation_id": str(operation_id), **source_navigation(rows)}
