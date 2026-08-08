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
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clue_api.auth_tool_context import tool_context_for_principal
from clue_api.auth_wiring import principal_from_request
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
    IngestionTarget,
    MaterialContext,
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


class DeclaredMaterialInput(BaseModel):
    """The caller-authored part of a declared material context: what the document *is*.

    The domain model (:class:`~clue_research.ingestion.DeclaredMaterialContext`) also carries
    ``brand_id``/``project_id``, which are :data:`~clue_agents.contracts.
    MODEL_FORBIDDEN_AUTHORITY_KEYS` — this execution's brand and project. The strip/inject seam is
    top-level only, so while they lived here the model both saw and authored them (PC-C8 task 1.4).
    They are hoisted onto :class:`SubmitIngestionInput` instead, where the existing seam hides and
    serves them; this model is the remainder, and the domain context is rejoined engine-side by
    :meth:`for_execution`. The durable idempotency key is unchanged — it hashes the *composed*
    domain context, whose shape and values are the same as before.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    product_id: str | None = None
    targets: tuple[IngestionTarget, ...] = ()
    document_context: MaterialContext = MaterialContext.UNKNOWN

    def for_execution(
        self,
        *,
        brand_id: str,
        project_id: str | None,
    ) -> DeclaredMaterialContext:
        return DeclaredMaterialContext(
            brand_id=brand_id,
            project_id=project_id,
            product_id=self.product_id,
            targets=self.targets,
            document_context=self.document_context,
        )

    @classmethod
    def of(cls, context: DeclaredMaterialContext) -> DeclaredMaterialInput:
        """Split a domain context back into its caller-authored part (the upload transport)."""

        return cls(
            product_id=context.product_id,
            targets=context.targets,
            document_context=context.document_context,
        )


class SubmitIngestionInput(ToolInput):
    artifact_key: str
    brand_id: str = Field(
        description="Trusted brand authority; supplied by the platform, never by you."
    )
    declared_context: DeclaredMaterialInput
    project_id: str | None = Field(
        default=None,
        description="Trusted project authority; supplied by the platform, never by you.",
    )


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
    # `brand_id`/`project_id` are deliberately absent since PC-C8 task 1.4 hoisted them out of
    # `declared_context`: a journal display summarises what the *caller* chose, and trusted scope
    # authority is not chosen — it is injected from the constitution. The durable receipt still
    # carries both in the full validated body (and in the declared-context hash), so nothing about
    # the audit trail narrowed; only the display stopped implying the caller picked them.
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
        try:
            inputs.declared_context.for_execution(
                brand_id=inputs.brand_id,
                project_id=inputs.project_id,
            )
        except ValidationError:
            # The domain context's own route rules (project_instruction needs a project,
            # client_about_product needs a product) now bind across the hoisted authority and the
            # declared remainder, so they are reported as a typed refusal here rather than as a
            # bare validation error thrown from the middle of a spend path.
            return (
                PreconditionFailure(
                    reason_code="ingestion_context_invalid",
                    message=(
                        "declared material context is not valid for this execution's "
                        "brand and project"
                    ),
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
            context=inputs.declared_context.for_execution(
                brand_id=inputs.brand_id,
                project_id=inputs.project_id,
            ),
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
            principal = principal_from_request(request)
            if principal is not None:
                principal.require("thread.write")
            artifact_key = await capture_upload(
                content=content,
                media_type=media_type,
                workspace_id=workspace_id,
                storage=storage,
                conn_factory=conn_factory,
                policy=policy,
            )
            operation_id = (
                operation_id_from_key(
                    workspace_id,
                    f"tool:submit_ingestion:{idempotency_key}",
                )
                if idempotency_key is not None
                else new_operation_id()
            )
            tool_context = (
                tool_context_for_principal(
                    principal,
                    conn_factory=conn_factory,
                    operation_id=operation_id,
                )
                if principal is not None
                else ToolContext(
                    workspace_id=workspace_id,
                    actor=actor,
                    conn_factory=conn_factory,
                    operation_id=operation_id,
                )
            )
            return await tool_invoker.invoke(
                "submit_ingestion",
                {
                    "artifact_key": artifact_key,
                    # The upload transport still speaks the whole domain context (the header
                    # contract is unchanged for the human boundary); the tool input splits its
                    # trusted scope authority from its declared remainder.
                    "brand_id": context.brand_id,
                    "project_id": context.project_id,
                    "declared_context": DeclaredMaterialInput.of(context).model_dump(mode="json"),
                },
                tool_context,
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
    "DeclaredMaterialInput",
    "RetryIngestionInput",
    "RetryIngestionTool",
    "SubmitIngestionInput",
    "SubmitIngestionTool",
    "build_ingestion_router",
    "capture_upload",
    "header_actor_resolver",
    "header_workspace_resolver",
]
