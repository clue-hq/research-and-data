"""Site-snapshot DAL (clone-fidelity F0.1) — what one website ingestion captured, kept.

``design_site_snapshot`` holds one row per (ingestion job, page): the digests of the post-JS
HTML, of every stylesheet the capture fetched, and of the full-page screenshot. The BYTES are
not here — they live in the design blob namespace behind
:func:`clue_design.storage.register_design_bytes` under ``source_key = "design_site_snapshot"``,
which is what makes a re-ingest of an unchanged site cost one row and no bytes.

Workspace-scoped and fail-closed like the rest of the DAL: a foreign-workspace snapshot id
raises the same :class:`DesignNotFoundError` an absent one does, so existence never leaks across
tenants. Callers own the transaction (one logical operation, one transaction — the O5 rule);
nothing here commits.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, as_datetime, dump_json, iso, load_json
from clue_design.errors import DesignNotFoundError

_COLUMNS = (
    "snapshot_id, workspace_id, job_id, page_url, page_index, html_digest, stylesheets_json, "
    "screenshot_digest, viewport_width, captured_at, meta_json, created_at"
)


def _from_row(row: Any) -> JsonObject:
    return {
        "snapshot_id": row.snapshot_id,
        "workspace_id": row.workspace_id,
        "job_id": row.job_id,
        "page_url": row.page_url,
        "page_index": row.page_index,
        "html_digest": row.html_digest,
        "stylesheets": load_json(row.stylesheets_json),
        "screenshot_digest": row.screenshot_digest,
        "viewport_width": row.viewport_width,
        "captured_at": iso(row.captured_at),
        "meta": load_json(row.meta_json),
        "created_at": iso(row.created_at),
    }


async def upsert_site_snapshot(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    snapshot_id: str,
    job_id: str,
    page_url: str,
    page_index: int,
    html_digest: str,
    stylesheets: Sequence[JsonObject],
    screenshot_digest: str | None,
    viewport_width: int | None,
    captured_at: object,
    meta: JsonObject,
) -> JsonObject:
    """Record one captured page. Re-recording the same ``snapshot_id`` CONVERGES.

    The id is content-derived from ``(job_id, page_url)``, so the only writer that can already
    hold that slot is an earlier attempt of this same job — the D5 Round C reaper re-offers a job
    whose worker died mid-flight, and that attempt must land on its predecessor's rows rather
    than fail on them. A collision on ``(job_id, page_url)`` under a DIFFERENT id is a different
    animal entirely (someone minted an id another way) and is refused by the unique constraint.
    """
    await conn.execute(
        text(
            """
            INSERT INTO design_site_snapshot
              (snapshot_id, workspace_id, job_id, page_url, page_index, html_digest,
               stylesheets_json, screenshot_digest, viewport_width, captured_at, meta_json)
            VALUES
              (:snapshot_id, :workspace_id, :job_id, :page_url, :page_index, :html_digest,
               CAST(:stylesheets AS jsonb), :screenshot_digest, :viewport_width,
               :captured_at, CAST(:meta AS jsonb))
            ON CONFLICT (snapshot_id) DO UPDATE SET
               page_index = EXCLUDED.page_index,
               html_digest = EXCLUDED.html_digest,
               stylesheets_json = EXCLUDED.stylesheets_json,
               screenshot_digest = EXCLUDED.screenshot_digest,
               viewport_width = EXCLUDED.viewport_width,
               captured_at = EXCLUDED.captured_at,
               meta_json = EXCLUDED.meta_json
            WHERE design_site_snapshot.workspace_id = EXCLUDED.workspace_id
            """
        ),
        {
            "snapshot_id": snapshot_id,
            "workspace_id": workspace_id,
            "job_id": job_id,
            "page_url": page_url,
            "page_index": page_index,
            "html_digest": html_digest,
            "stylesheets": dump_json(list(stylesheets)),
            "screenshot_digest": screenshot_digest,
            "viewport_width": viewport_width,
            "captured_at": as_datetime(captured_at),
            "meta": dump_json(meta),
        },
    )
    return await get_site_snapshot(conn, workspace_id=workspace_id, snapshot_id=snapshot_id)


async def get_site_snapshot(
    conn: AsyncConnection, *, workspace_id: str, snapshot_id: str
) -> JsonObject:
    """One snapshot row, or the fail-closed refusal (absent OR another tenant's)."""
    row = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM design_site_snapshot "
                "WHERE snapshot_id = :snapshot_id AND workspace_id = :workspace_id"
            ),
            {"snapshot_id": snapshot_id, "workspace_id": workspace_id},
        )
    ).one_or_none()
    if row is None:
        raise DesignNotFoundError("design_site_snapshot", snapshot_id)
    return _from_row(row)


async def list_site_snapshots_for_job(
    conn: AsyncConnection, *, workspace_id: str, job_id: str
) -> list[JsonObject]:
    """Every page one ingestion job captured, in capture order (entry page first)."""
    rows = await conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM design_site_snapshot "
            "WHERE workspace_id = :workspace_id AND job_id = :job_id "
            "ORDER BY page_index, page_url"
        ),
        {"workspace_id": workspace_id, "job_id": job_id},
    )
    return [_from_row(row) for row in rows]
