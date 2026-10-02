"""derived turn submissions

Revision ID: c937a6b69e8a
Revises: b9c5e4829868
Create Date: 2026-09-20 14:00:00.000000+00:00

Spec 2026-09-20 (derived design turns) §2.1: a submission the server made from a user's own
message bytes says so. ``derivation`` names the kind (the out-of-scope redelivery that always
existed, and the design leg's first turn), ``derived_from_turn_id`` names the turn whose bytes it
carries. Both or neither. Readers use the columns to append no second user row and render no
second user bubble.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c937a6b69e8a"
down_revision: str | None = "b9c5e4829868"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_turn_submission
            ADD COLUMN derivation text NULL,
            ADD COLUMN derived_from_turn_id uuid NULL,
            ADD CONSTRAINT agent_turn_submission_derivation_kind
                CHECK (derivation IS NULL
                       OR derivation IN ('design_leg_redelivery', 'design_leg_first_turn')),
            ADD CONSTRAINT agent_turn_submission_derivation_pair
                CHECK ((derivation IS NULL) = (derived_from_turn_id IS NULL))
        """
    )
    op.execute(
        "COMMENT ON COLUMN agent_turn_submission.derivation IS 'Set when the server made this "
        "submission from a user''s own message bytes: design_leg_redelivery (an out-of-scope "
        "leg close re-delivering the message to head-of-abm) or design_leg_first_turn (the "
        "design leg''s first turn, queued by open_design_leg). NULL for a human submission.'"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_turn_submission
            DROP CONSTRAINT agent_turn_submission_derivation_pair,
            DROP CONSTRAINT agent_turn_submission_derivation_kind,
            DROP COLUMN derived_from_turn_id,
            DROP COLUMN derivation
        """
    )
