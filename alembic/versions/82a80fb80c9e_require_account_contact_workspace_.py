"""require account/contact workspace ownership — [B3×research] residual 1 closure.

Revision ID: 82a80fb80c9e
Revises: 7f1868a127aa
Create Date: 2026-07-24 07:10:37.641083+00:00

The workspace-localization migration ``7f1868a127aa`` deliberately kept ``workspace_id`` nullable
so pre-B3 development rows remained representable and failed closed at every serving seam. The
founder decision on 2026-07-24 closes that transitional state: all existing database contents are
synthetic development data and may be discarded, so development databases are reset rather than
backfilled. From this revision onward every account and contact has an owning workspace.

The preflight is intentionally fail-closed instead of deleting rows in-place. Entity ids are soft
references in several append-only/audit tables, so surgically deleting only an account tree could
leave dangling historical references. A development database containing legacy rows must be reset
with ``make db-fresh && make migrate``; a clean deployment migrates normally.

The old NULL-only unique indexes are removed. The surviving strong-key indexes remain scoped by
``workspace_id`` and no longer carry the now-redundant ``workspace_id IS NOT NULL`` predicates.
``brand_id`` remains nullable and is deliberately outside this decision.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "82a80fb80c9e"
down_revision: str | None = "7f1868a127aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REGISTRIES = ("DUNS", "NPI", "CIK", "LEI")


def upgrade() -> None:
    # Do not create dangling soft references by trying to delete only part of an old entity graph.
    # The accepted dev-phase disposition is a full reset; make the required operator action loud.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM account_entity WHERE workspace_id IS NULL)
               OR EXISTS (SELECT 1 FROM contact_entity WHERE workspace_id IS NULL)
            THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'legacy unscoped account/contact rows must be discarded before '
                              'migration 82a80fb80c9e',
                    HINT = 'Development data only: run make db-fresh && make migrate.';
            END IF;
        END
        $$;
        """
    )

    op.execute("DROP INDEX account_entity_primary_domain_legacy_key")
    op.execute("DROP INDEX account_entity_primary_domain_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX account_entity_primary_domain_ws_key "
        "ON account_entity (workspace_id, primary_domain) "
        "WHERE primary_domain IS NOT NULL"
    )
    for namespace in _REGISTRIES:
        slug = namespace.lower()
        op.execute(f"DROP INDEX account_entity_registry_{slug}_legacy_key")
        op.execute(f"DROP INDEX account_entity_registry_{slug}_ws_key")
        op.execute(
            f"CREATE UNIQUE INDEX account_entity_registry_{slug}_ws_key "
            f"ON account_entity (workspace_id, (registry_ids->>'{namespace}')) "
            f"WHERE registry_ids ? '{namespace}'"
        )

    op.execute("DROP INDEX contact_entity_linkedin_url_legacy_key")
    op.execute("DROP INDEX contact_entity_linkedin_url_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_linkedin_url_ws_key "
        "ON contact_entity (workspace_id, linkedin_url) "
        "WHERE linkedin_url IS NOT NULL"
    )
    op.execute("DROP INDEX contact_entity_verified_email_legacy_key")
    op.execute("DROP INDEX contact_entity_verified_email_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_verified_email_ws_key "
        "ON contact_entity (workspace_id, verified_email) "
        "WHERE verified_email IS NOT NULL"
    )

    op.execute("ALTER TABLE account_entity ALTER COLUMN workspace_id SET NOT NULL")
    op.execute("ALTER TABLE contact_entity ALTER COLUMN workspace_id SET NOT NULL")
    op.execute(
        "COMMENT ON COLUMN account_entity.workspace_id IS 'Required workspace ownership: "
        "accounts are workspace-local; Company X in two workspaces is two rows, with no "
        "cross-tenant identity or enrichment reuse.'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE contact_entity ALTER COLUMN workspace_id DROP NOT NULL")
    op.execute("ALTER TABLE account_entity ALTER COLUMN workspace_id DROP NOT NULL")

    op.execute("DROP INDEX contact_entity_verified_email_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_verified_email_ws_key "
        "ON contact_entity (workspace_id, verified_email) "
        "WHERE verified_email IS NOT NULL AND workspace_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_verified_email_legacy_key "
        "ON contact_entity (verified_email) "
        "WHERE verified_email IS NOT NULL AND workspace_id IS NULL"
    )
    op.execute("DROP INDEX contact_entity_linkedin_url_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_linkedin_url_ws_key "
        "ON contact_entity (workspace_id, linkedin_url) "
        "WHERE linkedin_url IS NOT NULL AND workspace_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_linkedin_url_legacy_key "
        "ON contact_entity (linkedin_url) "
        "WHERE linkedin_url IS NOT NULL AND workspace_id IS NULL"
    )

    for namespace in _REGISTRIES:
        slug = namespace.lower()
        op.execute(f"DROP INDEX account_entity_registry_{slug}_ws_key")
        op.execute(
            f"CREATE UNIQUE INDEX account_entity_registry_{slug}_ws_key "
            f"ON account_entity (workspace_id, (registry_ids->>'{namespace}')) "
            f"WHERE registry_ids ? '{namespace}' AND workspace_id IS NOT NULL"
        )
        op.execute(
            f"CREATE UNIQUE INDEX account_entity_registry_{slug}_legacy_key "
            f"ON account_entity ((registry_ids->>'{namespace}')) "
            f"WHERE registry_ids ? '{namespace}' AND workspace_id IS NULL"
        )
    op.execute("DROP INDEX account_entity_primary_domain_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX account_entity_primary_domain_ws_key "
        "ON account_entity (workspace_id, primary_domain) "
        "WHERE primary_domain IS NOT NULL AND workspace_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX account_entity_primary_domain_legacy_key "
        "ON account_entity (primary_domain) "
        "WHERE primary_domain IS NOT NULL AND workspace_id IS NULL"
    )
    op.execute(
        "COMMENT ON COLUMN account_entity.workspace_id IS 'Workspace-local account tenancy "
        "(founder ruling 2026-07-22): Company X in two workspaces = two rows, no cross-tenant "
        "reuse. Nullable for legacy rows; a NULL-workspace row cannot own workspace-scoped memory "
        "(the memory scope FK can never reference it — fail-closed, no global memory).'"
    )
