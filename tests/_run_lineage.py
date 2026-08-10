"""Shared assertions for FI-2 P2 run-lineage registration (spec §3).

Every production run-mint site registers its run in ``run_lineage`` inside the same transaction as
the first durable write that uses the run id — never per claim. These helpers are the single place
the "a claim's ``run_id`` back-joins to the project that produced it" assertion is written, so the
per-path suites (discovery / scoring / tiering / import / stage 0 / …) all check the same contract.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_LINEAGE_SQL = text(
    "SELECT workspace_id, project_id, project_run_id, kind FROM run_lineage WHERE run_id = :run_id"
)
_CLAIMS_SQL = text("SELECT count(*) FROM claim WHERE run_id = :run_id")


def _uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def assert_run_registered(
    conn: AsyncConnection,
    run_id: Any,
    *,
    kind: str,
    workspace_id: str,
    project_id: str | None = None,
    project_run_id: Any | None = None,
) -> None:
    """The run is in ``run_lineage`` with exactly this attribution."""
    row = (await conn.execute(_LINEAGE_SQL, {"run_id": _uuid(run_id)})).mappings().one_or_none()
    assert row is not None, f"run {run_id} (kind={kind}) was never registered in run_lineage"
    assert row["kind"] == kind, f"run {run_id} registered as {row['kind']!r}, expected {kind!r}"
    assert row["workspace_id"] == workspace_id
    assert row["project_id"] == project_id
    registered_run = None if row["project_run_id"] is None else _uuid(row["project_run_id"])
    assert registered_run == (None if project_run_id is None else _uuid(project_run_id))


async def assert_written_claims_are_attributable(
    conn: AsyncConnection,
    run_id: Any,
    *,
    kind: str,
    workspace_id: str,
    project_id: str | None = None,
    project_run_id: Any | None = None,
) -> None:
    """The path actually wrote claims under ``run_id`` *and* that run is attributable.

    Asserting the claim count first keeps the test honest: a path that silently wrote nothing would
    otherwise pass the lineage assertion vacuously.
    """
    written = int((await conn.execute(_CLAIMS_SQL, {"run_id": _uuid(run_id)})).scalar_one())
    assert written > 0, f"expected claims written under run {run_id} (kind={kind}), found none"
    await assert_run_registered(
        conn,
        run_id,
        kind=kind,
        workspace_id=workspace_id,
        project_id=project_id,
        project_run_id=project_run_id,
    )
