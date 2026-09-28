"""display recipe shared_from

Revision ID: 2b702a116c15
Revises: fd8795c4fd5a
Create Date: 2026-09-21 19:44:06.095083+00:00

Spec 2026-09-12 §3. Two nullable columns name the owner of a shared section. The two sections that
become shared (insights context-only ← overview watch-outs; insights contact-insights ← the contact
page's why-this-person) stop owning blocks, so their own live blocks are retired here — the
composed page reads the owner's block from now on, and a retired block is audit, never served.

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
revision: str = "2b702a116c15"
down_revision: str | None = "fd8795c4fd5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE display_section_recipe ADD COLUMN shared_from_page text")
    op.execute("ALTER TABLE display_section_recipe ADD COLUMN shared_from_section_key text")
    op.execute(
        """
        ALTER TABLE display_section_recipe ADD CONSTRAINT display_section_recipe_shared_from_pair
        CHECK ((shared_from_page IS NULL) = (shared_from_section_key IS NULL))
        """
    )
    op.execute(
        """
        UPDATE display_block SET superseded_at = now()
        WHERE page = 'insights' AND section_key IN ('context-only', 'contact-insights')
          AND superseded_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE display_section_recipe DROP CONSTRAINT display_section_recipe_shared_from_pair"
    )
    op.execute("ALTER TABLE display_section_recipe DROP COLUMN shared_from_section_key")
    op.execute("ALTER TABLE display_section_recipe DROP COLUMN shared_from_page")
    # The retired blocks stay retired: the next read of an insights page writes the two sections
    # afresh under the pre-share recipes.
