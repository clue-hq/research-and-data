"""account research directive a2

Revision ID: 8f44b739674c
Revises: e9634dbc522f
Create Date: 2026-08-03 20:36:33.337809+00:00

The directive is execution input, not memory and not a claim.  Immutable version content lives in
``account_research_directive``; lifecycle changes have append-only events.  Per-account overrides
and account-run pins are separately content-addressed so a later project edit cannot move a running
operation to new instructions.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "8f44b739674c"
down_revision: str | None = "e9634dbc522f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE research_directive_status AS ENUM ('draft', 'confirmed', 'superseded')")
    op.execute(
        "CREATE TYPE research_directive_event_type AS ENUM ('drafted', 'confirmed', 'superseded')"
    )
    op.execute(
        """
        CREATE TABLE account_research_directive (
            directive_id             uuid NOT NULL,
            workspace_id             text NOT NULL,
            project_id               text NOT NULL,
            product_id               text NOT NULL,
            icp_key                  text NOT NULL,
            icp_version              int NOT NULL,
            version                  int NOT NULL,
            status                   research_directive_status NOT NULL DEFAULT 'draft',
            predecessor_id           uuid,
            content_json             jsonb NOT NULL,
            memory_refs              jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_by               text NOT NULL,
            source_turn_ref          text NOT NULL,
            draft_operation_id       uuid NOT NULL,
            draft_request_sha256     text NOT NULL,
            confirmation_operation_id uuid,
            confirmed_by             text,
            confirming_turn_ref      text,
            canonical_json_sha256    text NOT NULL,
            created_at               timestamptz NOT NULL DEFAULT now(),
            confirmed_at             timestamptz,

            CONSTRAINT account_research_directive_pkey PRIMARY KEY (directive_id),
            CONSTRAINT account_research_directive_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id) ON DELETE CASCADE,
            CONSTRAINT account_research_directive_project_fk FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT account_research_directive_product_fk FOREIGN KEY (product_id, workspace_id)
                REFERENCES product (product_id, workspace_id),
            CONSTRAINT account_research_directive_icp_fk
                FOREIGN KEY (workspace_id, icp_key, icp_version)
                REFERENCES icp_spec (workspace_id, icp_key, version),
            CONSTRAINT account_research_directive_predecessor_fk FOREIGN KEY (predecessor_id)
                REFERENCES account_research_directive (directive_id),
            CONSTRAINT account_research_directive_version_positive CHECK (version >= 1),
            CONSTRAINT account_research_directive_content_object
                CHECK (jsonb_typeof(content_json) = 'object'),
            CONSTRAINT account_research_directive_memory_refs_array
                CHECK (jsonb_typeof(memory_refs) = 'array'),
            CONSTRAINT account_research_directive_sha256
                CHECK (canonical_json_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT account_research_directive_draft_request_sha256
                CHECK (draft_request_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT account_research_directive_confirmation_shape CHECK (
                (status = 'draft' AND confirmation_operation_id IS NULL
                    AND confirmed_by IS NULL AND confirming_turn_ref IS NULL
                    AND confirmed_at IS NULL)
                OR
                (status IN ('confirmed', 'superseded') AND confirmation_operation_id IS NOT NULL
                    AND confirmed_by IS NOT NULL AND confirming_turn_ref IS NOT NULL
                    AND confirmed_at IS NOT NULL)
            ),
            CONSTRAINT account_research_directive_version_unique UNIQUE
                (workspace_id, project_id, product_id, icp_key, icp_version, version),
            CONSTRAINT account_research_directive_workspace_anchor UNIQUE
                (directive_id, workspace_id),
            CONSTRAINT account_research_directive_pin_anchor UNIQUE
                (directive_id, version, canonical_json_sha256),
            CONSTRAINT account_research_directive_draft_operation_unique UNIQUE
                (workspace_id, draft_operation_id),
            CONSTRAINT account_research_directive_confirmation_operation_unique UNIQUE
                (workspace_id, confirmation_operation_id)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX account_research_directive_one_confirmed "
        "ON account_research_directive "
        "(workspace_id, project_id, product_id, icp_key, icp_version) "
        "WHERE status = 'confirmed'"
    )
    op.execute(
        "CREATE INDEX account_research_directive_project_versions ON account_research_directive "
        "(workspace_id, project_id, product_id, icp_key, icp_version, version DESC)"
    )

    op.execute(
        """
        CREATE TABLE account_research_directive_override (
            override_id              uuid NOT NULL,
            directive_id             uuid NOT NULL,
            workspace_id             text NOT NULL,
            account_id               uuid NOT NULL,
            content_json             jsonb NOT NULL,
            created_by               text NOT NULL,
            source_turn_ref          text NOT NULL,
            canonical_json_sha256    text NOT NULL,
            created_at               timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT account_research_directive_override_pkey PRIMARY KEY (override_id),
            CONSTRAINT account_research_directive_override_directive_fk
                FOREIGN KEY (directive_id, workspace_id)
                REFERENCES account_research_directive (directive_id, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT account_research_directive_override_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT account_research_directive_override_content_object
                CHECK (jsonb_typeof(content_json) = 'object'),
            CONSTRAINT account_research_directive_override_sha256
                CHECK (canonical_json_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT account_research_directive_override_account_unique
                UNIQUE (directive_id, account_id),
            CONSTRAINT account_research_directive_override_pin_anchor
                UNIQUE (override_id, directive_id, account_id, canonical_json_sha256)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE account_research_directive_event (
            event_id                 uuid NOT NULL,
            directive_id             uuid NOT NULL,
            workspace_id             text NOT NULL,
            event_type               research_directive_event_type NOT NULL,
            actor_type               text NOT NULL,
            actor_ref                text NOT NULL,
            turn_ref                 text NOT NULL,
            successor_id             uuid,
            operation_id             uuid NOT NULL,
            occurred_at              timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT account_research_directive_event_pkey PRIMARY KEY (event_id),
            CONSTRAINT account_research_directive_event_directive_fk
                FOREIGN KEY (directive_id, workspace_id)
                REFERENCES account_research_directive (directive_id, workspace_id)
                ON DELETE CASCADE,
            CONSTRAINT account_research_directive_event_successor_fk FOREIGN KEY (successor_id)
                REFERENCES account_research_directive (directive_id),
            CONSTRAINT account_research_directive_event_actor_type
                CHECK (actor_type IN ('human', 'agent', 'engine')),
            CONSTRAINT account_research_directive_event_successor_shape CHECK (
                (event_type = 'superseded' AND successor_id IS NOT NULL)
                OR (event_type <> 'superseded' AND successor_id IS NULL)
            ),
            CONSTRAINT account_research_directive_event_operation_unique
                UNIQUE (workspace_id, operation_id, event_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX account_research_directive_event_timeline "
        "ON account_research_directive_event (directive_id, occurred_at, event_id)"
    )

    op.execute(
        """
        CREATE FUNCTION account_research_directive_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF EXISTS (SELECT 1 FROM project WHERE project_id = OLD.project_id) THEN
                    RAISE EXCEPTION
                        'account_research_directive is lifecycle-owned; delete the project';
                END IF;
                RETURN OLD;
            END IF;
            IF NEW.directive_id IS DISTINCT FROM OLD.directive_id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.project_id IS DISTINCT FROM OLD.project_id
               OR NEW.product_id IS DISTINCT FROM OLD.product_id
               OR NEW.icp_key IS DISTINCT FROM OLD.icp_key
               OR NEW.icp_version IS DISTINCT FROM OLD.icp_version
               OR NEW.version IS DISTINCT FROM OLD.version
               OR NEW.predecessor_id IS DISTINCT FROM OLD.predecessor_id
               OR NEW.content_json IS DISTINCT FROM OLD.content_json
               OR NEW.memory_refs IS DISTINCT FROM OLD.memory_refs
               OR NEW.created_by IS DISTINCT FROM OLD.created_by
               OR NEW.source_turn_ref IS DISTINCT FROM OLD.source_turn_ref
               OR NEW.draft_operation_id IS DISTINCT FROM OLD.draft_operation_id
               OR NEW.draft_request_sha256 IS DISTINCT FROM OLD.draft_request_sha256
               OR NEW.canonical_json_sha256 IS DISTINCT FROM OLD.canonical_json_sha256
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION
                    'research directive content is immutable; append a successor version';
            END IF;
            IF NOT (
                (OLD.status = 'draft' AND NEW.status = 'confirmed')
                OR (OLD.status = 'confirmed' AND NEW.status = 'superseded')
                OR (OLD.status = NEW.status)
            ) THEN
                RAISE EXCEPTION 'invalid research directive lifecycle transition';
            END IF;
            IF OLD.status = NEW.status AND (
                NEW.confirmation_operation_id IS DISTINCT FROM OLD.confirmation_operation_id
                OR NEW.confirmed_by IS DISTINCT FROM OLD.confirmed_by
                OR NEW.confirming_turn_ref IS DISTINCT FROM OLD.confirming_turn_ref
                OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
            ) THEN
                RAISE EXCEPTION 'research directive confirmation receipt is immutable';
            END IF;
            IF OLD.status = 'draft' AND NEW.status = 'confirmed' AND (
                NEW.confirmation_operation_id IS NULL
                OR NEW.confirmed_by IS NULL
                OR NEW.confirming_turn_ref IS NULL
                OR NEW.confirmed_at IS NULL
            ) THEN
                RAISE EXCEPTION 'confirmed directive requires a complete confirmation receipt';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_research_directive_immutable "
        "BEFORE UPDATE OR DELETE ON account_research_directive FOR EACH ROW "
        "EXECUTE FUNCTION account_research_directive_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION account_research_directive_child_immutable() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'research directive child records are append-only';
            END IF;
            IF TG_TABLE_NAME = 'account_research_directive_override' THEN
                IF EXISTS (
                    SELECT 1 FROM account_research_directive
                    WHERE directive_id = OLD.directive_id
                ) AND EXISTS (SELECT 1 FROM account_entity WHERE id = OLD.account_id) THEN
                    RAISE EXCEPTION 'research directive overrides are lifecycle-owned';
                END IF;
            ELSIF EXISTS (
                SELECT 1 FROM account_research_directive
                WHERE directive_id = OLD.directive_id
            ) THEN
                RAISE EXCEPTION 'research directive events are lifecycle-owned';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_research_directive_override_immutable "
        "BEFORE UPDATE OR DELETE ON account_research_directive_override FOR EACH ROW "
        "EXECUTE FUNCTION account_research_directive_child_immutable()"
    )
    op.execute(
        "CREATE TRIGGER account_research_directive_event_immutable "
        "BEFORE UPDATE OR DELETE ON account_research_directive_event FOR EACH ROW "
        "EXECUTE FUNCTION account_research_directive_child_immutable()"
    )

    op.execute(
        """
        ALTER TABLE account_run
            ADD COLUMN research_directive_id uuid,
            ADD COLUMN research_directive_version int,
            ADD COLUMN research_directive_ref text,
            ADD COLUMN research_directive_sha256 text,
            ADD COLUMN research_directive_override_id uuid,
            ADD COLUMN research_directive_override_ref text,
            ADD COLUMN research_directive_override_sha256 text,
            ADD CONSTRAINT account_run_research_directive_pin_shape CHECK (
                (research_directive_id IS NULL AND research_directive_version IS NULL
                    AND research_directive_ref IS NULL AND research_directive_sha256 IS NULL
                    AND research_directive_override_id IS NULL
                    AND research_directive_override_ref IS NULL
                    AND research_directive_override_sha256 IS NULL)
                OR
                (research_directive_id IS NOT NULL AND research_directive_version IS NOT NULL
                    AND research_directive_ref IS NOT NULL
                    AND research_directive_ref =
                        'research-directive:' || research_directive_id::text ||
                        ':' || 'v' || research_directive_version::text
                    AND research_directive_sha256 ~ '^[0-9a-f]{64}$'
                    AND (
                        (research_directive_override_id IS NULL
                            AND research_directive_override_ref IS NULL
                            AND research_directive_override_sha256 IS NULL)
                        OR
                        (research_directive_override_id IS NOT NULL
                            AND research_directive_override_ref IS NOT NULL
                            AND research_directive_override_ref =
                                'research-directive-override:' ||
                                research_directive_override_id::text
                            AND research_directive_override_sha256 ~ '^[0-9a-f]{64}$')
                    ))
            ),
            ADD CONSTRAINT account_run_research_directive_fk FOREIGN KEY
                (research_directive_id, research_directive_version, research_directive_sha256)
                REFERENCES account_research_directive
                (directive_id, version, canonical_json_sha256),
            ADD CONSTRAINT account_run_research_directive_override_fk FOREIGN KEY
                (research_directive_override_id, research_directive_id, entity_id,
                 research_directive_override_sha256)
                REFERENCES account_research_directive_override
                (override_id, directive_id, account_id, canonical_json_sha256)
        """
    )
    op.execute(
        """
        CREATE FUNCTION account_run_research_directive_guard() RETURNS trigger AS $$
        DECLARE
            run_project_id text;
            run_workspace_id text;
        BEGIN
            IF TG_OP = 'UPDATE' AND OLD.research_directive_id IS NOT NULL AND (
                NEW.research_directive_id IS DISTINCT FROM OLD.research_directive_id
                OR NEW.research_directive_version IS DISTINCT FROM OLD.research_directive_version
                OR NEW.research_directive_ref IS DISTINCT FROM OLD.research_directive_ref
                OR NEW.research_directive_sha256 IS DISTINCT FROM OLD.research_directive_sha256
                OR NEW.research_directive_override_id
                    IS DISTINCT FROM OLD.research_directive_override_id
                OR NEW.research_directive_override_ref
                    IS DISTINCT FROM OLD.research_directive_override_ref
                OR NEW.research_directive_override_sha256
                    IS DISTINCT FROM OLD.research_directive_override_sha256
            ) THEN
                RAISE EXCEPTION 'an account run cannot change its pinned research directive';
            END IF;
            IF NEW.research_directive_id IS NOT NULL AND (
                (TG_OP = 'INSERT' AND (NEW.status <> 'pending' OR NEW.plan_json <> '{}'::jsonb))
                OR
                (TG_OP = 'UPDATE' AND OLD.research_directive_id IS NULL
                    AND (OLD.status <> 'pending' OR OLD.plan_json <> '{}'::jsonb))
            ) THEN
                RAISE EXCEPTION
                    'research directive must be pinned before an account run begins';
            END IF;
            IF NEW.research_directive_id IS NOT NULL THEN
                SELECT project_id, workspace_id INTO run_project_id, run_workspace_id
                FROM project_run WHERE id = NEW.project_run_id;
                IF TG_OP = 'INSERT' THEN
                    IF NOT EXISTS (
                        SELECT 1 FROM account_research_directive
                        WHERE directive_id = NEW.research_directive_id
                          AND project_id = run_project_id
                          AND workspace_id = run_workspace_id
                          AND status = 'confirmed'
                    ) THEN
                        RAISE EXCEPTION
                            'account-run directive must be confirmed and match project/workspace';
                    END IF;
                ELSIF OLD.research_directive_id IS NULL THEN
                    IF NOT EXISTS (
                        SELECT 1 FROM account_research_directive
                        WHERE directive_id = NEW.research_directive_id
                          AND project_id = run_project_id
                          AND workspace_id = run_workspace_id
                          AND status = 'confirmed'
                    ) THEN
                        RAISE EXCEPTION
                            'account-run directive must be confirmed and match project/workspace';
                    END IF;
                ELSIF NOT EXISTS (
                        SELECT 1 FROM account_research_directive
                        WHERE directive_id = NEW.research_directive_id
                          AND project_id = run_project_id
                          AND workspace_id = run_workspace_id
                          AND status IN ('confirmed', 'superseded')
                ) THEN
                    RAISE EXCEPTION
                        'account-run directive must be confirmed and match project/workspace';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER account_run_research_directive_immutable "
        "BEFORE INSERT OR UPDATE ON account_run FOR EACH ROW "
        "EXECUTE FUNCTION account_run_research_directive_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER account_run_research_directive_immutable ON account_run")
    op.execute("DROP FUNCTION account_run_research_directive_guard()")
    op.execute(
        "ALTER TABLE account_run "
        "DROP CONSTRAINT account_run_research_directive_override_fk, "
        "DROP CONSTRAINT account_run_research_directive_fk, "
        "DROP CONSTRAINT account_run_research_directive_pin_shape, "
        "DROP COLUMN research_directive_override_sha256, "
        "DROP COLUMN research_directive_override_ref, "
        "DROP COLUMN research_directive_override_id, "
        "DROP COLUMN research_directive_sha256, "
        "DROP COLUMN research_directive_ref, "
        "DROP COLUMN research_directive_version, "
        "DROP COLUMN research_directive_id"
    )
    op.execute(
        "DROP TRIGGER account_research_directive_event_immutable "
        "ON account_research_directive_event"
    )
    op.execute(
        "DROP TRIGGER account_research_directive_override_immutable "
        "ON account_research_directive_override"
    )
    op.execute("DROP FUNCTION account_research_directive_child_immutable()")
    op.execute("DROP TRIGGER account_research_directive_immutable ON account_research_directive")
    op.execute("DROP FUNCTION account_research_directive_guard()")
    op.execute("DROP TABLE account_research_directive_event")
    op.execute("DROP TABLE account_research_directive_override")
    op.execute("DROP INDEX account_research_directive_project_versions")
    op.execute("DROP INDEX account_research_directive_one_confirmed")
    op.execute("DROP TABLE account_research_directive")
    op.execute("DROP TYPE research_directive_event_type")
    op.execute("DROP TYPE research_directive_status")
