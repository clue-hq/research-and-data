"""C5.5 run-local supervisor telemetry and replay identity.

Revision ID: ed7a01cd8845
Revises: d9b39fb407ed
Create Date: 2026-07-25 08:09:56.978645+00:00

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
revision: str = "ed7a01cd8845"
down_revision: str | None = "d9b39fb407ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A control tool may commit its domain event and die before its invocation journal completion
    # lands.  The operation identity makes that retry converge on the same event instead of
    # appending a second state transition.  The column is nullable only for compatibility with
    # any rows written while the C5.1 tables were dormant; every C5.5 writer requires it.
    op.execute("ALTER TABLE run_control_event ADD COLUMN operation_id uuid")
    op.execute(
        "CREATE UNIQUE INDEX run_control_event_operation "
        "ON run_control_event (execution_id, operation_id) "
        "WHERE operation_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX supervisor_observation_execution_created "
        "ON supervisor_observation (execution_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX supervisor_observation_project_run_created "
        "ON supervisor_observation (project_run_id, created_at DESC) "
        "WHERE project_run_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX supervisor_diagnosis_one_per_observation "
        "ON supervisor_diagnosis (observation_id)"
    )

    # The pre-existing source_yield table is deliberately workspace/ICP lifetime learning data.
    # C5.5 needs a distinct execution-scoped ledger for a canary: every row is one provider
    # boundary outcome, including hard failures and empty results that produced no claim row.
    op.execute(
        """
        CREATE TABLE source_call_observation (
            id                uuid PRIMARY KEY,
            execution_id      uuid NOT NULL,
            workspace_id      text NOT NULL,
            project_run_id    uuid NOT NULL,
            project_id        text NOT NULL,
            account_entity_id uuid NOT NULL,
            account_run_id    uuid NOT NULL,
            field_key         text NOT NULL,
            source_key        text NOT NULL,
            outcome           text NOT NULL,
            error_code        text,
            claims_count      int NOT NULL DEFAULT 0,
            cost_cents        numeric NOT NULL DEFAULT 0,
            latency_ms        double precision NOT NULL DEFAULT 0,
            created_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT source_call_observation_execution_fk
                FOREIGN KEY (execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT source_call_observation_project_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT source_call_observation_source_fk
                FOREIGN KEY (source_key) REFERENCES source_manifest (source_key),
            CONSTRAINT source_call_observation_outcome CHECK (
                outcome IN ('claims_produced', 'empty', 'failed')
            ),
            CONSTRAINT source_call_observation_error_shape CHECK (
                (outcome = 'failed' AND error_code IS NOT NULL)
                OR (outcome <> 'failed' AND error_code IS NULL)
            ),
            CONSTRAINT source_call_observation_claims_nonnegative CHECK (claims_count >= 0),
            CONSTRAINT source_call_observation_cost_nonnegative CHECK (cost_cents >= 0),
            CONSTRAINT source_call_observation_latency_nonnegative CHECK (latency_ms >= 0),
            CONSTRAINT source_call_observation_identity_nonempty CHECK (
                length(btrim(field_key)) > 0
                AND length(btrim(source_key)) > 0
                AND (error_code IS NULL OR length(btrim(error_code)) > 0)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX source_call_observation_execution_source_created "
        "ON source_call_observation (execution_id, source_key, created_at)"
    )
    op.execute(
        "CREATE INDEX source_call_observation_execution_account_created "
        "ON source_call_observation (execution_id, account_entity_id, created_at)"
    )
    op.execute(
        "CREATE TRIGGER source_call_observation_append_only "
        "BEFORE UPDATE OR DELETE ON source_call_observation "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )

    # C1 originally read by account-run id.  The supervisor's canary read is project-run scoped.
    op.execute(
        "CREATE INDEX coverage_attempt_project_run_created "
        "ON coverage_attempt (workspace_id, project_run_id, created_at) "
        "WHERE project_run_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX coverage_decision_project_run_created "
        "ON coverage_decision (workspace_id, project_run_id, created_at) "
        "WHERE project_run_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS coverage_decision_project_run_created")
    op.execute("DROP INDEX IF EXISTS coverage_attempt_project_run_created")
    op.execute(
        "DROP TRIGGER IF EXISTS source_call_observation_append_only ON source_call_observation"
    )
    op.execute("DROP INDEX IF EXISTS source_call_observation_execution_account_created")
    op.execute("DROP INDEX IF EXISTS source_call_observation_execution_source_created")
    op.execute("DROP TABLE IF EXISTS source_call_observation")
    op.execute("DROP INDEX IF EXISTS supervisor_diagnosis_one_per_observation")
    op.execute("DROP INDEX IF EXISTS supervisor_observation_project_run_created")
    op.execute("DROP INDEX IF EXISTS supervisor_observation_execution_created")
    op.execute("DROP INDEX IF EXISTS run_control_event_operation")
    op.execute("ALTER TABLE run_control_event DROP COLUMN IF EXISTS operation_id")
