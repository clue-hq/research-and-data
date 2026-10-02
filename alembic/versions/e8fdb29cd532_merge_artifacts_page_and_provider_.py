"""merge: artifacts page (design_document_user_mark) + provider incidents

Revision ID: e8fdb29cd532
Revises: 323081354b51, 89791cb5949e
Create Date: 2026-09-16

Two parallel branches each chained a migration off ``b7193eb28363``: the artifacts-page lane
(``5f2bd1b4b82d`` → ``323081354b51``, the library's archive state and per-user marks) and the
provider-incidents lane (``89791cb5949e``, the ``provider_incident`` table). This is the join
revision the migration convention asks for (``alembic merge``, never a hand-renumber): no schema
change of its own, both sub-chains preserved, one head again.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "e8fdb29cd532"
down_revision: str | Sequence[str] | None = ("323081354b51", "89791cb5949e")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
