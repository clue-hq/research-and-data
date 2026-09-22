"""record research specialist model calls

Revision ID: c237eb027732
Revises: f4b30cb3d088
Create Date: 2026-09-22 19:08:00.964122+00:00

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
revision: str = "c237eb027732"
down_revision: str | None = "f4b30cb3d088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD = (
    "'head_of_abm','research','content_drafter','reviewer','account_research',"
    "'design','onboarding_synthesis'"
)
_NEW = _OLD + ",'research_claims','research_narrative'"


def _install(roles: str) -> None:
    op.execute("ALTER TABLE agent_model_call DROP CONSTRAINT agent_model_call_role")
    op.execute(
        "ALTER TABLE agent_model_call ADD CONSTRAINT agent_model_call_role "
        f"CHECK (role IS NULL OR role IN ({roles}))"
    )


def upgrade() -> None:
    _install(_NEW)


def downgrade() -> None:
    # Restoring the vocabulary refuses existing new-role rows rather than deleting telemetry.
    _install(_OLD)
