"""workspace research fields settings

Revision ID: 3a75cb367c2b
Revises: 6d25b68bff68
Create Date: 2026-09-16 07:47:04.349651+00:00

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
revision: str = "3a75cb367c2b"
down_revision: str | None = "6d25b68bff68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE workspace_field_definition ADD COLUMN label text")
    op.execute("ALTER TABLE workspace_field_definition ALTER COLUMN pack DROP NOT NULL")
    op.execute(
        "ALTER TABLE workspace_field_definition "
        "ALTER COLUMN promoted_from_proposal_id DROP NOT NULL"
    )
    for suffix in ("client_namespace", "pack", "role"):
        op.drop_constraint(f"workspace_field_definition_{suffix}", "workspace_field_definition")
    op.create_check_constraint(
        "workspace_field_definition_client_namespace",
        "workspace_field_definition",
        "field_key LIKE 'client.%' OR field_key LIKE 'account.%' OR field_key LIKE 'contact.%'",
    )
    op.create_check_constraint(
        "workspace_field_definition_role",
        "workspace_field_definition",
        "client_kb_role IN ('extended', 'research')",
    )
    op.create_check_constraint(
        "workspace_field_definition_pack",
        "workspace_field_definition",
        "(client_kb_role = 'extended' AND field_key LIKE 'client.%' "
        "AND field_class = 'pack' AND pack IS NOT NULL AND pack = 'client' "
        "AND promoted_from_proposal_id IS NOT NULL) OR "
        "(client_kb_role = 'research' AND pack IS NULL AND "
        "((field_key LIKE 'account.%' AND field_class = 'account') OR "
        "(field_key LIKE 'contact.%' AND field_class = 'contact')))",
    )
    op.create_check_constraint(
        "workspace_field_definition_research_shape",
        "workspace_field_definition",
        "client_kb_role <> 'research' OR (label IS NOT NULL AND "
        "length(btrim(label)) BETWEEN 1 AND 200 AND description IS NOT NULL AND "
        "length(btrim(description)) BETWEEN 1 AND 2000 AND value_type = 'json' AND "
        "value_schema IS NULL AND pass_kind = 'deep' AND research_scope IS NOT NULL AND "
        "research_scope = 'project_neutral' AND product_scope IS NOT NULL AND "
        "product_scope = 'forbidden' AND promoted_from_proposal_id IS NULL AND "
        "promotion_policy_version = 'settings-v1' AND promoted_by LIKE 'human:%')",
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION workspace_field_definition_reject_update()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.client_kb_role = 'research'
               AND NEW.definition_version = OLD.definition_version + 1
               AND (NEW.label IS DISTINCT FROM OLD.label
                    OR NEW.description IS DISTINCT FROM OLD.description)
               AND (to_jsonb(NEW) - ARRAY['label', 'description', 'definition_version'])
                 = (to_jsonb(OLD) - ARRAY['label', 'description', 'definition_version'])
            THEN RETURN NEW;
            END IF;
            RAISE EXCEPTION 'workspace field identity and shape are immutable';
        END;
        $$ LANGUAGE plpgsql
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM workspace_field_definition WHERE client_kb_role='research')
            THEN RAISE EXCEPTION
                'Research fields exist; preserve definitions and claims before rollback';
            END IF;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION workspace_field_definition_reject_update()
        RETURNS trigger AS $$ BEGIN
            RAISE EXCEPTION 'workspace_field_definition is append-only';
        END; $$ LANGUAGE plpgsql
    """)
    for suffix in ("research_shape", "client_namespace", "pack", "role"):
        op.drop_constraint(f"workspace_field_definition_{suffix}", "workspace_field_definition")
    for suffix, condition in (
        ("client_namespace", "field_key LIKE 'client.%'"),
        ("pack", "field_class = 'pack' AND pack = 'client'"),
        ("role", "client_kb_role = 'extended'"),
    ):
        op.create_check_constraint(
            f"workspace_field_definition_{suffix}", "workspace_field_definition", condition
        )
    op.execute("ALTER TABLE workspace_field_definition ALTER COLUMN pack SET NOT NULL")
    op.execute(
        "ALTER TABLE workspace_field_definition ALTER COLUMN promoted_from_proposal_id SET NOT NULL"
    )
    op.drop_column("workspace_field_definition", "label")
