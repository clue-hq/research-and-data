"""design documents and history (part2 D1a)

Revision ID: 7bff99d2ad65
Revises: c6d84aa84b79
Create Date: 2026-08-07

Part II slice D1, migration (a) of six (contract ``docs/specs/PD-part2-design-substrate.md``
§5 rows 1–6): the design document spine — ``design_document`` plus its history/undo substrate
(``design_operation_log``, ``design_edit_envelope``, ``design_snapshot``,
``design_template_revision``, ``design_document_diagnostic``). Ports the merged design
subsystem's SQLite DDL (``subsystems/clue-design/apps/api/migrations/001_init.sql`` +
``003_edit_envelopes.sql``) onto the platform substrate:

* **Tenancy laws (contract §3):** ``workspace_id NOT NULL`` + workspace FK on every table;
  parents carry a ``*_workspace_anchor``; child FKs are composite ``(parent_id, workspace_id)``
  so a cross-workspace reference is unrepresentable, not merely refused.
* ``current_scene_json`` stays the source of truth (full scene rewritten per write); the op log
  + envelopes are the **append-only** history/undo substrate — a preserved principle (founder
  2026-08-07): undo/redo writes new *forward* envelopes (``reverts_batch_id`` /
  ``reapplies_batch_id``); history is never truncated or compacted.
* Per-parent sequences (``design_operation_log.sequence``, ``design_edit_envelope.seq``) are
  allocated by the D2 DAL under ``SELECT … FOR UPDATE`` on the parent ``design_document`` row;
  the uniqueness constraints here make a racing allocator fail loudly.
* ``design_document.account_id`` is created WITHOUT its FK — ``design_account`` lands in
  migration (e) ``86a9ce389e6e``, which adds ``design_document_account_fk`` (breaks the a↔e
  creation cycle).
* Enum types (``design_doc_kind``, ``design_effective_brand_source``, ``design_op_source``)
  mirror ``clue_design.enums`` (package-local, the fleet precedent; parity-tested in
  ``tests/design/``). ``design_edit_envelope.source`` adopts the op log's enum — the envelope
  writers use the identical vocabulary; SQLite merely omitted the CHECK there.

Hand-written and reversible: ``downgrade()`` mirrors everything (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7bff99d2ad65"
down_revision: str | None = "c6d84aa84b79"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_design.enums (package-local; parity-tested in tests/design/).
_DOC_KIND = ("scene", "web")
_EFFECTIVE_BRAND_SOURCE = (
    "request",
    "document",
    "generated_default",
    "brand_kit_library",
    "scene_ref",
)
_OP_SOURCE = ("editor", "agent", "api", "system")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE design_doc_kind AS ENUM ({_enum_values_sql(_DOC_KIND)})")
    op.execute(
        "CREATE TYPE design_effective_brand_source AS ENUM "
        f"({_enum_values_sql(_EFFECTIVE_BRAND_SOURCE)})"
    )
    op.execute(f"CREATE TYPE design_op_source AS ENUM ({_enum_values_sql(_OP_SOURCE)})")

    # --- design_document: the document spine (scene + web, discriminated by doc_kind) --------
    op.execute(
        """
        CREATE TABLE design_document (
            id             text NOT NULL,
            workspace_id   text NOT NULL,
            title          text NOT NULL,
            status         text NOT NULL,
            doc_kind       design_doc_kind NOT NULL DEFAULT 'scene',
            current_scene_json jsonb NOT NULL,
            current_version    integer NOT NULL DEFAULT 0,
            effective_brand_kit_source  design_effective_brand_source,
            effective_brand_kit_id      text,
            effective_brand_kit_version integer,
            effective_brand_mode_json   jsonb,
            brand_kit_json              jsonb,
            undo_stack_json jsonb,
            redo_stack_json jsonb,
            agent_instructions     text,
            layout_managed_editing boolean NOT NULL DEFAULT false,
            is_template            boolean NOT NULL DEFAULT false,
            template_document_id   text,
            template_doc_version   integer,
            account_id             text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_document_pkey PRIMARY KEY (id),
            CONSTRAINT design_document_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_document_workspace_anchor UNIQUE (id, workspace_id),
            -- Template lineage stays inside the workspace; losing the template detaches,
            -- never deletes, the derived document.
            CONSTRAINT design_document_template_fk
                FOREIGN KEY (template_document_id, workspace_id)
                REFERENCES design_document (id, workspace_id)
                ON DELETE SET NULL (template_document_id),
            CONSTRAINT design_document_scene_object
                CHECK (jsonb_typeof(current_scene_json) = 'object'),
            CONSTRAINT design_document_brand_mode_object
                CHECK (effective_brand_mode_json IS NULL
                       OR jsonb_typeof(effective_brand_mode_json) = 'object'),
            CONSTRAINT design_document_brand_kit_object
                CHECK (brand_kit_json IS NULL OR jsonb_typeof(brand_kit_json) = 'object'),
            CONSTRAINT design_document_undo_array
                CHECK (undo_stack_json IS NULL OR jsonb_typeof(undo_stack_json) = 'array'),
            CONSTRAINT design_document_redo_array
                CHECK (redo_stack_json IS NULL OR jsonb_typeof(redo_stack_json) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_document IS 'Design-substrate document spine (PD D1a). "
        "current_scene_json is the source of truth (full scene/WebDoc, rewritten per write); "
        "current_version is the CAS counter (D2 extends CAS to scene writes). account_id FK "
        "lands in migration 86a9ce389e6e with design_account.'"
    )
    op.execute("CREATE INDEX design_document_workspace ON design_document (workspace_id)")

    # --- design_edit_envelope: the append-only undo/history substrate ------------------------
    # Created before design_operation_log so the op log's batch FK has its anchor.
    op.execute(
        """
        CREATE TABLE design_edit_envelope (
            id           bigint GENERATED ALWAYS AS IDENTITY,
            batch_id     text NOT NULL,
            workspace_id text NOT NULL,
            document_id  text NOT NULL,
            seq          integer NOT NULL,
            envelope_version integer NOT NULL DEFAULT 1,
            base_revision    integer,
            actor_kind   text NOT NULL,
            actor_id     text,
            source       design_op_source NOT NULL,
            intent       text,
            checkpoint_label text,
            touched_targets_json    jsonb NOT NULL DEFAULT '[]'::jsonb,
            operations_json         jsonb NOT NULL,
            inverse_operations_json jsonb,
            lineage_json            jsonb,
            reverts_batch_id   text,
            reapplies_batch_id text,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_edit_envelope_pkey PRIMARY KEY (id),
            CONSTRAINT design_edit_envelope_batch_unique UNIQUE (batch_id),
            CONSTRAINT design_edit_envelope_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            -- Composite-FK anchor for the op log's batch link + the self-references below.
            CONSTRAINT design_edit_envelope_batch_anchor UNIQUE (batch_id, workspace_id),
            CONSTRAINT design_edit_envelope_document_fk
                FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_edit_envelope_doc_seq_unique UNIQUE (document_id, seq),
            -- Undo/redo lineage: forward envelopes referencing the envelope they revert or
            -- reapply — same workspace, structurally.
            CONSTRAINT design_edit_envelope_reverts_fk
                FOREIGN KEY (reverts_batch_id, workspace_id)
                REFERENCES design_edit_envelope (batch_id, workspace_id),
            CONSTRAINT design_edit_envelope_reapplies_fk
                FOREIGN KEY (reapplies_batch_id, workspace_id)
                REFERENCES design_edit_envelope (batch_id, workspace_id),
            CONSTRAINT design_edit_envelope_touched_array
                CHECK (jsonb_typeof(touched_targets_json) = 'array'),
            CONSTRAINT design_edit_envelope_operations_array
                CHECK (jsonb_typeof(operations_json) = 'array'),
            CONSTRAINT design_edit_envelope_inverse_array
                CHECK (inverse_operations_json IS NULL
                       OR jsonb_typeof(inverse_operations_json) = 'array'),
            CONSTRAINT design_edit_envelope_lineage_object
                CHECK (lineage_json IS NULL OR jsonb_typeof(lineage_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_edit_envelope IS 'Append-only edit/undo substrate (PD D1a). "
        "History is never truncated: undo/redo writes new FORWARD envelopes with "
        "reverts_batch_id/reapplies_batch_id set (preserved principle, founder 2026-08-07). "
        "seq is allocated under FOR UPDATE on the parent design_document row (D2 DAL).'"
    )
    op.execute(
        "CREATE INDEX design_edit_envelope_document ON design_edit_envelope (document_id, seq DESC)"
    )

    # --- design_operation_log: per-document canonical op history -----------------------------
    op.execute(
        """
        CREATE TABLE design_operation_log (
            document_id  text NOT NULL,
            workspace_id text NOT NULL,
            sequence     integer NOT NULL,
            operation_json   jsonb NOT NULL,
            actor_kind   text NOT NULL,
            actor_id     text,
            source       design_op_source NOT NULL,
            diagnostics_json jsonb NOT NULL,
            batch_id     text,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_operation_log_pkey PRIMARY KEY (document_id, sequence),
            CONSTRAINT design_operation_log_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_operation_log_document_fk
                FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id) ON DELETE CASCADE,
            -- Real FK now (SQLite linked by convention only); nullable — rows may predate
            -- their envelope.
            CONSTRAINT design_operation_log_batch_fk
                FOREIGN KEY (batch_id, workspace_id)
                REFERENCES design_edit_envelope (batch_id, workspace_id),
            CONSTRAINT design_operation_log_operation_object
                CHECK (jsonb_typeof(operation_json) = 'object'),
            CONSTRAINT design_operation_log_diagnostics_array
                CHECK (jsonb_typeof(diagnostics_json) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_operation_log IS 'Append-only canonical operation history "
        "(PD D1a) — audit substrate, not the read path (design_document.current_scene_json "
        "is). sequence allocated under FOR UPDATE on the parent document row (D2 DAL).'"
    )

    # --- design_snapshot: explicit full-scene copies -----------------------------------------
    op.execute(
        """
        CREATE TABLE design_snapshot (
            snapshot_id  text NOT NULL,
            workspace_id text NOT NULL,
            document_id  text NOT NULL,
            version      integer NOT NULL,
            scene_json   jsonb NOT NULL,
            reason       text NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_snapshot_pkey PRIMARY KEY (snapshot_id),
            CONSTRAINT design_snapshot_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_snapshot_workspace_anchor UNIQUE (snapshot_id, workspace_id),
            CONSTRAINT design_snapshot_document_fk
                FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_snapshot_scene_object CHECK (jsonb_typeof(scene_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_snapshot IS 'Explicit user/API-triggered full-scene copies "
        "(PD D1a) — not periodic compaction; the history tables are never compacted.'"
    )
    op.execute(
        "CREATE INDEX design_snapshot_document ON design_snapshot (document_id, created_at DESC)"
    )

    # --- design_template_revision: frozen template versions ----------------------------------
    op.execute(
        """
        CREATE TABLE design_template_revision (
            template_revision_id text NOT NULL,
            workspace_id text NOT NULL,
            document_id  text NOT NULL,
            source_snapshot_id text,
            version      integer NOT NULL,
            scene_json   jsonb NOT NULL,
            export_profiles_json jsonb NOT NULL,
            slot_summary_json    jsonb NOT NULL,
            brand_ref_json       jsonb,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_template_revision_pkey PRIMARY KEY (template_revision_id),
            CONSTRAINT design_template_revision_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_template_revision_workspace_anchor
                UNIQUE (template_revision_id, workspace_id),
            CONSTRAINT design_template_revision_document_fk
                FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_template_revision_snapshot_fk
                FOREIGN KEY (source_snapshot_id, workspace_id)
                REFERENCES design_snapshot (snapshot_id, workspace_id)
                ON DELETE SET NULL (source_snapshot_id),
            CONSTRAINT design_template_revision_scene_object
                CHECK (jsonb_typeof(scene_json) = 'object'),
            CONSTRAINT design_template_revision_profiles_array
                CHECK (jsonb_typeof(export_profiles_json) = 'array'),
            CONSTRAINT design_template_revision_slots_array
                CHECK (jsonb_typeof(slot_summary_json) = 'array'),
            CONSTRAINT design_template_revision_brand_ref_object
                CHECK (brand_ref_json IS NULL OR jsonb_typeof(brand_ref_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_template_revision IS 'Frozen template versions (PD D1a) — "
        "the personalization plane (D1d) keys derivation on these.'"
    )
    op.execute(
        "CREATE INDEX design_template_revision_document "
        "ON design_template_revision (document_id, version DESC)"
    )

    # --- design_document_diagnostic: append-only diagnostics ---------------------------------
    op.execute(
        """
        CREATE TABLE design_document_diagnostic (
            id           bigint GENERATED ALWAYS AS IDENTITY,
            workspace_id text NOT NULL,
            document_id  text NOT NULL,
            kind         text NOT NULL,
            diagnostics_json jsonb NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_document_diagnostic_pkey PRIMARY KEY (id),
            CONSTRAINT design_document_diagnostic_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_document_diagnostic_document_fk
                FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_document_diagnostic_array
                CHECK (jsonb_typeof(diagnostics_json) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_document_diagnostic IS 'Append-only per-document diagnostics "
        "(PD D1a); reads take the latest row per kind.'"
    )
    op.execute(
        "CREATE INDEX design_document_diagnostic_document "
        "ON design_document_diagnostic (document_id, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_document_diagnostic")
    op.execute("DROP TABLE design_template_revision")
    op.execute("DROP TABLE design_snapshot")
    op.execute("DROP TABLE design_operation_log")
    op.execute("DROP TABLE design_edit_envelope")
    op.execute("DROP TABLE design_document")
    op.execute("DROP TYPE design_op_source")
    op.execute("DROP TYPE design_effective_brand_source")
    op.execute("DROP TYPE design_doc_kind")
