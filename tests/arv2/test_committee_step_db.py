"""The committee step against the real tables: candidates become people, claims and person jobs.

The step is where an account job's finding ("these five people are the buying committee") becomes
the lane's next unit of work. Three properties are what make that safe, and each one is a test
here:

* **Only a confirmed, named person is fanned out.** A vacant seat is a finding about the account,
  not a person — it creates no contact and no job — and a named candidate with no confirming URL
  was never written as a claim either, so it is not researched.
* **It is idempotent.** A re-settled job (a redelivery, a re-driven attempt) finds its contacts and
  its person jobs already there and writes nothing a second time; the person job row is the
  member's latch, and the member is written atomically behind it.
* **It never costs the account job its terminal row.** Every member's work is one savepoint, so a
  candidate that cannot be resolved or written is a recorded skip rather than a rolled-back settle.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2 import account_research_store as store
from clue_api.arv2.account_research_catalog import arv2_person_profile_sha256
from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.committee_step import run_committee_step
from clue_api.arv2.structuring_client import FieldCatalog, FieldSpec
from clue_core import EntityId, new_project_run_id
from clue_obs.langfuse import ENTITIES_METADATA_KEY, observation
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.durable.project_run import ensure_project_run
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.profiling.committee.fields import load_committee_pack
from clue_research.profiling.fields import load_deep_profiling_pack
from tests._langfuse import finished_spans, langfuse_installed
from tests._workspace import seed_project

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def _attributes(span: Any) -> dict[str, Any]:
    return dict(span.attributes or {})


WORKSPACE = "ws_r3_committee"
SHA = "a" * 64

#: The three committee fields as the job's own catalog serves them: the member's claims take their
#: use class from the field's declared hint, never from a default this module chose.
COMMITTEE_CATALOG = FieldCatalog(
    contact=(
        FieldSpec("contact.persona", "Buying-committee persona.", None),
        FieldSpec("contact.current_title", "Current professional title.", None),
        FieldSpec(
            "contact.role_on_committee",
            "The seat and the reasoning behind it.",
            None,
            use_class_hint="professional-public",
        ),
    )
)

#: The candidate list a finalization proposes, in the model's own order. Two confirmed people, one
#: vacant seat, one named candidate nobody confirmed, and a third confirmed person past the cap.
CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "name": "Dana Reyes",
        "title": "VP Marketing",
        "persona": "economic_buyer",
        "linkedin_url": "https://www.linkedin.com/in/dana-reyes/",
        "confirmed_by": "https://probook.ai/team",
        "vacant_seat": False,
        "evidence_span": "Dana Reyes, VP Marketing",
    },
    {
        "name": None,
        "title": None,
        "persona": "technical_evaluator",
        "linkedin_url": None,
        "confirmed_by": None,
        "vacant_seat": True,
        "evidence_span": "the role is open",
    },
    {
        "name": "Sam Okafor",
        "title": "Head of Demand Gen",
        "persona": "champion",
        "linkedin_url": None,
        "confirmed_by": "https://probook.ai/blog/demand-gen",
        "vacant_seat": False,
        "evidence_span": "Sam Okafor, who runs demand generation",
    },
    {
        "name": "Unconfirmed Person",
        "title": "CTO",
        "persona": "blocker",
        "linkedin_url": None,
        "confirmed_by": None,
        "vacant_seat": False,
        "evidence_span": "",
    },
    {
        "name": "Past The Cap",
        "title": "CFO",
        "persona": "blocker",
        "linkedin_url": "https://www.linkedin.com/in/past-the-cap",
        "confirmed_by": "https://probook.ai/leadership",
        "vacant_seat": False,
        "evidence_span": "the CFO",
    },
)


async def _seed(
    conn: AsyncConnection, *, committee_cap: int = 2
) -> tuple[store.RunRow, UUID, UUID]:
    """A workspace, a project run, an account, the run row, and its account job."""
    project = await seed_project(conn, WORKSPACE)
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="clue-abm-buyers",
        icp_version=1,
    )
    await load_deep_profiling_pack(conn)
    await load_committee_pack(conn)
    await load_arv2_pack(conn)
    account = await insert_account_entity(
        conn,
        canonical_name="Probook",
        primary_domain="probook.ai",
        workspace_id=project.workspace_id,
    )
    run = store.RunRow(
        run_id=uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=project.brand_id,
        project_run_id=UUID(str(project_run_id)),
        icp_artifact_key=f"{project.workspace_id}/icp",
        icp_artifact_sha256=SHA,
        icp_key="clue-abm-buyers",
        icp_version=1,
        product_selection_version=1,
        effort="full",
        committee_cap=committee_cap,
        directive_text="",
        profile_ref="agent-profile:arv2-account:v1",
        profile_sha256="b" * 64,
        requested_by_user_id="usr_r3_committee",
        request_sha256="c" * 64,
    )
    assert await store.create_run(conn, run) is True
    job_id = uuid4()
    assert (
        await store.create_job(
            conn,
            job_id=job_id,
            run_id=run.run_id,
            workspace_id=run.workspace_id,
            account_entity_id=UUID(str(account)),
            profile_sha256=run.profile_sha256,
        )
        is True
    )
    return run, UUID(str(account)), job_id


def _scope(run: store.RunRow, account_id: UUID) -> JobScope:
    return JobScope(
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        project_run_id=run.project_run_id,
        run_id=run.run_id,
        job_id=uuid4(),
        account_id=EntityId(account_id),
        account_name="Probook",
        account_domain="probook.ai",
        icp_markdown="",
        persona_markdown="",
        already_established="",
        effort=run.effort,
        committee_cap=run.committee_cap,
        today=date(2026, 9, 9),
    )


async def _contacts(conn: AsyncConnection, account_id: UUID) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT id, full_name, linkedin_url FROM contact_entity "
                    "WHERE account_entity_id = :account ORDER BY full_name"
                ),
                {"account": account_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def test_confirmed_candidates_become_contacts_claims_and_person_jobs() -> None:
    """Two confirmed people fan out; the vacant seat, the unconfirmed name and the cap do not."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            job = await store.read_job(conn, job_id=job_id)
            assert job is not None

            result = await run_committee_step(
                conn,
                job=job,
                run=run,
                scope=_scope(run, account),
                candidates=CANDIDATES,
                writer=LenientClaimWriter(lenient=True),
                person_profile_sha256=arv2_person_profile_sha256(),
                catalog=COMMITTEE_CATALOG,
            )

            contacts = await _contacts(conn, account)
            assert [row["full_name"] for row in contacts] == ["Dana Reyes", "Sam Okafor"]
            # The strong key is folded exactly as the entity layer folds it, so a re-run's lookup
            # finds this row rather than colliding with it.
            assert contacts[0]["linkedin_url"] == "https://www.linkedin.com/in/dana-reyes"
            assert contacts[1]["linkedin_url"] is None
            assert len(result.contacts_created) == 2
            assert result.linkedin_missing == ("Sam Okafor",)

            assert [(skip.name, skip.reason) for skip in result.skipped] == [
                ("", "vacant_seat"),
                ("Unconfirmed Person", "unconfirmed"),
                ("Past The Cap", "committee_cap"),
            ]

            # One person job per admitted member, pinned to the PERSON profile, under this run.
            jobs = {job.job_id: job for job in await store.list_jobs(conn, run_id=run.run_id)}
            person_jobs = [row for row in jobs.values() if row.subject_type == "person"]
            assert len(person_jobs) == 2
            for row in person_jobs:
                assert row.account_entity_id == account
                assert row.profile_sha256 == arv2_person_profile_sha256()
                assert row.status == "not_started"
            assert {row.subject_entity_id for row in person_jobs} == {
                UUID(str(row["id"])) for row in contacts
            }
            assert {queued.job_id for queued in result.jobs} == {row.job_id for row in person_jobs}
            assert {queued.run_id for queued in result.jobs} == {run.run_id}
            assert {queued.workspace_id for queued in result.jobs} == {run.workspace_id}

            # The three committee-member claims land on the person, not on the account.
            dana = EntityId(UUID(str(contacts[0]["id"])))
            claims = await claims_for(
                conn, dana, scope=WorkspaceScope.for_workspace(run.workspace_id)
            )
            by_field = {claim.field_key: claim for claim in claims}
            assert set(by_field) == {
                "contact.persona",
                "contact.role_on_committee",
                "contact.current_title",
            }
            assert by_field["contact.persona"].value_json == "economic_buyer"
            assert by_field["contact.current_title"].value_json == "VP Marketing"
            assert by_field["contact.persona"].source_url == "https://probook.ai/team"
            assert by_field["contact.persona"].evidence_span == "Dana Reyes, VP Marketing"
            assert by_field["contact.persona"].run_id == run.run_id

    run_async(scenario())


def test_each_member_is_tagged_on_the_jobs_trace_as_they_are_born() -> None:
    """A member born here tags the job's trace, so "which traces carried contact X" is a query."""

    async def scenario() -> None:
        with langfuse_installed() as (exporter, _provider):
            async with rollback_conn(seed_pack=True) as conn:
                run, account, job_id = await _seed(conn)
                job = await store.read_job(conn, job_id=job_id)
                assert job is not None
                with observation("job", as_type="agent"):
                    await run_committee_step(
                        conn,
                        job=job,
                        run=run,
                        scope=_scope(run, account),
                        candidates=CANDIDATES,
                        writer=LenientClaimWriter(lenient=True),
                        person_profile_sha256=arv2_person_profile_sha256(),
                        catalog=COMMITTEE_CATALOG,
                    )
                members = [str(row["id"]) for row in await _contacts(conn, account)]
            spans = finished_spans(exporter)
        tagged = [
            _attributes(s)[f"langfuse.trace.metadata.{ENTITIES_METADATA_KEY}"]
            for s in spans
            if s.name == "entities.tagged"
        ]
        assert members and len(members) == 2
        assert tagged, "a confirmed member tags the trace it was born on"
        assert tagged[0].split(",") == [members[0]], "the first member tags the trace alone"
        assert set(tagged[-1].split(",")) == set(members)

    run_async(scenario())


def test_a_re_settled_job_creates_no_second_contact_job_or_claim() -> None:
    """The person job row is the member's latch: a second settle re-offers, and writes nothing."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            job = await store.read_job(conn, job_id=job_id)
            assert job is not None
            scope = _scope(run, account)
            writer = LenientClaimWriter(lenient=True)

            first = await run_committee_step(
                conn,
                job=job,
                run=run,
                scope=scope,
                candidates=CANDIDATES,
                writer=writer,
                person_profile_sha256=arv2_person_profile_sha256(),
                catalog=COMMITTEE_CATALOG,
            )
            second = await run_committee_step(
                conn,
                job=job,
                run=run,
                scope=scope,
                candidates=CANDIDATES,
                writer=writer,
                person_profile_sha256=arv2_person_profile_sha256(),
                catalog=COMMITTEE_CATALOG,
            )

            assert second.contacts_created == ()
            # Every member is still offered: a lost fleet offer is repaired by re-settling, and a
            # duplicate dedup key is a no-op at the real queue.
            assert {queued.job_id for queued in second.jobs} == {
                queued.job_id for queued in first.jobs
            }
            assert len(await _contacts(conn, account)) == 2
            jobs = await store.list_jobs(conn, run_id=run.run_id)
            assert len([row for row in jobs if row.subject_type == "person"]) == 2

            dana = EntityId(UUID(str((await _contacts(conn, account))[0]["id"])))
            claims = await claims_for(
                conn, dana, scope=WorkspaceScope.for_workspace(run.workspace_id)
            )
            assert len(claims) == 3, "the second settle wrote no second copy of the three claims"

    run_async(scenario())


def test_a_candidate_whose_linkedin_is_already_a_contact_reuses_that_person() -> None:
    """The LinkedIn URL is the strong key: the committee joins the person, never duplicates them."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            existing = await insert_contact_entity(
                conn,
                account_entity_id=EntityId(account),
                full_name="Dana Reyes",
                # Stored unfolded on purpose: the candidate's URL has the trailing slash and the
                # capitals a real page carries, and both must fold onto this row.
                linkedin_url="https://www.LinkedIn.com/in/dana-reyes",
            )
            job = await store.read_job(conn, job_id=job_id)
            assert job is not None

            result = await run_committee_step(
                conn,
                job=job,
                run=run,
                scope=_scope(run, account),
                candidates=CANDIDATES[:1],
                writer=LenientClaimWriter(lenient=True),
                person_profile_sha256=arv2_person_profile_sha256(),
                catalog=COMMITTEE_CATALOG,
            )

            assert result.contacts_created == ()
            assert len(await _contacts(conn, account)) == 1
            person_jobs = [
                row
                for row in await store.list_jobs(conn, run_id=run.run_id)
                if row.subject_type == "person"
            ]
            assert [row.subject_entity_id for row in person_jobs] == [UUID(str(existing))]

    run_async(scenario())


def test_an_unwritable_member_is_a_recorded_skip_not_a_lost_transaction() -> None:
    """The failure law: one broken member costs itself, never the account job's terminal row."""

    class _Exploding(LenientClaimWriter):
        async def write(self, conn: AsyncConnection, draft: Any) -> Any:
            if draft.field_key == "contact.persona":
                # A write that reaches the database and fails is the case that matters: it poisons
                # the transaction unless the member's work is its own savepoint.
                await conn.execute(text("SELECT 1 FROM contact_entity WHERE id = 'not-a-uuid'"))
            return await super().write(conn, draft)

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            job = await store.read_job(conn, job_id=job_id)
            assert job is not None

            result = await run_committee_step(
                conn,
                job=job,
                run=run,
                scope=_scope(run, account),
                candidates=CANDIDATES[:1],
                writer=_Exploding(lenient=True),
                person_profile_sha256=arv2_person_profile_sha256(),
                catalog=COMMITTEE_CATALOG,
            )

            assert [skip.reason for skip in result.skipped] == ["member_not_written"]
            assert result.jobs == () and result.contacts_created == ()
            # The member rolled back whole — no half-written person — and the connection is still
            # usable, which is the property the account job's ``finish_job`` depends on.
            assert await _contacts(conn, account) == []
            assert await store.read_job(conn, job_id=job_id) is not None

    run_async(scenario())


def test_a_member_the_workspace_already_holds_elsewhere_keeps_their_own_employer() -> None:
    """The strong key is workspace-wide, so the entity layer's employer is the job's account.

    One person is one row: a candidate confirmed on this account's page whose LinkedIn already
    belongs to a contact of another account resolves to that contact — and their person job carries
    the account the *entity* names, exactly as an on-demand person launch would.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            elsewhere = await insert_account_entity(
                conn,
                canonical_name="Elsewhere",
                primary_domain="elsewhere.example",
                workspace_id=run.workspace_id,
            )
            held = await insert_contact_entity(
                conn,
                account_entity_id=elsewhere,
                full_name="Dana Reyes",
                linkedin_url="https://www.linkedin.com/in/dana-reyes",
            )
            job = await store.read_job(conn, job_id=job_id)
            assert job is not None

            result = await run_committee_step(
                conn,
                job=job,
                run=run,
                scope=_scope(run, account),
                candidates=CANDIDATES[:1],
                writer=LenientClaimWriter(lenient=True),
                person_profile_sha256=arv2_person_profile_sha256(),
                catalog=COMMITTEE_CATALOG,
            )

            assert result.contacts_created == ()
            assert await _contacts(conn, account) == []
            person_jobs = [
                row
                for row in await store.list_jobs(conn, run_id=run.run_id)
                if row.subject_type == "person"
            ]
            assert [row.subject_entity_id for row in person_jobs] == [UUID(str(held))]
            assert [row.account_entity_id for row in person_jobs] == [UUID(str(elsewhere))]

    run_async(scenario())


def test_two_people_of_one_name_under_the_account_are_refused_rather_than_guessed() -> None:
    """The same-name trap, at the one place the step resolves a person without a strong key."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            run, account, job_id = await _seed(conn)
            for suffix in ("a", "b"):
                await insert_contact_entity(
                    conn,
                    account_entity_id=EntityId(account),
                    full_name="Sam Okafor",
                    linkedin_url=f"https://www.linkedin.com/in/sam-okafor-{suffix}",
                )
            job = await store.read_job(conn, job_id=job_id)
            assert job is not None

            # The third candidate is the one with a name and no LinkedIn URL.
            result = await run_committee_step(
                conn,
                job=job,
                run=run,
                scope=_scope(run, account),
                candidates=CANDIDATES[2:3],
                writer=LenientClaimWriter(lenient=True),
                person_profile_sha256=arv2_person_profile_sha256(),
                catalog=COMMITTEE_CATALOG,
            )

            assert [(skip.name, skip.reason) for skip in result.skipped] == [
                ("Sam Okafor", "ambiguous_name")
            ]
            assert result.jobs == () and result.contacts_created == ()
            assert len(await _contacts(conn, account)) == 2, "no third row was invented"

    run_async(scenario())
