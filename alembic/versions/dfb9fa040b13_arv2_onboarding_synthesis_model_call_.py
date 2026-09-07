"""ARV2 Track O (O4) — admit ``onboarding_synthesis`` on the model-call ledger too.

``000b9d8bb17b`` widened three of the four agent-role vocabularies (``agent_turn_role``,
``agent_plan_role``, ``agent_delegation_roles``) but not the fourth: ``agent_model_call_role``,
added later by the P3.2 attribution migration (``65880921cd52``) and therefore absent from the
role-vocabulary list every earlier widening used. Every governed turn stamps one
``agent_model_call`` row per model round, so the omission made a synthesis turn fail at its FIRST
model call with ``agent_model_call_role`` — found live by the O4 turn-runner acceptance test.

Same coordinated shape as its predecessors: drop and rebuild the CHECK with the full vocabulary.
The column stays nullable (historical rows predate attribution and remain honestly NULL).

Downgrade restores the prior six-role vocabulary and FAILS LOUDLY if any ``onboarding_synthesis``
model call already exists — deliberate, per house convention.

Revision ID: dfb9fa040b13
Revises: 000b9d8bb17b
Create Date: 2026-09-08

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3):
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up -> down -> up).
- Named CHECKs; enums mirror ``core.enums``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dfb9fa040b13"
down_revision: str | None = "000b9d8bb17b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_ROLES = (
    "('head_of_abm', 'research', 'content_drafter', 'reviewer', 'account_research', 'design')"
)
_NEW_ROLES = (
    "('head_of_abm', 'research', 'content_drafter', 'reviewer', 'account_research', 'design', "
    "'onboarding_synthesis')"
)


def _install(roles: str) -> None:
    op.execute("ALTER TABLE agent_model_call DROP CONSTRAINT agent_model_call_role")
    op.execute(
        "ALTER TABLE agent_model_call ADD CONSTRAINT agent_model_call_role CHECK ("
        f"role IS NULL OR role IN {roles})"
    )


def upgrade() -> None:
    _install(_NEW_ROLES)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM agent_model_call WHERE role = 'onboarding_synthesis') THEN
                RAISE EXCEPTION
                    'cannot downgrade O4 while onboarding_synthesis model calls exist';
            END IF;
        END $$
        """
    )
    _install(_OLD_ROLES)
