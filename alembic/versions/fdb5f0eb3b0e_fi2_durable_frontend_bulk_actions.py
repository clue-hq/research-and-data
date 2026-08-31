"""fi2 durable frontend bulk actions

Revision ID: fdb5f0eb3b0e
Revises: fee9d89bca93
Create Date: 2026-08-12 19:30:44.823672+00:00

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
revision: str = "fdb5f0eb3b0e"
down_revision: str | None = "fee9d89bca93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE frontend_bulk_action_operation (
            id                          uuid        NOT NULL,
            workspace_id                text        NOT NULL,
            action_key                  text        NOT NULL,
            subject_type                text        NOT NULL,
            idempotency_key             text        NOT NULL,
            request_sha256              text        NOT NULL,
            request_json                jsonb       NOT NULL,
            requested_by_user_id        text,
            requested_via_membership_id text,
            state                       text        NOT NULL DEFAULT 'pending',
            requested_count             integer     NOT NULL,
            completed_count             integer     NOT NULL DEFAULT 0,
            unchanged_count             integer     NOT NULL DEFAULT 0,
            ineligible_count            integer     NOT NULL DEFAULT 0,
            failed_count                integer     NOT NULL DEFAULT 0,
            created_at                  timestamptz NOT NULL DEFAULT now(),
            finalized_at                timestamptz,

            CONSTRAINT frontend_bulk_action_operation_pkey PRIMARY KEY (id),
            CONSTRAINT frontend_bulk_action_operation_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT frontend_bulk_action_operation_membership_workspace_fk
                FOREIGN KEY (requested_via_membership_id, workspace_id)
                REFERENCES workspace_membership (membership_id, workspace_id),
            CONSTRAINT frontend_bulk_action_operation_membership_actor_fk
                FOREIGN KEY (requested_via_membership_id, requested_by_user_id)
                REFERENCES workspace_membership (membership_id, user_id),
            CONSTRAINT frontend_bulk_action_operation_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT frontend_bulk_action_operation_idempotency_unique
                UNIQUE (workspace_id, idempotency_key),
            CONSTRAINT frontend_bulk_action_operation_action_check CHECK (
                (subject_type='account' AND action_key='add_to_project')
                OR (subject_type='contact' AND action_key='lookup_work_email')
            ),
            CONSTRAINT frontend_bulk_action_operation_actor_shape CHECK (
                (requested_by_user_id IS NULL AND requested_via_membership_id IS NULL)
                OR (requested_by_user_id IS NOT NULL AND requested_via_membership_id IS NOT NULL)
            ),
            CONSTRAINT frontend_bulk_action_operation_idempotency_nonempty CHECK (
                length(btrim(idempotency_key)) BETWEEN 1 AND 200
            ),
            CONSTRAINT frontend_bulk_action_operation_request_hash CHECK (
                request_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT frontend_bulk_action_operation_request_object CHECK (
                jsonb_typeof(request_json)='object'
            ),
            CONSTRAINT frontend_bulk_action_operation_state_check CHECK (
                state IN ('pending','completed','partial','failed')
            ),
            CONSTRAINT frontend_bulk_action_operation_counts_check CHECK (
                requested_count BETWEEN 1 AND 100
                AND completed_count >= 0
                AND unchanged_count >= 0
                AND ineligible_count >= 0
                AND failed_count >= 0
                AND completed_count + unchanged_count + ineligible_count + failed_count
                    <= requested_count
            ),
            CONSTRAINT frontend_bulk_action_operation_finalized_shape CHECK (
                (state='pending' AND finalized_at IS NULL)
                OR (state<>'pending' AND finalized_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX frontend_bulk_action_operation_audit "
        "ON frontend_bulk_action_operation "
        "(workspace_id, action_key, requested_by_user_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE frontend_bulk_action_item (
            operation_id uuid        NOT NULL,
            workspace_id text        NOT NULL,
            ordinal      integer     NOT NULL,
            subject_id   uuid        NOT NULL,
            outcome      text        NOT NULL,
            reason_code  text,
            downstream_id uuid,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT frontend_bulk_action_item_pkey PRIMARY KEY (operation_id, ordinal),
            CONSTRAINT frontend_bulk_action_item_operation_workspace_fk
                FOREIGN KEY (operation_id, workspace_id)
                REFERENCES frontend_bulk_action_operation (id, workspace_id),
            CONSTRAINT frontend_bulk_action_item_subject_once
                UNIQUE (operation_id, subject_id),
            CONSTRAINT frontend_bulk_action_item_ordinal_check CHECK (ordinal >= 0),
            CONSTRAINT frontend_bulk_action_item_outcome_check CHECK (
                outcome IN ('accepted','completed','unchanged','not_found','withheld',
                            'ineligible','failed_retryable','failed_terminal')
            ),
            CONSTRAINT frontend_bulk_action_item_reason_nonempty CHECK (
                reason_code IS NULL OR length(btrim(reason_code)) > 0
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX frontend_bulk_action_item_subject_audit "
        "ON frontend_bulk_action_item (workspace_id, subject_id, created_at DESC)"
    )


def downgrade() -> None:
    op.drop_table("frontend_bulk_action_item")
    op.drop_table("frontend_bulk_action_operation")
