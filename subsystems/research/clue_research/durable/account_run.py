"""The ``account_run`` repository — read/write the per-account research-run cursor (M7.1).

The only sanctioned path to the ``account_run`` table, mirroring the claim store's repository shape
(``claimstore/claims.py``): module-level ``text(...)`` statements + ``async def`` helpers that take
an :class:`~sqlalchemy.ext.asyncio.AsyncConnection`. No caller hand-writes SQL against the table.

``account_run`` is mutable execution state (not append-only): the orchestrator ensures the row and
persists the plan, advancing it to ``running`` **before** any worker spawns, then folds the
collected references in. (M7.1's ``begin()`` does the ensure + plan in one transaction, so a
graph-started run is ``running`` from its first commit; the ``pending``/``planning`` states are for
a staged lifecycle — see :class:`~clue_research.durable.enums.AccountRunStatus`.) JSONB
(``plan_json``, ``references_index``) round-trips through the one ``core`` serialization path,
like ``claim.value_json``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    CostCents,
    EntityId,
    ProjectRunId,
    ResearchDirectiveId,
    ResearchDirectiveOverrideId,
    ResearchDirectivePin,
    RunId,
    UtcDatetime,
    decode_jsonb,
    serialize_value_json,
)
from clue_research.claimstore import record_run_lineage
from clue_research.durable.enums import AccountRunStatus, AccountRunSubPhase
from clue_research.durable.project_run import get_project_run

# Claim-id references grouped by aspect — the orchestrator's context-bounding artifact (substrate
# §5b): the lead holds ids, never claim bodies.
ReferencesIndex = dict[str, list[str]]


class AccountRunRow(BaseModel):
    """An ``account_run`` row reconstructed from the table (M7.1).

    ``id`` is the ``claim.run_id`` every worker of this run stamps. ``references_index`` maps each
    planned aspect to the claim ids that aspect's worker wrote — references only, so rebuilding a
    row never materializes a claim body.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: RunId
    project_run_id: ProjectRunId
    entity_id: EntityId
    tier: str
    status: AccountRunStatus
    sub_phase: AccountRunSubPhase | None = None
    plan_json: dict[str, JsonValue]
    references_index: ReferencesIndex
    cost_cents: CostCents
    budget_cap_cents: CostCents | None = None
    research_directive: ResearchDirectivePin | None = None
    started_at: UtcDatetime
    updated_at: UtcDatetime


_INSERT_SQL = text(
    """
    INSERT INTO account_run (id, project_run_id, entity_id, tier, status)
    VALUES (:id, :project_run_id, :entity_id, :tier, CAST(:status AS account_run_status))
    RETURNING id
    """
)

_ENSURE_SQL = text(
    """
    INSERT INTO account_run (id, project_run_id, entity_id, tier, status, budget_cap_cents)
    VALUES (:id, :project_run_id, :entity_id, :tier, CAST(:status AS account_run_status), :budget)
    ON CONFLICT (id) DO NOTHING
    """
)

_SELECT_COLUMNS = (
    "id, project_run_id, entity_id, tier, status, sub_phase, plan_json, references_index, "
    "cost_cents, budget_cap_cents, research_directive_id, research_directive_version, "
    "research_directive_ref, "
    "research_directive_sha256, research_directive_override_id, "
    "research_directive_override_ref, research_directive_override_sha256, started_at, updated_at"
)

_GET_SQL = text(f"SELECT {_SELECT_COLUMNS} FROM account_run WHERE id = :id")


async def _register_account_run_lineage(
    conn: AsyncConnection,
    *,
    account_run_id: RunId,
    project_run_id: ProjectRunId,
) -> None:
    """Attribute the account run to its project (FI-2 P2, spec §3) — at its own mint site.

    ``account_run.id`` *is* the ``claim.run_id`` every worker of the run stamps, so it is a
    claim-writing run like any other and must back-join to a project. Registered here, in the
    caller's transaction (the same one the row commits in), and idempotent — a resume that
    re-ensures the same run re-registers harmlessly. ``entity_research`` matches the kind the
    one-shot repair (``clue_research.project_lens_backfill``'s ``account_run_lineage`` source)
    reconstructs for rows that predate this writer.

    The workspace and project come from the ``project_run`` row rather than the caller: the two
    mint sites here take no workspace argument, and deriving it keeps the attribution identical to
    the run's own context by construction. ``account_run.project_run_id`` carries no FK, so a row
    naming a project run that does not exist is possible; such a run is left unattributed (the
    backfill's ``skipped_orphan`` disposition) rather than failing the insert — an orphan account
    run belongs to no project's lens, and an execution write must never be blocked by a lineage
    lookup.
    """
    project_run = await get_project_run(conn, project_run_id)
    if project_run is None:
        return
    await record_run_lineage(
        conn,
        run_id=UUID(str(account_run_id)),
        workspace_id=project_run.workspace_id,
        kind="entity_research",
        project_id=project_run.project_id,
        project_run_id=UUID(str(project_run_id)),
    )


async def insert_account_run(
    conn: AsyncConnection,
    *,
    account_run_id: RunId,
    project_run_id: ProjectRunId,
    entity_id: EntityId,
    tier: str,
    status: AccountRunStatus = AccountRunStatus.PENDING,
) -> RunId:
    """Insert a fresh ``account_run`` row (``pending`` by default) and return its id.

    The id is supplied by the caller (the graph mints it once per account so it is stable across
    a crash-and-resume) and becomes the ``claim.run_id`` provenance for every claim the run writes.
    """
    result = await conn.execute(
        _INSERT_SQL,
        {
            "id": account_run_id,
            "project_run_id": project_run_id,
            "entity_id": entity_id,
            "tier": tier,
            "status": status.value,
        },
    )
    await _register_account_run_lineage(
        conn, account_run_id=account_run_id, project_run_id=project_run_id
    )
    return RunId(result.scalar_one())


async def ensure_account_run(
    conn: AsyncConnection,
    *,
    account_run_id: RunId,
    project_run_id: ProjectRunId,
    entity_id: EntityId,
    tier: str,
    status: AccountRunStatus = AccountRunStatus.PENDING,
    budget_cap_cents: CostCents | None = None,
) -> None:
    """Insert the ``account_run`` row if it does not already exist (``ON CONFLICT DO NOTHING``).

    The resume-safe variant of :func:`insert_account_run`: a crash *during* the lead's plan step
    re-enters with the same ``account_run_id`` (the LangGraph ``thread_id``), so the insert must be
    a no-op the second time rather than a primary-key violation. Status is left untouched on
    conflict (a re-entry never resets a run that already advanced)."""
    await conn.execute(
        _ENSURE_SQL,
        {
            "id": account_run_id,
            "project_run_id": project_run_id,
            "entity_id": entity_id,
            "tier": tier,
            "status": status.value,
            "budget": budget_cap_cents,
        },
    )
    await _register_account_run_lineage(
        conn, account_run_id=account_run_id, project_run_id=project_run_id
    )


async def pin_account_run_research_directive(
    conn: AsyncConnection,
    *,
    account_run_id: RunId,
    pin: ResearchDirectivePin,
) -> None:
    """Set one confirmed directive pin exactly once; retries must present the same pin."""

    result = await conn.execute(
        text(
            "UPDATE account_run SET research_directive_id=:directive_id, "
            "research_directive_version=:version, research_directive_ref=:directive_ref, "
            "research_directive_sha256=:sha256, "
            "research_directive_override_id=:override_id, "
            "research_directive_override_ref=:override_ref, "
            "research_directive_override_sha256=:override_sha256 "
            "WHERE id=:account_run_id AND research_directive_id IS NULL "
            "AND status='pending' AND plan_json='{}'::jsonb"
        ),
        {
            "account_run_id": account_run_id,
            "directive_id": pin.directive_id,
            "version": pin.version,
            "directive_ref": pin.directive_ref,
            "sha256": pin.canonical_json_sha256,
            "override_id": pin.override_id,
            "override_ref": pin.override_ref,
            "override_sha256": pin.override_sha256,
        },
    )
    if result.rowcount:
        return
    row = await get_account_run(conn, account_run_id)
    if row is None:
        raise ValueError(f"account run {account_run_id} does not exist")
    if row.research_directive is None:
        raise ValueError("account run already began without a research directive pin")
    if row.research_directive != pin:
        raise ValueError("account run already pins a different research directive")


async def get_account_run(conn: AsyncConnection, account_run_id: RunId) -> AccountRunRow | None:
    """Return the ``account_run`` row, or ``None`` if it does not exist."""
    row = (await conn.execute(_GET_SQL, {"id": account_run_id})).mappings().one_or_none()
    return _row_to_account_run(dict(row)) if row is not None else None


_LIST_BY_CAMPAIGN_SQL = text(
    f"SELECT {_SELECT_COLUMNS} FROM account_run WHERE project_run_id = :project_run_id "
    "ORDER BY entity_id"
)


async def list_account_runs(
    conn: AsyncConnection, project_run_id: ProjectRunId
) -> list[AccountRunRow]:
    """All ``account_run`` rows for a project run, ordered by ``entity_id`` (a stable page).

    The read the M12.3 handoff emit path needs: it filters the returned rows to the handoff-ready
    accounts (``status = DONE`` AND ``sub_phase = CONTACTS_COMPLETE`` — "M12-ready", per
    :class:`AccountRunSubPhase`) to assemble + emit a handoff per account. A read-only repository
    helper (no caller hand-writes SQL against ``account_run`` — the repository is the only path)."""
    rows = (
        (await conn.execute(_LIST_BY_CAMPAIGN_SQL, {"project_run_id": project_run_id}))
        .mappings()
        .all()
    )
    return [_row_to_account_run(dict(r)) for r in rows]


async def find_account_runs_for_entity(
    conn: AsyncConnection,
    *,
    project_run_id: ProjectRunId,
    entity_id: EntityId,
    directive_ref: str | None = None,
    limit: int = 2,
) -> tuple[AccountRunRow, ...]:
    """Return the bounded exact project-run/account scope used by fail-closed readers.

    ``directive_ref`` lets a retry select the account run pinned to its own immutable directive
    even when earlier research runs for the same account remain in the project-run history.
    """

    directive_predicate = (
        " AND research_directive_ref = :directive_ref" if directive_ref is not None else ""
    )

    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_SELECT_COLUMNS} FROM account_run "
                    "WHERE project_run_id = :project_run_id AND entity_id = :entity_id "
                    f"{directive_predicate} "
                    "ORDER BY id LIMIT :limit"
                ),
                {
                    "project_run_id": project_run_id,
                    "entity_id": entity_id,
                    "directive_ref": directive_ref,
                    "limit": min(max(limit, 1), 10),
                },
            )
        )
        .mappings()
        .all()
    )
    return tuple(_row_to_account_run(dict(row)) for row in rows)


async def save_plan(
    conn: AsyncConnection,
    account_run_id: RunId,
    *,
    plan_json: dict[str, JsonValue],
    status: AccountRunStatus,
) -> None:
    """Persist the research plan and advance status (M7.1 AC: plan committed before any spawn)."""
    await conn.execute(
        text(
            """
            UPDATE account_run
            SET plan_json = CAST(:plan_json AS jsonb),
                status = CAST(:status AS account_run_status),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": account_run_id,
            "plan_json": serialize_value_json(plan_json),
            "status": status.value,
        },
    )


async def save_references(
    conn: AsyncConnection,
    account_run_id: RunId,
    *,
    references_index: ReferencesIndex,
    cost_cents: CostCents,
    status: AccountRunStatus,
) -> None:
    """Fold the collected aspect→claim-id references and accumulated cost in; advance status.

    Reference-collection step (M7.1): the orchestrator records *ids*, never bodies, so the row's
    size is independent of how much each worker found.
    """
    await conn.execute(
        text(
            """
            UPDATE account_run
            SET references_index = CAST(:references_index AS jsonb),
                cost_cents = :cost_cents,
                status = CAST(:status AS account_run_status),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": account_run_id,
            "references_index": serialize_value_json(references_index),
            "cost_cents": cost_cents,
            "status": status.value,
        },
    )


async def fold_references(
    conn: AsyncConnection,
    account_run_id: RunId,
    *,
    references_index: ReferencesIndex,
    status: AccountRunStatus,
) -> None:
    """Fold the collected references and advance status — without touching ``cost_cents`` (M8A.4).

    The cost-blind sibling of :func:`save_references`: the M8A deep orchestrator routes every
    committee/contact charge through :meth:`BudgetEngine.record`, which becomes the **single live
    writer** of ``account_run.cost_cents`` (atomically with the claim writes + the M7.4 ledger
    finalise, on one connection). The references fold must therefore *not* re-``SET`` the cost, or
    it would clobber the record-owned increments (the single-writer reconciliation, spec §M8A.4).
    Takes a connection so the orchestrator commits the fold + marker (:func:`set_account_sub_phase`)
    in the **same** transaction as the spend it folds. (The M7.1 graph path keeps using
    :func:`save_references`, which still owns ``cost_cents`` on the account axis it drives.)
    """
    await conn.execute(
        text(
            """
            UPDATE account_run
            SET references_index = CAST(:references_index AS jsonb),
                status = CAST(:status AS account_run_status),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": account_run_id,
            "references_index": serialize_value_json(references_index),
            "status": status.value,
        },
    )


async def set_status(
    conn: AsyncConnection, account_run_id: RunId, status: AccountRunStatus
) -> None:
    """Advance only the run's status (e.g. ``failed`` / ``paused``), stamping ``updated_at``."""
    await conn.execute(
        text(
            """
            UPDATE account_run
            SET status = CAST(:status AS account_run_status), updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": account_run_id, "status": status.value},
    )


async def set_account_sub_phase(
    conn: AsyncConnection, account_run_id: RunId, sub_phase: AccountRunSubPhase
) -> None:
    """Advance the deep-orchestration sub-phase marker (M8A.0), stamping ``updated_at``.

    Orthogonal to :func:`set_status`: this records *which* of the ``account → committee → contact``
    deep stages finished (M8A.1), so a crashed run resumes at its last boundary. Born ``NULL`` (not
    started) and advanced monotonically; it is **advisory** — the M7.4 ledger stays authoritative
    for spend, and the claim-store gap-recompute is the correctness backstop, so a stale marker can
    only cause an idempotent re-run.

    Takes a connection (like :func:`set_status` / :func:`save_references`) so the M8A.1 orchestrator
    can advance the marker inside the **same** transaction as its claim writes + budget charge (the
    M8A.4 exactly-once boundary), not in a separate commit.
    """
    await conn.execute(
        text(
            """
            UPDATE account_run
            SET sub_phase = CAST(:sub_phase AS account_run_sub_phase), updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": account_run_id, "sub_phase": sub_phase.value},
    )


def _row_to_account_run(row: dict[str, object]) -> AccountRunRow:
    research_directive = None
    if row["research_directive_id"] is not None:
        research_directive = ResearchDirectivePin(
            directive_id=ResearchDirectiveId(row["research_directive_id"]),  # type: ignore[arg-type]
            version=cast(int, row["research_directive_version"]),
            directive_ref=str(row["research_directive_ref"]),
            canonical_json_sha256=str(row["research_directive_sha256"]),
            account_id=EntityId(row["entity_id"]),  # type: ignore[arg-type]
            override_id=(
                ResearchDirectiveOverrideId(row["research_directive_override_id"])  # type: ignore[arg-type]
                if row["research_directive_override_id"] is not None
                else None
            ),
            override_ref=(
                str(row["research_directive_override_ref"])
                if row["research_directive_override_ref"] is not None
                else None
            ),
            override_sha256=(
                str(row["research_directive_override_sha256"])
                if row["research_directive_override_sha256"] is not None
                else None
            ),
        )
    return AccountRunRow.model_validate(
        {
            "id": row["id"],
            "project_run_id": row["project_run_id"],
            "entity_id": row["entity_id"],
            "tier": row["tier"],
            "status": row["status"],
            "sub_phase": row["sub_phase"],
            "plan_json": decode_jsonb(row["plan_json"]),
            "references_index": decode_jsonb(row["references_index"]),
            "cost_cents": row["cost_cents"] if row["cost_cents"] is not None else Decimal(0),
            "budget_cap_cents": row["budget_cap_cents"],
            "research_directive": research_directive,
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
        }
    )
