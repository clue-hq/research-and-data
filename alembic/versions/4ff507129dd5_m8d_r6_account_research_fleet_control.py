"""m8d r6 account research fleet control

Revision ID: 4ff507129dd5
Revises: 85595185f793
Create Date: 2026-08-06 04:50:42.972472+00:00

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
revision: str = "4ff507129dd5"
down_revision: str | None = "85595185f793"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_research_account_fleet (
            research_run_id       uuid PRIMARY KEY REFERENCES entity_research_run
                                      (research_run_id) ON DELETE RESTRICT,
            workspace_id          text NOT NULL,
            project_id            text NOT NULL,
            product_id            text NOT NULL,
            project_run_id        uuid NOT NULL,
            canary_job_ids        uuid[] NOT NULL,
            supervisor_policy_ref text NOT NULL,
            supervisor_policy_json jsonb NOT NULL,
            supervisor_policy_sha256 text NOT NULL,
            state                  text NOT NULL DEFAULT 'canary',
            diagnosis_json         jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_by             text NOT NULL,
            source_operation_id    uuid NOT NULL,
            source_action_ref      text NOT NULL,
            created_at             timestamptz NOT NULL DEFAULT now(),
            updated_at             timestamptz NOT NULL DEFAULT now(),
            suspended_at           timestamptz,
            terminal_at            timestamptz,
            CONSTRAINT entity_research_account_fleet_canary_nonempty
                CHECK (cardinality(canary_job_ids) >= 1),
            CONSTRAINT entity_research_account_fleet_policy_ref_nonempty
                CHECK (length(btrim(supervisor_policy_ref)) > 0),
            CONSTRAINT entity_research_account_fleet_policy_object
                CHECK (jsonb_typeof(supervisor_policy_json) = 'object'),
            CONSTRAINT entity_research_account_fleet_policy_sha
                CHECK (supervisor_policy_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_account_fleet_state CHECK (
                state IN ('canary', 'open', 'waiting_external', 'suspended', 'terminal')
            ),
            CONSTRAINT entity_research_account_fleet_diagnosis_object
                CHECK (jsonb_typeof(diagnosis_json) = 'object'),
            CONSTRAINT entity_research_account_fleet_terminal_shape CHECK (
                (state = 'terminal' AND terminal_at IS NOT NULL AND suspended_at IS NULL) OR
                (state = 'suspended' AND suspended_at IS NOT NULL AND terminal_at IS NULL) OR
                (state NOT IN ('terminal', 'suspended') AND terminal_at IS NULL
                    AND suspended_at IS NULL)
            ),
            CONSTRAINT entity_research_account_fleet_creator_nonempty
                CHECK (length(btrim(created_by)) > 0 AND length(btrim(source_action_ref)) > 0),
            CONSTRAINT entity_research_account_fleet_action_unique
                UNIQUE (workspace_id, source_action_ref)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_account_fleet_scope ON "
        "entity_research_account_fleet "
        "(workspace_id, project_id, product_id, project_run_id, state)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_account_fleet_job_control (
            job_id             uuid PRIMARY KEY REFERENCES entity_research_job
                                   (job_id) ON DELETE RESTRICT,
            research_run_id    uuid NOT NULL REFERENCES entity_research_account_fleet
                                   (research_run_id) ON DELETE RESTRICT,
            account_run_id     uuid REFERENCES account_run (id) ON DELETE RESTRICT,
            cohort             text NOT NULL,
            admission_state    text NOT NULL,
            effective_priority integer NOT NULL,
            pause_reason       text,
            created_at         timestamptz NOT NULL DEFAULT now(),
            updated_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_account_fleet_job_cohort
                CHECK (cohort IN ('canary', 'remainder')),
            CONSTRAINT entity_research_account_fleet_job_admission CHECK (
                admission_state IN ('admitted', 'held', 'released', 'paused', 'terminal')
            ),
            CONSTRAINT entity_research_account_fleet_job_pause_shape CHECK (
                (admission_state = 'paused' AND length(btrim(pause_reason)) > 0) OR
                (admission_state <> 'paused' AND pause_reason IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_account_fleet_job_drain ON "
        "entity_research_account_fleet_job_control "
        "(research_run_id, admission_state, effective_priority, job_id)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_account_fleet_control_event (
            event_seq        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id         uuid NOT NULL UNIQUE,
            research_run_id  uuid NOT NULL REFERENCES entity_research_account_fleet
                                 (research_run_id) ON DELETE RESTRICT,
            job_id           uuid REFERENCES entity_research_job (job_id) ON DELETE RESTRICT,
            actor            text NOT NULL,
            action           text NOT NULL,
            before_json      jsonb NOT NULL,
            after_json       jsonb NOT NULL,
            reason_code      text NOT NULL,
            references_json  jsonb NOT NULL DEFAULT '{}'::jsonb,
            occurred_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_account_fleet_event_actor
                CHECK (length(btrim(actor)) > 0 AND length(btrim(action)) > 0
                    AND length(btrim(reason_code)) > 0),
            CONSTRAINT entity_research_account_fleet_event_objects CHECK (
                jsonb_typeof(before_json) = 'object' AND
                jsonb_typeof(after_json) = 'object' AND
                jsonb_typeof(references_json) = 'object'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_account_fleet_event_run ON "
        "entity_research_account_fleet_control_event (research_run_id, event_seq)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_account_fleet_return (
            return_seq       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            return_id        uuid NOT NULL UNIQUE,
            research_run_id  uuid NOT NULL REFERENCES entity_research_account_fleet
                                 (research_run_id) ON DELETE RESTRICT,
            workspace_id     text NOT NULL,
            return_kind      text NOT NULL,
            payload_json     jsonb NOT NULL,
            payload_sha256   text NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_account_fleet_return_kind
                CHECK (return_kind IN ('suspended', 'terminal')),
            CONSTRAINT entity_research_account_fleet_return_object
                CHECK (jsonb_typeof(payload_json) = 'object'),
            CONSTRAINT entity_research_account_fleet_return_sha
                CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_account_fleet_return_once
                UNIQUE (research_run_id, payload_sha256)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_account_fleet_return_latest ON "
        "entity_research_account_fleet_return (research_run_id, return_seq DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION validate_entity_research_account_fleet_scope()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            run_row entity_research_run%ROWTYPE;
            job_row entity_research_job%ROWTYPE;
            account_run_row account_run%ROWTYPE;
        BEGIN
            SELECT * INTO run_row FROM entity_research_run
            WHERE research_run_id = NEW.research_run_id;
            IF run_row.run_kind <> 'account_research' OR run_row.subject_type <> 'account' THEN
                RAISE EXCEPTION 'account fleet requires an account-research run';
            END IF;
            IF TG_TABLE_NAME = 'entity_research_account_fleet' THEN
                IF run_row.workspace_id <> NEW.workspace_id OR
                   run_row.project_id <> NEW.project_id OR
                   run_row.product_id <> NEW.product_id OR
                   run_row.project_run_id <> NEW.project_run_id THEN
                    RAISE EXCEPTION 'account fleet scope differs from its research run';
                END IF;
                RETURN NEW;
            END IF;
            SELECT * INTO job_row FROM entity_research_job WHERE job_id = NEW.job_id;
            IF job_row.research_run_id <> NEW.research_run_id OR
               job_row.subject_type <> 'account' THEN
                RAISE EXCEPTION 'account fleet job control crosses run or subject scope';
            END IF;
            IF NEW.account_run_id IS NOT NULL THEN
                SELECT * INTO account_run_row FROM account_run WHERE id = NEW.account_run_id;
                IF NOT FOUND OR account_run_row.project_run_id <> run_row.project_run_id OR
                   account_run_row.entity_id <> job_row.subject_entity_id THEN
                    RAISE EXCEPTION 'account fleet job control has the wrong account run';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_account_fleet_scope_guard BEFORE INSERT OR UPDATE ON "
        "entity_research_account_fleet FOR EACH ROW EXECUTE FUNCTION "
        "validate_entity_research_account_fleet_scope()"
    )
    op.execute(
        "CREATE TRIGGER entity_research_account_fleet_job_scope_guard BEFORE INSERT OR UPDATE ON "
        "entity_research_account_fleet_job_control FOR EACH ROW EXECUTE FUNCTION "
        "validate_entity_research_account_fleet_scope()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_entity_research_account_fleet_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'account fleet events and returns are append-only';
        END
        $$
        """
    )
    for table in (
        "entity_research_account_fleet_control_event",
        "entity_research_account_fleet_return",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "reject_entity_research_account_fleet_history_mutation()"
        )


def downgrade() -> None:
    for table in (
        "entity_research_account_fleet_return",
        "entity_research_account_fleet_control_event",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_entity_research_account_fleet_history_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS entity_research_account_fleet_job_scope_guard ON "
        "entity_research_account_fleet_job_control"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS entity_research_account_fleet_scope_guard ON "
        "entity_research_account_fleet"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_entity_research_account_fleet_scope()")
    op.execute("DROP TABLE IF EXISTS entity_research_account_fleet_return")
    op.execute("DROP TABLE IF EXISTS entity_research_account_fleet_control_event")
    op.execute("DROP TABLE IF EXISTS entity_research_account_fleet_job_control")
    op.execute("DROP TABLE IF EXISTS entity_research_account_fleet")
