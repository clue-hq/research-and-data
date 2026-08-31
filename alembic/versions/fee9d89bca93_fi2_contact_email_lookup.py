"""FI-2 durable interactive Contact email acquisition.

Revision ID: fee9d89bca93
Revises: 5d7ab295742b
Create Date: 2026-08-12 18:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "fee9d89bca93"
down_revision: str | None = "5d7ab295742b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE contact_email_lookup (
            id uuid NOT NULL,
            workspace_id text NOT NULL,
            account_id uuid NOT NULL,
            contact_id uuid NOT NULL,
            requested_by text NOT NULL,
            observation_window text NOT NULL,
            request_fingerprint text NOT NULL,
            policy_version integer NOT NULL,
            target_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT contact_email_lookup_pkey PRIMARY KEY (id),
            CONSTRAINT contact_email_lookup_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT contact_email_lookup_account_fk FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT contact_email_lookup_contact_fk FOREIGN KEY (contact_id, workspace_id)
                REFERENCES contact_entity (id, workspace_id),
            CONSTRAINT contact_email_lookup_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT contact_email_lookup_window_unique
                UNIQUE (workspace_id, contact_id, observation_window),
            CONSTRAINT contact_email_lookup_fingerprint_unique
                UNIQUE (workspace_id, request_fingerprint),
            CONSTRAINT contact_email_lookup_hash CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
            CONSTRAINT contact_email_lookup_window CHECK (
                observation_window ~ '^[0-9]{4}-[0-9]{2}$'
            ),
            CONSTRAINT contact_email_lookup_requester CHECK (length(btrim(requested_by)) > 0),
            CONSTRAINT contact_email_lookup_policy CHECK (policy_version >= 1),
            CONSTRAINT contact_email_lookup_target_object CHECK (jsonb_typeof(target_json)='object')
        )
        """
    )
    op.execute(
        "CREATE INDEX contact_email_lookup_subject ON contact_email_lookup "
        "(workspace_id, account_id, contact_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE contact_email_lookup_provider (
            lookup_id uuid NOT NULL,
            workspace_id text NOT NULL,
            source_key text NOT NULL,
            state text NOT NULL DEFAULT 'planned',
            request_json jsonb NOT NULL,
            provider_import_id text,
            provider_operation_id text,
            observed_claim_id uuid,
            response_artifact_key text,
            credits_used numeric NOT NULL DEFAULT 0,
            cost_cents numeric NOT NULL DEFAULT 0,
            next_poll_at timestamptz,
            failure_code text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            terminal_at timestamptz,
            CONSTRAINT contact_email_lookup_provider_pkey PRIMARY KEY (lookup_id, source_key),
            CONSTRAINT contact_email_lookup_provider_lookup_fk
                FOREIGN KEY (lookup_id, workspace_id)
                REFERENCES contact_email_lookup (id, workspace_id),
            CONSTRAINT contact_email_lookup_provider_source_fk
                FOREIGN KEY (source_key) REFERENCES source_manifest (source_key),
            CONSTRAINT contact_email_lookup_provider_claim_fk
                FOREIGN KEY (observed_claim_id) REFERENCES claim (id),
            CONSTRAINT contact_email_lookup_provider_artifact_fk
                FOREIGN KEY (response_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT contact_email_lookup_provider_operation_unique
                UNIQUE (source_key, provider_operation_id),
            CONSTRAINT contact_email_lookup_provider_state CHECK (
                state IN ('planned', 'submitting', 'waiting_external', 'polling', 'available',
                          'no_result', 'withheld', 'unavailable', 'failed', 'contract_error',
                          'spend_unknown')
            ),
            CONSTRAINT contact_email_lookup_provider_request_object CHECK (
                jsonb_typeof(request_json)='object'
            ),
            CONSTRAINT contact_email_lookup_provider_cost CHECK (
                credits_used >= 0 AND cost_cents >= 0
            ),
            CONSTRAINT contact_email_lookup_provider_terminal_time CHECK (
                (state IN ('available', 'no_result', 'withheld', 'unavailable', 'failed',
                           'contract_error', 'spend_unknown')) = (terminal_at IS NOT NULL)
            ),
            CONSTRAINT contact_email_lookup_provider_claim_state CHECK (
                observed_claim_id IS NULL OR state IN ('available', 'withheld')
            ),
            CONSTRAINT contact_email_lookup_provider_result_artifact CHECK (
                observed_claim_id IS NULL OR response_artifact_key IS NOT NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX contact_email_lookup_provider_due ON contact_email_lookup_provider "
        "(next_poll_at, lookup_id, source_key) "
        "WHERE state='waiting_external' AND next_poll_at IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE contact_email_lookup_artifact (
            id bigserial NOT NULL,
            lookup_id uuid NOT NULL,
            workspace_id text NOT NULL,
            source_key text NOT NULL,
            artifact_kind text NOT NULL,
            artifact_key text NOT NULL,
            provider_request_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT contact_email_lookup_artifact_pkey PRIMARY KEY (id),
            CONSTRAINT contact_email_lookup_artifact_provider_fk
                FOREIGN KEY (lookup_id, source_key)
                REFERENCES contact_email_lookup_provider (lookup_id, source_key),
            CONSTRAINT contact_email_lookup_artifact_lookup_workspace_fk
                FOREIGN KEY (lookup_id, workspace_id)
                REFERENCES contact_email_lookup (id, workspace_id),
            CONSTRAINT contact_email_lookup_artifact_artifact_fk
                FOREIGN KEY (artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT contact_email_lookup_artifact_kind CHECK (
                length(btrim(artifact_kind)) > 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX contact_email_lookup_artifact_subject ON contact_email_lookup_artifact "
        "(workspace_id, lookup_id, source_key, created_at)"
    )


def downgrade() -> None:
    op.drop_table("contact_email_lookup_artifact")
    op.drop_table("contact_email_lookup_provider")
    op.drop_table("contact_email_lookup")
