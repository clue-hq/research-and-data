"""The R4 discovery store: one function per transition, against the real tables."""

from __future__ import annotations

import dataclasses
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.discovery_store import (
    CandidateRow,
    DiscoveryRunRow,
    SearchRow,
    active_discoveries_for_threads,
    active_discovery_for_project,
    begin_discovery_run,
    create_discovery_run,
    create_search,
    end_discovery_run,
    find_discovery_run,
    finish_discovery_run,
    finish_search,
    list_candidates,
    list_searches,
    mark_candidates_approved,
    project_found_domains,
    project_webset_ids,
    read_discovery_run,
    record_discovery_progress,
    record_search_webset,
    record_verdicts,
    record_wake_turn,
    release_discovery_for_turn,
    request_discovery_stop,
    seller_domain,
    stop_requested,
    suspend_discovery_run,
    upsert_candidate,
)
from clue_core import ProjectPhase, ProjectRunId
from clue_research.durable.project_run import ensure_project_run
from clue_research.identity import insert_account_entity
from clue_spine import Project
from tests._identity import seed_principal
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

WORKSPACE = "ws_r4_store"
PROJECT_RUN_ID = uuid4()


async def _seed(conn: AsyncConnection) -> Project:
    """A workspace, its brand + project, and the project run every discovery run hangs off."""
    project = await seed_project(conn, WORKSPACE)
    await ensure_project_run(
        conn,
        project_run_id=ProjectRunId(PROJECT_RUN_ID),
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="clue-abm-buyers",
        icp_version=1,
        phase=ProjectPhase.DEEP,
    )
    return project


def _run(
    project: Project,
    *,
    request_sha256: str = "a" * 64,
    target: int = 20,
    launched_thread_id: str | None = None,
) -> DiscoveryRunRow:
    return DiscoveryRunRow(
        run_id=uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=str(project.brand_id),
        project_run_id=PROJECT_RUN_ID,
        icp_artifact_key="ws/abc",
        icp_artifact_sha256="b" * 64,
        icp_key="clue-abm-buyers",
        icp_version=1,
        requested_by_user_id="user-1",
        request_sha256=request_sha256,
        target_count=target,
        relaxed_enabled=True,
        criteria_gate_keys=("geography", "stage"),
        launched_thread_id=launched_thread_id,
    )


async def _release(conn: AsyncConnection, run: DiscoveryRunRow) -> None:
    """End a run and free its project, so the same project may launch another."""
    await end_discovery_run(
        conn, run_id=run.run_id, status="completed", end_reason="filled", summary={}, release=True
    )


def test_run_create_is_idempotent_and_replay_finds_it_by_request_sha() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project)
            assert await create_discovery_run(conn, row) is True
            assert await create_discovery_run(conn, row) is False
            found = await find_discovery_run(
                conn, workspace_id=row.workspace_id, request_sha256=row.request_sha256
            )
            assert found is not None
            assert found.run_id == row.run_id
            assert found.status == "not_started"
            assert found.criteria_gate_keys == ("geography", "stage")
            assert found.relaxed_enabled is True
            # A launched run has bought nothing yet: not a single search.
            assert await list_searches(conn, run_id=row.run_id) == ()
            assert found.asked is None

    run_async(scenario())


def test_begin_claims_only_not_started_or_suspended_and_finish_records_counts() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project)
            await create_discovery_run(conn, row)
            begun = await begin_discovery_run(conn, run_id=row.run_id)
            assert begun is not None
            assert begun.status == "in_progress"
            assert begun.started_at is not None
            assert await begin_discovery_run(conn, run_id=row.run_id) is None
            first = SearchRow(
                run_id=row.run_id,
                ordinal=1,
                kind="strict",
                external_id=f"arv2-discovery:{row.run_id}:1",
                asked=20,
                criteria=("US", "Series A"),
            )
            held = await create_search(conn, first)
            # Written before anything is bought: no webset yet, and the run's ask is its sum.
            assert held.webset_id is None and held.criteria == ("US", "Series A")
            # A second attempt that re-records the same search gets the row it already wrote.
            assert await create_search(conn, dataclasses.replace(first, asked=99)) == held
            await record_search_webset(
                conn, run_id=row.run_id, ordinal=1, webset_id="ws_123", recall_estimate=210
            )
            await finish_search(
                conn, run_id=row.run_id, ordinal=1, found=15, analyzed=333, recall_estimate=None
            )
            topup = SearchRow(
                run_id=row.run_id,
                ordinal=2,
                kind="strict_topup",
                external_id=f"arv2-discovery:{row.run_id}:2",
                asked=5,
                criteria=("US", "Series A"),
                exclude_webset_ids=("ws_123",),
            )
            await create_search(conn, topup)
            await finish_discovery_run(
                conn,
                run_id=row.run_id,
                status="completed",
                found_strict=15,
                found_relaxed=0,
                analyzed=333,
                receipt={"asked": 25},
            )
            done = await read_discovery_run(conn, run_id=row.run_id)
            assert done is not None
            assert done.status == "completed"
            assert done.found_strict == 15
            assert done.receipt == {"asked": 25}
            assert done.asked == 25  # both searches' asks, each counted once
            assert done.recall_estimate == 210  # search 1's estimate is the run's
            assert done.finished_at is not None
            one, two = await list_searches(conn, run_id=row.run_id)
            assert (one.webset_id, one.found, one.analyzed) == ("ws_123", 15, 333)
            assert one.finished_at is not None and one.recall_estimate == 210
            assert (two.kind, two.webset_id, two.exclude_webset_ids) == (
                "strict_topup",
                None,
                ("ws_123",),
            )
            # A finished run is never reclaimed: asking for more is a new run.
            assert await begin_discovery_run(conn, run_id=row.run_id) is None

    run_async(scenario())


def test_suspend_parks_a_running_run_and_begin_reclaims_it() -> None:
    """A lost lease parks the run; the redelivered task picks it back up where it left off."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project)
            await create_discovery_run(conn, row)
            await begin_discovery_run(conn, run_id=row.run_id)
            await suspend_discovery_run(conn, run_id=row.run_id)
            parked = await read_discovery_run(conn, run_id=row.run_id)
            assert parked is not None and parked.status == "suspended"
            reclaimed = await begin_discovery_run(conn, run_id=row.run_id)
            assert reclaimed is not None and reclaimed.status == "in_progress"

    run_async(scenario())


def test_candidates_upsert_by_domain_and_a_later_run_remembers_everything_earlier_ones_found() -> (
    None
):
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            first = _run(project, request_sha256="1" * 64)
            await create_discovery_run(conn, first)
            cand = CandidateRow(
                candidate_id=uuid4(),
                run_id=first.run_id,
                workspace_id=first.workspace_id,
                project_id=first.project_id,
                pass_="strict",
                domain="probook.ai",
                websets_url="https://probook.com",
                name="Probook",
                provider_snapshot={"employees": 52},
            )
            cid = await upsert_candidate(conn, cand)
            assert (
                await upsert_candidate(
                    conn, dataclasses.replace(cand, candidate_id=uuid4(), name="Probook AI")
                )
                == cid
            )
            await record_verdicts(
                conn,
                candidate_id=cid,
                verdicts=[{"gate_key": "stage", "verdict": "pass"}],
                fit=1.0,
                disposition="pass",
                account_entity_id=None,
            )
            (row,) = await list_candidates(conn, run_id=first.run_id)
            assert row.name == "Probook AI"
            assert row.fit == 1.0
            assert row.disposition == "pass"
            assert row.verdicts[0]["gate_key"] == "stage"
            assert row.pass_ == "strict"
            # One unreleased discovery per project: the first must end before "find more".
            await _release(conn, first)
            second = _run(project, request_sha256="2" * 64)
            await create_discovery_run(conn, second)
            assert await project_found_domains(
                conn,
                workspace_id=first.workspace_id,
                project_id=first.project_id,
                before_run_id=second.run_id,
            ) == frozenset({"probook.ai"})
            # A run never hides its own candidates from itself.
            assert (
                await project_found_domains(
                    conn,
                    workspace_id=first.workspace_id,
                    project_id=first.project_id,
                    before_run_id=first.run_id,
                )
                == frozenset()
            )
            account = await insert_account_entity(
                conn,
                canonical_name="Probook",
                primary_domain="probook.ai",
                workspace_id=first.workspace_id,
            )
            await record_verdicts(
                conn,
                candidate_id=cid,
                verdicts=row.verdicts,
                fit=1.0,
                disposition="pass",
                account_entity_id=UUID(str(account)),
            )
            assert (
                await mark_candidates_approved(
                    conn,
                    workspace_id=first.workspace_id,
                    project_id=first.project_id,
                    account_entity_ids=[UUID(str(account))],
                    decided_by_user_id="user-1",
                )
                == 1
            )
            # An approval changes nothing about what was found: the company stays found.
            assert await project_found_domains(
                conn,
                workspace_id=first.workspace_id,
                project_id=first.project_id,
                before_run_id=second.run_id,
            ) == frozenset({"probook.ai"})
            (approved,) = await list_candidates(conn, run_id=first.run_id)
            assert approved.decision == "approved"
            assert approved.decided_by_user_id == "user-1"
            assert approved.decided_at is not None
            assert approved.account_entity_id == UUID(str(account))

    run_async(scenario())


def test_progress_updates_counters_without_landing_the_run() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project)
            assert await create_discovery_run(conn, row) is True
            assert await begin_discovery_run(conn, run_id=row.run_id) is not None
            await record_discovery_progress(
                conn, run_id=row.run_id, found_strict=7, found_relaxed=0, analyzed=120
            )
            mid = await read_discovery_run(conn, run_id=row.run_id)
            assert mid is not None
            assert (mid.found_strict, mid.found_relaxed, mid.analyzed) == (7, 0, 120)
            assert mid.status == "in_progress"
            assert mid.finished_at is None and mid.receipt is None
            # A later tick only moves the numbers forward; landing still owns status + receipt.
            await record_discovery_progress(
                conn, run_id=row.run_id, found_strict=12, found_relaxed=3, analyzed=300
            )
            later = await read_discovery_run(conn, run_id=row.run_id)
            assert later is not None
            assert (later.found_strict, later.found_relaxed, later.analyzed) == (12, 3, 300)
            # A zombie attempt's late tick carries smaller numbers; GREATEST keeps the larger
            # ones, so the counters a poller is watching never walk backwards.
            await record_discovery_progress(
                conn, run_id=row.run_id, found_strict=2, found_relaxed=0, analyzed=9
            )
            stale = await read_discovery_run(conn, run_id=row.run_id)
            assert stale is not None
            assert (stale.found_strict, stale.found_relaxed, stale.analyzed) == (12, 3, 300)

    run_async(scenario())


def test_a_later_run_skips_every_webset_the_projects_earlier_runs_bought() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            earlier = _run(project, request_sha256="3" * 64)
            later = _run(project, request_sha256="4" * 64)
            await create_discovery_run(conn, earlier)
            for ordinal, webset_id in ((1, "ws_a"), (3, "ws_b")):
                await create_search(
                    conn,
                    SearchRow(
                        run_id=earlier.run_id,
                        ordinal=ordinal,
                        kind="strict" if ordinal == 1 else "relaxed",
                        external_id=f"arv2-discovery:{earlier.run_id}:{ordinal}",
                        asked=5,
                        criteria=("US",),
                    ),
                )
                await record_search_webset(
                    conn,
                    run_id=earlier.run_id,
                    ordinal=ordinal,
                    webset_id=webset_id,
                    recall_estimate=None,
                )
            await _release(conn, earlier)
            await create_discovery_run(conn, later)
            assert await project_webset_ids(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                before_run_id=later.run_id,
            ) == ("ws_a", "ws_b")
            # The earlier run's own view excludes itself.
            assert (
                await project_webset_ids(
                    conn,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    before_run_id=earlier.run_id,
                )
                == ()
            )

    run_async(scenario())


def _candidate(
    run: DiscoveryRunRow,
    *,
    domain: str,
    disposition: str = "pending",
    excluded_by_gate: str | None = None,
) -> CandidateRow:
    return CandidateRow(
        candidate_id=uuid4(),
        run_id=run.run_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        pass_="strict",
        domain=domain,
        websets_url=None,
        name=domain,
        provider_snapshot={},
        disposition=disposition,  # type: ignore[arg-type]
        excluded_by_gate=excluded_by_gate,
    )


def test_the_brief_and_source_round_trip_with_the_launching_thread() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            brief = {"query": "Hotel operators in Spain.", "gates": [{"key": "hotels"}]}
            launching_turn = uuid4()
            row = dataclasses.replace(
                _run(project, launched_thread_id="thr_brief"),
                source="search",
                brief=brief,
                launching_turn_id=launching_turn,
            )
            await create_discovery_run(conn, row)
            held = await read_discovery_run(conn, run_id=row.run_id)
            assert held is not None
            assert (held.source, held.brief, held.launched_thread_id) == (
                "search",
                brief,
                "thr_brief",
            )
            assert held.launching_turn_id == launching_turn
            assert held.released_at is None and held.stop_requested_at is None
            assert held.end_reason is None and held.summary is None

    run_async(scenario())


def test_only_one_unreleased_run_per_project() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            first = _run(project, request_sha256="a" * 64, launched_thread_id="thr_a")
            second = _run(project, request_sha256="b" * 64, launched_thread_id="thr_b")
            assert await create_discovery_run(conn, first)
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await create_discovery_run(conn, second)
            active = await active_discovery_for_project(
                conn, workspace_id=first.workspace_id, project_id=first.project_id
            )
            assert active is not None and active.run_id == first.run_id
            assert active.launched_thread_id == "thr_a"

    run_async(scenario())


def test_end_with_release_frees_the_project() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project, request_sha256="c" * 64)
            await create_discovery_run(conn, row)
            await end_discovery_run(
                conn,
                run_id=row.run_id,
                status="completed",
                end_reason="filled",
                summary={"asked": 3},
                release=True,
            )
            assert (
                await active_discovery_for_project(
                    conn, workspace_id=row.workspace_id, project_id=row.project_id
                )
                is None
            )
            ended = await read_discovery_run(conn, run_id=row.run_id)
            assert ended is not None
            assert (ended.status, ended.end_reason, ended.summary) == (
                "completed",
                "filled",
                {"asked": 3},
            )
            assert ended.finished_at is not None and ended.released_at is not None

    run_async(scenario())


def test_the_wake_turn_releases_its_run() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project, request_sha256="d" * 64, launched_thread_id="thr_w")
            await create_discovery_run(conn, row)
            await end_discovery_run(
                conn,
                run_id=row.run_id,
                status="completed",
                end_reason="dry",
                summary={},
                release=False,
            )
            # Ended but not released: the project stays locked until the wake turn finishes.
            assert (
                await active_discovery_for_project(
                    conn, workspace_id=row.workspace_id, project_id=row.project_id
                )
                is not None
            )
            wake = uuid4()
            await record_wake_turn(conn, run_id=row.run_id, wake_turn_id=wake)
            by_thread = await active_discoveries_for_threads(
                conn, workspace_id=row.workspace_id, thread_ids=["thr_w", "thr_other"]
            )
            assert set(by_thread) == {"thr_w"}
            assert by_thread["thr_w"].wake_turn_id == wake
            # Another turn id releases nothing.
            assert (
                await release_discovery_for_turn(
                    conn, workspace_id=row.workspace_id, turn_id=uuid4()
                )
                is None
            )
            released = await release_discovery_for_turn(
                conn, workspace_id=row.workspace_id, turn_id=wake
            )
            assert released == row.run_id
            assert (
                await active_discoveries_for_threads(
                    conn, workspace_id=row.workspace_id, thread_ids=["thr_w"]
                )
                == {}
            )
            assert (
                await active_discoveries_for_threads(
                    conn, workspace_id=row.workspace_id, thread_ids=[]
                )
                == {}
            )

    run_async(scenario())


def test_stop_is_recorded_once_and_read_back() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project, request_sha256="e" * 64, launched_thread_id="thr_s")
            await create_discovery_run(conn, row)
            assert not await stop_requested(conn, run_id=row.run_id)
            stopped = await request_discovery_stop(
                conn, workspace_id=row.workspace_id, project_id=row.project_id, run_id=row.run_id
            )
            assert stopped is not None and stopped.stop_requested_at is not None
            assert await stop_requested(conn, run_id=row.run_id)
            again = await request_discovery_stop(
                conn, workspace_id=row.workspace_id, project_id=row.project_id, run_id=row.run_id
            )
            assert again is not None and again.stop_requested_at == stopped.stop_requested_at
            # A stop addressed through another project reaches nothing.
            assert (
                await request_discovery_stop(
                    conn, workspace_id=row.workspace_id, project_id="prj_other", run_id=row.run_id
                )
                is None
            )

    run_async(scenario())


def test_an_excluded_candidate_must_name_its_gate() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project, request_sha256="f" * 64)
            await create_discovery_run(conn, row)
            bad = _candidate(row, domain="x.com", disposition="excluded", excluded_by_gate=None)
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await upsert_candidate(conn, bad)
            good = _candidate(
                row, domain="y.com", disposition="excluded", excluded_by_gate="hotels"
            )
            await upsert_candidate(conn, good)
            (held,) = await list_candidates(conn, run_id=row.run_id)
            assert (held.disposition, held.excluded_by_gate) == ("excluded", "hotels")

    run_async(scenario())


def test_a_pending_candidate_is_excluded_through_record_verdicts() -> None:
    """The driver writes the candidate ``pending`` before its gates are asked, and a repeated
    upsert only refreshes the snapshot — so the exclusion is recorded by ``record_verdicts``, with
    the gate that excluded it, the verdicts behind it, and no account."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project, request_sha256="e" * 64)
            await create_discovery_run(conn, row)
            candidate_id = await upsert_candidate(conn, _candidate(row, domain="hotel.com"))
            verdicts = [{"gate_key": "sells_rooms", "verdict": "pass", "guard": "ok"}]
            await record_verdicts(
                conn,
                candidate_id=candidate_id,
                verdicts=verdicts,
                fit=None,
                disposition="excluded",
                excluded_by_gate="sells_rooms",
                account_entity_id=None,
            )
            (held,) = await list_candidates(conn, run_id=row.run_id)
            assert (held.disposition, held.excluded_by_gate, held.account_entity_id) == (
                "excluded",
                "sells_rooms",
                None,
            )
            assert held.fit is None
            assert [dict(v) for v in held.verdicts] == verdicts

    run_async(scenario())


def test_a_stopped_run_is_never_walked_back_into_the_queue() -> None:
    """A run a human stopped is finished: a late fleet stop signal must not suspend it, or the
    next delivery would claim it again."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project, request_sha256="d" * 64)
            await create_discovery_run(conn, row)
            await begin_discovery_run(conn, run_id=row.run_id)
            await end_discovery_run(
                conn,
                run_id=row.run_id,
                status="stopped",
                end_reason="stopped",
                summary={},
                release=True,
            )
            await suspend_discovery_run(conn, run_id=row.run_id)
            held = await read_discovery_run(conn, run_id=row.run_id)
            assert held is not None and held.status == "stopped"
            assert await begin_discovery_run(conn, run_id=row.run_id) is None

    run_async(scenario())


def test_brief_exclusions_are_not_found_before_for_later_runs() -> None:
    """Spec 2026-10-16 §4.6: a brief-excluded company was never judged, so the next run decides it
    from its own brief — a person's correction to the customer page takes effect there."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            first = _run(project, request_sha256="5" * 64)
            await create_discovery_run(conn, first)
            await upsert_candidate(
                conn,
                CandidateRow(
                    candidate_id=uuid4(),
                    run_id=first.run_id,
                    workspace_id=first.workspace_id,
                    project_id=first.project_id,
                    pass_="strict",
                    domain="marriott.com",
                    websets_url="https://www.marriott.com",
                    name="Marriott",
                    provider_snapshot={},
                    disposition="excluded_by_brief",
                    excluded_by_entry="Marriott",
                ),
            )
            (row,) = await list_candidates(conn, run_id=first.run_id)
            assert (row.disposition, row.excluded_by_entry) == ("excluded_by_brief", "Marriott")
            await _release(conn, first)
            second = _run(project, request_sha256="6" * 64)
            await create_discovery_run(conn, second)
            assert (
                await project_found_domains(
                    conn,
                    workspace_id=first.workspace_id,
                    project_id=first.project_id,
                    before_run_id=second.run_id,
                )
                == frozenset()
            )

    run_async(scenario())


def test_seller_domain_reads_the_latest_completed_full_run() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            assert (
                await seller_domain(conn, workspace_id=WORKSPACE, brand_id=project.brand_id) is None
            )
            user = "usr_seller_domain"
            await seed_principal(conn, workspace_id=WORKSPACE, user_id=user)
            for domain, status, at in (
                ("old.example", "completed", date(2026, 1, 1)),
                ("https://www.Conduit.ai/", "completed_with_gaps", date(2026, 2, 1)),
                ("newer-but-failed.example", "failed", date(2026, 3, 1)),
            ):
                await conn.execute(
                    text(
                        "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, "
                        " company_domain, requested_by_user_id, status, requested_at, finished_at) "
                        "VALUES (:run, :ws, :brand, :domain, :user, :status, :at, :at)"
                    ),
                    {
                        "run": uuid4(),
                        "ws": WORKSPACE,
                        "brand": project.brand_id,
                        "domain": domain,
                        "user": user,
                        "status": status,
                        "at": at,
                    },
                )
            assert (
                await seller_domain(conn, workspace_id=WORKSPACE, brand_id=project.brand_id)
                == "conduit.ai"
            )

    run_async(scenario())
