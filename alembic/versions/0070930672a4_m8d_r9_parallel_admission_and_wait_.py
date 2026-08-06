"""m8d r9 parallel admission and wait joining

Revision ID: 0070930672a4
Revises: 7bb3178d7580
Create Date: 2026-08-06 10:43:11.958123+00:00

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
revision: str = "0070930672a4"
down_revision: str | None = "7bb3178d7580"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_research_tool_batch (
            batch_id                    uuid PRIMARY KEY,
            agent_turn_id               uuid NOT NULL,
            agent_execution_id          uuid NOT NULL,
            research_run_id             uuid NOT NULL REFERENCES
                                        entity_research_run(research_run_id),
            job_id                      uuid NOT NULL REFERENCES entity_research_job(job_id),
            subject_type                text NOT NULL,
            target_entity_id            uuid NOT NULL,
            workspace_id                text NOT NULL,
            concurrency_cap             integer NOT NULL,
            call_count                  integer NOT NULL,
            batch_json                  jsonb NOT NULL,
            batch_sha256                text NOT NULL,
            created_at                  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_tool_batch_turn_fk
                FOREIGN KEY (agent_turn_id, agent_execution_id)
                REFERENCES entity_research_agent_turn(agent_turn_id, agent_execution_id),
            CONSTRAINT entity_research_tool_batch_subject
                CHECK (subject_type IN ('account', 'contact')),
            CONSTRAINT entity_research_tool_batch_count
                CHECK (call_count BETWEEN 1 AND concurrency_cap),
            CONSTRAINT entity_research_tool_batch_object
                CHECK (jsonb_typeof(batch_json)='object'),
            CONSTRAINT entity_research_tool_batch_sha
                CHECK (batch_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_tool_batch_turn_digest
                UNIQUE (agent_turn_id, batch_sha256)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_tool_batch_job ON "
        "entity_research_tool_batch(job_id, created_at, batch_id)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_budget_reservation (
            reservation_id             uuid PRIMARY KEY,
            research_run_id            uuid NOT NULL REFERENCES
                                       entity_research_run(research_run_id),
            job_id                     uuid NOT NULL REFERENCES entity_research_job(job_id),
            workspace_id               text NOT NULL,
            budget_envelope_ref        text NOT NULL,
            tool_name                  text NOT NULL,
            tool_input_sha256          text NOT NULL,
            provider_family            text NOT NULL,
            reserved_cents             numeric(18, 6) NOT NULL,
            created_at                 timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_budget_reservation_positive CHECK (reserved_cents > 0),
            CONSTRAINT entity_research_budget_reservation_sha
                CHECK (tool_input_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_budget_reservation_nonempty CHECK (
                length(btrim(budget_envelope_ref)) > 0 AND
                length(btrim(tool_name)) > 0 AND length(btrim(provider_family)) > 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_budget_reservation_active ON "
        "entity_research_budget_reservation(job_id, created_at, reservation_id)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_tool_batch_member (
            batch_id                    uuid NOT NULL REFERENCES
                                        entity_research_tool_batch(batch_id),
            raw_tool_call_id            text NOT NULL,
            tool_name                   text NOT NULL,
            tool_version                integer NOT NULL,
            tool_input_sha256           text NOT NULL,
            field_keys                  text[] NOT NULL DEFAULT '{}',
            source_keys                 text[] NOT NULL DEFAULT '{}',
            facet_key                   text,
            provider_family             text,
            budget_reservation_cents    numeric(18, 6) NOT NULL DEFAULT 0,
            provider_rate_limit_ref     text,
            provider_concurrency_limit  integer,
            budget_reservation_id       uuid REFERENCES
                                        entity_research_budget_reservation(reservation_id),
            created_at                  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (batch_id, raw_tool_call_id),
            CONSTRAINT entity_research_tool_batch_member_version CHECK (tool_version >= 1),
            CONSTRAINT entity_research_tool_batch_member_sha
                CHECK (tool_input_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_tool_batch_member_external CHECK (
                (provider_family IS NULL AND budget_reservation_cents=0 AND
                 provider_rate_limit_ref IS NULL AND provider_concurrency_limit IS NULL AND
                 budget_reservation_id IS NULL) OR
                (length(btrim(provider_family)) > 0 AND budget_reservation_cents > 0 AND
                 length(btrim(provider_rate_limit_ref)) > 0 AND
                 provider_concurrency_limit >= 1 AND budget_reservation_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_tool_batch_member_replay ON "
        "entity_research_tool_batch_member(tool_name, tool_input_sha256, created_at)"
    )
    op.execute(
        "CREATE INDEX entity_research_tool_batch_member_reservation ON "
        "entity_research_tool_batch_member(budget_reservation_id) "
        "WHERE budget_reservation_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE entity_research_provider_permit (
            permit_id                   uuid PRIMARY KEY,
            batch_id                    uuid NOT NULL,
            raw_tool_call_id            text NOT NULL,
            research_run_id             uuid NOT NULL REFERENCES
                                        entity_research_run(research_run_id),
            job_id                      uuid NOT NULL REFERENCES entity_research_job(job_id),
            provider_family             text NOT NULL,
            provider_rate_limit_ref     text NOT NULL,
            concurrency_limit           integer NOT NULL,
            created_at                  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_provider_permit_member_fk
                FOREIGN KEY (batch_id, raw_tool_call_id)
                REFERENCES entity_research_tool_batch_member(batch_id, raw_tool_call_id),
            CONSTRAINT entity_research_provider_permit_limit CHECK (concurrency_limit >= 1),
            CONSTRAINT entity_research_provider_permit_member_once
                UNIQUE (batch_id, raw_tool_call_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_provider_permit_active ON "
        "entity_research_provider_permit(provider_rate_limit_ref, created_at, permit_id)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_tool_batch_event (
            event_seq                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id                    uuid NOT NULL UNIQUE,
            batch_id                    uuid NOT NULL,
            raw_tool_call_id            text NOT NULL,
            event_kind                  text NOT NULL,
            disposition                 text NOT NULL,
            member_wait_ref             text,
            result_json                 jsonb,
            result_sha256               text,
            error_json                  jsonb,
            result_erased_at            timestamptz,
            created_at                  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_tool_batch_event_member_fk
                FOREIGN KEY (batch_id, raw_tool_call_id)
                REFERENCES entity_research_tool_batch_member(batch_id, raw_tool_call_id),
            CONSTRAINT entity_research_tool_batch_event_kind_once
                UNIQUE (batch_id, raw_tool_call_id, event_kind),
            CONSTRAINT entity_research_tool_batch_event_kind
                CHECK (event_kind IN ('completed', 'waiting_external', 'failed')),
            CONSTRAINT entity_research_tool_batch_event_shape CHECK (
                (event_kind='completed' AND result_json IS NOT NULL AND
                 result_sha256 ~ '^[0-9a-f]{64}$' AND member_wait_ref IS NULL AND
                 error_json IS NULL) OR
                (event_kind='waiting_external' AND length(btrim(member_wait_ref)) > 0 AND
                 result_json IS NULL AND result_sha256 IS NULL AND error_json IS NULL) OR
                (event_kind='failed' AND jsonb_typeof(error_json)='object' AND
                 member_wait_ref IS NULL AND result_json IS NULL AND result_sha256 IS NULL)
            ),
            CONSTRAINT entity_research_tool_batch_event_erasure CHECK (
                result_erased_at IS NULL OR
                (event_kind='completed' AND result_json='{"erased": true}'::jsonb)
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX entity_research_tool_batch_member_completed ON "
        "entity_research_tool_batch_event(batch_id, raw_tool_call_id) "
        "WHERE event_kind='completed'"
    )
    op.execute(
        "CREATE INDEX entity_research_tool_batch_event_latest ON "
        "entity_research_tool_batch_event(batch_id, raw_tool_call_id, event_seq DESC)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_tool_batch_result_subject (
            event_id                    uuid NOT NULL REFERENCES
                                        entity_research_tool_batch_event(event_id),
            workspace_id                text NOT NULL,
            subject_type                text NOT NULL,
            target_entity_id            uuid NOT NULL,
            created_at                  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (event_id, subject_type, target_entity_id),
            CONSTRAINT entity_research_batch_result_subject_type
                CHECK (subject_type IN ('account', 'contact'))
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_batch_result_subject_lookup ON "
        "entity_research_tool_batch_result_subject"
        "(workspace_id, subject_type, target_entity_id, event_id)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_budget_reservation_release (
            reservation_id             uuid PRIMARY KEY REFERENCES
                                       entity_research_budget_reservation(reservation_id),
            disposition                text NOT NULL,
            settled_cost_cents         numeric(18, 6) NOT NULL,
            released_by_event_id       uuid NOT NULL REFERENCES
                                       entity_research_tool_batch_event(event_id),
            released_at                timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_budget_release_disposition CHECK (
                disposition IN ('settled', 'failed_before_dispatch', 'cancelled_before_dispatch')
            ),
            CONSTRAINT entity_research_budget_release_cost CHECK (
                settled_cost_cents >= 0 AND
                (disposition='settled' OR settled_cost_cents=0)
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE entity_research_provider_permit_release (
            permit_id                   uuid PRIMARY KEY REFERENCES
                                       entity_research_provider_permit(permit_id),
            disposition                text NOT NULL,
            released_by_event_id       uuid NOT NULL REFERENCES
                                       entity_research_tool_batch_event(event_id),
            released_at                timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_provider_permit_release_disposition CHECK (
                disposition IN ('completed', 'waiting_external', 'failed')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE entity_research_tool_batch_wait (
            batch_id                    uuid PRIMARY KEY REFERENCES
                                        entity_research_tool_batch(batch_id),
            wait_ref                    text NOT NULL UNIQUE,
            research_run_id             uuid NOT NULL REFERENCES
                                        entity_research_run(research_run_id),
            job_id                      uuid NOT NULL REFERENCES entity_research_job(job_id),
            member_wait_refs            text[] NOT NULL,
            state                       text NOT NULL DEFAULT 'active',
            created_at                  timestamptz NOT NULL DEFAULT now(),
            resolved_at                 timestamptz,
            resolved_by                 text,
            CONSTRAINT entity_research_tool_batch_wait_members
                CHECK (cardinality(member_wait_refs) >= 1),
            CONSTRAINT entity_research_tool_batch_wait_state
                CHECK (state IN ('active', 'woken', 'cancelled')),
            CONSTRAINT entity_research_tool_batch_wait_resolution CHECK (
                (state='active' AND resolved_at IS NULL AND resolved_by IS NULL) OR
                (state<>'active' AND resolved_at IS NOT NULL AND length(btrim(resolved_by)) > 0)
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE entity_research_tool_batch_wait_member (
            batch_id                    uuid NOT NULL REFERENCES
                                        entity_research_tool_batch_wait(batch_id),
            member_wait_ref             text NOT NULL,
            state                       text NOT NULL DEFAULT 'active',
            ready_at                    timestamptz,
            ready_by                    text,
            PRIMARY KEY (batch_id, member_wait_ref),
            CONSTRAINT entity_research_tool_batch_wait_member_state
                CHECK (state IN ('active', 'ready')),
            CONSTRAINT entity_research_tool_batch_wait_member_ready CHECK (
                (state='active' AND ready_at IS NULL AND ready_by IS NULL) OR
                (state='ready' AND ready_at IS NOT NULL AND length(btrim(ready_by)) > 0)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_tool_batch_wait_lookup ON "
        "entity_research_tool_batch_wait_member(member_wait_ref, state)"
    )
    op.execute(
        """
        CREATE FUNCTION entity_research_validate_tool_batch() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM entity_research_agent_turn turn_row
                JOIN entity_research_job job ON job.job_id=NEW.job_id
                WHERE turn_row.agent_turn_id=NEW.agent_turn_id
                  AND turn_row.agent_execution_id=NEW.agent_execution_id
                  AND turn_row.job_id=NEW.job_id
                  AND turn_row.research_run_id=NEW.research_run_id
                  AND turn_row.subject_type=NEW.subject_type
                  AND turn_row.target_entity_id=NEW.target_entity_id
                  AND turn_row.workspace_id=NEW.workspace_id
                  AND job.research_run_id=NEW.research_run_id
                  AND job.subject_type=NEW.subject_type
                  AND job.subject_entity_id=NEW.target_entity_id
                  AND job.workspace_id=NEW.workspace_id
                  AND job.state='running'
            ) THEN
                RAISE EXCEPTION 'entity research tool batch crosses live job authority';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_tool_batch_authority BEFORE INSERT ON "
        "entity_research_tool_batch FOR EACH ROW EXECUTE FUNCTION "
        "entity_research_validate_tool_batch()"
    )
    op.execute(
        """
        CREATE FUNCTION entity_research_reject_parallel_history_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'entity research parallel history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "entity_research_tool_batch",
        "entity_research_budget_reservation",
        "entity_research_tool_batch_member",
        "entity_research_provider_permit",
        "entity_research_tool_batch_result_subject",
        "entity_research_budget_reservation_release",
        "entity_research_provider_permit_release",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION entity_research_reject_parallel_history_mutation()"
        )
    op.execute(
        """
        CREATE FUNCTION entity_research_protect_tool_batch_event() RETURNS trigger AS $$
        BEGIN
            IF TG_OP='UPDATE'
               AND OLD.event_kind='completed'
               AND OLD.result_erased_at IS NULL
               AND NEW.result_erased_at IS NOT NULL
               AND NEW.result_json='{"erased": true}'::jsonb
               AND (to_jsonb(NEW)-'result_json'-'result_erased_at') =
                   (to_jsonb(OLD)-'result_json'-'result_erased_at') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'entity research parallel history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_tool_batch_event_append_only BEFORE UPDATE OR DELETE ON "
        "entity_research_tool_batch_event FOR EACH ROW EXECUTE FUNCTION "
        "entity_research_protect_tool_batch_event()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS entity_research_tool_batch_event_append_only ON "
        "entity_research_tool_batch_event"
    )
    op.execute("DROP FUNCTION IF EXISTS entity_research_protect_tool_batch_event")
    for table in (
        "entity_research_provider_permit_release",
        "entity_research_budget_reservation_release",
        "entity_research_tool_batch_result_subject",
        "entity_research_provider_permit",
        "entity_research_tool_batch_member",
        "entity_research_budget_reservation",
        "entity_research_tool_batch",
    ):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.execute("DROP FUNCTION entity_research_reject_parallel_history_mutation")
    op.execute("DROP TRIGGER entity_research_tool_batch_authority ON entity_research_tool_batch")
    op.execute("DROP FUNCTION entity_research_validate_tool_batch")
    op.execute("DROP TABLE entity_research_tool_batch_wait_member")
    op.execute("DROP TABLE entity_research_tool_batch_wait")
    op.execute("DROP TABLE entity_research_tool_batch_result_subject")
    op.execute("DROP TABLE entity_research_provider_permit_release")
    op.execute("DROP TABLE entity_research_budget_reservation_release")
    op.execute("DROP TABLE entity_research_tool_batch_event")
    op.execute("DROP TABLE entity_research_provider_permit")
    op.execute("DROP TABLE entity_research_tool_batch_member")
    op.execute("DROP TABLE entity_research_budget_reservation")
    op.execute("DROP TABLE entity_research_tool_batch")
