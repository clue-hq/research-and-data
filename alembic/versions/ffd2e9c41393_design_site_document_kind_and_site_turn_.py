"""design site document kind (Puck) and site_turn run kind.

Revision ID: ffd2e9c41393
Revises: 10edab6dd974
Create Date: 2026-10-09 10:05:09.859051+00:00

Rebuilds both enums (PostgreSQL cannot drop a label, so a rebuild keeps the change reversible),
the pattern of 50b84c524fa2 `_rebuild_run_status`. Each enum has exactly one column.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "ffd2e9c41393"
down_revision: str | None = "10edab6dd974"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror clue_design.enums (parity-tested in tests/design/test_design_schema_db.py).
_DOC_KIND_AFTER = ("scene", "web", "site")
_DOC_KIND_BEFORE = ("scene", "web")
_RUN_KIND_AFTER = ("agent_turn", "web_turn", "site_turn")
_RUN_KIND_BEFORE = ("agent_turn", "web_turn")


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _rebuild(
    type_name: str,
    table: str,
    column: str,
    values: tuple[str, ...],
    default: str | None = None,
) -> None:
    op.execute(f"ALTER TYPE {type_name} RENAME TO {type_name}_prev")
    op.execute(f"CREATE TYPE {type_name} AS ENUM ({_values(values)})")
    if default is not None:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {type_name}"
        f" USING {column}::text::{type_name}"
    )
    if default is not None:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}'")
    op.execute(f"DROP TYPE {type_name}_prev")


def upgrade() -> None:
    _rebuild("design_doc_kind", "design_document", "doc_kind", _DOC_KIND_AFTER, default="scene")
    _rebuild("design_run_kind", "design_agent_run", "kind", _RUN_KIND_AFTER)


def downgrade() -> None:
    bind = op.get_bind()
    sites = bind.execute(
        text("SELECT count(*) FROM design_document WHERE doc_kind = 'site'")
    ).scalar()
    turns = bind.execute(
        text("SELECT count(*) FROM design_agent_run WHERE kind = 'site_turn'")
    ).scalar()
    if sites or turns:
        raise RuntimeError(
            f"cannot downgrade: {sites} site documents and {turns} site_turn runs exist"
        )
    _rebuild("design_run_kind", "design_agent_run", "kind", _RUN_KIND_BEFORE)
    _rebuild("design_doc_kind", "design_document", "doc_kind", _DOC_KIND_BEFORE, default="scene")
