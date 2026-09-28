"""Account research generations and durable continuation signals.

Revision ID: 369f195d9976
Revises: c237eb027732
"""

from collections.abc import Sequence

from alembic import op

revision: str = "369f195d9976"
down_revision: str | None = "c237eb027732"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""CREATE TABLE arv2_account_research_generation (
        generation_id uuid PRIMARY KEY, workspace_id text NOT NULL, project_id text NOT NULL,
        context_id uuid NOT NULL, run_id uuid NOT NULL, account_id uuid NOT NULL,
        initial_job_id uuid NOT NULL UNIQUE, input_revision bigint NOT NULL DEFAULT 0,
        reconciled_revision bigint NOT NULL DEFAULT -1,
        state text NOT NULL DEFAULT 'researching', initial_settled_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL
        DEFAULT now(),
        CONSTRAINT quality_generation_scope UNIQUE(generation_id,workspace_id),
        CONSTRAINT quality_generation_job FOREIGN
        KEY(initial_job_id,workspace_id,run_id,account_id)
            REFERENCES arv2_research_job(job_id,workspace_id,run_id,account_entity_id),
        CONSTRAINT quality_generation_context FOREIGN KEY(context_id,workspace_id,project_id)
            REFERENCES arv2_research_context_pin(context_id,workspace_id,project_id),
        CONSTRAINT quality_generation_revisions CHECK(input_revision>=0 AND
        reconciled_revision>=-1
            AND reconciled_revision<=input_revision),
        CONSTRAINT quality_generation_state CHECK(state IN
('researching','provisional','reconciled','partial','needs_review','suspended','privacy_stopped'))
    )""")
    op.execute(
        "CREATE INDEX quality_generation_account ON "
        "arv2_account_research_generation(workspace_id,project_id,account_id,context_id)"
    )
    op.execute(
        "CREATE INDEX quality_generation_pending ON "
        "arv2_account_research_generation(updated_at,generation_id) WHERE "
        "input_revision>reconciled_revision"
    )
    op.execute("""CREATE TABLE arv2_generation_child (
        generation_id uuid NOT NULL, workspace_id text NOT NULL, job_id uuid NOT NULL,
        contact_id uuid NOT NULL, terminal_status text, result_sha256 text,
        receipt_key text, recorded_at timestamptz,
        CONSTRAINT quality_generation_child_pk PRIMARY KEY(generation_id,job_id),
        CONSTRAINT quality_generation_child_parent FOREIGN KEY(generation_id,workspace_id)
            REFERENCES arv2_account_research_generation(generation_id,workspace_id),
        CONSTRAINT quality_generation_child_job FOREIGN KEY(job_id,workspace_id)
            REFERENCES arv2_research_job(job_id,workspace_id),
        CONSTRAINT quality_generation_child_contact FOREIGN KEY(contact_id,workspace_id)
            REFERENCES contact_entity(id,workspace_id),
        CONSTRAINT quality_generation_child_receipt FOREIGN KEY(receipt_key,workspace_id)
            REFERENCES artifact(storage_key,workspace_id),
        CONSTRAINT quality_generation_child_status CHECK(terminal_status IS NULL OR
        terminal_status IN
            ('completed','needs_review','failed')),
        CONSTRAINT quality_generation_child_digest CHECK(result_sha256 IS NULL OR
        result_sha256 ~ '^[0-9a-f]{64}$')
    )""")
    op.execute(
        "CREATE INDEX quality_generation_child_subject ON "
        "arv2_generation_child(workspace_id,contact_id,generation_id)"
    )
    op.execute(
        "CREATE INDEX quality_generation_child_job_lookup ON "
        "arv2_generation_child(workspace_id,job_id)"
    )
    op.execute("""CREATE TABLE arv2_generation_signal (
        generation_id uuid NOT NULL, workspace_id text NOT NULL, event_id uuid NOT NULL,
        input_revision bigint NOT NULL, reason text NOT NULL, created_at timestamptz NOT
        NULL DEFAULT now(),
        CONSTRAINT quality_generation_signal_pk PRIMARY KEY(generation_id,event_id),
        CONSTRAINT quality_generation_signal_parent FOREIGN KEY(generation_id,workspace_id)
            REFERENCES arv2_account_research_generation(generation_id,workspace_id),
        CONSTRAINT quality_generation_signal_revision UNIQUE(generation_id,input_revision),
        CONSTRAINT quality_generation_signal_reason CHECK(reason IN
('initial_settled','person_result','claim_changed','media_changed','manual_refresh'))
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE arv2_generation_signal")
    op.execute("DROP TABLE arv2_generation_child")
    op.execute("DROP TABLE arv2_account_research_generation")
