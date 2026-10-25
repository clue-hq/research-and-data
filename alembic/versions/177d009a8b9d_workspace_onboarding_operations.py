"""workspace onboarding operations (spec 2026-10-25 §12)

Revision ID: 177d009a8b9d
Revises: cba395a41e66
Create Date: 2026-10-25 18:42:42.444353+00:00

Three additions for the operator lifecycle (add a workspace, start onboarding, pre-flight, repair):

- ``onboarding_run.kind`` gains ``repair``: a run that re-does only the steps a repair planned,
  listed in the new ``planned_steps`` column (present exactly on repair runs).
- ``workspace_operation``: one audit row per applied operator operation — who, why, the plan, the
  estimate and what it started.
- ``design_ingestion_status`` gains ``succeeded_with_gaps`` (a brand-kit job that finished with
  failed descriptions, ad analyses, card, brief or grammar audit) and ``design_ingestion_kind``
  gains ``kit_repair`` (batch-describe, republish, re-offer the ad card). Both labels are APPENDED;
  the enum-parity test asserts order lock-step with ``clue_design.enums``.

The enums are rebuilt (rename, create, re-type, drop) in both directions rather than ``ADD VALUE``,
the 403bce58bdcf idiom, so the whole migration stays one transaction. The downgrade refuses while a
``kit_repair`` job exists and maps ``succeeded_with_gaps`` rows back to ``succeeded``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "177d009a8b9d"
down_revision: str | None = "cba395a41e66"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("queued", "running", "succeeded", "failed")
_KINDS = ("website", "pdf", "asset_upload", "ad_assets", "asset_enrichment")


def _rebuild_enum(type_name: str, column: str, labels: tuple[str, ...]) -> None:
    values = ", ".join(f"'{label}'" for label in labels)
    op.execute(f"ALTER TYPE {type_name} RENAME TO {type_name}_old")
    op.execute(f"CREATE TYPE {type_name} AS ENUM ({values})")
    op.execute(
        f"ALTER TABLE design_ingestion_job ALTER COLUMN {column} TYPE {type_name} "
        f"USING {column}::text::{type_name}"
    )
    op.execute(f"DROP TYPE {type_name}_old")


def upgrade() -> None:
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_kind")
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_kind "
        "CHECK (kind IN ('full', 'personas', 'customers', 'repair'))"
    )
    op.execute("ALTER TABLE onboarding_run ADD COLUMN planned_steps jsonb")
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_repair_plan "
        "CHECK ((kind = 'repair') = (planned_steps IS NOT NULL))"
    )
    op.execute("""CREATE TABLE workspace_operation (
        operation_id uuid PRIMARY KEY,
        operation text NOT NULL,
        workspace_id text NOT NULL,
        actor text NOT NULL,
        reason text,
        plan_json jsonb NOT NULL DEFAULT '{}'::jsonb,
        estimated_cost_usd numeric(12, 4) NOT NULL DEFAULT 0,
        onboarding_run_id uuid,
        design_job_ids text[] NOT NULL DEFAULT '{}',
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT workspace_operation_kind
            CHECK (operation IN ('add_workspace', 'start_onboarding', 'repair')),
        CONSTRAINT workspace_operation_actor CHECK (length(btrim(actor)) > 0),
        CONSTRAINT workspace_operation_reason CHECK (reason IS NULL OR length(btrim(reason)) > 0),
        CONSTRAINT workspace_operation_cost CHECK (estimated_cost_usd >= 0)
    )""")
    op.execute(
        "CREATE INDEX workspace_operation_workspace "
        "ON workspace_operation(workspace_id, created_at DESC)"
    )
    _rebuild_enum("design_ingestion_status", "status", (*_STATUSES, "succeeded_with_gaps"))
    _rebuild_enum("design_ingestion_kind", "kind", (*_KINDS, "kit_repair"))


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM design_ingestion_job WHERE kind::text = 'kit_repair') THEN
            RAISE EXCEPTION 'kit_repair ingestion jobs exist; delete them before downgrading';
        END IF;
        IF EXISTS (SELECT 1 FROM onboarding_run WHERE kind = 'repair') THEN
            RAISE EXCEPTION 'repair onboarding runs exist; delete them before downgrading';
        END IF;
    END $$""")
    op.execute(
        "UPDATE design_ingestion_job SET status = 'succeeded' "
        "WHERE status::text = 'succeeded_with_gaps'"
    )
    _rebuild_enum("design_ingestion_kind", "kind", _KINDS)
    _rebuild_enum("design_ingestion_status", "status", _STATUSES)
    op.execute("DROP TABLE workspace_operation")
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_repair_plan")
    op.execute("ALTER TABLE onboarding_run DROP COLUMN planned_steps")
    op.execute("ALTER TABLE onboarding_run DROP CONSTRAINT onboarding_run_kind")
    op.execute(
        "ALTER TABLE onboarding_run ADD CONSTRAINT onboarding_run_kind "
        "CHECK (kind IN ('full', 'personas', 'customers'))"
    )
