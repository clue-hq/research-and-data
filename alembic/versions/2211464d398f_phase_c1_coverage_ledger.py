"""Phase C1 append-only coverage-attempt and decision ledgers.

Revision ID: 2211464d398f
Revises: b366c985ca12
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2211464d398f"
down_revision: str | None = "b366c985ca12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE research_attempt_outcome AS ENUM "
        "('claims_produced', 'no_hit', 'blocked', 'budget_stop', 'failed')"
    )
    op.execute(
        "CREATE TYPE research_terminal_status AS ENUM "
        "('filled', 'unfilled_terminal', 'blocked_by_policy', 'budget_exhausted')"
    )
    op.execute(
        """
        CREATE TABLE coverage_attempt (
            id uuid PRIMARY KEY,
            workspace_id text NOT NULL REFERENCES workspace (workspace_id),
            run_id uuid NOT NULL,
            project_run_id uuid,
            entity_id uuid NOT NULL,
            entity_type entity_type NOT NULL,
            field_key text NOT NULL,
            tier text NOT NULL,
            round integer NOT NULL,
            strategy_key text NOT NULL,
            source_family text,
            outcome research_attempt_outcome NOT NULL,
            stop_reason text NOT NULL,
            reason_detail text,
            cost_cents numeric NOT NULL DEFAULT 0,
            claim_refs_json jsonb NOT NULL DEFAULT '[]'::jsonb,
            quality_mode text,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT coverage_attempt_round_positive CHECK (round >= 1),
            CONSTRAINT coverage_attempt_cost_nonnegative CHECK (cost_cents >= 0),
            CONSTRAINT coverage_attempt_claim_refs_array
                CHECK (jsonb_typeof(claim_refs_json) = 'array'),
            CONSTRAINT coverage_attempt_natural_key UNIQUE
                (run_id, entity_id, field_key, tier, round, strategy_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE coverage_decision (
            id uuid PRIMARY KEY,
            workspace_id text NOT NULL REFERENCES workspace (workspace_id),
            run_id uuid NOT NULL,
            project_run_id uuid,
            entity_id uuid NOT NULL,
            entity_type entity_type NOT NULL,
            field_key text NOT NULL,
            tier text NOT NULL,
            round integer NOT NULL,
            terminal_status research_terminal_status,
            next_strategy_key text,
            reason_code text NOT NULL,
            reason_detail text NOT NULL,
            attempt_refs_json jsonb NOT NULL DEFAULT '[]'::jsonb,
            claim_refs_json jsonb NOT NULL DEFAULT '[]'::jsonb,
            judge_model text,
            judge_prompt_version text,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT coverage_decision_round_positive CHECK (round >= 1),
            CONSTRAINT coverage_decision_attempt_refs_array
                CHECK (jsonb_typeof(attempt_refs_json) = 'array'),
            CONSTRAINT coverage_decision_claim_refs_array
                CHECK (jsonb_typeof(claim_refs_json) = 'array'),
            CONSTRAINT coverage_decision_terminal_xor_next CHECK (
                (terminal_status IS NOT NULL AND next_strategy_key IS NULL)
                OR (terminal_status IS NULL AND next_strategy_key IS NOT NULL)
            ),
            CONSTRAINT coverage_decision_round_key UNIQUE
                (run_id, entity_id, field_key, tier, round)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX coverage_decision_one_terminal "
        "ON coverage_decision (run_id, entity_id, field_key, tier) "
        "WHERE terminal_status IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX coverage_attempt_scope "
        "ON coverage_attempt (workspace_id, run_id, entity_id, field_key, round)"
    )
    op.execute(
        "CREATE INDEX coverage_decision_scope "
        "ON coverage_decision (workspace_id, run_id, entity_id, field_key, round)"
    )
    op.execute(
        """
        CREATE FUNCTION coverage_reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'coverage ledgers are append-only (no % allowed)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("coverage_attempt", "coverage_decision"):
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION coverage_reject_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION coverage_reject_mutation()"
        )


def downgrade() -> None:
    for table in ("coverage_decision", "coverage_attempt"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update ON {table}")
    op.execute("DROP FUNCTION IF EXISTS coverage_reject_mutation()")
    op.execute("DROP INDEX IF EXISTS coverage_decision_scope")
    op.execute("DROP INDEX IF EXISTS coverage_attempt_scope")
    op.execute("DROP INDEX IF EXISTS coverage_decision_one_terminal")
    op.execute("DROP TABLE IF EXISTS coverage_decision")
    op.execute("DROP TABLE IF EXISTS coverage_attempt")
    op.execute("DROP TYPE IF EXISTS research_terminal_status")
    op.execute("DROP TYPE IF EXISTS research_attempt_outcome")
