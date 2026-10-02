"""`add_product_aliases`: append-only, folded-deduplicated, never renames."""

from __future__ import annotations

import pytest

from clue_spine import add_product_aliases, create_product, get_product
from tests._workspace import seed_project

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")


def test_aliases_append_without_duplicates_and_the_name_never_moves() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-spine-aliases"
            project = await seed_project(conn, ws, name="aliases")
            product = await create_product(
                conn,
                brand_id=project.brand_id,
                workspace_id=ws,
                name="Aura AI Scribe",
                aliases=("Aura",),
            )
            updated = await add_product_aliases(
                conn,
                product_id=product.product_id,
                workspace_id=ws,
                aliases=("Aura™ AI Scribe", "aura ai scribe", "Aura", "AI FrontDesk"),
            )
            assert updated.name == "Aura AI Scribe"
            # An alias is added only when its folded form matches neither the name nor an existing
            # alias. Both "Aura™ AI Scribe" (marks are stripped before folding) and "aura ai scribe"
            # fold onto the NAME, and "Aura" is already an alias — so exactly one spelling is new.
            assert updated.aliases == ("Aura", "AI FrontDesk")
            assert (await get_product(conn, product.product_id)).aliases == updated.aliases
            with pytest.raises(ValueError):
                await add_product_aliases(
                    conn, product_id=product.product_id, workspace_id="ws-other", aliases=("x",)
                )

    run_async(scenario())
