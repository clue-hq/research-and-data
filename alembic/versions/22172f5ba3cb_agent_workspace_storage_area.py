"""agent workspace storage area

Revision ID: 22172f5ba3cb
Revises: 01baa2e73e84
Create Date: 2026-10-23 10:00:00.000000+00:00

F3 Phase 2 (docs/superpowers/specs/agent-workspace/, WS-30/AW-26; plan
docs/superpowers/plans/2026-10-23-agent-workspace-phase-2-retention.md, Task 1).

A chat's agent-workspace files get their own key namespace,
``{workspace_id|public}/agent-workspace/{sha256}``, written by
``clue_storage.agent_workspace_key``. Phase 2 expires those files by age, and the areas are what
decide what an expiry can reach: in the bare ``{workspace}/{sha}`` namespace the chat's copy of a
file would dedup onto the *same row* as an evidence snapshot, an upload or a Gallery artifact of
identical bytes, so deleting the chat's copy would delete somebody else's blob. A separate area
makes that unrepresentable instead of a refcount to get right — the same reason design bytes got
``{workspace}/design/{sha}`` in ``13cd5078d697`` (ruling R-D4-2).

So ``artifact_key_encodes_scope`` (B2, ``d0c2e361f7d4``; widened once already for design) must
admit a third shape. The invariant it exists to enforce is unchanged: the key still *encodes* its
scope — the leading segment is still the row's workspace and the trailing segment is still the
row's content hash — a row may simply now name one more namespace it is in. All three shapes stay
unforgeable; nothing else relaxes.

Hand-written and reversible. The downgrade refuses while any agent-workspace row exists (correct:
those keys are not representable in the two-shape constraint), and otherwise restores it exactly.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "22172f5ba3cb"
down_revision: str | None = "01baa2e73e84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE = "COALESCE(workspace_id, 'public')"


def upgrade() -> None:
    op.execute("ALTER TABLE artifact DROP CONSTRAINT artifact_key_encodes_scope")
    op.execute(
        "ALTER TABLE artifact ADD CONSTRAINT artifact_key_encodes_scope CHECK ("
        f"storage_key = {_SCOPE} || '/' || content_sha256"
        f" OR storage_key = {_SCOPE} || '/design/' || content_sha256"
        f" OR storage_key = {_SCOPE} || '/agent-workspace/' || content_sha256)"
    )


def downgrade() -> None:
    rows = op.get_bind().exec_driver_sql(
        "SELECT 1 FROM artifact WHERE storage_key LIKE '%/agent-workspace/%' LIMIT 1"
    )
    if rows.first() is not None:
        raise RuntimeError(
            "artifact rows in the agent-workspace area exist; their keys cannot be represented "
            "by the two-shape artifact_key_encodes_scope constraint. Expire or erase them "
            "(F3 Phase 2 retention) before downgrading."
        )
    op.execute("ALTER TABLE artifact DROP CONSTRAINT artifact_key_encodes_scope")
    op.execute(
        "ALTER TABLE artifact ADD CONSTRAINT artifact_key_encodes_scope CHECK ("
        f"storage_key = {_SCOPE} || '/' || content_sha256"
        f" OR storage_key = {_SCOPE} || '/design/' || content_sha256)"
    )
