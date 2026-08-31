"""FI-2 slice 1, Task 2 — the global-lens accounts list (`GET /frontend/v1/accounts`).

Drives the ASGI app in-process via ``httpx.ASGITransport`` on the same event loop as the rollback
connection (the ``test_projections_app`` idiom), so the endpoint reads exactly the rows the test
seeded and nothing commits.

The fixture is shaped after the slice-0 canonical one — **two projects over one workspace** — plus
the two shapes the read layer must not choke on: an account that only one project targets, and a
membership-less account (a stage-0 seed / legacy import), which is a legitimate, null-heavy row and
not an error.

Covered, per the plan's ACs: both projects on the two-project account's row; the membership-less
account renders; ``?projectId=`` returns exactly the membership set (and an unknown project is an
empty *filter*, not a 404); per-project score attribution (project B's ICP score is never served as
project A's); zero research → ``not_started`` for every membership project; keyset pagination over
two pages with no duplicate and no skip, including *within* a ``?projectId=`` filter; and a
shape-level assertion that no display string reaches the wire.

Two structural properties get their own behavioural fixtures, because a comment cannot prove them:

* **species-conditional lineage** — a ``project_neutral`` fact written on a run attributed to
  project A still appears on the row served under ``?projectId=B`` (neutral fields come from the
  canonical merge in every lens), while the relative half of the same row stays lineage-bound;
* **run-level vs per-account status** — one research run with two account jobs, one paused and one
  terminal, proves the fleet-wide ``suspended`` state cannot mask the finished account's
  ``needs_review``.

The rest of the research-status mapping (in-progress, the four terminal outcomes, admission-paused
→ suspended) is exercised against real ``entity_research_job`` rows launched through the production
R2 entry point.

Every read and every count is workspace-scoped: this suite shares a database with suites that
commit, so an unscoped assertion would fail for reasons unrelated to FI-2.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.client_context_binding import bind_workspace_client
from clue_api.frontend_read import FRONTEND_READ_PREFIX, AccountResearchStatusValue
from clue_api.frontend_read.accounts_list import decode_cursor, encode_cursor
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import (
    AccountStatus,
    Confidence,
    EntityId,
    ExtractionMethod,
    ResearchMode,
    ResearchScope,
    RunId,
    account_claim,
    new_run_id,
    resolve_research_scope,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    ResearchRunKind,
    ResearchRunLifecycleContract,
)
from clue_fleet import (
    EntityResearchJobEnvelope,
    EntityResearchRunEnvelope,
    launch_entity_research_run,
)
from clue_research.claimstore import get_field, insert_claim, record_run_lineage
from clue_research.identity import insert_account_entity, stamp_reuse
from clue_research.membership import ensure_project_account
from clue_spine import Project
from tests._workspace import seed_project, seed_workspace
from tests.db.conftest import run_async
from tests.fleet.entity_research_r2_helpers import lifecycle_fixture
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WS = "fi2-slice1-accounts-list"
_OTHER_WS = "fi2-slice1-accounts-list-other"
_ACCOUNTS_PATH = f"{FRONTEND_READ_PREFIX}/accounts"


# --- harness --------------------------------------------------------------------------------


def _app(conn: AsyncConnection):
    """The real projections app with the flag on and the DB seam bound to the test's connection."""
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None, frontend_read_enabled=True),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _get(conn: AsyncConnection, *, workspace_id: str = _WS, **params: Any) -> httpx.Response:
    async with _client(_app(conn)) as client:
        return await client.get(
            _ACCOUNTS_PATH,
            params={key: value for key, value in params.items() if value is not None},
            headers={"X-Workspace-Id": workspace_id},
        )


def _rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The page keyed by account name — the assertions read better than by uuid."""
    return {row["name"]: row for row in payload["data"]}


async def _count_statements(conn: AsyncConnection) -> tuple[int, dict[str, Any]]:
    """``(statements issued, payload)`` for one default list request.

    The endpoint composes a fixed number of batched reads per page, so this count is a *constant*
    the tests can compare across fixtures of different shapes — which is how the N+1 guard proves a
    per-row lookup has not crept into the composition.
    """
    statements = 0

    def count(*_args: object) -> None:
        nonlocal statements
        statements += 1

    event.listen(conn.sync_connection, "before_cursor_execute", count)
    try:
        response = await _get(conn)
    finally:
        event.remove(conn.sync_connection, "before_cursor_execute", count)
    assert response.status_code == 200
    return statements, response.json()


# --- seeding --------------------------------------------------------------------------------


async def _account(
    conn: AsyncConnection,
    *,
    name: str,
    domain: str | None,
    workspace_id: str = _WS,
    created_at: datetime | None = None,
) -> EntityId:
    account_id = await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=domain,
        status=AccountStatus.ACTIVE,
        workspace_id=workspace_id,
    )
    if created_at is not None:
        # Keyset pagination orders on ``created_at``; the seeds are written microseconds apart, so
        # the pagination test pins explicit, well-separated times instead of racing the clock.
        await conn.execute(
            text("UPDATE account_entity SET created_at = :at WHERE id = :id"),
            {"at": created_at, "id": account_id},
        )
    return account_id


async def _neutral_claim(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    field_key: str,
    value: Any,
    project_id: str | None = None,
) -> None:
    """A public-footprint neutral fact.

    ``project_id`` sets the *lineage* of the run that wrote it. It must make no difference to what
    this endpoint serves — a neutral field comes from the canonical merge in every lens — which is
    exactly what ``test_a_neutral_fact_written_on_one_projects_run_still_shows_under_another``
    pins.
    """
    run_id = new_run_id()
    await record_run_lineage(
        conn,
        run_id=run_id,
        workspace_id=_WS,
        kind="enrichment" if project_id is None else "scoring",
        project_id=project_id,
    )
    await insert_claim(
        conn,
        stamp_reuse(
            account_claim(
                entity_id=account_id,
                field_key=field_key,
                value_json=value,
                source_tier=2,
                extraction_method=ExtractionMethod.API,
                confidence=Confidence(0.9),
                run_id=run_id,
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://example.test/facts",
                evidence_span="seeded",
            ),
            workspace_id=None,
        ),
    )


async def _score(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    project_id: str,
    fit: float,
    intent: float | None,
    icp_key: str,
    icp_version: int,
) -> RunId:
    """A project's Pass-A score, written the way M6.3 writes it: tenant-private claims on a run
    registered to that project (the lineage row is what makes the score attributable at all)."""
    run_id = new_run_id()
    await record_run_lineage(
        conn, run_id=run_id, workspace_id=_WS, kind="scoring", project_id=project_id
    )
    values: list[tuple[str, float]] = [("account.scoring.fit", fit)]
    if intent is not None:
        values.append(("account.scoring.intent", intent))
    for field_key, value in values:
        await insert_claim(
            conn,
            stamp_reuse(
                account_claim(
                    entity_id=account_id,
                    field_key=field_key,
                    value_json={
                        "value": value,
                        "components": [],
                        "icp_key": icp_key,
                        "icp_version": icp_version,
                    },
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=Confidence(1.0),
                    run_id=run_id,
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                ),
                workspace_id=_WS,
            ),
        )
    return run_id


async def _launch_account_research(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, account_ids: Sequence[EntityId]
) -> dict[EntityId, uuid.UUID]:
    """Launch ONE real account-research run over ``account_ids`` through the production R2 entry
    point, returning ``{account_id: job_id}``.

    Multiple subjects in one run is the normal shape — that is what a fleet *is* — and it is what
    makes the run-level/per-account distinction testable. Only the *scope* ids and the subject list
    are overridden on the frozen R0 fixture lifecycle.
    """
    lifecycle = lifecycle_fixture(ResearchRunKind.ACCOUNT_RESEARCH)
    payload = lifecycle.model_dump(mode="json")
    selection = payload["selection"]
    selection["workspace_id"] = workspace_id
    selection["project_id"] = project_id
    template = selection["subjects"][0]
    selection["subjects"] = [
        {**template, "subject_entity_id": str(account_id)} for account_id in account_ids
    ]
    lifecycle = ResearchRunLifecycleContract.model_validate(payload)

    jobs: list[EntityResearchJobEnvelope] = []
    by_account: dict[EntityId, uuid.UUID] = {}
    for priority, subject in enumerate(lifecycle.selection.subjects):
        authorization = EntityResearchJobAuthorization(
            job_id=uuid.uuid4(),
            research_run_id=lifecycle.run_id,
            subject_type=lifecycle.selection.subject_type,
            subject_entity_id=subject.subject_entity_id,
            parent_account_id=lifecycle.selection.account_entity_id,
            workspace_id=lifecycle.selection.workspace_id,
            project_id=lifecycle.selection.project_id,
            product_id=lifecycle.selection.product_id,
            project_run_id=lifecycle.selection.project_run_id,
            selection=lifecycle.selection,
            agent_profile_ref="agent-profile:account:v1",
            agent_profile_sha256=f"{priority:064d}",
            checkpoint_thread_id=f"checkpoint:{lifecycle.run_id}:{subject.subject_entity_id}",
            attempt_id=uuid.uuid4(),
            lease_id=uuid.uuid4(),
        )
        jobs.append(
            EntityResearchJobEnvelope(
                authorization=authorization,
                priority=priority,
                budget_envelope_ref=f"budget:job:{authorization.job_id}",
                budget_cap_cents=Decimal("4.00"),
            )
        )
        by_account[EntityId(subject.subject_entity_id)] = authorization.job_id
    await launch_entity_research_run(
        conn,
        EntityResearchRunEnvelope(
            lifecycle=lifecycle,
            jobs=tuple(jobs),
            budget_cap_cents=Decimal("10.00"),
            concurrency_limit=1,
        ),
    )
    return by_account


async def _launch_one(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, account_id: EntityId
) -> uuid.UUID:
    """The single-subject case of :func:`_launch_account_research`."""
    launched = await _launch_account_research(
        conn, workspace_id=workspace_id, project_id=project_id, account_ids=[account_id]
    )
    return launched[account_id]


async def _finalize_job(conn: AsyncConnection, job_id: uuid.UUID, *, outcome: str) -> None:
    """Drive a launched job to its terminal row.

    Deliberately a direct row transition rather than the full claim → lease → begin → finalize
    dance: what this endpoint reads is the terminal row, and driving the fleet lifecycle is R2's
    own acceptance suite's job. The row still satisfies every terminal CHECK.
    """
    await conn.execute(
        text(
            """
            UPDATE entity_research_job
            SET state = 'terminal',
                finalization_outcome = :outcome,
                finalization_receipt_ref = :receipt,
                terminal_at = now()
            WHERE job_id = :job_id
            """
        ),
        {"outcome": outcome, "receipt": f"receipt:{job_id}", "job_id": job_id},
    )


async def _seed_account_fleet(
    conn: AsyncConnection,
    *,
    job_id: uuid.UUID,
    workspace_id: str,
    project_id: str,
    state: str = "open",
) -> uuid.UUID:
    """Create the R6 account-fleet row over the run that owns ``job_id``, returning the run id.

    The fleet row is **run-level** — one per research run, not per account. That is the whole point
    of the mixed-fleet test: its ``state`` says nothing about any particular subject.
    """
    research_run_id, product_id, project_run_id = (
        await conn.execute(
            text(
                "SELECT j.research_run_id, j.product_id, j.project_run_id "
                "FROM entity_research_job j WHERE j.job_id = :j"
            ),
            {"j": job_id},
        )
    ).one()
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_account_fleet
                (research_run_id, workspace_id, project_id, product_id, project_run_id,
                 canary_job_ids, supervisor_policy_ref, supervisor_policy_json,
                 supervisor_policy_sha256, state, created_by, source_operation_id,
                 source_action_ref, suspended_at)
            VALUES
                (:run, :ws, :project, :product, :project_run, ARRAY[:job]::uuid[],
                 'account-fleet-supervisor:test', '{}'::jsonb, :sha, :state, 'tester',
                 :operation, :action,
                 CASE WHEN :state = 'suspended' THEN now() END)
            """
        ),
        {
            "run": research_run_id,
            "ws": workspace_id,
            "project": project_id,
            "product": product_id,
            "project_run": project_run_id,
            "job": job_id,
            "sha": "b" * 64,
            "state": state,
            "operation": uuid.uuid4(),
            "action": f"action:{job_id}",
        },
    )
    return uuid.UUID(str(research_run_id))


async def _set_admission(
    conn: AsyncConnection,
    *,
    job_id: uuid.UUID,
    research_run_id: uuid.UUID,
    admission_state: str,
) -> None:
    """Give one job its per-job R6 admission-control row (the genuinely per-account signal)."""
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_account_fleet_job_control
                (job_id, research_run_id, cohort, admission_state, effective_priority,
                 pause_reason)
            VALUES (:job, :run, 'canary', :admission, 0, :reason)
            """
        ),
        {
            "job": job_id,
            "run": research_run_id,
            "admission": admission_state,
            "reason": "awaiting_human" if admission_state == "paused" else None,
        },
    )


async def _pause_admission(
    conn: AsyncConnection, job_id: uuid.UUID, *, workspace_id: str, project_id: str
) -> None:
    """The common case: an open fleet whose one job is held at ``paused`` admission."""
    research_run_id = await _seed_account_fleet(
        conn, job_id=job_id, workspace_id=workspace_id, project_id=project_id
    )
    await _set_admission(
        conn, job_id=job_id, research_run_id=research_run_id, admission_state="paused"
    )


class _Fixture:
    """The seeded workspace's ids, as attributes so the assertions read like prose."""

    def __init__(
        self,
        *,
        project_a: Project,
        project_b: Project,
        acme: EntityId,
        zephyr: EntityId,
        seedling: EntityId,
    ) -> None:
        self.project_a = project_a
        self.project_b = project_b
        self.acme = acme
        self.zephyr = zephyr
        self.seedling = seedling


async def _build(conn: AsyncConnection) -> _Fixture:
    """Two projects over one workspace, one account shared, one project-local, one unaffiliated."""
    await seed_workspace(conn, _WS)
    project_a = await seed_project(conn, _WS, name="Project A")
    project_b = await seed_project(conn, _WS, name="Project B")

    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    acme = await _account(conn, name="Acme", domain="acme.test", created_at=base)
    zephyr = await _account(
        conn, name="Zephyr", domain="zephyr.test", created_at=base + timedelta(hours=1)
    )
    seedling = await _account(
        conn, name="Seedling", domain=None, created_at=base + timedelta(hours=2)
    )

    await ensure_project_account(
        conn,
        workspace_id=_WS,
        project_id=project_a.project_id,
        account_entity_id=acme,
        added_via="discovered",
        added_at=base,
    )
    await ensure_project_account(
        conn,
        workspace_id=_WS,
        project_id=project_b.project_id,
        account_entity_id=acme,
        added_via="imported",
        added_at=base + timedelta(minutes=5),
    )
    await ensure_project_account(
        conn,
        workspace_id=_WS,
        project_id=project_b.project_id,
        account_entity_id=zephyr,
        added_via="manual",
        added_at=base + timedelta(hours=1),
    )

    await _neutral_claim(conn, account_id=acme, field_key="core.employee_count", value=1200)
    await _neutral_claim(conn, account_id=acme, field_key="core.revenue_band", value="100m_500m")
    await _score(
        conn,
        account_id=acme,
        project_id=project_a.project_id,
        fit=0.81,
        intent=0.40,
        icp_key="alpha",
        icp_version=1,
    )
    await _score(
        conn,
        account_id=acme,
        project_id=project_b.project_id,
        fit=0.55,
        intent=None,
        icp_key="beta",
        icp_version=3,
    )
    return _Fixture(
        project_a=project_a, project_b=project_b, acme=acme, zephyr=zephyr, seedling=seedling
    )


# --- the two-project row --------------------------------------------------------------------


def test_the_shared_account_carries_both_projects_and_the_earliest_is_primary() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            response = await _get(conn)
            assert response.status_code == 200
            payload = response.json()

            assert payload["meta"]["total"] == 3
            assert payload["meta"]["nextCursor"] is None
            rows = _rows(payload)
            assert set(rows) == {"Acme", "Zephyr", "Seedling"}

            acme = rows["Acme"]
            assert acme["id"] == str(fixture.acme)
            assert acme["domain"] == "acme.test"
            assert acme["employeeCount"] == 1200
            assert acme["revenueBand"] == "100m_500m"
            assert acme["logoUrl"] is None
            assert [project["projectId"] for project in acme["projects"]] == [
                fixture.project_a.project_id,
                fixture.project_b.project_id,
            ]
            assert [project["addedVia"] for project in acme["projects"]] == [
                "discovered",
                "imported",
            ]
            # The FI-1 §9 plan-owner addendum: the membership row carries the project's own name,
            # resolved by a join, so the table can search and sort on it without a second endpoint.
            assert [project["name"] for project in acme["projects"]] == [
                "Project A",
                "Project B",
            ]
            # Element 0 of the membership read IS the recorded primary-project policy.
            assert acme["primaryProjectId"] == fixture.project_a.project_id

    run_async(scenario())


def test_project_names_are_one_batched_read_not_one_query_per_membership() -> None:
    """The name join must not reintroduce an N+1 over a 200-row page.

    Measured, not asserted in a comment: the endpoint's statement count is captured over the base
    fixture and again after three more projects each acquire the same account. A per-membership
    lookup would grow by three; a batched read costs the same either way.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            baseline, _ = await _count_statements(conn)

            base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
            for ordinal in range(3):
                extra = await seed_project(conn, _WS, name=f"Extra project {ordinal}")
                await ensure_project_account(
                    conn,
                    workspace_id=_WS,
                    project_id=extra.project_id,
                    account_entity_id=fixture.acme,
                    added_via="manual",
                    added_at=base + timedelta(hours=3, minutes=ordinal),
                )
            widened, payload = await _count_statements(conn)

            assert len(_rows(payload)["Acme"]["projects"]) == 5, "the memberships really did grow"
            # Without the lower bound the guard is vacuous: a harness change that stops the
            # listener firing would compare 0 == 0 and pass an endpoint full of per-row lookups.
            assert baseline > 0, "the listener really fired"
            assert widened == baseline

    run_async(scenario())


def test_a_membership_less_account_renders_as_a_null_heavy_row() -> None:
    """Seeds, the client entity and legacy imports have no membership — they are still accounts."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            payload = (await _get(conn)).json()

            seedling = _rows(payload)["Seedling"]
            assert seedling["domain"] is None
            assert seedling["employeeCount"] is None
            assert seedling["revenueBand"] is None
            assert seedling["projects"] == []
            assert seedling["primaryProjectId"] is None
            assert seedling["scores"] == []
            assert seedling["researchStatus"] == []

    run_async(scenario())


def test_the_workspace_client_is_not_listed_as_its_own_target_account() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _WS)
            client = await _account(conn, name="Insight Health", domain="insighthealth.ai")
            target = await _account(conn, name="Neuro Practice", domain="neuro.test")
            await bind_workspace_client(
                conn,
                workspace_id=_WS,
                client_entity_id=client,
            )

            response = await _get(conn)
            assert response.status_code == 200
            assert [(row["id"], row["name"]) for row in response.json()["data"]] == [
                (str(target), "Neuro Practice")
            ]
            assert response.json()["meta"]["total"] == 1

    run_async(scenario())


# --- per-project score attribution ----------------------------------------------------------


def test_each_projects_score_is_served_attributed_to_that_project_only() -> None:
    """The relative-field contract: project B's ICP score is never rendered as project A's."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            acme = _rows((await _get(conn)).json())["Acme"]

            by_project = {score["projectId"]: score for score in acme["scores"]}
            assert set(by_project) == {fixture.project_a.project_id, fixture.project_b.project_id}

            a_score = by_project[fixture.project_a.project_id]
            assert a_score["fit"] == pytest.approx(0.81)
            assert a_score["intent"] == pytest.approx(0.40)
            assert (a_score["icpKey"], a_score["icpVersion"]) == ("alpha", 1)

            b_score = by_project[fixture.project_b.project_id]
            assert b_score["fit"] == pytest.approx(0.55)
            # B scored fit and not intent; reporting the missing half as 0 would be a fabrication.
            assert b_score["intent"] is None
            assert (b_score["icpKey"], b_score["icpVersion"]) == ("beta", 3)

            assert datetime.fromisoformat(a_score["scoredAt"]).tzinfo is not None

    run_async(scenario())


def test_a_score_whose_run_has_no_project_is_not_attributed_to_any() -> None:
    """An unattributable score is omitted, never smeared across the account's projects."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            orphan_run = new_run_id()
            await record_run_lineage(
                conn, run_id=orphan_run, workspace_id=_WS, kind="scoring", project_id=None
            )
            await insert_claim(
                conn,
                stamp_reuse(
                    account_claim(
                        entity_id=fixture.zephyr,
                        field_key="account.scoring.fit",
                        value_json={"value": 0.99, "icp_key": "ghost", "icp_version": 9},
                        source_tier=1,
                        extraction_method=ExtractionMethod.HUMAN,
                        confidence=Confidence(1.0),
                        run_id=orphan_run,
                        research_mode=ResearchMode.ACCOUNT_PROFILING,
                    ),
                    workspace_id=_WS,
                ),
            )

            assert _rows((await _get(conn)).json())["Zephyr"]["scores"] == []

    run_async(scenario())


# --- the projectId filter ---------------------------------------------------------------------


def test_the_project_filter_returns_exactly_that_projects_membership() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)

            only_a = (await _get(conn, projectId=fixture.project_a.project_id)).json()
            assert set(_rows(only_a)) == {"Acme"}
            assert only_a["meta"]["total"] == 1
            # A filter narrows the *set of rows*, not the row: Acme still carries both projects.
            assert len(_rows(only_a)["Acme"]["projects"]) == 2

            only_b = (await _get(conn, projectId=fixture.project_b.project_id)).json()
            assert set(_rows(only_b)) == {"Acme", "Zephyr"}
            assert only_b["meta"]["total"] == 2

    run_async(scenario())


def test_a_neutral_fact_written_on_one_projects_run_still_shows_under_another() -> None:
    """Species-conditional lineage, behaviourally: a ``project_neutral`` field is served from the
    canonical merge in **every** lens, so a fact whose run is attributed to project A must still
    appear on the row returned under ``?projectId=B``. Lineage-filtering it would make a shared
    firmographic fact vanish for every project that did not happen to fetch it."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            # Zephyr belongs only to B; its headcount is discovered on a run attributed to A.
            await _neutral_claim(
                conn,
                account_id=fixture.zephyr,
                field_key="core.employee_count",
                value=340,
                project_id=fixture.project_a.project_id,
            )

            unfiltered = _rows((await _get(conn)).json())["Zephyr"]
            assert unfiltered["employeeCount"] == 340

            under_b = _rows((await _get(conn, projectId=fixture.project_b.project_id)).json())[
                "Zephyr"
            ]
            assert under_b["employeeCount"] == 340
            # And the *relative* half of the same row is still lineage-bound: A's run wrote no
            # score for Zephyr, so no score is attributed to anyone.
            assert under_b["scores"] == []

    run_async(scenario())


def test_an_unknown_project_is_an_empty_filter_not_a_404() -> None:
    """This endpoint has no authority to say a project does not exist — it lists accounts."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            response = await _get(conn, projectId="no-such-project")
            assert response.status_code == 200
            assert response.json() == {"data": [], "meta": {"total": 0, "nextCursor": None}}

    run_async(scenario())


def test_another_workspaces_accounts_are_never_served() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            await seed_workspace(conn, _OTHER_WS)
            await _account(conn, name="Foreign", domain="foreign.test", workspace_id=_OTHER_WS)

            assert "Foreign" not in _rows((await _get(conn)).json())
            other = (await _get(conn, workspace_id=_OTHER_WS)).json()
            assert set(_rows(other)) == {"Foreign"}

    run_async(scenario())


# --- research status --------------------------------------------------------------------------


def test_an_account_with_no_research_is_not_started_for_every_project_it_belongs_to() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            acme = _rows((await _get(conn)).json())["Acme"]

            assert acme["researchStatus"] == [
                {"projectId": fixture.project_a.project_id, "status": "not_started"},
                {"projectId": fixture.project_b.project_id, "status": "not_started"},
            ]

    run_async(scenario())


def test_research_status_tracks_the_job_lifecycle_per_project() -> None:
    """A queued job is in progress; a terminal one reports its outcome; and each project's status
    is independent of the other's."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await _launch_one(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_a.project_id,
                account_id=fixture.acme,
            )
            b_job = await _launch_one(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_b.project_id,
                account_id=fixture.acme,
            )
            await _finalize_job(conn, b_job, outcome="completed")

            statuses = {
                entry["projectId"]: entry["status"]
                for entry in _rows((await _get(conn)).json())["Acme"]["researchStatus"]
            }
            assert statuses == {
                fixture.project_a.project_id: AccountResearchStatusValue.IN_PROGRESS.value,
                fixture.project_b.project_id: AccountResearchStatusValue.COMPLETED.value,
            }

    run_async(scenario())


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("needs_review", AccountResearchStatusValue.NEEDS_REVIEW),
        ("completed", AccountResearchStatusValue.COMPLETED),
        # No `failed` slot exists: every non-success terminal is "stopped, awaiting a human".
        ("cancelled", AccountResearchStatusValue.SUSPENDED),
        ("budget_stopped", AccountResearchStatusValue.SUSPENDED),
    ],
)
def test_a_terminal_outcome_maps_to_the_honest_status(
    outcome: str, expected: AccountResearchStatusValue
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            job_id = await _launch_one(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_a.project_id,
                account_id=fixture.acme,
            )
            await _finalize_job(conn, job_id, outcome=outcome)

            statuses = {
                entry["projectId"]: entry["status"]
                for entry in _rows((await _get(conn)).json())["Acme"]["researchStatus"]
            }
            assert statuses[fixture.project_a.project_id] == expected.value

    run_async(scenario())


def test_a_paused_admission_reads_as_suspended_not_in_progress() -> None:
    """FI-1 §5.2's explicit carve-out: a non-terminal job whose admission is paused is not running.
    This is also the backend's real failure mode — a crash re-queues and pauses, it never fails."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            job_id = await _launch_one(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_a.project_id,
                account_id=fixture.acme,
            )
            await _pause_admission(
                conn, job_id, workspace_id=_WS, project_id=fixture.project_a.project_id
            )

            statuses = {
                entry["projectId"]: entry["status"]
                for entry in _rows((await _get(conn)).json())["Acme"]["researchStatus"]
            }
            assert statuses[fixture.project_a.project_id] == "suspended"

    run_async(scenario())


def test_a_run_level_suspension_never_masks_an_accounts_own_terminal_outcome() -> None:
    """The R6 fleet state is **run-level**: the supervisor suspends the whole fleet when *any* job
    pauses. One run, two accounts — the paused sibling must not erase the other's finished
    ``needs_review``, which is the most actionable state the screen shows.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await ensure_project_account(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_a.project_id,
                account_entity_id=fixture.zephyr,
                added_via="manual",
            )
            launched = await _launch_account_research(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_a.project_id,
                account_ids=[fixture.acme, fixture.zephyr],
            )
            finished, stuck = launched[fixture.acme], launched[fixture.zephyr]

            # Zephyr's job pauses, which drives the shared fleet to `suspended`; Acme's own job has
            # already finished with an accepted receipt.
            research_run_id = await _seed_account_fleet(
                conn,
                job_id=stuck,
                workspace_id=_WS,
                project_id=fixture.project_a.project_id,
                state="suspended",
            )
            await _set_admission(
                conn, job_id=stuck, research_run_id=research_run_id, admission_state="paused"
            )
            await _set_admission(
                conn, job_id=finished, research_run_id=research_run_id, admission_state="terminal"
            )
            await _finalize_job(conn, finished, outcome="needs_review")

            rows = _rows((await _get(conn)).json())

            def status(row: dict[str, Any]) -> str:
                return next(
                    entry["status"]
                    for entry in row["researchStatus"]
                    if entry["projectId"] == fixture.project_a.project_id
                )

            assert status(rows["Acme"]) == "needs_review"
            assert status(rows["Zephyr"]) == "suspended"

    run_async(scenario())


# --- pagination --------------------------------------------------------------------------------


def test_two_pages_cover_the_workspace_with_no_duplicate_and_no_skip() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)

            first = (await _get(conn, limit=2)).json()
            assert [row["name"] for row in first["data"]] == ["Seedling", "Zephyr"]
            assert first["meta"]["total"] == 3
            cursor = first["meta"]["nextCursor"]
            assert isinstance(cursor, str) and cursor

            second = (await _get(conn, limit=2, cursor=cursor)).json()
            assert [row["name"] for row in second["data"]] == ["Acme"]
            # The last page closes the walk: no cursor, so a client stops.
            assert second["meta"]["nextCursor"] is None

            seen = [row["id"] for row in first["data"]] + [row["id"] for row in second["data"]]
            assert len(seen) == len(set(seen)) == 3

    run_async(scenario())


def test_numbered_pages_expose_stable_page_metadata_and_no_cursor() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)

            first = (await _get(conn, limit=2, page=1)).json()
            second = (await _get(conn, limit=2, page=2)).json()

            assert [row["name"] for row in first["data"]] == ["Seedling", "Zephyr"]
            assert [row["name"] for row in second["data"]] == ["Acme"]
            assert first["meta"] == {
                "total": 3,
                "nextCursor": None,
                "page": 1,
                "pageSize": 2,
                "totalPages": 2,
            }
            assert second["meta"]["page"] == 2
            assert second["meta"]["totalPages"] == 2

    run_async(scenario())


def test_numbered_page_and_cursor_cannot_be_combined() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            first = (await _get(conn, limit=1)).json()
            response = await _get(conn, limit=1, page=2, cursor=first["meta"]["nextCursor"])

            assert response.status_code == 400
            assert response.json()["error"]["code"] == "INVALID_PAGINATION"

    run_async(scenario())


def test_the_project_filter_and_the_cursor_compose() -> None:
    """Paging *within* a filter must page the filtered set — the cursor predicate and the
    membership predicate are ANDed, so a filtered walk can neither leak a non-member nor skip a
    member."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            # A third member of B, so the filtered set is big enough to need two pages.
            base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
            nimbus = await _account(
                conn, name="Nimbus", domain="nimbus.test", created_at=base + timedelta(hours=3)
            )
            await ensure_project_account(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_b.project_id,
                account_entity_id=nimbus,
                added_via="manual",
            )

            first = (await _get(conn, projectId=fixture.project_b.project_id, limit=2)).json()
            assert first["meta"]["total"] == 3
            assert [row["name"] for row in first["data"]] == ["Nimbus", "Zephyr"]
            cursor = first["meta"]["nextCursor"]
            assert isinstance(cursor, str) and cursor

            second = (
                await _get(conn, projectId=fixture.project_b.project_id, limit=2, cursor=cursor)
            ).json()
            assert [row["name"] for row in second["data"]] == ["Acme"]
            assert second["meta"]["nextCursor"] is None

            walked = [row["name"] for row in first["data"] + second["data"]]
            # `Seedling` belongs to no project and must never appear inside a filtered walk.
            assert sorted(walked) == ["Acme", "Nimbus", "Zephyr"]
            assert len(walked) == len(set(walked))

    run_async(scenario())


def test_the_cursor_survives_a_round_trip() -> None:
    """Opaque *by contract*, not by cryptography: base64url is decodable, and that is fine — the
    cursor names only a keyset position, and what actually bounds a forged one is the
    ``X-Workspace-Id`` scoping every query applies regardless of where paging resumes."""
    created_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    account_id = uuid.uuid4()
    cursor = encode_cursor(created_at, account_id)
    assert str(account_id) not in cursor  # not a plaintext key an integration should parse
    assert decode_cursor(cursor) == (created_at, account_id)


def test_a_cursor_this_endpoint_never_issued_is_refused_in_the_envelope() -> None:
    """Silently ignoring a bad cursor would re-serve page 1 forever and look like data loss."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            response = await _get(conn, cursor="not-a-cursor")
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "INVALID_CURSOR"

    run_async(scenario())


def test_the_limit_is_bounded_so_the_workspace_scan_can_never_be_unbounded() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            assert (await _get(conn, limit=201)).status_code == 422
            assert (await _get(conn, limit=0)).status_code == 422

    run_async(scenario())


# --- Band-2 wire discipline --------------------------------------------------------------------


_ALLOWED_ROW_KEYS = {
    "id",
    "name",
    "domain",
    "employeeCount",
    "revenueBand",
    "logoUrl",
    "projects",
    "primaryProjectId",
    "scores",
    "researchStatus",
    "updatedAt",
}


def test_no_display_string_reaches_the_wire() -> None:
    """Band-2: enums, numbers, ISO timestamps, opaque ids and nulls — never a label the frontend
    should own. The key set is pinned, so a later `sizeLabel`/`timeLabel` cannot slip in."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            payload = (await _get(conn)).json()

            assert set(payload) == {"data", "meta"}
            assert set(payload["meta"]) == {"total", "nextCursor"}
            for row in payload["data"]:
                assert set(row) == _ALLOWED_ROW_KEYS
                assert not any(key.lower().endswith("label") for key in row)
                for membership in row["projects"]:
                    assert set(membership) == {"projectId", "name", "addedVia", "addedAt"}
                    datetime.fromisoformat(membership["addedAt"])
                for score in row["scores"]:
                    assert set(score) == {
                        "projectId",
                        "fit",
                        "intent",
                        "icpKey",
                        "icpVersion",
                        "scoredAt",
                    }
                for status in row["researchStatus"]:
                    assert set(status) == {"projectId", "status"}
                    # A backend-honest vocabulary, not a frontend badge string.
                    assert status["status"] in set(AccountResearchStatusValue)
                datetime.fromisoformat(row["updatedAt"])

    run_async(scenario())


def test_the_endpoint_still_refuses_a_request_without_a_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            async with _client(_app(conn)) as client:
                response = await client.get(_ACCOUNTS_PATH)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHORIZED"

    run_async(scenario())


# --- the claim-scoping trap ---------------------------------------------------------------------


def test_the_module_never_scopes_a_claim_read_by_claim_workspace_id() -> None:
    """The slice-0 trap: ``claim.workspace_id`` is the reuse-class tenant binding, forced NULL on
    every public claim, so filtering on it silently empties a read instead of narrowing it. This is
    a grep because the failure mode is a *plausible short answer*, which no fixture can catch."""

    from pathlib import Path

    import clue_api.frontend_read.accounts_list as module

    source = Path(module.__file__).read_text()
    assert "claim.workspace_id" not in source.split('"""', 2)[2]


def test_neutral_and_relative_fields_are_read_through_different_paths() -> None:
    """Species-conditional lineage: the neutral list fields must never be lineage-filtered (they
    serve from the canonical merge in every lens), and the scoring fields must always be."""
    from clue_api.frontend_read import accounts_list

    assert accounts_list.LIST_NEUTRAL_FIELD_KEYS == ("core.employee_count", "core.revenue_band")
    for field_key in accounts_list.LIST_NEUTRAL_FIELD_KEYS:
        assert field_key not in accounts_list._SCORE_CLAIMS_TEMPLATE
    assert "run_lineage" in accounts_list._SCORE_CLAIMS_TEMPLATE
    assert accounts_list.SCORE_FIELD_KEYS == (
        "account.scoring.fit",
        "account.scoring.intent",
    )


def test_the_scoring_fields_really_are_project_relative_in_the_registry() -> None:
    """If a future pack edit made these neutral, lineage-filtering them would be wrong — so the
    read layer's species assumption is pinned against the registry, not merely commented."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            from clue_api.frontend_read import accounts_list

            # Through ``resolve_research_scope``, never the raw column: a global registry row may
            # legitimately carry NULL and the key rule decides (slice-0 handoff).
            for field_key in accounts_list.SCORE_FIELD_KEYS:
                field = await get_field(conn, field_key)
                assert field is not None
                assert resolve_research_scope(field) is ResearchScope.PROJECT_RELATIVE
            for field_key in accounts_list.LIST_NEUTRAL_FIELD_KEYS:
                field = await get_field(conn, field_key)
                assert field is not None
                assert resolve_research_scope(field) is ResearchScope.PROJECT_NEUTRAL

    run_async(scenario())


def test_the_lineage_join_dispatches_on_project_id_never_on_kind() -> None:
    """``run_lineage.run_id`` is a mixed id space and ``kind`` is advisory first-writer-wins, so
    project attribution must key on ``project_id`` alone (slice-0 handoff)."""
    from clue_api.frontend_read import accounts_list

    assert "l.project_id IS NOT NULL" in accounts_list._SCORE_CLAIMS_TEMPLATE
    assert "kind" not in accounts_list._SCORE_CLAIMS_TEMPLATE
