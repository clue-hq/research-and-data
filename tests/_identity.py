"""Shared test helper: the Lane B identity rows a durable human owner now requires.

FI Lane D's B1-join migration (``c4ccc7b11810``) turned ``agent_thread.created_by_user_id`` /
``created_via_membership_id`` and ``agent_turn.submitted_by_user_id`` /
``submitted_via_membership_id`` into real foreign keys onto ``platform_user`` and
``workspace_membership``. A suite that writes one of those ownership values must therefore write
the identity behind it first — an invented ``usr_…`` string is now a database error, which is the
whole point of the join.

This is the single seeding helper every suite imports (DRY, exactly like ``tests/_workspace.py``
for workspaces/projects). It is idempotent and it goes through ``clue_auth``'s own CRUD, so a test
fixture can never drift from Lane B's row shape or lifecycle. NULL ownership needs nothing from
here: a platform-originated thread or turn has no human owner and passes the foreign keys by
being absent, which is the honest representation Lane B ruling 8 requires.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_auth import (
    create_platform_user,
    create_workspace_membership,
    get_auth_identity,
    get_platform_user,
    get_workspace_membership,
    link_auth_identity,
)
from tests._workspace import seed_workspace

#: The provider mapping a seeded fixture is filed under. Not a real provider and not the local-dev
#: one: nothing authenticates against it, it only gives the fixture production's row *shape*.
TEST_PROVIDER_KEY = "clue_test_fixture"


@dataclass(frozen=True, slots=True)
class SeededPrincipal:
    """The internal ids a seeded fixture identity owns."""

    user_id: str
    membership_id: str
    workspace_id: str
    role_key: str


async def seed_principal(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    user_id: str,
    membership_id: str | None = None,
    role_key: str = "owner",
) -> SeededPrincipal:
    """Ensure ``user_id`` exists and holds an active membership of ``workspace_id``.

    Idempotent in both directions: a repeat call finds its rows. ``membership_id`` is honoured when
    supplied and minted otherwise — ``workspace_membership`` is unique on ``(workspace_id,
    user_id)``, so one user in two workspaces holds two different membership ids and a suite that
    seeds the same user twice must let the second one be minted.
    """

    await seed_workspace(conn, workspace_id)
    user = await get_platform_user(conn, user_id)
    if user is None:
        user = await create_platform_user(
            conn, user_id=user_id, display_name="Seeded test principal"
        )
    subject = f"test-fixture:{user_id}"
    if (
        await get_auth_identity(conn, provider_key=TEST_PROVIDER_KEY, provider_subject=subject)
        is None
    ):
        await link_auth_identity(
            conn,
            user_id=user.user_id,
            provider_key=TEST_PROVIDER_KEY,
            provider_subject=subject,
        )
    membership = await get_workspace_membership(
        conn, workspace_id=workspace_id, user_id=user.user_id
    )
    if membership is None:
        membership = await create_workspace_membership(
            conn,
            workspace_id=workspace_id,
            user_id=user.user_id,
            role_key=role_key,
            status="active",
            membership_id=membership_id,
        )
    return SeededPrincipal(
        user_id=user.user_id,
        membership_id=membership.membership_id,
        workspace_id=membership.workspace_id,
        role_key=membership.role_key,
    )
