"""Millicredit groundwork — the rate mapping + pure read path over the M13.4 cost surface
(PB-B2.6).

The eventual client-facing credit system (harness A7: integer millicredits, debit/credit/hold,
402 semantics) sits *over* the USD cost ledger. B2 lays only the groundwork the founder ratified
(PB-B2 ruling 3): a versioned ``millicredit_rate`` mapping (USD cents per credit, workspace
override → global default) and a **pure conversion** that re-expresses the existing
:class:`~clue_research.review.observability.CostBurnDown` in integer millicredits. Nothing here
touches ``durable/budget.py``, ``budget_event``, or any counter — it is a view, not a ledger.

Money in is exact ``Decimal`` cents (:class:`~clue_core.CostCents`); credits out are **integers**
(1 credit = ``cents_per_credit`` cents = 1000 millicredits; ROUND_HALF_UP at the millicredit
grain). No float ever enters the arithmetic.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import CostCents, UtcDatetime
from clue_research.review.observability import CostBurnDown

# 1 credit = 1000 millicredits — the A7 display/billing grain.
MILLICREDITS_PER_CREDIT = Decimal(1000)


class MillicreditRate(BaseModel):
    """One ``millicredit_rate`` row: how many USD cents one credit costs, versioned per scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rate_id: str
    workspace_id: str | None = None  # None = the global default rate
    version: int
    cents_per_credit: Decimal
    created_at: UtcDatetime


class MillicreditBurnDown(BaseModel):
    """The M13.4 cost burn-down panel re-expressed in integer millicredits (a pure view —
    the authoritative money numbers stay on the underlying :class:`CostBurnDown`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_run_id: str
    spent_millicredits: int
    estimated_millicredits: int
    cap_millicredits: int
    remaining_millicredits: int
    status: str
    over_cap: bool
    has_cap: bool
    rate_version: int
    cents_per_credit: Decimal


async def insert_millicredit_rate(
    conn: AsyncConnection,
    *,
    cents_per_credit: Decimal,
    workspace_id: str | None = None,
    version: int = 1,
) -> MillicreditRate:
    """Insert one rate row (config seeding / tests). A duplicate ``(scope, version)`` — including
    the global NULL scope, ``NULLS NOT DISTINCT`` — raises ``IntegrityError``: rates are
    append-a-new-version, never overwrite."""
    result = await conn.execute(
        text(
            "INSERT INTO millicredit_rate (workspace_id, version, cents_per_credit) "
            "VALUES (:workspace_id, :version, :cents_per_credit) "
            "RETURNING rate_id, workspace_id, version, cents_per_credit, created_at"
        ),
        {
            "workspace_id": workspace_id,
            "version": version,
            "cents_per_credit": cents_per_credit,
        },
    )
    row = dict(result.mappings().one())
    row["rate_id"] = str(row["rate_id"])
    return MillicreditRate(**row)


async def load_millicredit_rate(
    conn: AsyncConnection, workspace_id: str | None = None
) -> MillicreditRate | None:
    """The effective rate for a workspace: its own latest row, else the latest global default.

    Deterministic ordering (the M9.3 loader discipline): workspace override beats global, then
    highest ``version``, then ``created_at``/``rate_id`` as tie-breaks — so the answer can never
    depend on row arrival order. ``None`` when no rate is configured (the caller decides whether
    that means "credits not enabled" — this read path never invents a price).
    """
    result = await conn.execute(
        text(
            "SELECT rate_id, workspace_id, version, cents_per_credit, created_at "
            "FROM millicredit_rate "
            "WHERE workspace_id = :workspace_id OR workspace_id IS NULL "
            "ORDER BY (workspace_id IS NOT NULL) DESC, version DESC, created_at DESC, rate_id DESC "
            "LIMIT 1"
        ),
        {"workspace_id": workspace_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    data = dict(row)
    data["rate_id"] = str(data["rate_id"])
    return MillicreditRate(**data)


def to_millicredits(cents: CostCents, rate: MillicreditRate) -> int:
    """Exact ``Decimal`` conversion: cents → integer millicredits (ROUND_HALF_UP at the
    millicredit grain). ``100 cents @ cents_per_credit=100`` → 1 credit → 1000 millicredits."""
    millicredits = (Decimal(cents) / rate.cents_per_credit) * MILLICREDITS_PER_CREDIT
    return int(millicredits.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_millicredit_burn_down(burndown: CostBurnDown, rate: MillicreditRate) -> MillicreditBurnDown:
    """Re-express the M13.4 burn-down in millicredits — a pure view over the panel the
    ``CostBurnDownReader`` already serves; the cents figures stay authoritative."""
    return MillicreditBurnDown(
        campaign_run_id=str(burndown.campaign_run_id),
        spent_millicredits=to_millicredits(burndown.spent_cents, rate),
        estimated_millicredits=to_millicredits(burndown.estimated_cents, rate),
        cap_millicredits=to_millicredits(burndown.cap_cents, rate),
        remaining_millicredits=to_millicredits(burndown.remaining_cents, rate),
        status=burndown.status,
        over_cap=burndown.over_cap,
        has_cap=burndown.has_cap,
        rate_version=rate.version,
        cents_per_credit=rate.cents_per_credit,
    )
