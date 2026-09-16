"""The R2 run/job/annotation store: one function per transition, against the real tables."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2 import account_research_store as store
from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_core import (
    EntityType,
    ExtractionMethod,
    ResearchMode,
    new_project_run_id,
    new_run_id,
)
from clue_research.durable.project_run import ensure_project_run
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.profiling.committee.fields import load_committee_pack
from clue_research.profiling.fields import load_deep_profiling_pack
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

SHA = "a" * 64


async def _seed(conn: AsyncConnection) -> tuple[store.RunRow, tuple[UUID, UUID]]:
    """A workspace, its project + project run, two accounts, and the run row that pins them."""
    project = await seed_project(conn, "ws_r2_store")
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="icp-clue-abm-buyers",
        icp_version=1,
    )
    accounts = []
    for name, domain in (("Zafran", "zafran.io"), ("Probook", "probook.ai")):
        accounts.append(
            await insert_account_entity(
                conn,
                canonical_name=name,
                primary_domain=domain,
                workspace_id=project.workspace_id,
            )
        )
    row = store.RunRow(
        run_id=uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=project.brand_id,
        project_run_id=UUID(str(project_run_id)),
        icp_artifact_key="ws_r2_store/icp",
        icp_artifact_sha256=SHA,
        icp_key="icp-clue-abm-buyers",
        icp_version=1,
        product_selection_version=1,
        effort="full",
        committee_cap=3,
        directive_text="focus on hiring signals",
        profile_ref="arv2-account/v1",
        profile_sha256="b" * 64,
        requested_by_user_id="user_founder",
        request_sha256="c" * 64,
    )
    return row, (accounts[0], accounts[1])


def test_a_run_and_its_jobs_walk_the_seam_1_states() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with rollback_conn() as conn:
            run, (first_account, second_account) = await _seed(conn)
            assert await store.create_run(conn, run) is True
            assert await store.create_run(conn, run) is False

            stored = await store.read_run(conn, run_id=run.run_id)
            assert stored is not None
            assert stored.status == "not_started" and stored.finished_at is None
            assert stored.directive_text == run.directive_text
            assert stored.icp_artifact_sha256 == SHA
            assert stored.committee_cap == 3 and stored.effort == "full"
            assert stored.product_selection_version == 1
            assert stored.brand_id == run.brand_id
            assert stored.created_at is not None

            first, second = uuid4(), uuid4()
            for job_id, account in ((first, first_account), (second, second_account)):
                assert (
                    await store.create_job(
                        conn,
                        job_id=job_id,
                        run_id=run.run_id,
                        workspace_id=run.workspace_id,
                        account_entity_id=account,
                    )
                    is True
                )
            assert (
                await store.create_job(
                    conn,
                    job_id=first,
                    run_id=run.run_id,
                    workspace_id=run.workspace_id,
                    account_entity_id=first_account,
                )
                is False
            )
            assert await store.refresh_run_status(conn, run_id=run.run_id) == "not_started"

            begun = await store.begin_job(conn, job_id=first)
            assert begun is not None
            assert begun.status == "in_progress" and begun.attempt == 1
            assert begun.started_at is not None and begun.finished_at is None
            assert begun.account_entity_id == first_account
            assert await store.refresh_run_status(conn, run_id=run.run_id) == "in_progress"

            await store.finish_job(
                conn,
                job_id=first,
                status="completed",
                finalization={"outcome": "completed", "claims": 12},
                model_rounds=9,
                tool_calls=31,
                cost_usd=Decimal("1.250000"),
                credits=Decimal("4.500"),
                media_seconds=61,
            )
            done = await store.read_job(conn, job_id=first)
            assert done is not None
            assert done.status == "completed" and done.finished_at is not None
            assert done.finalization == {"outcome": "completed", "claims": 12}
            assert done.failure_code is None and done.failure_message is None
            assert done.model_rounds == 9 and done.tool_calls == 31
            assert done.cost_usd == Decimal("1.250000")
            assert done.credits == Decimal("4.500")
            assert done.media_seconds == 61
            # One completed, one still queued: the run is under way, not finished.
            assert await store.refresh_run_status(conn, run_id=run.run_id) == "in_progress"
            assert (await store.read_run(conn, run_id=run.run_id)).finished_at is None  # type: ignore[union-attr]

            # A terminal job neither re-begins nor suspends.
            assert await store.begin_job(conn, job_id=first) is None
            await store.suspend_job(conn, job_id=first)
            assert (await store.read_job(conn, job_id=first)).status == "completed"  # type: ignore[union-attr]

            assert await store.begin_job(conn, job_id=second) is not None
            await store.suspend_job(conn, job_id=second)
            suspended = await store.read_job(conn, job_id=second)
            assert suspended is not None and suspended.status == "suspended"
            assert await store.refresh_run_status(conn, run_id=run.run_id) == "suspended"

            resumed = await store.begin_job(conn, job_id=second)
            assert resumed is not None and resumed.attempt == 2
            await store.finish_job(
                conn,
                job_id=second,
                status="needs_review",
                finalization={"outcome": "needs_review"},
                failure_code="link_audit_failed",
                failure_message="two claims cite pages that do not carry them",
                model_rounds=4,
                tool_calls=12,
                cost_usd=Decimal("0.500000"),
                credits=Decimal("0"),
                media_seconds=0,
            )
            flagged = await store.read_job(conn, job_id=second)
            assert flagged is not None
            assert flagged.status == "needs_review"
            assert flagged.failure_code == "link_audit_failed"
            assert flagged.finished_at is not None

            assert await store.refresh_run_status(conn, run_id=run.run_id) == "needs_review"
            closed = await store.read_run(conn, run_id=run.run_id)
            assert closed is not None and closed.finished_at is not None

            jobs = await store.list_jobs(conn, run_id=run.run_id)
            assert {job.job_id for job in jobs} == {first, second}
            assert len(jobs) == 2

    run_async(scenario())


def test_a_run_whose_jobs_all_completed_is_completed() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with rollback_conn() as conn:
            run, (account, _) = await _seed(conn)
            await store.create_run(conn, run)
            job_id = uuid4()
            await store.create_job(
                conn,
                job_id=job_id,
                run_id=run.run_id,
                workspace_id=run.workspace_id,
                account_entity_id=account,
            )
            await store.begin_job(conn, job_id=job_id)
            await store.finish_job(
                conn,
                job_id=job_id,
                status="completed",
                finalization={"outcome": "completed"},
                model_rounds=1,
                tool_calls=1,
                cost_usd=Decimal("0"),
                credits=Decimal("0"),
                media_seconds=0,
            )
            status = await store.refresh_run_status(conn, run_id=run.run_id)
            closed = await store.read_run(conn, run_id=run.run_id)
            return status, closed

    status, closed = run_async(scenario())
    assert status == "completed"
    assert closed is not None and closed.finished_at is not None


def test_annotations_land_one_row_per_claim_and_verdict() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with rollback_conn() as conn:
            run, (account, _) = await _seed(conn)
            await store.create_run(conn, run)
            job_id = uuid4()
            await store.create_job(
                conn,
                job_id=job_id,
                run_id=run.run_id,
                workspace_id=run.workspace_id,
                account_entity_id=account,
            )
            writer = LenientClaimWriter(lenient=True)
            claims = []
            for field_key, value in (
                ("core.account_name", "Zafran Security"),
                ("core.primary_domain", "zafran.io"),
            ):
                receipt = await writer.write(
                    conn,
                    ClaimDraft(
                        entity_id=account,
                        entity_type=EntityType.ACCOUNT,
                        field_key=field_key,
                        value_json=value,
                        extraction_method=ExtractionMethod.API,
                        run_id=new_run_id(),
                        research_mode=ResearchMode.ACCOUNT_PROFILING,
                        workspace_id=run.workspace_id,
                        source_url="https://zafran.io/",
                    ),
                )
                claims.append(UUID(str(receipt.claim_id)))
            written = await store.record_annotations(
                conn,
                job_id=job_id,
                claim_ids_by_verdict={
                    "EXACT": [claims[0]],
                    "NOT_FOUND": [claims[1]],
                    "PARTIAL": [],
                },
            )
            empty = await store.record_annotations(
                conn, job_id=job_id, claim_ids_by_verdict={"PARTIAL": []}
            )
            rows = (
                await conn.execute(
                    text(
                        "SELECT claim_id, kind, verdict FROM arv2_claim_annotation "
                        "WHERE job_id = :job"
                    ),
                    {"job": job_id},
                )
            ).all()
            return (
                written,
                empty,
                sorted((str(r.claim_id), r.kind, r.verdict) for r in rows),
                claims,
            )

    written, empty, rows, claims = run_async(scenario())
    assert written == 2
    assert empty == 0
    assert rows == sorted(
        [(str(claims[0]), "link_audit", "EXACT"), (str(claims[1]), "link_audit", "NOT_FOUND")]
    )


def test_an_annotation_records_why_and_the_tally_is_keyed_by_verdict_and_reason() -> None:
    """The audit's *reason* is durable, and the tally a receipt reads is keyed by it.

    Two claims can both be ``fetch_failed`` — one page empty, one page dead — and a tally that
    collapsed them would hide the only difference a human could act on.
    """

    async def scenario():  # type: ignore[no-untyped-def]
        async with rollback_conn() as conn:
            run, (account, _) = await _seed(conn)
            await store.create_run(conn, run)
            job_id = uuid4()
            await store.create_job(
                conn,
                job_id=job_id,
                run_id=run.run_id,
                workspace_id=run.workspace_id,
                account_entity_id=account,
            )
            writer = LenientClaimWriter(lenient=True)
            claims = []
            for field_key, value in (
                ("core.account_name", "Zafran Security"),
                ("core.primary_domain", "zafran.io"),
                ("core.industry", "cyber security"),
            ):
                receipt = await writer.write(
                    conn,
                    ClaimDraft(
                        entity_id=account,
                        entity_type=EntityType.ACCOUNT,
                        field_key=field_key,
                        value_json=value,
                        extraction_method=ExtractionMethod.API,
                        run_id=new_run_id(),
                        research_mode=ResearchMode.ACCOUNT_PROFILING,
                        workspace_id=run.workspace_id,
                        source_url="https://zafran.io/",
                    ),
                )
                claims.append(UUID(str(receipt.claim_id)))
            written = await store.record_annotations(
                conn,
                job_id=job_id,
                rows=[
                    store.AnnotationRow(
                        claim_id=claims[0],
                        verdict="fetch_failed",
                        detail={
                            "reason": "page_empty",
                            "url": "https://zafran.io/",
                            "origin": "exa_contents",
                            "structuring_mode": None,
                        },
                    ),
                    store.AnnotationRow(
                        claim_id=claims[1],
                        verdict="fetch_failed",
                        detail={"reason": "page_unreachable", "url": "https://zafran.io/gone"},
                    ),
                ],
            )
            # The older verdict-only form still writes its row; it simply says nothing about why.
            await store.record_annotations(
                conn, job_id=job_id, claim_ids_by_verdict={"EXACT": [claims[2]]}
            )
            detail = (
                await conn.execute(
                    text(
                        "SELECT detail_json FROM arv2_claim_annotation "
                        "WHERE job_id = :job AND claim_id = :claim"
                    ),
                    {"job": job_id, "claim": claims[0]},
                )
            ).scalar_one()
            return written, detail, await store.job_link_audit(conn, job_id=job_id)

    written, detail, tally = run_async(scenario())
    assert written == 2
    assert detail == {
        "reason": "page_empty",
        "url": "https://zafran.io/",
        "origin": "exa_contents",
        "structuring_mode": None,
    }
    assert tally == {
        "fetch_failed/page_empty": 1,
        "fetch_failed/page_unreachable": 1,
        f"EXACT/{store.UNRECORDED_REASON}": 1,
    }


def test_a_person_job_carries_its_subject_contact_and_its_own_profile_pin() -> None:
    """R3: a job names *what* it researches. A person job pins the contact and its own profile."""

    async def scenario():  # type: ignore[no-untyped-def]
        async with rollback_conn() as conn:
            run, (account, _other) = await _seed(conn)
            assert await store.create_run(conn, run) is True

            contact, job_id = uuid4(), uuid4()
            assert (
                await store.create_job(
                    conn,
                    job_id=job_id,
                    run_id=run.run_id,
                    workspace_id=run.workspace_id,
                    account_entity_id=account,
                    subject_type="person",
                    subject_entity_id=contact,
                    profile_sha256=SHA,
                )
                is True
            )

            # Every reader maps the three new columns, not just the one the writer touched.
            read = await store.read_job(conn, job_id=job_id)
            assert read is not None
            assert read.subject_type == "person"
            assert read.subject_entity_id == contact
            assert read.profile_sha256 == SHA
            assert read.account_entity_id == account

            begun = await store.begin_job(conn, job_id=job_id)
            assert begun is not None
            assert begun.subject_type == "person" and begun.subject_entity_id == contact
            assert begun.profile_sha256 == SHA

            listed = {job.job_id: job for job in await store.list_jobs(conn, run_id=run.run_id)}
            assert listed[job_id].subject_type == "person"
            assert listed[job_id].subject_entity_id == contact
            assert listed[job_id].profile_sha256 == SHA

    run_async(scenario())


def test_one_account_subject_per_run_but_many_person_subjects_under_it() -> None:
    """The uniqueness moved to the *subject*: one account row, one row per committee member."""

    async def scenario():  # type: ignore[no-untyped-def]
        async with rollback_conn() as conn:
            run, (account, _other) = await _seed(conn)
            assert await store.create_run(conn, run) is True

            account_job = uuid4()
            assert (
                await store.create_job(
                    conn,
                    job_id=account_job,
                    run_id=run.run_id,
                    workspace_id=run.workspace_id,
                    account_entity_id=account,
                )
                is True
            )
            # The default subject is the account itself: no contact, no per-job pin.
            queued = await store.read_job(conn, job_id=account_job)
            assert queued is not None
            assert queued.subject_type == "account"
            assert queued.subject_entity_id is None
            assert queued.profile_sha256 is None

            # A second account subject in the same run is still refused (unchanged from R2).
            assert (
                await store.create_job(
                    conn,
                    job_id=uuid4(),
                    run_id=run.run_id,
                    workspace_id=run.workspace_id,
                    account_entity_id=account,
                )
                is False
            )

            # Two committee members of that same account each get their own job.
            for contact in (uuid4(), uuid4()):
                assert (
                    await store.create_job(
                        conn,
                        job_id=uuid4(),
                        run_id=run.run_id,
                        workspace_id=run.workspace_id,
                        account_entity_id=account,
                        subject_type="person",
                        subject_entity_id=contact,
                        profile_sha256=SHA,
                    )
                    is True
                )
            jobs = await store.list_jobs(conn, run_id=run.run_id)
            assert len(jobs) == 3
            assert sum(1 for job in jobs if job.subject_type == "person") == 2

            # …and re-queuing one of them is refused by the same subject uniqueness.
            repeated = uuid4()
            assert (
                await store.create_job(
                    conn,
                    job_id=uuid4(),
                    run_id=run.run_id,
                    workspace_id=run.workspace_id,
                    account_entity_id=account,
                    subject_type="person",
                    subject_entity_id=repeated,
                    profile_sha256=SHA,
                )
                is True
            )
            assert (
                await store.create_job(
                    conn,
                    job_id=uuid4(),
                    run_id=run.run_id,
                    workspace_id=run.workspace_id,
                    account_entity_id=account,
                    subject_type="person",
                    subject_entity_id=repeated,
                    profile_sha256=SHA,
                )
                is False
            )

    run_async(scenario())


def test_a_subject_without_its_entity_is_unrepresentable() -> None:
    """The CHECK is biconditional: a person job names a contact, an account job names none."""

    async def scenario():  # type: ignore[no-untyped-def]
        async with rollback_conn() as conn:
            run, (account, _other) = await _seed(conn)
            assert await store.create_run(conn, run) is True

            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await store.create_job(
                        conn,
                        job_id=uuid4(),
                        run_id=run.run_id,
                        workspace_id=run.workspace_id,
                        account_entity_id=account,
                        subject_type="person",
                        subject_entity_id=None,
                    )

            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await store.create_job(
                        conn,
                        job_id=uuid4(),
                        run_id=run.run_id,
                        workspace_id=run.workspace_id,
                        account_entity_id=account,
                        subject_type="account",
                        subject_entity_id=uuid4(),
                    )

            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO arv2_research_job "
                            "(job_id, run_id, workspace_id, account_entity_id, subject_type) "
                            "VALUES (:job_id, :run_id, :ws, :account, 'committee')"
                        ),
                        {
                            "job_id": uuid4(),
                            "run_id": run.run_id,
                            "ws": run.workspace_id,
                            "account": account,
                        },
                    )

    run_async(scenario())


def test_the_person_catalog_is_the_contact_menu_plus_the_work_email() -> None:
    """Read from the registry, never enumerated in code: the person menu is every registered
    ``contact.*`` field plus the person's own work email, and a facet carries the
    ``use_class_hint`` the registry declares in its ``validation``.

    No ``account.*`` key is on it. A person job stamps every claim to the contact, so an account
    fact offered here would be written on the person; the agent reads the account's facts from the
    already-established block its context carries instead.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:  # CORE_PACK → core.work_email
            await load_deep_profiling_pack(conn)  # contact.facet.alma_mater
            await load_committee_pack(conn)  # contact.current_title / persona / location
            await load_arv2_pack(conn)  # contact.facet.hobby, with the personal hint

            catalog = await store.read_person_catalog(conn, workspace_id="catalog-test")

            keys = catalog.keys()
            assert {
                "contact.current_title",
                "contact.persona",
                "contact.role_on_committee",
                "contact.current_location",
                "contact.facet.alma_mater",
                "contact.facet.hobby",
                "core.work_email",
            } <= keys
            # An account fact written through this menu would land on the person, so none is on it.
            assert not [key for key in keys if key.startswith("account.")]
            assert "core.revenue_band" not in keys and "core.employee_count" not in keys

            hobby = catalog.spec("contact.facet.hobby")
            assert hobby is not None and hobby.use_class_hint == "personal-public-non-sensitive"
            career = catalog.spec("contact.facet.career_history")
            assert career is not None and career.use_class_hint == "professional-public"
            # A plain contact field declares no hint: the claim path's default decides.
            title = catalog.spec("contact.current_title")
            assert title is not None and title.use_class_hint is None
            assert title.value_schema == {"type": "string"}

            # The three menu sections are the three the model is shown.
            assert {spec.key for spec in catalog.account} == {"core.work_email"}
            assert all(spec.key.startswith("contact.facet.") for spec in catalog.facet)
            assert all(
                spec.key.startswith("contact.") and not spec.key.startswith("contact.facet.")
                for spec in catalog.contact
            )

    run_async(scenario())


def test_find_contact_by_name_resolves_one_match_and_refuses_an_ambiguous_one() -> None:
    """``contact.reports_to`` needs a contact id the agent cannot know, so the name is resolved.

    Two people of the same name under one account is the very trap this lane exists to refuse, so
    an ambiguous name resolves to nothing rather than to whichever row came back first.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, "ws_r2_reports_to")
            account = await insert_account_entity(
                conn,
                canonical_name="Probook",
                primary_domain="probook.ai",
                workspace_id=project.workspace_id,
            )
            other = await insert_account_entity(
                conn,
                canonical_name="Sysdig",
                primary_domain="sysdig.com",
                workspace_id=project.workspace_id,
            )
            manager = await insert_contact_entity(
                conn,
                account_entity_id=account,
                full_name="Dana Reyes",
                linkedin_url="https://www.linkedin.com/in/dana-reyes",
            )
            await insert_contact_entity(
                conn,
                account_entity_id=other,
                full_name="Ambiguous Twin",
                linkedin_url="https://www.linkedin.com/in/twin-a",
            )

            found = await store.find_contact_by_name(
                conn,
                workspace_id=project.workspace_id,
                account_id=UUID(str(account)),
                name="  dana reyes ",
            )
            assert found == UUID(str(manager)), "the match folds case and surrounding whitespace"

            # A contact under a *different* account of the same workspace is not this account's.
            assert (
                await store.find_contact_by_name(
                    conn,
                    workspace_id=project.workspace_id,
                    account_id=UUID(str(account)),
                    name="Ambiguous Twin",
                )
                is None
            )

            await insert_contact_entity(
                conn,
                account_entity_id=account,
                full_name="Dana Reyes",
                linkedin_url="https://www.linkedin.com/in/dana-reyes-2",
            )
            assert (
                await store.find_contact_by_name(
                    conn,
                    workspace_id=project.workspace_id,
                    account_id=UUID(str(account)),
                    name="Dana Reyes",
                )
                is None
            ), "two of the same name resolve to nobody; picking one would be a guess"

    run_async(scenario())
