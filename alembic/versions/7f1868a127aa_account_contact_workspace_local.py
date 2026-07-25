"""account/contact workspace-local — [B3×research] research-lane completion.

Revision ID: 7f1868a127aa
Revises: 7f2a9c4b1d8e
Create Date: 2026-07-23 09:50:24.251037+00:00

Founder ruling 2026-07-22 (see 50b778e4009a): accounts are workspace-local — no global account
identity, no cross-tenant enrichment reuse. 50b778e4009a added the nullable columns + anchor on
account_entity; this migration adds the research half: contact_entity.workspace_id (denormalized,
composite-FK-bound to the parent account so contact workspace ≡ account workspace is
unrepresentable otherwise), within-workspace merge FKs on both entity tables, and workspace-scoped
strong-key uniqueness (legacy NULL-workspace rows keep the old global uniqueness via partial
indexes). Columns stay nullable — legacy rows remain representable and fail-closed everywhere.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f1868a127aa"
down_revision: str | None = "7f2a9c4b1d8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REGISTRIES = ("DUNS", "NPI", "CIK", "LEI")  # mirror 0005_entity_model._IDENTIFYING_REGISTRIES


def upgrade() -> None:
    # 1. contact_entity gains workspace_id, bound to its parent account's (id, workspace_id).
    op.execute("ALTER TABLE contact_entity ADD COLUMN workspace_id text")
    op.execute(
        "ALTER TABLE contact_entity ADD CONSTRAINT contact_entity_workspace_fk "
        "FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id)"
    )
    op.execute(
        "ALTER TABLE contact_entity ADD CONSTRAINT contact_entity_account_workspace_fk "
        "FOREIGN KEY (account_entity_id, workspace_id) "
        "REFERENCES account_entity (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE contact_entity ADD CONSTRAINT contact_entity_workspace_anchor "
        "UNIQUE (id, workspace_id)"
    )
    # 2. Backfill from the parent account (no-op on legacy NULL parents).
    op.execute(
        "UPDATE contact_entity c SET workspace_id = a.workspace_id "
        "FROM account_entity a WHERE c.account_entity_id = a.id "
        "AND a.workspace_id IS NOT NULL"
    )
    # 3. Within-workspace merge fences (MATCH SIMPLE: NULL workspace ⇒ unenforced ⇒ legacy-safe).
    op.execute(
        "ALTER TABLE account_entity ADD CONSTRAINT account_entity_merge_same_workspace "
        "FOREIGN KEY (merged_into, workspace_id) REFERENCES account_entity (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE contact_entity ADD CONSTRAINT contact_entity_merge_same_workspace "
        "FOREIGN KEY (merged_into, workspace_id) REFERENCES contact_entity (id, workspace_id)"
    )
    # 4. Strong-key uniqueness → workspace-scoped; legacy NULL-workspace rows keep global semantics.
    op.execute("DROP INDEX account_entity_primary_domain_key")
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
    for ns in _REGISTRIES:
        op.execute(f"DROP INDEX account_entity_registry_{ns.lower()}_key")
        op.execute(
            f"CREATE UNIQUE INDEX account_entity_registry_{ns.lower()}_ws_key "
            f"ON account_entity (workspace_id, (registry_ids->>'{ns}')) "
            f"WHERE registry_ids ? '{ns}' AND workspace_id IS NOT NULL"
        )
        op.execute(
            f"CREATE UNIQUE INDEX account_entity_registry_{ns.lower()}_legacy_key "
            f"ON account_entity ((registry_ids->>'{ns}')) "
            f"WHERE registry_ids ? '{ns}' AND workspace_id IS NULL"
        )
    op.execute("DROP INDEX contact_entity_linkedin_url_key")
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
    op.execute("DROP INDEX contact_entity_verified_email_key")
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
    # 5. Plain lookup indexes for the workspace-filtered resolution queries (Task 2).
    op.execute("CREATE INDEX account_entity_workspace ON account_entity (workspace_id)")
    op.execute("CREATE INDEX contact_entity_workspace ON contact_entity (workspace_id)")


def downgrade() -> None:
    op.execute("DROP INDEX contact_entity_workspace")
    op.execute("DROP INDEX account_entity_workspace")
    op.execute("DROP INDEX contact_entity_verified_email_legacy_key")
    op.execute("DROP INDEX contact_entity_verified_email_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_verified_email_key ON contact_entity (verified_email) "
        "WHERE verified_email IS NOT NULL"
    )
    op.execute("DROP INDEX contact_entity_linkedin_url_legacy_key")
    op.execute("DROP INDEX contact_entity_linkedin_url_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX contact_entity_linkedin_url_key ON contact_entity (linkedin_url) "
        "WHERE linkedin_url IS NOT NULL"
    )
    for ns in _REGISTRIES:
        op.execute(f"DROP INDEX account_entity_registry_{ns.lower()}_legacy_key")
        op.execute(f"DROP INDEX account_entity_registry_{ns.lower()}_ws_key")
        op.execute(
            f"CREATE UNIQUE INDEX account_entity_registry_{ns.lower()}_key "
            f"ON account_entity ((registry_ids->>'{ns}')) WHERE registry_ids ? '{ns}'"
        )
    op.execute("DROP INDEX account_entity_primary_domain_legacy_key")
    op.execute("DROP INDEX account_entity_primary_domain_ws_key")
    op.execute(
        "CREATE UNIQUE INDEX account_entity_primary_domain_key ON account_entity (primary_domain) "
        "WHERE primary_domain IS NOT NULL"
    )
    op.execute("ALTER TABLE contact_entity DROP CONSTRAINT contact_entity_merge_same_workspace")
    op.execute("ALTER TABLE account_entity DROP CONSTRAINT account_entity_merge_same_workspace")
    op.execute("ALTER TABLE contact_entity DROP CONSTRAINT contact_entity_workspace_anchor")
    op.execute("ALTER TABLE contact_entity DROP CONSTRAINT contact_entity_account_workspace_fk")
    op.execute("ALTER TABLE contact_entity DROP CONSTRAINT contact_entity_workspace_fk")
    op.execute("ALTER TABLE contact_entity DROP COLUMN workspace_id")
