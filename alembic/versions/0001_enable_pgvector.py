"""enable pgvector

Revision ID: 0001
Revises:
Create Date: 2026-06-18

The initial migration. It does exactly one thing — enable the ``vector`` (pgvector) extension,
the substrate for identity-resolution candidate sets and client-knowledge retrieval (substrate §2,
§8, §12). It creates **no domain tables**: ``claim``, ``account_entity``, ``field_definition``,
``source_manifest``, and the campaign-run/state tables are defined by M1+ migrations and must
conform to the conventions checklist in ``src/clue_research/db/README.md``.

``CREATE EXTENSION IF NOT EXISTS`` is idempotent, so re-running ``upgrade`` on a database that
already has the extension is a no-op. ``downgrade`` drops it, so CI's up → down → up smoke leaves a
consistent schema (docs/specs/M00-foundations-and-shared-contracts.md §M0.3).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
