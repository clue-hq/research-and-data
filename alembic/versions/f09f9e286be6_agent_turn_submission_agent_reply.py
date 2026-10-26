"""agent turn submission: whether the agent replies

Revision ID: f09f9e286be6
Revises: 0e92986934d3
Create Date: 2026-10-22 13:36:18.738562+00:00

CRM rulings R-11.3 and R-11.6: answering the CRM write card starts no agent turn. The answer
stays a turn submission — the receipt ``agent_gate_answer.turn_id`` points at and the anchor a
retried click replays on — and this column says whether the agent replies to it:

* ``expected`` (the default, and every submission before this revision): the submission is a
  turn the fleet runs;
* ``none``: the submission is recorded and never run. The dispatcher and every busy check skip it.

``downgrade()`` drops the column. A ``none`` submission recorded before a downgrade would then
read as a turn the dispatcher owes; there are none outside development databases.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f09f9e286be6"
down_revision: str | None = "0e92986934d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_turn_submission
            ADD COLUMN agent_reply text NOT NULL DEFAULT 'expected',
            ADD CONSTRAINT agent_turn_submission_agent_reply
                CHECK (agent_reply IN ('expected', 'none'))
        """
    )
    op.execute(
        "COMMENT ON COLUMN agent_turn_submission.agent_reply IS 'Whether the agent replies to "
        "this submission: expected (a turn the fleet runs) or none (recorded only, never run; "
        "a CRM write card answer, R-11.6).'"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_turn_submission
            DROP CONSTRAINT agent_turn_submission_agent_reply,
            DROP COLUMN agent_reply
        """
    )
