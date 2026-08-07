"""design personalization (part2 D1d)

Revision ID: 47d2e1ca25f1
Revises: c6cb64259ef1
Create Date: 2026-08-07

Part II slice D1, migration (d) of six (contract ``docs/specs/PD-part2-design-substrate.md``
§5 rows 12–15): the scene-mode personalization plane — ``design_binding_set``,
``design_instance_batch``, ``design_instance``, ``design_repair_request`` — porting SQLite
``005_personalization.sql``.

* Everything keys on a frozen ``design_template_revision`` (D1a); the SQLite tables carried NO
  FKs here — they become real composite FKs now (contract §4: real FKs with soft semantics
  preserved).
* ``design_instance.instance_id`` / ``design_repair_request.repair_id`` keep their
  **deterministic** id scheme (``inst_<rev>_<bind>`` / ``rep_<rev>_<slot>_<bind>`` after
  sanitization) — idempotent re-derivation upserts the same row; the PK now enforces what the
  application convention promised.
* ``derived_scene_json`` is a re-derivable cache of the derivation, kept for serving; the
  batch ``cursor`` chunked-resume seam is ported as-is and is superseded by the fleet at D5.
* ``design_instance_batch`` precedes ``design_instance`` so the instance's batch FK has its
  anchor. Batch deletion detaches (SET NULL), never deletes, derived instances; binding-set or
  revision deletion cascades — an instance is meaningless without either.

Hand-written and reversible: ``downgrade()`` mirrors everything (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "47d2e1ca25f1"
down_revision: str | None = "c6cb64259ef1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- design_binding_set: slot-key -> value maps against a frozen revision ----------------
    op.execute(
        """
        CREATE TABLE design_binding_set (
            binding_set_id text NOT NULL,
            workspace_id   text NOT NULL,
            template_revision_id text NOT NULL,
            binding_json     jsonb NOT NULL,
            status           text NOT NULL,
            diagnostics_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_binding_set_pkey PRIMARY KEY (binding_set_id),
            CONSTRAINT design_binding_set_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_binding_set_workspace_anchor
                UNIQUE (binding_set_id, workspace_id),
            CONSTRAINT design_binding_set_revision_fk
                FOREIGN KEY (template_revision_id, workspace_id)
                REFERENCES design_template_revision (template_revision_id, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT design_binding_set_binding_object
                CHECK (jsonb_typeof(binding_json) = 'object'),
            CONSTRAINT design_binding_set_diagnostics_array
                CHECK (jsonb_typeof(diagnostics_json) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_binding_set IS 'Scene-mode personalization bindings (PD "
        "D1d): slot_key -> BoundValue maps against a frozen template revision. (Web mode has "
        "no separate binding authoring — the design_account row IS the binding set.)'"
    )
    op.execute(
        "CREATE INDEX design_binding_set_revision "
        "ON design_binding_set (workspace_id, template_revision_id)"
    )

    # --- design_instance_batch: chunked bulk derivation (created before design_instance) -----
    op.execute(
        """
        CREATE TABLE design_instance_batch (
            batch_id     text NOT NULL,
            workspace_id text NOT NULL,
            template_revision_id text NOT NULL,
            status       text NOT NULL,
            binding_set_ids_json jsonb NOT NULL,
            export_formats_json  jsonb NOT NULL,
            chunk_size   integer NOT NULL,
            cursor       integer NOT NULL,
            counts_json   jsonb NOT NULL,
            manifest_json jsonb NOT NULL,
            diagnostics_json jsonb NOT NULL,
            export_profile_json jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_instance_batch_pkey PRIMARY KEY (batch_id),
            CONSTRAINT design_instance_batch_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_instance_batch_workspace_anchor UNIQUE (batch_id, workspace_id),
            CONSTRAINT design_instance_batch_revision_fk
                FOREIGN KEY (template_revision_id, workspace_id)
                REFERENCES design_template_revision (template_revision_id, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT design_instance_batch_chunk_positive CHECK (chunk_size >= 1),
            CONSTRAINT design_instance_batch_cursor_nonneg CHECK (cursor >= 0),
            CONSTRAINT design_instance_batch_binding_ids_array
                CHECK (jsonb_typeof(binding_set_ids_json) = 'array'),
            CONSTRAINT design_instance_batch_formats_array
                CHECK (jsonb_typeof(export_formats_json) = 'array'),
            CONSTRAINT design_instance_batch_counts_object
                CHECK (jsonb_typeof(counts_json) = 'object'),
            CONSTRAINT design_instance_batch_manifest_array
                CHECK (jsonb_typeof(manifest_json) = 'array'),
            CONSTRAINT design_instance_batch_diagnostics_array
                CHECK (jsonb_typeof(diagnostics_json) = 'array'),
            CONSTRAINT design_instance_batch_profile_object
                CHECK (export_profile_json IS NULL
                       OR jsonb_typeof(export_profile_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_instance_batch IS 'Chunked bulk-derivation batches (PD D1d). "
        "cursor is the synchronous chunked-resume seam, ported as-is; the fleet supersedes it "
        "at D5.'"
    )
    op.execute(
        "CREATE INDEX design_instance_batch_revision "
        "ON design_instance_batch (workspace_id, template_revision_id)"
    )

    # --- design_instance: one derived, personalized document ---------------------------------
    op.execute(
        """
        CREATE TABLE design_instance (
            instance_id  text NOT NULL,
            workspace_id text NOT NULL,
            template_revision_id text NOT NULL,
            binding_set_id       text NOT NULL,
            batch_id             text,
            status       text NOT NULL,
            fit_status   text NOT NULL,
            derived_scene_json jsonb NOT NULL,
            diagnostics_json   jsonb NOT NULL,
            audit_json         jsonb NOT NULL,
            fit_report_json    jsonb NOT NULL,
            artifacts_json     jsonb NOT NULL,
            generated_assets_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_instance_pkey PRIMARY KEY (instance_id),
            CONSTRAINT design_instance_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_instance_workspace_anchor UNIQUE (instance_id, workspace_id),
            CONSTRAINT design_instance_revision_fk
                FOREIGN KEY (template_revision_id, workspace_id)
                REFERENCES design_template_revision (template_revision_id, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT design_instance_binding_fk
                FOREIGN KEY (binding_set_id, workspace_id)
                REFERENCES design_binding_set (binding_set_id, workspace_id)
                ON DELETE CASCADE,
            -- Batch deletion detaches, never deletes, the derived instance.
            CONSTRAINT design_instance_batch_fk
                FOREIGN KEY (batch_id, workspace_id)
                REFERENCES design_instance_batch (batch_id, workspace_id)
                ON DELETE SET NULL (batch_id),
            CONSTRAINT design_instance_scene_object
                CHECK (jsonb_typeof(derived_scene_json) = 'object'),
            CONSTRAINT design_instance_diagnostics_array
                CHECK (jsonb_typeof(diagnostics_json) = 'array'),
            CONSTRAINT design_instance_audit_array CHECK (jsonb_typeof(audit_json) = 'array'),
            CONSTRAINT design_instance_fit_report_object
                CHECK (jsonb_typeof(fit_report_json) = 'object'),
            CONSTRAINT design_instance_artifacts_array
                CHECK (jsonb_typeof(artifacts_json) = 'array'),
            CONSTRAINT design_instance_generated_assets_object
                CHECK (jsonb_typeof(generated_assets_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_instance IS 'Derived personalized instances (PD D1d). "
        "instance_id is DETERMINISTIC (inst_<revision>_<binding> sanitized) — idempotent "
        "re-derivation upserts the same row; derived_scene_json is a re-derivable cache.'"
    )
    op.execute(
        "CREATE INDEX design_instance_revision "
        "ON design_instance (workspace_id, template_revision_id)"
    )
    op.execute(
        "CREATE INDEX design_instance_binding ON design_instance (workspace_id, binding_set_id)"
    )
    op.execute(
        "CREATE INDEX design_instance_batch_id ON design_instance (workspace_id, batch_id) "
        "WHERE batch_id IS NOT NULL"
    )

    # --- design_repair_request: slot-overflow repair queue -----------------------------------
    op.execute(
        """
        CREATE TABLE design_repair_request (
            repair_id    text NOT NULL,
            workspace_id text NOT NULL,
            template_revision_id text NOT NULL,
            slot_key     text NOT NULL,
            node_id      text NOT NULL,
            binding_set_id text NOT NULL,
            instance_id    text,
            reason       text NOT NULL,
            status       text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_repair_request_pkey PRIMARY KEY (repair_id),
            CONSTRAINT design_repair_request_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_repair_request_revision_fk
                FOREIGN KEY (template_revision_id, workspace_id)
                REFERENCES design_template_revision (template_revision_id, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT design_repair_request_binding_fk
                FOREIGN KEY (binding_set_id, workspace_id)
                REFERENCES design_binding_set (binding_set_id, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT design_repair_request_instance_fk
                FOREIGN KEY (instance_id, workspace_id)
                REFERENCES design_instance (instance_id, workspace_id)
                ON DELETE SET NULL (instance_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_repair_request IS 'Slot-overflow repair queue (PD D1d). "
        "repair_id is DETERMINISTIC (rep_<revision>_<slot>_<binding> sanitized) — the same "
        "overflow re-detected upserts the same open row.'"
    )
    op.execute(
        "CREATE INDEX design_repair_request_revision "
        "ON design_repair_request (workspace_id, template_revision_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_repair_request")
    op.execute("DROP TABLE design_instance")
    op.execute("DROP TABLE design_instance_batch")
    op.execute("DROP TABLE design_binding_set")
