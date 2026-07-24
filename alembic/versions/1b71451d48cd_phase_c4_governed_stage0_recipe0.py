"""Phase C4 governed Stage 0, product lineage, readiness, and Recipe #0 pins.

Revision ID: 1b71451d48cd
Revises: fc1f3d22a167
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "1b71451d48cd"
down_revision: str | None = "fc1f3d22a167"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLAIM_IMMUTABLE = (
    "id",
    "entity_id",
    "entity_type",
    "field_key",
    "value_json",
    "source_url",
    "source_tier",
    "extraction_method",
    "evidence_span",
    "confidence",
    "observed_at",
    "collected_at",
    "cost_cents",
    "run_id",
    "research_mode",
    "identity_binding",
    "use_class",
    "discovery_provenance",
    "claim_flavor",
    "workspace_id",
    "reuse_scope",
    "source_key",
    "artifact_key",
)
_CLAIM_MUTABLE = ("superseded_by", "verification_status", "corroborations")
_ICP_IMMUTABLE = (
    "workspace_id",
    "icp_key",
    "version",
    "created_from",
    "parent_version",
    "label",
    "description",
    "field_keys",
    "enabled_packs",
    "discovery_strategy",
    "source_profile_ref",
    "scoring_rubric",
    "created_by",
    "created_at",
)


def _claim_guard(columns: tuple[str, ...]) -> str:
    guard = " OR ".join(f"NEW.{column} IS DISTINCT FROM OLD.{column}" for column in columns)
    allowed = ", ".join(_CLAIM_MUTABLE)
    return f"""
        CREATE OR REPLACE FUNCTION claim_reject_immutable_update() RETURNS trigger AS $$
        BEGIN
            IF {guard} THEN
                RAISE EXCEPTION
                    'claim is append-only: only ({allowed}) may be updated; an immutable '
                    'provenance column was modified. Supersede by inserting a new claim.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def _icp_guard(columns: tuple[str, ...]) -> str:
    guard = " OR ".join(f"NEW.{column} IS DISTINCT FROM OLD.{column}" for column in columns)
    return f"""
        CREATE OR REPLACE FUNCTION icp_spec_reject_immutable_update() RETURNS trigger AS $$
        BEGIN
            IF {guard} THEN
                RAISE EXCEPTION
                    'icp_spec is append-only: only status may change; '
                    'edit by inserting a new version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def _append_only_guard(function: str, table: str, mutable: tuple[str, ...] = ()) -> str:
    if mutable:
        allowed = " AND ".join(
            f"NEW.{column} IS NOT DISTINCT FROM OLD.{column}" for column in mutable
        )
        condition = f"NOT ({allowed})"
    else:
        condition = "NEW IS DISTINCT FROM OLD"
    return f"""
        CREATE FUNCTION {function}() RETURNS trigger AS $$
        BEGIN
            IF {condition} THEN
                RAISE EXCEPTION '{table} is append-only';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def upgrade() -> None:
    op.execute("ALTER TYPE modality ADD VALUE IF NOT EXISTS 'conversation'")
    # Composite context anchors let every C4 row pin one coherent workspace/brand/product tuple.
    op.create_unique_constraint(
        "product_context_anchor", "product", ["product_id", "workspace_id", "brand_id"]
    )

    # Product-scoped claim provenance.
    op.execute("ALTER TABLE claim ADD COLUMN product_id text")
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_product_workspace_fk "
        "FOREIGN KEY (product_id, workspace_id) REFERENCES product (product_id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE claim ADD CONSTRAINT claim_product_requires_private_scope CHECK "
        "(product_id IS NULL OR (workspace_id IS NOT NULL AND reuse_scope = 'tenant_private'))"
    )
    op.execute(
        "CREATE INDEX claim_product_scoped_read "
        "ON claim (workspace_id, product_id, entity_id, field_key, collected_at DESC) "
        "WHERE product_id IS NOT NULL"
    )
    op.execute(_claim_guard(_CLAIM_IMMUTABLE + ("product_id",)))

    # Immutable KB -> ICP -> product lineage. Nullable preserves legacy/manual specs.
    op.execute("ALTER TABLE icp_spec ADD COLUMN client_entity_id uuid")
    op.execute("ALTER TABLE icp_spec ADD COLUMN client_kb_version int")
    op.execute("ALTER TABLE icp_spec ADD COLUMN product_id text")
    op.execute(
        "ALTER TABLE icp_spec ADD CONSTRAINT icp_spec_client_workspace_fk "
        "FOREIGN KEY (client_entity_id, workspace_id) "
        "REFERENCES account_entity (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE icp_spec ADD CONSTRAINT icp_spec_product_workspace_fk "
        "FOREIGN KEY (product_id, workspace_id) REFERENCES product (product_id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE icp_spec ADD CONSTRAINT icp_spec_lineage_complete CHECK "
        "((client_entity_id IS NULL AND client_kb_version IS NULL AND product_id IS NULL) OR "
        "(client_entity_id IS NOT NULL AND client_kb_version >= 1 AND product_id IS NOT NULL))"
    )
    op.execute(_icp_guard(_ICP_IMMUTABLE + ("client_entity_id", "client_kb_version", "product_id")))

    op.execute(
        """
        CREATE TABLE onboarding_input (
            id               uuid PRIMARY KEY,
            workspace_id     text NOT NULL,
            brand_id         text NOT NULL,
            product_id       text,
            project_id       text,
            client_entity_id uuid,
            kind             text NOT NULL,
            artifact_key     text NOT NULL,
            content_sha256   text NOT NULL,
            source_ref       text,
            actor            text NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT onboarding_input_kind CHECK (
                kind IN ('website', 'user_turn', 'upload', 'pasted_text', 'crm_reference')
            ),
            CONSTRAINT onboarding_input_actor CHECK (actor IN ('human', 'agent', 'system')),
            CONSTRAINT onboarding_input_sha CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT onboarding_input_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT onboarding_input_product_fk FOREIGN KEY
                (product_id, workspace_id, brand_id)
                REFERENCES product (product_id, workspace_id, brand_id),
            CONSTRAINT onboarding_input_project_fk FOREIGN KEY
                (project_id, workspace_id, brand_id)
                REFERENCES project (project_id, workspace_id, brand_id),
            CONSTRAINT onboarding_input_client_fk FOREIGN KEY (client_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT onboarding_input_artifact_fk FOREIGN KEY (artifact_key)
                REFERENCES artifact (storage_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX onboarding_input_scope "
        "ON onboarding_input (workspace_id, brand_id, product_id, project_id, created_at)"
    )
    op.execute(_append_only_guard("onboarding_input_reject_update", "onboarding_input"))
    op.execute(
        "CREATE TRIGGER onboarding_input_immutable BEFORE UPDATE ON onboarding_input "
        "FOR EACH ROW EXECUTE FUNCTION onboarding_input_reject_update()"
    )

    op.execute(
        """
        CREATE TABLE recon_run (
            id                       uuid PRIMARY KEY,
            workspace_id             text NOT NULL,
            brand_id                 text NOT NULL,
            product_id               text,
            project_id               text,
            client_entity_id         uuid,
            dedupe_hash              text NOT NULL,
            dedupe_expires_at        timestamptz NOT NULL,
            onboarding_input_ids     jsonb NOT NULL DEFAULT '[]'::jsonb,
            fast_run_id              uuid NOT NULL,
            background_run_id        uuid NOT NULL,
            fast_status              text NOT NULL DEFAULT 'queued',
            background_status        text NOT NULL DEFAULT 'queued',
            fast_budget_cents        numeric NOT NULL,
            background_budget_cents  numeric NOT NULL,
            fast_cost_cents          numeric NOT NULL DEFAULT 0,
            background_cost_cents    numeric NOT NULL DEFAULT 0,
            fast_client_kb_version   int,
            client_kb_version        int,
            recipe_version           text NOT NULL,
            skill_version            text NOT NULL,
            failure_code             text,
            created_at               timestamptz NOT NULL DEFAULT now(),
            fast_started_at          timestamptz,
            fast_completed_at        timestamptz,
            background_started_at    timestamptz,
            background_completed_at  timestamptz,
            updated_at               timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT recon_run_statuses CHECK (
                fast_status IN ('queued', 'running', 'completed', 'failed', 'paused')
                AND background_status IN ('queued', 'running', 'completed', 'failed', 'paused')
            ),
            CONSTRAINT recon_run_budgets_nonnegative CHECK (
                fast_budget_cents >= 0 AND background_budget_cents >= 0
                AND fast_cost_cents >= 0 AND background_cost_cents >= 0
            ),
            CONSTRAINT recon_run_input_refs_array CHECK (
                jsonb_typeof(onboarding_input_ids) = 'array'
            ),
            CONSTRAINT recon_run_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT recon_run_product_fk FOREIGN KEY (product_id, workspace_id, brand_id)
                REFERENCES product (product_id, workspace_id, brand_id),
            CONSTRAINT recon_run_project_fk FOREIGN KEY (project_id, workspace_id, brand_id)
                REFERENCES project (project_id, workspace_id, brand_id),
            CONSTRAINT recon_run_client_fk FOREIGN KEY (client_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX recon_run_scope ON recon_run (workspace_id, brand_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX recon_run_dedupe ON recon_run "
        "(workspace_id, dedupe_hash, dedupe_expires_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE volunteered_statement (
            id                    uuid PRIMARY KEY,
            onboarding_input_id   uuid NOT NULL,
            workspace_id          text NOT NULL,
            brand_id              text NOT NULL,
            product_id            text,
            project_id            text,
            client_entity_id      uuid,
            entity_id             uuid,
            route_kind            text NOT NULL,
            route_key             text NOT NULL,
            route_ref             text,
            quote_start           int NOT NULL,
            quote_end             int NOT NULL,
            quote_sha256          text NOT NULL,
            correction_of_id      uuid,
            created_by_actor      text NOT NULL,
            created_at            timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT volunteered_statement_route CHECK (
                route_kind IN (
                    'claim', 'memory', 'project_state', 'field_proposal',
                    'source_proposal', 'unmapped'
                )
            ),
            CONSTRAINT volunteered_statement_offsets CHECK (
                quote_start >= 0 AND quote_end > quote_start
            ),
            CONSTRAINT volunteered_statement_sha CHECK (quote_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT volunteered_statement_actor CHECK (
                created_by_actor IN ('human', 'agent', 'system')
            ),
            CONSTRAINT volunteered_statement_input_fk FOREIGN KEY (onboarding_input_id)
                REFERENCES onboarding_input (id),
            CONSTRAINT volunteered_statement_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT volunteered_statement_product_fk FOREIGN KEY
                (product_id, workspace_id, brand_id)
                REFERENCES product (product_id, workspace_id, brand_id),
            CONSTRAINT volunteered_statement_project_fk FOREIGN KEY
                (project_id, workspace_id, brand_id)
                REFERENCES project (project_id, workspace_id, brand_id),
            CONSTRAINT volunteered_statement_client_fk FOREIGN KEY
                (client_entity_id, workspace_id) REFERENCES account_entity (id, workspace_id),
            CONSTRAINT volunteered_statement_correction_fk FOREIGN KEY (correction_of_id)
                REFERENCES volunteered_statement (id),
            CONSTRAINT volunteered_statement_idempotency UNIQUE
                (onboarding_input_id, entity_id, route_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX volunteered_statement_scope "
        "ON volunteered_statement (workspace_id, project_id, created_at)"
    )
    op.execute(_append_only_guard("volunteered_statement_reject_update", "volunteered_statement"))
    op.execute(
        "CREATE TRIGGER volunteered_statement_immutable BEFORE UPDATE ON volunteered_statement "
        "FOR EACH ROW EXECUTE FUNCTION volunteered_statement_reject_update()"
    )

    op.execute(
        """
        CREATE TABLE product_context_version (
            id                    uuid PRIMARY KEY,
            workspace_id          text NOT NULL,
            brand_id              text NOT NULL,
            product_id            text NOT NULL,
            client_entity_id      uuid NOT NULL,
            client_kb_version     int NOT NULL,
            claim_refs            jsonb NOT NULL DEFAULT '[]'::jsonb,
            memory_refs           jsonb NOT NULL DEFAULT '[]'::jsonb,
            artifact_refs         jsonb NOT NULL DEFAULT '[]'::jsonb,
            freshness_snapshot    jsonb NOT NULL DEFAULT '{}'::jsonb,
            manifest_hash         text NOT NULL,
            compiler_version      text NOT NULL,
            compiled_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT product_context_kb_version CHECK (client_kb_version >= 1),
            CONSTRAINT product_context_refs CHECK (
                jsonb_typeof(claim_refs) = 'array'
                AND jsonb_typeof(memory_refs) = 'array'
                AND jsonb_typeof(artifact_refs) = 'array'
                AND jsonb_typeof(freshness_snapshot) = 'object'
            ),
            CONSTRAINT product_context_hash CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT product_context_product_fk FOREIGN KEY
                (product_id, workspace_id, brand_id)
                REFERENCES product (product_id, workspace_id, brand_id),
            CONSTRAINT product_context_client_fk FOREIGN KEY (client_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT product_context_manifest_unique UNIQUE
                (workspace_id, product_id, manifest_hash),
            CONSTRAINT product_context_full_anchor UNIQUE
                (id, workspace_id, brand_id, product_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX product_context_latest "
        "ON product_context_version (workspace_id, product_id, compiled_at DESC)"
    )
    op.execute(_append_only_guard("product_context_reject_update", "product_context_version"))
    op.execute(
        "CREATE TRIGGER product_context_immutable BEFORE UPDATE ON product_context_version "
        "FOR EACH ROW EXECUTE FUNCTION product_context_reject_update()"
    )

    op.execute(
        """
        CREATE TABLE readiness_spec_revision (
            workspace_id text NOT NULL,
            version      int NOT NULL,
            policy_json  jsonb NOT NULL,
            policy_hash  text NOT NULL,
            created_by   text NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT readiness_spec_revision_pkey PRIMARY KEY (workspace_id, version),
            CONSTRAINT readiness_spec_version_positive CHECK (version >= 1),
            CONSTRAINT readiness_spec_policy_object CHECK (jsonb_typeof(policy_json) = 'object'),
            CONSTRAINT readiness_spec_policy_hash CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT readiness_spec_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT readiness_spec_policy_unique UNIQUE (workspace_id, policy_hash)
        )
        """
    )
    op.execute(_append_only_guard("readiness_spec_reject_update", "readiness_spec_revision"))
    op.execute(
        "CREATE TRIGGER readiness_spec_immutable BEFORE UPDATE ON readiness_spec_revision "
        "FOR EACH ROW EXECUTE FUNCTION readiness_spec_reject_update()"
    )

    op.execute(
        """
        CREATE TABLE readiness_decision (
            id                         uuid PRIMARY KEY,
            workspace_id               text NOT NULL,
            brand_id                   text NOT NULL,
            product_id                 text,
            project_id                 text,
            client_entity_id           uuid,
            client_kb_version          int,
            icp_key                    text,
            icp_version                int,
            product_context_version_id uuid,
            gate                       text NOT NULL,
            verdict                    text NOT NULL,
            spec_version               int NOT NULL,
            gap_refs                   jsonb NOT NULL DEFAULT '[]'::jsonb,
            field_proposal_refs        jsonb NOT NULL DEFAULT '[]'::jsonb,
            source_proposal_refs       jsonb NOT NULL DEFAULT '[]'::jsonb,
            ingestion_refs             jsonb NOT NULL DEFAULT '[]'::jsonb,
            metrics                    jsonb NOT NULL DEFAULT '{}'::jsonb,
            reason_codes               jsonb NOT NULL DEFAULT '[]'::jsonb,
            agent_sufficiency_status   text NOT NULL DEFAULT 'not_evaluated',
            agent_sufficiency_ref      text,
            created_by_actor           text NOT NULL,
            created_at                 timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT readiness_decision_gate CHECK (
                gate IN ('icp_synthesis', 'discovery_spend', 'deep_spend')
            ),
            CONSTRAINT readiness_decision_verdict CHECK (
                verdict IN ('ready', 'not_ready')
            ),
            CONSTRAINT readiness_decision_actor CHECK (
                created_by_actor IN ('human', 'agent', 'system')
            ),
            CONSTRAINT readiness_decision_refs CHECK (
                jsonb_typeof(gap_refs) = 'array'
                AND jsonb_typeof(field_proposal_refs) = 'array'
                AND jsonb_typeof(source_proposal_refs) = 'array'
                AND jsonb_typeof(ingestion_refs) = 'array'
                AND jsonb_typeof(metrics) = 'object'
                AND jsonb_typeof(reason_codes) = 'array'
            ),
            CONSTRAINT readiness_decision_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT readiness_decision_product_fk FOREIGN KEY
                (product_id, workspace_id, brand_id)
                REFERENCES product (product_id, workspace_id, brand_id),
            CONSTRAINT readiness_decision_project_fk FOREIGN KEY
                (project_id, workspace_id, brand_id)
                REFERENCES project (project_id, workspace_id, brand_id),
            CONSTRAINT readiness_decision_client_fk FOREIGN KEY
                (client_entity_id, workspace_id) REFERENCES account_entity (id, workspace_id),
            CONSTRAINT readiness_decision_icp_fk FOREIGN KEY
                (workspace_id, icp_key, icp_version)
                REFERENCES icp_spec (workspace_id, icp_key, version),
            CONSTRAINT readiness_decision_context_fk FOREIGN KEY
                (product_context_version_id, workspace_id, brand_id, product_id)
                REFERENCES product_context_version (id, workspace_id, brand_id, product_id),
            CONSTRAINT readiness_decision_spec_fk FOREIGN KEY (workspace_id, spec_version)
                REFERENCES readiness_spec_revision (workspace_id, version),
            CONSTRAINT readiness_decision_full_anchor UNIQUE
                (id, workspace_id, brand_id, product_id, project_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX readiness_decision_latest "
        "ON readiness_decision (workspace_id, project_id, gate, created_at DESC)"
    )
    op.execute(_append_only_guard("readiness_decision_reject_update", "readiness_decision"))
    op.execute(
        "CREATE TRIGGER readiness_decision_immutable BEFORE UPDATE ON readiness_decision "
        "FOR EACH ROW EXECUTE FUNCTION readiness_decision_reject_update()"
    )

    op.execute(
        """
        CREATE TABLE readiness_override (
            id                    uuid PRIMARY KEY,
            readiness_decision_id uuid NOT NULL,
            workspace_id          text NOT NULL,
            gate                  text NOT NULL,
            actor                 text NOT NULL,
            reason                text NOT NULL,
            created_at            timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT readiness_override_gate CHECK (
                gate IN ('icp_synthesis', 'discovery_spend', 'deep_spend')
            ),
            CONSTRAINT readiness_override_human_only CHECK (actor = 'human'),
            CONSTRAINT readiness_override_decision_fk FOREIGN KEY (readiness_decision_id)
                REFERENCES readiness_decision (id),
            CONSTRAINT readiness_override_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT readiness_override_unique UNIQUE (readiness_decision_id)
        )
        """
    )
    op.execute(_append_only_guard("readiness_override_reject_update", "readiness_override"))
    op.execute(
        "CREATE TRIGGER readiness_override_immutable BEFORE UPDATE ON readiness_override "
        "FOR EACH ROW EXECUTE FUNCTION readiness_override_reject_update()"
    )

    # Post-confirmation execution pins. Legacy Recipe #1 rows remain nullable.
    op.execute("ALTER TABLE project_run ADD COLUMN client_entity_id uuid")
    op.execute("ALTER TABLE project_run ADD COLUMN client_kb_version int")
    op.execute("ALTER TABLE project_run ADD COLUMN product_id text")
    op.execute("ALTER TABLE project_run ADD COLUMN product_context_version_id uuid")
    op.execute("ALTER TABLE project_run ADD COLUMN readiness_decision_id uuid")
    op.execute(
        "ALTER TABLE project_run ADD CONSTRAINT project_run_client_workspace_fk "
        "FOREIGN KEY (client_entity_id, workspace_id) REFERENCES account_entity (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE project_run ADD CONSTRAINT project_run_product_context_fk "
        "FOREIGN KEY (product_context_version_id, workspace_id, brand_id, product_id) "
        "REFERENCES product_context_version (id, workspace_id, brand_id, product_id)"
    )
    op.execute(
        "ALTER TABLE project_run ADD CONSTRAINT project_run_readiness_context_fk "
        "FOREIGN KEY (readiness_decision_id, workspace_id, brand_id, product_id, project_id) "
        "REFERENCES readiness_decision (id, workspace_id, brand_id, product_id, project_id)"
    )
    op.execute(
        "ALTER TABLE project_run ADD CONSTRAINT project_run_stage0_pins_complete CHECK ("
        "(client_entity_id IS NULL AND client_kb_version IS NULL AND product_id IS NULL "
        "AND product_context_version_id IS NULL AND readiness_decision_id IS NULL) OR "
        "(client_entity_id IS NOT NULL AND client_kb_version >= 1 AND product_id IS NOT NULL "
        "AND product_context_version_id IS NOT NULL AND readiness_decision_id IS NOT NULL))"
    )


def downgrade() -> None:
    op.drop_constraint("project_run_stage0_pins_complete", "project_run", type_="check")
    op.drop_constraint("project_run_readiness_context_fk", "project_run", type_="foreignkey")
    op.drop_constraint("project_run_product_context_fk", "project_run", type_="foreignkey")
    op.drop_constraint("project_run_client_workspace_fk", "project_run", type_="foreignkey")
    op.drop_column("project_run", "readiness_decision_id")
    op.drop_column("project_run", "product_context_version_id")
    op.drop_column("project_run", "product_id")
    op.drop_column("project_run", "client_kb_version")
    op.drop_column("project_run", "client_entity_id")

    for table, trigger, function in (
        ("readiness_override", "readiness_override_immutable", "readiness_override_reject_update"),
        ("readiness_decision", "readiness_decision_immutable", "readiness_decision_reject_update"),
        ("readiness_spec_revision", "readiness_spec_immutable", "readiness_spec_reject_update"),
        ("product_context_version", "product_context_immutable", "product_context_reject_update"),
        (
            "volunteered_statement",
            "volunteered_statement_immutable",
            "volunteered_statement_reject_update",
        ),
        ("onboarding_input", "onboarding_input_immutable", "onboarding_input_reject_update"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")

    op.drop_table("readiness_override")
    op.drop_table("readiness_decision")
    op.drop_table("readiness_spec_revision")
    op.drop_table("product_context_version")
    op.drop_table("volunteered_statement")
    op.drop_table("recon_run")
    op.drop_table("onboarding_input")

    op.execute(_icp_guard(_ICP_IMMUTABLE))
    op.drop_constraint("icp_spec_lineage_complete", "icp_spec", type_="check")
    op.drop_constraint("icp_spec_product_workspace_fk", "icp_spec", type_="foreignkey")
    op.drop_constraint("icp_spec_client_workspace_fk", "icp_spec", type_="foreignkey")
    op.drop_column("icp_spec", "product_id")
    op.drop_column("icp_spec", "client_kb_version")
    op.drop_column("icp_spec", "client_entity_id")

    op.execute(_claim_guard(_CLAIM_IMMUTABLE))
    op.drop_index("claim_product_scoped_read", table_name="claim")
    op.drop_constraint("claim_product_requires_private_scope", "claim", type_="check")
    op.drop_constraint("claim_product_workspace_fk", "claim", type_="foreignkey")
    op.drop_column("claim", "product_id")
    op.drop_constraint("product_context_anchor", "product", type_="unique")

    # Remove the C4-only enum value without rewriting any legacy manifest definitions.
    op.execute("DELETE FROM source_manifest WHERE modality::text = 'conversation'")
    op.execute("ALTER TYPE modality RENAME TO modality_with_conversation")
    op.execute("CREATE TYPE modality AS ENUM ('text', 'video', 'audio', 'pdf', 'structured')")
    op.execute(
        "ALTER TABLE source_manifest ALTER COLUMN modality TYPE modality "
        "USING modality::text::modality"
    )
    op.execute("DROP TYPE modality_with_conversation")
