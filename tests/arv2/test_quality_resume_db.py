"""A research turn re-claimed after it stopped continues its saved conversation.

Spec 2026-10-14 §3.1. Real research runtime, database and workspace; scripted models never spend.
Each test runs a job until a scripted model "dies", then builds a fresh runtime over the same
database and checkpoint store, as the next worker to claim the job would.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr
from sqlalchemy import text
from structlog.testing import capture_logs

from clue_agents import (
    AgentExecutionStatus,
    AgentWorkspaceFactory,
    ScriptedAgentChatModel,
    WorkspaceRootPolicy,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.job_resume import ResearchRestartRequired
from clue_api.arv2.quality_execution import Allowance
from clue_api.quality_research_wiring import ResearchUnitRuntime, quality_tools
from clue_config import load_settings
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_runtime_db import Models
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

REVISION = 15
MARKER = "Resume marker 7f3a"
OBJECTIVE = f"{MARKER}: read the saved report and delegate faithful claim processing."


class _StopOnce(ScriptedAgentChatModel):
    """Raises once when its script reaches ``stop_at``, as a worker dying mid-turn would."""

    stop_at: int = -1
    error: Any = RuntimeError
    _stopped: bool = PrivateAttr(default=False)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self._stopped and self._cursor == self.stop_at:
            self._stopped = True
            raise self.error("worker died mid-turn")
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _Held(Exception):
    """Raised by a scripted model once the test has cancelled the job around it.

    ``reached`` tells the test the model call is in flight; ``release`` lets the call end after
    the cancellation, so the worker thread finishes without producing a reply.
    """

    reached = threading.Event()
    release = threading.Event()

    def __init__(self, message: str) -> None:
        _Held.reached.set()
        _Held.release.wait(60)
        super().__init__(message)


class _ResumableModels(Models):
    """One model per role for the whole test, so a rebuilt runtime continues the script."""

    def __init__(self, *args, stop_role=None, stop_at=-1, error=RuntimeError, **kwargs):
        super().__init__(*args, **kwargs)
        self._models: dict[str, _StopOnce] = {}
        self.stop_role, self.stop_at, self.error = stop_role, stop_at, error

    def build(self, **kwargs):
        role = kwargs["role"]
        if role in self._models:
            self.builds.append(role)
            return self._models[role]
        scripted = super().build(**kwargs)
        self._models[role] = _StopOnce(
            responses=scripted.responses,
            stop_at=self.stop_at if role == self.stop_role else -1,
            error=self.error,
        )
        return self._models[role]


@asynccontextmanager
async def _job(tmp_path):
    async with rollback_conn() as conn:
        storage = FsStorage(tmp_path / "blobs")
        op, scope, context_id = await setup(conn, storage)
        scope = replace(
            scope, catalog_version="v4", input_refs={"quality_recipe_version": REVISION}
        )
        source = await save(conn, storage, op, {"employees": 64}, kind="provider_record", url=None)
        lock = asyncio.Lock()

        @asynccontextmanager
        async def connections():
            async with lock, conn.begin_nested():
                yield conn

        for directory in ("source", "home"):
            (tmp_path / directory).mkdir(mode=0o700)
        workspaces = AgentWorkspaceFactory(
            prepared_root=WorkspaceRootPolicy(
                configured_root=tmp_path / "runtime",
                source_root=tmp_path / "source",
                home_root=tmp_path / "home",
            ).prepare(),
            artifact_sink=DurableAgentArtifactStore(storage=storage, conn_factory=connections),
        )
        yield SimpleNamespace(
            conn=conn,
            storage=storage,
            scope=scope,
            context_id=context_id,
            source=source,
            connections=connections,
            workspaces=workspaces,
        )


def _runtime(job, models, saver, scope=None) -> ResearchUnitRuntime:
    @asynccontextmanager
    async def checkpoints(execution_id):
        yield saver

    scope = scope or job.scope
    return ResearchUnitRuntime(
        scope=scope,
        context_id=job.context_id,
        settings=load_settings(_env_file=None),
        storage=job.storage,
        connections=job.connections,
        models=models,
        workspaces=job.workspaces,
        tools=quality_tools(scope, job.storage, purge=True),
        limits=Allowance(20, 30, 4),
        checkpointer_factory=checkpoints,
    )


async def _count(job, sql: str) -> int:
    return (await job.conn.execute(text(sql), {"job": job.scope.job_id})).scalar_one()


_BUNDLES = (
    "SELECT count(*) FROM agent_context_bundle b JOIN arv2_quality_execution q "
    "ON q.execution_id=b.execution_id WHERE q.job_id=:job AND q.role={role}"
)


@pytest.fixture
def prompts(monkeypatch) -> list[str]:
    seen: list[str] = []
    original = ScriptedAgentChatModel._generate

    def capture(self, messages, *args, **kwargs):
        seen.append("\n".join(str(message.content) for message in messages))
        return original(self, messages, *args, **kwargs)

    monkeypatch.setattr(ScriptedAgentChatModel, "_generate", capture)
    return seen


def test_a_parent_stopped_mid_turn_continues_its_saved_conversation(tmp_path, prompts):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source, job.scope, job.context_id, stop_role="account_research", stop_at=3
            )
            saver = InMemorySaver()
            first = await _runtime(job, models, saver).run(objective=OBJECTIVE)
            assert first.status is AgentExecutionStatus.FAILED
            second = await _runtime(job, models, saver).run(objective=OBJECTIVE)
            assert second.status is AgentExecutionStatus.COMPLETED, second
            assert await _count(job, _BUNDLES.format(role="'account_research'")) == 1
            assert models.builds.count("research_claims") == 1
            delegations = await _count(
                job,
                "SELECT count(*) FROM arv2_quality_activity "
                "WHERE job_id=:job AND kind='delegation'",
            )
            assert delegations == 1
            assert prompts and all(prompt.count(MARKER) <= 1 for prompt in prompts)

    run_async(case())


def test_a_drifted_context_with_a_saved_conversation_continues_and_says_what_drifted(
    tmp_path, prompts
):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source, job.scope, job.context_id, stop_role="account_research", stop_at=3
            )
            saver = InMemorySaver()
            first = await _runtime(job, models, saver).run(objective=OBJECTIVE)
            assert first.status is AgentExecutionStatus.FAILED
            with capture_logs() as logs:
                second = await _runtime(job, models, saver).run(
                    objective=OBJECTIVE + " Changed after the stop."
                )
            assert second.status is AgentExecutionStatus.COMPLETED, second
            drift = [e for e in logs if e["event"] == "arv2.quality.resume_context_drift"]
            assert drift and "l7_turn" in drift[0]["layers"]
            assert await _count(job, _BUNDLES.format(role="'account_research'")) == 1

    run_async(case())


def test_changed_instructions_ask_for_a_restart(tmp_path, prompts):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source, job.scope, job.context_id, stop_role="account_research", stop_at=3
            )
            saver = InMemorySaver()
            first = await _runtime(job, models, saver).run(objective=OBJECTIVE)
            assert first.status is AgentExecutionStatus.FAILED
            changed = replace(job.scope, input_refs={"quality_recipe_version": 14})
            with pytest.raises(ResearchRestartRequired) as restart:
                await _runtime(job, models, saver, scope=changed).run(objective=OBJECTIVE)
            assert restart.value.reason == "instructions_changed"

    run_async(case())


def test_a_drift_before_the_first_step_asks_for_a_restart(tmp_path, prompts):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source, job.scope, job.context_id, stop_role="account_research", stop_at=0
            )
            first = await _runtime(job, models, InMemorySaver()).run(objective=OBJECTIVE)
            assert first.status is AgentExecutionStatus.FAILED
            # A store with no saved state: the worker died before LangGraph wrote anything.
            with pytest.raises(ResearchRestartRequired) as restart:
                await _runtime(job, models, InMemorySaver()).run(
                    objective=OBJECTIVE + " Changed before the first step."
                )
            assert restart.value.reason == "context_changed_before_start"

    run_async(case())


def test_an_unchanged_context_with_no_saved_state_starts_normally(tmp_path, prompts):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source, job.scope, job.context_id, stop_role="account_research", stop_at=0
            )
            first = await _runtime(job, models, InMemorySaver()).run(objective=OBJECTIVE)
            assert first.status is AgentExecutionStatus.FAILED
            second = await _runtime(job, models, InMemorySaver()).run(objective=OBJECTIVE)
            assert second.status is AgentExecutionStatus.COMPLETED, second

    run_async(case())


def test_a_specialist_stopped_mid_turn_resumes_once(tmp_path, prompts):
    """The fleet cancels the job's task while a specialist is mid-call, as a lost lease or a
    deploy restart does; the next claim resumes the parent, which resumes the specialist."""

    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source,
                job.scope,
                job.context_id,
                stop_role="research_claims",
                stop_at=2,
                error=_Held,
            )
            saver = InMemorySaver()
            running = asyncio.create_task(_runtime(job, models, saver).run(objective=OBJECTIVE))
            assert await asyncio.to_thread(_Held.reached.wait, 60)
            running.cancel()
            _Held.release.set()
            with pytest.raises(asyncio.CancelledError):
                await running
            second = await _runtime(job, models, saver).run(objective=OBJECTIVE)
            assert second.status is AgentExecutionStatus.COMPLETED, second
            assert await _count(job, _BUNDLES.format(role="'research_claims'")) == 1
            delegations = await _count(
                job,
                "SELECT count(*) FROM arv2_quality_activity "
                "WHERE job_id=:job AND kind='delegation'",
            )
            assert delegations == 1
            assert all(prompt.count(MARKER) <= 1 for prompt in prompts)

    run_async(case())
