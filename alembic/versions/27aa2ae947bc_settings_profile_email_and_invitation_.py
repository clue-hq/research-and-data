"""settings profile email and invitation provider id

Revision ID: 27aa2ae947bc
Revises: d36bc7d32c9a
Create Date: 2026-09-14 19:09:54.748751+00:00

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "27aa2ae947bc"
down_revision: str | None = "d36bc7d32c9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE platform_user ADD COLUMN email text")
    op.execute(
        "CREATE INDEX platform_user_email_lower_idx ON platform_user (lower(email)) "
        "WHERE email IS NOT NULL"
    )
    op.execute("ALTER TABLE workspace_invitation ADD COLUMN provider_invitation_id text")


def downgrade() -> None:
    op.execute("ALTER TABLE workspace_invitation DROP COLUMN provider_invitation_id")
    op.execute("DROP INDEX platform_user_email_lower_idx")
    op.execute("ALTER TABLE platform_user DROP COLUMN email")
