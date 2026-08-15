"""enforce product knowledge scope

Revision ID: adaadcfaa9e8
Revises: 1043a61823f1
Create Date: 2026-08-15 04:12:36.768600+00:00

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
revision: str = "adaadcfaa9e8"
down_revision: str | None = "1043a61823f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("field_definition", "workspace_field_definition"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN product_scope text")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_product_scope "
            "CHECK (product_scope IS NULL OR product_scope IN "
            "('forbidden', 'required', 'optional'))"
        )
        op.execute(
            f"COMMENT ON COLUMN {table}.product_scope IS 'FI context release closure R1: "
            "declared product binding for claims of this field. NULL resolves forbidden for "
            "client.* and optional otherwise; required fields need product_id; forbidden fields "
            "must remain company/entity scoped.'"
        )

    # Materialize the fail-safe default for every already-registered client field so a later pack
    # reload compares equal instead of seeing runtime ``forbidden`` and stored NULL as different
    # definitions. Workspace-local dynamic Client-KB fields are company-wide by construction.
    op.execute(
        "UPDATE field_definition SET product_scope='forbidden' WHERE field_key LIKE 'client.%'"
    )
    op.execute(
        "UPDATE workspace_field_definition SET product_scope='forbidden' "
        "WHERE field_key LIKE 'client.%'"
    )

    # These are the frozen S5 product-knowledge exceptions. The dual company/product marker is
    # explicitly optional.
    op.execute(
        """
        UPDATE field_definition SET product_scope='required'
        WHERE field_key IN (
            'client.product_overview',
            'client.product_capability',
            'client.product_use_case',
            'client.product_differentiator',
            'client.product_pricing',
            'client.product_integration',
            'client.product_competitor',
            'client.product_customer_evidence',
            'client.product_positioning'
        )
        """
    )
    op.execute(
        "UPDATE field_definition SET product_scope='optional' WHERE field_key='client.kb_version'"
    )

    # Application writes fail early with ProductScopeError. This trigger is the cross-process and
    # direct-SQL backstop: no writer can bypass the field registry by skipping Python validation.
    op.execute(
        """
        CREATE FUNCTION claim_enforce_product_scope() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            declared_scope text;
            effective_scope text;
        BEGIN
            IF NEW.workspace_id IS NOT NULL THEN
                SELECT product_scope INTO declared_scope
                FROM workspace_field_definition
                WHERE workspace_id=NEW.workspace_id AND field_key=NEW.field_key;
            END IF;
            IF declared_scope IS NULL THEN
                SELECT product_scope INTO declared_scope
                FROM field_definition WHERE field_key=NEW.field_key;
            END IF;
            effective_scope := COALESCE(
                declared_scope,
                CASE WHEN NEW.field_key LIKE 'client.%' THEN 'forbidden' ELSE 'optional' END
            );
            IF effective_scope='required' AND NEW.product_id IS NULL THEN
                RAISE EXCEPTION USING
                    ERRCODE='23514',
                    CONSTRAINT='claim_product_scope_policy',
                    MESSAGE='field requires product_id';
            END IF;
            IF effective_scope='forbidden' AND NEW.product_id IS NOT NULL THEN
                RAISE EXCEPTION USING
                    ERRCODE='23514',
                    CONSTRAINT='claim_product_scope_policy',
                    MESSAGE='field forbids product_id';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER claim_product_scope_policy "
        "BEFORE INSERT ON claim FOR EACH ROW EXECUTE FUNCTION claim_enforce_product_scope()"
    )

    # Existing immutable claims are never rewritten by a migration. Operators need an exact,
    # body-free inventory of pre-policy violations, and every Client-KB reader now excludes them.
    op.execute(
        """
        CREATE VIEW claim_product_scope_violation AS
        SELECT
            c.id AS claim_id,
            c.workspace_id,
            c.field_key,
            c.product_id,
            COALESCE(
                w.product_scope,
                f.product_scope,
                CASE WHEN c.field_key LIKE 'client.%' THEN 'forbidden' ELSE 'optional' END
            ) AS effective_product_scope
        FROM claim c
        LEFT JOIN workspace_field_definition w
          ON w.workspace_id=c.workspace_id AND w.field_key=c.field_key
        LEFT JOIN field_definition f ON f.field_key=c.field_key
        WHERE
            (
                COALESCE(
                    w.product_scope,
                    f.product_scope,
                    CASE WHEN c.field_key LIKE 'client.%' THEN 'forbidden' ELSE 'optional' END
                )='required' AND c.product_id IS NULL
            )
            OR
            (
                COALESCE(
                    w.product_scope,
                    f.product_scope,
                    CASE WHEN c.field_key LIKE 'client.%' THEN 'forbidden' ELSE 'optional' END
                )='forbidden' AND c.product_id IS NOT NULL
            )
        """
    )
    op.execute(
        "COMMENT ON VIEW claim_product_scope_violation IS 'Body-free inventory of immutable "
        "claims written before FI context release closure R1 whose product binding violates the "
        "current field policy. New violations are refused by claim_product_scope_policy.'"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS claim_product_scope_violation")
    op.execute("DROP TRIGGER IF EXISTS claim_product_scope_policy ON claim")
    op.execute("DROP FUNCTION IF EXISTS claim_enforce_product_scope()")
    for table in ("workspace_field_definition", "field_definition"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_product_scope")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS product_scope")
