"""crm write: the CRM's whole answer beside its message

Revision ID: 01b066d230e7
Revises: f09f9e286be6
Create Date: 2026-10-22 15:22:39.940952+00:00

CRM Phase 2 live check, finding L8: ``crm_write.crm_message`` held the CRM's whole JSON error
body, which the done card, the wake message and ``crm_write_log`` showed as a blob. The message
becomes the CRM's message text (HubSpot's ``errors[].message``, else its ``message``; Salesforce's
``message (errorCode)``), and this nullable column keeps the answer it came from: the parsed JSON
body, or the raw text when that was too long to show whole. ``NULL`` when the message is the
answer itself (Clue's own sentences, short plain text) and on every row before this revision.

``downgrade()`` drops the column and the answers it kept.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "01b066d230e7"
down_revision: str | None = "f09f9e286be6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE crm_write ADD COLUMN crm_response jsonb NULL")
    op.execute(
        "COMMENT ON COLUMN crm_write.crm_response IS 'The CRM answer crm_message was taken "
        "from: its JSON body, or its raw text when too long to show whole. NULL when crm_message "
        "is the whole answer.'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE crm_write DROP COLUMN crm_response")
