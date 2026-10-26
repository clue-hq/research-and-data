"""stream_token: the ``agent_thread`` subject, for a chat thread's live stream

Revision ID: 8c3e73eb83b2
Revises: 3b800d603402
Create Date: 2026-10-21 15:22:13.534018+00:00

CRM trial 1, finding F2 (ruling R-10.1): an open chat follows every turn of its thread through one
thread-level stream, opened with a single-use token whose subject is ``('agent_thread',
<thread id>)``. The subject vocabulary CHECK (``stream_token_subject_kind_known``, D7) learns the
new kind; the coherence CHECK already admits any non-``project_run`` kind with a subject id.

The downgrade deletes the ``agent_thread`` tokens before restoring the two-kind CHECK. They are
short-lived and single-use, so deleting them only closes streams that were about to open.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c3e73eb83b2"
down_revision: str | None = "3b800d603402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROP = "ALTER TABLE stream_token DROP CONSTRAINT stream_token_subject_kind_known"


def _add(kinds: str) -> str:
    return (
        "ALTER TABLE stream_token ADD CONSTRAINT stream_token_subject_kind_known "
        f"CHECK (subject_kind IS NULL OR subject_kind IN ({kinds}))"
    )


def upgrade() -> None:
    op.execute(_DROP)
    op.execute(_add("'project_run', 'design_run', 'agent_thread'"))


def downgrade() -> None:
    op.execute("DELETE FROM stream_token WHERE subject_kind = 'agent_thread'")
    op.execute(_DROP)
    op.execute(_add("'project_run', 'design_run'"))
