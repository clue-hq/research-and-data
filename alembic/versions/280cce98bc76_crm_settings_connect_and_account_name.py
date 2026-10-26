"""crm settings connect and account name

Settings -> Integrations (R-15.3): a connect request may come from Settings, with no chat, so
its project/thread/turn are all null or all set; a connection keeps the CRM account's name
(Salesforce org name; HubSpot's needs a scope Clue does not ask for, so it stays null).

Revision ID: 280cce98bc76
Revises: b1d0eb59cd73
Create Date: 2026-10-25 18:22:24.799212+00:00

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
revision: str = "280cce98bc76"
down_revision: str | None = "b1d0eb59cd73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workspace_integration_connection ADD COLUMN external_account_name text NULL"
    )
    op.execute(
        """
        ALTER TABLE crm_connect_request
            ALTER COLUMN project_id DROP NOT NULL,
            ALTER COLUMN thread_id DROP NOT NULL,
            ALTER COLUMN turn_id DROP NOT NULL,
            ADD CONSTRAINT crm_connect_request_chat_all_or_none CHECK (
                (project_id IS NULL AND thread_id IS NULL AND turn_id IS NULL)
                OR (project_id IS NOT NULL AND thread_id IS NOT NULL AND turn_id IS NOT NULL)
            )
        """
    )


def downgrade() -> None:
    # Settings requests have no chat and cannot exist under the old NOT NULL columns.
    op.execute("DELETE FROM crm_connect_request WHERE turn_id IS NULL")
    op.execute(
        """
        ALTER TABLE crm_connect_request
            DROP CONSTRAINT crm_connect_request_chat_all_or_none,
            ALTER COLUMN project_id SET NOT NULL,
            ALTER COLUMN thread_id SET NOT NULL,
            ALTER COLUMN turn_id SET NOT NULL
        """
    )
    op.execute("ALTER TABLE workspace_integration_connection DROP COLUMN external_account_name")
