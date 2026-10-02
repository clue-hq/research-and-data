"""workspace hostnames and pages settings

Revision ID: aaff3d831895
Revises: e8fdb29cd532
Create Date: 2026-09-17 10:07:25.511934+00:00

Custom-domain publishing (design 2026-09-17 §4). ``workspace_hostname`` is the registry every
public page request begins with: hostname → workspace. System rows (``<label>.pages.cluehq.ai``)
double as the workspace-slug registry (Part IV piece 1); custom rows carry the Cloudflare
custom-hostname lifecycle. ``kind``/``status`` are text + CHECK like every migration since the
object spine (no Postgres enum, no core-enum mirror). ``workspace_pages_settings`` is one row per
workspace of page defaults; a missing row means all defaults. The migration creates no rows —
system hostnames are backfilled by ``make pages-backfill-hostnames``.

Reversible: the downgrade drops both tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "aaff3d831895"
down_revision: str | None = "e8fdb29cd532"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE workspace_hostname (
            hostname              text NOT NULL,
            workspace_id          text NOT NULL,
            kind                  text NOT NULL,
            status                text NOT NULL,
            cf_custom_hostname_id text,
            cname_target          text,
            ownership_txt_name    text,
            ownership_txt_value   text,
            observed_cname        text,
            observed_txt_present  boolean,
            last_checked_at       timestamptz,
            last_error_code       text,
            last_error_detail     text,
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now(),
            activated_at          timestamptz,
            CONSTRAINT workspace_hostname_pkey PRIMARY KEY (hostname),
            CONSTRAINT workspace_hostname_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_hostname_kind CHECK (kind IN ('system', 'custom')),
            CONSTRAINT workspace_hostname_status CHECK (status IN (
                'pending_dns', 'verifying_ownership', 'issuing_certificate',
                'active', 'error', 'disconnecting')),
            CONSTRAINT workspace_hostname_lowercase
                CHECK (hostname = lower(hostname) AND hostname !~ '\\.$'),
            CONSTRAINT workspace_hostname_system_is_active
                CHECK (kind <> 'system' OR status = 'active'),
            CONSTRAINT workspace_hostname_custom_columns CHECK (
                kind <> 'custom' OR (cname_target IS NOT NULL AND ownership_txt_name IS NOT NULL
                                     AND ownership_txt_value IS NOT NULL)),
            CONSTRAINT workspace_hostname_system_columns CHECK (
                kind <> 'system' OR (cf_custom_hostname_id IS NULL AND cname_target IS NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX workspace_hostname_one_system_per_workspace "
        "ON workspace_hostname (workspace_id) WHERE kind = 'system'"
    )
    op.execute(
        "CREATE UNIQUE INDEX workspace_hostname_one_custom_per_workspace "
        "ON workspace_hostname (workspace_id) WHERE kind = 'custom'"
    )
    op.execute("CREATE INDEX workspace_hostname_workspace_idx ON workspace_hostname (workspace_id)")
    op.execute(
        """
        CREATE TABLE workspace_pages_settings (
            workspace_id          text NOT NULL,
            fallback_url          text,
            page_title            text,
            page_description      text,
            favicon_sha256        text,
            social_preview_sha256 text,
            updated_at            timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT workspace_pages_settings_pkey PRIMARY KEY (workspace_id),
            CONSTRAINT workspace_pages_settings_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_pages_settings_fallback_https
                CHECK (fallback_url IS NULL OR fallback_url ~ '^https://')
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE workspace_pages_settings")
    op.execute("DROP TABLE workspace_hostname")
