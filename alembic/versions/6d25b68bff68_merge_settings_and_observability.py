"""merge settings and observability

Revision ID: 6d25b68bff68
Revises: 27aa2ae947bc, b7193eb28363
Create Date: 2026-09-16 05:43:52.523942+00:00

Join the Settings identity changes and research-streaming's observability changes without
rewriting either migration's ancestry. This revision makes no schema or data changes itself.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "6d25b68bff68"
down_revision: str | Sequence[str] | None = ("27aa2ae947bc", "b7193eb28363")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
