"""D2 T5 exit gate: display_block persistence, recipe-scoped staleness, the evidence read.

A written section is only worth storing if the store can also say when it stopped being true, so
these run against the real table: the partial unique index that makes "one live block per section"
a database fact rather than a convention, and the five staleness reasons computed from the claims
the block cites and the recipe that produced it.

The draft is built by hand — no model is called and no key is read. What is exercised here is the
persistence, not the writing.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.calls import CallCost
from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_api.arv2.display.blocks import (
    LiveBlock,
    Staleness,
    block_body,
    cited_claim_ids,
    compose_display_block,
    insert_block,
    insight_summary,
    live_blocks,
    stale_sections,
    supersede_blocks,
)
from clue_api.arv2.display.evidence import evidence_for_ids
from clue_api.arv2.display.gather import (
    SectionInput,
    committee_members,
    gather_section_inputs,
    resolve_subject,
)
from clue_api.arv2.display.prompts import PROMPT_VERSION
from clue_api.arv2.display.recipes import (
    RECIPE_VERSION,
    SectionRecipe,
    load_display_recipes,
    read_recipes,
    recipes_for,
)
from clue_api.arv2.display.runner import SectionDraft
from clue_config import Settings
from clue_core import (
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    new_claim_id,
    new_run_id,
)
from clue_research.claimstore import WorkspaceScope, claims_by_ids, supersede_claim
from clue_research.claimstore.packs import load_core_pack
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.profiling.committee.fields import load_committee_pack
from clue_research.profiling.fields import load_deep_profiling_pack
from tests._workspace import seed_workspace
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_b"
PERMISSIVE = Settings(_env_file=None, verification_enabled=False)


class Seeded:
    """The one page's worth of state every test here starts from."""

    def __init__(
        self,
        *,
        workspace_id: str,
        account: EntityId,
        nick: EntityId,
        recipes: tuple[SectionRecipe, ...],
        sections: list[SectionInput],
    ) -> None:
        self.workspace_id = workspace_id
        self.account = account
        self.nick = nick
        self.recipes = recipes
        self.sections = sections

    @property
    def openers(self) -> SectionInput:
        return next(s for s in self.sections if s.recipe.section_key == "openers")

    @property
    def subject_ids(self) -> list[str]:
        return [str(self.nick), str(self.account)]


async def _write(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    entity_id: EntityId,
    entity_type: EntityType,
    field_key: str,
    value_json: Any,
    **overrides: Any,
) -> str:
    draft = ClaimDraft(
        entity_id=entity_id,
        entity_type=entity_type,
        field_key=field_key,
        value_json=value_json,
        extraction_method=overrides.pop("extraction_method", ExtractionMethod.SCRAPE),
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
        workspace_id=workspace_id,
        source_url=overrides.pop("source_url", "https://zafran.io/newsroom"),
        **overrides,
    )
    receipt = await LenientClaimWriter(lenient=True).write(conn, draft)
    return str(receipt.claim_id)


async def _seed(conn: AsyncConnection) -> Seeded:
    ws = await seed_workspace(conn, WORKSPACE)
    await load_core_pack(conn)
    await load_deep_profiling_pack(conn)
    await load_committee_pack(conn)
    await load_arv2_pack(conn)
    await load_display_recipes(conn)

    account = await insert_account_entity(
        conn, canonical_name="Zafran Security", primary_domain="zafran.io", workspace_id=ws
    )
    nick = await insert_contact_entity(
        conn,
        account_entity_id=account,
        full_name="Nick Fisher",
        linkedin_url="https://www.linkedin.com/in/nicholastfisher",
    )
    vari = await insert_contact_entity(
        conn,
        account_entity_id=account,
        full_name="Vari Bindra",
        linkedin_url="https://www.linkedin.com/in/varibindra",
    )

    await _write(
        conn,
        workspace_id=ws,
        entity_id=nick,
        entity_type=EntityType.CONTACT,
        field_key="contact.persona",
        value_json="economic_buyer",
        signal_priority=1,
    )
    await _write(
        conn,
        workspace_id=ws,
        entity_id=nick,
        entity_type=EntityType.CONTACT,
        field_key="contact.current_title",
        value_json="VP of Marketing",
        signal_priority=1,
    )
    await _write(
        conn,
        workspace_id=ws,
        entity_id=vari,
        entity_type=EntityType.CONTACT,
        field_key="contact.persona",
        value_json="champion",
        signal_priority=2,
    )
    await _write(
        conn,
        workspace_id=ws,
        entity_id=nick,
        entity_type=EntityType.CONTACT,
        field_key="contact.facet.hobby",
        value_json=["Cocktail YouTuber, creator of the Cocktail Chemistry channel"],
        signal_priority=2,
        evidence_span="I run the Cocktail Chemistry channel",
    )
    await _write(
        conn,
        workspace_id=ws,
        entity_id=nick,
        entity_type=EntityType.CONTACT,
        field_key="contact.facet.voice_quote",
        value_json={
            "text": "We buy tools that show us the buyer, not the dashboard",
            "media_url": "https://youtu.be/zafran",
            "media_timestamp": "12:04",
        },
        signal_priority=1,
        evidence_span="We buy tools that show us the buyer, not the dashboard",
    )

    subject = await resolve_subject(conn, workspace_id=ws, kind="contact", subject_id=str(nick))
    people = await committee_members(conn, workspace_id=ws, account_id=str(account))
    recipes = await read_recipes(conn, "contact", workspace_id=ws)
    sections = await gather_section_inputs(
        conn,
        workspace_id=ws,
        subject=subject,
        recipes=recipes,
        people=people,
        settings=PERMISSIVE,
    )
    return Seeded(workspace_id=ws, account=account, nick=nick, recipes=recipes, sections=sections)


def _draft(
    section: SectionInput, *, cited: list[str], model: str = "x-ai/grok-4.6"
) -> SectionDraft:
    """One section as the runner would have returned it, written by hand."""
    items: list[dict[str, object]] = [
        {
            "id": f"openers-{index}",
            "h2": f"Opener {index}",
            "body": [{"text": f"Sentence {index}.", "claimIds": [claim_id]}],
            "sendLine": None,
            "contactRefs": [],
            "priority": 2,
            "newSinceLastVisit": False,
        }
        for index, claim_id in enumerate(cited, start=1)
    ]
    return SectionDraft(
        section_key=section.recipe.section_key,
        intro=[],
        items=items,
        cited_claim_ids=list(cited),
        checks={"prompt_version": PROMPT_VERSION, "unknown_aliases": [], "off_recipe": []},
        aliases={f"c{i}": claim_id for i, claim_id in enumerate(cited, start=1)},
        cost=CallCost(
            cost_usd=Decimal("0.0141"),
            credits=None,
            media_seconds=None,
            cost_source="metered",
            ledger_row_id="ledger-1",
            raw_ref="artifact://raw/1",
            provider="openrouter",
            operation="display_section",
        ),
        model=model,
        raw_refs=("artifact://raw/1",),
    )


async def _insert(
    conn: AsyncConnection, seeded: Seeded, *, now: datetime, model: str = "x-ai/grok-4.6"
) -> tuple[str, SectionDraft, list[str]]:
    section = seeded.openers
    cited = [claim.claim_id for claim in section.claims[:2]]
    draft = _draft(section, cited=cited, model=model)
    block_id = await insert_block(
        conn,
        workspace_id=seeded.workspace_id,
        subject_kind="contact",
        subject_id=str(seeded.nick),
        page="contact",
        recipe=section.recipe,
        draft=draft,
        section=section,
        now=now,
    )
    return block_id, draft, cited


async def _live(conn: AsyncConnection, seeded: Seeded) -> dict[str, LiveBlock]:
    return await live_blocks(
        conn,
        workspace_id=seeded.workspace_id,
        subject_kind="contact",
        subject_id=str(seeded.nick),
        page="contact",
    )


async def _stale(
    conn: AsyncConnection,
    seeded: Seeded,
    blocks: dict[str, LiveBlock],
    *,
    recipes: tuple[SectionRecipe, ...] | None = None,
    subject_ids: list[str] | None = None,
) -> list[Staleness]:
    return await stale_sections(
        conn,
        workspace_id=seeded.workspace_id,
        subject_ids=subject_ids if subject_ids is not None else seeded.subject_ids,
        recipes=recipes if recipes is not None else seeded.recipes,
        blocks=blocks,
    )


# -- the body ------------------------------------------------------------------------------------


def test_the_body_carries_the_items_the_flags_and_the_call_it_cost() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            section = seeded.openers
            assert len(section.claims) >= 2
            cited = [claim.claim_id for claim in section.claims[:2]]
            body = block_body(_draft(section, cited=cited), section)

            assert set(body) == {"intro", "items", "checks", "cited_flags", "cost_usd", "call"}
            assert body["intro"] == []
            assert isinstance(body["items"], list) and len(body["items"]) == 2
            assert body["cited_flags"] == dict.fromkeys(cited, True)
            assert body["cost_usd"] == "0.0141"
            assert body["call"] == {
                "ledger_row_id": "ledger-1",
                "raw_ref": "artifact://raw/1",
                "raw_refs": ["artifact://raw/1"],
            }
            # The provider's request id is not on CallCost and is not invented here.
            assert "provider_request_id" not in body["call"]

    run_async(_run())


def test_a_section_that_never_reached_a_provider_records_no_call_and_no_cost() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            section = seeded.openers
            draft = replace(_draft(section, cited=[]), cost=None)
            body = block_body(draft, section)
            assert body["cost_usd"] is None
            assert body["call"] is None
            assert body["cited_flags"] == {}

    run_async(_run())


def test_an_unsafe_cited_claim_is_recorded_with_its_own_flag() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            await _write(
                conn,
                workspace_id=seeded.workspace_id,
                entity_id=seeded.account,
                entity_type=EntityType.ACCOUNT,
                field_key="account.reputation_risk",
                value_json={"what": "A 2025 customer dispute", "status": "unresolved"},
                signal_priority=3,
                outreach_safe=False,
                evidence_span="an unresolved dispute",
            )
            sections = await gather_section_inputs(
                conn,
                workspace_id=seeded.workspace_id,
                subject=await resolve_subject(
                    conn,
                    workspace_id=seeded.workspace_id,
                    kind="contact",
                    subject_id=str(seeded.nick),
                ),
                recipes=seeded.recipes,
                people=await committee_members(
                    conn, workspace_id=seeded.workspace_id, account_id=str(seeded.account)
                ),
                settings=PERMISSIVE,
            )
            restricted = next(s for s in sections if s.recipe.section_key == "do-not-mention")
            unsafe = [claim for claim in restricted.claims if not claim.outreach_safe]
            assert unsafe
            body = block_body(_draft(restricted, cited=[unsafe[0].claim_id]), restricted)
            assert body["cited_flags"] == {unsafe[0].claim_id: False}

    run_async(_run())


# -- persistence ---------------------------------------------------------------------------------


def test_a_written_section_is_stored_and_read_back_as_the_live_block() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            now = datetime.now(UTC)
            block_id, draft, cited = await _insert(conn, seeded, now=now)

            blocks = await _live(conn, seeded)
            assert set(blocks) == {"openers"}
            block = blocks["openers"]
            assert block.display_block_id == block_id
            assert block.section_key == "openers"
            assert block.model == "x-ai/grok-4.6"
            assert block.prompt_version == f"{PROMPT_VERSION}+v1"
            assert block.recipe_version == RECIPE_VERSION
            assert block.generated_at == now
            assert list(block.cited_claim_ids) == cited
            assert block.body_json["cited_flags"] == dict.fromkeys(cited, True)
            assert len(block.body_json["items"]) == len(draft.items)

    run_async(_run())


def test_a_second_write_supersedes_the_first_and_leaves_one_live_row() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            first, _, _ = await _insert(conn, seeded, now=datetime.now(UTC))
            second, _, _ = await _insert(
                conn, seeded, now=datetime.now(UTC), model="anthropic/claude"
            )
            assert first != second

            blocks = await _live(conn, seeded)
            assert set(blocks) == {"openers"}
            assert blocks["openers"].display_block_id == second
            assert blocks["openers"].model == "anthropic/claude"

            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT display_block_id, superseded_at FROM display_block "
                            "WHERE workspace_id = :ws ORDER BY generated_at"
                        ),
                        {"ws": seeded.workspace_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(rows) == 2
            retired = [row for row in rows if row["superseded_at"] is not None]
            assert [row["display_block_id"] for row in retired] == [uuid.UUID(first)]

    run_async(_run())


def test_supersede_blocks_retires_the_sections_it_is_given() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            now = datetime.now(UTC)
            await _insert(conn, seeded, now=now)
            retired = await supersede_blocks(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
                section_keys=["openers", "angles"],
                now=now,
            )
            assert retired == 1
            assert await _live(conn, seeded) == {}
            assert (
                await supersede_blocks(
                    conn,
                    workspace_id=seeded.workspace_id,
                    subject_kind="contact",
                    subject_id=str(seeded.nick),
                    page="contact",
                    section_keys=["openers"],
                    now=now,
                )
            ) == 0

    run_async(_run())


# -- staleness -----------------------------------------------------------------------------------


def test_a_freshly_written_block_is_not_stale() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            await _insert(conn, seeded, now=datetime.now(UTC))
            assert await _stale(conn, seeded, await _live(conn, seeded)) == []

    run_async(_run())


def test_a_section_with_no_block_is_never_reported_stale() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            assert await _stale(conn, seeded, {}) == []

    run_async(_run())


def test_a_newer_claim_on_an_allowed_key_of_an_expansion_entity_is_new_claims() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            await _insert(conn, seeded, now=datetime.now(UTC))
            blocks = await _live(conn, seeded)

            # ``account.abm_program_maturity`` is an allowed key of ``openers`` — and it lands on
            # the *account*, which is only in scope because the subject's expansion carries it.
            await _write(
                conn,
                workspace_id=seeded.workspace_id,
                entity_id=seeded.account,
                entity_type=EntityType.ACCOUNT,
                field_key="account.abm_program_maturity",
                value_json="Running ABM on three named accounts",
                signal_priority=1,
                evidence_span="running ABM on three named accounts",
            )

            stale = await _stale(conn, seeded, blocks)
            assert [entry.section_key for entry in stale] == ["openers"]
            assert stale[0].reasons == ("new_claims",)

            # Without the account in the subject set, the same claim is out of scope.
            assert await _stale(conn, seeded, blocks, subject_ids=[str(seeded.nick)]) == []

    run_async(_run())


def test_a_claim_on_a_key_no_recipe_allows_does_not_make_the_section_stale() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            await _insert(conn, seeded, now=datetime.now(UTC))
            blocks = await _live(conn, seeded)
            await _write(
                conn,
                workspace_id=seeded.workspace_id,
                entity_id=seeded.account,
                entity_type=EntityType.ACCOUNT,
                field_key="account.reputation_risk",
                value_json={"what": "A dispute", "status": "open"},
                signal_priority=3,
                outreach_safe=False,
                evidence_span="a dispute",
            )
            assert await _stale(conn, seeded, blocks) == []

    run_async(_run())


def test_superseding_a_cited_claim_is_superseded_citation() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            _, _, cited = await _insert(conn, seeded, now=datetime.now(UTC))
            blocks = await _live(conn, seeded)

            old_id = uuid.UUID(cited[0])
            found = await claims_by_ids(
                conn,
                [old_id],  # type: ignore[list-item]
                scope=WorkspaceScope.for_workspace(seeded.workspace_id),
            )
            claim = next(iter(found.values()))
            replacement = claim.model_copy(
                update={
                    "id": new_claim_id(),
                    "value_json": "A corrected quote",
                    "collected_at": datetime.now(UTC),
                }
            )
            await supersede_claim(conn, claim.id, replacement, validate_field=False)

            stale = await _stale(conn, seeded, blocks)
            assert [entry.section_key for entry in stale] == ["openers"]
            assert "superseded_citation" in stale[0].reasons

    run_async(_run())


def test_flipping_a_cited_claims_flag_is_flag_changed() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            _, _, cited = await _insert(conn, seeded, now=datetime.now(UTC))
            blocks = await _live(conn, seeded)
            await conn.execute(
                text("UPDATE claim SET outreach_safe = false WHERE id = :id"),
                {"id": uuid.UUID(cited[0])},
            )
            stale = await _stale(conn, seeded, blocks)
            assert [entry.section_key for entry in stale] == ["openers"]
            assert stale[0].reasons == ("flag_changed",)

    run_async(_run())


def test_a_changed_instruction_version_is_prompt_version() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            await _insert(conn, seeded, now=datetime.now(UTC))
            blocks = await _live(conn, seeded)
            rewritten = tuple(
                replace(recipe, instruction_version="v2")
                if recipe.section_key == "openers"
                else recipe
                for recipe in seeded.recipes
            )
            stale = await _stale(conn, seeded, blocks, recipes=rewritten)
            assert [entry.section_key for entry in stale] == ["openers"]
            assert stale[0].reasons == ("prompt_version",)

    run_async(_run())


def test_a_block_written_under_an_older_recipe_version_is_recipe_version() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            block_id, _, _ = await _insert(conn, seeded, now=datetime.now(UTC))
            await conn.execute(
                text("UPDATE display_block SET recipe_version = :old WHERE display_block_id = :id"),
                {"old": RECIPE_VERSION - 1, "id": uuid.UUID(block_id)},
            )
            stale = await _stale(conn, seeded, await _live(conn, seeded))
            assert [entry.section_key for entry in stale] == ["openers"]
            assert stale[0].reasons == ("recipe_version",)

    run_async(_run())


def test_several_reasons_are_reported_together_in_a_stable_order() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            _, _, cited = await _insert(conn, seeded, now=datetime.now(UTC))
            blocks = await _live(conn, seeded)
            await conn.execute(
                text("UPDATE claim SET outreach_safe = false WHERE id = :id"),
                {"id": uuid.UUID(cited[0])},
            )
            await _write(
                conn,
                workspace_id=seeded.workspace_id,
                entity_id=seeded.nick,
                entity_type=EntityType.CONTACT,
                field_key="contact.facet.hobby",
                value_json=["Restores vintage motorcycles"],
                signal_priority=2,
                evidence_span="restoring vintage motorcycles",
            )
            rewritten = tuple(
                replace(recipe, instruction_version="v2")
                if recipe.section_key == "openers"
                else recipe
                for recipe in seeded.recipes
            )
            stale = await _stale(conn, seeded, blocks, recipes=rewritten)
            assert len(stale) == 1
            assert stale[0].reasons == ("new_claims", "flag_changed", "prompt_version")

    run_async(_run())


# -- composition ---------------------------------------------------------------------------------


def test_the_contact_page_composes_six_sections_with_the_recipes_flags() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            await _insert(conn, seeded, now=datetime.now(UTC))
            page = compose_display_block("contact", seeded.recipes, await _live(conn, seeded))

            assert page["page"] == "contact"
            sections = page["sections"]
            assert [section["key"] for section in sections] == [
                "why-this-person",
                "problem-right-now",
                "openers",
                "angles",
                "do-not-mention",
                "miscellaneous",
            ]
            by_key = {section["key"]: section for section in sections}
            assert by_key["openers"]["empty"] is False
            assert len(by_key["openers"]["items"]) == 2
            assert by_key["openers"]["h1"] == "Openers"
            assert all(by_key[key]["empty"] is True for key in by_key if key != "openers")
            assert all(
                section["items"] == [] for section in sections if section["key"] != "openers"
            )
            assert by_key["do-not-mention"]["restricted"] is True
            assert by_key["angles"]["restricted"] is False
            assert by_key["angles"]["defaultOpen"] is False
            assert by_key["openers"]["defaultOpen"] is True
            assert all("emptyMessage" not in section for section in sections)
            # No contact-page section is narrative, so none of them carries an intro.
            assert all("intro" not in section for section in sections)

    run_async(_run())


def test_a_narrative_section_always_carries_an_intro_even_when_it_has_no_block() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            overview = await read_recipes(conn, "overview", workspace_id=seeded.workspace_id)
            page = compose_display_block("overview", overview, {})
            by_key = {section["key"]: section for section in page["sections"]}
            assert by_key["what-they-do"]["intro"] == []
            assert by_key["what-they-do"]["empty"] is True
            assert "intro" not in by_key["why-now"]

    run_async(_run())


def test_insight_summary_counts_only_the_unrestricted_items() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            await _insert(conn, seeded, now=datetime.now(UTC))
            page = compose_display_block("contact", seeded.recipes, await _live(conn, seeded))
            assert insight_summary(page, 3) == ["2 insights", "3 people"]

            restricted = next(
                section for section in page["sections"] if section["key"] == "do-not-mention"
            )
            restricted["items"] = [{"id": "do-not-mention-1"}]
            restricted["empty"] = False
            assert insight_summary(page, 0) == ["2 insights", "0 people"]

    run_async(_run())


# -- evidence over the store ---------------------------------------------------------------------


def test_evidence_for_ids_resolves_the_cited_claims_of_a_stored_block() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            await _insert(conn, seeded, now=datetime.now(UTC))
            block = (await _live(conn, seeded))["openers"]

            refs = await evidence_for_ids(
                conn,
                workspace_id=seeded.workspace_id,
                claim_ids=list(block.cited_claim_ids),
            )
            assert {ref.claim_id for ref in refs} == set(block.cited_claim_ids)
            assert all(ref.source_domain == "zafran.io" for ref in refs)
            assert all(ref.verification_kind == "verified" for ref in refs)
            assert all(ref.quote for ref in refs)
            assert all("researchExcerpt" not in ref.to_wire() for ref in refs)

            # Another workspace's read of the same ids resolves nothing.
            other = await seed_workspace(conn, "ws_b_other")
            assert (
                await evidence_for_ids(
                    conn, workspace_id=other, claim_ids=list(block.cited_claim_ids)
                )
                == []
            )

    run_async(_run())


def test_evidence_for_ids_of_nothing_is_nothing() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            assert (
                await evidence_for_ids(conn, workspace_id=seeded.workspace_id, claim_ids=[]) == []
            )

    run_async(_run())


def test_the_stored_block_survives_a_round_trip_through_the_page_shape() -> None:
    """The items the composer serves are the items the runner wrote, key for key."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await _seed(conn)
            _, draft, _ = await _insert(conn, seeded, now=datetime.now(UTC))
            page = compose_display_block("contact", seeded.recipes, await _live(conn, seeded))
            served = next(section for section in page["sections"] if section["key"] == "openers")[
                "items"
            ]
            assert served == draft.items

    run_async(_run())


# -- shared blocks: a section that renders somebody else's stored body --------------------------


def test_a_shared_section_composes_the_owner_body_under_its_own_chrome() -> None:
    owner = LiveBlock(
        display_block_id=str(uuid.uuid4()),
        section_key="watch-outs",
        body_json={"items": [{"id": "i1", "h2": "x", "body": []}], "intro": []},
        cited_claim_ids=("c1",),
        model="m",
        prompt_version="display-v1+v1",
        recipe_version=1,
        generated_at=datetime.now(UTC),
    )
    recipes = recipes_for("insights")
    composed = compose_display_block("insights", recipes, {}, shared={"context-only": [owner]})
    section = next(s for s in composed["sections"] if s["key"] == "context-only")
    assert section["h1"] == "Context only" and section["restricted"] is True
    assert section["items"] == owner.body_json["items"] and section["empty"] is False
    assert cited_claim_ids(recipes, {}, {"context-only": [owner]}) == ("c1",)


def test_a_shared_section_whose_owner_is_unwritten_is_empty_and_never_pending_here() -> None:
    composed = compose_display_block("insights", recipes_for("insights"), {}, shared={})
    section = next(s for s in composed["sections"] if s["key"] == "context-only")
    assert section["empty"] is True and section["items"] == []
