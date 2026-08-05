"""m8d r3 entity research agent journal

Revision ID: ac980e12eb5e
Revises: 022b1154b3aa
Create Date: 2026-08-05 21:41:25.255130+00:00

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
revision: str = "ac980e12eb5e"
down_revision: str | None = "022b1154b3aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_research_agent_turn (
            agent_turn_id                  uuid PRIMARY KEY,
            agent_execution_id             uuid NOT NULL,
            job_id                         uuid NOT NULL REFERENCES entity_research_job
                                               (job_id) ON DELETE RESTRICT,
            research_run_id                uuid NOT NULL REFERENCES entity_research_run
                                               (research_run_id) ON DELETE RESTRICT,
            role                           text NOT NULL,
            subject_type                   text NOT NULL,
            target_entity_id               uuid NOT NULL,
            parent_account_id               uuid,
            workspace_id                   text NOT NULL,
            project_id                     text NOT NULL,
            product_id                     text NOT NULL,
            project_run_id                 uuid NOT NULL,
            checkpoint_thread_id            text NOT NULL,
            parent_agent_execution_id       uuid,
            parent_agent_turn_id            uuid REFERENCES entity_research_agent_turn
                                               (agent_turn_id) ON DELETE RESTRICT,
            facet_key                       text,
            facet_depth                     integer,
            context_json                    jsonb NOT NULL,
            context_sha256                  text NOT NULL,
            resource_manifest_json          jsonb NOT NULL,
            resource_manifest_sha256        text NOT NULL,
            tool_manifest_json              jsonb NOT NULL,
            tool_manifest_sha256            text NOT NULL,
            system_prompt_sha256            text NOT NULL,
            started_at                      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT entity_research_agent_turn_role
                CHECK (role IN ('account', 'contact', 'facet')),
            CONSTRAINT entity_research_agent_turn_subject
                CHECK (subject_type IN ('account', 'contact')),
            CONSTRAINT entity_research_agent_turn_parent_shape CHECK (
                (subject_type = 'account' AND parent_account_id IS NULL) OR
                (subject_type = 'contact' AND parent_account_id IS NOT NULL)
            ),
            CONSTRAINT entity_research_agent_turn_facet_shape CHECK (
                (
                    role = 'facet' AND parent_agent_execution_id IS NOT NULL
                    AND parent_agent_turn_id IS NOT NULL AND facet_key IS NOT NULL
                    AND facet_depth = 1
                ) OR (
                    role <> 'facet' AND parent_agent_execution_id IS NULL
                    AND parent_agent_turn_id IS NULL AND facet_key IS NULL
                    AND facet_depth IS NULL
                )
            ),
            CONSTRAINT entity_research_agent_turn_context_object
                CHECK (jsonb_typeof(context_json) = 'object'),
            CONSTRAINT entity_research_agent_turn_resource_object
                CHECK (jsonb_typeof(resource_manifest_json) = 'object'),
            CONSTRAINT entity_research_agent_turn_tools_array
                CHECK (jsonb_typeof(tool_manifest_json) = 'array'),
            CONSTRAINT entity_research_agent_turn_hashes CHECK (
                context_sha256 ~ '^[0-9a-f]{64}$' AND
                resource_manifest_sha256 ~ '^[0-9a-f]{64}$' AND
                tool_manifest_sha256 ~ '^[0-9a-f]{64}$' AND
                system_prompt_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT entity_research_agent_turn_context_scope CHECK ((
                context_json->>'agent_execution_id' = agent_execution_id::text AND
                context_json->>'agent_turn_id' = agent_turn_id::text AND
                context_json->>'role' = role AND
                context_json->>'subject_type' = subject_type AND
                context_json->>'subject_entity_id' = target_entity_id::text AND
                context_json->>'job_id' = job_id::text AND
                context_json->>'research_run_id' = research_run_id::text AND
                context_json->>'workspace_id' = workspace_id::text AND
                context_json->>'project_id' = project_id::text AND
                context_json->>'product_id' = product_id::text AND
                context_json->>'project_run_id' = project_run_id::text AND
                context_json->>'checkpoint_thread_id' = checkpoint_thread_id
            ) IS TRUE),
            CONSTRAINT entity_research_agent_turn_identity_pair
                UNIQUE (agent_turn_id, agent_execution_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_agent_turn_job_history "
        "ON entity_research_agent_turn (job_id, started_at, agent_turn_id)"
    )
    op.execute(
        "CREATE INDEX entity_research_agent_turn_execution_history "
        "ON entity_research_agent_turn (agent_execution_id, started_at, agent_turn_id)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_agent_event (
            event_id                 uuid PRIMARY KEY,
            event_seq                bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
            agent_turn_id            uuid NOT NULL,
            agent_execution_id       uuid NOT NULL,
            event_kind               text NOT NULL,
            tool_call_id             text,
            tool_name                text,
            tool_version             integer,
            tool_input_sha256        text,
            payload_json             jsonb NOT NULL,
            occurred_at              timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT entity_research_agent_event_turn_fk
                FOREIGN KEY (agent_turn_id, agent_execution_id)
                REFERENCES entity_research_agent_turn (agent_turn_id, agent_execution_id)
                ON DELETE RESTRICT,
            CONSTRAINT entity_research_agent_event_kind CHECK (
                event_kind IN (
                    'execution_started', 'model_started', 'model_completed',
                    'tool_started', 'tool_completed', 'tool_failed',
                    'finalization_proposed', 'finalization_accepted', 'facet_completed',
                    'execution_suspended', 'execution_failed', 'execution_cancelled'
                )
            ),
            CONSTRAINT entity_research_agent_event_payload_object
                CHECK (jsonb_typeof(payload_json) = 'object'),
            CONSTRAINT entity_research_agent_event_tool_shape CHECK (
                (
                    event_kind IN ('tool_started', 'tool_completed', 'tool_failed')
                    AND tool_call_id IS NOT NULL AND length(tool_call_id) > 0
                    AND tool_name IS NOT NULL AND length(tool_name) > 0
                    AND tool_version >= 1
                    AND tool_input_sha256 ~ '^[0-9a-f]{64}$'
                ) OR (
                    event_kind NOT IN ('tool_started', 'tool_completed', 'tool_failed')
                    AND tool_call_id IS NULL AND tool_name IS NULL
                    AND tool_version IS NULL AND tool_input_sha256 IS NULL
                )
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_agent_event_history "
        "ON entity_research_agent_event (agent_turn_id, event_seq)"
    )
    op.execute(
        "CREATE INDEX entity_research_agent_event_tool_causation "
        "ON entity_research_agent_event "
        "(agent_execution_id, tool_call_id, event_seq) WHERE tool_call_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE FUNCTION reject_entity_research_agent_journal_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'entity research agent journal is append-only';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_agent_turn_append_only "
        "BEFORE UPDATE OR DELETE ON entity_research_agent_turn FOR EACH ROW "
        "EXECUTE FUNCTION reject_entity_research_agent_journal_mutation()"
    )
    op.execute(
        "CREATE TRIGGER entity_research_agent_event_append_only "
        "BEFORE UPDATE OR DELETE ON entity_research_agent_event FOR EACH ROW "
        "EXECUTE FUNCTION reject_entity_research_agent_journal_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER entity_research_agent_event_append_only ON entity_research_agent_event"
    )
    op.execute("DROP TRIGGER entity_research_agent_turn_append_only ON entity_research_agent_turn")
    op.execute("DROP FUNCTION reject_entity_research_agent_journal_mutation")
    op.execute("DROP TABLE entity_research_agent_event")
    op.execute("DROP TABLE entity_research_agent_turn")
