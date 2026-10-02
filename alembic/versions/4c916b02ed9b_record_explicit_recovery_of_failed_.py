"""record explicit recovery of failed interaction tools

Revision ID: 4c916b02ed9b
Revises: 7d5efcd83a32
Create Date: 2026-09-25 07:21:48.204469+00:00

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

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c916b02ed9b"
down_revision: str | None = "7d5efcd83a32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD = (
    "execution.queued",
    "execution.started",
    "execution.paused",
    "execution.resumed",
    "execution.completed",
    "execution.failed",
    "node.scheduled",
    "node.started",
    "node.blocked",
    "node.completed",
    "node.failed",
    "node.abandoned",
    "gate.opened",
    "gate.decided",
    "steering.before",
    "steering.after",
    "supervisor.observed",
    "supervisor.diagnosed",
    "supervisor.actioned",
)


def _constraint(values: tuple[str, ...]) -> None:
    op.drop_constraint("execution_event_type", "execution_event", type_="check")
    allowed = ", ".join(repr(value) for value in values)
    op.create_check_constraint(
        "execution_event_type", "execution_event", f"event_type IN ({allowed})"
    )


def upgrade() -> None:
    _constraint((*_OLD, "node.recovered"))


def downgrade() -> None:
    # Never rewrite append-only audit history to fit an older event vocabulary.
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM execution_event WHERE event_type='node.recovered')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("cannot downgrade recovery events while their audit records exist")
    _constraint(_OLD)
