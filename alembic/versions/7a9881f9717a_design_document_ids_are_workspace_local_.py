"""design document ids are workspace local (part2 D2.2g)

Revision ID: 7a9881f9717a
Revises: e79f192828b1
Create Date: 2026-08-08

Part II D2.2 follow-up to the D1 schema, surfaced by the D2.2 port: **document ids are
client-suppliable** (a scene payload carries ``meta.id``; the API honours it), so a GLOBAL
``design_document`` primary key would let one workspace squat an id for every other tenant —
exactly the wart the founder's O6 ruling rejected for publish slugs. Same medicine:

* ``design_document`` PK becomes ``(id, workspace_id)``. Safe re-key: every child FK already
  targets the composite ``design_document_workspace_anchor (id, workspace_id)``, which stays;
  only the standalone ``PRIMARY KEY (id)`` falls away (nothing references it).
* The per-document sequence keys gain the workspace column for the same reason —
  ``design_operation_log`` PK → ``(document_id, workspace_id, sequence)``;
  ``design_edit_envelope``'s doc-seq unique → ``(document_id, workspace_id, seq)`` — so two
  workspaces holding the same client-supplied doc id keep independent, gapless histories.
  (The D2.1 allocators filter their MAX() by workspace accordingly.)
* The same workspace-locality applies to every design id namespace whose ids are
  **client-supplied** (``design_template_revision`` — finalize passes the id;
  ``design_account`` — importable ids; ``design_brand_kit`` — the kit payload carries its id)
  or **content-derived** (``design_web_publish_revision`` = ``webpub_<package sha>``;
  ``design_custom_component_source_revision``/``_artifact`` = ``ccsrc_``/``ccart_<sha>`` —
  identical content in two workspaces yields the SAME id, so a global PK would make one
  tenant's publish block another's). Each PK gains ``workspace_id``; safe re-keys — every
  child FK already targets the surviving composite ``*_workspace_anchor``, never the old PK.
  Server-minted-uuid namespaces (snapshots, binding sets, batches, runs, jobs, compilations —
  and instances/repairs, whose deterministic ids embed a uuid-minted binding id) stay global:
  collision is impossible by construction.

Hand-written and reversible: ``downgrade()`` restores the global keys (raising loudly is not
needed — a downgrade with cross-workspace duplicate ids fails naturally on the PK rebuild).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a9881f9717a"
down_revision: str | None = "e79f192828b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE design_document
            DROP CONSTRAINT design_document_pkey,
            ADD CONSTRAINT design_document_pkey PRIMARY KEY (id, workspace_id)
        """
    )
    # Staged-port deferral: design_account is not populated until D2.4 (accounts still live in
    # the SQLite web_accounts table), so a document's account stamp cannot satisfy this FK yet.
    # The column keeps its SQLite-era advisory semantics until D2.4 RE-ADDS the constraint with
    # the account port (tracked in the PD contract's D2.4 scope).
    op.execute("ALTER TABLE design_document DROP CONSTRAINT design_document_account_fk")
    # The D1a inventory under-read the effective-brand closed set: the runtime also assigns
    # 'platform_default' (4 call sites in lumen_api/main.py). ADD VALUE appends at the end, so
    # clue_design.enums keeps definition-order parity. (Precedent d9b39fb407ed; the member
    # deliberately survives downgrade — PG cannot drop an enum label without a type rebuild,
    # and a surplus label is harmless to the D1a schema.)
    op.execute(
        "ALTER TYPE design_effective_brand_source ADD VALUE IF NOT EXISTS 'platform_default'"
    )
    # Client-supplied / content-derived id namespaces become workspace-local (docstring).
    for table, pkey_cols in (
        ("design_template_revision", "template_revision_id, workspace_id"),
        ("design_account", "account_id, workspace_id"),
        ("design_brand_kit", "brand_kit_id, version, workspace_id"),
        ("design_web_publish_revision", "publish_id, workspace_id"),
        ("design_custom_component_source_revision", "revision_id, workspace_id"),
        ("design_custom_component_artifact", "artifact_id, workspace_id"),
    ):
        pkey = {
            "design_custom_component_source_revision": "design_custom_component_source_pkey",
            "design_custom_component_artifact": "design_custom_component_artifact_pkey",
        }.get(table, f"{table}_pkey")
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT {pkey}, "
            f"ADD CONSTRAINT {pkey} PRIMARY KEY ({pkey_cols})"
        )
    op.execute(
        """
        ALTER TABLE design_operation_log
            DROP CONSTRAINT design_operation_log_pkey,
            ADD CONSTRAINT design_operation_log_pkey
                PRIMARY KEY (document_id, workspace_id, sequence)
        """
    )
    op.execute(
        """
        ALTER TABLE design_edit_envelope
            DROP CONSTRAINT design_edit_envelope_doc_seq_unique,
            ADD CONSTRAINT design_edit_envelope_doc_seq_unique
                UNIQUE (document_id, workspace_id, seq)
        """
    )


def downgrade() -> None:
    for table, pkey_cols in (
        ("design_custom_component_artifact", "artifact_id"),
        ("design_custom_component_source_revision", "revision_id"),
        ("design_web_publish_revision", "publish_id"),
        ("design_brand_kit", "brand_kit_id, version"),
        ("design_account", "account_id"),
        ("design_template_revision", "template_revision_id"),
    ):
        pkey = {
            "design_custom_component_source_revision": "design_custom_component_source_pkey",
            "design_custom_component_artifact": "design_custom_component_artifact_pkey",
        }.get(table, f"{table}_pkey")
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT {pkey}, "
            f"ADD CONSTRAINT {pkey} PRIMARY KEY ({pkey_cols})"
        )
    op.execute(
        """
        ALTER TABLE design_document
            ADD CONSTRAINT design_document_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES design_account (account_id, workspace_id)
                ON DELETE SET NULL (account_id)
        """
    )
    op.execute(
        """
        ALTER TABLE design_edit_envelope
            DROP CONSTRAINT design_edit_envelope_doc_seq_unique,
            ADD CONSTRAINT design_edit_envelope_doc_seq_unique UNIQUE (document_id, seq)
        """
    )
    op.execute(
        """
        ALTER TABLE design_operation_log
            DROP CONSTRAINT design_operation_log_pkey,
            ADD CONSTRAINT design_operation_log_pkey PRIMARY KEY (document_id, sequence)
        """
    )
    op.execute(
        """
        ALTER TABLE design_document
            DROP CONSTRAINT design_document_pkey,
            ADD CONSTRAINT design_document_pkey PRIMARY KEY (id)
        """
    )
