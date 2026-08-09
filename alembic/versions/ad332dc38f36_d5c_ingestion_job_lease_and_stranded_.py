"""d5c ingestion job lease and stranded reoffer

Revision ID: ad332dc38f36
Revises: 50b84c524fa2
Create Date: 2026-08-09

Part II slice D5 Round C — two closely-related shapes, one migration because neither is useful
without the other.

**1. ``design_ingestion_job`` gets the same lease trio ``design_agent_run`` got in
``50b84c524fa2``** (``leased_by`` / ``lease_generation`` / ``leased_at``, nullable, all-or-nothing
CHECK, ``generation >= 1`` CHECK). Round C moves brand-kit ingestion off FastAPI
``BackgroundTasks`` and onto the ``design_job`` fleet queue, so a job is now claimed by a leased
worker exactly as a turn is — and a claim that cannot express a generation cannot express
takeover: it could not tell "the previous holder died and I hold a newer lease" from "another
live worker owns this right now". The columns are the design plane's own record of who is
driving; the authoritative fence stays the platform ``work_lease`` row (Rule F1).

**2. Both tables get ``reoffer_count smallint NOT NULL DEFAULT 0``** — the stranded-work reaper's
bounded-retry counter. A handler that dies *between* claiming a run/job and terminalizing it (a
store fault, not a failed turn) leaves the design row ``running`` while the fleet marks its task
FAILED, and nothing re-offers it: the row is stranded forever. The Round C reaper re-offers such a
row exactly ONCE (``running`` → ``queued``, lease cleared, ``reoffer_count`` incremented) and
terminalizes it ``failed`` with a ``stranded`` error code on the second sighting. The counter has
to be durable — a process-local memory of "I already retried this" dies with the process that had
the memory, which is the very failure being repaired. ``smallint`` because the policy ceiling is
1; the CHECK keeps it non-negative rather than pretending it is a general attempt counter.

No enum type changes: ``design_ingestion_status`` already carries ``queued``, and a reaper's
re-offer moves a row back to a label that has always existed.

Hand-written and reversible: ``downgrade()`` mirrors ``upgrade()`` exactly (CI runs up → down →
up). Dropping a nullable observability column and a defaulted counter destroys no domain state, so
downgrade needs no refusal guard (unlike ``50b84c524fa2``, which had to protect the ``queued``
enum label it introduced).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ad332dc38f36"
down_revision: str | None = "50b84c524fa2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REOFFER_COMMENT = (
    "Stranded-work reaper's bounded-retry counter (PD D5 Round C). 0 = never re-offered; the "
    "reaper re-offers a stranded row exactly once (incrementing this) and terminalizes it "
    "'failed' with a stranded error code the second time it sees it."
)


def _literal(text: str) -> str:
    """A SQL string literal (single quotes doubled)."""
    doubled = text.replace("'", "''")
    return f"'{doubled}'"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE design_ingestion_job
        ADD COLUMN leased_by        text,
        ADD COLUMN lease_generation bigint,
        ADD COLUMN leased_at        timestamptz,
        ADD COLUMN reoffer_count    smallint NOT NULL DEFAULT 0,
        ADD CONSTRAINT design_ingestion_job_lease_generation_positive
            CHECK (lease_generation IS NULL OR lease_generation >= 1),
        ADD CONSTRAINT design_ingestion_job_lease_shape CHECK (
            (leased_by IS NULL AND lease_generation IS NULL AND leased_at IS NULL) OR
            (leased_by IS NOT NULL AND lease_generation IS NOT NULL AND leased_at IS NOT NULL)
        ),
        ADD CONSTRAINT design_ingestion_job_reoffer_count_nonnegative
            CHECK (reoffer_count >= 0)
        """
    )
    for column, comment in (
        (
            "leased_by",
            "Observability: worker id that last claimed this ingestion job. The authoritative "
            "fence is the platform work_lease row; design code never reads the queue.",
        ),
        (
            "lease_generation",
            "Observability: lease generation under which the job was claimed. Also the "
            "compare-and-set key of claim_job_for_execution (takeover requires a HIGHER "
            "generation) and of the fenced terminal writes.",
        ),
        ("leased_at", "Observability: when the current lease holder claimed the job."),
        ("reoffer_count", _REOFFER_COMMENT),
    ):
        op.execute(f"COMMENT ON COLUMN design_ingestion_job.{column} IS {_literal(comment)}")

    op.execute(
        """
        ALTER TABLE design_agent_run
        ADD COLUMN reoffer_count smallint NOT NULL DEFAULT 0,
        ADD CONSTRAINT design_agent_run_reoffer_count_nonnegative
            CHECK (reoffer_count >= 0)
        """
    )
    op.execute(f"COMMENT ON COLUMN design_agent_run.reoffer_count IS {_literal(_REOFFER_COMMENT)}")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE design_agent_run
        DROP CONSTRAINT design_agent_run_reoffer_count_nonnegative,
        DROP COLUMN reoffer_count
        """
    )
    op.execute(
        """
        ALTER TABLE design_ingestion_job
        DROP CONSTRAINT design_ingestion_job_reoffer_count_nonnegative,
        DROP CONSTRAINT design_ingestion_job_lease_shape,
        DROP CONSTRAINT design_ingestion_job_lease_generation_positive,
        DROP COLUMN reoffer_count,
        DROP COLUMN leased_at,
        DROP COLUMN lease_generation,
        DROP COLUMN leased_by
        """
    )
