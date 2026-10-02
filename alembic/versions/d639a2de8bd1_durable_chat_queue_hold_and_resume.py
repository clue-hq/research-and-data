"""durable chat queue hold and resume

Revision ID: d639a2de8bd1
Revises: c90aaea30a88
Create Date: 2026-09-12 12:05:52.347124+00:00

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
revision: str = "d639a2de8bd1"
down_revision: str | None = "c90aaea30a88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE agent_turn_stop_ack ("
        "control_id uuid PRIMARY KEY REFERENCES agent_turn_control_request (control_id), "
        "acknowledged_at timestamptz NOT NULL DEFAULT now())"
    )
    op.execute(
        "CREATE TRIGGER agent_turn_stop_ack_append_only BEFORE UPDATE OR DELETE "
        "ON agent_turn_stop_ack FOR EACH ROW "
        "EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )
    # Preserve the prior release's already-acknowledged cancellations on upgrade.
    op.execute("""
        INSERT INTO agent_turn_stop_ack (control_id, acknowledged_at)
        SELECT c.control_id, c.requested_at FROM agent_turn_control_request c
        WHERE c.kind='stop' AND (
            EXISTS (SELECT 1 FROM agent_turn_event e WHERE e.turn_id=c.turn_id
                AND e.workspace_id=c.workspace_id AND e.status='cancelled')
            OR EXISTS (SELECT 1 FROM agent_turn_event_stream e WHERE e.turn_id=c.turn_id
                AND e.workspace_id=c.workspace_id AND e.event_type='turn.cancelled')
        )
    """)
    op.execute("ALTER TABLE agent_thread ADD COLUMN queue_hold_control_id uuid")
    op.execute(
        "ALTER TABLE agent_thread ADD CONSTRAINT agent_thread_queue_hold_fk "
        "FOREIGN KEY (queue_hold_control_id) REFERENCES agent_turn_control_request (control_id)"
    )
    op.execute("""
        CREATE TABLE agent_thread_queue_resume (
            hold_control_id uuid PRIMARY KEY REFERENCES agent_turn_control_request (control_id),
            workspace_id text NOT NULL,
            thread_id text NOT NULL,
            resumed_at timestamptz NOT NULL DEFAULT now(),
            resumed_by_user_id text NOT NULL REFERENCES platform_user (user_id),
            resumed_via_membership_id text NOT NULL,
            CONSTRAINT agent_thread_queue_resume_thread_fk FOREIGN KEY (thread_id, workspace_id)
                REFERENCES agent_thread (id, workspace_id),
            CONSTRAINT agent_thread_queue_resume_membership_fk
                FOREIGN KEY (resumed_via_membership_id, workspace_id)
                REFERENCES workspace_membership (membership_id, workspace_id)
        )
    """)
    op.execute(
        "CREATE TRIGGER agent_thread_queue_resume_append_only "
        "BEFORE UPDATE OR DELETE ON agent_thread_queue_resume FOR EACH ROW "
        "EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_turn_stop_ack")
    op.execute("DROP TABLE agent_thread_queue_resume")
    op.execute("ALTER TABLE agent_thread DROP CONSTRAINT agent_thread_queue_hold_fk")
    op.execute("ALTER TABLE agent_thread DROP COLUMN queue_hold_control_id")
