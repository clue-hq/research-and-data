"""design site section

Revision ID: 57f948ca3545
Revises: b4bff1ecca97
Create Date: 2026-10-12 17:04:35.863086+00:00

Lane B, Contract 4 of docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md:
one immutable row per compiled agent-written Puck section, keyed by the sha256 of its compiled
module, per workspace. The source, module and CSS bytes live in DesignBlobStore under
source_key 'design_site_section', which the public /asset-store read never serves.

``created_at`` defaults to ``clock_timestamp()`` rather than ``now()`` so two sections written in
one transaction still order by when each was written (the newest-per-name read depends on it).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "57f948ca3545"
down_revision: str | None = "b4bff1ecca97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_site_section (
            workspace_id      text        NOT NULL REFERENCES workspace (workspace_id),
            digest            text        NOT NULL,
            name              text        NOT NULL,
            source_sha256     text        NOT NULL,
            module_sha256     text        NOT NULL,
            css_sha256        text        NOT NULL,
            props_schema_json jsonb       NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
            created_by_run_id text,
            CONSTRAINT design_site_section_pkey PRIMARY KEY (workspace_id, digest),
            CONSTRAINT design_site_section_digest_shape CHECK (digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_site_section_module_is_digest CHECK (module_sha256 = digest),
            CONSTRAINT design_site_section_source_shape CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_site_section_css_shape CHECK (css_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_site_section_name_shape CHECK (name ~ '^[A-Z][A-Za-z0-9]{2,40}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX design_site_section_newest_by_name "
        "ON design_site_section (workspace_id, name, created_at DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION design_site_section_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'design_site_section is immutable (content-addressed)';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER design_site_section_no_update BEFORE UPDATE ON design_site_section "
        "FOR EACH ROW EXECUTE FUNCTION design_site_section_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER design_site_section_no_update ON design_site_section")
    op.execute("DROP FUNCTION design_site_section_immutable()")
    op.execute("DROP TABLE design_site_section")
