"""c6_7 coverage evaluator advice

Revision ID: 6e30fac321bf
Revises: 6628a407e993
Create Date: 2026-07-26 11:30:45.906822+00:00

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6e30fac321bf"
down_revision: str | None = "6628a407e993"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE coverage_evaluator_advice (
            id uuid PRIMARY KEY,
            workspace_id text NOT NULL REFERENCES workspace (workspace_id),
            run_id uuid NOT NULL,
            project_run_id uuid,
            entity_id uuid NOT NULL,
            entity_type entity_type NOT NULL,
            tier text NOT NULL,
            round integer NOT NULL,
            proposal_kind text NOT NULL,
            planned_fields_json jsonb NOT NULL,
            result_json jsonb,
            valid boolean NOT NULL,
            answering_model text NOT NULL,
            prompt_version text NOT NULL,
            cost_cents numeric NOT NULL DEFAULT 0,
            non_authoritative boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT coverage_evaluator_advice_round_positive CHECK (round >= 1),
            CONSTRAINT coverage_evaluator_advice_kind
                CHECK (proposal_kind IN ('round_boundary', 'agent_stop_proposal')),
            CONSTRAINT coverage_evaluator_advice_fields_array
                CHECK (jsonb_typeof(planned_fields_json) = 'array'),
            CONSTRAINT coverage_evaluator_advice_result_object
                CHECK (result_json IS NULL OR jsonb_typeof(result_json) = 'object'),
            CONSTRAINT coverage_evaluator_advice_cost_nonnegative CHECK (cost_cents >= 0),
            CONSTRAINT coverage_evaluator_advice_non_authoritative CHECK (non_authoritative),
            CONSTRAINT coverage_evaluator_advice_natural_key UNIQUE
                (run_id, entity_id, tier, round, proposal_kind)
        )
        """
    )
    op.execute(
        "CREATE INDEX coverage_evaluator_advice_scope "
        "ON coverage_evaluator_advice (workspace_id, run_id, entity_id, round)"
    )
    op.execute(
        "ALTER TABLE coverage_decision ADD COLUMN evaluator_advice_id uuid "
        "REFERENCES coverage_evaluator_advice (id)"
    )
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER coverage_evaluator_advice_no_{operation.lower()} "
            f"BEFORE {operation} ON coverage_evaluator_advice "
            "FOR EACH ROW EXECUTE FUNCTION coverage_reject_mutation()"
        )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS coverage_evaluator_advice_no_delete ON coverage_evaluator_advice"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS coverage_evaluator_advice_no_update ON coverage_evaluator_advice"
    )
    op.execute("ALTER TABLE coverage_decision DROP COLUMN IF EXISTS evaluator_advice_id")
    op.execute("DROP INDEX IF EXISTS coverage_evaluator_advice_scope")
    op.execute("DROP TABLE IF EXISTS coverage_evaluator_advice")
