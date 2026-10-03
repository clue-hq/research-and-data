"""Preserve each capture's kit association for content-addressed website fragments.

Revision ID: d27183d13445
Revises: 5cac3234cfb3

A reingestion creates a new kit id while identical section bytes reuse the same
fragment id. Keep every capture association without rewriting original provenance.
Release decisions remain explicit, workspace-scoped and version-specific.
"""

from alembic import op

revision = "d27183d13445"
down_revision = "5cac3234cfb3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE design_web_fragment_kit_binding (
            workspace_id text NOT NULL,
            fragment_id text NOT NULL,
            brand_kit_id text NOT NULL,
            brand_kit_version integer NOT NULL,
            approved boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT design_web_fragment_kit_binding_pkey
                PRIMARY KEY (workspace_id, fragment_id, brand_kit_id, brand_kit_version),
            CONSTRAINT design_web_fragment_kit_binding_fragment_fk
                FOREIGN KEY (fragment_id, workspace_id)
                REFERENCES design_web_fragment (fragment_id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_web_fragment_kit_binding_kit_fk
                FOREIGN KEY (brand_kit_id, brand_kit_version, workspace_id)
                REFERENCES design_brand_kit (brand_kit_id, version, workspace_id) ON DELETE RESTRICT
        )
    """)
    op.execute("""
        CREATE INDEX design_web_fragment_kit_binding_release_idx
        ON design_web_fragment_kit_binding (workspace_id, brand_kit_id, brand_kit_version)
    """)
    op.execute("""
        INSERT INTO design_web_fragment_kit_binding
            (workspace_id, fragment_id, brand_kit_id, brand_kit_version, approved)
        SELECT f.workspace_id, f.fragment_id, f.source_kit_id, f.source_kit_version,
               f.status = 'approved' AND k.approval_status = 'approved'
        FROM design_web_fragment f
        JOIN design_brand_kit k ON k.workspace_id = f.workspace_id
            AND k.brand_kit_id = f.source_kit_id AND k.version = f.source_kit_version
    """)


def downgrade() -> None:
    op.execute("DROP TABLE design_web_fragment_kit_binding")
