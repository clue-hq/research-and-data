"""ARV2 Track O (O4) — admit the ``onboarding_synthesis`` agent role.

Widens the three agent-role CHECKs (``agent_turn_role``, ``agent_plan_role``,
``agent_delegation_roles``) to admit ``'onboarding_synthesis'`` — the brand-level onboarding
synthesis agent that writes the ICP and persona documents from the onboarding research
documents. Same coordinated-role-vocabulary shape as ``549de68ae3b9`` (which admitted
``'design'``), per the C8 §8 precedent.

Downgrade restores the prior six-role vocabulary and FAILS LOUDLY if any
``onboarding_synthesis`` turn already exists — deliberate, per house convention.

Revision ID: 000b9d8bb17b
Revises: 3742d1281a10
Create Date: 2026-09-07 18:05:38.212568+00:00

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
revision: str = "000b9d8bb17b"
down_revision: str | None = "3742d1281a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_CHECKS = (
    # (table, constraint, column expression rebuilt on upgrade/downgrade)
    ("agent_turn", "agent_turn_role", "role"),
    ("agent_plan", "agent_plan_role", "role"),
)
_OLD_ROLES = (
    "('head_of_abm', 'research', 'content_drafter', 'reviewer', 'account_research', 'design')"
)
_NEW_ROLES = (
    "('head_of_abm', 'research', 'content_drafter', 'reviewer', 'account_research', 'design', "
    "'onboarding_synthesis')"
)


def _install(roles: str) -> None:
    for table, constraint, column in _ROLE_CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK ({column} IN {roles})")
    op.execute("ALTER TABLE agent_delegation DROP CONSTRAINT agent_delegation_roles")
    op.execute(
        "ALTER TABLE agent_delegation ADD CONSTRAINT agent_delegation_roles CHECK ("
        f"    parent_role IN {roles}"
        f"    AND child_role IN {roles}"
        "    AND parent_role <> child_role"
        ")"
    )


def upgrade() -> None:
    _install(_NEW_ROLES)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM agent_turn WHERE role = 'onboarding_synthesis') THEN
                RAISE EXCEPTION 'cannot downgrade O4 while onboarding_synthesis turns exist';
            END IF;
        END $$
        """
    )
    _install(_OLD_ROLES)
