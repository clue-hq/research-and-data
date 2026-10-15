"""arv2 recovery lookup indexes (W2-17 of the research cost/speed audit, 2026-10-08)

``recover_acquisitions`` (``clue_api.arv2.quality_acquisition.RECOVERY_QUERY``) runs after every
evidence call and asks for one job's settled ledger results that have no evidence source yet. With
no index on ``provider_call_ledger.entity_research_job_id`` and none on
``arv2_evidence_source.ledger_id``, Postgres read both tables whole on every call, so the check grew
with every research run ever stored: measured on a scaled copy of a lane database, about 1 ms at
one run, 49 ms at 100 runs and 96 ms at 300 runs — and it runs under the worker-wide database lock,
so every other job on that worker waits behind it. With these two indexes it is 0.3 ms at 300 runs.

Built ``CONCURRENTLY`` inside Alembic's autocommit block, so a production deploy never blocks
ledger or evidence writes while the indexes build (the ledger takes a row for every provider call).
``CONCURRENTLY`` cannot run in a transaction, which is why the block commits first. If a concurrent
build is interrupted it leaves an INVALID index behind; ``IF NOT EXISTS`` would then skip it, so
the upgrade drops any index of the same name before building — an index only this migration makes.

One consequence of committing outside Alembic's transaction: in a multi-step downgrade that fails
at a LATER step, the index drop here has already committed while the version row rolls back to
this revision, so ``upgrade head`` then does nothing and the indexes stay missing. That costs speed,
not correctness; ``alembic downgrade 4a94970221e9 && alembic upgrade head`` restores them.

Revision ID: 702784fe02b7
Revises: 4a94970221e9
Create Date: 2026-10-08 12:57:54.577284+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "702784fe02b7"
down_revision: str | None = "4a94970221e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    (
        "provider_call_ledger_job",
        "provider_call_ledger (entity_research_job_id) WHERE phase = 'result'",
    ),
    ("arv2_evidence_source_ledger", "arv2_evidence_source (workspace_id, ledger_id)"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, target in _INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            op.execute(f"CREATE INDEX CONCURRENTLY {name} ON {target}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _ in _INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
