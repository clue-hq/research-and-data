"""The workspace accounts table (`GET /frontend/v1/accounts`).

Drives the ASGI app in-process via ``httpx.ASGITransport`` on the same event loop as the rollback
connection (the ``test_projections_app`` idiom), so the endpoint reads exactly the rows the test
seeded and nothing commits.

Two fixtures. ``_build`` is the slice-0 canonical shape — **two projects over one workspace** —
plus the two shapes the read layer must not choke on: an account that only one project targets,
and a membership-less account (a stage-0 seed / legacy import), which is a legitimate, null-heavy
row and not an error. It carries the page's own rules: the ``?projectId=`` filter, keyset and
numbered pagination, workspace scoping. ``_build_v1`` is the fully-populated ARV2 account — owner,
custom fields, industries, socials, bands, an ARV2 research job — and carries the row itself.

Two structural properties get their own behavioural fixtures, because a comment cannot prove them:

* **species-conditional lineage** — a ``project_neutral`` fact written on a run attributed to
  project A still appears on the row served under ``?projectId=B`` (neutral fields come from the
  canonical merge in every lens), while the relative half of the same row stays lineage-bound;
* **a fixed statement count per page** — measured across fixtures of different shapes, which is how
  the N+1 guard proves a per-row lookup has not crept into the composition.

Every read and every count is workspace-scoped: this suite shares a database with suites that
commit, so an unscoped assertion would fail for reasons unrelated to this endpoint.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_store import JobStatus
from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_api.client_context_binding import bind_workspace_client
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.accounts_list import decode_cursor, encode_cursor
from clue_api.frontend_read.contract_v1 import AccountsResponseV1, AccountV1
from clue_api.frontend_read.v1_shared import iso_utc
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import (
    AccountStatus,
    Confidence,
    EntityId,
    EntityType,
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
from clue_research.claimstore.packs import load_core_pack
from clue_research.identity import insert_account_entity, stamp_reuse
from clue_research.membership import ensure_project_account
from clue_spine import Project
from tests._workspace import seed_project, seed_workspace
from tests.api.contract_v1.oracle import zod_validate
from tests.arv2.account_research_job_helpers import seed_arv2_job
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


async def _count_statements(conn: AsyncConnection, **params: Any) -> tuple[int, dict[str, Any]]:
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
        response = await _get(conn, **params)
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
            assert unfiltered["employeeBand"] == "201-500"

            under_b = _rows((await _get(conn, projectId=fixture.project_b.project_id)).json())[
                "Zephyr"
            ]
            assert under_b["employeeBand"] == "201-500"
            # And the *relative* half of the same row is still lineage-bound: A's run wrote no
            # score for Zephyr, so the row carries no fit under either lens.
            assert under_b["fitScore"] is None
            assert under_b["overallFit"] is None

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


def test_numbered_pages_walk_the_same_order_and_issue_no_cursor() -> None:
    """A numbered page is the same total order, addressed by offset instead of by keyset.

    The contract's ``meta`` carries ``total`` and ``nextCursor`` only, so a numbered walk is
    explicitly cursorless: the browser already knows which page it asked for, and minting a cursor
    beside it would offer two ways to name one position.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)

            first = (await _get(conn, limit=2, page=1)).json()
            second = (await _get(conn, limit=2, page=2)).json()

            assert [row["name"] for row in first["data"]] == ["Seedling", "Zephyr"]
            assert [row["name"] for row in second["data"]] == ["Acme"]
            assert first["meta"] == {"total": 3, "nextCursor": None}
            assert second["meta"] == {"total": 3, "nextCursor": None}

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


def test_the_scoring_fields_really_are_project_relative_in_the_registry() -> None:
    """If a future pack edit made these neutral, lineage-filtering them would be wrong — so the
    read layer's species assumption is pinned against the registry, not merely commented."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            from clue_api.frontend_read import accounts_list

            await load_arv2_pack(conn)
            # Through ``resolve_research_scope``, never the raw column: a global registry row may
            # legitimately carry NULL and the key rule decides (slice-0 handoff).
            for field_key in accounts_list.SCORE_FIELD_KEYS:
                field = await get_field(conn, field_key)
                assert field is not None
                assert resolve_research_scope(field) is ResearchScope.PROJECT_RELATIVE
            for field_key in accounts_list.V1_NEUTRAL_FIELD_KEYS:
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


# --- the row itself (ARV2 E1) --------------------------------------------------------------------
#
# Everything above is the *page*: which accounts, in what order, under which filter. Everything
# below is the *row*: what the table shows about one account, over the fully-populated ``_build_v1``
# fixture.


async def _seed_user(
    conn: AsyncConnection,
    user_id: str,
    *,
    display_name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> str:
    await conn.execute(
        text(
            "INSERT INTO platform_user (user_id, display_name, first_name, last_name) "
            "VALUES (:u, :d, :f, :l) ON CONFLICT (user_id) DO NOTHING"
        ),
        {"u": user_id, "d": display_name, "f": first_name, "l": last_name},
    )
    return user_id


async def _seed_client_field(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    field_key: str,
    description: str,
    presentation: str = "text",
) -> None:
    """One tenant-local ``client.*`` registry row, planted the way the promotion service leaves it
    (the same recipe as ``tests/api/test_frontend_read_v1_shared.py``)."""
    brand = f"b_{workspace_id}"
    await conn.execute(
        text(
            "INSERT INTO brand (brand_id, workspace_id, name) VALUES (:b, :w, 'Clue') "
            "ON CONFLICT DO NOTHING"
        ),
        {"b": brand, "w": workspace_id},
    )
    proposal_id = uuid.uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO field_definition_revision (
                id, workspace_id, brand_id, field_key, payload_hash, payload_json,
                proposed_by_actor, required_authority
            ) VALUES (:id, :w, :b, :k, :hash, CAST('{}' AS jsonb), 'human', 'human')
            """
        ),
        {
            "id": proposal_id,
            "w": workspace_id,
            "b": brand,
            "k": field_key,
            "hash": f"{abs(hash(field_key)):064x}"[:64],
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO workspace_field_definition (
                workspace_id, field_key, value_type, tier_plan, pass_kind, reuse_scope,
                field_class, description, pack, client_kb_role, active, definition_version,
                promoted_from_proposal_id, promotion_policy_version, promoted_by, presentation
            ) VALUES (
                :w, :k, 'str', CAST('[]' AS jsonb), CAST('deep' AS field_pass),
                CAST('tenant_private' AS reuse_scope), CAST('pack' AS field_class), :d,
                'client', 'extended', TRUE, 1, :p, 'test', 'tester', :pres
            )
            """
        ),
        {
            "w": workspace_id,
            "k": field_key,
            "d": description,
            "p": proposal_id,
            "pres": presentation,
        },
    )


async def _client_claim(
    conn: AsyncConnection, *, account_id: EntityId, field_key: str, value: Any
) -> None:
    """A tenant-private ``client.*`` claim, written through the D1 lenient writer."""
    await LenientClaimWriter(lenient=True).write(
        conn,
        ClaimDraft(
            entity_id=account_id,
            entity_type=EntityType.ACCOUNT,
            field_key=field_key,
            value_json=value,
            extraction_method=ExtractionMethod.SCRAPE,
            run_id=new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            workspace_id=_WS,
            source_url="https://zafran.io/newsroom",
        ),
    )


async def _build_v1(conn: AsyncConnection) -> tuple[_Fixture, EntityId]:
    """The FI-2 fixture plus one fully-populated account — the shape the v1 row is designed for.

    Zafran carries every source the v1 row composes: the eight neutral facts, an owner and a
    creator, memberships in both projects, a fit score under the *primary* project (and a lower one
    under the other, so attribution is provable), a finished research job, and a client-pack custom
    field. The FI-2 accounts stay exactly as they were, so both halves of the file share one seed.
    """
    fixture = await _build(conn)
    await load_core_pack(conn)
    await load_arv2_pack(conn)
    await _seed_user(conn, "u_owner", display_name="Ada Lovelace")
    await _seed_user(conn, "u_creator", first_name="Grace", last_name="Hopper")

    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    zafran = await _account(
        conn, name="Zafran", domain="zafran.io", created_at=base + timedelta(hours=3)
    )
    await conn.execute(
        text(
            "UPDATE account_entity SET owner_user_id = 'u_owner', "
            "created_by_user_id = 'u_creator' WHERE id = :id"
        ),
        {"id": zafran},
    )
    await ensure_project_account(
        conn,
        workspace_id=_WS,
        project_id=fixture.project_a.project_id,
        account_entity_id=zafran,
        added_via="discovered",
        added_at=base,
    )
    await ensure_project_account(
        conn,
        workspace_id=_WS,
        project_id=fixture.project_b.project_id,
        account_entity_id=zafran,
        added_via="imported",
        added_at=base + timedelta(minutes=5),
    )

    for field_key, value in (
        ("core.employee_count", 167),
        # The registry shapes, not convenient strings: ``employee_range`` is an object whose only
        # required key is ``label``, ``hq_location`` an object whose required key is ``raw``.
        ("core.employee_range", {"label": "101-250", "min": 101, "max": 250}),
        ("core.revenue_band", "50m_100m"),
        ("core.hq_location", {"raw": "Tel Aviv, Israel", "city": "Tel Aviv", "country": "Israel"}),
        ("core.industry", "Cybersecurity"),
        ("core.industries_all", ["Cybersecurity", "Security software"]),
        ("core.company_linkedin_url", "https://www.linkedin.com/company/zafran"),
    ):
        await _neutral_claim(conn, account_id=zafran, field_key=field_key, value=value)

    await _seed_client_field(
        conn,
        workspace_id=_WS,
        field_key="client.compliance_regime",
        description="Compliance regime",
        presentation="badge",
    )
    await _client_claim(
        conn, account_id=zafran, field_key="client.compliance_regime", value="SOC 2"
    )

    await _score(
        conn,
        account_id=zafran,
        project_id=fixture.project_b.project_id,
        fit=0.20,
        intent=None,
        icp_key="beta",
        icp_version=3,
    )
    # The lower score under project B is written FIRST and the primary project's higher score
    # LAST, so the higher one is the newest. Founder ruling 2026-09-11: a fit is global to the
    # account — the row shows the most recently scored fit whichever project scored it, no
    # longer only the primary project's.
    await _score(
        conn,
        account_id=zafran,
        project_id=fixture.project_a.project_id,
        fit=0.82,
        intent=0.5,
        icp_key="alpha",
        icp_version=1,
    )
    # The v1 row's research status comes from ARV2's own rows and nothing else (D4-b decision 1),
    # so the seed is an ``arv2_research_job`` driven through the R2 store — not an M8D job.
    await seed_arv2_job(conn, project=fixture.project_a, account_id=zafran, status="completed")
    return fixture, zafran


def test_the_row_is_the_display_row_for_a_fully_populated_account() -> None:
    """Every v1 field on the row, composed from the sources decisions 3–7/15/16 name — and the
    whole body validated twice: by the strict pydantic model and by the frontend's own Zod."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture, zafran = await _build_v1(conn)
            response = await _get(conn)
            assert response.status_code == 200
            body = response.json()

            # The strict wire model: extra keys forbidden, required-nullable fields present.
            AccountsResponseV1.model_validate(body)
            assert body["meta"] == {"total": 4, "nextCursor": None}

            row = _rows(body)["Zafran"]
            assert row["id"] == str(zafran)
            assert row["logoPath"] is None
            assert row["websiteUrl"] == "https://zafran.io"
            assert row["researchStatus"] == "completed"
            assert row["researchStatusLabel"] == "Researched"
            assert row["researchIsRefreshing"] is False
            assert row["overallFit"] == "High"
            assert row["fitScore"] == 82
            # The label, not the `core.revenue_band` token (D4-b controller ruling 2).
            assert row["revenueBand"] == "$50M–100M"
            # The provider's own range wins over the band we would compute from the headcount.
            assert row["employeeBand"] == "101-250"
            assert row["locationCount"] == 1
            assert row["locationsLabel"] == "Tel Aviv, Israel"
            assert row["industryLabels"] == ["Cybersecurity", "Security software"]
            assert row["socials"] == [
                {
                    "id": "linkedin",
                    "label": "LinkedIn",
                    "url": "https://www.linkedin.com/company/zafran",
                }
            ]
            assert row["owner"] == {"id": "u_owner", "name": "Ada Lovelace"}
            assert row["createdBy"] == {"id": "u_creator", "name": "Grace Hopper"}
            assert row["primaryProjectId"] == fixture.project_a.project_id
            assert row["projects"] == [
                {"id": fixture.project_a.project_id, "name": "Project A"},
                {"id": fixture.project_b.project_id, "name": "Project B"},
            ]
            assert row["customFields"] == [
                {
                    "id": "client.compliance_regime",
                    "claimId": row["customFields"][0]["claimId"],
                    "label": "Compliance regime",
                    "value": "SOC 2",
                    "presentation": "badge",
                    "primary": True,
                }
            ]
            # Timestamps are UTC and ``Z``-suffixed: Zod's ``z.string().datetime()`` accepts an
            # offset only with ``{offset: true}``, which the vendored schemas do not set.
            assert row["createdAt"] == "2026-08-01T15:00:00Z"
            assert row["lastModifiedAt"] >= row["createdAt"]
            assert row["lastModifiedAt"].endswith("Z")

            # The employee band falls back to the headcount when no range claim exists.
            assert _rows(body)["Acme"]["employeeBand"] == "1001-5000"

            for served in body["data"]:
                zod_validate(served, "AccountSchema")

    run_async(scenario())


def test_the_revenue_column_serves_the_providers_own_range_over_the_band() -> None:
    """Founder 2026-10-27: the table shows the range AI Ark gives. A ``core.annual_revenue`` range
    wins over the band, as on the account page; a range that straddles two of our bands — which
    has no band at all — still shows."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            _, zafran = await _build_v1(conn)
            await _neutral_claim(
                conn,
                account_id=zafran,
                field_key="core.annual_revenue",
                value={
                    "amount_min": 25_000_000,
                    "amount_max": 75_000_000,
                    "currency": "USD",
                    "as_of": "2026-10-21",
                    "estimate_kind": "provider_estimate",
                },
            )
            body = (await _get(conn)).json()
            AccountsResponseV1.model_validate(body)

            assert _rows(body)["Zafran"]["revenueBand"] == "$25M–75M"

    run_async(scenario())


def test_an_unscored_membership_less_account_serves_nulls_and_unknown_bands() -> None:
    """Decision 16: a required band says "Unknown"; a nullable score says ``null``. Neither is
    guessed, and the row still renders."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build_v1(conn)
            body = (await _get(conn)).json()

            seedling = _rows(body)["Seedling"]
            assert seedling["overallFit"] is None
            assert seedling["fitScore"] is None
            assert seedling["revenueBand"] == "Unknown"
            assert seedling["employeeBand"] == "Unknown"
            assert seedling["locationCount"] == 0
            assert "locationsLabel" not in seedling
            assert seedling["websiteUrl"] is None
            assert seedling["logoPath"] is None
            assert seedling["researchStatus"] == "not_started"
            assert seedling["researchStatusLabel"] == "Not started"
            assert seedling["researchIsRefreshing"] is False
            assert seedling["owner"] is None
            assert seedling["createdBy"] is None
            assert seedling["primaryProjectId"] is None
            assert seedling["projects"] == []
            assert seedling["customFields"] == []
            zod_validate(seedling, "AccountSchema")

    run_async(scenario())


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ("not_started", "Not started"),
        ("in_progress", "In progress"),
        ("needs_review", "Needs review"),
        ("completed", "Researched"),
        ("suspended", "Paused"),
    ],
)
def test_the_row_serves_the_latest_arv2_job_status_verbatim(status: str, label: str) -> None:
    """All five R2 states, unmapped. ``arv2_research_job.status`` IS the wire vocabulary, so the
    read layer has no lifecycle to reinterpret and nothing to invent."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await seed_arv2_job(
                conn,
                project=fixture.project_a,
                account_id=fixture.acme,
                status=cast(JobStatus, status),
            )

            row = _rows((await _get(conn)).json())["Acme"]
            assert row["researchStatus"] == status
            assert row["researchStatusLabel"] == label
            assert row["researchIsRefreshing"] is False

    run_async(scenario())


def test_an_account_with_no_arv2_job_is_not_started_and_not_refreshing() -> None:
    """The absent row, spelled once at the row rather than invented by the read."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            row = _rows((await _get(conn)).json())["Acme"]

            assert row["researchStatus"] == "not_started"
            assert row["researchStatusLabel"] == "Not started"
            assert row["researchIsRefreshing"] is False

    run_async(scenario())


def test_a_job_launched_after_a_completed_one_marks_the_row_refreshing() -> None:
    """``researchIsRefreshing`` is the honest "researched, and being re-researched right now" —
    a non-terminal ARV2 job newer than a ``completed`` one for the same account."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture, zafran = await _build_v1(conn)
            # ``_build_v1``'s completed job and this one would share a transaction ``now()``; ageing
            # it makes "newer" a fact about the rows, not about uuid ordering.
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET created_at = created_at - interval '1 hour' "
                    "WHERE account_entity_id = :id"
                ),
                {"id": zafran},
            )
            await seed_arv2_job(
                conn, project=fixture.project_a, account_id=zafran, status="in_progress"
            )

            row = _rows((await _get(conn)).json())["Zafran"]
            assert row["researchIsRefreshing"] is True
            # The latest job is the in-flight one, so the status is what that job says.
            assert row["researchStatus"] == "in_progress"
            assert row["researchStatusLabel"] == "In progress"

    run_async(scenario())


def test_a_completed_job_newer_than_an_in_flight_one_is_not_refreshing() -> None:
    """The reverse order: a stale in-flight row older than the result must not light the spinner
    on an account whose latest job actually finished."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            base = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
            await seed_arv2_job(
                conn,
                project=fixture.project_a,
                account_id=fixture.acme,
                status="in_progress",
                created_at=base,
            )
            await seed_arv2_job(
                conn,
                project=fixture.project_a,
                account_id=fixture.acme,
                status="completed",
                created_at=base + timedelta(hours=1),
            )

            row = _rows((await _get(conn)).json())["Acme"]
            assert row["researchStatus"] == "completed"
            assert row["researchIsRefreshing"] is False

    run_async(scenario())


def test_a_job_launched_by_a_non_primary_project_still_shows_on_the_row() -> None:
    """Research is a fact about the *account*: an ARV2 run pins its project, but the row reports
    the account's latest job whichever project launched it. Hiding project B's finished research
    because project A leads the row would report a researched account as never researched."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await seed_arv2_job(
                conn, project=fixture.project_b, account_id=fixture.acme, status="completed"
            )

            row = _rows((await _get(conn)).json())["Acme"]
            assert row["primaryProjectId"] == fixture.project_a.project_id
            assert row["researchStatus"] == "completed"

    run_async(scenario())


def test_the_row_costs_a_constant_number_of_statements_per_page() -> None:
    """The row composes many sources; it must still cost a fixed number of batched reads, not one
    per membership, owner or custom field."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture, zafran = await _build_v1(conn)
            baseline, _ = await _count_statements(conn)

            base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
            for ordinal in range(3):
                extra = await seed_project(conn, _WS, name=f"Extra project {ordinal}")
                await ensure_project_account(
                    conn,
                    workspace_id=_WS,
                    project_id=extra.project_id,
                    account_entity_id=zafran,
                    added_via="manual",
                    added_at=base + timedelta(hours=4, minutes=ordinal),
                )
            for ordinal in range(3):
                await _seed_client_field(
                    conn,
                    workspace_id=_WS,
                    field_key=f"client.extra_{ordinal}",
                    description=f"Extra {ordinal}",
                )
                await _client_claim(
                    conn,
                    account_id=fixture.acme,
                    field_key=f"client.extra_{ordinal}",
                    value=f"value {ordinal}",
                )
            widened, payload = await _count_statements(conn)

            rows = _rows(payload)
            assert len(rows["Zafran"]["projects"]) == 5, "the memberships really did grow"
            assert len(rows["Acme"]["customFields"]) == 3, "the custom fields really did grow"
            assert baseline > 0, "the listener really fired"
            assert widened == baseline

    run_async(scenario())


def test_the_z_suffixed_timestamp_is_the_only_form_the_frontends_zod_accepts() -> None:
    """Why ``iso_utc`` exists, proven against the real parser rather than asserted in a comment.

    Every v1 timestamp is a Zod ``z.string().datetime()``, which takes an offset only when the
    schema opts in with ``{offset: true}`` — and none of the vendored schemas do. A ``timestamptz``
    column's natural ``isoformat()`` (``+00:00``) would therefore be rejected by the frontend's own
    parser, which is a failure no pydantic-side assertion can see.
    """
    row = AccountV1(
        id="acct-1",
        name="Zafran",
        logo_path=None,
        website_url="https://zafran.io",
        research_status="not_started",
        overall_fit=None,
        fit_score=None,
        revenue_band="Unknown",
        employee_band="Unknown",
        location_count=0,
        created_at=iso_utc(datetime(2026, 9, 8, 12, 0, tzinfo=UTC)),
    ).model_dump(mode="json")

    assert row["createdAt"] == "2026-09-08T12:00:00Z"
    zod_validate(row, "AccountSchema")
    with pytest.raises(AssertionError):
        zod_validate({**row, "createdAt": "2026-09-08T12:00:00+00:00"}, "AccountSchema")


def test_a_stored_mark_serves_the_platforms_route_and_a_domain_without_one_gets_brandfetch() -> (
    None
):
    """Founder rulings 2026-09-11 (supersede D0 ruling S2): an account carrying a LinkedIn mark
    serves a rooted path to the platform's logo route — never the third-party URL; an account with
    a domain but no stored mark gets Brandfetch's embed-only Logo API URL for that domain; and
    with no client id configured that account serves ``null`` so the frontend shows its glyph."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture, zafran = await _build_v1(conn)
            await _neutral_claim(
                conn,
                account_id=zafran,
                field_key="core.logo_url",
                value="https://media.licdn.com/dms/image/v2/X/company-logo_200_200/0?e=2147483647",
            )
            without = (await _get(conn)).json()
            rows = _rows(without)
            assert rows["Zafran"]["logoPath"] == f"/api/clue/frontend/v1/accounts/{zafran}/logo"
            assert "media.licdn.com" not in rows["Zafran"]["logoPath"]
            assert rows["Seedling"]["logoPath"] is None  # no mark, no domain, no client id
            zod_validate(rows["Zafran"], "AccountSchema")

    run_async(scenario())
