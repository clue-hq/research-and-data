"""execution node operation index

Revision ID: 3f0b61c7a2d4
Revises: 22172f5ba3cb
Create Date: 2026-10-24 06:00:00.000000+00:00

F3 Phase 2 (docs/superpowers/specs/agent-workspace/; final-review finding I5).

``clue_api.agent_workspace_receipts`` looks a saved ``reads/<operation_id>.json`` file up by its
operation id to say what tool produced it, and that lookup runs **once per new or changed file,
sequentially, inside a turn's save**. ``execution_node`` had no index that could serve it: the two
it has — ``execution_node_ready_order (execution_id, ordinal, node_key)`` and the unique
``execution_node_operation_unique (execution_id, operation_id)`` — both lead with
``execution_id``, so a lookup by operation id alone was a sequential scan of the execution
journal, one of the largest tables in the system. A CRM-heavy turn that spills forty reads paid
forty of them on its critical path.

``operation_id`` is near-unique across the table (it is unique per execution and minted from a
uuid), so a plain b-tree on it is both small and selective. Nothing about the journal's semantics
changes; this is a read path only.

Hand-written and reversible.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f0b61c7a2d4"
down_revision: str | None = "22172f5ba3cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX execution_node_operation ON execution_node (operation_id)")


def downgrade() -> None:
    op.execute("DROP INDEX execution_node_operation")
