"""S4 exit gate: every recipe key is a registered field; the page grammar is the master plan's."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_api.arv2.catalog_seed import ARV2_FIELD_KEYS
from clue_api.arv2.display.recipes import (
    PAGES,
    RECIPE_VERSION,
    RESTRICTED_SECTION_KEYS,
    SYSTEM_RECIPES,
    load_display_recipes,
    read_recipes,
    recipes_for,
)
from clue_research.claimstore.packs import CORE_PACK
from clue_research.profiling.committee.fields import COMMITTEE_PACK
from clue_research.profiling.fields import DEEP_PROFILING_PACK
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

EXPECTED_H1S = {
    "insights": [
        "Buying signals",
        "Money & momentum",
        "Tools they already use",
        "How they sell, and who they win",
        "Context only",
        "Miscellaneous",
    ],
    "overview": [
        "What they do",
        "Why they fit",
        "Why now",
        "Buying committee",
        "How to approach",
        "Watch-outs",
    ],
    "contact": [
        "Why this person",
        "Their problem right now",
        "Openers",
        "Angles",
        "Do not mention",
        "Miscellaneous",
    ],
}


def _static_registered_keys() -> set[str]:
    keys = set(ARV2_FIELD_KEYS)
    for pack in (CORE_PACK, DEEP_PROFILING_PACK, COMMITTEE_PACK):
        keys.update(str(seed.field_def.field_key) for seed in pack)
    return keys


def test_page_grammar_is_the_master_plans() -> None:
    for page in PAGES:
        rows = recipes_for(page)
        assert [r.h1 for r in rows] == EXPECTED_H1S[page]
        assert [r.position for r in rows] == list(range(len(rows)))
        assert all("(" not in r.h1 and "·" not in r.h1 for r in rows), "h1 is served bare"


def test_restricted_sections_are_exactly_the_three() -> None:
    restricted = {r.section_key for r in SYSTEM_RECIPES if r.restricted}
    assert restricted == RESTRICTED_SECTION_KEYS == {"context-only", "watch-outs", "do-not-mention"}


def test_every_recipe_key_is_a_registered_field_statically() -> None:
    registered = _static_registered_keys()
    missing = {
        (r.page, r.section_key, key)
        for r in SYSTEM_RECIPES
        for key in r.allowed_field_keys
        if key not in registered
    }
    assert not missing, f"unregistered recipe keys: {sorted(missing)}"


def test_every_recipe_has_keys_and_versions() -> None:
    assert RECIPE_VERSION == 1
    for r in SYSTEM_RECIPES:
        assert r.allowed_field_keys, (r.page, r.section_key)
        assert len(set(r.allowed_field_keys)) == len(r.allowed_field_keys), "no duplicate keys"
        assert r.instruction_version == "v1"
        assert r.workspace_id == ""


@pytest.mark.usefixtures("require_claimstore_db")
def test_recipes_seed_idempotently_and_a_workspace_row_overrides() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await load_display_recipes(conn)
            await load_display_recipes(conn)  # second run is a no-op upsert
            n = (
                await conn.execute(text("SELECT count(*) FROM display_section_recipe"))
            ).scalar_one()
            assert n == len(SYSTEM_RECIPES)
            await conn.execute(
                text(
                    "INSERT INTO workspace (workspace_id, name) "
                    "VALUES ('ws_r', 'ws_r') ON CONFLICT DO NOTHING"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO display_section_recipe "
                    "(page, section_key, workspace_id, h1, position, "
                    "allowed_field_keys, restricted, default_open, instruction_version) "
                    "VALUES ('contact', 'openers', 'ws_r', 'Openers', 2, "
                    "ARRAY['contact.facet.hobby'], false, true, 'v1-ws')"
                )
            )
            rows = await read_recipes(conn, "contact", workspace_id="ws_r")
            openers = next(r for r in rows if r.section_key == "openers")
            assert openers.allowed_field_keys == ("contact.facet.hobby",)
            assert openers.instruction_version == "v1-ws"
            assert [r.h1 for r in rows] == EXPECTED_H1S["contact"]
            system = await read_recipes(conn, "contact", workspace_id="ws_other")
            assert next(r for r in system if r.section_key == "openers").instruction_version == "v1"

    run_async(_run())


def test_the_sharing_set_leaves_the_insights_page_five_generated_recipes() -> None:
    insights = recipes_for("insights")
    shared = {r.section_key: r.shared_from for r in insights if r.shared_from is not None}
    assert shared == {
        "context-only": ("overview", "watch-outs"),
    }
    assert [r.section_key for r in insights if r.shared_from is None] == [
        "buying-signals",
        "money-and-momentum",
        "tools-they-already-use",
        "how-they-sell",
        "miscellaneous",
    ]
    # The owner and the sharer ask the same question: identical keys for the same-subject pair.
    by_key = {(r.page, r.section_key): r for r in SYSTEM_RECIPES}
    assert (
        by_key[("insights", "context-only")].allowed_field_keys
        == by_key[("overview", "watch-outs")].allowed_field_keys
    )
    # A sharer never owns a block, so it is never restricted differently from its owner.
    assert (
        by_key[("insights", "context-only")].restricted
        is by_key[("overview", "watch-outs")].restricted
    )


@pytest.mark.usefixtures("require_claimstore_db")
def test_shared_from_round_trips_through_the_recipe_table() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await load_display_recipes(conn)
            rows = await read_recipes(conn, "insights", workspace_id="ws_any")
            assert {r.section_key: r.shared_from for r in rows if r.shared_from} == {
                "context-only": ("overview", "watch-outs"),
            }

    run_async(_run())
