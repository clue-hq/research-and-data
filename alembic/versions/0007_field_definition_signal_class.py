"""field_definition.signal_class — the two-tier signal link (M3.2 / ENG-109)

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-19

Doc C §1: a single signal class spans both passes — a cheap ``scoring`` proxy and a ``deep``
narrative (e.g. intent = a job-count-delta proxy + a "why in-market" narrative). The compiler
(M3.2) links the two by a shared ``signal_class`` so Pass A and Pass B stay coherent.

This **extends** (does not redefine) the M1.3 ``field_definition`` registry with one nullable text
column the compiler reads (conventions §4 — extend, not redefine). The merge / source layers ignore
it; only the compiler groups by it.

NOTE (integration): the parallel M2 identity worktree also adds migrations from 0005; merging the
branches will require renumbering this chain. Kept sequential within this branch.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE field_definition ADD COLUMN signal_class text")
    op.execute(
        "COMMENT ON COLUMN field_definition.signal_class IS 'Two-tier signal link (Doc C §1): "
        "fields sharing a signal_class are the scoring proxy and deep narrative of one signal.'"
    )
    # The compiler groups by signal_class; index the populated rows for that read path.
    op.execute(
        "CREATE INDEX field_definition_signal_class ON field_definition (signal_class) "
        "WHERE signal_class IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS field_definition_signal_class")
    op.execute("ALTER TABLE field_definition DROP COLUMN IF EXISTS signal_class")
