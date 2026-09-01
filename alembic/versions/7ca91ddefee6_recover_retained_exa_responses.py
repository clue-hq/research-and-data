"""recover retained exa responses

Revision ID: 7ca91ddefee6
Revises: 486ee7b24ae8
Create Date: 2026-08-18 22:02:35.146523+00:00

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
revision: str = "7ca91ddefee6"
down_revision: str | None = "486ee7b24ae8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE external_research_response_recovery (
            recovery_id          uuid NOT NULL,
            operation_id         uuid NOT NULL,
            workspace_id         text NOT NULL,
            response_artifact_key text NOT NULL,
            provider_request_id  text NOT NULL,
            parser_version       text NOT NULL,
            actor_ref            text NOT NULL,
            recovered_at         timestamptz NOT NULL,

            CONSTRAINT external_research_response_recovery_pkey PRIMARY KEY (recovery_id),
            CONSTRAINT external_research_response_recovery_operation_unique UNIQUE (operation_id),
            CONSTRAINT external_research_response_recovery_operation_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES external_research_operation (id, workspace_id),
            CONSTRAINT external_research_response_recovery_artifact_fk
                FOREIGN KEY (response_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT external_research_response_recovery_nonempty CHECK (
                length(btrim(provider_request_id)) > 0
                AND length(btrim(parser_version)) > 0
                AND length(btrim(actor_ref)) > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION external_research_response_recovery_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'external research response recovery rows are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_response_recovery_immutable "
        "BEFORE UPDATE OR DELETE ON external_research_response_recovery FOR EACH ROW "
        "EXECUTE FUNCTION external_research_response_recovery_immutable()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION external_research_reject_attempt_mutation()
        RETURNS trigger AS $$
        DECLARE
            is_response_recovery boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'external research attempts cannot be deleted';
            END IF;
            IF NEW.operation_id <> OLD.operation_id
               OR NEW.workspace_id <> OLD.workspace_id
               OR NEW.ordinal <> OLD.ordinal
               OR NEW.request_artifact_key <> OLD.request_artifact_key
               OR (
                   NEW.dispatched_at IS DISTINCT FROM OLD.dispatched_at
                   AND NOT (
                       OLD.state = 'dispatching'
                       AND NEW.state = 'failed_pre_dispatch'
                       AND NEW.dispatched_at IS NULL
                   )
               ) THEN
                RAISE EXCEPTION 'external research attempt lineage is immutable';
            END IF;
            is_response_recovery := (
                OLD.state = 'spend_outcome_unknown'
                AND NEW.state = 'responded'
                AND NEW.response_artifact_key = OLD.response_artifact_key
                AND NEW.provider_request_id = OLD.provider_request_id
                AND NEW.failure_code IS NULL
                AND NEW.failure_detail IS NULL
                AND EXISTS (
                    SELECT 1 FROM external_research_response_recovery recovery
                    WHERE recovery.operation_id = OLD.operation_id
                      AND recovery.workspace_id = OLD.workspace_id
                      AND recovery.response_artifact_key = OLD.response_artifact_key
                      AND recovery.provider_request_id = OLD.provider_request_id
                )
            );
            IF OLD.state <> 'dispatching' AND NEW IS DISTINCT FROM OLD
               AND NOT is_response_recovery THEN
                RAISE EXCEPTION 'terminal external research attempt is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION external_research_reject_operation_mutation()
        RETURNS trigger AS $$
        DECLARE
            is_response_recovery boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'external research operations cannot be deleted';
            END IF;
            IF NEW.workspace_id <> OLD.workspace_id
               OR NEW.project_id <> OLD.project_id
               OR NEW.project_run_id <> OLD.project_run_id
               OR NEW.subject_kind <> OLD.subject_kind
               OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR NEW.contact_id IS DISTINCT FROM OLD.contact_id
               OR NEW.icp_key <> OLD.icp_key
               OR NEW.icp_version <> OLD.icp_version
               OR NEW.research_directive_id <> OLD.research_directive_id
               OR NEW.research_directive_version <> OLD.research_directive_version
               OR NEW.research_directive_sha256 <> OLD.research_directive_sha256
               OR NEW.research_override_id IS DISTINCT FROM OLD.research_override_id
               OR NEW.research_override_sha256 IS DISTINCT FROM OLD.research_override_sha256
               OR NEW.source_key <> OLD.source_key
               OR NEW.observation_window <> OLD.observation_window
               OR NEW.freshness_policy_ref <> OLD.freshness_policy_ref
               OR NEW.freshness_seconds <> OLD.freshness_seconds
               OR NEW.request_fingerprint <> OLD.request_fingerprint
               OR NEW.reuse_fingerprint <> OLD.reuse_fingerprint
               OR NEW.wire_request_sha256 <> OLD.wire_request_sha256
               OR NEW.request_json <> OLD.request_json
               OR NEW.request_artifact_key <> OLD.request_artifact_key
               OR NEW.cost_cents_reserved <> OLD.cost_cents_reserved THEN
                RAISE EXCEPTION 'external research request lineage is immutable';
            END IF;
            is_response_recovery := (
                OLD.state = 'spend_outcome_unknown'
                AND NEW.state = 'ready'
                AND NEW.spend_outcome = 'provider_reported'
                AND NEW.provider_request_id = OLD.provider_request_id
                AND NEW.failure_code IS NULL
                AND NEW.failure_detail IS NULL
                AND EXISTS (
                    SELECT 1 FROM external_research_response_recovery recovery
                    WHERE recovery.operation_id = OLD.id
                      AND recovery.workspace_id = OLD.workspace_id
                      AND recovery.provider_request_id = NEW.provider_request_id
                )
            );
            IF OLD.state IN ('ready', 'failed_terminal', 'spend_outcome_unknown', 'cancelled')
               AND NEW IS DISTINCT FROM OLD AND NOT is_response_recovery THEN
                RAISE EXCEPTION 'terminal external research operation is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION external_research_reject_operation_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'external research operations cannot be deleted';
            END IF;
            IF NEW.workspace_id <> OLD.workspace_id
               OR NEW.project_id <> OLD.project_id
               OR NEW.project_run_id <> OLD.project_run_id
               OR NEW.subject_kind <> OLD.subject_kind
               OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR NEW.contact_id IS DISTINCT FROM OLD.contact_id
               OR NEW.icp_key <> OLD.icp_key
               OR NEW.icp_version <> OLD.icp_version
               OR NEW.research_directive_id <> OLD.research_directive_id
               OR NEW.research_directive_version <> OLD.research_directive_version
               OR NEW.research_directive_sha256 <> OLD.research_directive_sha256
               OR NEW.research_override_id IS DISTINCT FROM OLD.research_override_id
               OR NEW.research_override_sha256 IS DISTINCT FROM OLD.research_override_sha256
               OR NEW.source_key <> OLD.source_key
               OR NEW.observation_window <> OLD.observation_window
               OR NEW.freshness_policy_ref <> OLD.freshness_policy_ref
               OR NEW.freshness_seconds <> OLD.freshness_seconds
               OR NEW.request_fingerprint <> OLD.request_fingerprint
               OR NEW.reuse_fingerprint <> OLD.reuse_fingerprint
               OR NEW.wire_request_sha256 <> OLD.wire_request_sha256
               OR NEW.request_json <> OLD.request_json
               OR NEW.request_artifact_key <> OLD.request_artifact_key
               OR NEW.cost_cents_reserved <> OLD.cost_cents_reserved THEN
                RAISE EXCEPTION 'external research request lineage is immutable';
            END IF;
            IF OLD.state IN ('ready', 'failed_terminal', 'spend_outcome_unknown', 'cancelled')
               AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal external research operation is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION external_research_reject_attempt_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'external research attempts cannot be deleted';
            END IF;
            IF NEW.operation_id <> OLD.operation_id
               OR NEW.workspace_id <> OLD.workspace_id
               OR NEW.ordinal <> OLD.ordinal
               OR NEW.request_artifact_key <> OLD.request_artifact_key
               OR (
                   NEW.dispatched_at IS DISTINCT FROM OLD.dispatched_at
                   AND NOT (
                       OLD.state = 'dispatching'
                       AND NEW.state = 'failed_pre_dispatch'
                       AND NEW.dispatched_at IS NULL
                   )
               ) THEN
                RAISE EXCEPTION 'external research attempt lineage is immutable';
            END IF;
            IF OLD.state <> 'dispatching' AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal external research attempt is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER external_research_response_recovery_immutable "
        "ON external_research_response_recovery"
    )
    op.execute("DROP FUNCTION external_research_response_recovery_immutable()")
    op.execute("DROP TABLE external_research_response_recovery")
