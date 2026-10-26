"""F3 Phase 1, plan Task 9: a finalized turn saves its agent folders before it commits (spec WS-9,
WS-10; AW-18)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from clue_agents import ArtifactRef, WorkspaceConflict
from clue_agents.contracts import AgentFinalizeEnvelope, FinalizeStatus
from clue_agents.workspace_snapshot import WorkspaceSaveUnavailable
from clue_agents.workspace_snapshotter import SaveReport
from clue_api.agent_runtime_wiring import AgentFinalizationAuthority
from clue_core import ExecutionId

EXECUTION = ExecutionId(UUID("00000000-0000-0000-0000-000000000a01"))
TURN = UUID("00000000-0000-0000-0000-000000000a02")
WS = "ws-final"
REF = ArtifactRef(
    workspace_id=WS, artifact_key=f"{WS}/{'a' * 64}", sha256="a" * 64, media_type="x", byte_count=1
)


class _Identity:
    execution_id = EXECUTION
    workspace_id = WS


class _Backend:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def snapshot_outputs(self, *, reopen_after: bool = False) -> tuple[ArtifactRef, ...]:
        self._calls.append("snapshot_outputs")
        return ()


class _Lease:
    def __init__(self, calls: list[str], save_status: str | Exception) -> None:
        self.identity = _Identity()
        self.backend = _Backend(calls)
        self._calls = calls
        self._save_status = save_status

    def usage_snapshot(self) -> object:
        return object()

    async def save_snapshot(self) -> SaveReport:
        self._calls.append("save_snapshot")
        if isinstance(self._save_status, Exception):
            raise self._save_status
        return SaveReport(
            status=self._save_status,  # type: ignore[arg-type]
            uploaded=0,
            bytes=0,
            version=1,
            duration_ms=0,
        )


class _Artifacts:
    async def read(self, ref: ArtifactRef) -> bytes:
        return b""

    async def persist_body(self, **_: Any) -> ArtifactRef:
        return REF


class _Turns:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def record_workspace_usage(self, **_: Any) -> None:
        return None

    async def record_finalization(self, **_: Any) -> None:
        self._calls.append("record_finalization")

    async def commit_finalization_authority(self, **_: Any) -> None:
        self._calls.append("commit")


class _Result:
    def mappings(self) -> _Result:
        return self

    def one_or_none(self) -> None:
        return None


class _Conn:
    async def execute(self, *_: Any, **__: Any) -> _Result:
        return _Result()


@asynccontextmanager
async def _conn() -> AsyncIterator[_Conn]:
    yield _Conn()


async def _no_crash(*_: Any, **__: Any) -> None:
    return None


def _finalize(lease: _Lease, calls: list[str]) -> ArtifactRef:
    authority = AgentFinalizationAuthority(
        lease=lease,  # type: ignore[arg-type]
        artifacts=_Artifacts(),  # type: ignore[arg-type]
        turns=_Turns(calls),  # type: ignore[arg-type]
        crash_hook=_no_crash,
        conn_factory=_conn,  # type: ignore[arg-type]
    )
    envelope = AgentFinalizeEnvelope(
        finalization_id=UUID("00000000-0000-0000-0000-000000000a03"),
        execution_id=EXECUTION,
        status=FinalizeStatus.COMPLETED,
        user_message_artifact_ref=REF,
        output_refs=(),
        finalized_at=datetime(2026, 10, 22, tzinfo=UTC),
    )
    return asyncio.run(authority.finalize(turn_id=TURN, workspace_id=WS, envelope=envelope))


def test_finalize_saves_after_outputs_and_before_commit() -> None:
    calls: list[str] = []
    assert _finalize(_Lease(calls, "saved"), calls) == REF
    assert calls.index("snapshot_outputs") < calls.index("save_snapshot") < calls.index("commit")


@pytest.mark.parametrize("status", ["stale", "fenced"])
def test_finalize_refuses_to_commit_a_turn_whose_save_lost(status: str) -> None:
    calls: list[str] = []
    with pytest.raises(WorkspaceConflict):
        _finalize(_Lease(calls, status), calls)
    assert "commit" not in calls


def test_finalize_fails_without_commit_when_storage_is_unreachable() -> None:
    calls: list[str] = []
    with pytest.raises(WorkspaceSaveUnavailable):
        _finalize(_Lease(calls, WorkspaceSaveUnavailable("down")), calls)
    assert "commit" not in calls


def test_an_unchanged_save_commits() -> None:
    calls: list[str] = []
    assert _finalize(_Lease(calls, "unchanged"), calls) == REF
    assert "commit" in calls
