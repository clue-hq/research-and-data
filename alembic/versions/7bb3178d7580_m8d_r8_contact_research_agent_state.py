"""m8d r8 contact research agent state

Revision ID: 7bb3178d7580
Revises: 02e552db75da
Create Date: 2026-08-06 08:51:18.674264+00:00

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
revision: str = "7bb3178d7580"
down_revision: str | None = "02e552db75da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_research_contact_identity_lock (
            job_id              uuid PRIMARY KEY REFERENCES entity_research_job(job_id),
            research_run_id     uuid NOT NULL REFERENCES entity_research_run(research_run_id),
            workspace_id        text NOT NULL,
            contact_entity_id   uuid NOT NULL,
            parent_account_id   uuid NOT NULL,
            identity_json       jsonb NOT NULL,
            identity_sha256     text NOT NULL,
            created_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_contact_identity_object
                CHECK (jsonb_typeof(identity_json)='object'),
            CONSTRAINT entity_research_contact_identity_sha
                CHECK (identity_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_contact_identity_exact CHECK ((
                identity_json->>'job_id'=job_id::text AND
                identity_json->>'contact_id'=contact_entity_id::text AND
                identity_json->>'account_id'=parent_account_id::text AND
                identity_json->>'workspace_id'=workspace_id
            ) IS TRUE)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE entity_research_contact_facet_event (
            event_seq           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id            uuid NOT NULL UNIQUE,
            research_run_id     uuid NOT NULL REFERENCES entity_research_run(research_run_id),
            job_id              uuid NOT NULL REFERENCES entity_research_job(job_id),
            workspace_id        text NOT NULL,
            contact_entity_id   uuid NOT NULL,
            facet_key           text NOT NULL,
            child_ordinal       integer NOT NULL,
            parent_turn_id      uuid NOT NULL,
            child_turn_id       uuid NOT NULL,
            state               text NOT NULL,
            result_refs         text[] NOT NULL DEFAULT '{}',
            claim_refs          text[] NOT NULL DEFAULT '{}',
            evidence_refs       text[] NOT NULL DEFAULT '{}',
            wait_ref            text,
            payload_json        jsonb NOT NULL,
            payload_sha256      text NOT NULL,
            created_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_contact_facet_ordinal CHECK (child_ordinal BETWEEN 1 AND 2),
            CONSTRAINT entity_research_contact_facet_state
                CHECK (state IN ('started', 'waiting_external', 'completed')),
            CONSTRAINT entity_research_contact_facet_wait CHECK (
                (state='waiting_external')=(wait_ref IS NOT NULL)),
            CONSTRAINT entity_research_contact_facet_object
                CHECK (jsonb_typeof(payload_json)='object'),
            CONSTRAINT entity_research_contact_facet_sha
                CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_contact_facet_child UNIQUE (job_id, child_turn_id, state)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_contact_facet_latest ON "
        "entity_research_contact_facet_event (job_id, facet_key, event_seq DESC)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_contact_channel_causation (
            causation_id         uuid PRIMARY KEY,
            research_run_id      uuid NOT NULL REFERENCES entity_research_run(research_run_id),
            job_id               uuid NOT NULL REFERENCES entity_research_job(job_id),
            workspace_id         text NOT NULL,
            contact_entity_id    uuid NOT NULL,
            parent_account_id    uuid NOT NULL,
            agent_turn_id        uuid NOT NULL,
            agent_execution_id   uuid NOT NULL,
            tool_event_id        uuid NOT NULL REFERENCES entity_research_agent_event(event_id),
            tool_call_id         text NOT NULL,
            tool_input_sha256    text NOT NULL,
            channel_operation_id uuid NOT NULL REFERENCES contact_channel_operation(id),
            channel              contact_channel_kind NOT NULL,
            stage                text NOT NULL,
            disposition          text NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_contact_channel_stage
                CHECK (stage IN ('acquisition', 'validation')),
            CONSTRAINT entity_research_contact_channel_disposition
                CHECK (disposition IN ('caused', 'joined', 'replayed')),
            CONSTRAINT entity_research_contact_channel_input_sha
                CHECK (tool_input_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_contact_channel_call_once
                UNIQUE (agent_turn_id, tool_call_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_contact_channel_job ON "
        "entity_research_contact_channel_causation (job_id, channel, created_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX entity_research_contact_channel_dispatch_once ON "
        "entity_research_contact_channel_causation (job_id, channel_operation_id, stage) "
        "WHERE disposition='caused'"
    )
    op.execute(
        """
        CREATE TABLE entity_research_contact_channel_cost_fold (
            channel_operation_id uuid NOT NULL REFERENCES contact_channel_operation(id),
            stage                text NOT NULL,
            research_run_id      uuid NOT NULL REFERENCES entity_research_run(research_run_id),
            job_id               uuid NOT NULL REFERENCES entity_research_job(job_id),
            cost_cents           numeric(18, 6) NOT NULL,
            folded_at            timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (channel_operation_id, stage),
            CONSTRAINT entity_research_contact_channel_fold_stage
                CHECK (stage IN ('acquisition', 'validation')),
            CONSTRAINT entity_research_contact_channel_fold_cost CHECK (cost_cents >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE entity_research_contact_coverage (
            coverage_id              uuid PRIMARY KEY,
            research_run_id          uuid NOT NULL REFERENCES entity_research_run(research_run_id),
            job_id                   uuid NOT NULL REFERENCES entity_research_job(job_id),
            workspace_id             text NOT NULL,
            contact_entity_id        uuid NOT NULL,
            parent_account_id        uuid NOT NULL,
            identity_lock_ref        text NOT NULL,
            result_refs              text[] NOT NULL,
            facet_refs               text[] NOT NULL,
            channel_operation_refs   text[] NOT NULL,
            completed_field_keys     text[] NOT NULL,
            unresolved_field_keys    text[] NOT NULL,
            unresolved_reasons       text[] NOT NULL,
            review_flags             text[] NOT NULL,
            claim_refs               text[] NOT NULL,
            evidence_refs            text[] NOT NULL,
            coverage_json            jsonb NOT NULL,
            coverage_sha256          text NOT NULL,
            created_at               timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_contact_coverage_identity_nonempty
                CHECK (length(btrim(identity_lock_ref)) > 0),
            CONSTRAINT entity_research_contact_coverage_object
                CHECK (jsonb_typeof(coverage_json)='object'),
            CONSTRAINT entity_research_contact_coverage_sha
                CHECK (coverage_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_contact_coverage_job ON "
        "entity_research_contact_coverage (job_id, created_at DESC, coverage_id DESC)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_contact_review_item (
            review_item_id       uuid PRIMARY KEY,
            coverage_id          uuid NOT NULL REFERENCES
                                 entity_research_contact_coverage(coverage_id),
            research_run_id      uuid NOT NULL REFERENCES entity_research_run(research_run_id),
            job_id               uuid NOT NULL REFERENCES entity_research_job(job_id),
            workspace_id         text NOT NULL,
            contact_entity_id    uuid NOT NULL,
            reason_code          text NOT NULL,
            details_json         jsonb NOT NULL,
            state                text NOT NULL DEFAULT 'open',
            created_at           timestamptz NOT NULL DEFAULT now(),
            resolved_at          timestamptz,
            resolved_by          text,
            resolution_ref       text,
            CONSTRAINT entity_research_contact_review_reason
                CHECK (length(btrim(reason_code)) > 0),
            CONSTRAINT entity_research_contact_review_object
                CHECK (jsonb_typeof(details_json)='object'),
            CONSTRAINT entity_research_contact_review_state CHECK (state IN ('open', 'resolved')),
            CONSTRAINT entity_research_contact_review_resolution CHECK (
                (state='open' AND resolved_at IS NULL AND resolved_by IS NULL
                    AND resolution_ref IS NULL) OR
                (state='resolved' AND resolved_at IS NOT NULL AND
                    length(btrim(resolved_by)) > 0 AND length(btrim(resolution_ref)) > 0)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_contact_review_queue ON "
        "entity_research_contact_review_item (workspace_id, state, created_at)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_contact_finalization_intent (
            proposal_id          uuid PRIMARY KEY,
            coverage_id          uuid NOT NULL REFERENCES
                                 entity_research_contact_coverage(coverage_id),
            research_run_id      uuid NOT NULL REFERENCES entity_research_run(research_run_id),
            job_id               uuid NOT NULL REFERENCES entity_research_job(job_id),
            workspace_id         text NOT NULL,
            contact_entity_id    uuid NOT NULL,
            current_state_sha256 text NOT NULL,
            proposal_json        jsonb NOT NULL,
            proposal_sha256      text NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_contact_finalization_state_sha
                CHECK (current_state_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_contact_finalization_object
                CHECK (jsonb_typeof(proposal_json)='object'),
            CONSTRAINT entity_research_contact_finalization_sha
                CHECK (proposal_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_contact_finalization_exact CHECK ((
                proposal_json->>'proposal_id'=proposal_id::text AND
                proposal_json->>'target_entity_id'=contact_entity_id::text AND
                proposal_json->>'subject_type'='contact'
            ) IS TRUE)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_contact_finalization_job ON "
        "entity_research_contact_finalization_intent (job_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_contact_fleet_return (
            return_seq       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            return_id        uuid NOT NULL UNIQUE,
            research_run_id  uuid NOT NULL REFERENCES
                             entity_research_contact_launch(research_run_id),
            workspace_id     text NOT NULL,
            return_kind      text NOT NULL,
            payload_json     jsonb NOT NULL,
            payload_sha256   text NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_contact_return_kind
                CHECK (return_kind IN ('waiting_external', 'terminal')),
            CONSTRAINT entity_research_contact_return_object
                CHECK (jsonb_typeof(payload_json)='object'),
            CONSTRAINT entity_research_contact_return_sha
                CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_contact_return_once UNIQUE (research_run_id, payload_sha256)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_contact_return_latest ON "
        "entity_research_contact_fleet_return (research_run_id, return_seq DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION validate_entity_research_contact_agent_scope()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            job_row entity_research_job%ROWTYPE;
            operation_row contact_channel_operation%ROWTYPE;
        BEGIN
            SELECT * INTO job_row FROM entity_research_job WHERE job_id=NEW.job_id;
            IF NOT FOUND OR job_row.research_run_id<>NEW.research_run_id OR
               job_row.workspace_id<>NEW.workspace_id OR job_row.subject_type<>'contact' OR
               job_row.subject_entity_id<>NEW.contact_entity_id THEN
                RAISE EXCEPTION 'contact-agent row crosses exact job scope';
            END IF;
            IF TG_TABLE_NAME='entity_research_contact_identity_lock' THEN
                IF job_row.parent_account_id<>NEW.parent_account_id THEN
                    RAISE EXCEPTION 'contact identity lock crosses parent account';
                END IF;
            ELSIF TG_TABLE_NAME='entity_research_contact_facet_event' THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(
                        job_row.authorization_json->'selection'->'subjects'
                    ) selected
                    WHERE selected->>'subject_entity_id'=NEW.contact_entity_id::text
                      AND (selected->'contact_authority'->'facet_keys') ? NEW.facet_key
                ) THEN
                    RAISE EXCEPTION 'facet event is outside exact selected facet authority';
                END IF;
                IF NEW.state='started' AND EXISTS (
                    SELECT 1 FROM entity_research_contact_facet_event prior
                    WHERE prior.job_id=NEW.job_id AND prior.state='started'
                      AND prior.facet_key<>NEW.facet_key
                    GROUP BY prior.job_id HAVING count(DISTINCT prior.facet_key)>=2
                ) THEN
                    RAISE EXCEPTION 'contact facet event exceeds the two-child cap';
                END IF;
            ELSIF TG_TABLE_NAME='entity_research_contact_channel_causation' THEN
                SELECT * INTO operation_row FROM contact_channel_operation
                WHERE id=NEW.channel_operation_id;
                IF NOT FOUND OR operation_row.workspace_id<>NEW.workspace_id OR
                   operation_row.contact_id<>NEW.contact_entity_id OR
                   operation_row.account_id<>NEW.parent_account_id OR
                   operation_row.channel<>NEW.channel THEN
                    RAISE EXCEPTION 'channel causation crosses exact contact/channel';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM entity_research_agent_event event
                    WHERE event.event_id=NEW.tool_event_id
                      AND event.agent_turn_id=NEW.agent_turn_id
                      AND event.agent_execution_id=NEW.agent_execution_id
                      AND event.tool_call_id=NEW.tool_call_id
                      AND event.tool_input_sha256=NEW.tool_input_sha256
                      AND event.event_kind='tool_started'
                      AND event.tool_name=(CASE WHEN NEW.stage='acquisition'
                          THEN 'reveal_contact_channel' ELSE 'validate_contact_channel' END)
                ) THEN
                    RAISE EXCEPTION 'channel causation lacks the exact preceding tool event';
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(
                        job_row.authorization_json->'selection'->'subjects'
                    ) selected,
                    jsonb_array_elements_text(
                        selected->'contact_authority'->'channel_permissions'
                    ) permission
                    WHERE selected->>'subject_entity_id'=NEW.contact_entity_id::text
                      AND permission=NEW.channel::text
                ) THEN
                    RAISE EXCEPTION 'channel causation exceeds exact selected permission';
                END IF;
                IF NEW.stage='validation' AND NOT EXISTS (
                    SELECT 1 FROM entity_research_contact_channel_causation acquisition
                    WHERE acquisition.job_id=NEW.job_id
                      AND acquisition.channel_operation_id=NEW.channel_operation_id
                      AND acquisition.stage='acquisition'
                ) THEN
                    RAISE EXCEPTION 'channel validation has no preceding acquisition decision';
                END IF;
            ELSIF TG_TABLE_NAME='entity_research_contact_coverage' THEN
                IF job_row.parent_account_id<>NEW.parent_account_id OR EXISTS (
                    SELECT 1 FROM unnest(
                        NEW.completed_field_keys || NEW.unresolved_field_keys
                    ) key WHERE key NOT LIKE 'contact.%'
                ) THEN
                    RAISE EXCEPTION 'contact coverage crosses account or field axis';
                END IF;
            ELSIF TG_TABLE_NAME='entity_research_contact_finalization_intent' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM entity_research_contact_coverage coverage
                    WHERE coverage.coverage_id=NEW.coverage_id
                      AND coverage.job_id=NEW.job_id
                      AND coverage.research_run_id=NEW.research_run_id
                      AND coverage.workspace_id=NEW.workspace_id
                      AND coverage.contact_entity_id=NEW.contact_entity_id
                ) THEN
                    RAISE EXCEPTION 'contact finalization crosses exact coverage';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    for table in (
        "entity_research_contact_identity_lock",
        "entity_research_contact_facet_event",
        "entity_research_contact_channel_causation",
        "entity_research_contact_coverage",
        "entity_research_contact_finalization_intent",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_scope BEFORE INSERT ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION validate_entity_research_contact_agent_scope()"
        )
    op.execute(
        """
        CREATE FUNCTION validate_entity_research_contact_channel_fold()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM entity_research_contact_channel_causation link
                JOIN entity_research_job job ON job.job_id=link.job_id
                WHERE link.channel_operation_id=NEW.channel_operation_id
                  AND link.stage=NEW.stage
                  AND link.job_id=NEW.job_id
                  AND link.research_run_id=NEW.research_run_id
                  AND job.research_run_id=NEW.research_run_id
            ) THEN
                RAISE EXCEPTION 'contact channel fold crosses exact causation/job';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_contact_channel_cost_fold_scope BEFORE INSERT ON "
        "entity_research_contact_channel_cost_fold FOR EACH ROW EXECUTE FUNCTION "
        "validate_entity_research_contact_channel_fold()"
    )
    op.execute(
        """
        CREATE FUNCTION validate_entity_research_contact_return()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM entity_research_contact_launch launch
                JOIN entity_research_run run USING (research_run_id)
                WHERE launch.research_run_id=NEW.research_run_id
                  AND launch.workspace_id=NEW.workspace_id
                  AND run.run_kind='contact_research'
                  AND run.subject_type='contact'
            ) THEN
                RAISE EXCEPTION 'contact fleet return crosses exact run scope';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_contact_fleet_return_scope BEFORE INSERT ON "
        "entity_research_contact_fleet_return FOR EACH ROW EXECUTE FUNCTION "
        "validate_entity_research_contact_return()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_entity_research_contact_agent_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'contact agent history is append-only';
        END
        $$
        """
    )
    for table in (
        "entity_research_contact_identity_lock",
        "entity_research_contact_facet_event",
        "entity_research_contact_channel_causation",
        "entity_research_contact_channel_cost_fold",
        "entity_research_contact_coverage",
        "entity_research_contact_finalization_intent",
        "entity_research_contact_fleet_return",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_entity_research_contact_agent_history_mutation()"
        )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS entity_research_contact_fleet_return_scope ON "
        "entity_research_contact_fleet_return"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_entity_research_contact_return()")
    op.execute(
        "DROP TRIGGER IF EXISTS entity_research_contact_channel_cost_fold_scope ON "
        "entity_research_contact_channel_cost_fold"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_entity_research_contact_channel_fold()")
    for table in (
        "entity_research_contact_identity_lock",
        "entity_research_contact_facet_event",
        "entity_research_contact_channel_causation",
        "entity_research_contact_channel_cost_fold",
        "entity_research_contact_coverage",
        "entity_research_contact_finalization_intent",
        "entity_research_contact_fleet_return",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_entity_research_contact_agent_history_mutation()")
    for table in (
        "entity_research_contact_identity_lock",
        "entity_research_contact_facet_event",
        "entity_research_contact_channel_causation",
        "entity_research_contact_coverage",
        "entity_research_contact_finalization_intent",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_scope ON {table}")
    op.execute("DROP FUNCTION IF EXISTS validate_entity_research_contact_agent_scope()")
    op.execute("DROP TABLE IF EXISTS entity_research_contact_fleet_return")
    op.execute("DROP TABLE IF EXISTS entity_research_contact_finalization_intent")
    op.execute("DROP TABLE IF EXISTS entity_research_contact_review_item")
    op.execute("DROP TABLE IF EXISTS entity_research_contact_coverage")
    op.execute("DROP TABLE IF EXISTS entity_research_contact_channel_cost_fold")
    op.execute("DROP TABLE IF EXISTS entity_research_contact_channel_causation")
    op.execute("DROP TABLE IF EXISTS entity_research_contact_facet_event")
    op.execute("DROP TABLE IF EXISTS entity_research_contact_identity_lock")
