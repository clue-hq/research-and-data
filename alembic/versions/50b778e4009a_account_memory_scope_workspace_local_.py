"""account memory scope — workspace-local accounts (Doc M §4 / PB-B3 follow-up)

Revision ID: 50b778e4009a
Revises: 8aba77245267
Create Date: 2026-07-21

The ``account`` arm of the scoped-memory substrate, unblocked by the founder ruling of 2026-07-22:
**accounts are workspace-local entities.** There is no global account identity and no cross-tenant
enrichment reuse — the grounds are provider licensing (enrichment data is licensed per controller,
not poolable across clients) and GDPR controller-separation (each workspace is its own controller).
Company X researched in workspaces A and B is therefore two separate ``account_entity`` rows, with
separate claims, contacts, and memories; nothing is shared across the workspace boundary.

Spine style throughout — raw ``op.execute`` SQL, named constraints, invalid states impossible **by
schema**. The two moving parts:

* **``account_entity`` becomes workspace-localizable.** Nullable ``workspace_id`` / ``brand_id``
  columns (the same legacy-compatible deferral the spine migration used for pre-existing tables:
  the research-side writers that stamp these — and the full domain/registry/contact re-scoping —
  are follow-up work in the research lane). A composite-FK anchor ``(id, workspace_id)`` is added so
  a memory can pin its account scope to the account's own workspace. A NULL ``workspace_id`` is a
  legacy/global row that **cannot own workspace-scoped memory** — the memory FK below can never
  reference it (memory.workspace_id is NOT NULL), so global memory is unrepresentable (fail-closed).
* **``memory`` gains the account arm.** ``scope_account_entity_id`` + a composite FK
  ``(scope_account_entity_id, workspace_id) → account_entity (id, workspace_id)`` — the isolation
  guarantee: a cross-workspace account reference is unrepresentable, exactly the spine-anchor
  pattern the brand/product/project arms already use. The ``memory_scope_type`` /
  ``memory_scope_shape`` CHECKs gain the ``account`` value/arm; the generated ``scope_id`` grouping
  column is regenerated to project the account id (Postgres cannot ALTER a generated expression, so
  it is dropped and re-added — the uuid→text cast is immutable, legal in a generated column).

Hand-written and reversible: ``downgrade()`` mirrors everything back to the four-scope schema
(CI runs up → down → up on clean, empty throwaway DBs — removing the scope necessarily removes its
rows).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "50b778e4009a"
down_revision: str | None = "8aba77245267"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- account_entity becomes workspace-localizable (nullable, legacy-compatible) -----------
    # Accounts are workspace-local (founder ruling 2026-07-22): no global account identity, no
    # cross-tenant enrichment reuse (provider licensing + separate-controller GDPR posture). The
    # columns are nullable so the legacy chain stays reversible and the research-side writers that
    # stamp them land later; a NULL-workspace row is a legacy row that cannot own scoped memory.
    op.execute(
        """
        ALTER TABLE account_entity
            ADD COLUMN workspace_id text,
            ADD COLUMN brand_id text,
            ADD CONSTRAINT account_entity_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            ADD CONSTRAINT account_entity_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            ADD CONSTRAINT account_entity_brand_needs_workspace
                CHECK (brand_id IS NULL OR workspace_id IS NOT NULL),
            ADD CONSTRAINT account_entity_workspace_anchor UNIQUE (id, workspace_id)
        """
    )
    op.execute(
        "COMMENT ON COLUMN account_entity.workspace_id IS 'Workspace-local account tenancy "
        "(founder ruling 2026-07-22): Company X in two workspaces = two rows, no cross-tenant "
        "reuse. Nullable for legacy rows; a NULL-workspace row cannot own workspace-scoped memory "
        "(the memory scope FK can never reference it — fail-closed, no global memory).'"
    )
    op.execute(
        "COMMENT ON COLUMN account_entity.brand_id IS 'Workspace-local brand the account belongs "
        "to (composite-FK anchored to workspace_id). Nullable legacy-compatible; the research-side "
        "stamping + domain/registry re-scoping is follow-up work in the research lane.'"
    )

    # --- memory gains the account arm ---------------------------------------------------------
    op.execute("ALTER TABLE memory ADD COLUMN scope_account_entity_id uuid")
    # The isolation guarantee: composite-pinned to the memory's own (NOT NULL) workspace, so a
    # cross-workspace account reference — and any reference to a NULL-workspace legacy account —
    # is unrepresentable (the spine-anchor pattern the brand/product/project arms use).
    op.execute(
        "ALTER TABLE memory ADD CONSTRAINT memory_scope_account_fk "
        "FOREIGN KEY (scope_account_entity_id, workspace_id) "
        "REFERENCES account_entity (id, workspace_id)"
    )

    # scope_type gains 'account'.
    op.execute("ALTER TABLE memory DROP CONSTRAINT memory_scope_type")
    op.execute(
        """
        ALTER TABLE memory ADD CONSTRAINT memory_scope_type CHECK (
            scope_type IN ('workspace', 'brand', 'product', 'project', 'account')
        )
        """
    )

    # scope_shape: every existing arm additionally requires the account column NULL; the new
    # 'account' arm requires exactly scope_account_entity_id set (all the sibling columns NULL).
    op.execute("ALTER TABLE memory DROP CONSTRAINT memory_scope_shape")
    op.execute(
        """
        ALTER TABLE memory ADD CONSTRAINT memory_scope_shape CHECK (
            CASE scope_type
                WHEN 'workspace' THEN scope_brand_id IS NULL AND scope_product_id IS NULL
                    AND scope_project_id IS NULL AND scope_account_entity_id IS NULL
                WHEN 'brand' THEN scope_brand_id IS NOT NULL AND scope_product_id IS NULL
                    AND scope_project_id IS NULL AND scope_account_entity_id IS NULL
                WHEN 'product' THEN scope_product_id IS NOT NULL AND scope_brand_id IS NULL
                    AND scope_project_id IS NULL AND scope_account_entity_id IS NULL
                WHEN 'project' THEN scope_project_id IS NOT NULL AND scope_brand_id IS NULL
                    AND scope_product_id IS NULL AND scope_account_entity_id IS NULL
                WHEN 'account' THEN scope_account_entity_id IS NOT NULL AND scope_brand_id IS NULL
                    AND scope_product_id IS NULL AND scope_project_id IS NULL
                ELSE false
            END
        )
        """
    )

    # Regenerate scope_id to project the account id (Postgres cannot ALTER a generated
    # expression — drop the dependent index + column, re-add both). The uuid→text cast is
    # immutable, so it is legal inside a generated column.
    op.execute("DROP INDEX memory_scope_read")
    op.execute("ALTER TABLE memory DROP COLUMN scope_id")
    op.execute(
        """
        ALTER TABLE memory ADD COLUMN scope_id text GENERATED ALWAYS AS (
            CASE scope_type
                WHEN 'workspace' THEN workspace_id
                WHEN 'brand'     THEN scope_brand_id
                WHEN 'product'   THEN scope_product_id
                WHEN 'project'   THEN scope_project_id
                WHEN 'account'   THEN scope_account_entity_id::text
            END
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX memory_scope_read ON memory "
        "(workspace_id, scope_type, scope_id, type, status)"
    )


def downgrade() -> None:
    # Removing the account scope necessarily removes its rows (db-smoke runs on empty DBs, so this
    # is a no-op there); the journals reference the memory rows, so drop dependents first.
    op.execute(
        "DELETE FROM memory_event WHERE memory_id IN "
        "(SELECT memory_id FROM memory WHERE scope_type = 'account')"
    )
    op.execute(
        "DELETE FROM memory_claim_ref WHERE memory_id IN "
        "(SELECT memory_id FROM memory WHERE scope_type = 'account')"
    )
    op.execute("DELETE FROM memory WHERE scope_type = 'account'")

    # Restore the four-scope generated column + index.
    op.execute("DROP INDEX memory_scope_read")
    op.execute("ALTER TABLE memory DROP COLUMN scope_id")
    op.execute(
        """
        ALTER TABLE memory ADD COLUMN scope_id text GENERATED ALWAYS AS (
            CASE scope_type
                WHEN 'workspace' THEN workspace_id
                WHEN 'brand'     THEN scope_brand_id
                WHEN 'product'   THEN scope_product_id
                WHEN 'project'   THEN scope_project_id
            END
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX memory_scope_read ON memory "
        "(workspace_id, scope_type, scope_id, type, status)"
    )

    # Restore the four-scope shape/type CHECKs.
    op.execute("ALTER TABLE memory DROP CONSTRAINT memory_scope_shape")
    op.execute(
        """
        ALTER TABLE memory ADD CONSTRAINT memory_scope_shape CHECK (
            CASE scope_type
                WHEN 'workspace' THEN scope_brand_id IS NULL
                    AND scope_product_id IS NULL AND scope_project_id IS NULL
                WHEN 'brand' THEN scope_brand_id IS NOT NULL
                    AND scope_product_id IS NULL AND scope_project_id IS NULL
                WHEN 'product' THEN scope_product_id IS NOT NULL
                    AND scope_brand_id IS NULL AND scope_project_id IS NULL
                WHEN 'project' THEN scope_project_id IS NOT NULL
                    AND scope_brand_id IS NULL AND scope_product_id IS NULL
                ELSE false
            END
        )
        """
    )
    op.execute("ALTER TABLE memory DROP CONSTRAINT memory_scope_type")
    op.execute(
        """
        ALTER TABLE memory ADD CONSTRAINT memory_scope_type CHECK (
            scope_type IN ('workspace', 'brand', 'product', 'project')
        )
        """
    )

    # Drop the memory account FK + column (before dropping the account_entity anchor it needs).
    op.execute("ALTER TABLE memory DROP CONSTRAINT memory_scope_account_fk")
    op.execute("ALTER TABLE memory DROP COLUMN scope_account_entity_id")

    # Revert account_entity to its pre-workspace-local shape.
    op.execute(
        """
        ALTER TABLE account_entity
            DROP CONSTRAINT account_entity_workspace_anchor,
            DROP CONSTRAINT account_entity_brand_needs_workspace,
            DROP CONSTRAINT account_entity_brand_fk,
            DROP CONSTRAINT account_entity_workspace_fk,
            DROP COLUMN brand_id,
            DROP COLUMN workspace_id
        """
    )
