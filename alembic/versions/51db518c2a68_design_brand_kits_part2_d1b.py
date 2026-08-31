"""design brand kits (part2 D1b)

Revision ID: 51db518c2a68
Revises: 7bff99d2ad65
Create Date: 2026-08-07

Part II slice D1, migration (b) of six (contract ``docs/specs/PD-part2-design-substrate.md``
§5 rows 7–8): ``design_brand_kit`` + ``design_brand_compat_report``, porting the merged design
subsystem's ``brand_kits`` / ``brand_compatibility_reports`` (SQLite ``002_brand_kits.sql`` as
rebuilt by ``007_ingestion_jobs.sql`` — that drop-and-rebuild-on-boot ritual is deliberately
NOT ported; this is a normal versioned migration).

* **O2 (RATIFIED 2026-08-07): ``design_brand_kit`` is THE platform's versioned brand-kit
  payload** — the version-pinned kit Part III's delegation bundle references, and the durable
  payload behind the per-brand "brand studio" surface. ``brand_id`` is **born-nullable** with a
  composite FK ``(brand_id, workspace_id) → brand`` via ``brand_workspace_anchor``; D3
  completes the join and decides NOT NULL promotion.
* Versions are immutable-by-convention rows keyed ``(brand_kit_id, version)`` — a new version
  is a new row (the D2 DAL never updates ``brand_kit_json`` in place; ``approval_status`` /
  ``product_ready`` are the mutable review columns).
* Kit JSON carries tokens/modes/constraints and **references** to fonts/logos/images by asset
  id/digest — bytes live in the asset registry (D1c) and move to platform storage at D4.
* Enum types ``design_brand_approval_status`` / ``design_brand_kit_source`` mirror
  ``clue_design.enums``; parity-tested in ``tests/design/``.

Hand-written and reversible: ``downgrade()`` mirrors everything (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "51db518c2a68"
down_revision: str | None = "7bff99d2ad65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_design.enums (package-local; parity-tested in tests/design/).
_APPROVAL_STATUS = ("draft", "generated_unreviewed", "approved", "deprecated")
_KIT_SOURCE = (
    "manual",
    "uploaded",
    "generated",
    "styles",
    "platform_default",
    "api",
    "website",
    "pdf",
    "asset_upload",
)


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(
        f"CREATE TYPE design_brand_approval_status AS ENUM ({_enum_values_sql(_APPROVAL_STATUS)})"
    )
    op.execute(f"CREATE TYPE design_brand_kit_source AS ENUM ({_enum_values_sql(_KIT_SOURCE)})")

    # --- design_brand_kit: the platform's versioned brand-kit payload (O2) -------------------
    op.execute(
        """
        CREATE TABLE design_brand_kit (
            brand_kit_id text NOT NULL,
            version      integer NOT NULL,
            workspace_id text NOT NULL,
            brand_id     text,
            name         text NOT NULL,
            approval_status design_brand_approval_status,
            product_ready   boolean NOT NULL DEFAULT false,
            source          design_brand_kit_source NOT NULL,
            brand_kit_json     jsonb NOT NULL,
            brand_summary_json jsonb NOT NULL,
            diagnostics_json   jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_brand_kit_pkey PRIMARY KEY (brand_kit_id, version),
            CONSTRAINT design_brand_kit_version_positive CHECK (version >= 1),
            CONSTRAINT design_brand_kit_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            -- O2: born-nullable brand-spine join; when set, the brand lives in the kit's own
            -- workspace — structurally. D3 completes the join.
            CONSTRAINT design_brand_kit_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            -- Composite-FK anchor for compat reports + the ingestion-job result pointer (D1f).
            CONSTRAINT design_brand_kit_workspace_anchor
                UNIQUE (brand_kit_id, version, workspace_id),
            CONSTRAINT design_brand_kit_json_object
                CHECK (jsonb_typeof(brand_kit_json) = 'object'),
            CONSTRAINT design_brand_kit_summary_object
                CHECK (jsonb_typeof(brand_summary_json) = 'object'),
            CONSTRAINT design_brand_kit_diagnostics_array
                CHECK (jsonb_typeof(diagnostics_json) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_brand_kit IS 'THE platform versioned brand-kit payload (PD "
        "D1b; O2 ratified 2026-08-07). Keyed (brand_kit_id, version) — a new version is a new "
        "row; brand_kit_json holds tokens/modes/constraints + asset references (bytes live in "
        "the asset registry). brand_id joins the brand spine (born-nullable; D3 tightens). "
        "Part III delegation bundles pin (brand_kit_id, version).'"
    )
    op.execute(
        "CREATE INDEX design_brand_kit_workspace "
        "ON design_brand_kit (workspace_id, brand_kit_id, version DESC)"
    )
    op.execute(
        "CREATE INDEX design_brand_kit_brand ON design_brand_kit (brand_id, version DESC) "
        "WHERE brand_id IS NOT NULL"
    )

    # --- design_brand_compat_report: cross-version compatibility diffs -----------------------
    op.execute(
        """
        CREATE TABLE design_brand_compat_report (
            report_id    text NOT NULL,
            workspace_id text NOT NULL,
            from_brand_kit_id text NOT NULL,
            from_version      integer NOT NULL,
            to_brand_kit_id   text NOT NULL,
            to_version        integer NOT NULL,
            report_json      jsonb NOT NULL,
            diagnostics_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_brand_compat_report_pkey PRIMARY KEY (report_id),
            CONSTRAINT design_brand_compat_report_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_brand_compat_report_from_fk
                FOREIGN KEY (from_brand_kit_id, from_version, workspace_id)
                REFERENCES design_brand_kit (brand_kit_id, version, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT design_brand_compat_report_to_fk
                FOREIGN KEY (to_brand_kit_id, to_version, workspace_id)
                REFERENCES design_brand_kit (brand_kit_id, version, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT design_brand_compat_report_report_object
                CHECK (jsonb_typeof(report_json) = 'object'),
            CONSTRAINT design_brand_compat_report_diagnostics_array
                CHECK (jsonb_typeof(diagnostics_json) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_brand_compat_report IS 'Brand-kit cross-version "
        "compatibility reports (PD D1b); both endpoints are same-workspace kit versions, "
        "structurally.'"
    )
    op.execute(
        "CREATE INDEX design_brand_compat_report_from "
        "ON design_brand_compat_report (from_brand_kit_id, from_version, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_brand_compat_report")
    op.execute("DROP TABLE design_brand_kit")
    op.execute("DROP TYPE design_brand_kit_source")
    op.execute("DROP TYPE design_brand_approval_status")
