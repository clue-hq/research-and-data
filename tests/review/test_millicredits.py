"""PB-B2.6 — millicredit rate mapping + pure read path (additive-only over the M13.4 surface).

Pure tests: exact Decimal conversion (no float), rounding at the millicredit grain, the
burn-down view equals the cents panel converted. DB tests: workspace override beats the global
default, version/tie-break determinism, and the ``NULLS NOT DISTINCT`` global-slot uniqueness
(the M9.1 gap, closed up front here).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from clue_research.review import (
    CostBurnDown,
    MillicreditRate,
    insert_millicredit_rate,
    load_millicredit_rate,
    to_millicredit_burn_down,
    to_millicredits,
)
from tests.review.conftest import rollback_conn, run_async


def _rate(cents_per_credit: str = "100", version: int = 1) -> MillicreditRate:
    from datetime import UTC, datetime

    return MillicreditRate(
        rate_id="r1",
        workspace_id=None,
        version=version,
        cents_per_credit=Decimal(cents_per_credit),
        created_at=datetime.now(UTC),
    )


# --- pure conversion ----------------------------------------------------------


def test_conversion_is_exact_decimal() -> None:
    rate = _rate("100")  # $1 per credit
    assert to_millicredits(Decimal(100), rate) == 1000  # 1 credit
    assert to_millicredits(Decimal(1), rate) == 10  # 1 cent = 10 millicredits
    assert to_millicredits(Decimal(0), rate) == 0
    assert to_millicredits(Decimal("0.05"), rate) == 1  # rounds half-up at the grain
    assert to_millicredits(Decimal("0.04"), rate) == 0


def test_conversion_with_non_round_rate() -> None:
    rate = _rate("250")  # $2.50 per credit
    assert to_millicredits(Decimal(250), rate) == 1000
    assert to_millicredits(Decimal(125), rate) == 500
    # 1 cent @ 250 cents/credit = 4 millicredits exactly — no float drift
    assert to_millicredits(Decimal(1), rate) == 4


def test_burn_down_view_equals_cents_converted() -> None:
    rate = _rate("100")
    panel = CostBurnDown(
        campaign_run_id="11111111-1111-1111-1111-111111111111",
        spent_cents=Decimal(250),
        estimated_cents=Decimal(400),
        cap_cents=Decimal(1000),
        remaining_cents=Decimal(750),
        status="ok",
        over_cap=False,
        has_cap=True,
    )
    view = to_millicredit_burn_down(panel, rate)
    assert view.spent_millicredits == 2500
    assert view.estimated_millicredits == 4000
    assert view.cap_millicredits == 10000
    assert view.remaining_millicredits == 7500
    assert view.status == "ok" and view.has_cap and not view.over_cap
    assert view.rate_version == 1 and view.cents_per_credit == Decimal(100)


# --- the loader (DB) ----------------------------------------------------------

pytestmark = pytest.mark.usefixtures("require_review_db")


def test_workspace_override_beats_global_default() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await insert_millicredit_rate(conn, cents_per_credit=Decimal(100))  # global v1
            await insert_millicredit_rate(
                conn, cents_per_credit=Decimal(80), workspace_id="ws_a", version=1
            )
            effective = await load_millicredit_rate(conn, "ws_a")
            assert effective is not None and effective.cents_per_credit == Decimal(80)
            other = await load_millicredit_rate(conn, "ws_b")  # no override → global
            assert other is not None and other.cents_per_credit == Decimal(100)
            assert await load_millicredit_rate(conn) is not None  # global read

    run_async(scenario())


def test_latest_version_wins() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await insert_millicredit_rate(conn, cents_per_credit=Decimal(100), version=1)
            await insert_millicredit_rate(conn, cents_per_credit=Decimal(90), version=2)
            effective = await load_millicredit_rate(conn)
            assert effective is not None
            assert effective.version == 2 and effective.cents_per_credit == Decimal(90)

    run_async(scenario())


def test_global_null_slot_is_unique() -> None:
    """NULLS NOT DISTINCT: a duplicate (NULL, version) global row is impossible — the M9.1
    pre_spend_policy gap, not repeated here."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await insert_millicredit_rate(conn, cents_per_credit=Decimal(100), version=1)
            with pytest.raises(IntegrityError, match="millicredit_rate_scope_version"):
                await insert_millicredit_rate(conn, cents_per_credit=Decimal(120), version=1)

    run_async(scenario())


def test_no_rate_configured_returns_none() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            assert await load_millicredit_rate(conn, "ws_none") is None

    run_async(scenario())
