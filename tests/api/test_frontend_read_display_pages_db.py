"""D3 Task 4 exit gate: the display seam, over a real database and the D2 provider double.

The seam has exactly three jobs and each one is proved here against real rows:

* **a page on read** — compose what is stored, and (only when a runner exists) write what is
  missing during the request;
* **degraded, never broken** — a provider that refuses to sell yields an honestly empty page and a
  named reason, not a 500;
* **staleness is repaired in the background** — a read never pays for a rewrite, it schedules one,
  and it schedules exactly one.

The provider double is D2's :class:`RoutingTransport` (imported, not re-written: a second copy is
how two suites end up disagreeing about what the model said). Everything below it is real — the
seeded claims, the recipes, the blocks, the committee reads.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_store import create_job, finish_job
from clue_api.arv2.display.personas import PERSONA_RANK, persona_label
from clue_api.arv2.display.recipes import recipes_for
from clue_api.arv2.display.runner import LunaSectionRunner
from clue_api.arv2.errors import ProviderHalted
from clue_api.arv2.fleet_task import ARV2_DISPLAY_DEDUP_PREFIX, arv2_display_work_id
from clue_api.arv2.sinks import LedgerSink, RawSink
from clue_api.frontend_read.display_pages import (
    DEFAULT_WHY_THEY_MATTER,
    DERIVED_ROLE_MARKER,
    DERIVED_ROLE_RATIONALE_PHRASE,
    PENDING_MESSAGE,
    ROLE_KEY,
    DisplayPages,
    _membership_gap_text,
    _why_they_matter,
    buying_committee,
    committee,
    rail_contacts,
)
from clue_config import Secrets, Settings
from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    ReuseScope,
    UseClass,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_fleet import FleetTaskKind
from clue_research.compliance import WorkspacePolicy
from clue_research.durable import ensure_project_run
from clue_research.identity import insert_account_entity, insert_contact_entity
from tests._workspace import seed_project
from tests.arv2.display._seed import Seeded, seed_display_fixture, write_claim

# The D2 page suite's keyed provider double and its one-runner-per-section factory. Imported so
# both suites answer with the same canned section for the same request.
from tests.arv2.display.test_page_db import RoutingTransport, _factory
from tests.arv2.test_provider_ledger_db import FakeArtifacts
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_d3_display"

#: Generation is ON in every case below, so what decides whether a model is called is the runner
#: the seam built — never the flag alone.
SETTINGS = Settings(
    _env_file=None,
    verification_enabled=False,
    arv2_display_max_parallel=4,
    arv2_display_generate_on_read=True,
)

#: No key configured, whatever the ambient environment says (an init value beats the env).
NO_KEY = Secrets(_env_file=None, openrouter_api_key=None)

CONTACT_SECTIONS = tuple(recipe.section_key for recipe in recipes_for("contact"))

POLICY = WorkspacePolicy()


def _sections(read: Any) -> list[Mapping[str, Any]]:
    sections = read.display_block["sections"]
    assert isinstance(sections, list)
    return sections


async def _retired_blocks(conn: AsyncConnection, workspace_id: str) -> int:
    """How many display blocks the workspace has superseded — the regeneration's own footprint."""
    return int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM display_block "
                    "WHERE workspace_id = :ws AND superseded_at IS NOT NULL"
                ),
                {"ws": workspace_id},
            )
        ).scalar_one()
    )


def _pages(conn: AsyncConnection, *, runner_factory: Any = None, **kwargs: Any) -> DisplayPages:
    return DisplayPages(
        settings=kwargs.pop("settings", SETTINGS),
        secrets=kwargs.pop("secrets", NO_KEY),
        conn_factory=conn_session_factory(conn),
        runner_factory=runner_factory,
        artifacts=kwargs.pop("artifacts", FakeArtifacts()),
        queue=kwargs.pop("queue", None),
    )


async def _contact_page(pages: DisplayPages, conn: AsyncConnection, seeded: Seeded) -> Any:
    return await pages.page(
        conn,
        workspace_id=seeded.workspace_id,
        subject_kind="contact",
        subject_id=str(seeded.nick),
        page="contact",
    )


# -- construction: the runner exists only when generation is on AND a key is configured ---------


def test_the_seam_builds_no_runner_without_a_key_even_when_generation_is_on() -> None:
    """Case (f): construction never raises, and a keyless deployment is a pure projection.

    ``default_runner_factory`` raises on a blank key — deliberately, so a CLI fails before it
    opens a database. A read surface must not: it serves what is stored and says nothing about
    money it cannot spend.
    """

    async def _factory_unused() -> None:  # pragma: no cover - never called
        raise AssertionError("the connection factory must not be opened at construction")

    assert (
        DisplayPages(
            settings=SETTINGS,
            secrets=NO_KEY,
            conn_factory=_factory_unused,  # type: ignore[arg-type]
        ).generates
        is False
    )
    blank = Secrets(_env_file=None, openrouter_api_key=SecretStr("   "))
    assert (
        DisplayPages(
            settings=SETTINGS,
            secrets=blank,
            conn_factory=_factory_unused,  # type: ignore[arg-type]
        ).generates
        is False
    )
    assert (
        DisplayPages(
            settings=SETTINGS,
            secrets=None,
            conn_factory=_factory_unused,  # type: ignore[arg-type]
        ).generates
        is False
    )

    keyed = Secrets(_env_file=None, openrouter_api_key=SecretStr("k"))
    assert (
        DisplayPages(
            settings=SETTINGS,
            secrets=keyed,
            conn_factory=_factory_unused,  # type: ignore[arg-type]
            artifacts=FakeArtifacts(),
        ).generates
        is True
    )
    # A key, but nowhere to put the raw bodies the ledger rows cite: still a pure projection.
    assert (
        DisplayPages(
            settings=SETTINGS,
            secrets=keyed,
            conn_factory=_factory_unused,  # type: ignore[arg-type]
        ).generates
        is False
    )
    off = Settings(_env_file=None, arv2_display_generate_on_read=False)
    assert (
        DisplayPages(
            settings=off,
            secrets=keyed,
            conn_factory=_factory_unused,  # type: ignore[arg-type]
        ).generates
        is False
    )


# -- (a) no runner: the page is composed from what is stored, and nothing is called -------------


def test_without_a_runner_the_page_is_the_stored_one_and_no_model_is_called() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            pages = _pages(conn)
            assert pages.generates is False

            read = await _contact_page(pages, conn, seeded)

            # The page grammar is fixed whether or not anything has been written into it.
            assert read.display_block["page"] == "contact"
            assert [section["key"] for section in _sections(read)] == list(CONTACT_SECTIONS)
            assert all(section["empty"] for section in _sections(read))
            assert read.generated == ()
            assert read.stale == ()
            assert read.cited_claim_ids == ()
            assert read.degraded_reason is None

    run_async(_run())


def test_a_runner_without_an_artifact_sink_serves_the_stored_page_and_calls_nothing() -> None:
    """Slice 1b: a ledger row cites the artifact its reply became, so a seam with no artifact
    store cannot record what a page would cost — it serves what is stored, exactly as a keyless
    deployment does, rather than spending money it cannot account for."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            # ``allowed=False`` raises if the provider is called at all — the runner really exists.
            transport = RoutingTransport(allowed=False)
            pages = _pages(conn, runner_factory=_factory(transport), artifacts=None)

            assert pages.generates is False, "a runner alone is not enough to write a page"

            read = await _contact_page(pages, conn, seeded)

            assert transport.sections == []
            assert read.generated == ()
            assert read.degraded_reason is None
            assert all(section["empty"] for section in _sections(read))
            assert read.cited_claim_ids == ()

    run_async(_run())


# -- (b) with a runner: the first read writes the page, the second serves it ---------------------


def test_the_first_read_generates_the_page_and_the_second_serves_it_unpaid() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            pages = _pages(conn, runner_factory=_factory(transport))
            assert pages.generates is True

            first = await _contact_page(pages, conn, seeded)
            assert first.generated == CONTACT_SECTIONS
            assert sorted(transport.sections) == sorted(CONTACT_SECTIONS)
            assert not any(section["empty"] for section in _sections(first))
            assert first.cited_claim_ids
            assert first.degraded_reason is None
            assert first.stale == ()

            served = _pages(conn, runner_factory=_factory(RoutingTransport(allowed=False)))
            again = await _contact_page(served, conn, seeded)
            assert again.generated == ()
            assert again.display_block == first.display_block
            assert again.cited_claim_ids == first.cited_claim_ids
            assert again.degraded_reason is None

    run_async(_run())


# -- (b2) generate=False: a stored-only read, with no spend and no side effect -------------------


def test_generation_can_be_refused_per_read_so_an_authorisation_check_never_spends() -> None:
    """``generate=False`` is a pure projection *whatever the seam is configured to do*.

    The evidence route asks this seam which claims a page cites in order to decide whether a
    caller may stream one. That question must not be a reason to write the page: an authorisation
    check that spends money is a denial-of-wallet, and one that schedules a background rewrite
    makes a GET unsafe to retry. So with a live runner in hand and every section unwritten, this
    read must call nothing, schedule nothing, and still answer honestly about what is stored.
    """

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            pages = _pages(conn, runner_factory=_factory(transport))
            assert pages.generates is True, "the runner really exists, or this proves nothing"

            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
                generate=False,
            )

            assert transport.sections == [], "no provider call may be made to authorise a read"
            assert read.generated == ()
            assert read.degraded_reason is None
            # The page grammar is still served, honestly empty.
            assert [section["key"] for section in _sections(read)] == list(CONTACT_SECTIONS)
            assert all(section["empty"] for section in _sections(read))
            assert read.cited_claim_ids == ()
            # Nothing was scheduled either: ``drain`` is a no-op because there is no task table.
            assert pages._regenerating == {}
            await pages.drain()
            assert transport.sections == []
            assert await _retired_blocks(conn, seeded.workspace_id) == 0

            # ...and the same seam still generates when a read asks it to, so the refusal is the
            # caller's decision and not a broken runner.
            paid = await _contact_page(pages, conn, seeded)
            assert paid.generated == CONTACT_SECTIONS

    run_async(_run())


def test_a_stale_page_read_with_generate_false_reports_staleness_and_schedules_nothing() -> None:
    """The other half of the no-side-effects promise: a stale section is *reported*, not repaired.

    A normal read schedules the background rewrite; a ``generate=False`` read must not, or an
    evidence request would keep paying for a page nobody asked to see.
    """

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            pages = _pages(conn, runner_factory=_factory(transport))
            written = await _contact_page(pages, conn, seeded)
            assert written.generated == CONTACT_SECTIONS

            # Move the research underneath the written page.
            await write_claim(
                conn,
                seeded.claims,
                label="fresh_hobby",
                workspace_id=seeded.workspace_id,
                entity_id=seeded.nick,
                entity_type=EntityType.CONTACT,
                field_key="contact.facet.hobby",
                value_json=["Restoring a 1972 Alfa Romeo"],
                extraction_method=ExtractionMethod.SCRAPE,
            )
            written_calls = len(transport.sections)

            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
                generate=False,
            )

            assert read.stale, "the page really is stale"
            assert read.generated == ()
            assert pages._regenerating == {}
            await pages.drain()
            assert len(transport.sections) == written_calls, "no rewrite was paid for"

    run_async(_run())


# -- (c) a halted provider degrades the page, it never breaks the request ------------------------


def test_a_halted_provider_serves_an_empty_page_and_names_the_reason() -> None:
    def _halted(raw: RawSink, ledger: LedgerSink) -> LunaSectionRunner:
        raise ProviderHalted("openrouter", "insufficient_credits")

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            pages = _pages(conn, runner_factory=_halted)

            read = await _contact_page(pages, conn, seeded)

            assert read.degraded_reason == "ProviderHalted"
            assert read.generated == ()
            assert read.cited_claim_ids == ()
            assert [section["key"] for section in _sections(read)] == list(CONTACT_SECTIONS)
            assert all(section["empty"] for section in _sections(read))

    run_async(_run())


# -- (d) staleness is repaired in the background, once ------------------------------------------


def test_a_stale_section_is_served_as_it_is_and_regenerated_in_the_background_once() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            pages = _pages(conn, runner_factory=_factory(transport))
            await _contact_page(pages, conn, seeded)
            assert sorted(transport.sections) == sorted(CONTACT_SECTIONS)

            # ``contact.facet.hobby`` belongs to the openers recipe and to no other contact
            # section, so exactly one section's research has moved underneath the page.
            await write_claim(
                conn,
                seeded.claims,
                label="hobby_new",
                workspace_id=seeded.workspace_id,
                entity_id=seeded.nick,
                entity_type=EntityType.CONTACT,
                field_key="contact.facet.hobby",
                value_json=["Runs a weekend bread-baking club"],
                signal_priority=2,
                evidence_span="my weekend bread club",
                extraction_method=ExtractionMethod.SCRAPE,
            )

            read = await _contact_page(pages, conn, seeded)
            # The request itself paid for nothing: the stale section was served exactly as written.
            assert read.generated == ()
            assert read.stale == ("openers",)
            assert transport.sections.count("openers") == 1
            assert await _retired_blocks(conn, seeded.workspace_id) == 0

            # A second ask while the first is in flight starts nothing (no await in between, so
            # the scheduled task has not yet had the loop).
            assert (
                pages.schedule_regeneration(
                    workspace_id=seeded.workspace_id,
                    subject_kind="contact",
                    subject_id=str(seeded.nick),
                    page="contact",
                )
                is False
            )

            await pages.drain()
            assert transport.sections.count("openers") == 2
            assert await _retired_blocks(conn, seeded.workspace_id) == 1

            # And the repaired page is no longer stale.
            after = await _contact_page(pages, conn, seeded)
            assert after.stale == ()
            assert after.generated == ()

    run_async(_run())


# -- (e) the committee builders ------------------------------------------------------------------


async def _seed_committee_facts(conn: AsyncConnection, seeded: Seeded) -> None:
    """The two claims the seed does not carry: an email for Nick, a committee role for each."""
    await write_claim(
        conn,
        seeded.claims,
        label="nick_email",
        workspace_id=seeded.workspace_id,
        entity_id=seeded.nick,
        entity_type=EntityType.CONTACT,
        field_key="core.work_email",
        value_json={"address": "nick@zafran.io", "status": "verified_smtp"},
        extraction_method=ExtractionMethod.API,
    )
    await write_claim(
        conn,
        seeded.claims,
        label="nick_role",
        workspace_id=seeded.workspace_id,
        entity_id=seeded.nick,
        entity_type=EntityType.CONTACT,
        field_key="contact.role_on_committee",
        value_json={"role": "economic_buyer", "rationale": "Owns the marketing budget"},
        extraction_method=ExtractionMethod.API,
    )


def test_the_buying_committee_is_persona_ordered_and_reads_through_the_display_predicate() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            await _seed_committee_facts(conn, seeded)

            members = await committee(
                conn, workspace_id=seeded.workspace_id, account_id=str(seeded.account)
            )
            # The economic buyer leads the champion; the contact with no claims is not a member.
            assert [member.name for member in members] == ["Nick Fisher", "Vari Bindra"]

            rows = await buying_committee(
                conn,
                workspace_id=seeded.workspace_id,
                account_id=str(seeded.account),
                members=members,
                policy=POLICY,
            )
            assert [row.contact_id for row in rows] == [str(seeded.nick), str(seeded.vari)]

            nick = rows[0]
            assert nick.name == "Nick Fisher"
            assert nick.title == "VP of Marketing"
            # Display text on the wire (D4-b decision 5), never the vocabulary value.
            assert nick.persona == "Economic buyer"
            assert nick.email == "nick@zafran.io"
            assert nick.email_claim_id == seeded.claims["nick_email"]
            assert nick.why_they_matter == "Owns the marketing budget"
            assert str(nick.linkedin_url) == "https://www.linkedin.com/in/nicholastfisher"

            # Vari has a persona and a LinkedIn URL, and nothing else: the required strings take
            # their documented placeholders rather than an invented title or reason.
            vari = rows[1]
            assert vari.persona == "Champion"
            assert vari.title == "—"
            assert vari.why_they_matter == "Committee member"
            assert vari.email is None and vari.email_claim_id is None

            chips = await rail_contacts(
                conn, workspace_id=seeded.workspace_id, members=members, policy=POLICY
            )
            assert [chip.id for chip in chips] == [str(seeded.nick), str(seeded.vari)]
            assert [chip.title for chip in chips] == ["VP of Marketing", None]
            assert [chip.persona for chip in chips] == ["Economic buyer", "Champion"]
            assert [chip.email_verified for chip in chips] == [True, False]
            assert all(chip.has_detail for chip in chips)

            # A provisional assessment must not reuse an old champion rationale or repeat
            # diagnostic codes in the user-facing explanation.
            gap = _membership_gap_text("current_affiliation_not_established")
            provisional = replace(
                members[0],
                persona="candidate",
                membership_state="candidate",
                membership_gaps=(gap,),
                outreach_eligible=False,
            )
            candidate = (
                await buying_committee(
                    conn,
                    workspace_id=seeded.workspace_id,
                    account_id=str(seeded.account),
                    members=[provisional],
                    policy=POLICY,
                )
            )[0]
            assert candidate.membership_gaps == (
                "Current employment at this company is unverified.",
            )
            assert candidate.why_they_matter == "Buying responsibility has not been established."
            assert not candidate.outreach_eligible

    run_async(_run())


def test_an_account_with_no_contacts_has_an_empty_committee() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            empty = uuid.uuid4()
            assert (
                await committee(conn, workspace_id=seeded.workspace_id, account_id=str(empty)) == []
            )
            assert (
                await buying_committee(
                    conn,
                    workspace_id=seeded.workspace_id,
                    account_id=str(empty),
                    members=[],
                    policy=POLICY,
                )
                == []
            )
            assert (
                await rail_contacts(
                    conn, workspace_id=seeded.workspace_id, members=[], policy=POLICY
                )
                == []
            )

    run_async(_run())


# -- (f) why a member matters --------------------------------------------------------------------
#
# Pure functions over one claim, so they need no database — but they live here, beside the builder
# that calls them, because the string they produce is a committee-card decision.


def _role_claim(**overrides: object) -> Claim:
    """One ``contact.role_on_committee`` claim, shaped as the lenient writer stores it."""
    base: dict[str, object] = {
        "entity_id": new_entity_id(),
        "entity_type": EntityType.CONTACT,
        "field_key": ROLE_KEY,
        "value_json": {"role": "economic_buyer", "rationale": "Owns the marketing budget."},
        "source_url": "https://zafran.io/team",
        "source_tier": 1,
        "extraction_method": ExtractionMethod.API,
        "confidence": 0.9,
        "run_id": new_run_id(),
        "research_mode": ResearchMode.CONTACT_PROFILING,
        "reuse_scope": ReuseScope.TENANT_PRIVATE,
        "workspace_id": WORKSPACE,
        "identity_binding": IdentityBinding.STRONG,
        "use_class": UseClass.PROFESSIONAL_PUBLIC,
    }
    base.update(overrides)
    return Claim(**base)  # type: ignore[arg-type]


def test_persona_label_names_the_vocabulary_and_nothing_else() -> None:
    assert [persona_label(persona) for persona in PERSONA_RANK] == [
        "Economic buyer",
        "Champion",
        "Technical evaluator",
        "User",
        "Blocker",
    ]
    assert persona_label(None) is None
    assert persona_label("procurement_gatekeeper") is None


def test_a_researched_rationale_is_served_verbatim() -> None:
    """The sentence a human wrote (or a model was made to justify) is the reason, unedited."""
    claim = _role_claim()
    assert (
        _why_they_matter(claim, title="VP of Marketing", persona="economic_buyer")
        == "Owns the marketing budget."
    )


def test_a_persona_derived_role_is_not_a_reason_and_reads_as_title_and_persona() -> None:
    """D4-b decision 4. The D1 loader derives a role for a person the run gave only a persona, and
    marks the row twice. Either mark is enough, because serving that sentence would put a reason on
    the card that is really just the persona chip beside it, spelled out."""
    marked = _role_claim(
        value_json={"role": "economic_buyer", "rationale": "VP of Marketing — something", "x": 1},
        write_markers={DERIVED_ROLE_MARKER: "row-17"},
    )
    phrased = _role_claim(
        value_json={
            "role": "economic_buyer",
            "rationale": f"VP of Marketing — {DERIVED_ROLE_RATIONALE_PHRASE} recorded by AI Ark",
        }
    )
    for claim in (marked, phrased):
        assert (
            _why_they_matter(claim, title="VP of Marketing", persona="economic_buyer")
            == "VP of Marketing · Economic buyer"
        )
        # With no title there is nothing honest to say beyond membership itself.
        assert (
            _why_they_matter(claim, title=None, persona="economic_buyer") == DEFAULT_WHY_THEY_MATTER
        )
        # Nor with a persona the vocabulary does not name.
        assert (
            _why_they_matter(claim, title="VP of Marketing", persona="kingmaker")
            == DEFAULT_WHY_THEY_MATTER
        )


def test_no_role_claim_and_an_empty_rationale_take_the_same_placeholder_path() -> None:
    empty = _role_claim(value_json={"role": "champion", "rationale": "   "})
    for claim in (None, empty):
        assert _why_they_matter(claim, title="Head of RevOps", persona="champion") == (
            "Head of RevOps · Champion"
        )
        assert _why_they_matter(claim, title=None, persona=None) == DEFAULT_WHY_THEY_MATTER


def test_the_derived_role_markers_are_the_ones_the_loader_actually_writes() -> None:
    """The read surface states the loader's two marks itself rather than importing a seed loader;
    this is the drift guard that keeps the two statements the same statement."""
    from clue_api.arv2 import answer_key_loader

    assert DERIVED_ROLE_RATIONALE_PHRASE in answer_key_loader._DERIVED_ROLE_RATIONALE
    source = Path(answer_key_loader.__file__).read_text(encoding="utf-8")
    assert f'"{DERIVED_ROLE_MARKER}": persona.source_row_id' in source


# -- (c2) a refused generation says WHY the sections are empty ----------------------------------


def test_a_refused_generation_leaves_the_empty_sections_saying_why() -> None:
    """The halt is classified once (Task 1) and every empty section carries the same sentence.

    A 403 naming a key limit is a *refusal* — no retry changes it — so the page says so rather
    than leaving a reader to guess why an account's overview is blank.
    """

    def _halted(raw: RawSink, ledger: LedgerSink) -> LunaSectionRunner:
        raise ProviderHalted("openrouter", "Key limit exceeded (weekly limit)", http_status=403)

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            pages = _pages(conn, runner_factory=_halted)

            read = await _contact_page(pages, conn, seeded)

            assert read.degraded_reason == "ProviderHalted"
            assert read.unavailable_message == (
                "Not generated: model provider refused (key limit exceeded). Retries automatically."
            )
            empties = [section for section in _sections(read) if section["empty"]]
            assert empties
            assert all(section["emptyMessage"] == read.unavailable_message for section in empties)

    run_async(_run())


def test_a_healthy_page_says_nothing_about_a_provider() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            pages = _pages(conn, runner_factory=_factory(RoutingTransport()))

            read = await _contact_page(pages, conn, seeded)

            assert read.unavailable_message is None
            assert all("emptyMessage" not in section for section in _sections(read))

    run_async(_run())


# -- (g) with a queue the seam schedules: it serves pending sections and offers page tasks -------


class _RecordingQueue:
    """The fleet's work queue, reduced to the one call the read seam makes."""

    def __init__(self, *, accept: bool = True) -> None:
        self.offers: list[dict[str, Any]] = []
        self._accept = accept

    async def enqueue(self, **kwargs: Any) -> bool:
        self.offers.append(kwargs)
        return self._accept


class _BrokenQueue:
    """A queue that is down — the read must still be served."""

    async def enqueue(self, **kwargs: Any) -> bool:
        raise RuntimeError("queue down")


async def _seed_run(conn: AsyncConnection, seeded: Seeded) -> uuid.UUID:
    """One ``arv2_research_run`` (and the ``project_run`` it hangs off) to hold person jobs."""
    project = await seed_project(conn, seeded.workspace_id, name="Display prewrite")
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="display",
        icp_version=1,
    )
    run_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO arv2_research_run (run_id, workspace_id, project_id, brand_id, "
            "project_run_id, icp_artifact_key, icp_artifact_sha256, icp_key, icp_version, "
            "product_selection_version, effort, committee_cap, profile_ref, profile_sha256, "
            "requested_by_user_id, request_sha256, status) "
            "VALUES (:run, :ws, :project, :brand, :project_run, :key, :sha, 'display', 1, "
            "1, 'full', 5, 'account-research@v1', :sha, :user, :request_sha, 'in_progress')"
        ),
        {
            "run": run_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "brand": project.brand_id,
            "project_run": project_run_id,
            "key": f"{project.workspace_id}/icp",
            "sha": "a" * 64,
            "user": "usr_display_prewrite",
            "request_sha": uuid.uuid4().hex + uuid.uuid4().hex,
        },
    )
    return run_id


async def _settle_job(conn: AsyncConnection, job_id: uuid.UUID) -> None:
    await finish_job(
        conn,
        job_id=job_id,
        status="completed",
        finalization={},
        model_rounds=0,
        tool_calls=0,
        cost_usd=Decimal(0),
        credits=Decimal(0),
        media_seconds=0,
    )


def test_with_a_queue_a_missing_page_is_served_pending_and_offered_never_written_inline() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport(allowed=False)
            queue = _RecordingQueue()
            pages = _pages(conn, runner_factory=_factory(transport), queue=queue)
            assert pages.schedules is True

            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
            )

            assert transport.sections == [], "a read with a queue never calls the model"
            assert read.generated == ()
            assert read.pending == CONTACT_SECTIONS
            for section in _sections(read):
                assert section["empty"] is True
                assert section["pending"] is True
                assert section["emptyMessage"] == PENDING_MESSAGE
            assert len(queue.offers) == 1
            offer = queue.offers[0]
            assert offer["kind"] is FleetTaskKind.ARV2_DISPLAY_PAGE
            assert offer["work_id"] == arv2_display_work_id("contact", str(seeded.nick), "contact")
            assert offer["dedup_key"] == f"{ARV2_DISPLAY_DEDUP_PREFIX}contact:{seeded.nick}:contact"
            assert offer["reopen_terminal"] is True
            assert offer["payload"]["page"] == "contact"
            assert pages._regenerating == {}
            assert await _retired_blocks(conn, seeded.workspace_id) == 0

    run_async(_run())


def test_a_section_that_matches_nothing_is_never_pending() -> None:
    """The placeholder is a promise, so only a section a write would fill may make it.

    The subject is a contact under an account that holds no claims either — the fixture's own
    ``silent`` is not enough, because every contact recipe also admits account keys and Zafran's
    account claims would fill four of this page's five sections for anybody standing under it.
    """

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            blank_account = await insert_account_entity(
                conn,
                canonical_name="Unresearched Ltd",
                primary_domain="unresearched.example",
                workspace_id=seeded.workspace_id,
            )
            nobody = await insert_contact_entity(
                conn,
                account_entity_id=blank_account,
                full_name="Nobody Atall",
                linkedin_url="https://www.linkedin.com/in/nobodyatall",
            )
            queue = _RecordingQueue()
            pages = _pages(
                conn, runner_factory=_factory(RoutingTransport(allowed=False)), queue=queue
            )

            # Neither this person nor their account holds a claim: no section can ever be written.
            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(nobody),
                page="contact",
            )

            assert read.pending == ()
            assert all(not section["pending"] for section in _sections(read))
            assert all("emptyMessage" not in section for section in _sections(read))
            assert queue.offers == [], "nothing to write, nothing offered"

    run_async(_run())


def test_an_offer_that_fails_serves_the_sections_honestly_empty() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            pages = _pages(
                conn, runner_factory=_factory(RoutingTransport(allowed=False)), queue=_BrokenQueue()
            )
            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
            )
            assert read.pending == ()
            assert all(not section["pending"] for section in _sections(read))

    run_async(_run())


def test_a_stored_page_with_a_stale_section_is_served_as_stored_and_the_page_is_offered() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            # Write the page the old way first (no queue), so every section is stored.
            written = await _pages(conn, runner_factory=_factory(transport)).page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
            )
            assert written.generated == CONTACT_SECTIONS
            calls_before = len(transport.sections)
            # A new claim under one recipe makes one section stale.
            await write_claim(
                conn,
                seeded.claims,
                label="nick_new_hobby",
                workspace_id=seeded.workspace_id,
                entity_id=seeded.nick,
                entity_type=EntityType.CONTACT,
                field_key="contact.facet.hobby",
                value_json=["Restoring a 1972 Alfa Romeo"],
                extraction_method=ExtractionMethod.SCRAPE,
            )

            queue = _RecordingQueue()
            pages = _pages(conn, runner_factory=_factory(transport), queue=queue)
            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
            )

            assert len(transport.sections) == calls_before, "served as stored, no rewrite inline"
            assert read.stale != ()
            assert read.pending == ()
            assert all(not section["empty"] for section in _sections(read))
            assert len(queue.offers) == 1 and queue.offers[0]["payload"]["page"] == "contact"
            assert pages._regenerating == {}

    run_async(_run())


def test_opening_an_account_offers_the_contact_pages_of_settled_members_once() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            # Nick has a settled person job; Vari has none.
            account_job, nick_job = uuid.uuid4(), uuid.uuid4()
            run_id = await _seed_run(conn, seeded)
            await create_job(
                conn,
                job_id=account_job,
                run_id=run_id,
                workspace_id=seeded.workspace_id,
                account_entity_id=uuid.UUID(str(seeded.account)),
            )
            await create_job(
                conn,
                job_id=nick_job,
                run_id=run_id,
                workspace_id=seeded.workspace_id,
                account_entity_id=uuid.UUID(str(seeded.account)),
                subject_type="person",
                subject_entity_id=uuid.UUID(str(seeded.nick)),
            )
            await _settle_job(conn, nick_job)

            queue = _RecordingQueue()
            pages = _pages(
                conn, runner_factory=_factory(RoutingTransport(allowed=False)), queue=queue
            )
            await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(seeded.account),
                page="overview",
            )
            contact_offers = [o for o in queue.offers if o["payload"]["subject_kind"] == "contact"]
            assert [o["payload"]["subject_id"] for o in contact_offers] == [str(seeded.nick)]
            assert contact_offers[0]["payload"]["job_id"] == str(nick_job)

            # A second open inside the cooldown offers no contact page again.
            await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(seeded.account),
                page="insights",
            )
            assert len([o for o in queue.offers if o["payload"]["subject_kind"] == "contact"]) == 1

            # A member whose page exists is skipped: write Nick's page, clear the cooldown, reopen.
            await _pages(conn, runner_factory=_factory(RoutingTransport())).page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
            )
            pages._contact_offers.clear()
            await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(seeded.account),
                page="overview",
            )
            assert len([o for o in queue.offers if o["payload"]["subject_kind"] == "contact"]) == 1

    run_async(_run())


# -- shared blocks: a sharer is never pending, and a stale OWNER page is what gets offered -------


def test_a_shared_section_renders_its_owner_is_never_pending_and_re_offers_a_stale_owner() -> None:
    """Spec 2026-09-12 §3. ``context-only`` owns no block: it shows the overview's ``watch-outs``.

    So a read of the insights page must (a) serve those words rather than an empty section,
    (b) never mark the section pending — this page's task would not write it — and (c) when the
    owner's block has gone stale, offer the OWNER's page, on the owner's subject.
    """

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            # The owner page first, written inline with no queue.
            await _pages(conn, runner_factory=_factory(RoutingTransport())).page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(seeded.account),
                page="overview",
            )
            # A newer claim on a ``watch-outs`` key: the OWNER's block is now stale.
            await write_claim(
                conn,
                seeded.claims,
                label="newer_reputation_risk",
                workspace_id=seeded.workspace_id,
                entity_id=seeded.account,
                entity_type=EntityType.ACCOUNT,
                field_key="account.reputation_risk",
                value_json={"what": "A second dispute", "status": "open"},
                signal_priority=3,
                outreach_safe=False,
                evidence_span="a second unresolved dispute",
                extraction_method=ExtractionMethod.SCRAPE,
            )

            queue = _RecordingQueue()
            pages = _pages(
                conn, runner_factory=_factory(RoutingTransport(allowed=False)), queue=queue
            )
            read = await pages.page(
                conn,
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(seeded.account),
                page="insights",
            )

            sections = {section["key"]: section for section in _sections(read)}
            assert sections["context-only"]["empty"] is False, "the owner's body is rendered here"
            assert "context-only" not in read.pending
            assert sections["context-only"]["pending"] is False
            # The sharer is never reported stale on this page — the owner's page owns that.
            assert "context-only" not in read.stale
            offered = {(o["payload"]["subject_kind"], o["payload"]["page"]) for o in queue.offers}
            assert ("account", "overview") in offered, "the stale OWNER page is re-offered"

    run_async(_run())
