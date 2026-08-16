"""P3.2 checkpoint 2 — per-role attribution on the durable model-call ledger.

PD-part3 delta 6: ONE durable per-role usage authority. ``agent_model_call.role`` is the
agent-role label of the call — stamped from the governed model's per-call ``clue_role``
metadata when the instance is role-labelled (the design trio runs three roles inside one
turn, so the TURN's role is not enough), else the turn's constitution role. Nullable:
every historical row predates attribution and stays honestly NULL; new writes always
stamp. The vocabulary CHECK mirrors the (P3.1-widened) agent-role vocabulary.
"""

from alembic import op

revision = "65880921cd52"
down_revision = "549de68ae3b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_model_call ADD COLUMN role text")
    op.execute(
        "ALTER TABLE agent_model_call ADD CONSTRAINT agent_model_call_role CHECK ("
        "role IS NULL OR role IN ('head_of_abm', 'research', 'content_drafter', "
        "'reviewer', 'account_research', 'design'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_model_call DROP CONSTRAINT agent_model_call_role")
    op.execute("ALTER TABLE agent_model_call DROP COLUMN role")
