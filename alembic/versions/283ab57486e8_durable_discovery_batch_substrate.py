"""durable discovery batch substrate

Revision ID: 283ab57486e8
Revises: 933c7b604f1c
Create Date: 2026-08-02 11:26:22.416854+00:00

M6A D1 adds the provider-neutral, workspace-structural execution records underneath asynchronous
account discovery.  Provider bodies stay in the existing content-addressed ``artifact`` store;
these tables hold lifecycle, replay identity, lineage, reconciliation, subject indexes, and the
immutable completion seal.  No provider SDK or provider-specific column appears here.

The downgrade is intentionally complete.  ``waiting_external`` is removed from the existing
checkpoint enum by rebuilding the enum after mapping any residual external wait to ``in_progress``
(the safe resumable predecessor state).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "283ab57486e8"
down_revision: str | None = "933c7b604f1c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, values: tuple[str, ...]) -> None:
    op.execute(f"CREATE TYPE {name} AS ENUM ({', '.join(repr(value) for value in values)})")


def upgrade() -> None:
    # External provider time is neither a human pause nor a completed phase.  Insert it after the
    # active state so Python/DB enum parity remains deterministic.
    op.execute(
        "ALTER TYPE phase_checkpoint_status ADD VALUE IF NOT EXISTS "
        "'waiting_external' AFTER 'in_progress'"
    )

    _enum(
        "discovery_batch_state",
        (
            "planned",
            "submitting",
            "provider_running",
            "ingesting_events_and_pages",
            "reconciling",
            "identity_resolution",
            "field_materialization",
            "seal_pending",
            "sealed",
            "waiting_external",
            "paused_by_user",
            "spend_outcome_unknown",
            "failed_retryable",
            "failed_terminal",
            "cancelled_unsealed",
        ),
    )
    _enum(
        "discovery_operation_state",
        (
            "planned",
            "submitting",
            "provider_running",
            "ingesting",
            "reconciling",
            "waiting_external",
            "succeeded",
            "accepted_terminal_failure",
            "paused_by_user",
            "spend_outcome_unknown",
            "failed_retryable",
            "failed_terminal",
            "cancelled",
        ),
    )
    _enum("discovery_spend_outcome", ("not_dispatched", "unknown", "not_charged", "charged"))
    _enum(
        "discovery_event_disposition",
        ("pending", "processed", "superseded", "duplicate", "late_after_seal"),
    )
    _enum(
        "discovery_page_resource",
        ("websets", "searches", "enrichments", "items", "events"),
    )
    _enum(
        "discovery_normalization_state",
        ("raw", "normalized", "failed_retryable", "failed_terminal"),
    )
    _enum("discovery_candidate_admission_state", ("pending", "admitted", "merged", "excluded"))
    _enum(
        "discovery_field_resolution_state",
        (
            "pending",
            "resolved",
            "confirmed_missing",
            "conflict",
            "review_required",
            "accepted_missing",
            "account_excluded",
            "blocked_by_policy",
            "failed_retryable",
            "failed_terminal",
        ),
    )

    op.execute(
        """
        CREATE TABLE discovery_plan (
            id                        uuid NOT NULL,
            workspace_id              text NOT NULL,
            project_id                text NOT NULL,
            project_run_id            uuid NOT NULL,
            icp_key                   text NOT NULL,
            icp_version               integer NOT NULL,
            plan_version              integer NOT NULL,
            plan_sha256               text NOT NULL,
            provider_policy_version   text NOT NULL,
            field_policy_version      text NOT NULL,
            provider_contract_version text NOT NULL,
            plan_json                 jsonb NOT NULL,
            created_at                timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT discovery_plan_pkey PRIMARY KEY (id),
            CONSTRAINT discovery_plan_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT discovery_plan_project_fk FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            CONSTRAINT discovery_plan_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT discovery_plan_icp_fk FOREIGN KEY (workspace_id, icp_key, icp_version)
                REFERENCES icp_spec (workspace_id, icp_key, version),
            CONSTRAINT discovery_plan_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT discovery_plan_run_version_unique
                UNIQUE (workspace_id, project_run_id, plan_version),
            CONSTRAINT discovery_plan_sha_unique UNIQUE (workspace_id, plan_sha256),
            CONSTRAINT discovery_plan_version_positive CHECK (plan_version >= 1),
            CONSTRAINT discovery_plan_icp_version_positive CHECK (icp_version >= 1),
            CONSTRAINT discovery_plan_sha_shape CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT discovery_plan_json_object CHECK (jsonb_typeof(plan_json) = 'object')
        )
        """
    )

    op.execute(
        """
        CREATE TABLE discovery_batch (
            id                      uuid NOT NULL,
            workspace_id            text NOT NULL,
            project_id              text NOT NULL,
            project_run_id          uuid NOT NULL,
            icp_key                 text NOT NULL,
            icp_version             integer NOT NULL,
            discovery_plan_id       uuid NOT NULL,
            state                   discovery_batch_state NOT NULL DEFAULT 'planned',
            generation              integer NOT NULL,
            provider_units_reserved numeric NOT NULL DEFAULT 0,
            provider_units_charged  numeric NOT NULL DEFAULT 0,
            cost_cents_charged      numeric NOT NULL DEFAULT 0,
            failure_code            text,
            replacement_batch_id    uuid,
            started_at              timestamptz NOT NULL DEFAULT now(),
            updated_at              timestamptz NOT NULL DEFAULT now(),
            sealed_at               timestamptz,

            CONSTRAINT discovery_batch_pkey PRIMARY KEY (id),
            CONSTRAINT discovery_batch_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT discovery_batch_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT discovery_batch_plan_fk FOREIGN KEY (discovery_plan_id, workspace_id)
                REFERENCES discovery_plan (id, workspace_id),
            CONSTRAINT discovery_batch_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT discovery_batch_run_generation_unique
                UNIQUE (workspace_id, project_run_id, generation),
            CONSTRAINT discovery_batch_generation_positive CHECK (generation >= 1),
            CONSTRAINT discovery_batch_units_nonnegative CHECK (
                provider_units_reserved >= 0 AND provider_units_charged >= 0
            ),
            CONSTRAINT discovery_batch_cost_nonnegative CHECK (cost_cents_charged >= 0),
            CONSTRAINT discovery_batch_sealed_at_iff_sealed CHECK (
                (state = 'sealed') = (sealed_at IS NOT NULL)
            ),
            CONSTRAINT discovery_batch_replacement_not_self CHECK (
                replacement_batch_id IS NULL OR replacement_batch_id <> id
            )
        )
        """
    )
    op.execute(
        "ALTER TABLE discovery_batch ADD CONSTRAINT discovery_batch_replacement_fk "
        "FOREIGN KEY (replacement_batch_id, workspace_id) "
        "REFERENCES discovery_batch (id, workspace_id)"
    )
    op.execute(
        "CREATE INDEX discovery_batch_run_state ON discovery_batch "
        "(workspace_id, project_run_id, state)"
    )

    op.execute(
        """
        CREATE TABLE discovery_operation (
            id                         uuid NOT NULL,
            workspace_id               text NOT NULL,
            batch_id                   uuid NOT NULL,
            source_key                 text NOT NULL,
            provider_api_version       text NOT NULL,
            request_fingerprint        text NOT NULL,
            observation_window         text NOT NULL,
            provider_external_id       text NOT NULL,
            provider_operation_id      text,
            state                      discovery_operation_state NOT NULL DEFAULT 'planned',
            spend_outcome              discovery_spend_outcome NOT NULL DEFAULT 'not_dispatched',
            next_poll_at               timestamptz,
            submitted_receipt_ref      text,
            final_receipt_ref          text,
            raw_request_artifact_key   text,
            raw_response_manifest_key  text,
            provider_units_reserved    numeric NOT NULL DEFAULT 0,
            provider_units_charged     numeric NOT NULL DEFAULT 0,
            cost_cents_charged         numeric NOT NULL DEFAULT 0,
            final_reconciled_at        timestamptz,
            pagination_exhausted_at    timestamptz,
            started_at                 timestamptz,
            terminal_at                timestamptz,
            created_at                 timestamptz NOT NULL DEFAULT now(),
            updated_at                 timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT discovery_operation_pkey PRIMARY KEY (id),
            CONSTRAINT discovery_operation_batch_fk FOREIGN KEY (batch_id, workspace_id)
                REFERENCES discovery_batch (id, workspace_id),
            CONSTRAINT discovery_operation_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT discovery_operation_batch_anchor UNIQUE (id, workspace_id, batch_id),
            CONSTRAINT discovery_operation_request_unique
                UNIQUE (workspace_id, source_key, request_fingerprint, observation_window),
            CONSTRAINT discovery_operation_external_unique
                UNIQUE (source_key, provider_external_id),
            CONSTRAINT discovery_operation_fingerprint_shape
                CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT discovery_operation_units_nonnegative CHECK (
                provider_units_reserved >= 0 AND provider_units_charged >= 0
            ),
            CONSTRAINT discovery_operation_cost_nonnegative CHECK (cost_cents_charged >= 0),
            CONSTRAINT discovery_operation_unknown_spend_coherent CHECK (
                (state = 'spend_outcome_unknown') = (spend_outcome = 'unknown')
            ),
            CONSTRAINT discovery_operation_not_charged_zero CHECK (
                spend_outcome <> 'not_charged'
                OR (provider_units_charged = 0 AND cost_cents_charged = 0)
            ),
            CONSTRAINT discovery_operation_terminal_at_coherent CHECK (
                (state IN (
                    'succeeded', 'accepted_terminal_failure', 'failed_terminal', 'cancelled'
                ))
                = (terminal_at IS NOT NULL)
            ),
            CONSTRAINT discovery_operation_seal_terminal_dispatched CHECK (
                state NOT IN ('succeeded', 'accepted_terminal_failure')
                OR spend_outcome <> 'not_dispatched'
            ),
            CONSTRAINT discovery_operation_success_provider_id CHECK (
                state <> 'succeeded' OR provider_operation_id IS NOT NULL
            ),
            CONSTRAINT discovery_operation_success_response CHECK (
                state <> 'succeeded' OR raw_response_manifest_key IS NOT NULL
            ),
            CONSTRAINT discovery_operation_terminal_receipts CHECK (
                state NOT IN ('succeeded', 'accepted_terminal_failure')
                OR (submitted_receipt_ref IS NOT NULL AND final_receipt_ref IS NOT NULL
                    AND raw_request_artifact_key IS NOT NULL)
            ),
            CONSTRAINT discovery_operation_submitted_receipt_fk
                FOREIGN KEY (submitted_receipt_ref, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_operation_final_receipt_fk
                FOREIGN KEY (final_receipt_ref, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_operation_request_artifact_fk
                FOREIGN KEY (raw_request_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_operation_response_manifest_fk
                FOREIGN KEY (raw_response_manifest_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX discovery_operation_provider_id_unique ON discovery_operation "
        "(source_key, provider_operation_id) WHERE provider_operation_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX discovery_operation_poll_due ON discovery_operation "
        "(workspace_id, next_poll_at) WHERE next_poll_at IS NOT NULL "
        "AND state IN ('provider_running', 'waiting_external', 'reconciling')"
    )

    op.execute(
        """
        CREATE TABLE discovery_provider_event (
            id                     uuid NOT NULL,
            workspace_id           text NOT NULL,
            operation_id           uuid NOT NULL,
            provider_event_id      text NOT NULL,
            event_type             text NOT NULL,
            signature_verified     boolean NOT NULL,
            payload_artifact_key   text NOT NULL,
            provider_created_at    timestamptz NOT NULL,
            received_at            timestamptz NOT NULL,
            processed_at           timestamptz,
            processing_disposition discovery_event_disposition NOT NULL DEFAULT 'pending',

            CONSTRAINT discovery_provider_event_pkey PRIMARY KEY (id),
            CONSTRAINT discovery_provider_event_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES discovery_operation (id, workspace_id),
            CONSTRAINT discovery_provider_event_artifact_fk
                FOREIGN KEY (payload_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_provider_event_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT discovery_provider_event_identity_unique
                UNIQUE (workspace_id, operation_id, provider_event_id),
            CONSTRAINT discovery_provider_event_processing_coherent CHECK (
                (processing_disposition = 'pending') = (processed_at IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX discovery_provider_event_operation_time ON discovery_provider_event "
        "(workspace_id, operation_id, provider_created_at, provider_event_id)"
    )

    op.execute(
        """
        CREATE TABLE discovery_page_receipt (
            id                   uuid NOT NULL,
            workspace_id         text NOT NULL,
            operation_id         uuid NOT NULL,
            resource_kind        discovery_page_resource NOT NULL,
            request_cursor_key    text NOT NULL DEFAULT '__first_page__',
            next_cursor           text,
            has_more              boolean NOT NULL,
            payload_artifact_key  text NOT NULL,
            payload_sha256        text NOT NULL,
            item_count            integer NOT NULL,
            fetched_at            timestamptz NOT NULL,

            CONSTRAINT discovery_page_receipt_pkey PRIMARY KEY (id),
            CONSTRAINT discovery_page_receipt_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES discovery_operation (id, workspace_id),
            CONSTRAINT discovery_page_receipt_artifact_fk
                FOREIGN KEY (payload_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_page_receipt_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT discovery_page_receipt_operation_anchor
                UNIQUE (id, workspace_id, operation_id),
            CONSTRAINT discovery_page_receipt_cursor_unique
                UNIQUE (workspace_id, operation_id, resource_kind, request_cursor_key),
            CONSTRAINT discovery_page_receipt_cursor_nonempty
                CHECK (length(btrim(request_cursor_key)) > 0),
            CONSTRAINT discovery_page_receipt_sha_shape
                CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT discovery_page_receipt_count_nonnegative CHECK (item_count >= 0),
            CONSTRAINT discovery_page_receipt_cursor_coherent CHECK (
                (has_more AND next_cursor IS NOT NULL AND length(btrim(next_cursor)) > 0)
                OR (NOT has_more AND next_cursor IS NULL)
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE discovery_item_snapshot (
            id                  uuid NOT NULL,
            workspace_id        text NOT NULL,
            operation_id        uuid NOT NULL,
            provider_item_id    text NOT NULL,
            source_kind         text NOT NULL,
            source_id           text NOT NULL,
            raw_artifact_key    text NOT NULL,
            item_sha256         text NOT NULL,
            observed_at         timestamptz NOT NULL,
            normalization_state discovery_normalization_state NOT NULL DEFAULT 'raw',
            normalized_at       timestamptz,

            CONSTRAINT discovery_item_snapshot_pkey PRIMARY KEY (id),
            CONSTRAINT discovery_item_snapshot_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES discovery_operation (id, workspace_id),
            CONSTRAINT discovery_item_snapshot_artifact_fk
                FOREIGN KEY (raw_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_item_snapshot_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT discovery_item_snapshot_operation_anchor
                UNIQUE (id, workspace_id, operation_id),
            CONSTRAINT discovery_item_snapshot_lineage_unique
                UNIQUE (workspace_id, operation_id, provider_item_id, item_sha256),
            CONSTRAINT discovery_item_snapshot_sha_shape CHECK (item_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT discovery_item_snapshot_normalized_at_coherent CHECK (
                (normalization_state = 'normalized') = (normalized_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX discovery_item_snapshot_provider_item ON discovery_item_snapshot "
        "(workspace_id, operation_id, provider_item_id)"
    )

    # A page-to-item edge is required to prove that every page member has a durable snapshot;
    # comparing only aggregate counts cannot detect a missing item offset by a duplicate.
    op.execute(
        """
        CREATE TABLE discovery_page_item (
            workspace_id    text NOT NULL,
            operation_id    uuid NOT NULL,
            page_receipt_id uuid NOT NULL,
            item_snapshot_id uuid NOT NULL,
            ordinal         integer NOT NULL,

            CONSTRAINT discovery_page_item_pkey
                PRIMARY KEY (workspace_id, page_receipt_id, item_snapshot_id),
            CONSTRAINT discovery_page_item_page_fk
                FOREIGN KEY (page_receipt_id, workspace_id, operation_id)
                REFERENCES discovery_page_receipt (id, workspace_id, operation_id),
            CONSTRAINT discovery_page_item_item_fk
                FOREIGN KEY (item_snapshot_id, workspace_id, operation_id)
                REFERENCES discovery_item_snapshot (id, workspace_id, operation_id),
            CONSTRAINT discovery_page_item_ordinal_unique
                UNIQUE (workspace_id, page_receipt_id, ordinal),
            CONSTRAINT discovery_page_item_ordinal_nonnegative CHECK (ordinal >= 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE discovery_candidate_link (
            workspace_id        text NOT NULL,
            batch_id            uuid NOT NULL,
            item_snapshot_id    uuid NOT NULL,
            raw_name            text,
            candidate_domain    text,
            source_url          text,
            admission_status    discovery_candidate_admission_state NOT NULL DEFAULT 'pending',
            account_entity_id   uuid,
            survivor_entity_id  uuid,
            disposition_reason  text,
            updated_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT discovery_candidate_link_pkey
                PRIMARY KEY (workspace_id, batch_id, item_snapshot_id),
            CONSTRAINT discovery_candidate_link_batch_fk FOREIGN KEY (batch_id, workspace_id)
                REFERENCES discovery_batch (id, workspace_id),
            CONSTRAINT discovery_candidate_link_item_fk
                FOREIGN KEY (item_snapshot_id, workspace_id)
                REFERENCES discovery_item_snapshot (id, workspace_id),
            CONSTRAINT discovery_candidate_link_account_fk
                FOREIGN KEY (account_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT discovery_candidate_link_survivor_fk
                FOREIGN KEY (survivor_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT discovery_candidate_link_shape CHECK (
                (admission_status = 'pending' AND account_entity_id IS NULL
                    AND survivor_entity_id IS NULL AND disposition_reason IS NULL)
                OR (admission_status = 'admitted' AND account_entity_id IS NOT NULL
                    AND survivor_entity_id = account_entity_id AND disposition_reason IS NULL)
                OR (admission_status = 'merged' AND account_entity_id IS NOT NULL
                    AND survivor_entity_id IS NOT NULL
                    AND survivor_entity_id <> account_entity_id
                    AND disposition_reason IS NOT NULL)
                OR (admission_status = 'excluded' AND account_entity_id IS NULL
                    AND survivor_entity_id IS NULL AND disposition_reason IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX discovery_candidate_survivor ON discovery_candidate_link "
        "(workspace_id, batch_id, survivor_entity_id) WHERE survivor_entity_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE discovery_field_resolution (
            id                       uuid NOT NULL,
            workspace_id             text NOT NULL,
            batch_id                 uuid NOT NULL,
            account_entity_id        uuid NOT NULL,
            logical_field_key        text NOT NULL,
            state                    discovery_field_resolution_state NOT NULL DEFAULT 'pending',
            winning_claim_id         uuid,
            reason_code              text,
            review_disposition_ref   text,
            updated_at               timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT discovery_field_resolution_pkey PRIMARY KEY (id),
            CONSTRAINT discovery_field_resolution_batch_fk FOREIGN KEY (batch_id, workspace_id)
                REFERENCES discovery_batch (id, workspace_id),
            CONSTRAINT discovery_field_resolution_account_fk
                FOREIGN KEY (account_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT discovery_field_resolution_winner_fk FOREIGN KEY (winning_claim_id)
                REFERENCES claim (id),
            CONSTRAINT discovery_field_resolution_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT discovery_field_resolution_identity_unique
                UNIQUE (workspace_id, batch_id, account_entity_id, logical_field_key),
            CONSTRAINT discovery_field_resolution_shape CHECK (
                (state = 'pending' AND winning_claim_id IS NULL AND reason_code IS NULL)
                OR (state = 'resolved' AND winning_claim_id IS NOT NULL AND reason_code IS NULL)
                OR (state IN ('confirmed_missing', 'conflict', 'review_required',
                              'accepted_missing', 'account_excluded', 'blocked_by_policy',
                              'failed_retryable', 'failed_terminal')
                    AND winning_claim_id IS NULL AND reason_code IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX discovery_field_resolution_batch_state ON discovery_field_resolution "
        "(workspace_id, batch_id, state)"
    )

    op.execute(
        """
        CREATE TABLE discovery_field_claim (
            workspace_id  text NOT NULL,
            resolution_id uuid NOT NULL,
            claim_id      uuid NOT NULL,

            CONSTRAINT discovery_field_claim_pkey
                PRIMARY KEY (workspace_id, resolution_id, claim_id),
            CONSTRAINT discovery_field_claim_resolution_fk
                FOREIGN KEY (resolution_id, workspace_id)
                REFERENCES discovery_field_resolution (id, workspace_id),
            CONSTRAINT discovery_field_claim_claim_fk FOREIGN KEY (claim_id) REFERENCES claim (id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE discovery_field_source_item (
            workspace_id    text NOT NULL,
            resolution_id   uuid NOT NULL,
            item_snapshot_id uuid NOT NULL,

            CONSTRAINT discovery_field_source_item_pkey
                PRIMARY KEY (workspace_id, resolution_id, item_snapshot_id),
            CONSTRAINT discovery_field_source_item_resolution_fk
                FOREIGN KEY (resolution_id, workspace_id)
                REFERENCES discovery_field_resolution (id, workspace_id),
            CONSTRAINT discovery_field_source_item_item_fk
                FOREIGN KEY (item_snapshot_id, workspace_id)
                REFERENCES discovery_item_snapshot (id, workspace_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE discovery_batch_seal (
            batch_id                       uuid NOT NULL,
            workspace_id                   text NOT NULL,
            seal_sha256                    text NOT NULL,
            project_run_id                 uuid NOT NULL,
            icp_key                        text NOT NULL,
            icp_version                    integer NOT NULL,
            discovery_plan_id              uuid NOT NULL,
            plan_sha256                    text NOT NULL,
            sealed_at                      timestamptz NOT NULL,
            account_count                  integer NOT NULL,
            account_manifest_artifact_key  text NOT NULL,
            account_manifest_sha256        text NOT NULL,
            excluded_candidate_count       integer NOT NULL,
            field_resolution_summary       jsonb NOT NULL,
            provider_operation_ids         jsonb NOT NULL,
            request_fingerprints            jsonb NOT NULL,
            raw_artifact_manifest_key       text NOT NULL,
            claim_id_manifest_key           text NOT NULL,
            provider_units_charged          numeric NOT NULL,
            cost_cents_charged              numeric NOT NULL,
            coverage_report_ref             text NOT NULL,

            CONSTRAINT discovery_batch_seal_pkey PRIMARY KEY (batch_id),
            CONSTRAINT discovery_batch_seal_batch_fk FOREIGN KEY (batch_id, workspace_id)
                REFERENCES discovery_batch (id, workspace_id),
            CONSTRAINT discovery_batch_seal_plan_fk FOREIGN KEY (discovery_plan_id, workspace_id)
                REFERENCES discovery_plan (id, workspace_id),
            CONSTRAINT discovery_batch_seal_account_manifest_fk
                FOREIGN KEY (account_manifest_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_batch_seal_raw_manifest_fk
                FOREIGN KEY (raw_artifact_manifest_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_batch_seal_claim_manifest_fk
                FOREIGN KEY (claim_id_manifest_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_batch_seal_coverage_ref_fk
                FOREIGN KEY (coverage_report_ref, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_batch_seal_sha_unique UNIQUE (seal_sha256),
            CONSTRAINT discovery_batch_seal_sha_shape CHECK (seal_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT discovery_batch_seal_plan_sha_shape CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT discovery_batch_seal_manifest_sha_shape
                CHECK (account_manifest_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT discovery_batch_seal_counts_nonnegative
                CHECK (account_count >= 0 AND excluded_candidate_count >= 0),
            CONSTRAINT discovery_batch_seal_costs_nonnegative
                CHECK (provider_units_charged >= 0 AND cost_cents_charged >= 0),
            CONSTRAINT discovery_batch_seal_summary_object
                CHECK (jsonb_typeof(field_resolution_summary) = 'object'),
            CONSTRAINT discovery_batch_seal_operations_array
                CHECK (jsonb_typeof(provider_operation_ids) = 'array'),
            CONSTRAINT discovery_batch_seal_fingerprints_array
                CHECK (jsonb_typeof(request_fingerprints) = 'array')
        )
        """
    )

    # A conservative subject index over raw and manifest artifacts.  ``subject_entity_id`` is a
    # typed soft reference because one table indexes both account and contact subjects.  The
    # scoped repository verifies the workspace-local entity before inserting the edge.
    op.execute(
        """
        CREATE TABLE discovery_artifact_subject (
            id                uuid NOT NULL,
            workspace_id      text NOT NULL,
            artifact_key      text NOT NULL,
            subject_kind      text NOT NULL,
            subject_entity_id uuid NOT NULL,
            reference_kind    text NOT NULL,
            reference_id      text NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),
            tombstoned_at     timestamptz,

            CONSTRAINT discovery_artifact_subject_pkey PRIMARY KEY (id),
            CONSTRAINT discovery_artifact_subject_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT discovery_artifact_subject_artifact_fk
                FOREIGN KEY (artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT discovery_artifact_subject_kind
                CHECK (subject_kind IN ('account', 'contact')),
            CONSTRAINT discovery_artifact_subject_identity_unique
                UNIQUE (workspace_id, artifact_key, subject_kind, subject_entity_id,
                        reference_kind, reference_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX discovery_artifact_subject_lookup ON discovery_artifact_subject "
        "(workspace_id, subject_kind, subject_entity_id, created_at, id) "
        "WHERE tombstoned_at IS NULL"
    )

    # Transactional outbox implementation of the scheduler seam.  Queue publication can crash and
    # replay safely because the stable dedupe key is committed before any external enqueue.
    op.execute(
        """
        CREATE TABLE discovery_wake_outbox (
            id                uuid NOT NULL,
            workspace_id      text NOT NULL,
            project_run_id    uuid NOT NULL,
            batch_id          uuid NOT NULL,
            operation_id      uuid,
            reason            text NOT NULL,
            available_at      timestamptz NOT NULL,
            dedupe_key        text NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),
            claimed_at        timestamptz,
            processed_at      timestamptz,

            CONSTRAINT discovery_wake_outbox_pkey PRIMARY KEY (id),
            CONSTRAINT discovery_wake_outbox_batch_fk FOREIGN KEY (batch_id, workspace_id)
                REFERENCES discovery_batch (id, workspace_id),
            CONSTRAINT discovery_wake_outbox_operation_fk
                FOREIGN KEY (operation_id, workspace_id, batch_id)
                REFERENCES discovery_operation (id, workspace_id, batch_id),
            CONSTRAINT discovery_wake_outbox_dedupe_unique UNIQUE (workspace_id, dedupe_key),
            CONSTRAINT discovery_wake_outbox_reason CHECK (
                reason IN ('scheduled_poll', 'provider_event', 'manual_reconcile', 'crash_recovery')
            ),
            CONSTRAINT discovery_wake_outbox_processed_after_claim CHECK (
                processed_at IS NULL OR claimed_at IS NOT NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX discovery_wake_outbox_due ON discovery_wake_outbox "
        "(available_at, id) WHERE processed_at IS NULL"
    )

    # Immutable records.  Mutable lifecycle tables intentionally do not receive this trigger.
    op.execute(
        """
        CREATE FUNCTION discovery_reject_immutable_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is immutable', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("discovery_plan", "discovery_page_receipt", "discovery_batch_seal"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION discovery_reject_immutable_mutation()"
        )

    # A seal closes the generation, not only the seal row.  Every child write is rejected after
    # the parent batch becomes sealed.  Provider events are the single exception: a late delivery
    # may be appended only when it is born terminal as ``late_after_seal``; it cannot mutate any
    # already-materialized discovery state.
    op.execute(
        """
        CREATE FUNCTION discovery_reject_sealed_batch_mutation() RETURNS trigger AS $$
        DECLARE
            scoped_workspace text;
            scoped_batch uuid;
            scoped_operation uuid;
            scoped_resolution uuid;
            current_state text;
        BEGIN
            IF TG_TABLE_NAME IN (
                'discovery_operation', 'discovery_candidate_link',
                'discovery_field_resolution'
            ) THEN
                IF TG_OP = 'DELETE' THEN
                    scoped_workspace := OLD.workspace_id;
                    scoped_batch := OLD.batch_id;
                ELSE
                    scoped_workspace := NEW.workspace_id;
                    scoped_batch := NEW.batch_id;
                END IF;
            ELSIF TG_TABLE_NAME IN (
                'discovery_provider_event', 'discovery_page_receipt',
                'discovery_item_snapshot', 'discovery_page_item'
            ) THEN
                IF TG_OP = 'DELETE' THEN
                    scoped_workspace := OLD.workspace_id;
                    scoped_operation := OLD.operation_id;
                ELSE
                    scoped_workspace := NEW.workspace_id;
                    scoped_operation := NEW.operation_id;
                END IF;
                SELECT operation.batch_id INTO scoped_batch
                FROM discovery_operation operation
                WHERE operation.workspace_id = scoped_workspace
                  AND operation.id = scoped_operation;
            ELSE
                IF TG_OP = 'DELETE' THEN
                    scoped_workspace := OLD.workspace_id;
                    scoped_resolution := OLD.resolution_id;
                ELSE
                    scoped_workspace := NEW.workspace_id;
                    scoped_resolution := NEW.resolution_id;
                END IF;
                SELECT resolution.batch_id INTO scoped_batch
                FROM discovery_field_resolution resolution
                WHERE resolution.workspace_id = scoped_workspace
                  AND resolution.id = scoped_resolution;
            END IF;

            SELECT batch.state::text INTO current_state
            FROM discovery_batch batch
            WHERE batch.workspace_id = scoped_workspace AND batch.id = scoped_batch;

            IF current_state = 'sealed' THEN
                IF TG_TABLE_NAME = 'discovery_provider_event' AND TG_OP = 'INSERT' THEN
                    IF NEW.processing_disposition = 'late_after_seal'
                       AND NEW.processed_at IS NOT NULL THEN
                        RETURN NEW;
                    END IF;
                END IF;
                RAISE EXCEPTION 'discovery batch % is sealed', scoped_batch;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "discovery_operation",
        "discovery_provider_event",
        "discovery_page_receipt",
        "discovery_item_snapshot",
        "discovery_page_item",
        "discovery_candidate_link",
        "discovery_field_resolution",
        "discovery_field_claim",
        "discovery_field_source_item",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_sealed_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION discovery_reject_sealed_batch_mutation()"
        )
    op.execute(
        """
        CREATE FUNCTION discovery_reject_sealed_batch_reopen() RETURNS trigger AS $$
        BEGIN
            IF OLD.state = 'sealed' AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'discovery batch % is sealed', OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER discovery_batch_sealed_guard BEFORE UPDATE ON discovery_batch "
        "FOR EACH ROW EXECUTE FUNCTION discovery_reject_sealed_batch_reopen()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS discovery_batch_sealed_guard ON discovery_batch")
    op.execute("DROP FUNCTION IF EXISTS discovery_reject_sealed_batch_reopen()")
    for table in ("discovery_batch_seal", "discovery_page_receipt", "discovery_plan"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS discovery_reject_immutable_mutation()")

    op.execute("DROP TABLE IF EXISTS discovery_wake_outbox")
    op.execute("DROP TABLE IF EXISTS discovery_artifact_subject")
    op.execute("DROP TABLE IF EXISTS discovery_batch_seal")
    op.execute("DROP TABLE IF EXISTS discovery_field_source_item")
    op.execute("DROP TABLE IF EXISTS discovery_field_claim")
    op.execute("DROP TABLE IF EXISTS discovery_field_resolution")
    op.execute("DROP TABLE IF EXISTS discovery_candidate_link")
    op.execute("DROP TABLE IF EXISTS discovery_page_item")
    op.execute("DROP TABLE IF EXISTS discovery_item_snapshot")
    op.execute("DROP TABLE IF EXISTS discovery_page_receipt")
    op.execute("DROP TABLE IF EXISTS discovery_provider_event")
    op.execute("DROP TABLE IF EXISTS discovery_operation")
    op.execute("DROP FUNCTION IF EXISTS discovery_reject_sealed_batch_mutation()")
    op.execute(
        "ALTER TABLE discovery_batch DROP CONSTRAINT IF EXISTS discovery_batch_replacement_fk"
    )
    op.execute("DROP TABLE IF EXISTS discovery_batch")
    op.execute("DROP TABLE IF EXISTS discovery_plan")

    for name in (
        "discovery_field_resolution_state",
        "discovery_candidate_admission_state",
        "discovery_normalization_state",
        "discovery_page_resource",
        "discovery_event_disposition",
        "discovery_spend_outcome",
        "discovery_operation_state",
        "discovery_batch_state",
    ):
        op.execute(f"DROP TYPE IF EXISTS {name}")

    # PostgreSQL has no DROP VALUE for enums.  Rebuild after moving any externally-waiting
    # checkpoint back to the resumable active state.
    op.execute("ALTER TABLE project_phase_checkpoint ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "UPDATE project_phase_checkpoint SET status = 'in_progress' "
        "WHERE status = 'waiting_external'"
    )
    # The check expression is typed against the old enum.  PostgreSQL cannot rewrite the column
    # through text while that expression remains attached, so recreate it after the enum swap.
    op.execute(
        "ALTER TABLE project_phase_checkpoint DROP CONSTRAINT "
        "project_phase_checkpoint_committed_at_iff_committed"
    )
    op.execute(
        "ALTER TABLE project_phase_checkpoint ALTER COLUMN status TYPE text USING status::text"
    )
    op.execute("DROP TYPE phase_checkpoint_status")
    _enum(
        "phase_checkpoint_status",
        ("in_progress", "awaiting_input", "committed", "failed"),
    )
    op.execute(
        "ALTER TABLE project_phase_checkpoint ALTER COLUMN status "
        "TYPE phase_checkpoint_status USING status::phase_checkpoint_status"
    )
    op.execute(
        "ALTER TABLE project_phase_checkpoint ADD CONSTRAINT "
        "project_phase_checkpoint_committed_at_iff_committed "
        "CHECK ((status = 'committed') = (committed_at IS NOT NULL))"
    )
    op.execute("ALTER TABLE project_phase_checkpoint ALTER COLUMN status SET DEFAULT 'in_progress'")
