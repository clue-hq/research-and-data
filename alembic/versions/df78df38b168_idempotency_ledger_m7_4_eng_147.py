"""idempotency_ledger (M7.4 / ENG-147)

Revision ID: df78df38b168
Revises: ce08f0be1c20
Create Date: 2026-06-21

The **two-level idempotency ledger** (substrate §5c; Doc C §4) — the single durable record of what
a keyed unit of work has already done, so a retry or crash-resume never double-charges a paid
resolver, never double-writes a claim, and a re-entered phase never double-spends. M7.1's
``account_run`` is the inner cursor and M7.3's ``campaign_phase_checkpoint`` is the per-phase
record; this table sits *in front of the write path* for both idempotency shapes:

* a per-account research **step** keyed ``(account_run, entity, field, tier)``
  (:func:`clue_core.idempotency.account_step_key`), and
* a campaign **phase** keyed ``(campaign_run, phase)``
  (:func:`clue_core.idempotency.phase_key`).

One row per derived ``key`` (PK = the spec's "unique-constrained on ``(key)``"). A step/phase
consults the ledger before executing: ``succeeded`` → return the recorded ``result_ref`` without
re-spending; ``in_progress`` and not stale → a live duplicate (skip/join); absent / ``failed`` /
stale-``in_progress`` → execute and record. ``cost_cents_charged`` is the single source of truth for
what the step actually charged, so M7.5's burn-down counts each spend exactly once.

Unlike ``adjustment_journal``/``claim`` this table is **not** append-only — a row legitimately
transitions ``in_progress → succeeded`` / ``→ failed`` (and a ``failed`` / stale row is re-owned
back to ``in_progress``), exactly like ``account_run``/``campaign_run`` execution state. So there is
no reject trigger; the status lifecycle is guarded by a CHECK and by the repository's atomic claim
upsert.

Enums: ``idempotency_scope`` mirrors the **core** :class:`clue_core.enums.IdempotencyScope`
(the cross-milestone key-shape vocabulary); ``idempotency_status`` mirrors the durable-internal
:class:`clue_research.durable.enums.IdempotencyStatus`. Both are parity-tested against their Python
sources in ``tests/durable/test_idempotency_db.py`` (the same ``StrEnum`` discipline as the other M7
enums).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "df78df38b168"
down_revision: str | None = "ce08f0be1c20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_core.enums.IdempotencyScope (a CORE enum — the shared key-shape vocabulary).
_IDEMPOTENCY_SCOPE = ("account_step", "campaign_phase")

# Mirror clue_research.durable.enums.IdempotencyStatus (durable-internal lifecycle).
_IDEMPOTENCY_STATUS = ("in_progress", "succeeded", "failed")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE idempotency_scope AS ENUM ({_enum_values_sql(_IDEMPOTENCY_SCOPE)})")
    op.execute(f"CREATE TYPE idempotency_status AS ENUM ({_enum_values_sql(_IDEMPOTENCY_STATUS)})")

    # --- idempotency_ledger: the exactly-once gate in front of the write path --------------------
    op.execute(
        """
        CREATE TABLE idempotency_ledger (
            key                text NOT NULL,
            scope              idempotency_scope NOT NULL,
            status             idempotency_status NOT NULL DEFAULT 'in_progress',
            result_ref         jsonb NOT NULL DEFAULT '{}'::jsonb,
            cost_cents_charged numeric NOT NULL DEFAULT 0,
            first_seen_at      timestamptz NOT NULL DEFAULT now(),
            completed_at       timestamptz,
            updated_at         timestamptz NOT NULL DEFAULT now(),

            -- The spec's "unique-constrained on (key)": one ledger row per derived key, so a
            -- retried step / re-entered phase deduplicates onto exactly this row.
            CONSTRAINT idempotency_ledger_pkey PRIMARY KEY (key),
            CONSTRAINT idempotency_ledger_result_ref_is_object
                CHECK (jsonb_typeof(result_ref) = 'object'),
            CONSTRAINT idempotency_ledger_cost_nonneg CHECK (cost_cents_charged >= 0),
            -- A succeeded step must stamp when it completed (and only a succeeded one may): the
            -- terminal-success marker the ledger short-circuits on. A failed / in_progress row
            -- keeps completed_at NULL (it is re-executable), mirroring campaign_phase_checkpoint's
            -- committed_at-iff-committed invariant.
            CONSTRAINT idempotency_ledger_completed_at_iff_succeeded
                CHECK ((status = 'succeeded') = (completed_at IS NOT NULL))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE idempotency_ledger IS 'Two-level idempotency ledger (M7.4; substrate §5c "
        "/ Doc C §4). One row per derived key (account_step / campaign_phase); the exactly-once "
        "gate in front of the claim write path. cost_cents_charged is the single charge record "
        "M7.5 counts once. Not append-only: status transitions in_progress<->succeeded/failed.'"
    )
    # Stale-in_progress recovery sweep: an in_progress row whose holder crashed is re-owned after a
    # staleness window. The partial index keeps that scan over only the in-flight rows.
    op.execute(
        "CREATE INDEX idempotency_ledger_inflight ON idempotency_ledger (first_seen_at) "
        "WHERE status = 'in_progress'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idempotency_ledger_inflight")
    op.execute("DROP TABLE IF EXISTS idempotency_ledger")
    op.execute("DROP TYPE IF EXISTS idempotency_status")
    op.execute("DROP TYPE IF EXISTS idempotency_scope")
