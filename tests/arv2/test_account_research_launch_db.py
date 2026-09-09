"""Seam 1's launch against the real tables: rows, lineage, membership, and one task per account.

The launch is the whole authority boundary of the lane — after it, a job runs against exactly what
a human signed off on. So the three things pinned here are the three that make that true: the run
is *deterministic* (the same signed-off request is one run, not two), every refusal is *typed*
(never a stack trace the caller has to parse), and the inputs it needs are only the ones standing
rule item 5 allows — account rows, an ICP artifact ref, and a product-selection version.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_catalog import (
    ARV2_ACCOUNT_PROFILE_REF,
    ARV2_PERSON_PROFILE_REF,
    arv2_account_profile_sha256,
    arv2_person_profile_sha256,
)
from clue_api.arv2.account_research_driver import (
    ARV2_ACCOUNT_DEDUP_PREFIX,
    ARV2_ACCOUNT_TASK_PRIORITY,
)
from clue_api.arv2.account_research_launch import (
    Arv2LaunchRefused,
    Arv2LaunchRequest,
    Arv2PersonLaunchRequest,
    DbArv2LaunchService,
    enqueue_launched_jobs,
    launch_arv2_account_research,
    launch_arv2_person_research,
)
from clue_api.arv2.account_research_store import list_jobs, read_run
from clue_auth.store import create_platform_user
from clue_config import Settings
from clue_core import EntityId
from clue_fleet import FleetTaskKind
from clue_fleet.lease import WorkId
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_spine import confirm_project_product_set, create_product
from clue_storage import artifact_key, content_address
from clue_storage.artifacts import record_artifact
from clue_storage.fs import FsStorage
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

WORKSPACE = "ws_r2_launch"
USER_ID = "usr_r2_launch"
ICP_KEY = "clue-abm-buyers"
ICP_BODY = "\n".join(
    (
        "---",
        "kind: icp-definition",
        f"icp_key: {ICP_KEY}",
        "version: 1",
        "status: confirmed",
        "---",
        "",
        "# Who we sell to",
        "",
        "US-headquartered, Series A or later, hiring go-to-market roles now.",
    )
)


@dataclass
class _FakeQueue:
    """Records every offer, and dedups by key the way the real queue does.

    The launch itself never touches this: it is handed to ``enqueue_launched_jobs``, which the
    caller runs *after* the launch transaction commits.
    """

    calls: list[dict[str, Any]] = field(default_factory=list)
    trace: list[str] | None = None

    async def enqueue(
        self,
        *,
        kind: FleetTaskKind,
        work_id: WorkId,
        dedup_key: str,
        priority: int = 0,
        payload: dict[str, Any] | None = None,
        reopen_terminal: bool = False,
    ) -> bool:
        if self.trace is not None:
            self.trace.append("enqueue")
        seen = any(call["dedup_key"] == dedup_key for call in self.calls)
        self.calls.append(
            {
                "kind": kind,
                "work_id": work_id,
                "dedup_key": dedup_key,
                "priority": priority,
                "payload": payload,
                "reopen_terminal": reopen_terminal,
            }
        )
        # A duplicate dedup key is a pure no-op at the real queue (``reopen_terminal=False``),
        # which is what makes re-offering a replayed run's jobs safe.
        return not seen


@dataclass(frozen=True)
class _Fixture:
    workspace_id: str
    project_id: str
    brand_id: str
    accounts: tuple[EntityId, ...]
    icp_artifact_key: str
    icp_artifact_sha256: str
    selection_version: int


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(_env_file=None, arv2_account_research_enabled=enabled)


async def _seed_icp_document(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    brand_id: str,
    body: str = ICP_BODY,
    kind: str = "icp-definition",
    status: str = "confirmed",
    path: str = "audience/icp-clue-abm-buyers.md",
) -> tuple[str, str]:
    """Register one ``brand_knowledge_document`` + its artifact, the way the loader does."""
    rendered = body.encode("utf-8")
    sha = content_address(rendered)
    key = artifact_key(workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=sha,
        media_type="text/markdown",
        size_bytes=len(rendered),
        source_key="arv2:test:knowledge_document",
    )
    await storage.put(key, rendered, media_type="text/markdown")
    await conn.execute(
        text(
            """
            INSERT INTO brand_knowledge_document
                (document_id, workspace_id, brand_id, folder, path, kind, version, status,
                 artifact_key, artifact_sha256)
            VALUES
                (:document_id, :workspace_id, :brand_id, :folder, :path, :kind, 1, :status,
                 :artifact_key, :artifact_sha256)
            """
        ),
        {
            "document_id": uuid5(UUID(int=0), f"{workspace_id}:{path}:{status}"),
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "folder": path.split("/", 1)[0],
            "path": path,
            "kind": kind,
            "status": status,
            "artifact_key": key,
            "artifact_sha256": sha,
        },
    )
    return key, sha


async def _seed(conn: AsyncConnection, storage: FsStorage) -> _Fixture:
    """The whole launch prerequisite set: spine, a confirmed product set, accounts, a confirmed ICP.

    Deliberately NOT seeded: an ``icp_spec`` row, an ``account_research_directive``, or any Stage-0
    pin on the project run — the launch must need none of them (standing rule item 5).
    """
    project = await seed_project(conn, WORKSPACE)
    await create_platform_user(conn, user_id=USER_ID, display_name="R2 launch test")
    product = await create_product(
        conn, brand_id=project.brand_id, workspace_id=project.workspace_id, name="Clue"
    )
    confirmed = await confirm_project_product_set(
        conn,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        product_ids=[str(product.product_id)],
        gate_id=uuid4(),
        confirmed_by_user_id=USER_ID,
    )
    assert confirmed is not None
    accounts: list[EntityId] = []
    for name, domain in (("Probook", "probook.ai"), ("Zafran", "zafran.io")):
        accounts.append(
            await insert_account_entity(
                conn, canonical_name=name, primary_domain=domain, workspace_id=project.workspace_id
            )
        )
    key, sha = await _seed_icp_document(
        conn,
        storage,
        workspace_id=project.workspace_id,
        brand_id=str(project.brand_id),
        path="audience/icp-clue-abm-buyers.md",
    )
    return _Fixture(
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=str(project.brand_id),
        accounts=tuple(accounts),
        icp_artifact_key=key,
        icp_artifact_sha256=sha,
        selection_version=confirmed.selection_version,
    )


def _request(fixture: _Fixture, **overrides: Any) -> Arv2LaunchRequest:
    payload: dict[str, Any] = {
        "workspace_id": fixture.workspace_id,
        "project_id": fixture.project_id,
        "account_entity_ids": tuple(UUID(str(value)) for value in fixture.accounts),
        "icp_artifact_key": fixture.icp_artifact_key,
        "icp_artifact_sha256": fixture.icp_artifact_sha256,
        "product_selection_version": fixture.selection_version,
        "requested_by_user_id": USER_ID,
        "directive_text": "focus on the hiring signals",
        "committee_cap": 4,
    }
    payload.update(overrides)
    return Arv2LaunchRequest(**payload)


async def _launch(
    conn: AsyncConnection,
    storage: FsStorage,
    request: Arv2LaunchRequest,
    queue: _FakeQueue,
    *,
    settings: Settings | None = None,
    profile_sha256: str | None = None,
) -> Any:
    """Launch, then offer — the production order, with the offer OUTSIDE the launch call.

    ``launch_arv2_account_research`` takes no queue at all; it reports what to offer and the
    caller offers it once the rows are committed. The tests keep both halves so the receipt's
    ``to_enqueue`` is exercised, and the queue argument is deliberately not reachable from the
    launch.
    """
    receipt = await launch_arv2_account_research(
        conn,
        request,
        settings=settings or _settings(),
        storage=storage,
        profile_sha256=profile_sha256 or arv2_account_profile_sha256(),
    )
    await enqueue_launched_jobs(queue, receipt)
    return receipt


def test_launch_creates_run_jobs_lineage_and_enqueues_one_task_per_job(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await _seed(conn, storage)
            queue = _FakeQueue()
            request = _request(fixture)

            receipt = await _launch(conn, storage, request, queue)

            assert receipt.replayed is False
            assert len(receipt.job_ids) == 2

            run = await read_run(conn, run_id=receipt.run_id)
            assert run is not None
            # Everything the job will run under is pinned on the row, not re-derived later.
            assert run.workspace_id == fixture.workspace_id
            assert run.project_id == fixture.project_id
            assert run.brand_id == fixture.brand_id
            assert run.project_run_id == receipt.project_run_id
            assert run.icp_artifact_key == fixture.icp_artifact_key
            assert run.icp_artifact_sha256 == fixture.icp_artifact_sha256
            assert run.icp_key == ICP_KEY and run.icp_version == 1
            assert run.product_selection_version == fixture.selection_version
            assert run.effort == "full" and run.committee_cap == 4
            assert run.directive_text == "focus on the hiring signals"
            assert run.profile_ref == ARV2_ACCOUNT_PROFILE_REF
            assert run.profile_sha256 == arv2_account_profile_sha256()
            assert run.requested_by_user_id == USER_ID
            assert run.status == "not_started"

            jobs = await list_jobs(conn, run_id=receipt.run_id)
            assert {job.account_entity_id for job in jobs} == {
                UUID(str(value)) for value in fixture.accounts
            }
            assert {job.job_id for job in jobs} == set(receipt.job_ids)
            assert all(job.status == "not_started" for job in jobs)
            # R3: the launch queues account subjects, each carrying its own copy of the run's pin.
            assert all(job.subject_type == "account" for job in jobs)
            assert all(job.subject_entity_id is None for job in jobs)
            assert all(job.profile_sha256 == arv2_account_profile_sha256() for job in jobs)

            lineage = (
                (
                    await conn.execute(
                        text(
                            "SELECT kind, project_id, project_run_id FROM run_lineage "
                            "WHERE run_id = :run_id"
                        ),
                        {"run_id": receipt.run_id},
                    )
                )
                .mappings()
                .one()
            )
            assert lineage["kind"] == "entity_research"
            assert lineage["project_id"] == fixture.project_id
            assert UUID(str(lineage["project_run_id"])) == receipt.project_run_id

            memberships = (
                (
                    await conn.execute(
                        text(
                            "SELECT account_entity_id, added_via FROM project_account "
                            "WHERE workspace_id = :w AND project_id = :p"
                        ),
                        {"w": fixture.workspace_id, "p": fixture.project_id},
                    )
                )
                .mappings()
                .all()
            )
            assert {UUID(str(row["account_entity_id"])) for row in memberships} == {
                UUID(str(value)) for value in fixture.accounts
            }
            assert {row["added_via"] for row in memberships} == {"manual"}

            assert len(queue.calls) == 2
            assert [job.job_id for job in receipt.to_enqueue] == list(receipt.job_ids)
            assert {job.run_id for job in receipt.to_enqueue} == {receipt.run_id}
            assert {job.workspace_id for job in receipt.to_enqueue} == {fixture.workspace_id}
            for job_id, call in zip(receipt.job_ids, queue.calls, strict=True):
                assert call["kind"] is FleetTaskKind.ARV2_ACCOUNT_RESEARCH
                assert UUID(str(call["work_id"])) == job_id
                assert call["dedup_key"] == f"{ARV2_ACCOUNT_DEDUP_PREFIX}{job_id}"
                assert call["priority"] == ARV2_ACCOUNT_TASK_PRIORITY
                assert call["reopen_terminal"] is False
                payload: Mapping[str, Any] = call["payload"]
                assert payload == {
                    "job_id": str(job_id),
                    "run_id": str(receipt.run_id),
                    "workspace_id": fixture.workspace_id,
                }

            # The same signed-off request is ONE run: replaying it writes no second job. It DOES
            # re-offer both jobs, and the queue refuses both on their dedup key — which is how a
            # run whose offer was lost after the commit is repaired by relaunching it.
            replay = await _launch(conn, storage, _request(fixture), queue)
            assert replay.run_id == receipt.run_id
            assert replay.job_ids == receipt.job_ids
            assert replay.replayed is True
            assert len(replay.to_enqueue) == 2
            assert len(queue.calls) == 4
            assert await enqueue_launched_jobs(queue, replay) == 0, "already-queued: no-op"
            assert len(await list_jobs(conn, run_id=receipt.run_id)) == 2

            # A different request (one fewer account) is a DIFFERENT run, not a mutation.
            other = await _launch(
                conn,
                storage,
                _request(fixture, account_entity_ids=(UUID(str(fixture.accounts[0])),)),
                queue,
            )
            assert other.run_id != receipt.run_id
            assert len(queue.calls) == 7

    run_async(scenario())


def test_launch_refuses_lane_disabled_unknown_account_unconfirmed_icp_and_digest_mismatch(
    tmp_path: Any,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await _seed(conn, storage)
            queue = _FakeQueue()

            with pytest.raises(Arv2LaunchRefused) as disabled:
                await _launch(
                    conn, storage, _request(fixture), queue, settings=_settings(enabled=False)
                )
            assert disabled.value.code == "lane_disabled"

            stranger = uuid4()
            with pytest.raises(Arv2LaunchRefused) as unknown:
                await _launch(
                    conn, storage, _request(fixture, account_entity_ids=(stranger,)), queue
                )
            assert unknown.value.code == f"account_not_found:{stranger}"

            # A real account, but somebody else's: refused by id, never researched by accident.
            foreign_project = await seed_project(conn, "ws_r2_launch_other")
            foreign = await insert_account_entity(
                conn,
                canonical_name="Elsewhere",
                primary_domain="elsewhere.example",
                workspace_id=foreign_project.workspace_id,
            )
            with pytest.raises(Arv2LaunchRefused) as foreign_refusal:
                await _launch(
                    conn,
                    storage,
                    _request(fixture, account_entity_ids=(UUID(str(foreign)),)),
                    queue,
                )
            assert foreign_refusal.value.code == f"account_not_in_workspace:{foreign}"

            with pytest.raises(Arv2LaunchRefused) as absent:
                await _launch(
                    conn, storage, _request(fixture, icp_artifact_key="ws_r2_launch/nope"), queue
                )
            assert absent.value.code == "icp_artifact_not_found"

            proposed_key, proposed_sha = await _seed_icp_document(
                conn,
                storage,
                workspace_id=fixture.workspace_id,
                brand_id=fixture.brand_id,
                body=ICP_BODY.replace("status: confirmed", "status: proposed"),
                status="proposed",
                path="audience/icp-proposed.md",
            )
            with pytest.raises(Arv2LaunchRefused) as unconfirmed:
                await _launch(
                    conn,
                    storage,
                    _request(
                        fixture,
                        icp_artifact_key=proposed_key,
                        icp_artifact_sha256=proposed_sha,
                    ),
                    queue,
                )
            assert unconfirmed.value.code == "icp_artifact_not_confirmed"

            with pytest.raises(Arv2LaunchRefused) as mismatch:
                await _launch(conn, storage, _request(fixture, icp_artifact_sha256="d" * 64), queue)
            assert mismatch.value.code == "icp_digest_mismatch"

            with pytest.raises(Arv2LaunchRefused) as version:
                await _launch(conn, storage, _request(fixture, product_selection_version=99), queue)
            assert version.value.code == "product_selection_version_unknown"

            with pytest.raises(Arv2LaunchRefused) as project:
                await _launch(conn, storage, _request(fixture, project_id="prj_nope"), queue)
            assert project.value.code in {
                "project_not_found",
                "product_selection_version_unknown",
            }

            # Not one refusal wrote a row or bought a task.
            assert queue.calls == []
            runs = (
                await conn.execute(
                    text("SELECT count(*) FROM arv2_research_run WHERE workspace_id = :w"),
                    {"w": fixture.workspace_id},
                )
            ).scalar_one()
            assert runs == 0

    run_async(scenario())


def test_launch_refuses_an_icp_whose_front_matter_has_no_key_or_no_integer_version(
    tmp_path: Any,
) -> None:
    """A malformed pin is a typed refusal, not a ``KeyError``/``ValueError`` out of the launcher."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await _seed(conn, storage)
            queue = _FakeQueue()

            malformed = {
                "audience/icp-no-version.md": ICP_BODY.replace("version: 1\n", ""),
                "audience/icp-word-version.md": ICP_BODY.replace("version: 1", "version: one"),
                "audience/icp-no-key.md": ICP_BODY.replace(f"icp_key: {ICP_KEY}\n", ""),
            }
            for path, body in malformed.items():
                key, sha = await _seed_icp_document(
                    conn,
                    storage,
                    workspace_id=fixture.workspace_id,
                    brand_id=fixture.brand_id,
                    body=body,
                    path=path,
                )
                with pytest.raises(Arv2LaunchRefused) as refused:
                    await _launch(
                        conn,
                        storage,
                        _request(fixture, icp_artifact_key=key, icp_artifact_sha256=sha),
                        queue,
                    )
                assert refused.value.code == "icp_front_matter_invalid", path

            assert queue.calls == []

    run_async(scenario())


def test_launch_needs_only_accounts_icp_ref_and_selection_version(tmp_path: Any) -> None:
    """Standing rule item 5: no ``icp_spec``, no directive row, no Stage-0 pin on the run."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await _seed(conn, storage)
            queue = _FakeQueue()

            receipt = await _launch(conn, storage, _request(fixture), queue)

            for table in ("icp_spec", "account_research_directive"):
                rows = (
                    await conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE workspace_id = :w"),
                        {"w": fixture.workspace_id},
                    )
                ).scalar_one()
                assert rows == 0, f"{table} must not be a launch prerequisite"

            pins = (
                (
                    await conn.execute(
                        text(
                            "SELECT product_id, client_entity_id, client_kb_version, "
                            " product_context_version_id, readiness_decision_id "
                            "FROM project_run WHERE id = :id"
                        ),
                        {"id": receipt.project_run_id},
                    )
                )
                .mappings()
                .one()
            )
            assert all(value is None for value in pins.values())
            assert len(queue.calls) == 2

    run_async(scenario())


def test_the_run_id_is_the_digest_of_what_the_human_signed_off_on(tmp_path: Any) -> None:
    """Two workspaces, two requests, two runs — the request sha is what identifies a run."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await _seed(conn, storage)
            queue = _FakeQueue()

            first = await _launch(conn, storage, _request(fixture), queue)
            run = await read_run(conn, run_id=first.run_id)
            assert run is not None
            assert len(run.request_sha256) == 64

            # A different directive is a different authorization, so a different run. So is a
            # different agent profile: new bytes are a new thing to have approved.
            other = await _launch(
                conn, storage, _request(fixture, directive_text="ignore hiring"), queue
            )
            assert other.run_id != first.run_id
            reprofiled = await _launch(
                conn, storage, _request(fixture), queue, profile_sha256="e" * 64
            )
            assert reprofiled.run_id not in {first.run_id, other.run_id}

    run_async(scenario())


def test_the_launch_itself_can_reach_no_queue_at_all() -> None:
    """C1, structurally: the offer cannot be made inside the launch's transaction.

    ``DbTaskQueue.enqueue`` commits in its **own** transaction, so a task offered while the run
    and job rows are still uncommitted is visible to a worker before they are — and that worker
    reads "no such job" as "already finished" and marks the task done, dropping that account's
    research permanently and unrecoverably. The launch therefore takes no queue: the only way to
    offer is ``enqueue_launched_jobs``, which the caller runs after the commit.
    """
    parameters = inspect.signature(launch_arv2_account_research).parameters
    assert "queue" not in parameters
    assert ".enqueue(" not in inspect.getsource(launch_arv2_account_research)


def test_the_service_offers_the_tasks_only_after_the_launch_transaction_closes(
    tmp_path: Any,
) -> None:
    """The production seam's ordering, pinned: rows committed, THEN the fleet is told."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await _seed(conn, storage)
            trace: list[str] = []
            queue = _FakeQueue(trace=trace)

            @asynccontextmanager
            async def factory() -> AsyncIterator[AsyncConnection]:
                trace.append("transaction_opened")
                try:
                    yield conn
                finally:
                    # The real ``transaction`` commits here; the test's connection rolls back at
                    # the end of the case, so what is asserted is the ORDER, not the durability.
                    trace.append("transaction_closed")

            service = DbArv2LaunchService(_settings(), storage, queue=queue, conn_factory=factory)

            receipt = await service.launch(_request(fixture))

            assert trace == [
                "transaction_opened",
                "transaction_closed",
                "enqueue",
                "enqueue",
            ]
            assert len(receipt.job_ids) == 2
            assert len(queue.calls) == 2

    run_async(scenario())


# -- the person launch (R3 task 6) -----------------------------------------------------------------


def test_person_launch_creates_a_run_of_its_own_with_one_job_per_person(tmp_path: Any) -> None:
    """A human named these people, so the run is theirs: person profile, full effort, cap = them.

    It resolves its own pins — the brand's currently confirmed ICP and the project's current
    product set — because there is no approved artifact ref to be handed one on-demand, and it
    records both on the run exactly like the account launch does.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await _seed(conn, storage)
            dana = await insert_contact_entity(
                conn,
                account_entity_id=fixture.accounts[0],
                full_name="Dana Reyes",
                linkedin_url="https://www.linkedin.com/in/dana-reyes",
            )
            sam = await insert_contact_entity(
                conn, account_entity_id=fixture.accounts[1], full_name="Sam Okafor"
            )
            queue = _FakeQueue()
            request = Arv2PersonLaunchRequest(
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                contact_entity_ids=(UUID(str(dana)), UUID(str(sam))),
                requested_by_user_id=USER_ID,
                directive_text="open with the podcast",
            )

            receipt = await launch_arv2_person_research(
                conn,
                request,
                settings=_settings(),
                storage=storage,
                profile_sha256=arv2_person_profile_sha256(),
            )
            await enqueue_launched_jobs(queue, receipt)

            run = await read_run(conn, run_id=receipt.run_id)
            assert run is not None
            assert run.profile_ref == ARV2_PERSON_PROFILE_REF
            assert run.profile_sha256 == arv2_person_profile_sha256()
            assert run.effort == "full" and run.committee_cap == 2
            assert run.icp_artifact_key == fixture.icp_artifact_key
            assert run.icp_artifact_sha256 == fixture.icp_artifact_sha256
            assert run.icp_key == ICP_KEY and run.icp_version == 1
            assert run.product_selection_version == fixture.selection_version
            assert run.directive_text == "open with the podcast"

            jobs = {
                job.subject_entity_id: job for job in await list_jobs(conn, run_id=receipt.run_id)
            }
            assert set(jobs) == {UUID(str(dana)), UUID(str(sam))}
            assert all(job.subject_type == "person" for job in jobs.values())
            # A person job carries their employer: it is scoped and joined like its account sibling.
            assert jobs[UUID(str(dana))].account_entity_id == UUID(str(fixture.accounts[0]))
            assert jobs[UUID(str(sam))].account_entity_id == UUID(str(fixture.accounts[1]))
            assert all(job.profile_sha256 == arv2_person_profile_sha256() for job in jobs.values())
            assert len(queue.calls) == 2

            # The same request is the same run: one person, one job, offered again for repair.
            replay = await launch_arv2_person_research(
                conn,
                request,
                settings=_settings(),
                storage=storage,
                profile_sha256=arv2_person_profile_sha256(),
            )
            assert replay.run_id == receipt.run_id and replay.replayed is True
            assert len(await list_jobs(conn, run_id=receipt.run_id)) == 2

    run_async(scenario())


def test_person_launch_refuses_a_contact_this_workspace_does_not_hold(tmp_path: Any) -> None:
    """Unknown and foreign are the same refusal: the caller learns nothing about another tenant."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await _seed(conn, storage)
            stranger = uuid4()
            with pytest.raises(Arv2LaunchRefused) as unknown:
                await launch_arv2_person_research(
                    conn,
                    Arv2PersonLaunchRequest(
                        workspace_id=fixture.workspace_id,
                        project_id=fixture.project_id,
                        contact_entity_ids=(stranger,),
                        requested_by_user_id=USER_ID,
                    ),
                    settings=_settings(),
                    storage=storage,
                    profile_sha256=arv2_person_profile_sha256(),
                )
            assert unknown.value.code == f"contact_not_found:{stranger}"

            other = await seed_project(conn, "ws_r2_launch_other")
            other_account = await insert_account_entity(
                conn,
                canonical_name="Elsewhere",
                primary_domain="elsewhere.example",
                workspace_id=other.workspace_id,
            )
            foreign = await insert_contact_entity(
                conn, account_entity_id=other_account, full_name="Someone Else"
            )
            with pytest.raises(Arv2LaunchRefused) as tenant:
                await launch_arv2_person_research(
                    conn,
                    Arv2PersonLaunchRequest(
                        workspace_id=fixture.workspace_id,
                        project_id=fixture.project_id,
                        contact_entity_ids=(UUID(str(foreign)),),
                        requested_by_user_id=USER_ID,
                    ),
                    settings=_settings(),
                    storage=storage,
                    profile_sha256=arv2_person_profile_sha256(),
                )
            assert tenant.value.code == f"contact_not_found:{foreign}"

            # Nothing was written by either refusal.
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM arv2_research_run WHERE profile_ref = :ref "
                        "AND workspace_id = :workspace_id"
                    ),
                    {"ref": ARV2_PERSON_PROFILE_REF, "workspace_id": fixture.workspace_id},
                )
            ).scalar_one() == 0

    run_async(scenario())


def test_person_launch_refuses_a_lane_that_is_off_and_a_request_naming_nobody(
    tmp_path: Any,
) -> None:
    """The two cheapest refusals, before a single read."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await _seed(conn, storage)
            contact = await insert_contact_entity(
                conn, account_entity_id=fixture.accounts[0], full_name="Dana Reyes"
            )
            request = Arv2PersonLaunchRequest(
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                contact_entity_ids=(UUID(str(contact)),),
                requested_by_user_id=USER_ID,
            )
            with pytest.raises(Arv2LaunchRefused) as disabled:
                await launch_arv2_person_research(
                    conn,
                    request,
                    settings=_settings(enabled=False),
                    storage=storage,
                    profile_sha256=arv2_person_profile_sha256(),
                )
            assert disabled.value.code == "lane_disabled"

            with pytest.raises(Arv2LaunchRefused) as empty:
                await launch_arv2_person_research(
                    conn,
                    Arv2PersonLaunchRequest(
                        workspace_id=fixture.workspace_id,
                        project_id=fixture.project_id,
                        contact_entity_ids=(),
                        requested_by_user_id=USER_ID,
                    ),
                    settings=_settings(),
                    storage=storage,
                    profile_sha256=arv2_person_profile_sha256(),
                )
            assert empty.value.code == "no_contacts"

    run_async(scenario())
