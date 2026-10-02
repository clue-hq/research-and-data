"""arv3 quality context evidence and claim assessments

Revision ID: 68e3053b58f2
Revises: 213dea37b230
Create Date: 2026-09-22 17:31:11.687660+00:00

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
revision: str = "68e3053b58f2"
down_revision: str | None = "213dea37b230"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("workspace_field_definition_research_shape", "workspace_field_definition")
    op.create_check_constraint(
        "workspace_field_definition_research_shape",
        "workspace_field_definition",
        _research_shape(allow_agent=True),
    )
    _workspace_pack(allow_facets=True)
    op.execute("""
      CREATE TABLE artifact_reference (
        workspace_id text NOT NULL,
        reference_kind text NOT NULL,
        reference_id text NOT NULL,
        storage_key text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT artifact_reference_pk
          PRIMARY KEY(workspace_id,reference_kind,reference_id,storage_key),
        CONSTRAINT artifact_reference_artifact_fk FOREIGN KEY(storage_key,workspace_id)
          REFERENCES artifact(storage_key,workspace_id),
        CONSTRAINT artifact_reference_kind CHECK (length(reference_kind) BETWEEN 1 AND 100),
        CONSTRAINT artifact_reference_identity CHECK (length(reference_id) BETWEEN 1 AND 200)
      )
    """)
    op.execute("CREATE INDEX artifact_reference_key ON artifact_reference(storage_key)")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT knowledge_document_scope "
        "UNIQUE (document_id, workspace_id)"
    )
    op.execute("ALTER TABLE brand_knowledge_document ADD COLUMN source_icp_document_id uuid")
    op.execute("ALTER TABLE brand_knowledge_document ADD COLUMN source_icp_sha256 text")
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT knowledge_persona_source_fk "
        "FOREIGN KEY (source_icp_document_id, workspace_id) "
        "REFERENCES brand_knowledge_document (document_id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE brand_knowledge_document ADD CONSTRAINT knowledge_persona_source_shape "
        "CHECK ((source_icp_document_id IS NULL) = (source_icp_sha256 IS NULL) AND "
        "(source_icp_sha256 IS NULL OR source_icp_sha256 ~ '^[0-9a-f]{64}$'))"
    )
    op.execute("""
      CREATE TABLE arv2_research_context_pin (
        context_id uuid PRIMARY KEY,
        workspace_id text NOT NULL,
        project_id text NOT NULL,
        brand_id text NOT NULL,
        manifest_key text NOT NULL,
        manifest_sha256 text NOT NULL,
        icp_document_id uuid NOT NULL,
        product_selection_version integer NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT arv2_context_scope UNIQUE (context_id, workspace_id),
        CONSTRAINT arv2_context_project_scope UNIQUE (context_id, workspace_id, project_id),
        CONSTRAINT arv2_context_digest CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT arv2_context_selection CHECK (product_selection_version > 0),
        CONSTRAINT arv2_context_identity UNIQUE (workspace_id, project_id, manifest_sha256),
        CONSTRAINT arv2_context_project_fk FOREIGN KEY (project_id, workspace_id)
          REFERENCES project(project_id, workspace_id),
        CONSTRAINT arv2_context_brand_fk FOREIGN KEY (brand_id, workspace_id)
          REFERENCES brand(brand_id, workspace_id),
        CONSTRAINT arv2_context_document_fk FOREIGN KEY (icp_document_id, workspace_id)
          REFERENCES brand_knowledge_document(document_id, workspace_id),
        CONSTRAINT arv2_context_artifact_fk FOREIGN KEY (manifest_key, workspace_id)
          REFERENCES artifact(storage_key, workspace_id)
      )
    """)
    op.execute("ALTER TABLE arv2_research_run ADD COLUMN context_id uuid")
    op.execute(
        "ALTER TABLE arv2_research_run ADD CONSTRAINT arv2_run_context_fk "
        "FOREIGN KEY (context_id, workspace_id, project_id) "
        "REFERENCES arv2_research_context_pin(context_id, workspace_id, project_id)"
    )

    # Exact document pins keep bytes alive, while authorized erasure still overrides reuse.
    op.execute("""
      CREATE TABLE arv2_context_document (
        context_id uuid NOT NULL,
        workspace_id text NOT NULL,
        document_id uuid NOT NULL,
        artifact_key text NOT NULL,
        role text NOT NULL,
        CONSTRAINT arv2_context_document_role CHECK (role IN ('icp','persona','seller')),
        PRIMARY KEY (context_id, document_id),
        FOREIGN KEY (context_id, workspace_id)
          REFERENCES arv2_research_context_pin(context_id, workspace_id) ON DELETE CASCADE,
        FOREIGN KEY (document_id, workspace_id)
          REFERENCES brand_knowledge_document(document_id, workspace_id),
        FOREIGN KEY (artifact_key, workspace_id) REFERENCES artifact(storage_key, workspace_id)
      )
    """)
    op.execute("CREATE INDEX arv2_context_document_artifact ON arv2_context_document(artifact_key)")


def downgrade() -> None:
    _workspace_pack(allow_facets=False)
    op.drop_constraint("workspace_field_definition_research_shape", "workspace_field_definition")
    op.create_check_constraint(
        "workspace_field_definition_research_shape",
        "workspace_field_definition",
        _research_shape(allow_agent=False),
    )
    op.execute("DROP TABLE arv2_context_document")
    op.execute("ALTER TABLE arv2_research_run DROP CONSTRAINT arv2_run_context_fk")
    op.execute("ALTER TABLE arv2_research_run DROP COLUMN context_id")
    op.execute("DROP TABLE arv2_research_context_pin")
    op.execute(
        "ALTER TABLE brand_knowledge_document DROP CONSTRAINT knowledge_persona_source_shape"
    )
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT knowledge_persona_source_fk")
    op.execute("ALTER TABLE brand_knowledge_document DROP COLUMN source_icp_sha256")
    op.execute("ALTER TABLE brand_knowledge_document DROP COLUMN source_icp_document_id")
    op.execute("ALTER TABLE brand_knowledge_document DROP CONSTRAINT knowledge_document_scope")
    op.execute("DROP TABLE artifact_reference")


def _research_shape(*, allow_agent: bool) -> str:
    origin = "(promotion_policy_version = 'settings-v1' AND promoted_by LIKE 'human:%')"
    if allow_agent:
        origin += " OR (promotion_policy_version = 'research-quality-v1' "
        origin += "AND promoted_by LIKE 'agent:%')"
    return (
        "client_kb_role <> 'research' OR (label IS NOT NULL AND "
        "length(btrim(label)) BETWEEN 1 AND 200 AND description IS NOT NULL AND "
        "length(btrim(description)) BETWEEN 1 AND 2000 AND value_type = 'json' AND "
        "value_schema IS NULL AND pass_kind = 'deep' AND research_scope IS NOT NULL AND "
        "research_scope = 'project_neutral' AND product_scope IS NOT NULL AND "
        "product_scope = 'forbidden' AND promoted_from_proposal_id IS NULL AND (" + origin + "))"
    )


def _workspace_pack(*, allow_facets: bool) -> None:
    op.drop_constraint("workspace_field_definition_pack", "workspace_field_definition")
    account = (
        "field_class IN ('account', 'account.resonance')"
        if allow_facets
        else "field_class='account'"
    )
    contact = (
        "field_class IN ('contact', 'contact.facet')" if allow_facets else "field_class='contact'"
    )
    op.create_check_constraint(
        "workspace_field_definition_pack",
        "workspace_field_definition",
        "(client_kb_role='extended' AND field_key LIKE 'client.%' AND field_class='pack' "
        "AND pack='client' AND pack IS NOT NULL AND promoted_from_proposal_id IS NOT NULL) OR "
        "(client_kb_role='research' AND pack IS NULL AND "
        f"((field_key LIKE 'account.%' AND {account}) OR "
        f"(field_key LIKE 'contact.%' AND {contact})))",
    )
