"""C3 lane-specific tools and upload transport.

Central registration is intentionally absent: the C0 treaty assigns that one-line composition to
the Phase-C integration branch.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from clue_api.tool_outputs import IngestionRetryOutput, IngestionSubmitOutput
from clue_config.ingestion import DEFAULT_INGESTION_POLICY, IngestionPolicy
from clue_core import RawArtifact, new_operation_id, operation_id_from_key
from clue_core.ingestion import IngestionJobId
from clue_db import ConnFactory, transaction
from clue_execution import OperationConflict
from clue_research.ingestion import (
    DeclaredMaterialContext,
    IngestionEngine,
    IngestionError,
    get_job,
)
from clue_storage import SnapshotSink, StorageBackend, flush_snapshots, get_artifact
from clue_toolbelt import (
    Actor,
    ExternalReplayBoundary,
    IdempotencyConflict,
    JournalParameterPolicy,
    PreconditionFailed,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolInvoker,
    ToolResult,
)

WorkspaceHeader = Annotated[str | None, Header(alias="X-Workspace-Id")]
ActorHeader = Annotated[str | None, Header(alias="X-Actor")]


def header_workspace_resolver(x_workspace_id: WorkspaceHeader = None) -> str:
    """Default tenant seam; production replaces it with authenticated workspace resolution."""
    if not x_workspace_id:
        raise HTTPException(status_code=401, detail="missing X-Workspace-Id (tenant) header")
    return x_workspace_id


def header_actor_resolver(x_actor: ActorHeader = None) -> Actor:
    if x_actor is None or x_actor == "human":
        return "human"
    if x_actor == "agent":
        return "agent"
    raise HTTPException(status_code=422, detail="X-Actor must be 'human' or 'agent'")


WorkspaceDep = Annotated[str, Depends(header_workspace_resolver)]
ActorDep = Annotated[Actor, Depends(header_actor_resolver)]


class SubmitIngestionInput(ToolInput):
    artifact_key: str
    declared_context: DeclaredMaterialContext


class RetryIngestionInput(ToolInput):
    ingestion_job_id: str


def _job_id(raw: str) -> IngestionJobId | None:
    try:
        return IngestionJobId(UUID(raw))
    except (TypeError, ValueError, AttributeError):
        return None


class SubmitIngestionTool(Tool):
    """Reason codes: ``ingestion_artifact_not_found``, ``ingestion_artifact_erased``."""

    name = "submit_ingestion"
    version = "1"
    input_model = SubmitIngestionInput
    output_model = IngestionSubmitOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.AT_LEAST_ONCE,
        durable_identity=("workspace + artifact content hash + declared material-context hash"),
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("artifact_key", "declared_context")
    )
    pin_requirements = ("artifact_input", "ingestion_policy", "brand")

    def __init__(self, engine: IngestionEngine | None) -> None:
        self._engine = engine

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SubmitIngestionInput)
        async with ctx.conn_factory() as conn:
            artifact = await get_artifact(conn, inputs.artifact_key)
        if artifact is None or artifact.workspace_id != ctx.workspace_id:
            return (
                PreconditionFailure(
                    reason_code="ingestion_artifact_not_found",
                    message="captured artifact does not exist in this workspace",
                ),
            )
        if artifact.erased_at is not None:
            return (
                PreconditionFailure(
                    reason_code="ingestion_artifact_erased",
                    message="captured artifact has been erased; upload it again before ingestion",
                ),
            )
        if self._engine is None:
            return (
                PreconditionFailure(
                    reason_code="ingestion_not_configured",
                    message="the ingestion engine is not configured at the API composition root",
                ),
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, SubmitIngestionInput)
        if self._engine is None:
            raise RuntimeError("submit_ingestion invoked without a configured ingestion engine")
        ref = await self._engine.submit(
            workspace_id=ctx.workspace_id,
            artifact_key=inputs.artifact_key,
            context=inputs.declared_context,
            actor=ctx.actor,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "ingestion_job_id": str(ref.ingestion_job_id),
                "artifact_key": ref.artifact_key,
                "status": ref.status.value,
            },
        )


class RetryIngestionTool(Tool):
    name = "retry_ingestion"
    version = "1"
    input_model = RetryIngestionInput
    output_model = IngestionRetryOutput

    def __init__(self, engine: IngestionEngine | None) -> None:
        self._engine = engine

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RetryIngestionInput)
        job_id = _job_id(inputs.ingestion_job_id)
        if job_id is None:
            return (
                PreconditionFailure(
                    reason_code="ingestion_not_found",
                    message="ingestion job does not exist in this workspace",
                ),
            )
        if self._engine is None:
            async with ctx.conn_factory() as conn:
                job = await get_job(conn, job_id, workspace_id=ctx.workspace_id)
        else:
            job = await self._engine.status(workspace_id=ctx.workspace_id, job_id=job_id)
        if job is None:
            return (
                PreconditionFailure(
                    reason_code="ingestion_not_found",
                    message="ingestion job does not exist in this workspace",
                ),
            )
        if self._engine is None:
            return (
                PreconditionFailure(
                    reason_code="ingestion_not_configured",
                    message="the ingestion engine is not configured at the API composition root",
                ),
            )
        if job.status.value not in {"failed", "snapshotted", "extracting"}:
            return (
                PreconditionFailure(
                    reason_code="ingestion_not_retryable",
                    message=f"ingestion job in status {job.status.value!r} is not retryable",
                ),
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RetryIngestionInput)
        if self._engine is None:
            raise RuntimeError("retry_ingestion invoked without a configured ingestion engine")
        job_id = _job_id(inputs.ingestion_job_id)
        assert job_id is not None
        ref = await self._engine.retry(workspace_id=ctx.workspace_id, job_id=job_id)
        assert ref is not None
        job = await self._engine.status(workspace_id=ctx.workspace_id, job_id=job_id)
        assert job is not None
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "ingestion_job_id": str(ref.ingestion_job_id),
                "status": ref.status.value,
                "retry_count": job.retry_count,
            },
        )


async def capture_upload(
    *,
    content: bytes,
    media_type: str,
    workspace_id: str,
    storage: StorageBackend,
    conn_factory: ConnFactory = transaction,
    policy: IngestionPolicy = DEFAULT_INGESTION_POLICY,
) -> str:
    """Capture bytes before any extraction and return the content-addressed artifact key."""
    if len(content) > policy.max_bytes:
        raise ValueError("upload exceeds configured byte limit")
    if media_type not in policy.allowed_media_types:
        raise ValueError("upload media type is not allowed")
    sink = SnapshotSink(workspace_id=workspace_id)
    key = sink.capture(
        RawArtifact(ref="upload", media_type=media_type, content=content),
        source_key="client_upload",
    )
    async with conn_factory() as conn:
        await flush_snapshots(conn, storage, sink)
    return key


async def _read_upload_body(request: Request, *, max_bytes: int) -> bytes:
    """Stream with a ceiling so a missing/false Content-Length cannot force an unbounded read."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail="upload exceeds configured limit")
        chunks.append(chunk)
    return b"".join(chunks)


def build_ingestion_router(
    *,
    tool_invoker: ToolInvoker,
    storage: StorageBackend,
    conn_factory: ConnFactory = transaction,
    policy: IngestionPolicy = DEFAULT_INGESTION_POLICY,
) -> APIRouter:
    """Build the raw-byte upload route; callers include it at the API composition root."""
    router = APIRouter(prefix="/ingestion", tags=["ingestion"])

    @router.post("/uploads")
    async def upload(
        request: Request,
        workspace_id: WorkspaceDep,
        actor: ActorDep,
        context_json: Annotated[str, Header(alias="X-Ingestion-Context")] = "{}",
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ToolResult:
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type not in policy.allowed_media_types:
            raise HTTPException(status_code=415, detail="upload media type is not allowed")
        # Reject from Content-Length before reading the body when possible; the post-read check in
        # capture_upload remains the authoritative ceiling for missing/lying headers.
        length = request.headers.get("content-length")
        if length is not None:
            try:
                parsed_length = int(length)
                if parsed_length < 0:
                    raise ValueError
                if parsed_length > policy.max_bytes:
                    raise HTTPException(status_code=413, detail="upload exceeds configured limit")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="invalid Content-Length") from exc
        try:
            context = DeclaredMaterialContext.model_validate(json.loads(context_json))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail="invalid X-Ingestion-Context") from exc
        content = await _read_upload_body(request, max_bytes=policy.max_bytes)
        try:
            artifact_key = await capture_upload(
                content=content,
                media_type=media_type,
                workspace_id=workspace_id,
                storage=storage,
                conn_factory=conn_factory,
                policy=policy,
            )
            return await tool_invoker.invoke(
                "submit_ingestion",
                {
                    "artifact_key": artifact_key,
                    "declared_context": context.model_dump(mode="json"),
                },
                ToolContext(
                    workspace_id=workspace_id,
                    actor=actor,
                    conn_factory=conn_factory,
                    operation_id=(
                        operation_id_from_key(
                            workspace_id,
                            f"tool:submit_ingestion:{idempotency_key}",
                        )
                        if idempotency_key is not None
                        else new_operation_id()
                    ),
                ),
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except IngestionError as exc:
            raise HTTPException(
                status_code=422, detail={"error": exc.code.value, "message": exc.detail}
            ) from exc
        except PreconditionFailed as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "precondition_failed",
                    "reason_codes": list(exc.reason_codes),
                    "failures": [
                        {"reason_code": failure.reason_code, "message": failure.message}
                        for failure in exc.failures
                    ],
                },
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "idempotency_conflict", "reason": exc.reason, "key": exc.key},
            ) from exc
        except OperationConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "idempotency_conflict", "reason": "operation"},
            ) from exc

    return router


__all__ = [
    "RetryIngestionInput",
    "RetryIngestionTool",
    "SubmitIngestionInput",
    "SubmitIngestionTool",
    "build_ingestion_router",
    "capture_upload",
    "header_actor_resolver",
    "header_workspace_resolver",
]
