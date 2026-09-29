"""drop the insights contact-insights section

Revision ID: 5e1c0a9d7b24
Revises: d9f29ca9ca66
Create Date: 2026-09-29 10:00:00.000000+00:00

Founder ruling 2026-09-29: the insights page no longer carries a Contact insights section (each
person's insights live on their contact page). The recipe leaves ``SYSTEM_RECIPES``; the seeder only
upserts, so the stored system row is deleted here, and Context only / Miscellaneous move up one
position to match. The downgrade restores the row as the 2026-09-21 shared recipe.

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
revision: str = "5e1c0a9d7b24"
down_revision: str | None = "d9f29ca9ca66"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM display_section_recipe WHERE page = 'insights' "
        "AND section_key = 'contact-insights' AND workspace_id = ''"
    )
    op.execute(
        """
        UPDATE display_section_recipe
        SET position = CASE section_key WHEN 'context-only' THEN 4 ELSE 5 END
        WHERE page = 'insights' AND workspace_id = ''
          AND section_key IN ('context-only', 'miscellaneous')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE display_section_recipe
        SET position = CASE section_key WHEN 'context-only' THEN 5 ELSE 6 END
        WHERE page = 'insights' AND workspace_id = ''
          AND section_key IN ('context-only', 'miscellaneous')
        """
    )
    op.execute(
        """
        INSERT INTO display_section_recipe
            (page, section_key, workspace_id, h1, position, allowed_field_keys,
             restricted, default_open, instruction_version,
             shared_from_page, shared_from_section_key)
        SELECT 'insights', 'contact-insights', '', 'Contact insights', 4,
               ARRAY['contact.persona', 'contact.current_title', 'contact.facet.recent_post',
                     'contact.facet.publications', 'contact.facet.voice_quote',
                     'contact.facet.certifications', 'contact.facet.career_history'],
               false, false, instruction_version, 'contact', 'why-this-person'
        FROM display_section_recipe
        WHERE page = 'insights' AND section_key = 'context-only' AND workspace_id = ''
        ON CONFLICT DO NOTHING
        """
    )
