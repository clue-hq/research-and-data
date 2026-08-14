"""s5 product catalog lineage and turn product version

Revision ID: 1043a61823f1
Revises: d3672ccf43cc
Create Date: 2026-08-14 19:38:35.084355+00:00

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
revision: str = "1043a61823f1"
down_revision: str | None = "d3672ccf43cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE product_catalog_lineage (
            lineage_id                    uuid PRIMARY KEY,
            workspace_id                  text NOT NULL,
            brand_id                      text NOT NULL,
            client_entity_id              uuid NOT NULL,
            company_client_kb_version     integer NOT NULL,
            catalog_claim_id               uuid NOT NULL,
            entry_ordinal                  integer NOT NULL,
            entry_fingerprint_sha256       text NOT NULL,
            product_id                     text,
            product_kb_version_at_sync      integer,
            resolution_state               text NOT NULL,
            candidate_count                integer NOT NULL DEFAULT 0,
            synchronized_at                timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT product_catalog_lineage_workspace_brand_fk
                FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT product_catalog_lineage_workspace_client_fk
                FOREIGN KEY (client_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT product_catalog_lineage_claim_fk
                FOREIGN KEY (catalog_claim_id) REFERENCES claim (id) ON DELETE CASCADE,
            CONSTRAINT product_catalog_lineage_workspace_product_fk
                FOREIGN KEY (product_id, workspace_id)
                REFERENCES product (product_id, workspace_id),
            CONSTRAINT product_catalog_lineage_entry_unique
                UNIQUE (catalog_claim_id, entry_ordinal),
            CONSTRAINT product_catalog_lineage_identity_nonempty CHECK (
                company_client_kb_version >= 1
                AND entry_ordinal >= 0
                AND entry_fingerprint_sha256 ~ '^sha256:[0-9a-f]{64}$'
                AND resolution_state IN ('created', 'alias_reused', 'unresolved_ambiguous')
                AND candidate_count >= 0
                AND (product_kb_version_at_sync IS NULL OR (
                    product_id IS NOT NULL AND product_kb_version_at_sync >= 1
                ))
                AND (
                    (resolution_state IN ('created', 'alias_reused') AND product_id IS NOT NULL)
                    OR (resolution_state = 'unresolved_ambiguous' AND product_id IS NULL)
                )
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX product_catalog_lineage_scope "
        "ON product_catalog_lineage "
        "(workspace_id, client_entity_id, company_client_kb_version, entry_ordinal)"
    )
    op.execute(
        "CREATE INDEX product_catalog_lineage_product "
        "ON product_catalog_lineage (workspace_id, product_id) WHERE product_id IS NOT NULL"
    )
    # Rows are immutable in ordinary operation, while ON DELETE CASCADE deliberately preserves
    # DSAR reach when the source catalog claim is erased.
    op.execute(
        "CREATE TRIGGER product_catalog_lineage_append_only "
        "BEFORE UPDATE ON product_catalog_lineage FOR EACH ROW "
        "EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )
    op.execute("ALTER TABLE agent_turn_scope_pin ADD COLUMN product_kb_version integer")
    op.execute(
        "ALTER TABLE agent_turn_scope_pin ADD CONSTRAINT agent_turn_scope_pin_product_version "
        "CHECK (product_kb_version IS NULL OR (product_id IS NOT NULL AND "
        "client_entity_id IS NOT NULL AND product_kb_version >= 1))"
    )
    op.execute(
        "CREATE INDEX agent_turn_scope_pin_product_version "
        "ON agent_turn_scope_pin (workspace_id, product_id, product_kb_version) "
        "WHERE product_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS agent_turn_scope_pin_product_version")
    op.execute(
        "ALTER TABLE agent_turn_scope_pin "
        "DROP CONSTRAINT IF EXISTS agent_turn_scope_pin_product_version"
    )
    op.execute("ALTER TABLE agent_turn_scope_pin DROP COLUMN IF EXISTS product_kb_version")
    op.execute(
        "DROP TRIGGER IF EXISTS product_catalog_lineage_append_only ON product_catalog_lineage"
    )
    op.execute("DROP INDEX IF EXISTS product_catalog_lineage_product")
    op.execute("DROP INDEX IF EXISTS product_catalog_lineage_scope")
    op.execute("DROP TABLE IF EXISTS product_catalog_lineage")
