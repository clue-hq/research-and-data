"""pre-spend effective source plan audit

Revision ID: e9634dbc522f
Revises: a5e32cf0815d
Create Date: 2026-08-04 00:00:00+00:00

Records the exact source key and content-addressed effective per-field source plan presented to the
pre-spend gate.  This closes the former tier-only authorization ambiguity while retaining nullable
columns for historical/static callers.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e9634dbc522f"
down_revision: str | None = "a5e32cf0815d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE effective_field_source_plan (
            workspace_id       text NOT NULL,
            icp_key            text NOT NULL,
            icp_version        int NOT NULL,
            field_key          text NOT NULL REFERENCES field_definition(field_key),
            plan_sha256        text NOT NULL UNIQUE,
            plan_json          jsonb NOT NULL,
            source_profile_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT effective_field_source_plan_pkey
                PRIMARY KEY (workspace_id, icp_key, icp_version, field_key),
            CONSTRAINT effective_field_source_plan_icp_fk
                FOREIGN KEY (workspace_id, icp_key, icp_version)
                REFERENCES icp_spec(workspace_id, icp_key, version) ON DELETE CASCADE,
            CONSTRAINT effective_field_source_plan_hash
                CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT effective_field_source_plan_json_object
                CHECK (jsonb_typeof(plan_json) = 'object'),
            CONSTRAINT effective_field_source_plan_profile_object
                CHECK (jsonb_typeof(source_profile_ref) = 'object'),
            CONSTRAINT effective_field_source_plan_json_coherent CHECK (
                plan_json->>'workspace_id' = workspace_id
                AND plan_json->>'icp_key' = icp_key
                AND (plan_json->>'icp_version')::int = icp_version
                AND plan_json->>'field_key' = field_key
                AND plan_json->>'plan_sha256' = plan_sha256
                AND jsonb_typeof(plan_json->'sources') = 'array'
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE effective_field_source_plan IS "
        "'Immutable exact-source authorization for one pinned ICP field; runtime policy may only "
        "narrow it.'"
    )
    op.execute(
        """
        CREATE FUNCTION effective_field_source_plan_reject_mutation() RETURNS trigger AS $$
        BEGIN
            -- A parent ICP deletion is the governed erasure path and reaches this trigger through
            -- the declared ON DELETE CASCADE after the parent row is no longer visible. Direct
            -- child deletion while the ICP still exists remains forbidden.
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM icp_spec
                WHERE workspace_id = OLD.workspace_id
                  AND icp_key = OLD.icp_key
                  AND version = OLD.icp_version
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'effective field source plan is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER effective_field_source_plan_immutable BEFORE UPDATE OR DELETE "
        "ON effective_field_source_plan FOR EACH ROW "
        "EXECUTE FUNCTION effective_field_source_plan_reject_mutation()"
    )
    op.execute("ALTER TABLE gate_decision ADD COLUMN source_key text")
    op.execute("ALTER TABLE gate_decision ADD COLUMN effective_plan_sha256 text")
    op.execute("ALTER TABLE gate_decision ADD COLUMN effective_source_plan jsonb")
    op.execute(
        "ALTER TABLE gate_decision ADD CONSTRAINT gate_decision_effective_plan_coherent CHECK ("
        " (effective_plan_sha256 IS NULL AND effective_source_plan IS NULL) OR "
        " (effective_plan_sha256 ~ '^[0-9a-f]{64}$' "
        "AND jsonb_typeof(effective_source_plan) = 'object'))"
    )
    op.execute(
        "COMMENT ON COLUMN gate_decision.source_key IS "
        "'Exact source registry key checked before spend; tier alone is not authorization.'"
    )
    op.execute(
        "COMMENT ON COLUMN gate_decision.effective_plan_sha256 IS "
        "'Digest of the pinned ICP per-field exact-source authorization supplied to the gate.'"
    )
    op.execute(
        "CREATE INDEX gate_decision_effective_plan ON gate_decision (effective_plan_sha256) "
        "WHERE effective_plan_sha256 IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS gate_decision_effective_plan")
    op.execute(
        "ALTER TABLE gate_decision DROP CONSTRAINT IF EXISTS gate_decision_effective_plan_coherent"
    )
    op.execute("ALTER TABLE gate_decision DROP COLUMN IF EXISTS effective_source_plan")
    op.execute("ALTER TABLE gate_decision DROP COLUMN IF EXISTS effective_plan_sha256")
    op.execute("ALTER TABLE gate_decision DROP COLUMN IF EXISTS source_key")
    op.execute(
        "DROP TRIGGER IF EXISTS effective_field_source_plan_immutable "
        "ON effective_field_source_plan"
    )
    op.execute("DROP TABLE IF EXISTS effective_field_source_plan")
    op.execute("DROP FUNCTION IF EXISTS effective_field_source_plan_reject_mutation()")
