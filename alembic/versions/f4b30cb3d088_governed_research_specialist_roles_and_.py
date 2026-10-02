"""Governed research specialists, explicit spending policy and shared job allowances.

Revision ID: f4b30cb3d088
Revises: 8822efd6ceae
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4b30cb3d088"
down_revision: str | None = "8822efd6ceae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "'head_of_abm','research','content_drafter','reviewer','account_research',"
    "'design','onboarding_synthesis'"
)
_NEW = _OLD + ",'research_claims','research_narrative'"


def _roles(values: str) -> None:
    for table in ("agent_turn", "agent_plan"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_role")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {table}_role CHECK (role IN ({values}))")
    op.execute("ALTER TABLE agent_delegation DROP CONSTRAINT agent_delegation_roles")
    op.execute(f"""ALTER TABLE agent_delegation ADD CONSTRAINT agent_delegation_roles
        CHECK (parent_role IN ({values}) AND child_role IN ({values})
          AND parent_role<>child_role)""")


def upgrade() -> None:
    _roles(_NEW)
    op.execute("ALTER TABLE agent_plan ADD COLUMN budget_mode text NOT NULL DEFAULT 'enforced'")
    op.execute("ALTER TABLE agent_plan DROP CONSTRAINT agent_plan_limits")
    op.execute("""ALTER TABLE agent_plan ADD CONSTRAINT agent_plan_limits CHECK (
        max_parallelism BETWEEN 1 AND 32 AND estimated_cost_millicents>=0
        AND budget_limit_millicents>=0 AND budget_mode IN ('enforced','record_only')
        AND (budget_mode='record_only' OR budget_limit_millicents>=estimated_cost_millicents))""")
    op.execute("""CREATE TABLE arv2_quality_allowance (
        job_id uuid PRIMARY KEY, workspace_id text NOT NULL, run_id uuid NOT NULL,
        account_id uuid NOT NULL, max_model_calls integer NOT NULL,
        max_tool_calls integer NOT NULL, max_delegations integer NOT NULL,
        model_calls integer NOT NULL DEFAULT 0, tool_calls integer NOT NULL DEFAULT 0,
        delegations integer NOT NULL DEFAULT 0,
        CONSTRAINT quality_allowance_job FOREIGN KEY(job_id,workspace_id,run_id,account_id)
          REFERENCES arv2_research_job(job_id,workspace_id,run_id,account_entity_id),
        CONSTRAINT quality_allowance_scope UNIQUE(job_id,workspace_id),
        CONSTRAINT quality_allowance_limits CHECK (
          max_model_calls>0 AND max_tool_calls>0 AND max_delegations>=0
          AND model_calls BETWEEN 0 AND max_model_calls
          AND tool_calls BETWEEN 0 AND max_tool_calls
          AND delegations BETWEEN 0 AND max_delegations)
    )""")
    op.execute("""CREATE TABLE arv2_quality_execution (
        execution_id uuid PRIMARY KEY, workspace_id text NOT NULL, job_id uuid NOT NULL,
        context_id uuid NOT NULL, evidence_grant_id uuid,
        role text NOT NULL, parent_execution_id uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT quality_execution_identity FOREIGN KEY(execution_id,workspace_id)
          REFERENCES execution(id,workspace_id),
        CONSTRAINT quality_execution_job FOREIGN KEY(job_id,workspace_id)
          REFERENCES arv2_quality_allowance(job_id,workspace_id),
        CONSTRAINT quality_execution_grant FOREIGN KEY(evidence_grant_id,workspace_id)
          REFERENCES arv2_evidence_grant(grant_id,workspace_id),
        CONSTRAINT quality_execution_scope UNIQUE(execution_id,workspace_id,job_id),
        CONSTRAINT quality_execution_parent FOREIGN KEY(parent_execution_id,workspace_id,job_id)
          REFERENCES arv2_quality_execution(execution_id,workspace_id,job_id),
        CONSTRAINT quality_execution_role CHECK (
          (parent_execution_id IS NULL AND role='account_research') OR
          (parent_execution_id IS NOT NULL AND role IN ('research_claims','research_narrative')))
    )""")
    op.execute("CREATE INDEX quality_execution_job ON arv2_quality_execution(workspace_id,job_id)")
    op.execute("""CREATE TABLE arv2_quality_activity (
        activity_id uuid PRIMARY KEY, workspace_id text NOT NULL, job_id uuid NOT NULL,
        execution_id uuid NOT NULL, kind text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT quality_activity_execution FOREIGN KEY(execution_id,workspace_id,job_id)
          REFERENCES arv2_quality_execution(execution_id,workspace_id,job_id),
        CONSTRAINT quality_activity_kind CHECK (kind IN ('model','tool','delegation'))
    )""")
    op.execute(
        "CREATE INDEX quality_activity_job ON arv2_quality_activity(workspace_id,job_id,kind)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE arv2_quality_activity")
    op.execute("DROP TABLE arv2_quality_execution")
    op.execute("DROP TABLE arv2_quality_allowance")
    # Restoring enforcement fails if live record-only plans exceed the old ceiling.
    op.execute("ALTER TABLE agent_plan DROP CONSTRAINT agent_plan_limits")
    op.execute("""ALTER TABLE agent_plan ADD CONSTRAINT agent_plan_limits CHECK (
        max_parallelism BETWEEN 1 AND 32 AND estimated_cost_millicents>=0
        AND budget_limit_millicents>=estimated_cost_millicents)""")
    op.execute("ALTER TABLE agent_plan DROP COLUMN budget_mode")
    _roles(_OLD)
