"""Scope quality pages to project/context/generation with retained dependency manifests.

Revision ID: 16bfa50620f4
Revises: 4005ff9c331c
"""

from alembic import op

revision = "16bfa50620f4"
down_revision = "4005ff9c331c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""ALTER TABLE display_block
      ADD COLUMN project_id text,
      ADD COLUMN context_id uuid,
      ADD COLUMN generation_id uuid,
      ADD COLUMN dependency_manifest jsonb,
      ADD COLUMN output_artifact_key text REFERENCES artifact(storage_key),
      ADD COLUMN execution_id uuid REFERENCES execution(id),
      ADD CONSTRAINT display_quality_context FOREIGN KEY(context_id,workspace_id,project_id)
        REFERENCES arv2_research_context_pin(context_id,workspace_id,project_id),
      ADD CONSTRAINT display_quality_generation FOREIGN KEY(generation_id,workspace_id)
        REFERENCES arv2_account_research_generation(generation_id,workspace_id),
      ADD CONSTRAINT display_quality_shape CHECK (
        (context_id IS NULL AND project_id IS NULL AND generation_id IS NULL
          AND dependency_manifest IS NULL AND output_artifact_key IS NULL AND execution_id IS NULL)
        OR (context_id IS NOT NULL AND project_id IS NOT NULL AND generation_id IS NOT NULL
          AND dependency_manifest IS NOT NULL AND output_artifact_key IS NOT NULL
          AND execution_id IS NOT NULL))""")
    op.execute("DROP INDEX display_block_live")
    op.execute(
        "CREATE UNIQUE INDEX display_block_live ON display_block "
        "(workspace_id,subject_kind,subject_id,page,section_key) "
        "WHERE superseded_at IS NULL AND context_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX display_block_context_live ON display_block "
        "(workspace_id,project_id,context_id,subject_kind,subject_id,page,section_key) "
        "WHERE superseded_at IS NULL AND context_id IS NOT NULL"
    )
    op.execute("""CREATE TABLE arv2_research_page_current (
      workspace_id text NOT NULL, project_id text NOT NULL, context_id uuid NOT NULL,
      subject_kind text NOT NULL, subject_id uuid NOT NULL, page text NOT NULL,
      generation_id uuid NOT NULL, dependency_sha256 text NOT NULL,
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT arv2_research_page_current_pk PRIMARY KEY
        (workspace_id,project_id,context_id,subject_kind,subject_id,page),
      CONSTRAINT arv2_research_page_current_context FOREIGN KEY(context_id,workspace_id,project_id)
        REFERENCES arv2_research_context_pin(context_id,workspace_id,project_id),
      CONSTRAINT arv2_research_page_current_generation FOREIGN KEY(generation_id,workspace_id)
        REFERENCES arv2_account_research_generation(generation_id,workspace_id),
      CONSTRAINT arv2_research_page_current_kind CHECK
        ((subject_kind='account' AND page IN ('overview','insights')) OR
         (subject_kind='contact' AND page='contact')),
      CONSTRAINT arv2_research_page_current_digest CHECK (dependency_sha256 ~ '^[0-9a-f]{64}$')
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE arv2_research_page_current")
    # Downgrade preserves new history but removes its current status before restoring old keys.
    op.execute(
        "UPDATE display_block SET superseded_at=COALESCE(superseded_at,now()) "
        "WHERE context_id IS NOT NULL"
    )
    op.execute("DROP INDEX display_block_context_live")
    op.execute("DROP INDEX display_block_live")
    op.execute("""ALTER TABLE display_block
      DROP CONSTRAINT display_quality_shape,
      DROP CONSTRAINT display_quality_generation,
      DROP CONSTRAINT display_quality_context,
      DROP COLUMN execution_id, DROP COLUMN output_artifact_key, DROP COLUMN dependency_manifest,
      DROP COLUMN generation_id, DROP COLUMN context_id, DROP COLUMN project_id""")
    op.execute(
        "CREATE UNIQUE INDEX display_block_live ON display_block "
        "(workspace_id,subject_kind,subject_id,page,section_key) WHERE superseded_at IS NULL"
    )
