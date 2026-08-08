"""``run_lineage`` — the claim→project join spine (FI-2 P2; spec §3).

Every claim carries a ``run_id``; nothing else records *which project* that run served. This
module is that registry: one row per run, written once at run-mint time, read back as the
project-lens predicate ``claim.run_id IN project_run_ids(...)``.

Registration is idempotent (``ON CONFLICT (run_id) DO NOTHING``) so a replayed or resumed run
re-registers harmlessly; the first write wins. A run with no ``project_id`` is workspace-level
(stage 0, seeds, client-KB) and belongs to no project's lens.

Known exemption classes — runs that deliberately carry **no** lineage row
=========================================================================
"Every claim-writing run registers" is the rule, not a universal. Two classes are exempt by
design; an audit that finds a ``claim.run_id`` with no ``run_lineage`` row should check these
before filing a bug:

* **Redaction / tombstone runs.** The DSAR and erasure paths (``compliance/dsar.py``,
  ``compliance/workspace_erasure.py``, and the Phase-C erasure wiring) mint a run id to supersede
  a claim with a redacted, ``REJECTED`` tombstone. Those runs are *not* registered, and must not
  be: a redaction belongs to no project's lens — it is an act of removal, not of research — and
  the tombstones it writes are merge-excluded anyway, so no project read can ever surface them.
  Registering them would attribute an erasure to a project that never asked for it.
* **Pre-FI-2 historical rows.** Claims written before the FI-2 P2 mint sites landed have no
  lineage row. ``clue_research.project_lens_backfill`` reconstructs the *launch-level* runs from
  the durable execution records; anything it cannot reach stays unattributed by construction.

Everything else that writes a claim registers its run at the mint site, in the same transaction
as the first durable write that uses it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import RunId

# Mirrors the ``run_lineage_kind_check`` CHECK in migration 9a21734d9406 (text + CHECK, not a DB
# enum) — the test suite asserts every kind here is accepted by the constraint.
RUN_LINEAGE_KINDS = (
    "discovery",
    "import",
    "scoring",
    "tiering",
    "entity_research",
    "committee",
    "contact_research",
    "narrative",
    "stage0",
    "enrichment",
    "manual",
)

_RECORD = text(
    """
    INSERT INTO run_lineage (run_id, workspace_id, project_id, project_run_id, kind, created_at)
    VALUES (:run_id, :workspace_id, :project_id, :project_run_id, :kind, :created_at)
    ON CONFLICT (run_id) DO NOTHING
    """
)

_BY_PROJECT = text(
    """
    SELECT run_id FROM run_lineage
    WHERE workspace_id = :workspace_id AND project_id = :project_id
    ORDER BY created_at, run_id
    """
)

_BY_PROJECT_RUN = text(
    """
    SELECT run_id FROM run_lineage
    WHERE workspace_id = :workspace_id AND project_run_id = :project_run_id
    ORDER BY created_at, run_id
    """
)


async def record_run_lineage(
    conn: AsyncConnection,
    *,
    run_id: uuid.UUID,
    workspace_id: str,
    kind: str,
    project_id: str | None = None,
    project_run_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> None:
    """Attribute one run to its workspace (and project, when it has one). Idempotent.

    Raises :class:`ValueError` on an unknown ``kind``, or on a ``project_run_id`` with no
    ``project_id`` (that run would be attributed to a project no lens read can find — the
    ``run_lineage_project_requires_project_id`` CHECK mirrors it). Both are raised before any
    statement is issued, so a bad caller never leaves a partial write or poisons a shared
    transaction.
    """
    if kind not in RUN_LINEAGE_KINDS:
        raise ValueError(f"unknown run lineage kind {kind!r}; expected one of {RUN_LINEAGE_KINDS}")
    if project_run_id is not None and project_id is None:
        raise ValueError(f"run lineage for project_run {project_run_id} needs a project_id")
    await conn.execute(
        _RECORD,
        {
            "run_id": run_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "project_run_id": project_run_id,
            "kind": kind,
            "created_at": created_at or datetime.now(UTC),
        },
    )


async def project_run_ids(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> tuple[RunId, ...]:
    """Every run id attributed to the project — the project-lens read predicate's input."""
    rows = await conn.execute(_BY_PROJECT, {"workspace_id": workspace_id, "project_id": project_id})
    return tuple(RunId(run_id) for run_id in rows.scalars())


async def runs_for_project_run(
    conn: AsyncConnection, *, workspace_id: str, project_run_id: uuid.UUID
) -> tuple[RunId, ...]:
    """Every run id attributed to **one execution** of a project — the narrower lens.

    :func:`project_run_ids` answers "which runs served this project"; this answers "which runs
    served this *run of* the project". It is what a project-run-pinned read needs (the C7 research
    view's ``context_scope='project_run_pinned'`` routes): a later run of the same project is a
    different execution and its claims must not leak into an earlier run's pinned sections.

    Workspace-level runs (``project_run_id IS NULL`` — stage 0, seeds, client-KB) and the known
    exemption classes in this module's docstring are excluded by construction: no lineage row, or
    no project run, means no membership in any project run's set.

    The read is by ``(workspace_id, project_run_id)``; the ``run_lineage_by_project`` index covers
    only the ``workspace_id`` prefix of it, which is sufficient at the row counts this table holds
    (one row per run) — a dedicated index would need a migration and has no measured need yet.
    """
    rows = await conn.execute(
        _BY_PROJECT_RUN, {"workspace_id": workspace_id, "project_run_id": project_run_id}
    )
    return tuple(RunId(run_id) for run_id in rows.scalars())
