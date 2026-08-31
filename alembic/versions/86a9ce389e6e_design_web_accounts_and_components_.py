"""design web accounts and components (part2 D1e)

Revision ID: 86a9ce389e6e
Revises: 47d2e1ca25f1
Create Date: 2026-08-07

Part II slice D1, migration (e) of six (contract ``docs/specs/PD-part2-design-substrate.md``
§5 rows 19–26): the web-personalization plane — ``design_account`` (the ABM target-company
row), ``design_web_batch``, ``design_web_publish_revision``, ``design_web_publish``, and the
four ``design_custom_component*`` tables — porting SQLite ``009``–``014``. Also completes
D1a's deferred ``design_document.account_id`` FK (the a↔e creation cycle breaks here).

* **O1 (RATIFIED):** ``design_account.account_entity_id`` is **born-nullable** ``uuid``; when
  present the composite FK ``(account_entity_id, workspace_id) →
  account_entity (id, workspace_id)`` binds the design account to the platform's
  workspace-scoped account entity — D3 wires resolve-or-create at the composition root and
  decides NOT NULL promotion. An account IS the web-mode binding set; ``notes`` is agent-only
  context, never a substitution value.
* **O6 (RATIFIED): publish slugs are workspace-local** — ``design_web_publish`` PK is
  ``(workspace_id, slug)``. Global URL uniqueness is a serving-layer concern (Part IV); the
  interim ``/p/{slug}`` rule is O6b, ratified at D2.
* **Immutability is enforced in the schema** (claim-trigger precedent):
  ``design_web_publish_revision`` rejects UPDATE *and* DELETE;
  ``design_custom_component_artifact`` / ``_source_revision`` / ``_compilation`` reject UPDATE
  (ports of the five SQLite triggers). Content-hash ids keep shape CHECKs
  (``ccart_<sha256>`` / ``ccsrc_<sha256>``), and ``design_web_publish_revision`` pins its
  content address structurally: ``publish_id = 'webpub_' || package_digest``.
* Provenance FKs (batch/publish-revision → document) are NO ACTION: published history blocks
  document deletion rather than silently losing provenance (append-only principle).

Hand-written and reversible: ``downgrade()`` mirrors everything (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "86a9ce389e6e"
down_revision: str | None = "47d2e1ca25f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_design.enums (package-local; parity-tested in tests/design/).
_PUBLISH_STATUS = ("active", "unpublished")
_COMPILATION_STATUS = ("succeeded", "failed", "transient_error")


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"CREATE TYPE design_publish_status AS ENUM ({_enum_values_sql(_PUBLISH_STATUS)})")
    op.execute(
        f"CREATE TYPE design_compilation_status AS ENUM ({_enum_values_sql(_COMPILATION_STATUS)})"
    )

    # --- design_account: one row per ABM target company (web-mode binding set) ---------------
    op.execute(
        """
        CREATE TABLE design_account (
            account_id   text NOT NULL,
            workspace_id text NOT NULL,
            account_entity_id uuid,
            name         text NOT NULL,
            domain       text,
            logo_asset_id text,
            data_json    jsonb NOT NULL DEFAULT '{}'::jsonb,
            notes        text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_account_pkey PRIMARY KEY (account_id),
            CONSTRAINT design_account_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_account_workspace_anchor UNIQUE (account_id, workspace_id),
            -- O1: born-nullable projection onto the platform account spine; when set, the
            -- entity lives in this workspace — structurally. D3 completes the join.
            CONSTRAINT design_account_entity_fk
                FOREIGN KEY (account_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            -- Real FK now (SQLite validated at write time only); losing the logo detaches it.
            CONSTRAINT design_account_logo_fk
                FOREIGN KEY (logo_asset_id, workspace_id)
                REFERENCES design_asset (asset_id, workspace_id)
                ON DELETE SET NULL (logo_asset_id),
            CONSTRAINT design_account_data_object CHECK (jsonb_typeof(data_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_account IS 'ABM target-company rows for web personalization "
        "(PD D1e; O1 ratified). An account IS the web-mode binding set: data_json (flat "
        "string map) projects into the account.* substitution namespace; notes is AGENT-ONLY "
        "context and never a substitution value. account_entity_id joins the platform account "
        "spine (born-nullable; D3 resolves-or-creates and tightens).'"
    )
    op.execute(
        "CREATE INDEX design_account_entity ON design_account (workspace_id, account_entity_id)"
        " WHERE account_entity_id IS NOT NULL"
    )

    # --- D1a deferral: documents may record the account they were derived for ----------------
    op.execute(
        """
        ALTER TABLE design_document
            ADD CONSTRAINT design_document_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES design_account (account_id, workspace_id)
                ON DELETE SET NULL (account_id)
        """
    )

    # --- design_web_batch: bulk derive+publish over N accounts -------------------------------
    op.execute(
        """
        CREATE TABLE design_web_batch (
            batch_id     text NOT NULL,
            workspace_id text NOT NULL,
            template_document_id text NOT NULL,
            template_doc_version integer NOT NULL,
            status       text NOT NULL,
            account_ids_json jsonb NOT NULL,
            publish      boolean NOT NULL DEFAULT true,
            slug_base    text,
            cursor       integer NOT NULL DEFAULT 0,
            manifest_json jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_web_batch_pkey PRIMARY KEY (batch_id),
            CONSTRAINT design_web_batch_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            -- Provenance pin: batches block template-document deletion (NO ACTION).
            CONSTRAINT design_web_batch_template_fk
                FOREIGN KEY (template_document_id, workspace_id)
                REFERENCES design_document (id, workspace_id),
            CONSTRAINT design_web_batch_cursor_nonneg CHECK (cursor >= 0),
            CONSTRAINT design_web_batch_account_ids_array
                CHECK (jsonb_typeof(account_ids_json) = 'array'),
            CONSTRAINT design_web_batch_manifest_array
                CHECK (jsonb_typeof(manifest_json) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_web_batch IS 'Bulk web derive+publish batches (PD D1e). "
        "template_doc_version pins provenance; counts derive from manifest_json at read time; "
        "cursor is the chunked-resume seam the fleet supersedes at D5.'"
    )
    op.execute(
        "CREATE INDEX design_web_batch_template "
        "ON design_web_batch (workspace_id, template_document_id)"
    )

    # --- design_web_publish_revision: immutable content-addressed publish packages -----------
    op.execute(
        """
        CREATE TABLE design_web_publish_revision (
            publish_id   text NOT NULL,
            workspace_id text NOT NULL,
            slug         text NOT NULL,
            document_id  text NOT NULL,
            doc_version  integer NOT NULL,
            html         text NOT NULL,
            html_digest  text NOT NULL,
            manifest_json   jsonb NOT NULL,
            manifest_digest text NOT NULL,
            package_digest  text NOT NULL,
            runtime_version integer,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_web_publish_revision_pkey PRIMARY KEY (publish_id),
            CONSTRAINT design_web_publish_revision_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_web_publish_revision_workspace_anchor
                UNIQUE (publish_id, workspace_id),
            -- Provenance pin: publish history blocks document deletion (NO ACTION).
            CONSTRAINT design_web_publish_revision_document_fk
                FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id),
            -- The content address is structural, not a naming convention.
            CONSTRAINT design_web_publish_revision_content_address
                CHECK (publish_id = 'webpub_' || package_digest),
            CONSTRAINT design_web_publish_revision_manifest_object
                CHECK (jsonb_typeof(manifest_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_web_publish_revision IS 'Immutable content-addressed web "
        "publish packages (PD D1e): publish_id = webpub_<package_digest>, enforced by CHECK; "
        "UPDATE and DELETE are rejected by trigger (append-only publish history).'"
    )
    op.execute(
        """
        CREATE FUNCTION design_web_publish_revision_reject_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'design_web_publish_revision is immutable: publish packages are content-'
                'addressed history; publish a new package instead of updating one.';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION design_web_publish_revision_reject_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'design_web_publish_revision is append-only: publish history is never '
                'deleted (unpublish flips design_web_publish.status, not history).';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER design_web_publish_revision_no_update "
        "BEFORE UPDATE ON design_web_publish_revision "
        "FOR EACH ROW EXECUTE FUNCTION design_web_publish_revision_reject_update()"
    )
    op.execute(
        "CREATE TRIGGER design_web_publish_revision_no_delete "
        "BEFORE DELETE ON design_web_publish_revision "
        "FOR EACH ROW EXECUTE FUNCTION design_web_publish_revision_reject_delete()"
    )
    op.execute(
        "CREATE INDEX design_web_publish_revision_slug "
        "ON design_web_publish_revision (workspace_id, slug, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX design_web_publish_revision_document "
        "ON design_web_publish_revision (workspace_id, document_id, created_at DESC)"
    )

    # --- design_web_publish: the live serving row per (workspace, slug) — O6 -----------------
    op.execute(
        """
        CREATE TABLE design_web_publish (
            workspace_id text NOT NULL,
            slug         text NOT NULL,
            document_id  text NOT NULL,
            doc_version  integer NOT NULL,
            html         text NOT NULL,
            previous_html        text,
            previous_doc_version integer,
            runtime_version      integer,
            status       design_publish_status NOT NULL DEFAULT 'active',
            publish_id          text,
            previous_publish_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            -- O6 (ratified): slugs are workspace-local; global URL uniqueness is the
            -- serving layer's concern (Part IV; interim rule = O6b at D2).
            CONSTRAINT design_web_publish_pkey PRIMARY KEY (workspace_id, slug),
            CONSTRAINT design_web_publish_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_web_publish_document_fk
                FOREIGN KEY (document_id, workspace_id)
                REFERENCES design_document (id, workspace_id),
            CONSTRAINT design_web_publish_revision_fk
                FOREIGN KEY (publish_id, workspace_id)
                REFERENCES design_web_publish_revision (publish_id, workspace_id),
            CONSTRAINT design_web_publish_previous_revision_fk
                FOREIGN KEY (previous_publish_id, workspace_id)
                REFERENCES design_web_publish_revision (publish_id, workspace_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_web_publish IS 'Live web-publish serving rows (PD D1e; O6 "
        "ratified: PK (workspace_id, slug) — tenant-local slug namespaces). previous_* is the "
        "one-step rollback buffer; full history lives in design_web_publish_revision.'"
    )
    op.execute(
        "CREATE INDEX design_web_publish_document "
        "ON design_web_publish (workspace_id, document_id, updated_at DESC)"
    )

    # --- design_custom_component: account-scoped component identity --------------------------
    # current_source_revision_id's FK is added AFTER the revision table exists (cycle).
    op.execute(
        """
        CREATE TABLE design_custom_component (
            workspace_id text NOT NULL,
            account_id   text NOT NULL,
            slug         text NOT NULL,
            source_version integer NOT NULL DEFAULT 0,
            current_source_revision_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_custom_component_pkey
                PRIMARY KEY (workspace_id, account_id, slug),
            CONSTRAINT design_custom_component_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_custom_component_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES design_account (account_id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_custom_component_slug_shape
                CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
            CONSTRAINT design_custom_component_version_nonneg CHECK (source_version >= 0)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_custom_component IS 'Account-scoped custom-component "
        "identity (PD D1e); revisions/artifacts/compilations hang off (workspace, account, "
        "slug).'"
    )

    # --- design_custom_component_source_revision: immutable source snapshots -----------------
    op.execute(
        """
        CREATE TABLE design_custom_component_source_revision (
            revision_id  text NOT NULL,
            workspace_id text NOT NULL,
            account_id   text NOT NULL,
            slug         text NOT NULL,
            source_version integer NOT NULL,
            entry_path   text NOT NULL,
            snapshot_digest_algorithm text NOT NULL,
            snapshot_digest_value     text NOT NULL,
            snapshot_opaque_ref       text NOT NULL,
            snapshot_byte_length      bigint NOT NULL,
            files_manifest_json jsonb NOT NULL,
            provenance_json     jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_custom_component_source_pkey PRIMARY KEY (revision_id),
            CONSTRAINT design_custom_component_source_id_shape
                CHECK (revision_id ~ '^ccsrc_[0-9a-f]{64}$'),
            CONSTRAINT design_custom_component_source_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_custom_component_source_workspace_anchor
                UNIQUE (revision_id, workspace_id),
            CONSTRAINT design_custom_component_source_component_fk
                FOREIGN KEY (workspace_id, account_id, slug)
                REFERENCES design_custom_component (workspace_id, account_id, slug)
                ON DELETE CASCADE,
            CONSTRAINT design_custom_component_source_version_positive
                CHECK (source_version >= 1),
            CONSTRAINT design_custom_component_source_bytes_positive
                CHECK (snapshot_byte_length >= 1),
            CONSTRAINT design_custom_component_source_version_unique
                UNIQUE (workspace_id, account_id, slug, source_version),
            CONSTRAINT design_custom_component_source_manifest_object
                CHECK (jsonb_typeof(files_manifest_json) = 'object'),
            CONSTRAINT design_custom_component_source_provenance_object
                CHECK (jsonb_typeof(provenance_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_custom_component_source_revision IS 'Immutable "
        "content-addressed component source snapshots (PD D1e): revision_id = ccsrc_<sha256 "
        "of the canonical revision identity>; UPDATE rejected by trigger.'"
    )
    op.execute(
        """
        CREATE FUNCTION design_custom_component_reject_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'custom component % rows are immutable (content-addressed): insert a new '
                'row instead of updating one.', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER design_custom_component_source_no_update "
        "BEFORE UPDATE ON design_custom_component_source_revision "
        "FOR EACH ROW EXECUTE FUNCTION design_custom_component_reject_update()"
    )
    op.execute(
        "CREATE INDEX design_custom_component_source_lookup "
        "ON design_custom_component_source_revision "
        "(workspace_id, account_id, slug, source_version DESC)"
    )
    op.execute(
        "CREATE INDEX design_custom_component_source_digest "
        "ON design_custom_component_source_revision (workspace_id, snapshot_digest_value)"
    )

    # Close the component ↔ revision cycle: the identity row may pin its current revision.
    op.execute(
        """
        ALTER TABLE design_custom_component
            ADD CONSTRAINT design_custom_component_current_revision_fk
                FOREIGN KEY (current_source_revision_id, workspace_id)
                REFERENCES design_custom_component_source_revision (revision_id, workspace_id)
                ON DELETE SET NULL (current_source_revision_id)
        """
    )

    # --- design_custom_component_artifact: immutable compiled bundles ------------------------
    op.execute(
        """
        CREATE TABLE design_custom_component_artifact (
            artifact_id  text NOT NULL,
            workspace_id text NOT NULL,
            account_id   text NOT NULL,
            slug         text NOT NULL,
            source_digest_algorithm text NOT NULL,
            source_digest_value     text NOT NULL,
            source_opaque_ref       text NOT NULL,
            source_byte_length      bigint NOT NULL,
            bundle_digest_algorithm text NOT NULL,
            bundle_digest_value     text NOT NULL,
            bundle_opaque_ref       text NOT NULL,
            bundle_byte_length      bigint NOT NULL,
            css_digest_algorithm text,
            css_digest_value     text,
            css_opaque_ref       text,
            css_byte_length      bigint,
            first_frame_digest_algorithm text,
            first_frame_digest_value     text,
            first_frame_opaque_ref       text,
            first_frame_byte_length      bigint,
            manifest_json   jsonb NOT NULL,
            provenance_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_custom_component_artifact_pkey PRIMARY KEY (artifact_id),
            CONSTRAINT design_custom_component_artifact_id_shape
                CHECK (artifact_id ~ '^ccart_[0-9a-f]{64}$'),
            CONSTRAINT design_custom_component_artifact_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT design_custom_component_artifact_workspace_anchor
                UNIQUE (artifact_id, workspace_id),
            CONSTRAINT design_custom_component_artifact_component_fk
                FOREIGN KEY (workspace_id, account_id, slug)
                REFERENCES design_custom_component (workspace_id, account_id, slug)
                ON DELETE CASCADE,
            CONSTRAINT design_custom_component_artifact_manifest_object
                CHECK (jsonb_typeof(manifest_json) = 'object'),
            CONSTRAINT design_custom_component_artifact_provenance_object
                CHECK (jsonb_typeof(provenance_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_custom_component_artifact IS 'Immutable compiled "
        "custom-component bundles (PD D1e): artifact_id = ccart_<sha256>; opaque refs point "
        "into the content-addressed store (platform storage from D4); UPDATE rejected by "
        "trigger.'"
    )
    op.execute(
        "CREATE TRIGGER design_custom_component_artifact_no_update "
        "BEFORE UPDATE ON design_custom_component_artifact "
        "FOR EACH ROW EXECUTE FUNCTION design_custom_component_reject_update()"
    )
    op.execute(
        "CREATE INDEX design_custom_component_artifact_lookup "
        "ON design_custom_component_artifact (workspace_id, account_id, slug, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX design_custom_component_artifact_source_digest "
        "ON design_custom_component_artifact (workspace_id, source_digest_value)"
    )
    op.execute(
        "CREATE INDEX design_custom_component_artifact_bundle_digest "
        "ON design_custom_component_artifact (workspace_id, bundle_digest_value)"
    )

    # --- design_custom_component_compilation: immutable compiler outcomes --------------------
    op.execute(
        """
        CREATE TABLE design_custom_component_compilation (
            compilation_id text NOT NULL,
            workspace_id   text NOT NULL,
            account_id     text NOT NULL,
            slug           text NOT NULL,
            source_revision_id text NOT NULL,
            source_version     integer NOT NULL,
            status         design_compilation_status NOT NULL,
            compiler_protocol_version integer NOT NULL,
            compiler_version          text NOT NULL,
            diagnostics_json jsonb NOT NULL,
            artifact_id    text,
            created_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_custom_component_compilation_pkey PRIMARY KEY (compilation_id),
            CONSTRAINT design_custom_component_compilation_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT design_custom_component_compilation_source_fk
                FOREIGN KEY (source_revision_id, workspace_id)
                REFERENCES design_custom_component_source_revision (revision_id, workspace_id)
                ON DELETE CASCADE,
            -- Real FK now (SQLite left it dangling); a purged artifact detaches the pointer.
            CONSTRAINT design_custom_component_compilation_artifact_fk
                FOREIGN KEY (artifact_id, workspace_id)
                REFERENCES design_custom_component_artifact (artifact_id, workspace_id)
                ON DELETE SET NULL (artifact_id),
            CONSTRAINT design_custom_component_compilation_version_positive
                CHECK (source_version >= 1),
            CONSTRAINT design_custom_component_compilation_diagnostics_array
                CHECK (jsonb_typeof(diagnostics_json) = 'array')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_custom_component_compilation IS 'Immutable custom-component "
        "compiler outcomes (PD D1e); UPDATE rejected by trigger.'"
    )
    op.execute(
        "CREATE TRIGGER design_custom_component_compilation_no_update "
        "BEFORE UPDATE ON design_custom_component_compilation "
        "FOR EACH ROW EXECUTE FUNCTION design_custom_component_reject_update()"
    )
    op.execute(
        "CREATE INDEX design_custom_component_compilation_lookup "
        "ON design_custom_component_compilation "
        "(workspace_id, account_id, slug, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX design_custom_component_compilation_source "
        "ON design_custom_component_compilation (source_revision_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_custom_component_compilation")
    op.execute("DROP TABLE design_custom_component_artifact")
    op.execute(
        "ALTER TABLE design_custom_component "
        "DROP CONSTRAINT design_custom_component_current_revision_fk"
    )
    op.execute("DROP TABLE design_custom_component_source_revision")
    op.execute("DROP FUNCTION design_custom_component_reject_update")
    op.execute("DROP TABLE design_custom_component")
    op.execute("DROP TABLE design_web_publish")
    op.execute("DROP TABLE design_web_publish_revision")
    op.execute("DROP FUNCTION design_web_publish_revision_reject_delete")
    op.execute("DROP FUNCTION design_web_publish_revision_reject_update")
    op.execute("DROP TABLE design_web_batch")
    op.execute("ALTER TABLE design_document DROP CONSTRAINT design_document_account_fk")
    op.execute("DROP TABLE design_account")
    op.execute("DROP TYPE design_compilation_status")
    op.execute("DROP TYPE design_publish_status")
