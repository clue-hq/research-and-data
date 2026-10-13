"""fleet maintenance clock and artifact privacy-purge index (2026-10-09)

``maintenance_run`` keeps when a fleet-wide maintenance job last ran, one row per job. The storage
sweep (purge erased artifacts, then orphan blobs) used to run every 6 h in EVERY fleet worker
process on a timer that lived in the process — about twenty passes a day across production's five
worker containers, and a timer every deploy reset. Now each process checks this row hourly and the
fleet sweeps once per interval (default 48 h), under an advisory lock, so one process sweeps and a
restart never resets the clock (``clue_api.storage_wiring.run_orphan_blob_sweep_if_due``).

``artifact_privacy_purged`` lets that sweep's write-back re-delete find the rows privacy-purged
since its last run without reading the whole ``artifact`` table (review N-2). It is built
``CONCURRENTLY`` in Alembic's autocommit block so a deploy never blocks artifact writes; an
interrupted build leaves an INVALID index, so the upgrade drops one of this name first (as
``702784fe02b7`` does, with the same caveat for a multi-step downgrade that fails later on).

Revision ID: 349779801104
Revises: 702784fe02b7
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "349779801104"
down_revision: str | None = "702784fe02b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE maintenance_run (
            name text CONSTRAINT maintenance_run_pkey PRIMARY KEY,
            last_run_at timestamptz NOT NULL
        )
        """
    )
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS artifact_privacy_purged")
        op.execute(
            "CREATE INDEX CONCURRENTLY artifact_privacy_purged ON artifact (purged_at) "
            "WHERE privacy_erased"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS artifact_privacy_purged")
    op.execute("DROP TABLE maintenance_run")
