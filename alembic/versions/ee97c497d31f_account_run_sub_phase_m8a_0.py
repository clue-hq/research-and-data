"""account_run sub_phase (M8A.0)

Revision ID: ee97c497d31f
Revises: 089dc65b5814
Create Date: 2026-06-22 19:42:48.997140+00:00

The per-account deep-orchestration sub-phase marker (M8A.0) — the *last completed* boundary of the
``account → committee → contact`` deep sequence (M8A.1), so a crashed account run resumes at its
last boundary instead of re-discovering the committee or re-profiling the account. Additive and
nullable:
``NULL`` = the sequence has not started (every existing ``account_run`` row reads ``NULL``), then it
advances monotonically ``account_profiled → committee_discovered → contacts_complete``.

The ``account_run.status`` lifecycle (the coarse pending→running→done enum) is **untouched**: this
is an orthogonal *sub*-granularity, not a status change.

Enum ``account_run_sub_phase`` is a **durable-internal** lifecycle enum (Beat-0: M8A/M7 own it; it
is NOT in ``core.enums``, mirroring ``account_run_status`` in 79d56a0f4425). It is mirrored from
:class:`clue_research.durable.enums.AccountRunSubPhase`; the parity test
``tests/durable/test_account_run_db.py::test_account_run_sub_phase_enum_matches_db`` guards against
drift.

This is the one migration M8A adds (the M8 parallel worktrees were "no migrations"; M8A is the
integration milestone where one additive, durable-owned migration is expected). It chains off the
origin/main head ``089dc65b5814`` — parallel to the in-flight ``c74c23defd01`` (M9.1 Option-C gate)
which also chains off ``089dc65b5814``; when both land, ``alembic merge`` joins the two heads (the
adopted parallel-branch convention). ``downgrade()`` cleanly reverses ``upgrade()`` (CI runs up →
down → up on a clean DB).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ee97c497d31f"
down_revision: str | None = "089dc65b5814"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_research.durable.enums.AccountRunSubPhase (durable-internal; not a core enum). The
# labels here ARE the StrEnum ``.value``s — the parity test asserts the PG enum labels equal these.
_ACCOUNT_RUN_SUB_PHASE = (
    "account_profiled",
    "committee_discovered",
    "contacts_complete",
)


def _enum_values_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(
        f"CREATE TYPE account_run_sub_phase AS ENUM ({_enum_values_sql(_ACCOUNT_RUN_SUB_PHASE)})"
    )
    # Additive + nullable: NULL = the deep sequence has not started; advances monotonically. No
    # default — an unstarted run is honestly NULL, not a synthetic first stage.
    op.execute("ALTER TABLE account_run ADD COLUMN sub_phase account_run_sub_phase NULL")
    op.execute(
        "COMMENT ON COLUMN account_run.sub_phase IS 'Last-completed deep-orchestration boundary "
        "(M8A.0): NULL=not started, then account_profiled -> committee_discovered -> "
        "contacts_complete. Advisory resume marker; the M7.4 ledger is authoritative for spend.'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE account_run DROP COLUMN IF EXISTS sub_phase")
    op.execute("DROP TYPE IF EXISTS account_run_sub_phase")
