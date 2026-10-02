"""arv2 onboarding run kind and lineage

Revision ID: af3cf1541ebe
Revises: 3742d1281a10
Create Date: 2026-09-07 18:02:37.881860+00:00

Track O (ARV2 onboarding), O3 — the fleet-driver substrate, two pieces:

1. ``fleet_task_kind`` gains ``onboarding_run``. ONE mechanical kind for the whole run (fast
   recon, catalog sync, background per-product research), the ``entity_research_job`` /
   ``design_job`` precedent: the exact shape of the work lives in the immutable by-value payload,
   not in the queue taxonomy, so the run has exactly one lease and one place to resume from.

2. ``onboarding_product_lineage`` — the onboarding lane's catalog lineage. The S5
   ``product_catalog_lineage`` cannot be re-pointed at this lane: its identity is a Client-KB
   *claim* (``catalog_claim_id`` NOT NULL FK ``claim``) plus a NOT NULL KB version, and Track O's
   catalog is an **artifact-keyed knowledge document**, not a claim. So the onboarding lane gets
   its own table keyed on ``(document_id, entry_ordinal)`` while keeping the S5 resolution
   vocabulary verbatim (``created`` / ``alias_reused`` / ``lineage_reused`` /
   ``unresolved_ambiguous``) so the two lanes read the same and a reader learns one taxonomy.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

Reversibility follows the ``be855c8f6993`` precedent exactly: PostgreSQL cannot drop an enum
label, so ``downgrade()`` refuses while any ``onboarding_run`` task exists and otherwise rebuilds
the type without the label (rename → CREATE → ALTER COLUMN … USING → DROP).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "af3cf1541ebe"
down_revision: str | None = "3742d1281a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The label set BEFORE this migration — what ``downgrade()`` restores. Mirrors
#: ``clue_fleet.enums.FleetTaskKind`` minus ``ONBOARDING_RUN``.
_KINDS_BEFORE = (
    "drive_run",
    "account_job",
    "execute_graph",
    "entity_research_job",
    "agent_turn",
    "stage0_recon",
    "official_site_crawl",
    "design_job",
)


def upgrade() -> None:
    # ADD VALUE is safe inside alembic's transaction because nothing here USES the label (PG16
    # forbids only the use, not the addition) — the be855c8f6993 precedent.
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'onboarding_run'")
    op.execute(
        """
        CREATE TABLE onboarding_product_lineage (
            lineage_id               uuid NOT NULL,
            workspace_id             text NOT NULL,
            brand_id                 text NOT NULL,
            document_id              uuid NOT NULL,
            entry_ordinal            integer NOT NULL,
            entry_fingerprint_sha256 text NOT NULL,
            product_id               text,
            resolution_state         text NOT NULL,
            candidate_count          integer NOT NULL DEFAULT 0,
            synchronized_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT onboarding_product_lineage_pkey PRIMARY KEY (lineage_id),
            CONSTRAINT onboarding_product_lineage_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT onboarding_product_lineage_document_fk FOREIGN KEY (document_id)
                REFERENCES brand_knowledge_document (document_id) ON DELETE CASCADE,
            CONSTRAINT onboarding_product_lineage_product_fk FOREIGN KEY (product_id, workspace_id)
                REFERENCES product (product_id, workspace_id),
            CONSTRAINT onboarding_product_lineage_entry_unique UNIQUE (document_id, entry_ordinal),
            CONSTRAINT onboarding_product_lineage_fingerprint CHECK
                (entry_fingerprint_sha256 ~ '^sha256:[0-9a-f]{64}$'),
            CONSTRAINT onboarding_product_lineage_state CHECK (
                (resolution_state IN ('created', 'alias_reused', 'lineage_reused')
                    AND product_id IS NOT NULL)
                OR (resolution_state = 'unresolved_ambiguous' AND product_id IS NULL)),
            CONSTRAINT onboarding_product_lineage_counts CHECK
                (entry_ordinal >= 0 AND candidate_count >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX onboarding_product_lineage_product "
        "ON onboarding_product_lineage (workspace_id, product_id) WHERE product_id IS NOT NULL"
    )
    # Rows are immutable in ordinary operation — a re-sync writes a NEW document and a new
    # lineage row rather than editing this one — while the ON DELETE CASCADE above deliberately
    # preserves DSAR reach when the source knowledge document is erased. Append-only means no
    # in-place edits; it never meant the row cannot be deleted (the S5 precedent, 1043a61823f1).
    op.execute(
        "CREATE TRIGGER onboarding_product_lineage_append_only "
        "BEFORE UPDATE ON onboarding_product_lineage FOR EACH ROW "
        "EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER onboarding_product_lineage_append_only ON onboarding_product_lineage")
    op.execute("DROP INDEX onboarding_product_lineage_product")
    op.execute("DROP TABLE onboarding_product_lineage")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'onboarding_run') THEN
                RAISE EXCEPTION 'cannot downgrade O3 while onboarding_run fleet tasks exist';
            END IF;
        END $$
        """
    )
    labels = ", ".join(f"'{k}'" for k in _KINDS_BEFORE)
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_o3")
    op.execute(f"CREATE TYPE fleet_task_kind AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE fleet_task ALTER COLUMN kind TYPE fleet_task_kind "
        "USING kind::text::fleet_task_kind"
    )
    op.execute("DROP TYPE fleet_task_kind_o3")
