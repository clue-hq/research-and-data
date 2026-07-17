"""campaign_run state machine (M7.3 / ENG-141)

Revision ID: ce08f0be1c20
Revises: 79d56a0f4425
Create Date: 2026-06-21

The **outer durable-execution state machine** (Doc C §4; substrate §5c) — the long-lived campaign
job that spans ``reverse_profiling → icp_confirmed → discovery → scoring → tier_checkpoint → deep →
verification → handoff``. M7.1's ``account_run`` is the *inner* per-account cursor; this migration
adds the *outer* tables the campaign-run state machine owns:

* ``campaign_run`` — one row per campaign job. Mutable workflow state (``phase``/``status``/
  ``spent_cents``/``tier_cutoffs_json`` change as the run advances), so — like ``account_run`` — it
  is deliberately **not** append-only (the claim store keeps immutable history; this is the
  resumable execution cursor over it). ``account_run.campaign_run_id`` is a soft FK back to it.
* ``campaign_phase_checkpoint`` — the per-phase durable record the run commits each phase transition
  into, **UNIQUE on ``(campaign_run_id, phase)``** (the frozen ``(campaign_run, phase)`` idempotency
  shape — :func:`clue_core.idempotency.phase_key`). ``payload_json`` carries the phase
  handler's :class:`~clue_core.PhaseResult` payload by reference — and is the **M6↔M7
  hand-off surface**: M6.4's ``tier_checkpoint`` handler persists its review payload (proposed
  cutoffs, tier distribution, cost estimate, decision) here via ``payload_json`` with a read-back,
  so M6 needs **no** bespoke ``tier_checkpoint`` table (telemetry-ownership agreement). ``status``
  distinguishes a crash-resumable ``in_progress``, the durable human/budget gate ``awaiting_input``,
  the committed-and-done ``committed``, and a ``failed`` phase.
* ``adjustment_journal`` — an **append-only** audit log of client-driven ``adjust`` actions (ICP
  re-version, budget-cap change, tier-cutoff edit). The M7.3 spec lists an illustrative
  ``adjustments_json[]`` column on ``campaign_run``; this normalizes it into a journal table (one
  source of truth, immutable audit) — "adjustments are journaled" (spec). Guarded append-only by a
  BEFORE UPDATE/DELETE reject trigger, mirroring the ``claim`` table (0002).

Soft FKs (no ``REFERENCES``, mirroring ``claim``/``account_run`` 0002/M7.1): ``campaign_run`` is not
FK-referenced by ``account_run`` at the DB level (integrity is enforced in the write path) so the
two M7 migrations stay order-independent.

Enums: ``campaign_phase`` mirrors the **core** :class:`clue_core.enums.CampaignPhase` (the
cross-milestone phase vocabulary — every phase handler shares it); ``campaign_run_status`` and
``phase_checkpoint_status`` are **durable-internal** lifecycle enums mirrored from
:mod:`clue_research.durable.enums`. All three are parity-tested against their Python sources in
``tests/durable/test_campaign_run_db.py`` (the same ``StrEnum`` discipline as the account-run enum).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ce08f0be1c20"
down_revision: str | None = "79d56a0f4425"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_core.enums.CampaignPhase (a CORE enum — the shared phase vocabulary). The
# parity test in tests/durable/ guards against drift, and obs.CAMPAIGN_PHASES derives from the same
# source, so the span tokens, the state-machine enum, and this DB enum cannot diverge.
_CAMPAIGN_PHASE = (
    "reverse_profiling",
    "icp_confirmed",
    "discovery",
    "scoring",
    "tier_checkpoint",
    "deep",
    "verification",
    "handoff",
)

# Mirror clue_research.durable.enums.CampaignRunStatus (durable-internal lifecycle).
_CAMPAIGN_RUN_STATUS = ("active", "paused", "completed", "failed")

# Mirror clue_research.durable.enums.PhaseCheckpointStatus (durable-internal lifecycle).
_PHASE_CHECKPOINT_STATUS = ("in_progress", "awaiting_input", "committed", "failed")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE campaign_phase AS ENUM ({_enum_values_sql(_CAMPAIGN_PHASE)})")
    op.execute(
        f"CREATE TYPE campaign_run_status AS ENUM ({_enum_values_sql(_CAMPAIGN_RUN_STATUS)})"
    )
    op.execute(
        "CREATE TYPE phase_checkpoint_status AS ENUM "
        f"({_enum_values_sql(_PHASE_CHECKPOINT_STATUS)})"
    )

    # --- campaign_run: the outer durable job -------------------------------------------------
    op.execute(
        """
        CREATE TABLE campaign_run (
            id                uuid NOT NULL,
            client_id         text NOT NULL,
            icp_key           text NOT NULL,
            icp_version       integer NOT NULL,
            phase             campaign_phase NOT NULL DEFAULT 'reverse_profiling',
            status            campaign_run_status NOT NULL DEFAULT 'active',
            budget_cap_cents  numeric,
            spent_cents       numeric NOT NULL DEFAULT 0,
            tier_cutoffs_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            paused_at         timestamptz,
            resumed_at        timestamptz,
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT campaign_run_pkey PRIMARY KEY (id),
            CONSTRAINT campaign_run_icp_version_positive CHECK (icp_version >= 1),
            CONSTRAINT campaign_run_spent_nonneg CHECK (spent_cents >= 0),
            CONSTRAINT campaign_run_cap_nonneg
                CHECK (budget_cap_cents IS NULL OR budget_cap_cents >= 0),
            CONSTRAINT campaign_run_cutoffs_is_object
                CHECK (jsonb_typeof(tier_cutoffs_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE campaign_run IS 'Outer campaign-run state machine (Doc C §4; M7.3). "
        "Mutable, resumable execution cursor over the phase sequence; account_run.campaign_run_id "
        "is a soft FK to it.'"
    )
    # Hot read: all runs for a client (the client-facing run list / cost surface).
    op.execute("CREATE INDEX campaign_run_client ON campaign_run (client_id)")

    # --- campaign_phase_checkpoint: the per-phase durable record ------------------------------
    op.execute(
        """
        CREATE TABLE campaign_phase_checkpoint (
            id               uuid NOT NULL,
            campaign_run_id  uuid NOT NULL,
            phase            campaign_phase NOT NULL,
            idempotency_key  text NOT NULL,
            status           phase_checkpoint_status NOT NULL DEFAULT 'in_progress',
            payload_json     jsonb NOT NULL DEFAULT '{}'::jsonb,
            committed_at     timestamptz,
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT campaign_phase_checkpoint_pkey PRIMARY KEY (id),
            -- The frozen (campaign_run, phase) idempotency shape: at most one checkpoint per phase
            -- of a run, so a re-entered phase deduplicates onto the same row (M7.4 keys on this).
            CONSTRAINT campaign_phase_checkpoint_run_phase UNIQUE (campaign_run_id, phase),
            CONSTRAINT campaign_phase_checkpoint_payload_is_object
                CHECK (jsonb_typeof(payload_json) = 'object'),
            -- A committed checkpoint must stamp when it committed (and only a committed one may).
            CONSTRAINT campaign_phase_checkpoint_committed_at_iff_committed
                CHECK ((status = 'committed') = (committed_at IS NOT NULL))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE campaign_phase_checkpoint IS 'Per-phase durable record (M7.3). "
        "UNIQUE(campaign_run_id, phase) = the (campaign_run, phase) idempotency shape; "
        "payload_json carries PhaseResult.payload (incl. M6.4 tier-checkpoint review payload "
        "— read-back surface, no bespoke tier table).'"
    )
    op.execute(
        "CREATE INDEX campaign_phase_checkpoint_run ON campaign_phase_checkpoint (campaign_run_id)"
    )

    # --- adjustment_journal: append-only audit of client adjust actions ----------------------
    op.execute(
        """
        CREATE TABLE adjustment_journal (
            id               uuid NOT NULL,
            seq              bigint GENERATED ALWAYS AS IDENTITY,
            campaign_run_id  uuid NOT NULL,
            kind             text NOT NULL,
            detail_json      jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT adjustment_journal_pkey PRIMARY KEY (id),
            CONSTRAINT adjustment_journal_detail_is_object
                CHECK (jsonb_typeof(detail_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE adjustment_journal IS 'Append-only audit of client adjust actions "
        "(M7.3): ICP re-version, budget-cap change, tier-cutoff edit. Immutable (reject trigger). "
        "Ordered by the monotonic seq, not created_at (which ties within a transaction).'"
    )
    # Ordered read by the monotonic ``seq``: rows appended in one transaction share ``created_at``
    # (= the transaction timestamp), so ``seq`` is the only stable audit order.
    op.execute("CREATE INDEX adjustment_journal_run ON adjustment_journal (campaign_run_id, seq)")

    # Append-only guard (mirrors the claim table, 0002): the journal is an immutable audit log, so
    # any UPDATE or DELETE is a programming error and is rejected at the database.
    op.execute(
        """
        CREATE FUNCTION adjustment_journal_reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'adjustment_journal is append-only (no % allowed)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER adjustment_journal_no_update BEFORE UPDATE ON adjustment_journal "
        "FOR EACH ROW EXECUTE FUNCTION adjustment_journal_reject_mutation()"
    )
    op.execute(
        "CREATE TRIGGER adjustment_journal_no_delete BEFORE DELETE ON adjustment_journal "
        "FOR EACH ROW EXECUTE FUNCTION adjustment_journal_reject_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS adjustment_journal_no_delete ON adjustment_journal")
    op.execute("DROP TRIGGER IF EXISTS adjustment_journal_no_update ON adjustment_journal")
    op.execute("DROP FUNCTION IF EXISTS adjustment_journal_reject_mutation()")
    op.execute("DROP INDEX IF EXISTS adjustment_journal_run")
    op.execute("DROP TABLE IF EXISTS adjustment_journal")

    op.execute("DROP INDEX IF EXISTS campaign_phase_checkpoint_run")
    op.execute("DROP TABLE IF EXISTS campaign_phase_checkpoint")

    op.execute("DROP INDEX IF EXISTS campaign_run_client")
    op.execute("DROP TABLE IF EXISTS campaign_run")

    op.execute("DROP TYPE IF EXISTS phase_checkpoint_status")
    op.execute("DROP TYPE IF EXISTS campaign_run_status")
    op.execute("DROP TYPE IF EXISTS campaign_phase")
