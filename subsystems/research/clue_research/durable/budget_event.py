"""The ``budget_event`` repository + the cost-accounting read/write helpers (M7.5).

The only sanctioned SQL path to the cost-governance state, mirroring the ``account_run`` /
``project_run`` repository shape (``durable/account_run.py``, ``durable/project_run.py``):
module-level ``text(...)`` statements + ``async def`` helpers that take an
:class:`~sqlalchemy.ext.asyncio.AsyncConnection`. No caller hand-writes SQL against these tables.

Two kinds of state live here, both read/written by the M7.5
:class:`~clue_research.durable.budget.BudgetEngine`:

* the **live spend counters** — ``project_run.spent_cents`` (run scope) and
  ``account_run.cost_cents`` (account scope) — incremented by :func:`add_run_spend` /
  :func:`add_account_spend` on each charge,
  plus the caps (``project_run.budget_cap_cents`` already exists from M7.3;
  ``account_run.budget_cap_cents`` and ``project_run.estimated_cents`` are added by the M7.5
  migration). These back :meth:`BudgetEngine.check` / :meth:`record` / :meth:`burn_down`.
* the **append-only governance audit** — ``budget_event`` — one immutable row per governed decision
  (:func:`insert_budget_event`), ordered by the monotonic ``seq`` (rows in one transaction tie on
  ``created_at``). A *charge* is never an event; charges are the spend counters above.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    BudgetScope,
    CostCents,
    ProjectRunId,
    RunId,
    UtcDatetime,
    decode_jsonb,
    serialize_value_json,
)
from clue_research.durable.enums import BudgetEventKind


class BudgetEventRow(BaseModel):
    """One append-only ``budget_event`` row (M7.5) — an audited cost-governance decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    seq: int
    project_run_id: ProjectRunId
    scope: BudgetScope
    kind: BudgetEventKind
    projected_cents: CostCents
    cap_cents: CostCents | None
    detail: dict[str, JsonValue]
    created_at: UtcDatetime


class RunBudgetState(BaseModel):
    """The project-run cost figures the budget engine reads (M7.5) — the per-run scope.

    ``spent_cents`` is the live running total (incremented per charge); ``cap_cents`` is the
    per-campaign hard cap (``None`` = uncapped); ``estimated_cents`` is the latest persisted pre-run
    projection (``None`` = never estimated). The three are exactly the burn-down surface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spent_cents: CostCents
    cap_cents: CostCents | None
    estimated_cents: CostCents | None


class AccountBudgetState(BaseModel):
    """The per-account cost figures the budget engine reads (M7.5) — the per-account scope.

    ``cost_cents`` is the account run's live spend (M7.1's column, = the per-account *spent*);
    ``budget_cap_cents`` is the optional per-account hard cap override (``None`` = fall back to the
    per-tier policy band); ``tier`` selects that band."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cost_cents: CostCents
    tier: str
    budget_cap_cents: CostCents | None


# --- budget_event (append-only governance audit) ------------------------------------------------

_EVENT_COLUMNS = (
    "id, seq, project_run_id, scope, kind, projected_cents, cap_cents, detail_json, created_at"
)

_INSERT_EVENT_SQL = text(
    """
    INSERT INTO budget_event (
        id, project_run_id, scope, kind, projected_cents, cap_cents, detail_json
    )
    VALUES (
        :id, :project_run_id, CAST(:scope AS budget_scope), CAST(:kind AS budget_event_kind),
        :projected_cents, :cap_cents, CAST(:detail AS jsonb)
    )
    """
)

_LIST_EVENTS_SQL = text(
    f"SELECT {_EVENT_COLUMNS} FROM budget_event WHERE project_run_id = :run ORDER BY seq"
)


async def insert_budget_event(
    conn: AsyncConnection,
    *,
    project_run_id: ProjectRunId,
    scope: BudgetScope,
    kind: BudgetEventKind,
    projected_cents: CostCents,
    cap_cents: CostCents | None,
    detail: dict[str, JsonValue] | None = None,
) -> None:
    """Append one immutable budget-governance event (M7.5) — a ``check_deny`` / ``graceful_stop`` /
    ``breach_pending`` / ``cap_raised`` decision the burn-down/audit surface reads. ``cap_cents`` is
    the cap in force at the decision (``None`` when uncapped); ``detail`` carries optional refs
    (entity/account ids, a reason) without a schema change."""
    await conn.execute(
        _INSERT_EVENT_SQL,
        {
            "id": uuid4(),
            "project_run_id": project_run_id,
            "scope": scope.value,
            "kind": kind.value,
            "projected_cents": projected_cents,
            "cap_cents": cap_cents,
            "detail": serialize_value_json(detail if detail is not None else {}),
        },
    )


async def list_budget_events(
    conn: AsyncConnection, project_run_id: ProjectRunId
) -> list[BudgetEventRow]:
    """All budget events for a run, oldest first by the monotonic ``seq`` (the audit trail)."""
    rows = (await conn.execute(_LIST_EVENTS_SQL, {"run": project_run_id})).mappings().all()
    return [_row_to_event(dict(r)) for r in rows]


# --- run-scope counters / caps / estimate (project_run) ----------------------------------------

_GET_RUN_BUDGET_SQL = text(
    "SELECT spent_cents, budget_cap_cents, estimated_cents FROM project_run WHERE id = :id"
)

_ADD_RUN_SPEND_SQL = text(
    "UPDATE project_run SET spent_cents = spent_cents + :delta, updated_at = now() WHERE id = :id"
)

_SET_ESTIMATED_SQL = text(
    "UPDATE project_run SET estimated_cents = :estimated, updated_at = now() WHERE id = :id"
)


async def get_run_budget_state(
    conn: AsyncConnection, project_run_id: ProjectRunId
) -> RunBudgetState | None:
    """The per-run spend / cap / estimate, or ``None`` if the project run does not exist."""
    row = (await conn.execute(_GET_RUN_BUDGET_SQL, {"id": project_run_id})).mappings().one_or_none()
    if row is None:
        return None
    return RunBudgetState(
        spent_cents=row["spent_cents"],
        cap_cents=row["budget_cap_cents"],
        estimated_cents=row["estimated_cents"],
    )


async def add_run_spend(
    conn: AsyncConnection, project_run_id: ProjectRunId, delta_cents: CostCents
) -> int:
    """Increment the run's live ``spent_cents`` by ``delta_cents`` (the per-charge accounting) and
    return the number of rows updated (0 if the run does not exist). The caller (the budget engine)
    raises on a 0-row update so a charge against a missing run can never silently vanish — the
    write-path analogue of ``check``'s fail-loud-on-missing-row guarantee."""
    result = await conn.execute(_ADD_RUN_SPEND_SQL, {"id": project_run_id, "delta": delta_cents})
    return result.rowcount


async def set_estimated_cents(
    conn: AsyncConnection, project_run_id: ProjectRunId, estimated_cents: CostCents
) -> None:
    """Persist the latest pre-run projection on the run (so ``burn_down`` shows spent-vs-estimate).
    Best-effort: a no-op if the run does not exist (a true pre-start estimate has no row yet)."""
    await conn.execute(_SET_ESTIMATED_SQL, {"id": project_run_id, "estimated": estimated_cents})


# --- account-scope counters / caps (account_run) ------------------------------------------------

_GET_ACCOUNT_BUDGET_SQL = text(
    "SELECT cost_cents, tier, budget_cap_cents FROM account_run WHERE id = :id"
)

_ADD_ACCOUNT_SPEND_SQL = text(
    "UPDATE account_run SET cost_cents = cost_cents + :delta, updated_at = now() WHERE id = :id"
)

_SET_ACCOUNT_CAP_SQL = text(
    "UPDATE account_run SET budget_cap_cents = :cap, updated_at = now() WHERE id = :id"
)


async def get_account_budget_state(
    conn: AsyncConnection, account_run_id: RunId
) -> AccountBudgetState | None:
    """The per-account spend / tier / cap, or ``None`` if the account run does not exist."""
    row = (
        (await conn.execute(_GET_ACCOUNT_BUDGET_SQL, {"id": account_run_id}))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return AccountBudgetState(
        cost_cents=row["cost_cents"],
        tier=row["tier"],
        budget_cap_cents=row["budget_cap_cents"],
    )


async def add_account_spend(
    conn: AsyncConnection, account_run_id: RunId, delta_cents: CostCents
) -> int:
    """Increment the account run's live ``cost_cents`` by ``delta_cents`` and return the rows
    updated (0 if the account run does not exist). The budget engine raises on a 0-row update so an
    account charge can never silently vanish."""
    result = await conn.execute(
        _ADD_ACCOUNT_SPEND_SQL, {"id": account_run_id, "delta": delta_cents}
    )
    return result.rowcount


async def set_account_budget_cap(
    conn: AsyncConnection, account_run_id: RunId, cap_cents: CostCents | None
) -> None:
    """Set (or clear, with ``None``) the per-account hard-cap override the engine's per-account
    ``check`` honours ahead of the per-tier policy band."""
    await conn.execute(_SET_ACCOUNT_CAP_SQL, {"id": account_run_id, "cap": cap_cents})


# --- row decoders -------------------------------------------------------------------------------


def _row_to_event(row: dict[str, object]) -> BudgetEventRow:
    # ``decode_jsonb`` is the one shared object-jsonb decoder (core.factories) — DRY, and more
    # robust than a local bytes-only copy (it also parses a ``str`` payload some drivers return).
    return BudgetEventRow.model_validate(
        {
            "id": row["id"],
            "seq": row["seq"],
            "project_run_id": row["project_run_id"],
            "scope": row["scope"],
            "kind": row["kind"],
            "projected_cents": row["projected_cents"],
            "cap_cents": row["cap_cents"],
            "detail": decode_jsonb(row["detail_json"]),
            "created_at": row["created_at"],
        }
    )
