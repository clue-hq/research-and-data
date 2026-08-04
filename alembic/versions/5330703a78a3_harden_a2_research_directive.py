"""harden a2 research directive

Revision ID: 5330703a78a3
Revises: 8f44b739674c
Create Date: 2026-08-04 07:17:22.956053+00:00

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
revision: str = "5330703a78a3"
down_revision: str | None = "8f44b739674c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Resolve both explicit selections and discovery-seal selections once, at draft time.  Every
    # later execution edge can then use a relational FK instead of reparsing mutable caller input.
    op.execute(
        """
        CREATE TABLE account_research_directive_account (
            directive_id  uuid NOT NULL,
            workspace_id  text NOT NULL,
            account_id    uuid NOT NULL,
            scope_kind    text NOT NULL,
            selection_ref text,
            created_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT account_research_directive_account_pkey
                PRIMARY KEY (directive_id, account_id),
            CONSTRAINT account_research_directive_account_directive_fk
                FOREIGN KEY (directive_id, workspace_id)
                REFERENCES account_research_directive (directive_id, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT account_research_directive_account_entity_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT account_research_directive_account_scope_kind
                CHECK (scope_kind IN ('explicit', 'discovery_seal')),
            CONSTRAINT account_research_directive_account_selection_shape CHECK (
                (scope_kind = 'explicit' AND selection_ref IS NULL)
                OR (scope_kind = 'discovery_seal' AND selection_ref IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX account_research_directive_account_lookup "
        "ON account_research_directive_account (workspace_id, account_id, directive_id)"
    )
    op.execute(
        """
        INSERT INTO account_research_directive_account
            (directive_id, workspace_id, account_id, scope_kind)
        SELECT directive.directive_id, directive.workspace_id, value::uuid, 'explicit'
        FROM account_research_directive directive
        CROSS JOIN LATERAL jsonb_array_elements_text(
            directive.content_json -> 'account_scope' -> 'explicit_account_ids'
        ) value
        """
    )
    # A strict ref was not previously enforced. Backfill any already-written strict sealed ref so
    # a branch database can upgrade without weakening membership; malformed legacy refs remain
    # deliberately unlaunchable because they produce no membership rows.
    op.execute(
        """
        INSERT INTO account_research_directive_account
            (directive_id, workspace_id, account_id, scope_kind, selection_ref)
        SELECT directive.directive_id, directive.workspace_id, account.value::uuid,
               'discovery_seal',
               directive.content_json -> 'account_scope' ->> 'sealed_selection_ref'
        FROM account_research_directive directive
        JOIN discovery_batch_seal seal
          ON seal.workspace_id = directive.workspace_id
         AND ('discovery-seal:' || seal.batch_id::text || ':' || seal.seal_sha256) =
             directive.content_json -> 'account_scope' ->> 'sealed_selection_ref'
        JOIN discovery_batch_manifest manifest
          ON manifest.batch_id = seal.batch_id AND manifest.workspace_id = seal.workspace_id
         AND manifest.project_id = directive.project_id
         AND manifest.icp_key = directive.icp_key
         AND manifest.icp_version = directive.icp_version
        CROSS JOIN LATERAL jsonb_array_elements_text(manifest.account_ids) account(value)
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        CREATE FUNCTION account_research_directive_account_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'research directive account membership is immutable';
            END IF;
            IF EXISTS (
                SELECT 1 FROM account_research_directive
                WHERE directive_id = OLD.directive_id
            ) THEN
                RAISE EXCEPTION 'research directive account membership is lifecycle-owned';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_research_directive_account_immutable "
        "BEFORE UPDATE OR DELETE ON account_research_directive_account FOR EACH ROW "
        "EXECUTE FUNCTION account_research_directive_account_guard()"
    )
    op.execute(
        "ALTER TABLE account_research_directive_override "
        "ADD CONSTRAINT account_research_directive_override_membership_fk "
        "FOREIGN KEY (directive_id, account_id) "
        "REFERENCES account_research_directive_account (directive_id, account_id)"
    )
    op.execute(
        "ALTER TABLE account_run ADD CONSTRAINT account_run_research_directive_account_fk "
        "FOREIGN KEY (research_directive_id, entity_id) "
        "REFERENCES account_research_directive_account (directive_id, account_id)"
    )

    # Project-scoped reverse bindings prevent deletion from orphaning generated context bytes.
    # RESTRICT is intentional: callers must run AgentPrivacyService.erase_project first.
    op.execute(
        """
        CREATE TABLE agent_artifact_project (
            workspace_id text NOT NULL,
            project_id   text NOT NULL,
            artifact_key text NOT NULL,
            binding_kind text NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_artifact_project_pkey
                PRIMARY KEY (workspace_id, project_id, artifact_key),
            CONSTRAINT agent_artifact_project_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id) ON DELETE RESTRICT,
            CONSTRAINT agent_artifact_project_artifact_fk
                FOREIGN KEY (artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT agent_artifact_project_kind
                CHECK (length(btrim(binding_kind)) > 0),
            CONSTRAINT agent_artifact_project_scope
                CHECK (split_part(artifact_key, '/', 1) = workspace_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_artifact_project_lookup "
        "ON agent_artifact_project (workspace_id, project_id, artifact_key)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX agent_artifact_project_lookup")
    op.execute("DROP TABLE agent_artifact_project")
    op.execute("ALTER TABLE account_run DROP CONSTRAINT account_run_research_directive_account_fk")
    op.execute(
        "ALTER TABLE account_research_directive_override "
        "DROP CONSTRAINT account_research_directive_override_membership_fk"
    )
    op.execute(
        "DROP TRIGGER account_research_directive_account_immutable "
        "ON account_research_directive_account"
    )
    op.execute("DROP FUNCTION account_research_directive_account_guard()")
    op.execute("DROP INDEX account_research_directive_account_lookup")
    op.execute("DROP TABLE account_research_directive_account")
