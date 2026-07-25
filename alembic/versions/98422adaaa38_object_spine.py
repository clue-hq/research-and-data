"""object spine — workspace → brand → {product, project} (Phase A3.2)

Revision ID: 98422adaaa38
Revises: b61cd4887129
Create Date: 2026-07-17

The founder-delegated object spine (spec ``docs/specs/PA-phase-a-restructure-and-spine.md``
§A3.2; harness doc Q3 ruling): the tenancy root ``workspace`` and the objects that hang off it —
``brand`` (V1: exactly one per workspace), ``product``, and ``project`` (§1a vocabulary: a
*project* is the end-to-end ABM motion; a *campaign* is a channel program within it). Invalid
states are impossible **by construction**, never by handler code:

* ``brand_one_per_workspace`` — the V1 one-brand rule is a UNIQUE constraint, not code;
  ``brand_workspace_anchor`` (``UNIQUE (brand_id, workspace_id)``) exists solely to anchor the
  composite FKs below.
* ``product`` carries a **composite FK** ``(brand_id, workspace_id) → brand`` — a product can
  never point at a brand in another workspace, structurally. ``product_workspace_anchor``
  anchors ``project``'s composite product FK the same way.
* ``project`` composite-FKs both its brand and its (nullable) product to its **own**
  ``workspace_id`` — cross-workspace references are unrepresentable.
* ``campaign_run.project_id`` — nullable ``REFERENCES project`` (runs execute *for* a project;
  nullable because pre-spine runs have none), with a partial index for the project→runs read.

Ids are ``text`` PKs so legacy ids slot in unchanged (fresh ones are ``ws_``/``brd_``/``prd_``/
``prj_`` prefixed uuid4 hex, minted in ``clue_spine``).

**Deliberately deferred (build step 2):** FKs from the legacy tables' ``workspace_id`` text
columns (``claim``, ``icp_spec``, ``campaign_run``, …) to ``workspace`` — existing dev data has
no workspace rows; the backfill + constraints land when a real workspace-creation flow exists.
Fail-closed tenancy checks continue unchanged meanwhile.

Hand-written and reversible: ``downgrade()`` mirrors everything (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "98422adaaa38"
down_revision: str | None = "b61cd4887129"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- workspace: the tenancy root ---------------------------------------------------------
    op.execute(
        """
        CREATE TABLE workspace (
            workspace_id text NOT NULL,
            name         text NOT NULL,
            status       text NOT NULL DEFAULT 'active',
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT workspace_pkey PRIMARY KEY (workspace_id),
            CONSTRAINT workspace_status CHECK (status IN ('active', 'archived'))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE workspace IS 'Object-spine tenancy root (Phase A3.2). Every "
        "workspace_id column across the platform names a row here (legacy-table FKs deferred "
        "to build step 2).'"
    )

    # --- brand: V1 exactly one per workspace -------------------------------------------------
    op.execute(
        """
        CREATE TABLE brand (
            brand_id     text NOT NULL,
            workspace_id text NOT NULL,
            name         text NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT brand_pkey PRIMARY KEY (brand_id),
            CONSTRAINT brand_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            -- V1: one brand per workspace — the rule IS the constraint, not handler code.
            CONSTRAINT brand_one_per_workspace UNIQUE (workspace_id),
            -- Composite-FK anchor: lets product/project pin (brand, workspace) as one unit.
            CONSTRAINT brand_workspace_anchor UNIQUE (brand_id, workspace_id)
        )
        """
    )

    # --- product: structurally pinned to a brand in its own workspace ------------------------
    op.execute(
        """
        CREATE TABLE product (
            product_id   text NOT NULL,
            brand_id     text NOT NULL,
            workspace_id text NOT NULL,
            name         text NOT NULL,
            aliases      jsonb NOT NULL DEFAULT '[]'::jsonb,
            status       text NOT NULL DEFAULT 'active',
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT product_pkey PRIMARY KEY (product_id),
            CONSTRAINT product_status CHECK (status IN ('active', 'archived')),
            CONSTRAINT product_aliases_is_array CHECK (jsonb_typeof(aliases) = 'array'),
            -- A product can never point at a brand in another workspace — structurally.
            CONSTRAINT product_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT product_name_per_brand UNIQUE (brand_id, name),
            -- Composite-FK anchor for project's product FK.
            CONSTRAINT product_workspace_anchor UNIQUE (product_id, workspace_id)
        )
        """
    )

    # --- project: the end-to-end ABM motion (§1a vocabulary) ---------------------------------
    op.execute(
        """
        CREATE TABLE project (
            project_id   text NOT NULL,
            workspace_id text NOT NULL,
            brand_id     text NOT NULL,
            product_id   text,
            name         text NOT NULL,
            status       text NOT NULL DEFAULT 'draft',
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT project_pkey PRIMARY KEY (project_id),
            CONSTRAINT project_status CHECK (status IN ('draft', 'active', 'archived')),
            CONSTRAINT project_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT project_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            -- Nullable product; but if set, it must live in the project's own workspace.
            CONSTRAINT project_product_fk FOREIGN KEY (product_id, workspace_id)
                REFERENCES product (product_id, workspace_id)
        )
        """
    )

    # --- campaign_run executes FOR a project (nullable: pre-spine runs have none) ------------
    op.execute(
        """
        ALTER TABLE campaign_run
            ADD COLUMN project_id text,
            ADD CONSTRAINT campaign_run_project_fk FOREIGN KEY (project_id)
                REFERENCES project (project_id)
        """
    )
    op.execute(
        "CREATE INDEX campaign_run_project ON campaign_run (project_id) "
        "WHERE project_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX campaign_run_project")
    op.execute(
        "ALTER TABLE campaign_run DROP CONSTRAINT campaign_run_project_fk, DROP COLUMN project_id"
    )
    op.execute("DROP TABLE project")
    op.execute("DROP TABLE product")
    op.execute("DROP TABLE brand")
    op.execute("DROP TABLE workspace")
