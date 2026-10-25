"""crm clue fields: what Clue set up in a connected CRM

Revision ID: 53f06d57df36
Revises: 31b850b308e6
Create Date: 2026-10-24 16:04:46.908841+00:00

CRM Phase 4, Task 1 (rulings R-13.1, R-13.2): a workspace owner or admin lets Clue set up its own
fields in the connected CRM (a HubSpot property group and properties plus a "Possible duplicate"
contact association label; Salesforce custom fields plus a "Clue fields" permission set).
``crm_clue_fields`` is one row per connection recording what that setup left in the CRM: the
object-qualified names of the fields Clue created (``Account.Clue_Id__c``, ``contacts.clue_id``;
the same CRM name exists on both objects), the Salesforce permission set id, the HubSpot
association label type id, its status (``ready`` everything is there; ``partial`` setup stopped
part way; ``gone`` a field Clue created has since disappeared from the CRM), which names were
found gone and when.

The row's workspace and provider must be its connection's own: the composite FK points at a new
``(connection_id, workspace_id, provider)`` key on ``workspace_integration_connection``. A
permission set id is only ever Salesforce's and a label type id only HubSpot's (CHECK).

``downgrade()`` drops the table with its rows and the new connection key; the connections stay.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "53f06d57df36"
down_revision: str | None = "31b850b308e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workspace_integration_connection "
        "ADD CONSTRAINT workspace_integration_connection_provider_anchor "
        "UNIQUE (connection_id, workspace_id, provider)"
    )
    op.execute(
        """
        CREATE TABLE crm_clue_fields (
            connection_id uuid NOT NULL,
            workspace_id text NOT NULL,
            provider text NOT NULL,
            status text NOT NULL,
            created_names text[] NOT NULL DEFAULT '{}',
            gone_names text[] NOT NULL DEFAULT '{}',
            permission_set_id text NULL,
            label_type_id text NULL,
            gone_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT crm_clue_fields_pkey PRIMARY KEY (connection_id),
            CONSTRAINT crm_clue_fields_connection_fk
                FOREIGN KEY (connection_id, workspace_id, provider)
                REFERENCES workspace_integration_connection (connection_id, workspace_id, provider),
            CONSTRAINT crm_clue_fields_provider CHECK (provider IN ('hubspot', 'salesforce')),
            CONSTRAINT crm_clue_fields_status CHECK (status IN ('ready', 'partial', 'gone')),
            CONSTRAINT crm_clue_fields_provider_ids CHECK (
                (provider = 'hubspot' AND permission_set_id IS NULL)
                OR (provider = 'salesforce' AND label_type_id IS NULL)
            ),
            CONSTRAINT crm_clue_fields_gone CHECK ((status = 'gone') = (gone_at IS NOT NULL))
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE crm_clue_fields")
    op.execute(
        "ALTER TABLE workspace_integration_connection "
        "DROP CONSTRAINT workspace_integration_connection_provider_anchor"
    )
