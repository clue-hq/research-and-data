"""d5 fleet design job kind

Revision ID: be855c8f6993
Revises: 13cd5078d697
Create Date: 2026-08-09

Part II slice D5 (durable execution), migration 1 of 2 — the one platform-table touch of the
slice: ``fleet_task_kind`` gains ``design_job``.

Design agent turns and brand-kit ingestion jobs move onto the platform fleet (leases, supervised
heartbeats, takeover) per the master plan, which is what closes the two known restart holes: a
daemon-thread turn and a ``BackgroundTasks`` ingestion are both stranded forever by a process
restart today.

**ONE mechanical kind, not three** — the ``entity_research_job`` precedent (M8D R2, migration
``022b1154b3aa``), where account and contact research share a single kind and the exact subject
authority lives in the immutable job envelope. Here the envelope (``design_agent_run.payload`` /
``design_ingestion_job.request_json``, frozen by-value at enqueue) discriminates
``agent_turn`` / ``web_turn`` / ``ingestion``. Adding a fleet kind per design shape would fork
the queue taxonomy for what is, to the fleet, the same mechanical unit of work.

Reversibility follows the R2 precedent exactly: PostgreSQL cannot drop an enum label, so
``downgrade()`` refuses while any ``design_job`` task exists and otherwise rebuilds the type
without the label (rename → CREATE → ALTER COLUMN … USING → DROP). ``ADD VALUE`` is safe inside
alembic's transaction because this migration never *uses* the new label (PG16 forbids only the
use, not the addition).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "be855c8f6993"
down_revision: str | None = "13cd5078d697"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The label set BEFORE this migration — what ``downgrade()`` restores. Mirrors
#: ``clue_fleet.enums.FleetTaskKind`` minus ``DESIGN_JOB``.
_KINDS_BEFORE = ("drive_run", "account_job", "execute_graph", "entity_research_job")


def upgrade() -> None:
    op.execute("ALTER TYPE fleet_task_kind ADD VALUE IF NOT EXISTS 'design_job'")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fleet_task WHERE kind::text = 'design_job') THEN
                RAISE EXCEPTION
                    'cannot downgrade PD D5 while design_job fleet tasks exist';
            END IF;
        END $$
        """
    )
    labels = ", ".join(f"'{k}'" for k in _KINDS_BEFORE)
    op.execute("ALTER TYPE fleet_task_kind RENAME TO fleet_task_kind_pd_d5")
    op.execute(f"CREATE TYPE fleet_task_kind AS ENUM ({labels})")
    op.execute(
        """
        ALTER TABLE fleet_task
        ALTER COLUMN kind TYPE fleet_task_kind
        USING kind::text::fleet_task_kind
        """
    )
    op.execute("DROP TYPE fleet_task_kind_pd_d5")
