"""The legacy-workspace-name backfill, against real rows.

Until the display-name work, a self-serve workspace was born named after its own id, so every
marketer provisioned before it saw ``ws_01J…`` wherever the product says "workspace". The website
those users typed at onboarding is still on their ``self_serve_provisioning`` row, and
:func:`canonical_workspace_name` turns it into the name they should have had all along.

Three properties are what make the script safe to point at a production database, and all three
are proven here against seeded rows rather than a mocked query: it renames **only** a workspace
still named as its id and holding a website (a workspace someone has already named, or one with no
provisioning row, is left alone), the rename is the canonical name, and it is **idempotent** — a
second pass plans nothing, because a renamed workspace no longer matches ``name = workspace_id``.
"""

from __future__ import annotations

import pytest
from scripts.backfill_workspace_names import apply_backfill, plan_backfill
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_auth import create_platform_user, link_auth_identity
from clue_spine import create_brand, create_workspace, get_workspace, new_workspace_id
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

_INSERT_PROVISIONING = text(
    "INSERT INTO self_serve_provisioning "
    "(auth_identity_id, user_id, workspace_id, brand_id, company_website) "
    "VALUES (:auth_identity_id, :user_id, :workspace_id, :brand_id, :company_website)"
)


async def _seed_workspace(conn: AsyncConnection, *, name: str | None, website: str | None) -> str:
    """One workspace, named ``name`` or after its own id, with a provisioning row iff a website.

    The provisioning row's FKs demand the whole self-serve chain — a platform user, the auth
    identity that provisioned it, and a same-workspace brand — so the seed builds it with the real
    ``clue_auth``/``clue_spine`` writers rather than inventing rows the constraints would reject.
    """
    workspace_id = new_workspace_id()
    await create_workspace(conn, workspace_id=workspace_id, name=name or workspace_id)
    if website is None:
        return workspace_id
    user = await create_platform_user(conn, display_name="Backfill user")
    identity = await link_auth_identity(
        conn,
        user_id=user.user_id,
        provider_key="local_fixture",
        provider_subject=f"backfill:{workspace_id}",
    )
    brand = await create_brand(conn, workspace_id=workspace_id, name="Backfill brand")
    await conn.execute(
        _INSERT_PROVISIONING,
        {
            "auth_identity_id": identity.auth_identity_id,
            "user_id": user.user_id,
            "workspace_id": workspace_id,
            "brand_id": brand.brand_id,
            "company_website": website,
        },
    )
    return workspace_id


async def _seed_three(conn: AsyncConnection) -> tuple[str, str, str]:
    """A: legacy + website. B: legacy, never self-serve. C: already named by a human."""
    legacy = await _seed_workspace(conn, name=None, website="https://www.acme-health.com")
    unprovisioned = await _seed_workspace(conn, name=None, website=None)
    named = await _seed_workspace(conn, name="Real Co", website="https://real-co.example")
    return legacy, unprovisioned, named


def test_plan_names_only_the_legacy_workspace_that_has_a_website() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            legacy, unprovisioned, named = await _seed_three(conn)

            plan = await plan_backfill(conn)

            planned = {rename.workspace_id: rename for rename in plan}
            assert unprovisioned not in planned, "a workspace with no provisioning row has no name"
            assert named not in planned, "a workspace someone has already named is never renamed"
            assert legacy in planned
            rename = planned[legacy]
            assert rename.old_name == legacy
            assert rename.new_name == "Acme Health"
            assert rename.website == "https://www.acme-health.com"

    run_async(scenario())


def test_apply_renames_only_the_planned_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            legacy, unprovisioned, named = await _seed_three(conn)
            plan = [rename for rename in await plan_backfill(conn) if rename.workspace_id == legacy]

            renamed = await apply_backfill(conn, plan)

            assert renamed == 1
            after = await get_workspace(conn, legacy)
            assert after is not None and after.name == "Acme Health"
            untouched = await get_workspace(conn, unprovisioned)
            assert untouched is not None and untouched.name == unprovisioned
            human = await get_workspace(conn, named)
            assert human is not None and human.name == "Real Co"

    run_async(scenario())


def test_a_second_pass_plans_nothing() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            legacy, _, _ = await _seed_three(conn)
            plan = [rename for rename in await plan_backfill(conn) if rename.workspace_id == legacy]
            await apply_backfill(conn, plan)

            again = await plan_backfill(conn)

            assert all(rename.workspace_id != legacy for rename in again)

    run_async(scenario())
