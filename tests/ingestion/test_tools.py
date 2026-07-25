from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from clue_api.ingestion_tools import (
    RetryIngestionInput,
    RetryIngestionTool,
    SubmitIngestionInput,
    SubmitIngestionTool,
    capture_upload,
)
from clue_config.ingestion import IngestionPolicy
from clue_core import new_operation_id
from clue_core.ingestion import IngestionJobId, IngestionJobRef, IngestionStatus
from clue_research.ingestion import DeclaredMaterialContext
from clue_research.ingestion.models import IngestionJob
from clue_toolbelt import ToolContext
from tests.db.conftest import run_async


@asynccontextmanager
async def _unused_conn():
    raise AssertionError("database access was not expected")
    yield  # pragma: no cover


class _Engine:
    def __init__(self, status: IngestionStatus = IngestionStatus.COMPLETED) -> None:
        self.ref = IngestionJobRef(
            ingestion_job_id=IngestionJobId(uuid4()),
            artifact_key="ws/hash",
            status=status,
        )

    async def submit(self, **kwargs):
        return self.ref

    async def retry(self, **kwargs):
        return self.ref

    async def status(self, **kwargs):
        now = datetime.now(UTC)
        return IngestionJob(
            id=self.ref.ingestion_job_id,
            workspace_id="ws",
            brand_id="brand",
            artifact_key=self.ref.artifact_key,
            content_sha256="a" * 64,
            declared_context=DeclaredMaterialContext(brand_id="brand"),
            declared_context_hash="b" * 64,
            media_type="text/plain",
            adapter_key="text",
            status=self.ref.status,
            retry_count=2,
            created_by_actor="human",
            created_at=now,
            updated_at=now,
        )


def _ctx() -> ToolContext:
    return ToolContext(
        workspace_id="ws",
        actor="human",
        conn_factory=_unused_conn,
        operation_id=new_operation_id(),
    )


def test_submit_tool_returns_only_frozen_references() -> None:
    engine = _Engine()
    tool = SubmitIngestionTool(engine)  # type: ignore[arg-type]
    result = run_async(
        tool.invoke(
            SubmitIngestionInput(
                artifact_key="ws/hash",
                declared_context=DeclaredMaterialContext(brand_id="brand"),
            ),
            _ctx(),
        )
    )
    assert result.references == {
        "ingestion_job_id": str(engine.ref.ingestion_job_id),
        "artifact_key": "ws/hash",
        "status": "completed",
    }


def test_submit_tool_preconditions_hide_foreign_artifacts(monkeypatch) -> None:
    async def foreign(_conn, _key):
        return SimpleNamespace(workspace_id="other", erased_at=None)

    @asynccontextmanager
    async def stub_conn():
        yield object()

    monkeypatch.setattr("clue_api.ingestion_tools.get_artifact", foreign)
    tool = SubmitIngestionTool(_Engine())  # type: ignore[arg-type]
    failures = run_async(
        tool.preconditions(
            SubmitIngestionInput(
                artifact_key="other/hash",
                declared_context=DeclaredMaterialContext(brand_id="brand"),
            ),
            ToolContext(
                workspace_id="ws",
                actor="human",
                conn_factory=stub_conn,
                operation_id=new_operation_id(),
            ),
        )
    )
    assert tuple(failure.reason_code for failure in failures) == ("ingestion_artifact_not_found",)


def test_retry_tool_reports_durable_retry_count() -> None:
    engine = _Engine(IngestionStatus.FAILED)
    tool = RetryIngestionTool(engine)  # type: ignore[arg-type]
    inputs = RetryIngestionInput(ingestion_job_id=str(engine.ref.ingestion_job_id))
    assert run_async(tool.preconditions(inputs, _ctx())) == ()
    result = run_async(tool.invoke(inputs, _ctx()))
    assert result.references["retry_count"] == 2


def test_capture_rejects_size_and_type_before_storage_or_db() -> None:
    class _Storage:
        pass

    policy = IngestionPolicy(max_bytes=1, allowed_media_types=frozenset({"text/plain"}))
    with pytest.raises(ValueError, match="byte limit"):
        run_async(
            capture_upload(
                content=b"xx",
                media_type="text/plain",
                workspace_id="ws",
                storage=_Storage(),  # type: ignore[arg-type]
                conn_factory=_unused_conn,
                policy=policy,
            )
        )
    with pytest.raises(ValueError, match="not allowed"):
        run_async(
            capture_upload(
                content=b"x",
                media_type="application/octet-stream",
                workspace_id="ws",
                storage=_Storage(),  # type: ignore[arg-type]
                conn_factory=_unused_conn,
                policy=policy,
            )
        )
