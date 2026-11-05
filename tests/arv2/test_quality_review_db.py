"""Recipe 40: the account agent reviews its people's findings and writes the one brief."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2 import page_writer_runtime
from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
from clue_api.arv2.account_research_store import create_job, read_job, read_run
from clue_api.arv2.quality_committee_tool import (
    NominateBriefedWebCommitteeTool,
    NominateBriefedWebInput,
)
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_generation import (
    continuation_work_id,
    ensure_generation,
    pending_continuations,
    read_generation,
    reconcile_generation,
    record_child_result,
    register_child,
    signal,
)
from clue_api.arv2.quality_person_release import ready_person_jobs
from clue_api.arv2.quality_results import QualityJobOutcome, ResearchUnitReport
from clue_api.arv2.quality_review import review_input
from clue_config import load_settings
from clue_core import ExecutionId, OperationId
from clue_fleet import LeaseGeneration, WorkId
from clue_fleet.work_worker import WorkContext
from clue_research.identity import insert_contact_entity
from clue_storage.fs import FsStorage
from clue_toolbelt import ToolContext
from tests.arv2.account_research_job_helpers import finish_seeded_job
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_generation_db import _waiting_account
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def _settle_person(conn, op, job, status="completed", failure_code=None, **finalization):
    await finish_seeded_job(
        conn,
        model_rounds=0,
        tool_calls=0,
        cost_usd=Decimal(0),
        credits=Decimal(0),
        media_seconds=0,
        job_id=job,
        status=status,
        finalization=finalization,
        **({"failure_code": failure_code} if failure_code else {}),
    )
    await record_child_result(conn, workspace_id=op.workspace_id, job_id=job)


async def _save_brief(conn, storage, op, *, execution_id, body):
    """What a finished turn leaves behind: a snapshot of its folders with the brief in it."""
    sha = hashlib.sha256(body.encode()).hexdigest()
    await storage.put(
        f"{op.workspace_id}/agent-workspace/{sha}", body.encode(), media_type="text/md"
    )
    manifest = json.dumps({"entries": [{"path": "outputs/page-brief.md", "sha256": sha}]}).encode()
    key = f"{op.workspace_id}/agent-workspace/manifest-{execution_id}"
    await storage.put(key, manifest, media_type="application/json")
    project = (
        await conn.execute(
            text("SELECT project_id FROM arv2_research_run WHERE run_id=:run"), {"run": op.run_id}
        )
    ).scalar_one()
    await conn.execute(
        text("""INSERT INTO agent_workspace_snapshot
            (workspace_id,thread_id,project_id,version,manifest_artifact_key,manifest_sha256)
            VALUES (:ws,:thread,:project,1,:key,:sha)"""),
        {
            "ws": op.workspace_id,
            "thread": f"research-quality-{execution_id}",
            "project": project,
            "key": key,
            "sha": hashlib.sha256(manifest).hexdigest(),
        },
    )


class _Harness:
    """The real driver and database, with a fake agent and a fake page writer."""

    def __init__(self, conn, tmp_path, op, scope, generation, *, brief="Pursue: the one brief."):
        self.conn, self.op, self.generation, self.brief = conn, op, generation, brief
        self.storage = FsStorage(tmp_path)
        self.scope = replace(scope, catalog_version="v4", input_refs={"quality_recipe_version": 40})
        self.calls: list[str] = []
        self.review_kwargs: list[dict] = []
        self.executions: list = []
        self.fail_review = False
        self.during_review = None
        self.needs_review: list[bool] = []
        self.handler = Arv2AccountResearchWorkHandler(
            settings=load_settings(),
            conn_factory=self._connections,
            artifacts=None,
            storage=self.storage,
            clients=None,
            model_provider=None,
            model_id="fixture/research",
            writer=None,
            quality_runner=self._runner,
            page_writer=object(),
        )
        composition = SimpleNamespace(
            scope=self.scope,
            run=SimpleNamespace(context_id=generation.context_id),
            model_id="fixture/research",
        )

        async def compose_quality(_conn, _job, _run):
            return composition

        self.handler._compose_quality = compose_quality
        self.handler._tool_runtime = lambda _composition: None

    @asynccontextmanager
    async def _connections(self):
        async with self.conn.begin_nested():
            yield self.conn

    async def _runner(self, **kwargs):
        self.calls.append("review")
        self.review_kwargs.append(kwargs)
        if self.during_review is not None:
            await self.during_review()
        if self.fail_review:
            raise RuntimeError("the agent could not resume")
        eid = await self._bind()
        self.executions.append(eid)
        if self.brief is not None:
            await _save_brief(self.conn, self.storage, self.op, execution_id=eid, body=self.brief)
        return QualityJobOutcome(
            execution_id=eid,
            status="completed",
            finalization_key=None,
            report=None,
            failure_code=None,
        )

    async def _bind(self):
        eid = await execution(self.conn, self.op, self.scope.project_id)
        await bind_execution(
            self.conn,
            self.op,
            execution_id=eid,
            context_id=self.generation.context_id,
            role="account_research",
            limits=Allowance(5, 5, 1),
        )
        return eid

    def patch_pages(self, monkeypatch):
        async def rewrite(**kwargs):
            self.calls.append("account_pages")
            self.calls.extend("contact_page" for _ in kwargs.get("deferred", ()))
            self.needs_review.append(kwargs.get("needs_review", False))
            self.brief_seen = await page_writer_runtime.page_brief(
                self.conn, self.storage, self.scope
            )
            applied = await reconcile_generation(
                self.conn,
                workspace_id=self.op.workspace_id,
                generation_id=self.generation.generation_id,
                expected_revision=kwargs["revision"],
                processed_snapshot=True,
                needs_review=kwargs.get("needs_review", False),
            )
            return {"applied": applied}

        monkeypatch.setattr(page_writer_runtime, "rewrite_account_pages", rewrite)

    async def current(self):
        return await read_generation(
            self.conn,
            workspace_id=self.op.workspace_id,
            generation_id=self.generation.generation_id,
        )

    async def continuation(self, *, attempt=1, revision=None):
        current = await self.current()
        return await self.handler.handle(
            WorkContext(
                task_id=uuid4(),
                work_id=WorkId(continuation_work_id(current)),
                worker_id="review",
                lease_generation=LeaseGeneration(1),
                payload={
                    "continuation": "quality_reconciliation",
                    "workspace_id": self.op.workspace_id,
                    "generation_id": str(current.generation_id),
                    "input_revision": revision or current.input_revision,
                },
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
                task_attempt=attempt,
            )
        )

    async def pending(self):
        return await pending_continuations(self.conn)


async def _ready(conn, tmp_path, monkeypatch, *, brief="Pursue: the one brief.", settle=True):
    op, scope, generation, child = await _waiting_account(conn, tmp_path, idle_minutes=1)
    harness = _Harness(conn, tmp_path, op, scope, generation, brief=brief)
    harness.patch_pages(monkeypatch)
    if settle:
        await _settle_person(conn, op, child, summary="Found their own words.", gaps=["No talks."])
    harness.first_revision = (await harness.current()).input_revision
    return harness, child


def test_review_input_reports_every_person(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, scope, generation, running = await _waiting_account(conn, tmp_path, idle_minutes=31)
            scope = replace(scope, catalog_version="v4", input_refs={"quality_recipe_version": 40})
            people = await review_input(conn, FsStorage(tmp_path), scope, generation.context_id)
            assert people["research_date"] == scope.today.isoformat()
            [person] = people["people"]
            assert person["contact_id"]
            assert person["name"] == "Fixture person"
            assert person["status"] == "in_progress"
            assert person["still_running"] is True

            await _settle_person(
                conn,
                op,
                running,
                "needs_review",
                failure_code="retries_exhausted",
                summary="Stopped.",
                gaps=["X"],
            )
            people = await review_input(conn, FsStorage(tmp_path), scope, generation.context_id)
            [person] = people["people"]
            assert person["still_running"] is False
            assert person["status"] == "needs_review"
            assert person["failure_code"] == "retries_exhausted"
            assert person["summary"] == "Stopped."
            assert person["gaps"] == ["X"]
            assert person["findings"] == []

    run_async(case())


def test_privacy_stopped_person_gives_the_review_nothing(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            _, scope, generation, child = await _waiting_account(conn, tmp_path, idle_minutes=1)
            await conn.execute(
                text("""UPDATE arv2_research_job SET
                    input_refs=input_refs||jsonb_build_object('privacy_stopped',true)
                    WHERE job_id=:job"""),
                {"job": child},
            )
            scope = replace(scope, catalog_version="v4", input_refs={"quality_recipe_version": 40})
            [person] = (
                await review_input(conn, FsStorage(tmp_path), scope, generation.context_id)
            )["people"]
            assert person == {"contact_id": person["contact_id"], "status": "privacy_stopped"}

    run_async(case())


def test_review_runs_before_pages(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, child = await _ready(conn, tmp_path, monkeypatch)

            await conn.execute(
                text("""UPDATE arv2_research_job SET finalization_json=finalization_json
                    || '{"coverage":{"deferred_pages":["contact"]}}' WHERE job_id=:job"""),
                {"job": child},
            )

            async def compose(_conn, job):
                return SimpleNamespace(scope=replace(harness.scope, job_id=job.job_id))

            harness.handler._compose = compose
            result = await harness.continuation()
            assert result.outcome == "completed", result
            assert harness.calls == ["review", "account_pages", "contact_page"]
            kwargs = harness.review_kwargs[0]
            assert kwargs["review"]["people"][0]["summary"] == "Found their own words."
            assert "account-review" in kwargs["objective"]
            assert harness.brief_seen == "Pursue: the one brief."
            assert (await harness.current()).state != "needs_review"

    run_async(case())


def test_one_review_with_no_new_input_causes_no_other(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, _ = await _ready(conn, tmp_path, monkeypatch)
            await harness.continuation()
            assert not await harness.pending()

    run_async(case())


def test_person_finishing_during_review_triggers_next_review(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, _ = await _ready(conn, tmp_path, monkeypatch)
            revision = (await harness.current()).input_revision

            async def late_result():
                await signal(
                    conn,
                    workspace_id=harness.op.workspace_id,
                    generation_id=harness.generation.generation_id,
                    event_id=uuid4(),
                    reason="person_result",
                )

            harness.during_review = late_result
            await harness.continuation()
            current = await harness.current()
            assert current.reconciled_revision == revision
            assert [g.input_revision for g in await harness.pending()] == [revision + 1]

    run_async(case())


def test_review_without_brief_falls_back(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, _ = await _ready(conn, tmp_path, monkeypatch, brief=None)
            result = await harness.continuation()
            assert result.outcome == "completed"
            assert harness.calls == ["review", "account_pages"]
            assert harness.needs_review == [True]
            assert (await harness.current()).state == "needs_review"

    run_async(case())


def test_review_failure_retries_then_falls_back(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, _ = await _ready(conn, tmp_path, monkeypatch)
            harness.fail_review = True
            revision = (await harness.current()).input_revision
            for attempt in (1, 2):
                result = await harness.continuation(attempt=attempt)
                assert result.requeue is True
                assert (await harness.current()).reconciled_revision < revision
            assert "account_pages" not in harness.calls
            result = await harness.continuation(attempt=3)
            assert result.requeue is False
            assert harness.calls == ["review", "review", "review", "account_pages"]
            current = await harness.current()
            assert current.reconciled_revision == revision
            assert current.state == "needs_review"

    run_async(case())


def test_stale_review_does_not_settle(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, _ = await _ready(conn, tmp_path, monkeypatch)
            stale = (await harness.current()).input_revision
            await signal(
                conn,
                workspace_id=harness.op.workspace_id,
                generation_id=harness.generation.generation_id,
                event_id=uuid4(),
                reason="person_result",
            )
            result = await harness.continuation(revision=stale)
            assert result.references.get("superseded") is True
            assert harness.calls == []
            assert (await harness.current()).reconciled_revision < stale

    run_async(case())


def test_page_brief_reads_the_review_turn(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, _ = await _ready(conn, tmp_path, monkeypatch)
            older = await harness._bind()
            await conn.execute(
                text("""UPDATE arv2_quality_execution SET created_at=now()-interval '1 hour'
                    WHERE execution_id=:id"""),
                {"id": older},
            )
            await _save_brief(conn, harness.storage, harness.op, execution_id=older, body="Older.")
            await harness.continuation()
            assert harness.brief_seen == "Pursue: the one brief."

    run_async(case())


def test_settled_job_finalization_is_untouched_by_the_review(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, _ = await _ready(conn, tmp_path, monkeypatch)
            before = await read_job(conn, job_id=harness.scope.job_id)
            await harness.continuation()
            after = await read_job(conn, job_id=harness.scope.job_id)
            assert (before.status, before.finalization) == (after.status, after.finalization)

    run_async(case())


async def _nominate_with_the_real_tool(conn, tmp_path, op, scope, cid, *, cap):
    storage = FsStorage(tmp_path)
    scope = replace(
        scope,
        catalog_version="v4",
        committee_cap=cap,
        input_refs={"quality_recipe_version": 40},
    )
    eid = await execution(conn, op, scope.project_id)
    await bind_execution(
        conn,
        op,
        execution_id=eid,
        context_id=cid,
        role="account_research",
        limits=Allowance(20, 40, 4),
    )
    body = "Alex Example now leads operations. Profile: https://www.linkedin.com/in/alex-example/"
    source = await save(conn, storage, op, body)

    @asynccontextmanager
    async def connections():
        yield conn

    tool = NominateBriefedWebCommitteeTool(scope, storage, purge_unevidenced=True)
    args = NominateBriefedWebInput(
        name="Alex Example",
        linkedin_url="https://www.linkedin.com/in/alex-example/",
        source_id=source.source_id,
        persona_key="operations",
        role="champion",
        rationale="Their predecessor has left; Alex now holds this responsibility.",
        research_brief="Research Alex. The person who held this seat has left the company.",
    )

    async def nominate():
        ctx = ToolContext(
            workspace_id=scope.workspace_id,
            actor="agent",
            conn_factory=connections,
            execution_id=ExecutionId(eid),
            operation_id=OperationId(uuid4()),
        )
        return await tool.invoke(args, ctx)

    return nominate


def test_review_can_nominate_past_the_cap(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, scope, generation, _ = await _waiting_account(conn, tmp_path, idle_minutes=1)
            nominate = await _nominate_with_the_real_tool(
                conn, tmp_path, op, scope, generation.context_id, cap=1
            )
            receipt = await nominate()
            job = await read_job(conn, job_id=receipt.references["person_job_id"])
            assert job.status == "not_started"
            ready = await ready_person_jobs(conn, generation_id=generation.generation_id)
            assert str(job.job_id) in {str(row["job_id"]) for row in ready}

    run_async(case())


def test_first_turn_still_respects_the_cap(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, scope, generation, _ = await _waiting_account(
                conn, tmp_path, idle_minutes=1, finish_parent=False
            )
            nominate = await _nominate_with_the_real_tool(
                conn, tmp_path, op, scope, generation.context_id, cap=1
            )
            with pytest.raises(ValueError, match="cap reached"):
                await nominate()

    run_async(case())


def test_renominating_someone_reuses_their_job(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, scope, generation, _ = await _waiting_account(conn, tmp_path, idle_minutes=1)
            nominate = await _nominate_with_the_real_tool(
                conn, tmp_path, op, scope, generation.context_id, cap=1
            )
            first = await nominate()
            again = await nominate()
            assert first.references["person_job_id"] == again.references["person_job_id"]
            assert again.references["replayed"] is True

    run_async(case())


async def _add_nominee(harness):
    """What a nomination leaves behind for the flow: a registered person who has not started."""
    contact = await insert_contact_entity(
        harness.conn, account_entity_id=harness.op.account_id, full_name="The replacement"
    )
    job = uuid4()
    await create_job(
        harness.conn,
        job_id=job,
        run_id=harness.op.run_id,
        workspace_id=harness.op.workspace_id,
        account_entity_id=harness.op.account_id,
        subject_type="person",
        subject_entity_id=contact,
        profile_sha256="a" * 64,
        input_refs={"parent_job_id": str(harness.op.job_id), "quality_recipe_version": 40},
    )
    await register_child(harness.conn, harness.generation, job_id=job)
    return job


def test_review_that_nominates_writes_no_pages(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, _ = await _ready(conn, tmp_path, monkeypatch)
            nominees = []

            async def nominate():
                nominees.append(await _add_nominee(harness))

            harness.during_review = nominate
            revision = (await harness.current()).input_revision
            result = await harness.continuation()
            assert result.outcome == "completed"
            assert harness.calls == ["review"]
            assert (await harness.current()).reconciled_revision == revision
            assert not await harness.pending()

            harness.during_review = None
            await _settle_person(conn, harness.op, nominees[0], summary="The replacement.")
            [pending] = await harness.pending()
            assert pending.input_revision > revision
            await harness.continuation()
            assert harness.calls == ["review", "review", "account_pages"]
            assert not await harness.pending()
            # The second review continues from the first, so it remembers what it decided.
            second = harness.review_kwargs[1]["review"]
            assert second["_source_execution"] == str(harness.executions[0])

    run_async(case())


def test_a_nominee_who_hangs_does_not_stall_the_account(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, _ = await _ready(conn, tmp_path, monkeypatch)
            nominees = []

            async def nominate():
                nominees.append(await _add_nominee(harness))

            harness.during_review = nominate
            await harness.continuation()
            harness.during_review = None
            await conn.execute(
                text("""UPDATE arv2_research_job SET status='in_progress',
                    started_at=now()-interval '31 minutes' WHERE job_id=:job"""),
                {"job": nominees[0]},
            )
            [pending] = await pending_continuations(conn, stall_after=timedelta(minutes=30))
            await harness.continuation(revision=pending.input_revision)
            assert harness.calls == ["review", "review", "account_pages"]

    run_async(case())


def test_nominee_survives_a_crashed_review(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            harness, _ = await _ready(conn, tmp_path, monkeypatch)
            nominees = []

            async def nominate():
                nominees.append(await _add_nominee(harness))

            harness.during_review = nominate
            harness.fail_review = True
            first = await harness.continuation()
            assert first.requeue is True
            harness.during_review, harness.fail_review = None, False
            ready = await ready_person_jobs(conn, generation_id=harness.generation.generation_id)
            assert nominees[0] in {row["job_id"] for row in ready}

            # The retry finds the nominee still running, so it waits rather than writing pages.
            await harness.continuation(attempt=2)
            assert harness.calls == ["review"]

            # Whether the nominee then hangs or finishes, a fresh revision carries the flow on.
            await conn.execute(
                text("""UPDATE arv2_research_job SET status='in_progress',
                    started_at=now()-interval '31 minutes' WHERE job_id=:job"""),
                {"job": nominees[0]},
            )
            [pending] = await pending_continuations(conn, stall_after=timedelta(minutes=30))
            assert pending.input_revision > harness.first_revision
            await harness.continuation(revision=pending.input_revision)
            assert harness.calls == ["review", "review", "account_pages"]

    run_async(case())


def test_whole_flow_with_one_slot(tmp_path, monkeypatch):
    """The direct deadlock proof: one job slot, an account and three people, all the way to pages.

    Every task the queue is offered runs at once, as a fleet would run it, and competes for the
    one slot. Nothing that holds the slot may wait for anything else.
    """

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            refs = {"quality_recipe_version": 40}
            scope = replace(scope, catalog_version="v4", input_refs=refs)
            await conn.execute(
                text("""UPDATE arv2_research_job SET input_refs=input_refs
                    || jsonb_build_object('quality_recipe_version',40) WHERE job_id=:job"""),
                {"job": op.job_id},
            )
            job = await read_job(conn, job_id=op.job_id)
            run = await read_run(conn, run_id=op.run_id)
            lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with lock, conn.begin_nested():
                    yield conn

            queue = _Queue()
            events: list[str] = []
            page_writes: list[int] = []

            async def runner(*, scope, context_id, runtime, objective, model_id, **kwargs):
                await asyncio.sleep(0)
                eid = uuid4()
                if kwargs.get("review") is not None:
                    events.append("review")
                    async with connections() as held:
                        await _save_brief(held, storage, op, execution_id=eid, body="The brief.")
                elif scope.person_subject_id:
                    events.append("person")
                else:
                    events.append("account")
                    async with connections() as held:
                        generation = await ensure_generation(held, op, context_id=cid)
                        for index in range(3):
                            contact = await insert_contact_entity(
                                held, account_entity_id=op.account_id, full_name=f"Person {index}"
                            )
                            person = uuid4()
                            await create_job(
                                held,
                                job_id=person,
                                run_id=op.run_id,
                                workspace_id=op.workspace_id,
                                account_entity_id=op.account_id,
                                subject_type="person",
                                subject_entity_id=contact,
                                profile_sha256="a" * 64,
                                input_refs={**refs, "parent_job_id": str(op.job_id)},
                            )
                            await register_child(held, generation, job_id=person)
                report = None
                if kwargs.get("review") is None:
                    report = ResearchUnitReport(
                        context_id=context_id, job_id=scope.job_id, summary="Fixture."
                    )
                return QualityJobOutcome(
                    execution_id=eid,
                    status="completed",
                    finalization_key=None,
                    report=report,
                    failure_code=None,
                )

            async def rewrite(**kwargs):
                page_writes.append(kwargs["revision"])
                events.append("pages")
                async with connections() as held:
                    await reconcile_generation(
                        held,
                        workspace_id=op.workspace_id,
                        generation_id=kwargs["generation_id"],
                        expected_revision=kwargs["revision"],
                        processed_snapshot=True,
                    )
                return {"applied": True}

            monkeypatch.setattr(page_writer_runtime, "rewrite_account_pages", rewrite)
            settings = load_settings().model_copy(update={"arv2_account_max_parallel_jobs": 1})
            handler = Arv2AccountResearchWorkHandler(
                settings=settings,
                conn_factory=connections,
                artifacts=None,
                storage=storage,
                clients=None,
                model_provider=None,
                model_id="fixture/research",
                writer=None,
                quality_runner=runner,
                page_writer=object(),
                queue=queue,
            )
            assert handler.max_in_flight == 1

            def composed(row):
                person = (
                    {"subject_kind": "person", "contact_id": row.subject_entity_id}
                    if row.subject_type == "person"
                    else {}
                )
                return SimpleNamespace(
                    job=row,
                    run=run,
                    scope=replace(scope, job_id=row.job_id, **person),
                    bundle=SimpleNamespace(manifest_sha256=lambda: "a" * 64),
                    model_id="fixture/research",
                    task_instruction="Research.",
                )

            async def compose(_conn, row):
                return composed(row)

            async def compose_quality(_conn, row, _run):
                return composed(row)

            async def landed(timeout_s):
                del timeout_s

            handler._compose = compose
            handler._compose_quality = compose_quality
            handler._tool_runtime = lambda _composition: SimpleNamespace(wait_for_inflight=landed)

            def context(offer):
                return WorkContext(
                    task_id=uuid4(),
                    work_id=WorkId(offer["work_id"]),
                    worker_id="one-slot",
                    lease_generation=LeaseGeneration(1),
                    payload=offer["payload"],
                    stop_requested=asyncio.Event(),
                    lease_lost=asyncio.Event(),
                )

            async def drive():
                running = {
                    asyncio.create_task(
                        handler.handle(
                            context(
                                {
                                    "work_id": job.job_id,
                                    "payload": {
                                        "job_id": str(job.job_id),
                                        "run_id": str(job.run_id),
                                        "workspace_id": job.workspace_id,
                                    },
                                }
                            )
                        )
                    )
                }
                seen: set[str] = set()
                while True:
                    if running:
                        done, _ = await asyncio.wait(running, timeout=0.05)
                        for task in done:
                            running.discard(task)
                            task.result()
                    await handler.sweep_quality()
                    for key, offer in queue.offers.items():
                        if key not in seen:
                            seen.add(key)
                            running.add(asyncio.create_task(handler.handle(context(offer))))
                    if page_writes and not running:
                        return

            await asyncio.wait_for(drive(), timeout=60)
            assert events.count("account") == 1
            assert events.count("person") == 3
            assert events.index("review") > max(
                i for i, event in enumerate(events) if event == "person"
            )
            assert events[-2:] == ["review", "pages"]
            assert events.count("pages") == 1

    run_async(case())


class _Queue:
    def __init__(self):
        self.offers = {}

    async def enqueue(self, **kwargs):
        key = kwargs["dedup_key"]
        existed = key in self.offers
        self.offers[key] = kwargs
        return not existed
