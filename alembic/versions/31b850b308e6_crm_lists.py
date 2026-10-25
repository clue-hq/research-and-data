"""crm lists: the lists and campaigns Clue keeps, and what a write cites

Revision ID: 31b850b308e6
Revises: 01b066d230e7
Create Date: 2026-10-22 21:23:09.781900+00:00

CRM Phase 3, Task 2 (ruling R-11.11): Clue keeps the ids of the CRM lists (HubSpot) and campaigns
(Salesforce) it uses itself. ``crm_list`` is one row per connection and CRM id (``gone_at`` set
when the CRM no longer has it); ``crm_list_project`` links a list to every project that uses it,
saying whether Clue created it for that project or a person named it, and only to a
project of the list's own workspace (composite FKs). Membership stays per list
member in ``crm_record_link``. ``crm_write`` gains ``source_claim_ids`` (the claims a write puts
into the CRM; empty for every write before this revision) and ``clue_entity_id`` (the Clue entity
the written record is), which later Phase 3 tasks fill.

``downgrade()`` drops the two tables with their rows and the two ``crm_write`` columns with their
values; the writes themselves are kept (``crm_write`` has no append-only guard).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "31b850b308e6"
down_revision: str | None = "01b066d230e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE crm_write "
        "ADD COLUMN source_claim_ids uuid[] NOT NULL DEFAULT '{}', "
        "ADD COLUMN clue_entity_id text NULL"
    )
    op.execute(
        """
        CREATE TABLE crm_list (
            list_id uuid NOT NULL,
            workspace_id text NOT NULL,
            connection_id uuid NOT NULL,
            provider text NOT NULL,
            crm_object text NOT NULL,
            crm_list_id text NOT NULL,
            name text NOT NULL,
            kind text NOT NULL,
            created_by_clue boolean NOT NULL,
            created_by_write_id uuid NULL,
            gone_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT crm_list_pkey PRIMARY KEY (list_id),
            CONSTRAINT crm_list_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT crm_list_connection_fk
                FOREIGN KEY (connection_id)
                REFERENCES workspace_integration_connection (connection_id),
            CONSTRAINT crm_list_write_fk
                FOREIGN KEY (created_by_write_id) REFERENCES crm_write (write_id),
            CONSTRAINT crm_list_provider CHECK (provider IN ('hubspot', 'salesforce')),
            CONSTRAINT crm_list_crm_object CHECK (crm_object IN ('company', 'contact')),
            CONSTRAINT crm_list_kind CHECK (kind IN ('hubspot_list', 'salesforce_campaign')),
            CONSTRAINT crm_list_connection_crm_id UNIQUE (connection_id, crm_list_id),
            -- The anchor crm_list_project's composite FK needs, so a link stays in the list's
            -- workspace.
            CONSTRAINT crm_list_workspace_anchor UNIQUE (list_id, workspace_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE crm_list_project (
            list_id uuid NOT NULL,
            project_id text NOT NULL,
            workspace_id text NOT NULL,
            linked_at timestamptz NOT NULL DEFAULT now(),
            linked_by text NOT NULL,
            CONSTRAINT crm_list_project_pkey PRIMARY KEY (list_id, project_id),
            -- Both composite: a list is linked only to a project of its own workspace.
            CONSTRAINT crm_list_project_list_fk
                FOREIGN KEY (list_id, workspace_id) REFERENCES crm_list (list_id, workspace_id),
            CONSTRAINT crm_list_project_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            CONSTRAINT crm_list_project_linked_by
                CHECK (linked_by IN ('clue_created', 'person_named'))
        )
        """
    )
    op.execute("CREATE INDEX crm_list_project_project ON crm_list_project (project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE crm_list_project")
    op.execute("DROP TABLE crm_list")
    op.execute("ALTER TABLE crm_write DROP COLUMN clue_entity_id, DROP COLUMN source_claim_ids")
