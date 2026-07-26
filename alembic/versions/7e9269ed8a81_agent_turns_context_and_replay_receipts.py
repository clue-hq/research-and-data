"""agent turns context and replay receipts

Revision ID: 7e9269ed8a81
Revises: ed7a01cd8845
Create Date: 2026-07-26 06:58:45.943084+00:00

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
revision: str = "7e9269ed8a81"
down_revision: str | None = "ed7a01cd8845"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # C6 receipts deliberately contain identities, hashes, counters and stable reason codes
    # only. Message, prompt, model-output, card and memory bodies remain in their owning
    # artifact/resource/domain stores and are reached exclusively through the normalized refs.
    op.execute(
        """
        CREATE TABLE agent_turn (
            id                           uuid PRIMARY KEY,
            execution_id                 uuid NOT NULL,
            parent_execution_id          uuid,
            workspace_id                 text NOT NULL,
            project_id                   text NOT NULL,
            thread_id                    text NOT NULL,
            actor_id                     text NOT NULL,
            role                         text NOT NULL,
            workspace_root_id            text NOT NULL,
            profile_name                 text NOT NULL,
            profile_version              text NOT NULL,
            profile_sha256               text NOT NULL,
            resource_manifest_key        text NOT NULL,
            resource_manifest_artifact_sha256 text NOT NULL,
            resource_manifest_sha256     text NOT NULL,
            retention_class              text NOT NULL,
            requested_at                 timestamptz NOT NULL,
            created_at                   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_turn_execution_fk
                FOREIGN KEY (execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT agent_turn_parent_execution_fk
                FOREIGN KEY (parent_execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT agent_turn_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            CONSTRAINT agent_turn_resource_manifest_fk
                FOREIGN KEY (resource_manifest_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_turn_execution_unique UNIQUE (execution_id),
            CONSTRAINT agent_turn_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT agent_turn_thread_anchor UNIQUE (id, workspace_id, thread_id),
            CONSTRAINT agent_turn_execution_anchor UNIQUE (id, execution_id, workspace_id),
            CONSTRAINT agent_turn_role CHECK (
                role IN ('head_of_abm', 'research', 'content_drafter', 'reviewer',
                         'account_research')
            ),
            CONSTRAINT agent_turn_hashes CHECK (
                profile_sha256 ~ '^[0-9a-f]{64}$'
                AND resource_manifest_artifact_sha256 ~ '^[0-9a-f]{64}$'
                AND resource_manifest_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT agent_turn_resource_scope CHECK (
                resource_manifest_key =
                    workspace_id || '/' || resource_manifest_artifact_sha256
            ),
            CONSTRAINT agent_turn_identity_nonempty CHECK (
                length(btrim(thread_id)) > 0
                AND length(btrim(actor_id)) > 0
                AND length(btrim(workspace_root_id)) > 0
                AND length(btrim(profile_name)) > 0
                AND length(btrim(profile_version)) > 0
                AND length(btrim(retention_class)) > 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_turn_thread_requested "
        "ON agent_turn (workspace_id, thread_id, requested_at, id)"
    )

    op.execute(
        """
        CREATE TABLE agent_turn_event (
            seq         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id    uuid NOT NULL UNIQUE,
            turn_id     uuid NOT NULL,
            workspace_id text NOT NULL,
            status      text NOT NULL,
            reason_code text,
            created_at  timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_turn_event_turn_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn (id, workspace_id),
            CONSTRAINT agent_turn_event_status CHECK (
                status IN ('requested', 'context_ready', 'running', 'awaiting_input',
                           'completed', 'failed', 'abandoned', 'privacy_tombstoned')
            ),
            CONSTRAINT agent_turn_event_reason_nonempty CHECK (
                reason_code IS NULL OR length(btrim(reason_code)) > 0
            )
        )
        """
    )
    op.execute("CREATE INDEX agent_turn_event_effective ON agent_turn_event (turn_id, seq DESC)")

    op.execute(
        """
        CREATE TABLE agent_artifact_ref (
            id             uuid PRIMARY KEY,
            turn_id        uuid NOT NULL,
            workspace_id   text NOT NULL,
            owner_kind     text NOT NULL,
            owner_id       uuid NOT NULL,
            ref_role       text NOT NULL,
            ordinal        int NOT NULL,
            artifact_key   text NOT NULL,
            artifact_sha256 text NOT NULL,
            retention_class text NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_artifact_ref_turn_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn (id, workspace_id),
            CONSTRAINT agent_artifact_ref_artifact_fk
                FOREIGN KEY (artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_artifact_ref_owner CHECK (
                owner_kind IN ('turn', 'context', 'history', 'model_call', 'finalization',
                               'workspace_output')
            ),
            CONSTRAINT agent_artifact_ref_role CHECK (
                ref_role IN ('stage_snapshot', 'readiness_snapshot', 'budget_envelope',
                             'resource_manifest', 'user_message', 'attachment',
                             'context_materialization', 'history_body', 'model_input',
                             'model_output', 'final_message', 'output', 'assumption',
                             'next_action', 'workspace_output')
            ),
            CONSTRAINT agent_artifact_ref_ordinal CHECK (ordinal >= 0),
            CONSTRAINT agent_artifact_ref_sha CHECK (
                artifact_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT agent_artifact_ref_scope CHECK (
                artifact_key = workspace_id || '/' || artifact_sha256
            ),
            CONSTRAINT agent_artifact_ref_identity UNIQUE (
                owner_kind, owner_id, ref_role, ordinal
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_artifact_ref_turn_role "
        "ON agent_artifact_ref (turn_id, ref_role, ordinal)"
    )
    op.execute("CREATE INDEX agent_artifact_ref_artifact ON agent_artifact_ref (artifact_key)")

    # Explicit subject bindings make DSAR reachability deterministic without inspecting bodies.
    # One artifact may carry multiple subjects, so this is not folded into agent_artifact_ref.
    op.execute(
        """
        CREATE TABLE agent_artifact_subject (
            workspace_id      text NOT NULL,
            artifact_key      text NOT NULL,
            subject_entity_id uuid NOT NULL,
            binding_kind      text NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_artifact_subject_pk PRIMARY KEY (
                workspace_id, artifact_key, subject_entity_id
            ),
            CONSTRAINT agent_artifact_subject_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT agent_artifact_subject_artifact_fk
                FOREIGN KEY (artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_artifact_subject_kind CHECK (
                binding_kind IN ('direct', 'derived', 'attachment', 'conversation',
                                 'context', 'output')
            ),
            CONSTRAINT agent_artifact_subject_scope CHECK (
                split_part(artifact_key, '/', 1) = workspace_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_artifact_subject_lookup "
        "ON agent_artifact_subject (workspace_id, subject_entity_id, artifact_key)"
    )

    # The tombstone outlives physical deletion and prevents a content-addressed personal
    # artifact from being silently resurrected by a retry.
    op.execute(
        """
        CREATE TABLE agent_artifact_tombstone (
            workspace_id      text NOT NULL,
            artifact_key      text NOT NULL,
            subject_entity_id uuid NOT NULL,
            reason_code       text NOT NULL,
            erased_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_artifact_tombstone_pk PRIMARY KEY (
                workspace_id, artifact_key, subject_entity_id
            ),
            CONSTRAINT agent_artifact_tombstone_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT agent_artifact_tombstone_artifact_fk
                FOREIGN KEY (artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_artifact_tombstone_scope CHECK (
                split_part(artifact_key, '/', 1) = workspace_id
            ),
            CONSTRAINT agent_artifact_tombstone_reason CHECK (
                length(btrim(reason_code)) > 0
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE agent_context_bundle (
            id                    uuid PRIMARY KEY,
            turn_id               uuid NOT NULL,
            execution_id          uuid NOT NULL,
            workspace_id          text NOT NULL,
            schema_version        text NOT NULL,
            policy_version        text NOT NULL,
            token_counter_version text NOT NULL,
            aggregate_sha256      text NOT NULL,
            assembled_at          timestamptz NOT NULL,
            created_at            timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_context_bundle_turn_fk
                FOREIGN KEY (turn_id, execution_id, workspace_id)
                REFERENCES agent_turn (id, execution_id, workspace_id),
            CONSTRAINT agent_context_bundle_execution_fk
                FOREIGN KEY (execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT agent_context_bundle_one_per_turn UNIQUE (turn_id),
            CONSTRAINT agent_context_bundle_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT agent_context_bundle_schema CHECK (schema_version = '1'),
            CONSTRAINT agent_context_bundle_sha CHECK (
                aggregate_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT agent_context_bundle_versions_nonempty CHECK (
                length(btrim(policy_version)) > 0
                AND length(btrim(token_counter_version)) > 0
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE agent_context_layer (
            context_bundle_id uuid NOT NULL,
            workspace_id      text NOT NULL,
            ordinal           int NOT NULL,
            layer             text NOT NULL,
            token_budget      int NOT NULL,
            token_count       int NOT NULL,
            included_count    int NOT NULL,
            excluded_count    int NOT NULL,

            CONSTRAINT agent_context_layer_pk PRIMARY KEY (context_bundle_id, ordinal),
            CONSTRAINT agent_context_layer_workspace_anchor UNIQUE (
                context_bundle_id, ordinal, workspace_id
            ),
            CONSTRAINT agent_context_layer_bundle_fk
                FOREIGN KEY (context_bundle_id, workspace_id)
                REFERENCES agent_context_bundle (id, workspace_id),
            CONSTRAINT agent_context_layer_ordinal CHECK (ordinal BETWEEN 1 AND 7),
            CONSTRAINT agent_context_layer_name CHECK (
                layer IN ('l1_identity', 'l2_workspace_product', 'l3_project', 'l4_memory',
                          'l5_focus', 'l6_conversation', 'l7_turn')
            ),
            CONSTRAINT agent_context_layer_order CHECK (
                (ordinal = 1 AND layer = 'l1_identity')
                OR (ordinal = 2 AND layer = 'l2_workspace_product')
                OR (ordinal = 3 AND layer = 'l3_project')
                OR (ordinal = 4 AND layer = 'l4_memory')
                OR (ordinal = 5 AND layer = 'l5_focus')
                OR (ordinal = 6 AND layer = 'l6_conversation')
                OR (ordinal = 7 AND layer = 'l7_turn')
            ),
            CONSTRAINT agent_context_layer_counts CHECK (
                token_budget >= 0 AND token_count >= 0 AND token_count <= token_budget
                AND included_count >= 0 AND excluded_count >= 0
            )
        )
        """
    )

    # One row per included or excluded pointer. content_sha256/materialized_path describe the
    # ephemeral compiled item, never its body. Exactly one artifact/domain ref shape is allowed.
    op.execute(
        """
        CREATE TABLE agent_context_ref (
            id                    uuid PRIMARY KEY,
            context_bundle_id     uuid NOT NULL,
            workspace_id          text NOT NULL,
            layer_ordinal         int NOT NULL,
            disposition           text NOT NULL,
            ordinal               int NOT NULL,
            ref_kind              text NOT NULL,
            artifact_key          text,
            artifact_sha256       text,
            object_type           text,
            object_id             text,
            object_version        bigint,
            content_sha256        text,
            materialized_path     text,
            token_count           int,
            exclusion_reason_code text,

            CONSTRAINT agent_context_ref_layer_fk
                FOREIGN KEY (context_bundle_id, layer_ordinal, workspace_id)
                REFERENCES agent_context_layer (
                    context_bundle_id, ordinal, workspace_id
                ),
            CONSTRAINT agent_context_ref_artifact_fk
                FOREIGN KEY (artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_context_ref_identity UNIQUE (
                context_bundle_id, layer_ordinal, disposition, ordinal
            ),
            CONSTRAINT agent_context_ref_disposition CHECK (
                disposition IN ('included', 'excluded')
            ),
            CONSTRAINT agent_context_ref_kind CHECK (ref_kind IN ('artifact', 'domain')),
            CONSTRAINT agent_context_ref_ordinal CHECK (ordinal >= 0),
            CONSTRAINT agent_context_ref_shape CHECK (
                (ref_kind = 'artifact'
                 AND artifact_key IS NOT NULL AND artifact_sha256 IS NOT NULL
                 AND object_type IS NULL AND object_id IS NULL AND object_version IS NULL)
                OR
                (ref_kind = 'domain'
                 AND artifact_key IS NULL AND artifact_sha256 IS NULL
                 AND object_type IS NOT NULL AND object_id IS NOT NULL
                 AND (object_version IS NULL OR object_version >= 1))
            ),
            CONSTRAINT agent_context_ref_inclusion_shape CHECK (
                (disposition = 'included'
                 AND content_sha256 IS NOT NULL AND token_count IS NOT NULL
                 AND token_count >= 0 AND exclusion_reason_code IS NULL)
                OR
                (disposition = 'excluded'
                 AND content_sha256 IS NULL AND materialized_path IS NULL
                 AND token_count IS NULL AND exclusion_reason_code IS NOT NULL)
            ),
            CONSTRAINT agent_context_ref_hashes CHECK (
                (artifact_sha256 IS NULL OR artifact_sha256 ~ '^[0-9a-f]{64}$')
                AND (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$')
            ),
            CONSTRAINT agent_context_ref_artifact_scope CHECK (
                artifact_key IS NULL
                OR artifact_key = workspace_id || '/' || artifact_sha256
            ),
            CONSTRAINT agent_context_ref_domain_nonempty CHECK (
                object_type IS NULL OR (
                    length(btrim(object_type)) > 0 AND length(btrim(object_id)) > 0
                )
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE agent_thread_message (
            id              uuid PRIMARY KEY,
            workspace_id    text NOT NULL,
            thread_id       text NOT NULL,
            turn_id         uuid NOT NULL,
            sequence        bigint NOT NULL,
            role            text NOT NULL,
            body_artifact_key text NOT NULL,
            body_sha256     text NOT NULL,
            retention_class text NOT NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_thread_message_turn_fk
                FOREIGN KEY (turn_id, workspace_id, thread_id)
                REFERENCES agent_turn (id, workspace_id, thread_id),
            CONSTRAINT agent_thread_message_artifact_fk
                FOREIGN KEY (body_artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_thread_message_sequence UNIQUE (
                workspace_id, thread_id, sequence
            ),
            CONSTRAINT agent_thread_message_role CHECK (
                role IN ('system', 'user', 'assistant', 'tool')
            ),
            CONSTRAINT agent_thread_message_sequence_positive CHECK (sequence >= 1),
            CONSTRAINT agent_thread_message_sha CHECK (
                body_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT agent_thread_message_scope CHECK (
                body_artifact_key = workspace_id || '/' || body_sha256
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE agent_model_call (
            id                 uuid PRIMARY KEY,
            turn_id            uuid NOT NULL,
            execution_id       uuid NOT NULL,
            workspace_id       text NOT NULL,
            sequence           int NOT NULL,
            requested_model    text NOT NULL,
            answering_model    text,
            status             text NOT NULL,
            input_tokens       int NOT NULL DEFAULT 0,
            output_tokens      int NOT NULL DEFAULT 0,
            cost_millicredits  bigint NOT NULL DEFAULT 0,
            latency_ms         double precision NOT NULL DEFAULT 0,
            error_code         text,
            started_at         timestamptz NOT NULL,
            completed_at       timestamptz,

            CONSTRAINT agent_model_call_turn_fk
                FOREIGN KEY (turn_id, execution_id, workspace_id)
                REFERENCES agent_turn (id, execution_id, workspace_id),
            CONSTRAINT agent_model_call_execution_fk
                FOREIGN KEY (execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT agent_model_call_sequence UNIQUE (turn_id, sequence),
            CONSTRAINT agent_model_call_status CHECK (
                status IN ('completed', 'failed', 'cancelled')
            ),
            CONSTRAINT agent_model_call_counts CHECK (
                sequence >= 1 AND input_tokens >= 0 AND output_tokens >= 0
                AND cost_millicredits >= 0 AND latency_ms >= 0
            ),
            CONSTRAINT agent_model_call_shape CHECK (
                (status = 'completed' AND answering_model IS NOT NULL
                 AND completed_at IS NOT NULL AND error_code IS NULL)
                OR
                (status = 'failed' AND completed_at IS NOT NULL AND error_code IS NOT NULL)
                OR
                (status = 'cancelled' AND completed_at IS NOT NULL)
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE agent_finalization (
            id            uuid PRIMARY KEY,
            turn_id       uuid NOT NULL,
            execution_id  uuid NOT NULL,
            workspace_id  text NOT NULL,
            status        text NOT NULL,
            failure_code  text,
            finalized_at  timestamptz NOT NULL,

            CONSTRAINT agent_finalization_turn_fk
                FOREIGN KEY (turn_id, execution_id, workspace_id)
                REFERENCES agent_turn (id, execution_id, workspace_id),
            CONSTRAINT agent_finalization_execution_fk
                FOREIGN KEY (execution_id, workspace_id)
                REFERENCES execution (id, workspace_id),
            CONSTRAINT agent_finalization_one_per_turn UNIQUE (turn_id),
            CONSTRAINT agent_finalization_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT agent_finalization_status CHECK (
                status IN ('completed', 'awaiting_input', 'blocked', 'failed')
            ),
            CONSTRAINT agent_finalization_failure_shape CHECK (
                (status = 'failed' AND failure_code IS NOT NULL)
                OR (status <> 'failed' AND failure_code IS NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE agent_finalization_domain_ref (
            finalization_id uuid NOT NULL,
            workspace_id    text NOT NULL,
            ref_role        text NOT NULL,
            ordinal         int NOT NULL,
            object_type     text NOT NULL,
            object_id       text NOT NULL,
            object_version  bigint,

            CONSTRAINT agent_finalization_domain_ref_pk PRIMARY KEY (
                finalization_id, ref_role, ordinal
            ),
            CONSTRAINT agent_finalization_domain_ref_finalization_fk
                FOREIGN KEY (finalization_id, workspace_id)
                REFERENCES agent_finalization (id, workspace_id),
            CONSTRAINT agent_finalization_domain_ref_role CHECK (
                ref_role IN ('output', 'open_gate')
            ),
            CONSTRAINT agent_finalization_domain_ref_counts CHECK (
                ordinal >= 0 AND (object_version IS NULL OR object_version >= 1)
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE agent_privacy_event (
            seq               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id          uuid NOT NULL UNIQUE,
            workspace_id      text NOT NULL,
            subject_entity_id uuid NOT NULL,
            turn_id           uuid,
            artifact_key      text,
            action            text NOT NULL,
            reason_code       text NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_privacy_event_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT agent_privacy_event_turn_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn (id, workspace_id),
            CONSTRAINT agent_privacy_event_artifact_fk
                FOREIGN KEY (artifact_key) REFERENCES artifact (storage_key),
            CONSTRAINT agent_privacy_event_action CHECK (
                action IN ('artifact_tombstoned', 'workspace_purged')
            ),
            CONSTRAINT agent_privacy_event_artifact_scope CHECK (
                artifact_key IS NULL OR split_part(artifact_key, '/', 1) = workspace_id
            ),
            CONSTRAINT agent_privacy_event_reason CHECK (
                length(btrim(reason_code)) > 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_privacy_event_subject "
        "ON agent_privacy_event (workspace_id, subject_entity_id, seq)"
    )

    # All C6 durable facts are append-only. Erasure is expressed through artifact lifecycle
    # timestamps plus these tombstone/event rows, never by rewriting a historical receipt.
    for table in (
        "agent_turn",
        "agent_turn_event",
        "agent_artifact_ref",
        "agent_artifact_subject",
        "agent_artifact_tombstone",
        "agent_context_bundle",
        "agent_context_layer",
        "agent_context_ref",
        "agent_thread_message",
        "agent_model_call",
        "agent_finalization",
        "agent_finalization_domain_ref",
        "agent_privacy_event",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
        )


def downgrade() -> None:
    for table in (
        "agent_privacy_event",
        "agent_finalization_domain_ref",
        "agent_finalization",
        "agent_model_call",
        "agent_thread_message",
        "agent_context_ref",
        "agent_context_layer",
        "agent_context_bundle",
        "agent_artifact_tombstone",
        "agent_artifact_subject",
        "agent_artifact_ref",
        "agent_turn_event",
        "agent_turn",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table}")
