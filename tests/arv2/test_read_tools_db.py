"""The Head of ABM's read tools against the real rows they answer from.

What would rot silently here is a *number*: an account list that quietly includes a merge loser,
a status read off a person job, or a "refreshing" flag that fires the first time an account is
researched. Each of those reads as a confident wrong sentence in the chat rather than as an error,
so the rows are seeded by hand and the derived answers are asserted against them.

The same standard governs one account's research: a superseded claim served as current truth, a
retired page section served as this week's words, or an unwritten overview served as an empty one
are all sentences the agent would say without hesitating. And the same again for a discovery run,
whose verified/shown/approved tallies are three derivations over one candidate table.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.claim_writer import TIER_FOR_METHOD
from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.arv2.read_tools import (
    EVIDENCE_CHARS,
    MAX_CANDIDATES,
    READ_REFERENCES_BUDGET_BYTES,
    Arv2ReadRefused,
    list_project_accounts,
    read_account_research,
    read_cited_claims,
    read_claims,
    read_discovery_run,
    receipt_bytes,
)
from clue_api.frontend_read.v1_shared import arv2_research_status_for
from clue_config import Settings
from clue_core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    UseClass,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import insert_claim
from clue_research.durable import ensure_project_run
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.membership import ensure_project_account
from clue_spine import Project

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests._workspace import seed_project

# The lenient-writer seeding helper the D2 display fixture already owns — claims written the way
# production writes them, rather than a second hand-rolled INSERT.
from tests.arv2.display._seed import write_claim
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_arv2_read_tools"
USER_ID = "usr_arv2_read_tools"
_SHA = "a" * 64
_NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)

#: The claims read mirrors the account page's display gate, and one arm of that gate is armed by
#: this flag — so the two postures are both exercised, exactly as ``test_gather_db`` exercises them.
VERIFYING = Settings(_env_file=None, verification_enabled=True)
PERMISSIVE = Settings(_env_file=None, verification_enabled=False)


#: Every seeded account gets a distinct ``created_at``, ascending in seed order.
#:
#: ``account_entity.created_at`` defaults to ``now()``, which is the TRANSACTION's clock — so every
#: account a test seeds inside one ``rollback_conn`` shares one timestamp and the listing's
#: ``created_at DESC, id DESC`` order falls through to a random uuid. Stamping the column makes
#: "newest first" mean "last seeded first", which is what these tests are actually asserting.
_SEED_CLOCK = _NOW


async def _seed_account(
    conn: AsyncConnection,
    project: Project,
    name: str,
    *,
    added_via: str = "manual",
    created_at: datetime | None = None,
) -> EntityId:
    global _SEED_CLOCK
    account_id = await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=f"{name.lower().replace(' ', '-')}.example",
        workspace_id=project.workspace_id,
    )
    if created_at is None:
        _SEED_CLOCK += timedelta(minutes=1)
        created_at = _SEED_CLOCK
    await conn.execute(
        text("UPDATE account_entity SET created_at = CAST(:at AS timestamptz) WHERE id = :id"),
        {"at": created_at, "id": account_id},
    )
    await ensure_project_account(
        conn,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        account_entity_id=account_id,
        added_via=added_via,
    )
    return account_id


async def _seed_research_run(conn: AsyncConnection, project: Project) -> UUID:
    """One ``arv2_research_run`` (plus the ``project_run`` it hangs off) to hold jobs."""

    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="gi-groups",
        icp_version=1,
    )
    run_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO arv2_research_run (run_id, workspace_id, project_id, brand_id, "
            "project_run_id, icp_artifact_key, icp_artifact_sha256, icp_key, icp_version, "
            "product_selection_version, effort, committee_cap, profile_ref, profile_sha256, "
            "requested_by_user_id, request_sha256, status) "
            "VALUES (:run, :ws, :project, :brand, :project_run, :key, :sha, 'gi-groups', 1, "
            "1, 'full', 5, 'account-research@v1', :sha, :user, :request_sha, 'in_progress')"
        ),
        {
            "run": run_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "brand": project.brand_id,
            "project_run": project_run_id,
            "key": f"{project.workspace_id}/icp",
            "sha": _SHA,
            "user": USER_ID,
            "request_sha": uuid4().hex + uuid4().hex,
        },
    )
    return run_id


async def _seed_job(
    conn: AsyncConnection,
    project: Project,
    run_id: UUID,
    account_id: EntityId,
    *,
    status: str,
    subject_type: str = "account",
    created_at: datetime,
) -> None:
    # ``arv2_research_job_finished`` makes the terminal statuses and ``finished_at`` biconditional,
    # ``arv2_research_job_failure`` does the same for ``needs_review`` and a failure code, and
    # ``arv2_research_job_subject`` for a person job and its contact.
    await conn.execute(
        text(
            "INSERT INTO arv2_research_job (job_id, run_id, workspace_id, account_entity_id, "
            "status, subject_type, subject_entity_id, created_at, finished_at, failure_code) "
            "VALUES (:job, :run, :ws, :account, :status, :subject_type, :subject_entity, "
            "CAST(:created_at AS timestamptz), "
            "CASE WHEN :status IN ('completed', 'needs_review') "
            "THEN CAST(:created_at AS timestamptz) END, "
            "CASE WHEN :status = 'needs_review' THEN 'profile_pin_mismatch' END)"
        ),
        {
            "job": uuid4(),
            "run": run_id,
            "ws": project.workspace_id,
            "account": account_id,
            "status": status,
            "subject_type": subject_type,
            "subject_entity": uuid4() if subject_type == "person" else None,
            "created_at": created_at,
        },
    )


def test_the_account_list_carries_the_latest_status_and_the_refreshing_flag() -> None:
    """An account researched once and running again is *refreshing*; one with no job never was."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            researched = await _seed_account(conn, project, "Alpha Health", added_via="discovered")
            untouched = await _seed_account(conn, project, "Beta Clinic", added_via="imported")

            first_run = await _seed_research_run(conn, project)
            second_run = await _seed_research_run(conn, project)
            await _seed_job(
                conn,
                project,
                first_run,
                researched,
                status="completed",
                created_at=_NOW - timedelta(days=2),
            )
            await _seed_job(
                conn, project, second_run, researched, status="in_progress", created_at=_NOW
            )
            # A person job on the *untouched* account: people share this table and the account
            # column, and a contact being researched is not the account being researched.
            await _seed_job(
                conn,
                project,
                second_run,
                untouched,
                status="in_progress",
                subject_type="person",
                created_at=_NOW,
            )

            page = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=100,
            )

            assert page.project_id == project.project_id
            assert page.total == 2
            # Newest first — the accounts screen's own default order (`created_at DESC, id DESC`),
            # so "the first ten accounts" means the same ten to the agent and to the marketer.
            beta, alpha = page.accounts
            assert (alpha.account_entity_id, alpha.name) == (str(researched), "Alpha Health")
            assert alpha.domain == "alpha-health.example"
            assert (alpha.research_status, alpha.refreshing) == ("in_progress", True)
            assert alpha.added_via == "discovered"
            assert alpha.added_at.startswith("20")
            assert (beta.name, beta.research_status, beta.refreshing) == (
                "Beta Clinic",
                "not_started",
                False,
            )
            assert beta.added_via == "imported"

    run_async(scenario())


def test_a_first_research_run_is_not_a_refresh() -> None:
    """``refreshing`` means "already researched, being researched again" — not "running"."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            run_id = await _seed_research_run(conn, project)
            await _seed_job(conn, project, run_id, account, status="in_progress", created_at=_NOW)

            # A second account whose live job came *before* the completed one — an abandoned run
            # followed by a finished one. It is researched and idle, not refreshing: the order of
            # the two jobs is what decides, not the fact that both exist.
            settled = await _seed_account(conn, project, "Beta Clinic")
            abandoned = await _seed_research_run(conn, project)
            finished = await _seed_research_run(conn, project)
            await _seed_job(
                conn,
                project,
                abandoned,
                settled,
                status="in_progress",
                created_at=_NOW - timedelta(days=3),
            )
            await _seed_job(conn, project, finished, settled, status="completed", created_at=_NOW)

            page = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=100,
            )

            beta, alpha = page.accounts
            assert (alpha.research_status, alpha.refreshing) == ("in_progress", False)
            assert (beta.research_status, beta.refreshing) == ("completed", False)

    run_async(scenario())


def test_a_merge_loser_and_another_project_s_accounts_are_not_this_project_s_accounts() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            survivor = await _seed_account(conn, project, "Alpha Health")
            loser = await _seed_account(conn, project, "Alpha Health Group")
            await conn.execute(
                text(
                    "UPDATE account_entity SET merged_into = :survivor, status = 'merged' "
                    "WHERE id = :loser"
                ),
                {"survivor": survivor, "loser": loser},
            )
            # A second project in the same workspace, with an account of its own.
            other = await seed_project(conn, WORKSPACE, name="Other project")
            await _seed_account(conn, other, "Gamma Surgery")

            page = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=100,
            )

            assert [account.name for account in page.accounts] == ["Alpha Health"]
            # The total counts what the listing can show, so "showing N of total" measures one
            # population: the merge loser is off the page and out of the count alike.
            assert page.total == 1

    run_async(scenario())


def test_the_page_is_bounded_and_the_total_is_not() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            await _seed_account(conn, project, "Alpha Health")
            await _seed_account(conn, project, "Beta Clinic")

            page = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=1,
            )

            assert [account.name for account in page.accounts] == ["Beta Clinic"]
            assert page.total == 2

            # …and the second page reaches the tail rather than leaving it unreachable.
            second = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=1,
                offset=1,
            )
            assert [account.name for account in second.accounts] == ["Alpha Health"]
            assert second.total == 2

    run_async(scenario())


def test_a_named_account_is_reachable_by_query_and_the_tail_by_offset() -> None:
    """I3: without a filter, an account past the first page is unreachable — and the model, told
    never to speak about an account from memory, would say it is not in the project."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            await _seed_account(conn, project, "Alpha Health")
            await _seed_account(conn, project, "Zeta Surgical")

            by_name = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=100,
                query="zeta surg",
            )
            assert [account.name for account in by_name.accounts] == ["Zeta Surgical"]
            # The total measures the FILTERED population, so "1 of 1" is not "1 of 2".
            assert by_name.total == 1

            by_domain = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=100,
                query="ALPHA-HEALTH.EXAMPLE",
            )
            assert [account.name for account in by_domain.accounts] == ["Alpha Health"]

            # A LIKE metacharacter is a character the human typed, not a pattern they wrote.
            wildcard = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=100,
                query="%",
            )
            assert wildcard.accounts == ()
            assert wildcard.total == 0

            # A filter that matches nothing is an empty page of the project, not a refusal: the
            # project is ours and it IS this list — there is just no account by that name.
            missing = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=100,
                query="Goodman Campbell",
            )
            assert (missing.accounts, missing.total) == ((), 0)

    run_async(scenario())


def test_the_list_order_is_the_accounts_screen_s_own_default() -> None:
    """M1: "the first ten accounts" must mean the same ten in chat and on the table."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            # Seeded oldest-first and alphabetically ascending, so an alphabetical order and the
            # screen's ``created_at DESC`` order are each other's reverse — no test passes by luck.
            for name in ("Alpha Health", "Beta Clinic", "Gamma Surgery"):
                await _seed_account(conn, project, name)

            page = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=100,
            )

            assert [account.name for account in page.accounts] == [
                "Gamma Surgery",
                "Beta Clinic",
                "Alpha Health",
            ]

    run_async(scenario())


def test_a_created_at_tie_breaks_on_the_job_id_the_accounts_screen_breaks_on() -> None:
    """M1: two account jobs written in one statement must not read `refreshing: false` here and
    "Refreshing" on the screen — both order latest by `(created_at, job_id)`, so both break the
    "an earlier run completed" test the same way."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            # One job per run per account (`arv2_research_job_subject_once`), so two runs.
            first = await _seed_research_run(conn, project)
            second = await _seed_research_run(conn, project)
            # ONE timestamp for both jobs — a completed job superseded and a new one queued in the
            # same transaction, with `now()` frozen.
            await _seed_job(conn, project, first, account, status="completed", created_at=_NOW)
            await _seed_job(conn, project, second, account, status="in_progress", created_at=_NOW)

            page = await list_project_accounts(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=100,
            )

            (alpha,) = page.accounts
            screen = await arv2_research_status_for(
                conn, workspace_id=project.workspace_id, account_ids=[account]
            )
            # Whatever the tie decides, the chat read and the accounts screen decide it together.
            assert (alpha.research_status, alpha.refreshing) == screen[account]

    run_async(scenario())


def test_a_project_this_workspace_cannot_see_is_refused_by_name() -> None:
    """Another tenant's project is not an empty project — an empty list here would be a lie."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            foreign = await seed_project(conn, "ws_arv2_read_tools_other", name="Foreign")
            await _seed_account(conn, foreign, "Alpha Health")

            with pytest.raises(Arv2ReadRefused) as refused:
                await list_project_accounts(
                    conn,
                    workspace_id=WORKSPACE,
                    project_id=foreign.project_id,
                    limit=100,
                )
            assert refused.value.code == "project_not_found"

            with pytest.raises(Arv2ReadRefused) as unknown:
                await list_project_accounts(
                    conn, workspace_id=WORKSPACE, project_id="prj_nonexistent", limit=100
                )
            assert unknown.value.code == "project_not_found"

    run_async(scenario())


# -- read 2: one account's research ---------------------------------------------------------------


async def _seed_block(
    conn: AsyncConnection,
    project: Project,
    account_id: EntityId,
    *,
    section_key: str,
    body: dict[str, object],
    cited: tuple[UUID, ...] = (),
) -> None:
    """One live ``display_block`` for the account's overview page."""

    await conn.execute(
        text(
            "INSERT INTO display_block (workspace_id, subject_kind, subject_id, page, "
            "section_key, body_json, cited_claim_ids, model, prompt_version, recipe_version, "
            "generated_at) VALUES (:ws, 'account', :subject, 'overview', :section, "
            "CAST(:body AS jsonb), CAST(:cited AS uuid[]), 'luna', 'v1+v1', 1, "
            "CAST(:now AS timestamptz))"
        ),
        {
            "ws": project.workspace_id,
            "subject": account_id,
            "section": section_key,
            "body": json.dumps(body),
            "cited": list(cited),
            "now": _NOW,
        },
    )


async def _seed_claim(
    conn: AsyncConnection,
    claims: dict[str, str],
    project: Project,
    account_id: EntityId,
    *,
    label: str,
    field_key: str,
    value: Any,
    **overrides: Any,
) -> UUID:
    await write_claim(
        conn,
        claims,
        label=label,
        workspace_id=project.workspace_id,
        entity_id=account_id,
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=value,
        **overrides,
    )
    return UUID(claims[label])


def test_the_overview_read_serves_the_written_sections_in_the_page_s_own_order() -> None:
    """Recipe order, not alphabetical: the agent reads the page the marketer sees."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            await load_display_recipes(conn)
            account = await _seed_account(conn, project, "Alpha Health")
            cited = uuid4()
            # Inserted in the order that is *wrong* for the page and right alphabetically, so a
            # read that forgot the recipes would come back in the seeded order and pass by luck.
            await _seed_block(
                conn,
                project,
                account,
                section_key="buying-committee",
                body={"intro": [], "items": [{"text": "Two VPs and a director."}]},
                cited=(cited,),
            )
            await _seed_block(
                conn,
                project,
                account,
                section_key="why-now",
                body={"intro": [], "items": [{"text": "They opened four ABM roles."}]},
            )
            # A superseded block of a third section is last week's page, not this one.
            await _seed_block(
                conn, project, account, section_key="why-they-fit", body={"items": []}
            )
            await conn.execute(
                text(
                    "UPDATE display_block SET superseded_at = CAST(:now AS timestamptz) "
                    "WHERE section_key = 'why-they-fit'"
                ),
                {"now": _NOW},
            )

            research = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="overview",
                settings=VERIFYING,
            )

            assert (research.account_entity_id, research.account_name) == (
                str(account),
                "Alpha Health",
            )
            assert research.section == "overview"
            assert [section.section_key for section in research.overview] == [
                "why-now",
                "buying-committee",
            ]
            # The body is the app's own shape, serialized and bounded rather than nested — an
            # overview body has no length of its own, and this read is context the model pays for.
            assert research.overview[0].body_text == (
                '{"intro": [], "items": [{"text": "They opened four ABM roles."}]}'
            )
            assert research.overview[0].body_truncated is False
            assert research.overview[1].cited_claim_ids == (str(cited),)
            assert research.overview[0].generated_at.startswith("2026-09-12T12:00:00")
            # The unasked half is empty rather than absent.
            assert (research.claims, research.truncated) == ((), False)

    run_async(scenario())


def test_the_claims_read_serves_the_live_claims_clipped_and_filtered() -> None:
    """A superseded claim is not what we know now, and a quote is clipped to be checked."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            long_span = "They opened four ABM roles. " * 20  # far past the clip
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="requisitions",
                field_key="account.open_requisitions",
                value=[{"title": "ABM Manager"}],
                evidence_span=long_span,
                source_url="https://alpha.example/careers",
            )
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="culture",
                field_key="account.resonance.buying_culture",
                value="Committee-led, slow to sign",
                evidence_span="every purchase goes to a committee",
            )
            stale = await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="stale_culture",
                field_key="account.resonance.buying_culture",
                value="Founder-led",
            )
            fresh = UUID(claims["culture"])
            await conn.execute(
                text("UPDATE claim SET superseded_by = :new WHERE id = :old"),
                {"new": fresh, "old": stale},
            )

            research = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=VERIFYING,
            )

            assert research.section == "claims"
            assert research.overview == ()
            assert research.truncated is False
            # Ordered by field key; the superseded value is gone.
            assert [claim.field_key for claim in research.claims] == [
                "account.open_requisitions",
                "account.resonance.buying_culture",
            ]
            requisitions, culture = research.claims
            assert requisitions.claim_id == claims["requisitions"]
            assert requisitions.value == [{"title": "ABM Manager"}]
            assert requisitions.source_url == "https://alpha.example/careers"
            # Clipped, and SAID to be clipped: a partial quote presented as a whole one is the
            # one dishonesty a verifiability-first system cannot afford.
            assert len(requisitions.evidence) == EVIDENCE_CHARS
            assert requisitions.evidence == long_span[: EVIDENCE_CHARS - 1] + "…"
            assert requisitions.evidence_truncated is True
            assert culture.evidence_truncated is False
            assert culture.evidence == "every purchase goes to a committee"
            assert requisitions.tier == 2  # stamped from the scrape method, not chosen
            assert (requisitions.verification_status, requisitions.outreach_safe) == (
                "unverified",
                True,
            )
            # Nothing was held back on this account, and the counts say so rather than being absent.
            assert research.excluded == {"sensitive": 0, "unverified": 0, "outreach_unsafe": 0}
            assert requisitions.collected_at.startswith("20")
            assert culture.value == "Committee-led, slow to sign"

            narrowed = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                field_prefix="account.resonance",
                settings=VERIFYING,
            )
            assert [claim.claim_id for claim in narrowed.claims] == [claims["culture"]]

    run_async(scenario())


def test_the_claims_read_holds_back_exactly_what_the_account_page_holds_back() -> None:
    """I1 / ruling Q: chat may not print a fact the account page deliberately refuses to print.

    One claim of each excluded class, and one VERIFIED tier-4 synthesis that must survive — because
    the failure this guards is not "drop tier 4", it is "drop the tier-4 rows nobody judged".
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="plain",
                field_key="account.open_requisitions",
                value=[{"title": "ABM Manager"}],
            )
            # (a) special-category: never leaves the store, for any section.
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="sensitive",
                field_key="account.resonance.buying_culture",
                value="A fact about the founder's health",
                use_class=UseClass.SENSITIVE,
            )
            # (b) tier-4 synthesis nobody judged: the least-trusted class in the platform.
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="unjudged",
                field_key="account.strategic_moves",
                value="Probably opening a second site",
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                evidence_span="hiring for a second site",
            )
            # (c) the same class, JUDGED — this one is a fact and must be served, with its status.
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="judged",
                field_key="account.strategic_moves",
                value="Opened a New York office in June 2026",
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                evidence_span="opened a New York office",
            )
            await conn.execute(
                text("UPDATE claim SET verification_status = 'verified' WHERE id = :id"),
                {"id": UUID(claims["judged"])},
            )
            # (d) outreach-unsafe: this read has no restricted section to put one in.
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="unsafe",
                field_key="account.reputation_risk",
                value={"what": "An unresolved customer dispute"},
                outreach_safe=False,
            )

            research = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=VERIFYING,
            )

            served = {claim.claim_id for claim in research.claims}
            assert served == {claims["plain"], claims["judged"]}
            assert research.excluded == {
                "sensitive": 1,
                "unverified": 1,
                "outreach_unsafe": 1,
            }
            judged = next(claim for claim in research.claims if claim.claim_id == claims["judged"])
            assert (judged.tier, judged.verification_status) == (4, "verified")
            assert judged.outreach_safe is True

            # The tier-4 arm is the posture's, exactly as it is on the page: with verification off,
            # the unjudged synthesis is served and the other two exclusions still hold.
            permissive = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=PERMISSIVE,
            )
            assert {claim.claim_id for claim in permissive.claims} == {
                claims["plain"],
                claims["judged"],
                claims["unjudged"],
            }
            assert permissive.excluded == {
                "sensitive": 1,
                "unverified": 0,
                "outreach_unsafe": 1,
            }

    run_async(scenario())


def test_with_verification_off_findings_and_narratives_are_served_and_real_rules_hold() -> None:
    """Founder ruling 2026-10-09: a research finding or a value narrative is born outreach-unsafe
    only because nobody has verified it yet. While verification is off, the claims read serves
    them. A claim held back by a real rule (here a reputation risk) stays held back either way."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="finding",
                field_key="account.research_finding",
                value={"topic": "Budget", "finding": "Healthcare up $4.2 million", "notes": []},
                outreach_safe=False,
            )
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="narrative",
                field_key="account.value_narrative",
                value={"persona": "economic_buyer", "argument": "Cut specialty waste in network"},
                outreach_safe=False,
            )
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="risk",
                field_key="account.reputation_risk",
                value={"what": "An unresolved customer dispute"},
                outreach_safe=False,
            )

            permissive = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=PERMISSIVE,
            )
            unverified_only = {claims["finding"], claims["narrative"]}
            assert {c.claim_id for c in permissive.claims} == unverified_only
            assert permissive.excluded == {
                "sensitive": 0,
                "unverified": 0,
                "outreach_unsafe": 1,
            }

            query = await read_claims(
                conn,
                workspace_id=project.workspace_id,
                entity_id=str(account),
                settings=PERMISSIVE,
            )
            assert {c.claim_id for c in query.claims} == unverified_only

            verifying = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=VERIFYING,
            )
            assert verifying.claims == ()
            assert verifying.excluded == {
                "sensitive": 0,
                "unverified": 0,
                "outreach_unsafe": 3,
            }

    run_async(scenario())


def test_the_claims_read_fits_the_governed_receipt_and_pages_the_rest() -> None:
    """The 2026-09-13 live defect: 72 claims built a valid result the runtime then refused
    ("bounded operation receipt exceeds 16 KiB"). The read now stops at the byte budget, says so,
    and names the offset the next call continues from."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            # ~400 bytes of evidence each: 72 of them is ~30 KiB, the shape of the live account.
            for index in range(72):
                await _seed_claim(
                    conn,
                    claims,
                    project,
                    account,
                    label=f"claim_{index}",
                    field_key=f"account.open_requisitions.role_{index:03d}",
                    value={"title": f"Role {index}", "posted": "2026-09-01"},
                    evidence_span=("Hiring now: " + ("clinical staff, ") * 24).strip(),
                    source_url=f"https://alpha.example/jobs/{index}",
                )

            first = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=VERIFYING,
            )
            assert first.truncated is True
            assert first.offset == 0
            assert first.next_offset is not None and 0 < first.next_offset < 72
            assert len(first.claims) == first.next_offset
            assert receipt_bytes([view.model_dump() for view in first.claims]) <= (
                READ_REFERENCES_BUDGET_BYTES
            )

            # Walk the rest: the pages partition the kept claims, in order, without overlap.
            seen = [view.claim_id for view in first.claims]
            offset = first.next_offset
            while offset is not None:
                page = await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="claims",
                    settings=VERIFYING,
                    offset=offset,
                )
                assert page.offset == offset
                seen.extend(view.claim_id for view in page.claims)
                offset = page.next_offset
            assert len(seen) == 72 and len(set(seen)) == 72

    run_async(scenario())


def test_the_claims_page_ends_at_whichever_ceiling_binds_first() -> None:
    """Two ceilings, not one: the byte budget is the substrate's, and ``limit`` is the caller's.

    The budget alone cannot express "give me five claims, I only want to quote a couple" — a model
    that wants three facts about an account still pays for every claim that fits in 12 KiB, on
    this turn and every later one. ``read_account_research@2`` asks for a page; the budget still
    binds first whenever the claims are large.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            # Twelve small claims: well inside the byte budget, so ``limit`` is the binding one.
            for index in range(12):
                await _seed_claim(
                    conn,
                    claims,
                    project,
                    account,
                    label=f"claim_{index}",
                    field_key=f"account.open_requisitions.role_{index:03d}",
                    value={"title": f"Role {index}"},
                    evidence_span=f"Hiring a Role {index}.",
                    source_url=f"https://alpha.example/jobs/{index}",
                )

            first = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=VERIFYING,
                limit=5,
            )

            assert len(first.claims) == 5
            assert (first.offset, first.next_offset) == (0, 5)
            # Five of twelve is more to come, and the read says so rather than reading complete.
            assert first.truncated is True

            # The pages partition the account's servable claims, in order, without overlap.
            seen = [view.claim_id for view in first.claims]
            walked = [view.field_key for view in first.claims]
            sizes = [len(first.claims)]
            offset = first.next_offset
            while offset is not None:
                page = await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="claims",
                    settings=VERIFYING,
                    offset=offset,
                    limit=5,
                )
                assert page.offset == offset
                seen.extend(view.claim_id for view in page.claims)
                walked.extend(view.field_key for view in page.claims)
                sizes.append(len(page.claims))
                offset = page.next_offset
            assert sizes == [5, 5, 2]
            assert len(seen) == 12 and len(set(seen)) == 12
            # One list read three times, not three lists: the walk is the store's own field order.
            assert walked == [f"account.open_requisitions.role_{index:03d}" for index in range(12)]

            # The other ceiling still binds when it is the smaller one: forty large claims asked
            # for at once come back as whatever fits in the receipt, with the rest offered.
            for index in range(40):
                await _seed_claim(
                    conn,
                    claims,
                    project,
                    account,
                    label=f"big_{index}",
                    field_key=f"account.strategic_moves.move_{index:03d}",
                    value={"summary": f"Move {index}", "posted": "2026-09-01"},
                    evidence_span=("They are expanding: " + ("new clinics, ") * 24).strip(),
                    source_url=f"https://alpha.example/news/{index}",
                )

            budgeted = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                field_prefix="account.strategic_moves",
                settings=VERIFYING,
                limit=40,
            )

            assert 0 < len(budgeted.claims) < 40
            assert budgeted.next_offset == len(budgeted.claims)
            assert receipt_bytes([view.model_dump() for view in budgeted.claims]) <= (
                READ_REFERENCES_BUDGET_BYTES
            )

    run_async(scenario())


def test_an_account_whose_every_claim_is_held_back_reads_empty_with_its_counts() -> None:
    """The gate now runs before the prefix filter, and an unnarrowed read must not turn that into
    a refusal: "there is something here and you may not have it" is the whole point of ``excluded``.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="sensitive",
                field_key="account.resonance.buying_culture",
                value="A fact about the founder's health",
                use_class=UseClass.SENSITIVE,
            )

            research = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=VERIFYING,
            )
            assert research.claims == ()
            assert research.excluded == {"sensitive": 1, "unverified": 0, "outreach_unsafe": 0}
            # No servable claim, so no family is advertised either.
            assert research.prefixes == {}

    run_async(scenario())


def test_a_prefix_that_matches_nothing_is_refused_with_the_prefixes_that_exist() -> None:
    """The live turn asked for ``firmographic`` and was told only that nothing matched."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="a",
                field_key="core.legal_name",
                value="Alpha Health LLC",
            )
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="b",
                field_key="account.resonance.culture",
                value="warm",
            )
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="c",
                field_key="account.resonance.frustrations",
                value="fax",
            )

            with pytest.raises(Arv2ReadRefused) as refused:
                await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="claims",
                    settings=VERIFYING,
                    field_prefix="firmographic",
                )
            assert refused.value.code == "no_claims_under_prefix"
            # Naming the families is the whole fix: the live turn guessed a second prefix because
            # the refusal told it only that its first guess was wrong.
            assert "account.resonance (2)" in str(refused.value)
            assert "core.legal_name (1)" in str(refused.value)

    run_async(scenario())


def test_the_claims_read_names_the_account_s_claim_families() -> None:
    """A narrowed page still says what else the account holds, so the model need not guess."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="a",
                field_key="core.legal_name",
                value="Alpha Health LLC",
            )
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="b",
                field_key="account.resonance.culture",
                value="warm",
            )

            research = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                settings=VERIFYING,
                field_prefix="core",
            )
            # The families are the whole account's, so a narrowed page still shows what else exists.
            assert research.prefixes == {"account.resonance": 1, "core.legal_name": 1}
            assert [view.field_key for view in research.claims] == ["core.legal_name"]

    run_async(scenario())


def test_a_long_overview_pages_by_whole_section_and_loses_nothing() -> None:
    """A long overview is read across pages, never cut: each page holds whole sections."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            await load_display_recipes(conn)
            account = await _seed_account(conn, project, "Alpha Health")
            # Nothing in the display package caps `items`. One of these is under a page on its
            # own (the old 6000-character section cap clipped it); three are past one page.
            long_body = {"items": [{"text": "They opened four ABM roles. " * 400}]}
            keys = ("why-now", "why-they-fit", "buying-committee")
            for section_key in keys:
                await _seed_block(conn, project, account, section_key=section_key, body=long_body)

            seen: list[str] = []
            offset = 0
            pages = 0
            while True:
                page = await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="overview",
                    settings=VERIFYING,
                    offset=offset,
                )
                pages += 1
                assert page.offset == offset
                assert receipt_bytes([s.model_dump() for s in page.overview]) <= (
                    READ_REFERENCES_BUDGET_BYTES
                )
                for section in page.overview:
                    # Served whole: the body is the stored JSON, untouched.
                    assert section.body_truncated is False
                    assert json.loads(section.body_text) == long_body
                    seen.append(section.section_key)
                assert page.truncated is (page.next_offset is not None)
                if page.next_offset is None:
                    break
                offset = page.next_offset

            assert sorted(seen) == sorted(keys)
            assert len(seen) == len(set(seen))
            assert pages > 1

            with pytest.raises(Arv2ReadRefused) as past:
                await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="overview",
                    settings=VERIFYING,
                    offset=len(keys),
                )
            assert past.value.code == "offset_past_end"

    run_async(scenario())


def test_a_section_larger_than_a_page_is_served_alone_and_says_it_was_clipped() -> None:
    """The one cut left: a single section bigger than a whole page, clipped to fit and flagged."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            await load_display_recipes(conn)
            account = await _seed_account(conn, project, "Alpha Health")
            await _seed_block(
                conn,
                project,
                account,
                section_key="why-now",
                body={"items": [{"text": "Ölçeklenen ABM ekipleri. " * 900}]},
            )
            await _seed_block(
                conn,
                project,
                account,
                section_key="why-they-fit",
                body={"items": [{"text": "A short section."}]},
            )

            served: dict[str, Any] = {}
            offset: int | None = 0
            while offset is not None:
                page = await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="overview",
                    settings=VERIFYING,
                    offset=offset,
                )
                # Held to the receipt's own byte bound, multi-byte text included.
                assert receipt_bytes([s.model_dump() for s in page.overview]) <= (
                    READ_REFERENCES_BUDGET_BYTES
                )
                for section in page.overview:
                    if section.body_truncated:
                        # The oversized section rides alone on its page.
                        assert len(page.overview) == 1
                    served[section.section_key] = section
                offset = page.next_offset

            assert set(served) == {"why-now", "why-they-fit"}
            assert served["why-now"].body_truncated is True
            assert served["why-now"].body_text.endswith("…")
            assert served["why-they-fit"].body_truncated is False
            assert json.loads(served["why-they-fit"].body_text) == {
                "items": [{"text": "A short section."}]
            }

    run_async(scenario())


def test_an_account_this_workspace_cannot_see_is_refused_by_name() -> None:
    """Another tenant's account, a merge loser and a malformed id all read the same: absent."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            foreign = await seed_project(conn, "ws_arv2_read_tools_other", name="Foreign")
            elsewhere = await _seed_account(conn, foreign, "Alpha Health")

            for account_entity_id in (str(elsewhere), str(uuid4()), "not-a-uuid"):
                with pytest.raises(Arv2ReadRefused) as refused:
                    await read_account_research(
                        conn,
                        workspace_id=WORKSPACE,
                        account_entity_id=account_entity_id,
                        section="claims",
                        settings=VERIFYING,
                    )
                assert refused.value.code == "account_not_found"

            project = await seed_project(conn, WORKSPACE, name="Read tools")
            survivor = await _seed_account(conn, project, "Beta Clinic")
            loser = await _seed_account(conn, project, "Beta Clinic Group")
            await conn.execute(
                text(
                    "UPDATE account_entity SET merged_into = :survivor, status = 'merged' "
                    "WHERE id = :loser"
                ),
                {"survivor": survivor, "loser": loser},
            )
            with pytest.raises(Arv2ReadRefused) as merged:
                await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(loser),
                    section="overview",
                    settings=VERIFYING,
                )
            assert merged.value.code == "account_not_found"

    run_async(scenario())


def test_an_unwritten_overview_and_an_unresearched_account_refuse_rather_than_read_empty() -> None:
    """An empty section would say "there is nothing to know", which is a different claim."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")

            with pytest.raises(Arv2ReadRefused) as unwritten:
                await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="overview",
                    settings=VERIFYING,
                )
            assert unwritten.value.code == "overview_not_written"
            assert "section='claims'" in str(unwritten.value)

            with pytest.raises(Arv2ReadRefused) as unresearched:
                await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="claims",
                    settings=VERIFYING,
                )
            assert unresearched.value.code == "account_not_researched"

            # A prefix that matches nothing is the same refusal, and names the prefix.
            claims: dict[str, str] = {}
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="requisitions",
                field_key="account.open_requisitions",
                value=[{"title": "ABM Manager"}],
            )
            with pytest.raises(Arv2ReadRefused) as narrowed:
                await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="claims",
                    field_prefix="account.resonance",
                    settings=VERIFYING,
                )
            # NOT `account_not_researched`: the account IS researched, and the machine-readable
            # half must not say otherwise because one prefix came back empty.
            assert narrowed.value.code == "no_claims_under_prefix"
            assert "account.resonance" in str(narrowed.value)

    run_async(scenario())


# -- read 4: the claims about one account or contact -----------------------------------------------


async def _seed_contact(
    conn: AsyncConnection, account_id: EntityId, *, name: str, linkedin: str
) -> EntityId:
    """One contact under an account, which is where the store keys a person's claims."""

    return await insert_contact_entity(
        conn, account_entity_id=account_id, full_name=name, linkedin_url=linkedin
    )


async def _seed_contact_claim(
    conn: AsyncConnection,
    claims: dict[str, str],
    project: Project,
    contact_id: EntityId,
    *,
    label: str,
    field_key: str,
    value: Any,
    **overrides: Any,
) -> UUID:
    await write_claim(
        conn,
        claims,
        label=label,
        workspace_id=project.workspace_id,
        entity_id=contact_id,
        entity_type=EntityType.CONTACT,
        field_key=field_key,
        value_json=value,
        **overrides,
    )
    return UUID(claims[label])


async def _dated_claim(
    conn: AsyncConnection,
    claims: dict[str, str],
    project: Project,
    account_id: EntityId,
    *,
    label: str,
    field_key: str,
    value: Any,
    collected_at: datetime,
    extraction_method: ExtractionMethod = ExtractionMethod.SCRAPE,
) -> UUID:
    """One claim stamped with the day it was collected.

    ``since`` filters on ``collected_at``, which the store stamps at insert and the claim table
    then refuses to change (it is append-only: only ``superseded_by``, ``verification_status`` and
    ``corroborations`` may be updated). A date test therefore cannot back-date a seeded row — the
    instant has to be chosen when the claim is built, which is the one thing
    ``LenientClaimWriter`` does not take. This is the only place these tests write a claim
    themselves, and it writes what that writer writes: tier stamped from the method, tenant-private
    scope, this workspace.
    """

    claim = Claim(
        entity_id=account_id,
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=value,
        source_url="https://alpha.example/newsroom",
        source_tier=TIER_FOR_METHOD[extraction_method],
        extraction_method=extraction_method,
        evidence_span="the sentence this value was read from",
        confidence=0.5,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=project.workspace_id,
        collected_at=collected_at,
    )
    claim_id = await insert_claim(conn, claim, validate_field=False)
    claims[label] = str(claim_id)
    return UUID(str(claim_id))


def test_the_claims_query_filters_by_family_tier_status_and_date() -> None:
    """Four filters over one claim list, and they compose.

    Without them a turn that wants three facts reads a hundred claims to find them, and pays for
    every one of them on every later turn of the thread. Each filter is asserted alone and then
    together, because a filter that is quietly dropped answers a narrowed question with the
    unnarrowed list — which reads to the model as "this is all there is".
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            august = datetime(2026, 8, 1, tzinfo=UTC)
            september = datetime(2026, 9, 10, tzinfo=UTC)
            # Tier is stamped from the extraction method, never chosen: api -> 1, scrape -> 2,
            # llm_synthesis -> 4. Asking for a tier is therefore asking "who says so?".
            await _dated_claim(
                conn,
                claims,
                project,
                account,
                label="legal_name",
                field_key="core.legal_name",
                value="Alpha Health Inc.",
                extraction_method=ExtractionMethod.API,
                collected_at=august,
            )
            await _dated_claim(
                conn,
                claims,
                project,
                account,
                label="requisitions",
                field_key="account.open_requisitions",
                value=[{"title": "ABM Manager"}],
                collected_at=august,
            )
            await _dated_claim(
                conn,
                claims,
                project,
                account,
                label="culture",
                field_key="account.resonance.buying_culture",
                value="Committee-led, slow to sign",
                collected_at=september,
            )
            await _dated_claim(
                conn,
                claims,
                project,
                account,
                label="moves",
                field_key="account.strategic_moves",
                value="Opened a New York office in June 2026",
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                collected_at=september,
            )
            # The judged tier-4 claim is a fact; an unjudged one would be held back by the gate,
            # which is the account page's rule and is tested in its own case below.
            await conn.execute(
                text("UPDATE claim SET verification_status = 'verified' WHERE id = ANY(:ids)"),
                {"ids": [UUID(claims["culture"]), UUID(claims["moves"])]},
            )

            async def query(**filters: Any) -> tuple[str, ...]:
                page = await read_claims(
                    conn,
                    workspace_id=project.workspace_id,
                    entity_id=str(account),
                    settings=VERIFYING,
                    **filters,
                )
                return tuple(claim.claim_id for claim in page.claims)

            # Unfiltered: everything servable, in the store's own (field_key, newest) order.
            assert set(await query()) == set(claims.values())
            # One family.
            assert await query(field_prefix="account.resonance") == (claims["culture"],)
            # One tier: "what does a deterministic source say?" is tier 1, and it is one claim.
            assert await query(tier=1) == (claims["legal_name"],)
            assert set(await query(tier=2)) == {claims["requisitions"], claims["culture"]}
            # One status.
            assert set(await query(verification_status="verified")) == {
                claims["culture"],
                claims["moves"],
            }
            assert set(await query(verification_status="unverified")) == {
                claims["legal_name"],
                claims["requisitions"],
            }
            # One date. A bare ISO date means midnight UTC, which is what a human means by it.
            assert set(await query(since="2026-09-01")) == {claims["culture"], claims["moves"]}
            assert set(await query(since="2026-09-10T00:00:00+00:00")) == {
                claims["culture"],
                claims["moves"],
            }
            # And they compose: each one narrows what the one before it left.
            assert await query(tier=2, since="2026-09-01") == (claims["culture"],)
            assert await query(
                field_prefix="account", verification_status="verified", since="2026-09-01"
            ) == (claims["culture"], claims["moves"])

    run_async(scenario())


def test_a_query_that_matches_nothing_is_an_empty_page_with_its_families_not_a_refusal() -> None:
    """ "No tier-1 claim about them since June" is a true sentence; "this account is unresearched"
    is a different, false one. The families come back with the empty page so the next call is a
    correction rather than another guess."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="requisitions",
                field_key="account.open_requisitions",
                value=[{"title": "ABM Manager"}],
            )
            # One held-back claim, so the counts are not zero on the empty answer either.
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="unsafe",
                field_key="account.reputation_risk",
                value={"what": "An unresolved customer dispute"},
                outreach_safe=False,
            )

            page = await read_claims(
                conn,
                workspace_id=project.workspace_id,
                entity_id=str(account),
                settings=VERIFYING,
                field_prefix="account.resonance",
            )

            assert page.claims == ()
            assert (page.truncated, page.next_offset, page.offset) == (False, None, 0)
            # What is there, and what is held back — both said out loud on an empty answer.
            assert page.prefixes == {"account.open_requisitions": 1}
            assert page.excluded == {"sensitive": 0, "unverified": 0, "outreach_unsafe": 1}

            # An account with no claims at all is the same shape, not a refusal: this read is the
            # general query, and "nothing yet" is an answer it is allowed to give.
            empty_account = await _seed_account(conn, project, "Beta Clinic")
            empty = await read_claims(
                conn,
                workspace_id=project.workspace_id,
                entity_id=str(empty_account),
                settings=VERIFYING,
            )
            assert (empty.claims, empty.prefixes, empty.next_offset) == ((), {}, None)
            assert empty.entity_type == "account"

    run_async(scenario())


def test_the_claims_query_pages_the_matches_and_refuses_an_offset_past_the_end() -> None:
    """The page is the shared one: ``limit`` and the receipt's byte budget, whichever binds."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            for index in range(12):
                await _seed_claim(
                    conn,
                    claims,
                    project,
                    account,
                    label=f"claim_{index:02d}",
                    field_key=f"account.open_requisitions.role_{index:03d}",
                    value={"title": f"Role {index}"},
                    evidence_span="Hiring now",
                )

            walked: list[str] = []
            sizes: list[int] = []
            offsets: list[int | None] = []
            offset: int | None = 0
            while offset is not None:
                page = await read_claims(
                    conn,
                    workspace_id=project.workspace_id,
                    entity_id=str(account),
                    settings=VERIFYING,
                    offset=offset,
                    limit=5,
                )
                assert page.offset == offset
                walked.extend(claim.claim_id for claim in page.claims)
                sizes.append(len(page.claims))
                offsets.append(page.next_offset)
                assert receipt_bytes([claim.model_dump() for claim in page.claims]) <= (
                    READ_REFERENCES_BUDGET_BYTES
                )
                offset = page.next_offset

            assert sizes == [5, 5, 2]
            assert offsets == [5, 10, None]
            # The pages partition the twelve: no gap, no repeat.
            assert len(walked) == 12 and len(set(walked)) == 12

            with pytest.raises(Arv2ReadRefused) as refused:
                await read_claims(
                    conn,
                    workspace_id=project.workspace_id,
                    entity_id=str(account),
                    settings=VERIFYING,
                    offset=90,
                )
            assert refused.value.code == "offset_past_end"

    run_async(scenario())


def test_the_claims_query_reads_a_contact_and_says_it_read_one() -> None:
    """The store keys claims on an entity id, so the general query is not account-only: "what do
    we know about this person?" is the question the account read cannot ask."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            contact = await _seed_contact(
                conn,
                account,
                name="Nick Fisher",
                linkedin="https://www.linkedin.com/in/nicholastfisher",
            )
            claims: dict[str, str] = {}
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="requisitions",
                field_key="account.open_requisitions",
                value=[{"title": "ABM Manager"}],
            )
            await _seed_contact_claim(
                conn,
                claims,
                project,
                contact,
                label="title",
                field_key="contact.current_title",
                value="VP of Marketing",
            )
            await _seed_contact_claim(
                conn,
                claims,
                project,
                contact,
                label="hobby",
                field_key="contact.facet.hobby",
                value=["Runs a cocktail channel"],
                evidence_span="I run the Cocktail Chemistry channel",
            )

            page = await read_claims(
                conn,
                workspace_id=project.workspace_id,
                entity_id=str(contact),
                settings=VERIFYING,
            )

            # The read says which kind of subject it read, rather than leaving the model to infer
            # it from the field keys.
            assert page.entity_type == "contact"
            assert page.entity_id == str(contact)
            # The person's claims, and only the person's: the account's are the account's.
            assert {claim.claim_id for claim in page.claims} == {claims["title"], claims["hobby"]}
            assert page.prefixes == {"contact.current_title": 1, "contact.facet": 1}
            # And the account it hangs off is still read under its own id.
            account_page = await read_claims(
                conn,
                workspace_id=project.workspace_id,
                entity_id=str(account),
                settings=VERIFYING,
            )
            assert account_page.entity_type == "account"
            assert [claim.claim_id for claim in account_page.claims] == [claims["requisitions"]]

    run_async(scenario())


def test_the_claims_query_holds_back_exactly_what_the_account_read_holds_back() -> None:
    """One gate, one answer. A second read that came to a gentler conclusion than the first would
    let chat state, with a claim id attached, a fact the account page deliberately refuses to
    print — so the two reads are asserted against each other, claim for claim and count for count,
    under both verification postures."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="plain",
                field_key="account.open_requisitions",
                value=[{"title": "ABM Manager"}],
            )
            # (a) special-category: never leaves the store, for any read.
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="sensitive",
                field_key="account.resonance.buying_culture",
                value="A fact about the founder's health",
                use_class=UseClass.SENSITIVE,
            )
            # (b) tier-4 synthesis nobody judged: the least-trusted class in the platform.
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="unjudged",
                field_key="account.strategic_moves",
                value="Probably opening a second site",
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                evidence_span="hiring for a second site",
            )
            # (c) outreach-unsafe: neither read has a restricted section to put one in.
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="unsafe",
                field_key="account.reputation_risk",
                value={"what": "An unresolved customer dispute"},
                outreach_safe=False,
            )

            for settings in (VERIFYING, PERMISSIVE):
                queried = await read_claims(
                    conn,
                    workspace_id=project.workspace_id,
                    entity_id=str(account),
                    settings=settings,
                )
                researched = await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="claims",
                    settings=settings,
                )
                assert [claim.claim_id for claim in queried.claims] == [
                    claim.claim_id for claim in researched.claims
                ]
                assert queried.excluded == researched.excluded
                assert queried.prefixes == researched.prefixes

            # And the counts are the real ones, not zeros: the sensitive and unsafe claims are
            # held back in both postures, the unjudged synthesis only where verification is on.
            verifying = await read_claims(
                conn,
                workspace_id=project.workspace_id,
                entity_id=str(account),
                settings=VERIFYING,
            )
            assert [claim.claim_id for claim in verifying.claims] == [claims["plain"]]
            assert verifying.excluded == {"sensitive": 1, "unverified": 1, "outreach_unsafe": 1}
            # The gate runs over the WHOLE subject, before any filter: a narrowed query still
            # reports what the subject holds back, never what this page's filter left out.
            narrowed = await read_claims(
                conn,
                workspace_id=project.workspace_id,
                entity_id=str(account),
                settings=VERIFYING,
                tier=1,
            )
            assert narrowed.claims == ()
            assert narrowed.excluded == verifying.excluded
            assert narrowed.prefixes == verifying.prefixes

    run_async(scenario())


def test_a_subject_this_workspace_cannot_see_and_a_bad_since_refuse_by_name() -> None:
    """Another tenant's account, a merge loser, an unknown id and a malformed one all read the
    same: absent. And an unparseable ``since`` is refused rather than ignored — answering a
    narrowed question with the unnarrowed list is the failure this code exists to prevent."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            foreign = await seed_project(conn, "ws_arv2_read_tools_other", name="Foreign")
            elsewhere = await _seed_account(conn, foreign, "Alpha Health")
            elsewhere_contact = await _seed_contact(
                conn,
                elsewhere,
                name="Aaron Elsewhere",
                linkedin="https://www.linkedin.com/in/aaronelsewhere",
            )
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            survivor = await _seed_account(conn, project, "Beta Clinic")
            loser = await _seed_account(conn, project, "Beta Clinic Group")
            await conn.execute(
                text(
                    "UPDATE account_entity SET merged_into = :survivor, status = 'merged' "
                    "WHERE id = :loser"
                ),
                {"survivor": survivor, "loser": loser},
            )

            for entity_id in (
                str(elsewhere),
                str(elsewhere_contact),
                str(loser),
                str(uuid4()),
                "not-a-uuid",
            ):
                with pytest.raises(Arv2ReadRefused) as refused:
                    await read_claims(
                        conn,
                        workspace_id=WORKSPACE,
                        entity_id=entity_id,
                        settings=VERIFYING,
                    )
                assert refused.value.code == "entity_not_found"

            for since in ("last tuesday", "2026-13-01", ""):
                with pytest.raises(Arv2ReadRefused) as bad_date:
                    await read_claims(
                        conn,
                        workspace_id=project.workspace_id,
                        entity_id=str(survivor),
                        settings=VERIFYING,
                        since=since,
                    )
                assert bad_date.value.code == "since_invalid"

    run_async(scenario())


# -- read 3: one discovery run --------------------------------------------------------------------


async def _seed_discovery_run(
    conn: AsyncConnection,
    project: Project,
    *,
    status: str = "completed",
    asked: int | None = 35,
    found_strict: int | None = 10,
    found_relaxed: int | None = 3,
    relaxed_search: bool = False,
    created_at: datetime = _NOW,
) -> UUID:
    """One ``arv2_discovery_run`` (plus the ``project_run`` it hangs off), and — when
    ``relaxed_search`` — the relaxed search it made."""

    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="gi-groups",
        icp_version=1,
    )
    run_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO arv2_discovery_run (run_id, workspace_id, project_id, brand_id, "
            "project_run_id, icp_artifact_key, icp_artifact_sha256, icp_key, icp_version, "
            "requested_by_user_id, request_sha256, target_count, relaxed_enabled, "
            "criteria_gate_keys, status, asked, found_strict, found_relaxed, "
            "created_at, started_at, finished_at, released_at) "
            "VALUES (:run, :ws, :project, :brand, :project_run, :key, :sha, 'gi-groups', 1, "
            ":user, :request_sha, 20, true, CAST(:gates AS jsonb), "
            ":status, :asked, :found_strict, :found_relaxed, CAST(:created_at AS timestamptz), "
            "CAST(:created_at AS timestamptz), "
            "CASE WHEN :status = 'completed' THEN CAST(:created_at AS timestamptz) END, "
            # A finished run has released its project (the one-active-discovery lock).
            "CASE WHEN :status = 'completed' THEN CAST(:created_at AS timestamptz) END)"
        ),
        {
            "run": run_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "brand": project.brand_id,
            "project_run": project_run_id,
            "key": f"{project.workspace_id}/icp",
            "sha": _SHA,
            "user": USER_ID,
            "request_sha": uuid4().hex + uuid4().hex,
            "gates": json.dumps(["geography"]),
            "status": status,
            "asked": asked,
            "found_strict": found_strict,
            "found_relaxed": found_relaxed,
            "created_at": created_at,
        },
    )
    if relaxed_search:
        await conn.execute(
            text(
                "INSERT INTO arv2_discovery_search (run_id, ordinal, kind, external_id, asked, "
                " criteria) VALUES (:run, 3, 'relaxed', :external, 7, CAST('[]' AS jsonb))"
            ),
            {"run": run_id, "external": f"arv2-discovery:{run_id}:3"},
        )
    return run_id


async def _seed_candidate(
    conn: AsyncConnection,
    project: Project,
    run_id: UUID,
    name: str,
    *,
    disposition: str,
    decision: str | None = None,
    fit: float | None = None,
    candidate_pass: str = "strict",
    judged: bool = True,
    workspace_id: str | None = None,
) -> None:
    """One candidate. ``judged`` writes a verdict row — which is what *verified* means.

    The default is ``True`` because the dispositions a verifier produces (`pass`/`partial`/
    `unclear`) always carry verdicts; the pre-spend ones (`duplicate_of_existing`,
    `found_before`) are stamped before any gate is asked, so a test that seeds one passes
    ``judged=False`` and the tallies must not count it.
    """

    await conn.execute(
        text(
            "INSERT INTO arv2_discovery_candidate (candidate_id, run_id, workspace_id, "
            "project_id, pass, domain, name, provider_snapshot_json, verdicts_json, fit, "
            "disposition, decision) "
            "VALUES (:candidate, :run, :ws, :project, :pass, :domain, :name, "
            "CAST(:snapshot AS jsonb), CAST(:verdicts AS jsonb), :fit, :disposition, :decision)"
        ),
        {
            "candidate": uuid4(),
            "run": run_id,
            "ws": workspace_id or project.workspace_id,
            "project": project.project_id,
            "pass": candidate_pass,
            "domain": f"{name.lower().replace(' ', '-')}.example",
            "name": name,
            "snapshot": json.dumps({"name": name}),
            "verdicts": json.dumps(
                [{"criterion": "geography", "verdict": "pass"}] if judged else []
            ),
            "fit": fit,
            "disposition": disposition,
            "decision": decision,
        },
    )


def test_the_latest_discovery_run_is_read_with_its_three_tallies() -> None:
    """Verified, shown and approved are three derivations over one candidate table."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            older = await _seed_discovery_run(
                conn, project, created_at=_NOW - timedelta(days=3), found_strict=1
            )
            await _seed_candidate(conn, project, older, "Old Health", disposition="pass")
            latest = await _seed_discovery_run(
                conn, project, relaxed_search=True, found_strict=10, found_relaxed=3
            )
            await _seed_candidate(
                conn,
                project,
                latest,
                "Alpha Health",
                disposition="pass",
                decision="approved",
                fit=0.9,
            )
            await _seed_candidate(
                conn, project, latest, "Beta Clinic", disposition="partial", fit=0.4
            )
            await _seed_candidate(conn, project, latest, "Gamma Surgery", disposition="unclear")
            # A candidate the driver stamped BEFORE any gate was asked: it cost the one website
            # answer that identified it and was never checked against the ICP, so it is not
            # verified — even though it is not pending either.
            await _seed_candidate(
                conn,
                project,
                latest,
                "Delta Labs",
                disposition="duplicate_of_existing",
                fit=0.1,
                judged=False,
            )
            await _seed_candidate(
                conn, project, latest, "Epsilon Group", disposition="pending", judged=False
            )

            run = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=None,
                limit=25,
            )

            # The newest run, not the first one seeded.
            assert run.run_id == str(latest)
            assert (run.status, run.icp_key, run.icp_version) == ("completed", "gi-groups", 1)
            assert (run.target_count, run.asked) == (20, 35)
            # strict + relaxed, coalesced.
            assert run.found == 13
            # THREE were judged (the pass/partial/unclear ones); the pre-spend duplicate and the
            # pending one were not. Under the old "not pending" reading this said 4 — and the agent
            # told the founder the platform had checked a company it had skipped.
            assert (run.verified, run.shown, run.approved) == (3, 3, 1)
            assert run.relaxed_requested is True
            assert run.started_at is not None and run.started_at.startswith("2026-09-12")
            assert run.finished_at is not None
            assert run.candidate_total == 5
            # The other run's candidate is not this run's.
            assert "Old Health" not in {candidate.name for candidate in run.candidates}

    run_async(scenario())


def test_the_candidates_are_shown_first_then_best_fit_and_the_list_is_bounded() -> None:
    """An unscored candidate is unknown, not bad: it sorts after every scored one."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            run_id = await _seed_discovery_run(conn, project)
            # Seeded in an order that is wrong for every rule at once.
            await _seed_candidate(
                conn,
                project,
                run_id,
                "Zeta Rehab",
                disposition="found_before",
                fit=1.0,
                judged=False,
            )
            await _seed_candidate(conn, project, run_id, "Unscored Clinic", disposition="pass")
            await _seed_candidate(
                conn, project, run_id, "Beta Clinic", disposition="partial", fit=0.5
            )
            await _seed_candidate(
                conn,
                project,
                run_id,
                "Alpha Health",
                disposition="unclear",
                fit=0.8,
                candidate_pass="relaxed",
            )

            run = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=None,
                limit=25,
            )

            assert [candidate.name for candidate in run.candidates] == [
                "Alpha Health",  # shown, fit 0.8
                "Beta Clinic",  # shown, fit 0.5
                "Unscored Clinic",  # shown, no fit
                "Zeta Rehab",  # not shown, even at fit 1.0
            ]
            alpha = run.candidates[0]
            assert (alpha.domain, alpha.pass_, alpha.disposition) == (
                "alpha-health.example",
                "relaxed",
                "unclear",
            )
            assert (alpha.fit, alpha.decision) == (0.8, None)

            bounded = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=None,
                limit=2,
            )
            assert [candidate.name for candidate in bounded.candidates] == [
                "Alpha Health",
                "Beta Clinic",
            ]
            # A bounded list never reads as a small run.
            assert bounded.candidate_total == 4

            tallies_only = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=None,
                limit=0,
            )
            assert tallies_only.candidates == ()
            # Four candidates; three were judged — `found_before` is a pre-spend stamp.
            assert (tallies_only.candidate_total, tallies_only.verified) == (4, 3)

    run_async(scenario())


def test_the_candidates_are_paged_to_the_end_rather_than_cut_at_the_first_page() -> None:
    """A sixty-company run read as twenty-five, and the other thirty-five were unreachable: the
    tool named no way to continue, so the agent either spoke about a third of the run as if it
    were the run, or asked for a bigger page it could not afford. The pages now partition the
    ordered candidates, and the last one says it is the last.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            run_id = await _seed_discovery_run(conn, project)
            # Descending fit, so the read's own order ("shown first, then best fit") is a known
            # sequence rather than whatever the table happens to return.
            for index in range(60):
                await _seed_candidate(
                    conn,
                    project,
                    run_id,
                    f"Company {index:03d}",
                    disposition="pass",
                    fit=1.0 - index / 100,
                )

            pages = []
            offset: int | None = 0
            while offset is not None:
                page = await read_discovery_run(
                    conn,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    run_id=None,
                    offset=offset,
                    limit=25,
                )
                # The whole run on every page: a page never reads as a small run.
                assert page.candidate_total == 60
                assert page.offset == offset
                pages.append(page)
                offset = page.next_offset

            assert [page.offset for page in pages] == [0, 25, 50]
            assert [page.next_offset for page in pages] == [25, 50, None]
            assert [len(page.candidates) for page in pages] == [25, 25, 10]
            # The three pages are the ordered list, partitioned: no gap, no repeat, no reordering.
            walked = [candidate.name for page in pages for candidate in page.candidates]
            assert walked == [f"Company {index:03d}" for index in range(60)]

    run_async(scenario())


def test_a_discovery_page_that_advances_nothing_names_no_next_page() -> None:
    """Two shapes that must not point a caller in a circle (or at a page that is not there):
    ``read_discovery_run@1``'s tallies-only ask, and an offset past the end."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            run_id = await _seed_discovery_run(conn, project)
            for index in range(3):
                await _seed_candidate(
                    conn, project, run_id, f"Company {index}", disposition="pass", fit=0.5
                )

            tallies_only = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=None,
                limit=0,
            )
            assert tallies_only.candidates == ()
            # ``next_offset 0`` would send a caller back to the page it just read, forever.
            assert (tallies_only.next_offset, tallies_only.candidate_total) == (None, 3)

            past_end = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=None,
                offset=90,
                limit=25,
            )
            assert (past_end.candidates, past_end.next_offset) == ((), None)
            # And the run is still reported honestly: an empty page is not an empty run.
            assert past_end.candidate_total == 3

    run_async(scenario())


def test_a_candidate_stamped_with_another_tenant_is_neither_listed_nor_counted() -> None:
    """I4: the tallies and the rows must agree about whether the single-column FK is trusted.

    ``arv2_discovery_candidate.run_id`` references the run and nothing forces the candidate's
    workspace to equal the run's, which the counts' ``:ws`` predicates already concede. The list
    must concede it too, or the agent reads "shown: 1" beside two shown companies and one of them
    is another tenant's row.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            run_id = await _seed_discovery_run(conn, project)
            await _seed_candidate(
                conn, project, run_id, "Alpha Health", disposition="pass", fit=0.9
            )
            # Same run id, another tenant's stamp — a repair script, a bulk import, a resumed run.
            await seed_project(conn, "ws_arv2_read_tools_other", name="Foreign")
            await _seed_candidate(
                conn,
                project,
                run_id,
                "Foreign Health",
                disposition="pass",
                fit=1.0,
                workspace_id="ws_arv2_read_tools_other",
            )

            run = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=None,
                limit=25,
            )

            assert [candidate.name for candidate in run.candidates] == ["Alpha Health"]
            # …and the remainder the model is told about is the remainder it can reach.
            assert run.candidate_total == 1
            assert (run.verified, run.shown) == (1, 1)

    run_async(scenario())


def test_a_run_can_be_read_by_id_and_an_unfinished_one_reads_honestly() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            older = await _seed_discovery_run(
                conn,
                project,
                created_at=_NOW - timedelta(days=3),
                status="in_progress",
                asked=None,
                found_strict=None,
                found_relaxed=None,
            )
            await _seed_candidate(
                conn, project, older, "Old Health", disposition="pending", judged=False
            )
            await _seed_discovery_run(conn, project)

            run = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=str(older),
                limit=25,
            )

            # The run asked for, not the newest one.
            assert run.run_id == str(older)
            assert run.status == "in_progress"
            assert run.asked is None
            # Neither counter is written yet: "found nothing so far", never a crash.
            assert run.found == 0
            assert (run.verified, run.shown, run.approved) == (0, 0, 0)
            assert run.finished_at is None
            assert run.candidate_total == 1

    run_async(scenario())


def test_another_project_s_run_and_a_project_without_discovery_refuse_by_name() -> None:
    """A run of a project you can see is still not *this* project's run."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            other = await seed_project(conn, WORKSPACE, name="Other project")
            elsewhere = await _seed_discovery_run(conn, other)
            foreign = await seed_project(conn, "ws_arv2_read_tools_other", name="Foreign")
            foreign_run = await _seed_discovery_run(conn, foreign)

            # No run of this project at all.
            with pytest.raises(Arv2ReadRefused) as none_yet:
                await read_discovery_run(
                    conn,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    run_id=None,
                    limit=25,
                )
            assert none_yet.value.code == "no_discovery_run"

            # A sibling project's run, another tenant's run, an unknown id and a malformed one all
            # read the same: absent.
            for run_id in (str(elsewhere), str(foreign_run), str(uuid4()), "not-a-uuid"):
                with pytest.raises(Arv2ReadRefused) as refused:
                    await read_discovery_run(
                        conn,
                        workspace_id=project.workspace_id,
                        project_id=project.project_id,
                        run_id=run_id,
                        limit=25,
                    )
                assert refused.value.code == "discovery_run_not_found"

            # And the project check comes first: another tenant's project is not ours to read.
            with pytest.raises(Arv2ReadRefused) as not_ours:
                await read_discovery_run(
                    conn,
                    workspace_id=WORKSPACE,
                    project_id=foreign.project_id,
                    run_id=str(foreign_run),
                    limit=25,
                )
            assert not_ours.value.code == "project_not_found"

    run_async(scenario())


async def _exclude(conn: AsyncConnection, run_id: UUID, name: str, *, gate: str) -> None:
    """Turn one seeded candidate into a company a gate excluded (the pair the CHECK ties)."""

    await conn.execute(
        text(
            "UPDATE arv2_discovery_candidate SET disposition = 'excluded', "
            "excluded_by_gate = :gate WHERE run_id = :run AND name = :name"
        ),
        {"run": run_id, "name": name, "gate": gate},
    )


def test_a_brief_run_is_read_with_its_summary_its_end_and_its_exclusions_apart() -> None:
    """``@3``'s substrate: the run's source, why it ended and its summary, and the companies a gate
    excluded listed apart from the candidates — which stay the ones the human may be shown."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            run_id = await _seed_discovery_run(conn, project)
            summary = {"asked": 20, "added": 1, "excluded": 2, "end_reason": "dry"}
            await conn.execute(
                text(
                    "UPDATE arv2_discovery_run SET source = 'search', end_reason = 'dry', "
                    "summary_json = CAST(:summary AS jsonb) WHERE run_id = :run"
                ),
                {"run": run_id, "summary": json.dumps(summary)},
            )
            await _seed_candidate(
                conn, project, run_id, "Alpha Health", disposition="pass", fit=0.9
            )
            await _seed_candidate(conn, project, run_id, "Rival B", disposition="pending")
            await _seed_candidate(conn, project, run_id, "Rival A", disposition="pending")
            await _seed_candidate(conn, project, run_id, "Seller", disposition="pending")
            await _exclude(conn, run_id, "Rival B", gate="sells_it")
            await _exclude(conn, run_id, "Rival A", gate="sells_it")
            await _exclude(conn, run_id, "Seller", gate="is_buyer")

            run = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=str(run_id),
                limit=25,
                excluded_apart=True,
            )

            assert (run.source, run.end_reason) == ("search", "dry")
            assert run.summary == summary
            assert [c.name for c in run.candidates] == ["Alpha Health"]
            assert run.candidates[0].excluded_by_gate is None
            # The page walks the candidates only: the excluded are not part of its total.
            assert (run.candidate_total, run.next_offset) == (1, None)
            # Grouped by the gate that excluded them, then by name.
            assert [(c.name, c.excluded_by_gate) for c in run.excluded] == [
                ("Seller", "is_buyer"),
                ("Rival A", "sells_it"),
                ("Rival B", "sells_it"),
            ]
            assert {c.disposition for c in run.excluded} == {"excluded"}
            assert run.excluded_total == 3
            # Judged, so verified; never shown.
            assert (run.verified, run.shown) == (4, 1)

            # ``@1``/``@2``'s shape: the excluded are listed inline, as they always were.
            inline = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=str(run_id),
                limit=25,
            )
            assert inline.candidate_total == 4
            assert inline.excluded == () and inline.excluded_total == 0
            assert sum(c.disposition == "excluded" for c in inline.candidates) == 3

    run_async(scenario())


def test_the_excluded_list_is_bounded_and_its_total_is_the_whole_run() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            run_id = await _seed_discovery_run(conn, project)
            for index in range(MAX_CANDIDATES + 3):
                name = f"Excluded {index:03d}"
                await _seed_candidate(conn, project, run_id, name, disposition="pending")
                await _exclude(conn, run_id, name, gate="sells_it")

            run = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=str(run_id),
                limit=25,
                excluded_apart=True,
            )

            assert len(run.excluded) == MAX_CANDIDATES
            assert run.excluded_total == MAX_CANDIDATES + 3
            assert run.candidates == () and run.candidate_total == 0

    run_async(scenario())


# --- read_account_research@3: the insights page and the buying committee (2026-10-05) --------


async def _seed_page_block(
    conn: AsyncConnection,
    project: Project,
    subject_id: EntityId,
    *,
    subject_kind: str,
    page: str,
    section_key: str,
    body: dict[str, object],
) -> None:
    """One live ``display_block`` on any page of any subject (the legacy display lane)."""

    await conn.execute(
        text(
            "INSERT INTO display_block (workspace_id, subject_kind, subject_id, page, "
            "section_key, body_json, cited_claim_ids, model, prompt_version, recipe_version, "
            "generated_at) VALUES (:ws, :kind, :subject, :page, :section, "
            "CAST(:body AS jsonb), CAST(:cited AS uuid[]), 'luna', 'v1+v1', 1, "
            "CAST(:now AS timestamptz))"
        ),
        {
            "ws": project.workspace_id,
            "kind": subject_kind,
            "subject": subject_id,
            "page": page,
            "section": section_key,
            "body": json.dumps(body),
            "cited": [],
            "now": _NOW,
        },
    )


def test_the_insights_section_serves_the_insights_page_and_refuses_when_unwritten() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            await load_display_recipes(conn)
            account = await _seed_account(conn, project, "Alpha Health")

            with pytest.raises(Arv2ReadRefused) as refused:
                await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="insights",
                    settings=VERIFYING,
                )
            assert refused.value.code == "insights_not_written"

            await _seed_page_block(
                conn,
                project,
                account,
                subject_kind="account",
                page="insights",
                section_key="watch-outs",
                body={"items": [{"text": "A new CFO joined in June."}]},
            )
            research = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="insights",
                settings=VERIFYING,
            )
            assert research.section == "insights"
            assert [section.section_key for section in research.overview] == ["watch-outs"]
            assert "A new CFO joined in June." in research.overview[0].body_text
            assert (research.claims, research.contacts) == ((), ())

    run_async(scenario())


def test_the_contacts_section_lists_the_committee_with_each_person_s_contact_page() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            await load_display_recipes(conn)
            account = await _seed_account(conn, project, "Alpha Health")
            claims: dict[str, str] = {}
            written = await _seed_contact(
                conn,
                account,
                name="Nick Fisher",
                linkedin="https://www.linkedin.com/in/nicholastfisher",
            )
            unwritten = await _seed_contact(
                conn, account, name="Ada Lane", linkedin="https://www.linkedin.com/in/adalane"
            )
            # The legacy committee is the contacts under the account holding a live claim.
            for label, contact, title in (
                ("t1", written, "VP of Marketing"),
                ("t2", unwritten, "CFO"),
            ):
                await _seed_contact_claim(
                    conn,
                    claims,
                    project,
                    contact,
                    label=label,
                    field_key="contact.current_title",
                    value=title,
                )
            await _seed_page_block(
                conn,
                project,
                written,
                subject_kind="contact",
                page="contact",
                section_key="why-this-person",
                body={"items": [{"text": "Owns the ABM budget."}]},
            )

            research = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="contacts",
                settings=VERIFYING,
            )
            by_id = {person.contact_entity_id: person for person in research.contacts}
            assert set(by_id) == {str(written), str(unwritten)}
            assert by_id[str(written)].name == "Nick Fisher"
            # The title the committee card shows, from the person's title claim.
            assert by_id[str(written)].title == "VP of Marketing"
            assert by_id[str(unwritten)].title == "CFO"
            assert by_id[str(written)].page_written is True
            assert by_id[str(written)].sections[0].section_key == "why-this-person"
            assert "Owns the ABM budget." in by_id[str(written)].sections[0].body_text
            # A person whose page is not written yet is still on the committee.
            assert by_id[str(unwritten)].page_written is False
            assert by_id[str(unwritten)].sections == ()
            assert research.next_offset is None and research.overview == ()

    run_async(scenario())


def test_overview_and_insights_read_the_current_lane_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """The current research lane's pages, not just the legacy blocks (regression 2026-10-05:
    ``_PAGE_WRITTEN_AT`` gained ``kind``/``page`` binds and the overview path still passed three,
    so every current-lane overview read raised)."""

    import clue_api.arv2.quality_pages as quality_pages
    import clue_api.arv2.quality_read as quality_read

    context_id = uuid4()

    class _Selection:
        scope = object()
        metadata: dict[str, object] = {"committee": []}

        def __init__(self) -> None:
            self.context_id = context_id

    async def fake_select(*_args: object, **_kwargs: object) -> _Selection:
        return _Selection()

    asked: list[str] = []

    async def fake_read_page(_conn: object, _scope: object, *, context_id: UUID, page: str):
        asked.append(page)
        text_by_page = {"overview": "They run 40 schools.", "insights": "A levy vote in May."}
        return {
            "display_block": {
                "sections": [
                    {"key": f"{page}-one", "h1": page, "intro": [{"text": text_by_page[page]}]}
                ]
            }
        }

    monkeypatch.setattr(quality_read, "select_quality_context", fake_select)
    monkeypatch.setattr(quality_pages, "read_page", fake_read_page)

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            for section, words in (
                ("overview", "They run 40 schools."),
                ("insights", "A levy vote in May."),
            ):
                research = await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section=section,
                    settings=VERIFYING,
                    project_id=project.project_id,
                )
                assert [s.section_key for s in research.overview] == [f"{section}-one"]
                assert words in research.overview[0].body_text
        assert asked == ["overview", "insights"]

    run_async(scenario())


def test_current_lane_contacts_carry_the_committee_card_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The current lane's committee (``committee()`` over the quality selection) carries no
    title of its own; the read fills it from the title claim, as the committee card does
    (found live 2026-10-05: every current-lane contact came back with title None)."""

    import clue_api.arv2.quality_pages as quality_pages
    import clue_api.arv2.quality_read as quality_read

    members: list[dict[str, object]] = []

    class _Scope:
        account_name = "Alpha Health"
        account_domain = "alpha.example"

    class _Selection:
        scope = _Scope()
        context_id = uuid4()

        @property
        def metadata(self) -> dict[str, object]:
            return {"committee": members}

    async def fake_select(*_args: object, **_kwargs: object) -> _Selection:
        return _Selection()

    async def fake_read_page(_conn: object, _scope: object, *, context_id: UUID, page: str):
        return {
            "display_block": {
                "sections": [
                    {
                        "key": "why-this-person",
                        "h1": "Why this person",
                        "intro": [{"text": "Owns the budget."}],
                    }
                ]
            }
        }

    monkeypatch.setattr(quality_read, "select_quality_context", fake_select)
    monkeypatch.setattr(quality_pages, "read_page", fake_read_page)

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            await load_display_recipes(conn)
            account = await _seed_account(conn, project, "Alpha Health")
            contact = await _seed_contact(
                conn, account, name="Nick Fisher", linkedin="https://www.linkedin.com/in/nfisher"
            )
            await _seed_contact_claim(
                conn,
                {},
                project,
                contact,
                label="t1",
                field_key="contact.current_title",
                value="VP of Marketing",
            )
            members.append(
                {
                    "contact_id": str(contact),
                    "assessment_claim_id": str(uuid4()),
                    "persona_key": "champion",
                    "proposed_role": "champion",
                    "state": "supported",
                    "employment_claim_ids": [],
                }
            )
            research = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="contacts",
                settings=VERIFYING,
                project_id=project.project_id,
            )
            (person,) = research.contacts
            assert (person.name, person.committee_role, person.title) == (
                "Nick Fisher",
                "champion",
                "VP of Marketing",
            )
            assert [s.section_key for s in person.sections] == ["why-this-person"]

    run_async(scenario())


def test_cited_claims_say_why_each_id_was_held_or_missing() -> None:
    """Review focus 2: the design agent drops a research statement only when the claim under it
    is held back by a real rule, so the read must say which rule, per id."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            contact = await _seed_contact(
                conn, account, name="Nalisa Clark", linkedin="https://www.linkedin.com/in/nclark"
            )
            claims: dict[str, str] = {}
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="plain",
                field_key="account.open_requisitions",
                value=[{"title": "ABM Manager"}],
            )
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="finding",
                field_key="account.research_finding",
                value={"topic": "Budget", "finding": "Healthcare up $4.2 million"},
                outreach_safe=False,
            )
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="risk",
                field_key="account.reputation_risk",
                value={"what": "An unresolved customer dispute"},
                outreach_safe=False,
            )
            await _seed_claim(
                conn,
                claims,
                project,
                account,
                label="sensitive",
                field_key="account.resonance.buying_culture",
                value="A fact about the founder's health",
                use_class=UseClass.SENSITIVE,
            )
            await _seed_contact_claim(
                conn,
                claims,
                project,
                contact,
                label="contact_finding",
                field_key="contact.research_finding",
                value={"topic": "Role", "finding": "Leads benefits"},
                outreach_safe=False,
            )
            await _seed_contact_claim(
                conn,
                claims,
                project,
                contact,
                label="contact_plain",
                field_key="contact.current_title",
                value="Chief Human Capital Officer",
            )
            missing = str(uuid4())
            ids = [
                claims[label]
                for label in (
                    "plain",
                    "finding",
                    "risk",
                    "sensitive",
                    "contact_finding",
                    "contact_plain",
                )
            ] + [missing, "not-a-uuid"]

            page = await read_cited_claims(
                conn,
                workspace_id=project.workspace_id,
                entity_id=str(account),
                claim_ids=ids,
                settings=PERMISSIVE,
            )

            assert page.dispositions == {
                claims["plain"]: "served",
                claims["finding"]: "served",  # verification off: findings pass the gate
                claims["risk"]: "held:outreach_unsafe",
                claims["sensitive"]: "held:sensitive",
                claims["contact_finding"]: "held:unverified_finding",
                claims["contact_plain"]: "held:other_entity",
                missing: "not_found",
                "not-a-uuid": "not_found",
            }
            assert [c.claim_id for c in page.claims] == [claims["plain"], claims["finding"]]

            verifying = await read_cited_claims(
                conn,
                workspace_id=project.workspace_id,
                entity_id=str(account),
                claim_ids=[claims["finding"], claims["risk"]],
                settings=VERIFYING,
            )
            # Under verification the finding is held, but only as an unverified finding.
            assert verifying.dispositions == {
                claims["finding"]: "held:unverified_finding",
                claims["risk"]: "held:outreach_unsafe",
            }

            with pytest.raises(Arv2ReadRefused) as refused:
                await read_cited_claims(
                    conn,
                    workspace_id=project.workspace_id,
                    entity_id=str(uuid4()),
                    claim_ids=ids,
                    settings=PERMISSIVE,
                )
            assert refused.value.code == "entity_not_found"


def test_brief_exclusions_are_served_apart_with_the_gate_exclusions() -> None:
    """Spec 2026-10-16 §4.6: a company the brief excluded (an existing customer, or the seller) is
    listed with the run's excluded companies, never among the candidates the human may be shown.
    ``@3``'s schema is pinned by hash, so the entry rides only as the disposition."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            run_id = await _seed_discovery_run(conn, project)
            await _seed_candidate(
                conn, project, run_id, "Alpha Health", disposition="pass", fit=0.9
            )
            await _seed_candidate(conn, project, run_id, "Marriott", disposition="pending")
            await conn.execute(
                text(
                    "UPDATE arv2_discovery_candidate SET disposition = 'excluded_by_brief', "
                    "excluded_by_entry = 'Marriott' WHERE run_id = :run AND name = 'Marriott'"
                ),
                {"run": run_id},
            )

            run = await read_discovery_run(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                run_id=str(run_id),
                limit=25,
                excluded_apart=True,
            )

            assert [c.name for c in run.candidates] == ["Alpha Health"]
            assert [(c.name, c.disposition, c.excluded_by_gate) for c in run.excluded] == [
                ("Marriott", "excluded_by_brief", None)
            ]
            assert run.excluded_total == 1

    run_async(scenario())
