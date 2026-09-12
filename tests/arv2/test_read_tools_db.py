"""The Head of ABM's read tools against the real rows they answer from.

What would rot silently here is a *number*: an account list that quietly includes a merge loser,
a status read off a person job, or a "refreshing" flag that fires the first time an account is
researched. Each of those reads as a confident wrong sentence in the chat rather than as an error,
so the rows are seeded by hand and the derived answers are asserted against them.

The same standard governs one account's research: a superseded claim served as current truth, a
retired page section served as this week's words, or an unwritten overview served as an empty one
are all sentences the agent would say without hesitating.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.arv2.read_tools import (
    EVIDENCE_CHARS,
    Arv2ReadRefused,
    list_project_accounts,
    read_account_research,
)
from clue_core import EntityId, EntityType, new_project_run_id
from clue_research.durable import ensure_project_run
from clue_research.identity import insert_account_entity
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


async def _seed_account(
    conn: AsyncConnection, project: Project, name: str, *, added_via: str = "manual"
) -> EntityId:
    account_id = await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=f"{name.lower().replace(' ', '-')}.example",
        workspace_id=project.workspace_id,
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
            # Ordered by canonical name.
            alpha, beta = page.accounts
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

            alpha, beta = page.accounts
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

            assert [account.name for account in page.accounts] == ["Alpha Health"]
            assert page.total == 2

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
            # The body is served verbatim — the app's shape, not a second one.
            assert research.overview[0].body == {
                "intro": [],
                "items": [{"text": "They opened four ABM roles."}],
            }
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
            assert len(requisitions.evidence) == EVIDENCE_CHARS
            assert requisitions.evidence == long_span[:EVIDENCE_CHARS]
            assert requisitions.tier == 2  # stamped from the scrape method, not chosen
            assert requisitions.collected_at.startswith("20")
            assert culture.value == "Committee-led, slow to sign"

            narrowed = await read_account_research(
                conn,
                workspace_id=project.workspace_id,
                account_entity_id=str(account),
                section="claims",
                field_prefix="account.resonance",
            )
            assert [claim.claim_id for claim in narrowed.claims] == [claims["culture"]]

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
                )
            assert unwritten.value.code == "overview_not_written"
            assert "section='claims'" in str(unwritten.value)

            with pytest.raises(Arv2ReadRefused) as unresearched:
                await read_account_research(
                    conn,
                    workspace_id=project.workspace_id,
                    account_entity_id=str(account),
                    section="claims",
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
                )
            assert narrowed.value.code == "account_not_researched"
            assert "account.resonance" in str(narrowed.value)

    run_async(scenario())
