"""budget_engine M7.5 ENG-153

Revision ID: a6628f6432c6
Revises: df78df38b168
Create Date: 2026-06-21

The **cost-governance engine's data model** (Doc C §5; substrate §5c) — the durable backing for the
M7.5 :class:`clue_research.durable.budget.BudgetEngine`, the single chokepoint for spend
authorisation and the live cost accounting that feeds the client-facing surface (M13.4) and the
source-intelligence learning loop (M13.3 / Doc C §6). It adds three things to the M7 schema:

* the per-account hard cap column ``account_run.budget_cap_cents`` (M7.1's ``account_run`` already
  carries ``cost_cents`` = the per-account *spent*; this adds the optional per-row cap override that
  the engine's per-account ``check`` honours ahead of the per-tier policy band). ``campaign_run``
  (M7.3) already has both ``budget_cap_cents`` and ``spent_cents``, so the per-run scope needs no
  new column there;
* the latest pre-run projection ``campaign_run.estimated_cents`` so the burn-down surface can show
  *spent vs estimate vs cap* live (``estimate`` best-effort persists it; ``burn_down`` reads it);
  and
* the ``budget_event`` append-only governance audit — one row per governed spend decision
  (``check_deny`` / ``graceful_stop`` / ``breach_pending`` / ``cap_raised``). A *charge* is never an
  event: charges live on the M7.4 ledger's ``cost_cents_charged`` and the ``spent_cents`` counters,
  counted exactly once — so the burn-down ties to the ledger with no double-count.

``budget_event`` is **append-only** (like ``adjustment_journal``/``claim``): a governance decision
is an immutable fact, so any UPDATE/DELETE is a programming error rejected by a BEFORE trigger. Rows
appended in one transaction share ``created_at`` (the transaction timestamp), so the monotonic
``seq`` (GENERATED ALWAYS AS IDENTITY) is the only stable audit order — exactly the
``adjustment_journal`` lesson.

Enums: ``budget_scope`` mirrors the **core** :class:`clue_core.enums.BudgetScope` (the
cross-milestone scope vocabulary the ``BudgetEngine`` ``check``/``record`` exchange);
``budget_event_kind`` mirrors the **durable-internal**
:class:`clue_research.durable.enums.BudgetEventKind`. Both are parity-tested against their Python
sources in ``tests/durable/test_budget_db.py`` (the same ``StrEnum`` discipline as the other M7
enums).

Soft FK (no ``REFERENCES``, mirroring ``claim``/``account_run``/``campaign_run``):
``budget_event.campaign_run_id`` is not FK-referenced — integrity is enforced in the write path so
the migration stays order-independent. Chains off ``df78df38b168`` (M7.4 idempotency ledger), the
single M7 head.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6628f6432c6"
down_revision: str | None = "df78df38b168"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_core.enums.BudgetScope (a CORE enum — the shared scope vocabulary).
_BUDGET_SCOPE = ("account", "pass", "run")

# Mirror clue_research.durable.enums.BudgetEventKind (durable-internal governance audit).
_BUDGET_EVENT_KIND = ("check_deny", "graceful_stop", "breach_pending", "cap_raised")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE budget_scope AS ENUM ({_enum_values_sql(_BUDGET_SCOPE)})")
    op.execute(f"CREATE TYPE budget_event_kind AS ENUM ({_enum_values_sql(_BUDGET_EVENT_KIND)})")

    # --- per-account hard cap override (the engine's per-account check honours it first) ---------
    op.execute("ALTER TABLE account_run ADD COLUMN budget_cap_cents numeric")
    op.execute(
        "ALTER TABLE account_run ADD CONSTRAINT account_run_budget_cap_nonneg "
        "CHECK (budget_cap_cents IS NULL OR budget_cap_cents >= 0)"
    )
    op.execute(
        "COMMENT ON COLUMN account_run.budget_cap_cents IS 'Optional per-account hard cap (M7.5). "
        "When set, the budget engine''s per-account check uses it ahead of the per-tier policy "
        "band; NULL = fall back to the policy band (or no per-account cap).'"
    )

    # --- the latest pre-run projection (spent-vs-estimate-vs-cap burn-down) ----------------------
    op.execute("ALTER TABLE campaign_run ADD COLUMN estimated_cents numeric")
    op.execute(
        "ALTER TABLE campaign_run ADD CONSTRAINT campaign_run_estimated_nonneg "
        "CHECK (estimated_cents IS NULL OR estimated_cents >= 0)"
    )
    op.execute(
        "COMMENT ON COLUMN campaign_run.estimated_cents IS 'Latest pre-run projected spend (M7.5). "
        "estimate() best-effort persists it; burn_down() reads it for the spent-vs-estimate "
        "surface. NULL = never estimated.'"
    )

    # --- budget_event: append-only governance audit of spend decisions ---------------------------
    op.execute(
        """
        CREATE TABLE budget_event (
            id               uuid NOT NULL,
            seq              bigint GENERATED ALWAYS AS IDENTITY,
            campaign_run_id  uuid NOT NULL,
            scope            budget_scope NOT NULL,
            kind             budget_event_kind NOT NULL,
            projected_cents  numeric NOT NULL DEFAULT 0,
            cap_cents        numeric,
            detail_json      jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT budget_event_pkey PRIMARY KEY (id),
            CONSTRAINT budget_event_projected_nonneg CHECK (projected_cents >= 0),
            CONSTRAINT budget_event_cap_nonneg CHECK (cap_cents IS NULL OR cap_cents >= 0),
            CONSTRAINT budget_event_detail_is_object CHECK (jsonb_typeof(detail_json) = 'object'),
            -- The engine's taxonomy (durable.enums.BudgetEventKind): check_deny is a per-account /
            -- per-pass denial; graceful_stop / breach_pending / cap_raised are run-scoped. The
            -- audit table is append-only (a bad row can't be UPDATE'd out) and M13 reads it, so the
            -- DB — not just the (sole) engine writer — refuses an impossible (scope, kind) pairing.
            CONSTRAINT budget_event_kind_scope CHECK (
                (kind = 'check_deny' AND scope IN ('account', 'pass'))
                OR (kind IN ('graceful_stop', 'breach_pending', 'cap_raised') AND scope = 'run')
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE budget_event IS 'Append-only governance audit of budget decisions "
        "(M7.5; Doc C §5): check_deny / graceful_stop / breach_pending / cap_raised. A charge is "
        "NOT an event (charges live on the M7.4 ledger + spent_cents counters). Immutable (reject "
        "trigger). Ordered by the monotonic seq, not created_at (which ties within a transaction).'"
    )
    # Ordered read by the monotonic ``seq``: rows appended in one transaction share ``created_at``
    # (= the transaction timestamp), so ``seq`` is the only stable audit order.
    op.execute("CREATE INDEX budget_event_run ON budget_event (campaign_run_id, seq)")

    # Append-only guard (mirrors the claim / adjustment_journal tables): a governance decision is
    # an immutable fact, so any UPDATE or DELETE is a programming error and is rejected at the DB.
    op.execute(
        """
        CREATE FUNCTION budget_event_reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'budget_event is append-only (no % allowed)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER budget_event_no_update BEFORE UPDATE ON budget_event "
        "FOR EACH ROW EXECUTE FUNCTION budget_event_reject_mutation()"
    )
    op.execute(
        "CREATE TRIGGER budget_event_no_delete BEFORE DELETE ON budget_event "
        "FOR EACH ROW EXECUTE FUNCTION budget_event_reject_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS budget_event_no_delete ON budget_event")
    op.execute("DROP TRIGGER IF EXISTS budget_event_no_update ON budget_event")
    op.execute("DROP FUNCTION IF EXISTS budget_event_reject_mutation()")
    op.execute("DROP INDEX IF EXISTS budget_event_run")
    op.execute("DROP TABLE IF EXISTS budget_event")

    op.execute("ALTER TABLE campaign_run DROP CONSTRAINT IF EXISTS campaign_run_estimated_nonneg")
    op.execute("ALTER TABLE campaign_run DROP COLUMN IF EXISTS estimated_cents")

    op.execute("ALTER TABLE account_run DROP CONSTRAINT IF EXISTS account_run_budget_cap_nonneg")
    op.execute("ALTER TABLE account_run DROP COLUMN IF EXISTS budget_cap_cents")

    op.execute("DROP TYPE IF EXISTS budget_event_kind")
    op.execute("DROP TYPE IF EXISTS budget_scope")
