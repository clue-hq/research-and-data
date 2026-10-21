"""The conversation engine binds the turn's sandbox workspace for exactly the turn (Task 11).

``run_python@1`` is handed ids, never handles, so it finds its host directories by looking the
turn up in :class:`~clue_api.sandbox.workspaces.SandboxWorkspaces`. That registry is only ever
truthful if the engine registers *while it holds the lease* and releases on every exit path —
otherwise a later turn's script could run against a released (or another turn's) tree.

These are engine-level properties, so the substituted boundary is everything the turn's durable
side does: the journal, the history and the runtime are doubles, and the workspace factory and
its lease are real, because the paths under test are derived from the real lease's segments.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from clue_agents import (
    AgentExecutionStatus,
    AgentTurnOutcome,
    AgentTurnRequest,
    MountRequest,
)
from clue_agents.worker_area import ChatScope
from clue_api import conversation_turns as engine_module
from clue_api.conversation_turns import ConversationTurnEngine
from clue_api.crm.read_sinks import CrmReadSinks
from clue_api.sandbox.workspaces import SandboxWorkspaces
from clue_core import ExecutionId
from tests.agents.conftest import artifact, constitution
from tests.agents.workspace_helpers import make_factory, policy

EXECUTION_ID = ExecutionId(UUID("00000000-0000-0000-0000-0000000011a1"))
TURN_ID = UUID("00000000-0000-0000-0000-0000000011a2")
WORKSPACE_ID = "ws-1"
PROJECT_ID = "project-1"
THREAD_ID = "thread-1"


class _Turns:
    """The turn journal, reduced to the two calls ``execute`` makes before it runs anything."""

    async def create(self, **_: Any) -> None:
        return None

    async def load_committed_outcome(self, **_: Any) -> AgentTurnOutcome | None:
        return None


class _History:
    async def append(self, **_: Any) -> None:
        return None


class _Contexts:
    async def assemble(self, **_: Any) -> object:
        return object()


class _Components:
    """Only the attributes ``execute`` touches on this path."""

    def __init__(
        self,
        *,
        workspaces: Any,
        sandbox_workspaces: SandboxWorkspaces | None,
        crm_read_sinks: CrmReadSinks | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.sandbox_workspaces = sandbox_workspaces
        self.crm_read_sinks = crm_read_sinks
        self.turns = _Turns()
        self.history = _History()
        self.artifacts: Any = None
        self.profiles: Any = None


def _outcome() -> AgentTurnOutcome:
    # A failed outcome carries no finalization, so `_result_from_outcome` reads no artifact and
    # this test needs no artifact store at all.
    return AgentTurnOutcome(
        turn_id=TURN_ID,
        execution_id=EXECUTION_ID,
        status=AgentExecutionStatus.FAILED,
        failure_code="test_double",
    )


def _request() -> AgentTurnRequest:
    return AgentTurnRequest(
        turn_id=TURN_ID,
        thread_id=THREAD_ID,
        constitution=constitution(
            execution_id=EXECUTION_ID,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            focus_refs=(),
        ),
        user_message_artifact_ref=artifact("message.txt", workspace_id=WORKSPACE_ID),
        requested_at=datetime(2026, 9, 19, 12, tzinfo=UTC),
    )


def _engine(
    *,
    components: _Components,
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    on_build: Any = None,
) -> ConversationTurnEngine:
    async def _no_history(*_: Any, **__: Any) -> tuple[()]:
        return ()

    def _build(**_: Any) -> object:
        if on_build is not None:
            on_build()
        return object()

    monkeypatch.setattr(engine_module, "load_head_of_abm_history", _no_history)
    monkeypatch.setattr(engine_module, "build_head_of_abm_stage0_execution", _build)
    return ConversationTurnEngine(
        surface="test",
        resolved=SimpleNamespace(profile=object()),  # type: ignore[arg-type]
        components=components,  # type: ignore[arg-type]
        tools=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        executor=None,  # type: ignore[arg-type]
        compatibility=None,  # type: ignore[arg-type]
        contexts=_Contexts(),  # type: ignore[arg-type]
        runtime=runtime,
        captured_turns=None,  # type: ignore[arg-type]
        plans=None,  # type: ignore[arg-type]
        conn_factory=None,  # type: ignore[arg-type]
    )


def _make_private(root: Path, path: Path) -> None:
    """Materialize a mounted tree the way the fleet's own sync does: 0700 at every level."""

    current = root
    for segment in path.relative_to(root).parts:
        current = current / segment
        if not current.exists():
            current.mkdir(mode=0o700)


def _lease(tmp_path: Path, mounts: MountRequest) -> tuple[Any, Any]:
    _root, factory, _sink = make_factory(tmp_path)
    # The chat's own copies sit in its own folder, beside its agent root (F3, WS-37).
    chat_dir = factory.chat_host_path(ChatScope(WORKSPACE_ID, PROJECT_ID, THREAD_ID))
    if mounts.project_library:
        _make_private(factory.root_path, chat_dir / "project")
    if mounts.attachments:
        _make_private(factory.root_path, chat_dir / "attachments")
    lease = factory.acquire(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        thread_id=THREAD_ID,
        execution_id=EXECUTION_ID,
        policy=policy(),
        mounts=mounts,
    )
    return factory, lease


def test_the_turns_sandbox_workspace_is_bound_for_the_turn_and_released_after(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mounts = MountRequest(project_library=True, attachments=True)
    factory, lease = _lease(tmp_path, mounts)
    sandbox = SandboxWorkspaces(max_runs_per_turn=4)
    components = _Components(workspaces=factory, sandbox_workspaces=sandbox)
    seen: dict[str, Any] = {}

    class _Runtime:
        async def run(self, **_: Any) -> AgentTurnOutcome:
            seen["mounts"] = sandbox.mounts_for(EXECUTION_ID)
            seen["runs"] = sandbox.runs_remaining(EXECUTION_ID)
            return _outcome()

    def _at_build() -> None:
        # The binding is in place before anything model-shaped is composed — the adapter build is
        # where the spill sink is bound, and the sandbox is bound at the same point.
        seen["at_build"] = sandbox.mounts_for(EXECUTION_ID)

    engine = _engine(
        components=components,
        runtime=_Runtime(),
        monkeypatch=monkeypatch,
        on_build=_at_build,
    )
    try:
        result = asyncio.run(
            engine.execute(
                request=_request(),
                lease=lease,
                budget_limit_millicents=1,
                mounts=mounts,
            )
        )
    finally:
        lease.backend.close()
        factory.close()

    assert result.outcome.status is AgentExecutionStatus.FAILED
    assert seen["at_build"] is not None
    bound = seen["mounts"]
    assert bound is not None
    assert bound.thread_root == factory.thread_host_path(WORKSPACE_ID, PROJECT_ID, THREAD_ID)
    # The mount table is the one the lease was acquired with, not a guess.
    assert "project" in bound.read_only
    assert set(bound.read_write) == {"scratch", "work", "outputs"}
    assert seen["runs"] == 4
    # And the turn is over: the next turn's tool cannot reach this turn's tree.
    assert sandbox.mounts_for(EXECUTION_ID) is None
    assert sandbox.runs_remaining(EXECUTION_ID) == 0


def test_a_runtime_that_raises_still_releases_the_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mounts = MountRequest()
    factory, lease = _lease(tmp_path, mounts)
    sandbox = SandboxWorkspaces(max_runs_per_turn=2)
    components = _Components(workspaces=factory, sandbox_workspaces=sandbox)

    class _Runtime:
        async def run(self, **_: Any) -> AgentTurnOutcome:
            raise RuntimeError("turn exploded")

    engine = _engine(components=components, runtime=_Runtime(), monkeypatch=monkeypatch)
    try:
        with pytest.raises(RuntimeError, match="turn exploded"):
            asyncio.run(
                engine.execute(
                    request=_request(),
                    lease=lease,
                    budget_limit_millicents=1,
                    mounts=mounts,
                )
            )
    finally:
        lease.backend.close()
        factory.close()

    assert sandbox.mounts_for(EXECUTION_ID) is None
    # Released, so the same execution id could be registered again by an honest retry.
    sandbox.register(EXECUTION_ID, _unused_mounts(factory))


def _unused_mounts(factory: Any) -> Any:
    from clue_api.sandbox.workspaces import SandboxMounts

    return SandboxMounts(
        thread_root=factory.thread_host_path(WORKSPACE_ID, PROJECT_ID, THREAD_ID),
        read_only={},
        read_write={},
        policy=policy(),
    )


def test_a_surface_that_names_no_mounts_registers_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trial and the test builders acquire their lease themselves and pass no MountRequest.

    Registering a guessed mount table for them would hand a script paths the turn never asked
    for, so the honest answer is no registration — and ``run_python@1`` then refuses by name.
    """

    factory, lease = _lease(tmp_path, MountRequest())
    sandbox = SandboxWorkspaces(max_runs_per_turn=2)
    components = _Components(workspaces=factory, sandbox_workspaces=sandbox)
    seen: dict[str, Any] = {}

    class _Runtime:
        async def run(self, **_: Any) -> AgentTurnOutcome:
            seen["mounts"] = sandbox.mounts_for(EXECUTION_ID)
            return _outcome()

    engine = _engine(components=components, runtime=_Runtime(), monkeypatch=monkeypatch)
    try:
        asyncio.run(
            engine.execute(request=_request(), lease=lease, budget_limit_millicents=1),
        )
    finally:
        lease.backend.close()
        factory.close()

    assert seen["mounts"] is None


def test_a_process_with_no_sandbox_registry_runs_the_turn_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sandbox is off by default; a turn on such a worker must be completely unaffected."""

    mounts = MountRequest()
    factory, lease = _lease(tmp_path, mounts)
    components = _Components(workspaces=factory, sandbox_workspaces=None)

    class _Runtime:
        async def run(self, **_: Any) -> AgentTurnOutcome:
            return _outcome()

    engine = _engine(components=components, runtime=_Runtime(), monkeypatch=monkeypatch)
    try:
        result = asyncio.run(
            engine.execute(
                request=_request(),
                lease=lease,
                budget_limit_millicents=1,
                mounts=mounts,
            )
        )
    finally:
        lease.backend.close()
        factory.close()

    assert result.outcome.status is AgentExecutionStatus.FAILED


def test_the_turns_crm_read_sink_is_bound_for_the_turn_and_released_after(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``run_crm_action@1`` writes into the turn's own ``reads/``, found by execution id."""

    factory, lease = _lease(tmp_path, MountRequest())
    sinks = CrmReadSinks()
    components = _Components(workspaces=factory, sandbox_workspaces=None, crm_read_sinks=sinks)
    seen: dict[str, Any] = {}

    class _Runtime:
        async def run(self, **_: Any) -> AgentTurnOutcome:
            seen["sink"] = sinks.sink_for(EXECUTION_ID)
            raise RuntimeError("turn exploded")

    engine = _engine(components=components, runtime=_Runtime(), monkeypatch=monkeypatch)
    try:
        with pytest.raises(RuntimeError, match="turn exploded"):
            asyncio.run(engine.execute(request=_request(), lease=lease, budget_limit_millicents=1))
    finally:
        lease.backend.close()
        factory.close()

    assert seen["sink"] is lease.backend
    assert sinks.sink_for(EXECUTION_ID) is None
