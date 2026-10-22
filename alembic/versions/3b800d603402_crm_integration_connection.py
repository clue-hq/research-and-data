"""crm integration: workspace connection, connect requests, crm_connected derived turns.

Spec: docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md §4,
§7; rulings R-3.1, R-3.10. A workspace has at most one active CRM connection (HubSpot or
Salesforce, through Composio — Composio holds the tokens; this row holds only its ids). A connect
request is one connect card shown in a chat: it records the waiting chat and the latest login
attempt, so the callback can be verified and every waiting chat woken with a ``crm_connected``
derived turn.

Revision ID: 3b800d603402
Revises: cba395a41e66
Create Date: 2026-10-20 13:34:40.056423+00:00

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
revision: str = "3b800d603402"
down_revision: str | None = "cba395a41e66"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DERIVATIONS_BEFORE = "'design_leg_redelivery', 'design_leg_first_turn', 'discovery_finished'"
_DERIVATIONS_AFTER = _DERIVATIONS_BEFORE + ", 'crm_connected'"


def _derivation_check(values: str) -> str:
    return f"""
        ALTER TABLE agent_turn_submission
            DROP CONSTRAINT agent_turn_submission_derivation_kind,
            ADD CONSTRAINT agent_turn_submission_derivation_kind
                CHECK (derivation IS NULL OR derivation IN ({values}))
        """


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE workspace_integration_connection (
            connection_id uuid NOT NULL,
            workspace_id text NOT NULL,
            provider text NOT NULL,
            composio_connected_account_id text NOT NULL,
            composio_auth_config_id text NOT NULL,
            external_account_id text NULL,
            status text NOT NULL,
            connected_by_user_id text NOT NULL,
            connected_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            disconnected_at timestamptz NULL,
            api_calls_day date NULL,
            api_calls_count integer NOT NULL DEFAULT 0,
            settings jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT workspace_integration_connection_pkey PRIMARY KEY (connection_id),
            CONSTRAINT workspace_integration_connection_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_integration_connection_provider
                CHECK (provider IN ('hubspot', 'salesforce')),
            CONSTRAINT workspace_integration_connection_status
                CHECK (status IN ('active', 'expired', 'disconnected')),
            CONSTRAINT workspace_integration_connection_api_calls_nonnegative
                CHECK (api_calls_count >= 0),
            CONSTRAINT workspace_integration_connection_account_unique
                UNIQUE (composio_connected_account_id)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX workspace_integration_connection_one_active "
        "ON workspace_integration_connection (workspace_id) WHERE status = 'active'"
    )
    op.execute(
        """
        CREATE TABLE crm_connect_request (
            request_id uuid NOT NULL,
            workspace_id text NOT NULL,
            project_id text NOT NULL,
            thread_id text NOT NULL,
            turn_id uuid NOT NULL,
            requested_by_user_id text NOT NULL,
            mode text NOT NULL,
            status text NOT NULL DEFAULT 'open',
            pending_connected_account_id text NULL,
            pending_provider text NULL,
            pending_started_by_user_id text NULL,
            pending_started_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            fulfilled_at timestamptz NULL,
            CONSTRAINT crm_connect_request_pkey PRIMARY KEY (request_id),
            CONSTRAINT crm_connect_request_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT crm_connect_request_mode CHECK (mode IN ('connect', 'reconnect', 'switch')),
            CONSTRAINT crm_connect_request_status
                CHECK (status IN ('open', 'fulfilled', 'cancelled')),
            CONSTRAINT crm_connect_request_pending_provider
                CHECK (pending_provider IS NULL OR pending_provider IN ('hubspot', 'salesforce')),
            CONSTRAINT crm_connect_request_one_per_turn UNIQUE (turn_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX crm_connect_request_open "
        "ON crm_connect_request (workspace_id) WHERE status = 'open'"
    )
    op.execute(_derivation_check(_DERIVATIONS_AFTER))


def _delete_guarded(table: str, guard: str, where: str) -> None:
    """Delete rows from an append-only table, lifting its delete guard for this statement only."""
    op.execute(f"ALTER TABLE {table} DISABLE TRIGGER {guard}")
    op.execute(f"DELETE FROM {table} WHERE {where}")
    op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {guard}")


def _delete_crm_connected_turns() -> None:
    """The ``crm_connected`` wake turns and their child rows (final review I-4: the submission
    table is append-only and its children hold it by foreign key, as in ebf28e41a6a4)."""
    turns = "SELECT turn_id FROM agent_turn_submission WHERE derivation = 'crm_connected'"
    for table, guard in (
        ("agent_turn_submission_context_ref", "agent_turn_submission_context_ref_append_only"),
        ("agent_turn_scope_pin", "agent_turn_scope_pin_append_only"),
        ("agent_turn_knowledge_pin", "agent_turn_knowledge_pin_append_only"),
        ("agent_turn_project_files", "agent_turn_project_files_append_only"),
        ("agent_gate_answer", "agent_gate_answer_append_only"),
    ):
        _delete_guarded(table, guard, f"turn_id IN ({turns})")
    op.execute(f"DELETE FROM agent_turn_submission_attachment WHERE turn_id IN ({turns})")
    _delete_guarded(
        "agent_turn_submission",
        "agent_turn_submission_append_only",
        "derivation = 'crm_connected'",
    )


def downgrade() -> None:
    _delete_crm_connected_turns()
    op.execute(_derivation_check(_DERIVATIONS_BEFORE))
    op.execute("DROP TABLE crm_connect_request")
    op.execute("DROP TABLE workspace_integration_connection")
