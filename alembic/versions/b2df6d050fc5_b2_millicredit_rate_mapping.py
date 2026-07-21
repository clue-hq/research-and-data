"""B2 — the ``millicredit_rate`` mapping table (PB-B2.6 / harness A7 groundwork)

Revision ID: b2df6d050fc5
Revises: d091e3962833
Create Date: 2026-07-21

Millicredit groundwork, **additive-only** (founder-ratified, PB-B2 ruling 3): the client-facing
integer-millicredit layer (harness A7) will eventually sit over the M13.4 USD cost ledger; B2
lays only the versioned **rate mapping** (how many USD cents one credit costs, per workspace with
a global default) and a pure read path (``review/millicredits.py``). **Zero changes** to
``durable/budget.py``, ``budget_event``, ``cost_estimate``, or the ``campaign_run`` counters —
the full ledger (debit/credit/hold, 402 semantics) is deliberately NOT guessed at here.

``UNIQUE NULLS NOT DISTINCT (workspace_id, version)`` closes the global-NULL-slot duplicate gap
up front (the M9.1 ``pre_spend_policy`` lesson, backlog M9.1×M0.4): two same-version global rows
are impossible, and the loader still tie-breaks deterministically.

Hand-written and reversible (up → down → up via ``make db-smoke``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2df6d050fc5"
down_revision: str | None = "d091e3962833"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # cents_per_credit is numeric (exact Decimal — money is never float); 1 credit = 1000
    # millicredits, so the conversion is pure arithmetic in review/millicredits.py.
    op.execute(
        """
        CREATE TABLE millicredit_rate (
            rate_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id     text,
            version          int NOT NULL,
            cents_per_credit numeric NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT millicredit_rate_version_pos CHECK (version >= 1),
            CONSTRAINT millicredit_rate_cents_per_credit_pos CHECK (cents_per_credit > 0),
            CONSTRAINT millicredit_rate_scope_version
                UNIQUE NULLS NOT DISTINCT (workspace_id, version)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE millicredit_rate IS 'Versioned USD-cents→credit rate (PB-B2.6, harness "
        "A7 groundwork): workspace_id NULL = the global default; a workspace row overrides it. "
        "Read by review/millicredits.py to express the M13.4 cost burn-down in integer "
        "millicredits (1 credit = 1000 millicredits). Additive-only over the cost ledger — no "
        "ledger/counter changes.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE millicredit_rate")
