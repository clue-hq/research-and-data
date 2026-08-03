"""tenant local dynamic client kb fields

Revision ID: 282b9c7278c2
Revises: 933c7b604f1c
Create Date: 2026-08-02 22:17:18.527524+00:00

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
revision: str = "282b9c7278c2"
down_revision: str | None = "933c7b604f1c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The proposal id remains globally unique, but a composite candidate key lets every promoted
    # definition prove that the proposal and definition belong to the same workspace in SQL.
    op.create_unique_constraint(
        "field_definition_revision_id_workspace_key",
        "field_definition_revision",
        ["id", "workspace_id"],
    )
    op.create_unique_constraint(
        "volunteered_statement_id_workspace_key",
        "volunteered_statement",
        ["id", "workspace_id"],
    )
    op.create_unique_constraint(
        "claim_id_workspace_key",
        "claim",
        ["id", "workspace_id"],
    )

    op.execute(
        """
        CREATE TABLE workspace_field_definition (
            workspace_id               text NOT NULL,
            field_key                  text NOT NULL,
            value_type                 text NOT NULL,
            validation                 jsonb,
            value_schema               jsonb,
            tier_plan                  jsonb NOT NULL DEFAULT '[]'::jsonb,
            freshness_ttl              interval,
            pass_kind                  field_pass NOT NULL,
            gate                       text,
            signal_class               text,
            reuse_scope                reuse_scope NOT NULL DEFAULT 'tenant_private',
            field_class                field_class NOT NULL,
            corroboration_min          int NOT NULL DEFAULT 1,
            single_source_sufficient   boolean NOT NULL DEFAULT false,
            equality_mode              equality_mode NOT NULL DEFAULT 'exact',
            description                text,
            pack                       text NOT NULL DEFAULT 'client',
            client_kb_role             text NOT NULL DEFAULT 'extended',
            active                     boolean NOT NULL DEFAULT true,
            definition_version         int NOT NULL DEFAULT 1,
            promoted_from_proposal_id  uuid NOT NULL,
            promotion_policy_version   text NOT NULL,
            promoted_by                text NOT NULL,
            promoted_at                timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT workspace_field_definition_pkey
                PRIMARY KEY (workspace_id, field_key),
            CONSTRAINT workspace_field_definition_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_field_definition_proposal_fk
                FOREIGN KEY (promoted_from_proposal_id, workspace_id)
                REFERENCES field_definition_revision (id, workspace_id),
            CONSTRAINT workspace_field_definition_proposal_unique
                UNIQUE (promoted_from_proposal_id),
            CONSTRAINT workspace_field_definition_client_namespace
                CHECK (field_key LIKE 'client.%'),
            CONSTRAINT workspace_field_definition_private
                CHECK (reuse_scope = 'tenant_private'),
            CONSTRAINT workspace_field_definition_pack
                CHECK (field_class = 'pack' AND pack = 'client'),
            CONSTRAINT workspace_field_definition_role
                CHECK (client_kb_role = 'extended'),
            CONSTRAINT workspace_field_definition_active
                CHECK (active),
            CONSTRAINT workspace_field_definition_version
                CHECK (definition_version >= 1),
            CONSTRAINT workspace_field_definition_tier_plan
                CHECK (jsonb_typeof(tier_plan) = 'array'),
            CONSTRAINT workspace_field_definition_value_schema
                CHECK (value_schema IS NULL OR jsonb_typeof(value_schema) = 'object'),
            CONSTRAINT workspace_field_definition_corroboration_min
                CHECK (corroboration_min >= 1)
        )
        """
    )
    op.execute(
        "CREATE INDEX workspace_field_definition_list "
        "ON workspace_field_definition (workspace_id, active, field_key)"
    )

    # Retirement is append-only policy state; the immutable definition row is never rewritten.
    op.execute(
        """
        CREATE TABLE workspace_field_retirement (
            workspace_id  text NOT NULL,
            field_key     text NOT NULL,
            retired_by   text NOT NULL,
            reason       text NOT NULL,
            retired_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT workspace_field_retirement_pkey PRIMARY KEY (workspace_id, field_key),
            CONSTRAINT workspace_field_retirement_definition_fk
                FOREIGN KEY (workspace_id, field_key)
                REFERENCES workspace_field_definition (workspace_id, field_key)
        )
        """
    )

    # The receipt is one terminal, replay-safe record. Refusals preserve the statement/proposal and
    # carry only a bounded reason code; successful rows reference the one claim/version produced.
    op.execute(
        """
        CREATE TABLE workspace_field_materialization (
            id                 uuid PRIMARY KEY,
            workspace_id       text NOT NULL,
            field_proposal_id  uuid NOT NULL,
            statement_id       uuid NOT NULL,
            field_key          text NOT NULL,
            value_digest       text NOT NULL,
            status             text NOT NULL,
            claim_id           uuid,
            client_entity_id   uuid,
            client_kb_version  int,
            run_id             uuid,
            refusal_code       text,
            completed_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT workspace_field_materialization_identity UNIQUE (
                workspace_id, field_proposal_id, statement_id, field_key, value_digest
            ),
            CONSTRAINT workspace_field_materialization_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_field_materialization_proposal_fk
                FOREIGN KEY (field_proposal_id, workspace_id)
                REFERENCES field_definition_revision (id, workspace_id),
            CONSTRAINT workspace_field_materialization_statement_fk
                FOREIGN KEY (statement_id, workspace_id)
                REFERENCES volunteered_statement (id, workspace_id),
            CONSTRAINT workspace_field_materialization_definition_fk
                FOREIGN KEY (workspace_id, field_key)
                REFERENCES workspace_field_definition (workspace_id, field_key),
            CONSTRAINT workspace_field_materialization_claim_fk
                FOREIGN KEY (claim_id, workspace_id) REFERENCES claim (id, workspace_id),
            CONSTRAINT workspace_field_materialization_client_fk
                FOREIGN KEY (client_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT workspace_field_materialization_digest
                CHECK (value_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT workspace_field_materialization_status
                CHECK (status IN ('materialized', 'refused')),
            CONSTRAINT workspace_field_materialization_result CHECK (
                (
                    status = 'materialized'
                    AND claim_id IS NOT NULL
                    AND client_entity_id IS NOT NULL
                    AND client_kb_version >= 1
                    AND run_id IS NOT NULL
                    AND refusal_code IS NULL
                )
                OR
                (
                    status = 'refused'
                    AND claim_id IS NULL
                    AND refusal_code IS NOT NULL
                )
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX workspace_field_materialization_scope "
        "ON workspace_field_materialization (workspace_id, field_proposal_id, completed_at DESC)"
    )

    # Optional tenant-local readiness requirements are a separate, human-authored versioned policy;
    # merely registering an extended field can never change the baseline denominator.
    op.execute(
        """
        CREATE TABLE workspace_client_kb_readiness_policy (
            workspace_id        text NOT NULL,
            version             int NOT NULL,
            required_field_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
            policy_hash         text NOT NULL,
            decided_by          text NOT NULL,
            decision_reason     text NOT NULL,
            created_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT workspace_client_kb_readiness_policy_pkey
                PRIMARY KEY (workspace_id, version),
            CONSTRAINT workspace_client_kb_readiness_policy_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_client_kb_readiness_policy_version CHECK (version >= 1),
            CONSTRAINT workspace_client_kb_readiness_policy_keys
                CHECK (jsonb_typeof(required_field_keys) = 'array'),
            CONSTRAINT workspace_client_kb_readiness_policy_hash
                CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT workspace_client_kb_readiness_policy_human
                CHECK (decided_by LIKE 'human:%')
        )
        """
    )

    for table in (
        "workspace_field_definition",
        "workspace_field_retirement",
        "workspace_field_materialization",
        "workspace_client_kb_readiness_policy",
    ):
        function = f"{table}_reject_update"
        trigger = f"{table}_immutable"
        op.execute(
            f"""
            CREATE FUNCTION {function}() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '{table} is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )

    # Compatibility repair for the old C2 path. A non-baseline client.* row promoted by exactly
    # one workspace proposal is private schema that was accidentally placed in the global table.
    # Ambiguous multi-workspace ownership aborts migration rather than silently fanning it out.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM field_definition_revision
                WHERE status = 'promoted'
                  AND field_key LIKE 'client.%'
                  AND field_key NOT IN (
                      'client.value_prop', 'client.product', 'client.differentiator',
                      'client.pricing_posture', 'client.proof_point', 'client.customer',
                      'client.icp_evidence', 'client.market_reputation',
                      'client.delivered_value', 'client.kb_version'
                  )
                GROUP BY field_key
                HAVING count(DISTINCT workspace_id) > 1
            ) THEN
                RAISE EXCEPTION
                    'ambiguous tenant-promoted client field exists in more than one workspace';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        INSERT INTO workspace_field_definition (
            workspace_id, field_key, value_type, validation, value_schema, tier_plan,
            freshness_ttl, pass_kind, gate, signal_class, reuse_scope, field_class,
            corroboration_min, single_source_sufficient, equality_mode, description, pack,
            client_kb_role, active, definition_version, promoted_from_proposal_id,
            promotion_policy_version, promoted_by, promoted_at
        )
        SELECT r.workspace_id, f.field_key, f.value_type, f.validation, f.value_schema, f.tier_plan,
               f.freshness_ttl, f.pass_kind, f.gate, f.signal_class, 'tenant_private',
               f.field_class,
               f.corroboration_min, f.single_source_sufficient, f.equality_mode, f.description,
               'client', 'extended', true, f.version, r.id, 'legacy-c2-migration-v1',
               COALESCE(r.decided_by, 'system:legacy-c2-migration'),
               COALESCE(r.decided_at, r.proposed_at)
        FROM field_definition_revision r
        JOIN field_definition f ON f.field_key = r.field_key
        WHERE r.status = 'promoted'
          AND r.field_key LIKE 'client.%'
          AND r.field_key NOT IN (
              'client.value_prop', 'client.product', 'client.differentiator',
              'client.pricing_posture', 'client.proof_point', 'client.customer',
              'client.icp_evidence', 'client.market_reputation',
              'client.delivered_value', 'client.kb_version'
          )
        ON CONFLICT (workspace_id, field_key) DO NOTHING
        """
    )
    op.execute(
        """
        DELETE FROM field_definition f
        USING workspace_field_definition w
        WHERE f.field_key = w.field_key
          AND w.promotion_policy_version = 'legacy-c2-migration-v1'
        """
    )


def downgrade() -> None:
    # Restore compatibility-migrated rows before removing the workspace overlay. The exact schema
    # was copied from these rows on upgrade, so this is a lossless reversal for the legacy case.
    op.execute(
        """
        INSERT INTO field_definition (
            field_key, value_type, validation, tier_plan, freshness_ttl, pass_kind, gate,
            signal_class, reuse_scope, field_class, value_schema, corroboration_min,
            single_source_sufficient, equality_mode, description, active, pack, version
        )
        SELECT field_key, value_type, validation, tier_plan, freshness_ttl, pass_kind, gate,
               signal_class, reuse_scope, field_class, value_schema, corroboration_min,
               single_source_sufficient, equality_mode, description, active, pack,
               definition_version
        FROM workspace_field_definition
        WHERE promotion_policy_version = 'legacy-c2-migration-v1'
        ON CONFLICT (field_key) DO NOTHING
        """
    )

    for table in (
        "workspace_client_kb_readiness_policy",
        "workspace_field_materialization",
        "workspace_field_retirement",
        "workspace_field_definition",
    ):
        trigger = f"{table}_immutable"
        function = f"{table}_reject_update"
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")
        op.drop_table(table)

    op.drop_constraint(
        "claim_id_workspace_key",
        "claim",
        type_="unique",
    )
    op.drop_constraint(
        "volunteered_statement_id_workspace_key",
        "volunteered_statement",
        type_="unique",
    )
    op.drop_constraint(
        "field_definition_revision_id_workspace_key",
        "field_definition_revision",
        type_="unique",
    )
