"""ARV2 Track O (O4) — admit the ``persona`` onboarding step kind.

The synthesis split turns one synthesis turn into one ICP turn plus one persona turn per ICP, so
an onboarding run now carries a ``persona`` step per ICP, separated by ``subject_ref`` (the
``onboarding_step_identity`` index already keys on ``(run_id, kind, COALESCE(subject_ref, ''))``,
so repeating the kind within a run needs no index change).

Downgrade restores the prior six-kind vocabulary and FAILS LOUDLY if any ``persona`` step already
exists — the same shape as ``000b9d8bb17b``, per house convention.

Revision ID: ae4a5dfb3943
Revises: a3602967bb73
Create Date: 2026-09-08 11:45:35.344277+00:00

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
revision: str = "ae4a5dfb3943"
down_revision: str | None = "a3602967bb73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KINDS = "('overview', 'lineup', 'catalog_sync', 'reviews', 'synthesis', 'product_research')"
_NEW_KINDS = (
    "('overview', 'lineup', 'catalog_sync', 'reviews', 'synthesis', 'product_research', 'persona')"
)


def _install(kinds: str) -> None:
    op.execute("ALTER TABLE onboarding_step DROP CONSTRAINT onboarding_step_kind")
    op.execute(
        f"ALTER TABLE onboarding_step ADD CONSTRAINT onboarding_step_kind CHECK (kind IN {kinds})"
    )


def upgrade() -> None:
    _install(_NEW_KINDS)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM onboarding_step WHERE kind = 'persona') THEN
                RAISE EXCEPTION 'cannot downgrade O4 while persona onboarding steps exist';
            END IF;
        END $$
        """
    )
    _install(_OLD_KINDS)
