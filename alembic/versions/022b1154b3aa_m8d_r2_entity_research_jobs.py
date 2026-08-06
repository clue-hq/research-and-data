"""m8d r2 entity research jobs

Revision ID: 022b1154b3aa
Revises: d338ba5a8f7e
Create Date: 2026-08-05 20:55:50.414299+00:00

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
revision: str = "022b1154b3aa"
down_revision: str | None = "d338ba5a8f7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'entity_research_job'")
    op.execute(
        """
        CREATE TABLE entity_research_run (
            research_run_id       uuid PRIMARY KEY,
            run_kind              text NOT NULL,
            subject_type          text NOT NULL,
            workspace_id          text NOT NULL,
            project_id            text NOT NULL,
            product_id            text NOT NULL,
            project_run_id        uuid NOT NULL,
            selection_id          uuid NOT NULL UNIQUE,
            lifecycle_json        jsonb NOT NULL,
            lifecycle_sha256      text NOT NULL,
            budget_envelope_ref   text NOT NULL,
            budget_cap_cents      numeric(18, 6) NOT NULL,
            spent_cents           numeric(18, 6) NOT NULL DEFAULT 0,
            concurrency_limit     integer NOT NULL,
            state                 text NOT NULL DEFAULT 'queued',
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now(),
            terminal_at           timestamptz,

            CONSTRAINT entity_research_run_kind
                CHECK (run_kind IN ('account_research', 'contact_research')),
            CONSTRAINT entity_research_run_subject
                CHECK (subject_type IN ('account', 'contact')),
            CONSTRAINT entity_research_run_kind_subject CHECK (
                (run_kind = 'account_research' AND subject_type = 'account') OR
                (run_kind = 'contact_research' AND subject_type = 'contact')
            ),
            CONSTRAINT entity_research_run_lifecycle_object
                CHECK (jsonb_typeof(lifecycle_json) = 'object'),
            CONSTRAINT entity_research_run_lifecycle_scope CHECK ((
                lifecycle_json->>'run_id' = research_run_id::text AND
                lifecycle_json->>'run_kind' = run_kind AND
                lifecycle_json->'selection'->>'selection_id' = selection_id::text AND
                lifecycle_json->'selection'->>'subject_type' = subject_type AND
                lifecycle_json->'selection'->>'workspace_id' = workspace_id::text AND
                lifecycle_json->'selection'->>'project_id' = project_id::text AND
                lifecycle_json->'selection'->>'product_id' = product_id::text AND
                lifecycle_json->'selection'->>'project_run_id' = project_run_id::text AND
                lifecycle_json->'selection'->>'budget_envelope_ref' = budget_envelope_ref
            ) IS TRUE),
            CONSTRAINT entity_research_run_lifecycle_sha
                CHECK (lifecycle_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_run_budget_nonnegative
                CHECK (budget_cap_cents >= 0 AND spent_cents >= 0
                       AND spent_cents <= budget_cap_cents),
            CONSTRAINT entity_research_run_budget_ref_nonempty
                CHECK (length(budget_envelope_ref) > 0),
            CONSTRAINT entity_research_run_concurrency_positive CHECK (concurrency_limit >= 1),
            CONSTRAINT entity_research_run_state
                CHECK (state IN ('queued', 'running', 'waiting_external', 'terminal')),
            CONSTRAINT entity_research_run_terminal_shape CHECK (
                (state = 'terminal' AND terminal_at IS NOT NULL) OR
                (state <> 'terminal' AND terminal_at IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_run_scope "
        "ON entity_research_run (workspace_id, project_id, product_id, project_run_id, run_kind)"
    )
    op.execute(
        "CREATE INDEX entity_research_run_state_idx ON entity_research_run (state, created_at)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_job (
            job_id                       uuid PRIMARY KEY,
            research_run_id              uuid NOT NULL REFERENCES entity_research_run
                                             (research_run_id) ON DELETE RESTRICT,
            subject_type                 text NOT NULL,
            subject_entity_id            uuid NOT NULL,
            parent_account_id            uuid,
            workspace_id                 text NOT NULL,
            project_id                   text NOT NULL,
            product_id                   text NOT NULL,
            project_run_id               uuid NOT NULL,
            authorization_json           jsonb NOT NULL,
            authorization_sha256         text NOT NULL,
            priority                     integer NOT NULL DEFAULT 0,
            budget_envelope_ref           text NOT NULL,
            budget_cap_cents              numeric(18, 6) NOT NULL,
            spent_cents                   numeric(18, 6) NOT NULL DEFAULT 0,
            checkpoint_thread_id          text NOT NULL,
            checkpoint_ref                text,
            checkpoint_sha256             text,
            current_state_sha256          text NOT NULL,
            state                         text NOT NULL DEFAULT 'queued',
            current_wait_ref              text,
            active_worker_id              text,
            lease_generation              bigint,
            finalization_outcome          text,
            finalization_receipt_ref       text,
            created_at                    timestamptz NOT NULL DEFAULT now(),
            updated_at                    timestamptz NOT NULL DEFAULT now(),
            terminal_at                   timestamptz,

            CONSTRAINT entity_research_job_subject
                CHECK (subject_type IN ('account', 'contact')),
            CONSTRAINT entity_research_job_parent_shape CHECK (
                (subject_type = 'account' AND parent_account_id IS NULL) OR
                (subject_type = 'contact' AND parent_account_id IS NOT NULL)
            ),
            CONSTRAINT entity_research_job_authorization_object
                CHECK (jsonb_typeof(authorization_json) = 'object'),
            CONSTRAINT entity_research_job_authorization_scope CHECK ((
                authorization_json->>'job_id' = job_id::text AND
                authorization_json->>'research_run_id' = research_run_id::text AND
                authorization_json->>'subject_type' = subject_type AND
                authorization_json->>'subject_entity_id' = subject_entity_id::text AND
                authorization_json->>'workspace_id' = workspace_id::text AND
                authorization_json->>'project_id' = project_id::text AND
                authorization_json->>'product_id' = product_id::text AND
                authorization_json->>'project_run_id' = project_run_id::text AND
                authorization_json->>'checkpoint_thread_id' = checkpoint_thread_id AND
                authorization_json->'selection'->>'workspace_id' = workspace_id::text AND
                authorization_json->'selection'->>'project_id' = project_id::text AND
                authorization_json->'selection'->>'product_id' = product_id::text AND
                authorization_json->'selection'->>'project_run_id' = project_run_id::text AND
                (
                    (parent_account_id IS NULL AND
                     authorization_json->>'parent_account_id' IS NULL) OR
                    authorization_json->>'parent_account_id' = parent_account_id::text
                )
            ) IS TRUE),
            CONSTRAINT entity_research_job_authorization_sha
                CHECK (authorization_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_job_state_sha
                CHECK (current_state_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_job_checkpoint_pair CHECK (
                (checkpoint_ref IS NULL AND checkpoint_sha256 IS NULL) OR
                (checkpoint_ref IS NOT NULL AND checkpoint_sha256 ~ '^[0-9a-f]{64}$')
            ),
            CONSTRAINT entity_research_job_budget_nonnegative
                CHECK (budget_cap_cents >= 0 AND spent_cents >= 0
                       AND spent_cents <= budget_cap_cents),
            CONSTRAINT entity_research_job_budget_ref_nonempty
                CHECK (length(budget_envelope_ref) > 0),
            CONSTRAINT entity_research_job_checkpoint_thread_nonempty
                CHECK (length(checkpoint_thread_id) > 0),
            CONSTRAINT entity_research_job_state CHECK (
                state IN ('queued', 'leased', 'running', 'waiting_external', 'terminal')
            ),
            CONSTRAINT entity_research_job_active_lease_shape CHECK (
                (state IN ('leased', 'running') AND active_worker_id IS NOT NULL
                    AND lease_generation >= 1) OR
                (state NOT IN ('leased', 'running') AND active_worker_id IS NULL)
            ),
            CONSTRAINT entity_research_job_wait_shape CHECK (
                (state = 'waiting_external' AND current_wait_ref IS NOT NULL) OR
                (state <> 'waiting_external' AND current_wait_ref IS NULL)
            ),
            CONSTRAINT entity_research_job_finalization_outcome CHECK (
                finalization_outcome IS NULL OR finalization_outcome IN
                    ('completed', 'exhausted', 'needs_review', 'budget_stopped',
                     'cancelled', 'failed')
            ),
            CONSTRAINT entity_research_job_terminal_shape CHECK (
                (
                    state = 'terminal' AND finalization_outcome IS NOT NULL
                    AND finalization_receipt_ref IS NOT NULL AND terminal_at IS NOT NULL
                ) OR (
                    state <> 'terminal' AND finalization_outcome IS NULL
                    AND finalization_receipt_ref IS NULL AND terminal_at IS NULL
                )
            ),
            CONSTRAINT entity_research_job_subject_once
                UNIQUE (research_run_id, subject_entity_id),
            CONSTRAINT entity_research_job_checkpoint_thread_once
                UNIQUE (research_run_id, checkpoint_thread_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_job_drain "
        "ON entity_research_job (research_run_id, state, priority, created_at)"
    )
    op.execute(
        "CREATE INDEX entity_research_job_scope "
        "ON entity_research_job "
        "(workspace_id, project_id, product_id, project_run_id, subject_type)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_job_wait (
            wait_id                 uuid PRIMARY KEY,
            research_run_id         uuid NOT NULL REFERENCES entity_research_run
                                        (research_run_id) ON DELETE RESTRICT,
            job_id                  uuid NOT NULL REFERENCES entity_research_job
                                        (job_id) ON DELETE RESTRICT,
            wait_ref                text NOT NULL,
            checkpoint_ref          text NOT NULL,
            checkpoint_sha256       text NOT NULL,
            current_state_sha256    text NOT NULL,
            state                   text NOT NULL DEFAULT 'active',
            created_at              timestamptz NOT NULL DEFAULT now(),
            resolved_at             timestamptz,
            resolved_by             text,

            CONSTRAINT entity_research_job_wait_ref_once UNIQUE (job_id, wait_ref),
            CONSTRAINT entity_research_job_wait_checkpoint_sha
                CHECK (checkpoint_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_job_wait_state_sha
                CHECK (current_state_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_job_wait_state
                CHECK (state IN ('active', 'woken', 'cancelled')),
            CONSTRAINT entity_research_job_wait_resolution CHECK (
                (state = 'active' AND resolved_at IS NULL AND resolved_by IS NULL) OR
                (state <> 'active' AND resolved_at IS NOT NULL AND resolved_by IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX entity_research_job_one_active_wait "
        "ON entity_research_job_wait (job_id) WHERE state = 'active'"
    )
    op.execute(
        """
        CREATE TABLE entity_research_job_finalization (
            receipt_id              uuid PRIMARY KEY,
            research_run_id         uuid NOT NULL REFERENCES entity_research_run
                                        (research_run_id) ON DELETE RESTRICT,
            job_id                  uuid NOT NULL UNIQUE REFERENCES entity_research_job
                                        (job_id) ON DELETE RESTRICT,
            receipt_ref             text NOT NULL UNIQUE,
            proposal_id             uuid NOT NULL UNIQUE,
            outcome                 text NOT NULL,
            accepted_state_sha256   text NOT NULL,
            receipt_json            jsonb NOT NULL,
            accepted_at             timestamptz NOT NULL,
            engine_actor            text NOT NULL,

            CONSTRAINT entity_research_job_finalization_outcome CHECK (
                outcome IN ('completed', 'exhausted', 'needs_review', 'budget_stopped',
                            'cancelled', 'failed')
            ),
            CONSTRAINT entity_research_job_finalization_state_sha
                CHECK (accepted_state_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_job_finalization_receipt_object
                CHECK (jsonb_typeof(receipt_json) = 'object')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE entity_research_job_event (
            event_id          uuid PRIMARY KEY,
            event_seq         bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
            research_run_id   uuid NOT NULL REFERENCES entity_research_run
                                  (research_run_id) ON DELETE RESTRICT,
            job_id            uuid NOT NULL REFERENCES entity_research_job
                                  (job_id) ON DELETE RESTRICT,
            event_kind        text NOT NULL,
            from_state        text,
            to_state          text NOT NULL,
            actor             text NOT NULL,
            references_json   jsonb NOT NULL DEFAULT '{}'::jsonb,
            occurred_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT entity_research_job_event_kind CHECK (
                event_kind IN ('queued', 'leased', 'started', 'checkpointed',
                               'waiting_external', 'woken', 'finalized', 'cancelled',
                               'lease_taken_over')
            ),
            CONSTRAINT entity_research_job_event_from_state CHECK (
                from_state IS NULL OR from_state IN
                    ('queued', 'leased', 'running', 'waiting_external', 'terminal')
            ),
            CONSTRAINT entity_research_job_event_to_state CHECK (
                to_state IN ('queued', 'leased', 'running', 'waiting_external', 'terminal')
            ),
            CONSTRAINT entity_research_job_event_references_object
                CHECK (jsonb_typeof(references_json) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_job_event_order "
        "ON entity_research_job_event (job_id, event_seq)"
    )
    op.execute(
        """
        CREATE FUNCTION prevent_entity_research_authority_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'entity_research_run' THEN
                IF ROW(NEW.run_kind, NEW.subject_type, NEW.workspace_id, NEW.project_id,
                       NEW.product_id, NEW.project_run_id, NEW.selection_id, NEW.lifecycle_json,
                       NEW.lifecycle_sha256, NEW.budget_envelope_ref, NEW.budget_cap_cents,
                       NEW.concurrency_limit)
                   IS DISTINCT FROM
                   ROW(OLD.run_kind, OLD.subject_type, OLD.workspace_id, OLD.project_id,
                       OLD.product_id, OLD.project_run_id, OLD.selection_id, OLD.lifecycle_json,
                       OLD.lifecycle_sha256, OLD.budget_envelope_ref, OLD.budget_cap_cents,
                       OLD.concurrency_limit) THEN
                    RAISE EXCEPTION 'entity research run authority is immutable';
                END IF;
            ELSE
                IF ROW(NEW.research_run_id, NEW.subject_type, NEW.subject_entity_id,
                       NEW.parent_account_id, NEW.workspace_id, NEW.project_id, NEW.product_id,
                       NEW.project_run_id, NEW.authorization_json, NEW.authorization_sha256,
                       NEW.priority, NEW.budget_envelope_ref, NEW.budget_cap_cents,
                       NEW.checkpoint_thread_id)
                   IS DISTINCT FROM
                   ROW(OLD.research_run_id, OLD.subject_type, OLD.subject_entity_id,
                       OLD.parent_account_id, OLD.workspace_id, OLD.project_id, OLD.product_id,
                       OLD.project_run_id, OLD.authorization_json, OLD.authorization_sha256,
                       OLD.priority, OLD.budget_envelope_ref, OLD.budget_cap_cents,
                       OLD.checkpoint_thread_id) THEN
                    RAISE EXCEPTION 'entity research job authority is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_run_authority_immutable "
        "BEFORE UPDATE ON entity_research_run FOR EACH ROW "
        "EXECUTE FUNCTION prevent_entity_research_authority_mutation()"
    )
    op.execute(
        "CREATE TRIGGER entity_research_job_authority_immutable "
        "BEFORE UPDATE ON entity_research_job FOR EACH ROW "
        "EXECUTE FUNCTION prevent_entity_research_authority_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER entity_research_job_authority_immutable ON entity_research_job")
    op.execute("DROP TRIGGER entity_research_run_authority_immutable ON entity_research_run")
    op.execute("DROP FUNCTION prevent_entity_research_authority_mutation")
    op.execute("DROP TABLE entity_research_job_event")
    op.execute("DROP TABLE entity_research_job_finalization")
    op.execute("DROP TABLE entity_research_job_wait")
    op.execute("DROP TABLE entity_research_job")
    op.execute("DROP TABLE entity_research_run")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM fleet_task WHERE kind::text = 'entity_research_job'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade M8D R2 while entity_research_job fleet tasks exist';
            END IF;
        END $$
        """
    )
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_m8d_r2")
    op.execute("CREATE TYPE fleet_task_kind AS ENUM ('drive_run', 'account_job', 'execute_graph')")
    op.execute(
        """
        ALTER TABLE fleet_task
        ALTER COLUMN kind TYPE fleet_task_kind
        USING kind::text::fleet_task_kind
        """
    )
    op.execute("DROP TYPE fleet_task_kind_m8d_r2")
