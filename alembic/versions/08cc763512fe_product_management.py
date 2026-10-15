"""product management: merged products, the change log, project provenance

Revision ID: 08cc763512fe
Revises: 284e4383227f
Create Date: 2026-10-15

Spec docs/superpowers/specs/2026-10-15-product-management-design.md §3, §7 and §9:

- ``product`` gains a ``merged`` status and ``merged_into`` (the ``account_entity`` pattern), and a
  name is unique only among a brand's **active** products, so a renamed or newly merged product may
  reuse a name an archived or merged one held.
- ``product_change`` records every add / rename / merge / remove / restore (append-only), and
  ``product_change_project`` records what each change did to each project's product set — the
  source of the chat notice. ``product_change_notice_dismissal`` remembers who dismissed it.
- ``project_product`` versions may now come from a product change (``product_change_id``), the
  third provenance beside a gate answer and an automatic turn.
- ``onboarding_product_lineage`` gains ``removed_by_person``: an onboarding re-run that meets a
  product a person removed records it and does not bring it back.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "08cc763512fe"
down_revision: str | None = "284e4383227f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINEAGE_STATE = "onboarding_product_lineage_state"
_LINEAGE_RESOLVED_BEFORE = (
    "'created', 'alias_reused', 'lineage_reused', 'model_reused', 'model_unsure'"
)
_LINEAGE_RESOLVED_AFTER = _LINEAGE_RESOLVED_BEFORE + ", 'removed_by_person'"


def _lineage_state(resolved: str) -> str:
    return (
        f"ALTER TABLE onboarding_product_lineage ADD CONSTRAINT {_LINEAGE_STATE} CHECK ("
        f"(resolution_state IN ({resolved}) AND product_id IS NOT NULL) "
        "OR (resolution_state = 'unresolved_ambiguous' AND product_id IS NULL))"
    )


def upgrade() -> None:
    # --- product: merged + merged_into; name unique among active products only ----------------
    op.execute("ALTER TABLE product DROP CONSTRAINT product_status")
    op.execute(
        "ALTER TABLE product ADD CONSTRAINT product_status "
        "CHECK (status IN ('active', 'archived', 'merged'))"
    )
    op.execute("ALTER TABLE product ADD COLUMN merged_into text")
    op.execute(
        "ALTER TABLE product ADD CONSTRAINT product_merged_into_fk "
        "FOREIGN KEY (merged_into, workspace_id) REFERENCES product (product_id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE product ADD CONSTRAINT product_merged_into_state "
        "CHECK ((status = 'merged') = (merged_into IS NOT NULL))"
    )
    op.execute(
        "ALTER TABLE product ADD CONSTRAINT product_merged_into_not_self "
        "CHECK (merged_into IS NULL OR merged_into <> product_id)"
    )
    op.execute("ALTER TABLE product DROP CONSTRAINT product_name_per_brand")
    op.execute(
        "CREATE UNIQUE INDEX product_name_per_brand ON product (brand_id, name) "
        "WHERE status = 'active'"
    )

    # --- the change log ------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE product_change (
            change_id             uuid PRIMARY KEY,
            workspace_id          text NOT NULL,
            brand_id              text NOT NULL,
            kind                  text NOT NULL,
            product_id            text NOT NULL,
            affected_product_ids  jsonb NOT NULL DEFAULT '[]'::jsonb,
            details               jsonb NOT NULL DEFAULT '{}'::jsonb,
            actor_user_id         text NOT NULL,
            actor_turn_id         uuid,
            undoes_change_id      uuid,
            idempotency_key       text,
            created_at            timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT product_change_kind
                CHECK (kind IN ('add', 'rename', 'merge', 'remove', 'restore')),
            CONSTRAINT product_change_affected_is_array
                CHECK (jsonb_typeof(affected_product_ids) = 'array'),
            CONSTRAINT product_change_details_is_object CHECK (jsonb_typeof(details) = 'object'),
            CONSTRAINT product_change_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT product_change_product_fk FOREIGN KEY (product_id, workspace_id)
                REFERENCES product (product_id, workspace_id),
            CONSTRAINT product_change_actor_fk FOREIGN KEY (actor_user_id)
                REFERENCES platform_user (user_id),
            CONSTRAINT product_change_undoes_fk FOREIGN KEY (undoes_change_id)
                REFERENCES product_change (change_id),
            CONSTRAINT product_change_idempotency UNIQUE (workspace_id, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX product_change_brand_recent "
        "ON product_change (workspace_id, brand_id, created_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX product_change_undone_once ON product_change (undoes_change_id) "
        "WHERE undoes_change_id IS NOT NULL"
    )
    op.execute(
        "CREATE TRIGGER product_change_append_only "
        "BEFORE UPDATE OR DELETE ON product_change FOR EACH ROW "
        "EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )

    # --- what a change did to each project -----------------------------------------------------
    op.execute(
        """
        CREATE TABLE product_change_project (
            change_id                   uuid NOT NULL REFERENCES product_change (change_id),
            project_id                  text NOT NULL,
            workspace_id                text NOT NULL,
            outcome                     text NOT NULL,
            selection_version           integer,
            previous_selection_version  integer,
            created_at                  timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT product_change_project_pkey PRIMARY KEY (change_id, project_id),
            CONSTRAINT product_change_project_outcome
                CHECK (outcome IN ('updated', 'needs_choice', 'restored', 'left_as_is')),
            CONSTRAINT product_change_project_version
                CHECK ((outcome IN ('updated', 'restored')) = (selection_version IS NOT NULL)),
            CONSTRAINT product_change_project_project_fk FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX product_change_project_by_project "
        "ON product_change_project (workspace_id, project_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE product_change_notice_dismissal (
            change_id     uuid NOT NULL,
            project_id    text NOT NULL,
            user_id       text NOT NULL REFERENCES platform_user (user_id),
            dismissed_at  timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT product_change_notice_dismissal_pkey
                PRIMARY KEY (change_id, project_id, user_id),
            CONSTRAINT product_change_notice_dismissal_notice_fk FOREIGN KEY (change_id, project_id)
                REFERENCES product_change_project (change_id, project_id)
        )
        """
    )

    # --- project_product: a third provenance -----------------------------------------------------
    op.execute("ALTER TABLE project_product ADD COLUMN product_change_id uuid")
    op.execute(
        "ALTER TABLE project_product ADD CONSTRAINT project_product_change_fk "
        "FOREIGN KEY (product_change_id) REFERENCES product_change (change_id)"
    )
    op.execute("ALTER TABLE project_product DROP CONSTRAINT project_product_confirmation_source")
    op.execute(
        "ALTER TABLE project_product ADD CONSTRAINT project_product_confirmation_source CHECK ("
        "(gate_id IS NOT NULL)::int + (confirmation_turn_id IS NOT NULL)::int "
        "+ (product_change_id IS NOT NULL)::int = 1)"
    )

    # --- onboarding lineage: a person removed this product --------------------------------------
    op.execute(f"ALTER TABLE onboarding_product_lineage DROP CONSTRAINT {_LINEAGE_STATE}")
    op.execute(_lineage_state(_LINEAGE_RESOLVED_AFTER))


def downgrade() -> None:
    # Refuse rather than relabel durable decisions the narrower schema cannot hold.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM product WHERE status = 'merged')
               OR EXISTS (SELECT 1 FROM onboarding_product_lineage
                          WHERE resolution_state = 'removed_by_person')
               OR EXISTS (SELECT 1 FROM project_product WHERE product_change_id IS NOT NULL)
            THEN
                RAISE EXCEPTION
                    'cannot downgrade product management while merged products, removed-product '
                    'lineage rows or product-change project versions exist';
            END IF;
        END $$
        """
    )
    op.execute(f"ALTER TABLE onboarding_product_lineage DROP CONSTRAINT {_LINEAGE_STATE}")
    op.execute(_lineage_state(_LINEAGE_RESOLVED_BEFORE))

    op.execute("ALTER TABLE project_product DROP CONSTRAINT project_product_confirmation_source")
    op.execute(
        "ALTER TABLE project_product ADD CONSTRAINT project_product_confirmation_source "
        "CHECK ((gate_id IS NOT NULL) <> (confirmation_turn_id IS NOT NULL))"
    )
    op.execute("ALTER TABLE project_product DROP CONSTRAINT project_product_change_fk")
    op.execute("ALTER TABLE project_product DROP COLUMN product_change_id")

    op.execute("DROP TABLE product_change_notice_dismissal")
    op.execute("DROP TABLE product_change_project")
    op.execute("DROP TABLE product_change")

    op.execute("DROP INDEX product_name_per_brand")
    op.execute("ALTER TABLE product ADD CONSTRAINT product_name_per_brand UNIQUE (brand_id, name)")
    op.execute("ALTER TABLE product DROP CONSTRAINT product_merged_into_not_self")
    op.execute("ALTER TABLE product DROP CONSTRAINT product_merged_into_state")
    op.execute("ALTER TABLE product DROP CONSTRAINT product_merged_into_fk")
    op.execute("ALTER TABLE product DROP COLUMN merged_into")
    op.execute("ALTER TABLE product DROP CONSTRAINT product_status")
    op.execute(
        "ALTER TABLE product ADD CONSTRAINT product_status CHECK (status IN ('active', 'archived'))"
    )
