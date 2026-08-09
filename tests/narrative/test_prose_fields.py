"""Lane E slice E0 — the prose field pack (``account.summary`` / ``contact.overview``).

Shape tests are pure (no DB) and pin the §2.4 ratified registration: TENANT_PRIVATE,
PROJECT_NEUTRAL, faithfulness-gated tier-4 synthesis fields routed to the ready-made SUMMARY
sections. The DB test proves ``load_prose_pack`` lands real ``field_definition`` rows and active
routes, idempotently. Routes are immutable-by-registration, so these shapes must be right first
time — that is what this suite freezes.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from clue_core import EntityType, PassKind, ResearchScope, ResearchSectionKind, ReuseScope
from clue_research.claimstore import list_research_view_routes
from clue_research.narrative import (
    ACCOUNT_SUMMARY,
    CONTACT_OVERVIEW,
    PROSE_FIELD_KEYS,
    PROSE_PACK,
    load_prose_pack,
)

from .conftest import rollback_conn, run_async


def test_prose_pack_declares_the_ratified_field_shapes() -> None:
    assert PROSE_FIELD_KEYS == (ACCOUNT_SUMMARY, CONTACT_OVERVIEW)
    assert ACCOUNT_SUMMARY == "account.summary"
    assert CONTACT_OVERVIEW == "contact.overview"
    for seed in PROSE_PACK:
        field = seed.field_def
        assert field.value_type == "object"
        assert field.tier_plan == ()  # written by the Lane E seam, never the M4 waterfall
        assert field.pass_kind is PassKind.DEEP
        assert field.gate == "faithfulness"
        assert field.freshness_ttl == timedelta(days=90)
        assert field.reuse_scope is ReuseScope.TENANT_PRIVATE
        assert field.research_scope is ResearchScope.PROJECT_NEUTRAL
        assert seed.single_source_sufficient is True
        assert seed.corroboration_min == 1


def test_prose_routes_target_the_summary_sections_neutrally() -> None:
    routes = {
        seed.field_def.field_key: seed.research_view_route
        for seed in PROSE_PACK
        if seed.research_view_route is not None
    }
    assert set(routes) == {ACCOUNT_SUMMARY, CONTACT_OVERVIEW}
    account_route = routes[ACCOUNT_SUMMARY]
    assert account_route.entity_type is EntityType.ACCOUNT
    contact_route = routes[CONTACT_OVERVIEW]
    assert contact_route.entity_type is EntityType.CONTACT
    for route in (account_route, contact_route):
        # Deliberately the opposite of the narrative's pinned/exact route (§2.4): neutral
        # world-fact prose serves every project lens from the subject's current truth.
        assert route.section_kind is ResearchSectionKind.SUMMARY
        assert route.context_scope == "subject_current"
        assert route.product_mode == "neutral_or_exact"


def test_prose_value_schema_carries_the_d2_project_id_slot() -> None:
    for seed in PROSE_PACK:
        schema = seed.value_schema
        assert schema is not None
        assert set(schema["required"]) == {
            "paragraphs",
            "prompt_version",
            "synthesized_from_job_id",
            "research_outcome",
            "project_id",
        }
        paragraphs = schema["properties"]["paragraphs"]
        assert paragraphs["type"] == "array"
        assert paragraphs["minItems"] == 1
        assert paragraphs["items"]["type"] == "string"
        # D2 amendment (§2.5/§7): the project dimension exists from day one, fixed to null while
        # the fields are PROJECT_NEUTRAL — flipping to PROJECT_RELATIVE is a value change, never
        # a key migration.
        assert schema["properties"]["project_id"]["type"] == ["string", "null"]
        assert schema["properties"]["research_outcome"]["enum"] == [
            "completed",
            "needs_review",
        ]
        # additive growth without a migration (the fields.py:55-68 rationale)
        assert "additionalProperties" not in schema


def test_load_prose_pack_registers_fields_and_routes(require_narrative_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_prose_pack(conn)
            await load_prose_pack(conn)  # idempotent — re-loading is a no-op

            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT field_key, value_type, reuse_scope, research_scope, gate
                        FROM field_definition
                        WHERE field_key = ANY(:keys)
                        ORDER BY field_key
                        """
                    ),
                    {"keys": list(PROSE_FIELD_KEYS)},
                )
            ).mappings()
            by_key = {row["field_key"]: row for row in rows}
            assert set(by_key) == set(PROSE_FIELD_KEYS)
            for row in by_key.values():
                assert row["value_type"] == "object"
                assert row["reuse_scope"] == "tenant_private"
                assert row["research_scope"] == "project_neutral"
                assert row["gate"] == "faithfulness"

            account_routes = await list_research_view_routes(conn, entity_type=EntityType.ACCOUNT)
            contact_routes = await list_research_view_routes(conn, entity_type=EntityType.CONTACT)
            summary_route = next(
                route for route in account_routes if route.field_key == ACCOUNT_SUMMARY
            )
            overview_route = next(
                route for route in contact_routes if route.field_key == CONTACT_OVERVIEW
            )
            for route in (summary_route, overview_route):
                assert route.section_kind is ResearchSectionKind.SUMMARY
                assert route.context_scope == "subject_current"
                assert route.product_mode == "neutral_or_exact"

    run_async(scenario())
