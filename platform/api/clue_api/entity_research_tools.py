"""M8D R4 governed entity-research semantic tools and lossless result projection.

The model chooses a semantic tool, fields, sources, and confirmed questions.  This module injects
all execution authority from the active R3 tool context, journals the provider-neutral request,
binds any new provider operation before dispatch, and persists a complete result projection before
returning it to the agent.  Provider adapters remain behind :class:`EntityResearchProviderAction`;
neither their SDKs nor scope identifiers appear in model-facing schemas.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Protocol, Self, cast, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.entity_research_contracts import (
    EntityResearchToolBinding,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    ActiveEntityResearchToolExecution,
    current_entity_research_tool_execution,
)
from clue_agents.entity_research_tools import (
    EntityResearchSemanticToolInput,
    ReadResearchEvidenceInput,
    ReadResearchResultInput,
)
from clue_core import EntityId, ExternalResearchOperationId, serialize_value_json
from clue_core.entity_research import (
    EntityAgentToolSurface,
    GovernedResearchToolRequest,
    PersistedResearchToolResult,
    ProviderOperationCausation,
    ResearchClaimDelta,
    ResearchFieldOutcome,
    ResearchFieldResultProjection,
    ResearchFollowUpReason,
    ResearchResultDelivery,
    ResearchSubjectType,
)
from clue_research.durable.discovery import (
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
)
from clue_research.durable.external_research import ExternalResearchOperationRow
from clue_storage import StorageBackend, content_address, read_verified_artifact

NonEmptyStr = Annotated[str, Field(min_length=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

_TOOL_REQUEST_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r4:tool-request")
_RESULT_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r4:research-result")
_PROVIDER_CAPABLE_TOOL_NAMES = frozenset(
    {
        "research_account_deep",
        "enrich_account",
        "discover_buying_committee",
        "research_contact_deep",
        "enrich_contact",
        "reveal_contact_channel",
        "validate_contact_channel",
    }
)


class EntityResearchToolAuthorityError(RuntimeError):
    """A semantic request, provider operation, claim, or read crosses exact job authority."""


class EntityResearchResultIntegrityError(RuntimeError):
    """Persisted research data does not reconstruct one complete grounded result."""


class ProviderOperationObservation(BaseModel):
    """One tool's relation to an operation; only ``caused`` is provider-spend causation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: UUID
    tool_request_id: UUID
    operation_id: UUID
    workspace_id: NonEmptyStr
    disposition: str
    created_at: datetime


class ExternalResearchProjectionDraft(BaseModel):
    """Claim-engine output awaiting R4 relational/artifact integrity validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: UUID
    snapshot_id: UUID
    requested_field_keys: tuple[NonEmptyStr, ...] = Field(min_length=1)
    fields: tuple[ResearchFieldResultProjection, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _complete_index(self) -> Self:
        returned = tuple(field.field_key for field in self.fields)
        if len(returned) != len(set(returned)) or set(returned) != set(self.requested_field_keys):
            raise ValueError("projection draft must cover each requested field exactly once")
        return self


class EntityResearchToolResultBatch(BaseModel):
    """One semantic call may compile into several provider-safe schema bundles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_request_ref: NonEmptyStr
    results: tuple[PersistedResearchToolResult, ...] = Field(min_length=1)


class ResearchEvidenceReadPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_ref: NonEmptyStr
    artifact_ref: NonEmptyStr
    offset: int = Field(ge=0)
    next_offset: int = Field(ge=0)
    complete: bool
    content: str
    content_sha256: Sha256


@runtime_checkable
class EntityResearchProviderAction(Protocol):
    """Provider-neutral semantic action implemented through reusable acquisition/claim services."""

    async def execute(
        self,
        request: GovernedResearchToolRequest,
        *,
        before_dispatch: Callable[[ExternalResearchOperationRow], Awaitable[None]],
    ) -> Sequence[ExternalResearchProjectionDraft]: ...


class ProviderActionBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    action: EntityResearchProviderAction
    version: int = Field(ge=1)


def _event_id(reference: str) -> UUID:
    prefix = "entity-agent-event:"
    if not reference.startswith(prefix):
        raise EntityResearchToolAuthorityError("tool journal returned an unknown event reference")
    try:
        return UUID(reference.removeprefix(prefix))
    except ValueError as exc:
        raise EntityResearchToolAuthorityError("tool journal event reference is malformed") from exc


def _prefixed_uuid(reference: str, prefix: str) -> UUID:
    if not reference.startswith(prefix):
        raise EntityResearchResultIntegrityError(f"reference {reference!r} has the wrong type")
    try:
        return UUID(reference.removeprefix(prefix))
    except ValueError as exc:
        raise EntityResearchResultIntegrityError(f"reference {reference!r} is malformed") from exc


def _artifact_key(reference: str) -> str:
    if not reference.startswith("artifact:"):
        raise EntityResearchResultIntegrityError("artifact reference uses an unknown scheme")
    value = reference.removeprefix("artifact:")
    if not value:
        raise EntityResearchResultIntegrityError("artifact reference is empty")
    return value


def _claim_id(reference: str) -> UUID:
    value = reference.removeprefix("claim:")
    try:
        return UUID(value)
    except ValueError as exc:
        raise EntityResearchResultIntegrityError(
            f"claim reference {reference!r} is malformed"
        ) from exc


def _canonical_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_contains_text(data: bytes, span: str) -> bool:
    try:
        decoded = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return span in data.decode("utf-8", errors="replace")

    def contains(value: object) -> bool:
        if isinstance(value, str):
            return span in value
        if isinstance(value, list):
            return any(contains(item) for item in value)
        if isinstance(value, dict):
            return any(contains(item) for item in value.values())
        return False

    return contains(decoded)


class EntityResearchToolRequestStore:
    """Project an admitted R3 call into the immutable R0 governed request contract."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def record(
        self,
        *,
        active: ActiveEntityResearchToolExecution,
        semantic: EntityResearchSemanticToolInput,
    ) -> GovernedResearchToolRequest:
        context = active.context
        authorization = context.authorization
        selection = authorization.selection
        if not set(semantic.field_keys).issubset(selection.admitted_field_keys):
            raise EntityResearchToolAuthorityError("semantic tool widened selected fields")
        if not set(semantic.source_keys).issubset(selection.admitted_source_keys):
            raise EntityResearchToolAuthorityError("semantic tool widened selected sources")
        if not set(semantic.questions).issubset(selection.research_questions):
            raise EntityResearchToolAuthorityError("semantic tool widened confirmed questions")
        if active.call.tool_name not in context.tool_surface.tool_names:
            raise EntityResearchToolAuthorityError("semantic tool is outside the exact surface")

        tool_request_id = uuid5(
            _TOOL_REQUEST_NAMESPACE,
            f"{context.agent_turn_id}:{active.call.tool_call_id}",
        )
        request = GovernedResearchToolRequest(
            research_run_id=authorization.research_run_id,
            job_id=authorization.job_id,
            subject_type=authorization.subject_type,
            target_entity_id=authorization.subject_entity_id,
            parent_account_id=authorization.parent_account_id,
            agent_turn_id=context.agent_turn_id,
            agent_execution_id=context.agent_execution_id,
            tool_call_id=tool_request_id,
            tool_name=active.call.tool_name,
            tool_version=active.call.tool_version,
            tool_input_sha256=active.call.tool_input_sha256,
            field_plan_ref=selection.field_plan_ref,
            source_plan_ref=selection.source_plan_ref,
            field_keys=semantic.field_keys,
            source_keys=semantic.source_keys,
            questions=semantic.questions,
            budget_reservation_key=(
                f"{selection.budget_envelope_ref}:job:{authorization.job_id}:tool:{tool_request_id}"
            ),
            idempotency_key=canonical_sha256(
                {
                    "contract": "m8d-r4-governed-tool-v1",
                    "agent_turn_id": str(context.agent_turn_id),
                    "tool_call_id": active.call.tool_call_id,
                    "tool_name": active.call.tool_name,
                    "tool_version": active.call.tool_version,
                    "tool_input_sha256": active.call.tool_input_sha256,
                    "target_entity_id": str(authorization.subject_entity_id),
                }
            ),
            parent_operation_ref=semantic.parent_operation_ref,
            parent_observation_ref=semantic.parent_observation_ref,
            follow_up_reason=semantic.follow_up_reason,
        )
        event_id = _event_id(active.journal_event_ref)
        values = {
            "tool_request_id": request.tool_call_id,
            "agent_turn_id": request.agent_turn_id,
            "agent_execution_id": request.agent_execution_id,
            "tool_event_id": event_id,
            "raw_tool_call_id": active.call.tool_call_id,
            "research_run_id": request.research_run_id,
            "job_id": request.job_id,
            "subject_type": request.subject_type.value,
            "target_entity_id": request.target_entity_id,
            "parent_account_id": request.parent_account_id,
            "workspace_id": authorization.workspace_id,
            "project_id": authorization.project_id,
            "product_id": authorization.product_id,
            "project_run_id": authorization.project_run_id,
            "tool_name": request.tool_name,
            "tool_version": request.tool_version,
            "tool_input_sha256": request.tool_input_sha256,
            "field_plan_ref": request.field_plan_ref,
            "source_plan_ref": request.source_plan_ref,
            "field_keys": list(request.field_keys),
            "source_keys": list(request.source_keys),
            "questions": list(request.questions),
            "budget_reservation_key": request.budget_reservation_key,
            "idempotency_key": request.idempotency_key,
            "parent_operation_ref": request.parent_operation_ref,
            "parent_observation_ref": request.parent_observation_ref,
            "follow_up_reason": (
                request.follow_up_reason.value if request.follow_up_reason is not None else None
            ),
        }
        async with self._conn_factory() as conn:
            if request.parent_operation_ref is not None:
                parent_operation_id = _prefixed_uuid(
                    request.parent_operation_ref,
                    "external-research-operation:",
                )
                parent_result_id = _prefixed_uuid(
                    cast(str, request.parent_observation_ref),
                    "research-result:",
                )
                parent_exists = (
                    await conn.execute(
                        text(
                            """
                            SELECT 1
                            FROM entity_research_result parent_result
                            JOIN entity_research_tool_request parent_request
                              ON parent_request.tool_request_id=parent_result.tool_request_id
                            WHERE parent_result.result_id=:parent_result_id
                              AND parent_result.operation_id=:parent_operation_id
                              AND parent_request.research_run_id=:research_run_id
                              AND parent_request.job_id=:job_id
                              AND parent_request.subject_type=:subject_type
                              AND parent_request.target_entity_id=:target_entity_id
                              AND parent_request.workspace_id=:workspace_id
                            """
                        ),
                        {
                            "parent_result_id": parent_result_id,
                            "parent_operation_id": parent_operation_id,
                            "research_run_id": request.research_run_id,
                            "job_id": request.job_id,
                            "subject_type": request.subject_type.value,
                            "target_entity_id": request.target_entity_id,
                            "workspace_id": authorization.workspace_id,
                        },
                    )
                ).scalar_one_or_none()
                if parent_exists is None:
                    raise EntityResearchToolAuthorityError(
                        "follow-up parent observation is outside the exact job"
                    )
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_tool_request
                        (tool_request_id, agent_turn_id, agent_execution_id, tool_event_id,
                         raw_tool_call_id, research_run_id, job_id, subject_type,
                         target_entity_id, parent_account_id, workspace_id, project_id,
                         product_id, project_run_id, tool_name, tool_version,
                         tool_input_sha256, field_plan_ref, source_plan_ref, field_keys,
                         source_keys, questions, budget_reservation_key, idempotency_key,
                         parent_operation_ref, parent_observation_ref, follow_up_reason)
                    VALUES
                        (:tool_request_id, :agent_turn_id, :agent_execution_id, :tool_event_id,
                         :raw_tool_call_id, :research_run_id, :job_id, :subject_type,
                         :target_entity_id, :parent_account_id, :workspace_id, :project_id,
                         :product_id, :project_run_id, :tool_name, :tool_version,
                         :tool_input_sha256, :field_plan_ref, :source_plan_ref, :field_keys,
                         :source_keys, :questions, :budget_reservation_key, :idempotency_key,
                         :parent_operation_ref, :parent_observation_ref, :follow_up_reason)
                    ON CONFLICT (tool_request_id) DO NOTHING
                    """
                ),
                values,
            )
            observed = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT agent_turn_id, agent_execution_id, tool_event_id,
                                   raw_tool_call_id, research_run_id, job_id, subject_type,
                                   target_entity_id, parent_account_id, workspace_id, project_id,
                                   product_id, project_run_id, tool_name, tool_version,
                                   tool_input_sha256, field_plan_ref, source_plan_ref, field_keys,
                                   source_keys, questions, budget_reservation_key, idempotency_key,
                                   parent_operation_ref, parent_observation_ref, follow_up_reason
                            FROM entity_research_tool_request
                            WHERE tool_request_id=:tool_request_id
                            """
                        ),
                        {"tool_request_id": request.tool_call_id},
                    )
                )
                .mappings()
                .one()
            )
        comparable = {
            key: values[key]
            for key in (
                "agent_turn_id",
                "agent_execution_id",
                "tool_event_id",
                "raw_tool_call_id",
                "research_run_id",
                "job_id",
                "subject_type",
                "target_entity_id",
                "parent_account_id",
                "workspace_id",
                "project_id",
                "product_id",
                "project_run_id",
                "tool_name",
                "tool_version",
                "tool_input_sha256",
                "field_plan_ref",
                "source_plan_ref",
                "field_keys",
                "source_keys",
                "questions",
                "budget_reservation_key",
                "idempotency_key",
                "parent_operation_ref",
                "parent_observation_ref",
                "follow_up_reason",
            )
        }
        normalized = dict(observed)
        for key in ("field_keys", "source_keys", "questions"):
            normalized[key] = list(normalized[key])
        if normalized != comparable:
            raise EntityResearchToolAuthorityError(
                "tool request id replayed with different immutable authority"
            )
        return request


class EntityResearchProviderCausationStore:
    """Bind causes before dispatch and distinguish later replay/join observations."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def get_operation(self, operation_id: UUID) -> ExternalResearchOperationRow:
        from clue_research.durable.external_research import get_external_research_operation

        async with self._conn_factory() as conn:
            workspace_id = (
                await conn.execute(
                    text("SELECT workspace_id FROM external_research_operation WHERE id=:id"),
                    {"id": operation_id},
                )
            ).scalar_one_or_none()
            if workspace_id is None:
                raise EntityResearchResultIntegrityError(
                    "provider action named an absent operation"
                )
            return await get_external_research_operation(
                conn,
                workspace_id=str(workspace_id),
                operation_id=ExternalResearchOperationId(operation_id),
            )

    async def bind_before_dispatch(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: ExternalResearchOperationRow,
    ) -> ProviderOperationObservation:
        # More than one admitted tool call can reserve the same stable operation before the
        # first dispatcher settles it. Exactly one call caused that operation; later callers are
        # resumptions/joins and must not trip the partial unique cause index or steal causation.
        # An unqualified conflict handler covers both the per-request observation key and the
        # partial one-cause-per-operation index. If a prior callback crashed before inserting,
        # this caller becomes the cause; otherwise it receives the already-persisted cause and
        # the action records its own join/replay observation after acquisition resolves.
        observation_id = uuid4()
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT observation_id, tool_request_id, operation_id,
                                   external_workspace_id, disposition, created_at
                            FROM entity_research_provider_observation
                            WHERE operation_id=:operation_id AND disposition='caused'
                            """
                        ),
                        {"operation_id": operation.operation_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is not None:
                return self._row(cast(Mapping[str, object], row))
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO entity_research_provider_observation
                                (observation_id, tool_request_id, operation_id,
                                 external_workspace_id, disposition)
                            VALUES
                                (:observation_id, :tool_request_id, :operation_id,
                                 :workspace_id, 'caused')
                            ON CONFLICT DO NOTHING
                            RETURNING observation_id, tool_request_id, operation_id,
                                      external_workspace_id, disposition, created_at
                            """
                        ),
                        {
                            "observation_id": observation_id,
                            "tool_request_id": request.tool_call_id,
                            "operation_id": operation.operation_id,
                            "workspace_id": operation.workspace_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                row = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT observation_id, tool_request_id, operation_id,
                                       external_workspace_id, disposition, created_at
                                FROM entity_research_provider_observation
                                WHERE operation_id=:operation_id AND disposition='caused'
                                """
                            ),
                            {"operation_id": operation.operation_id},
                        )
                    )
                    .mappings()
                    .one()
                )
        return self._row(cast(Mapping[str, object], row))

    async def observe(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: ExternalResearchOperationRow,
        joined: bool = False,
    ) -> ProviderOperationObservation:
        async with self._conn_factory() as conn:
            own = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT observation_id, tool_request_id, operation_id,
                                   external_workspace_id, disposition, created_at
                            FROM entity_research_provider_observation
                            WHERE tool_request_id=:tool_request_id AND operation_id=:operation_id
                            """
                        ),
                        {
                            "tool_request_id": request.tool_call_id,
                            "operation_id": operation.operation_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
        if own is not None:
            return self._row(cast(Mapping[str, object], own))
        return await self._record(
            request=request,
            operation=operation,
            disposition="joined_observation" if joined else "replay_observation",
        )

    async def _record(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: ExternalResearchOperationRow,
        disposition: str,
    ) -> ProviderOperationObservation:
        observation_id = uuid4()
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO entity_research_provider_observation
                                (observation_id, tool_request_id, operation_id,
                                 external_workspace_id, disposition)
                            VALUES
                                (:observation_id, :tool_request_id, :operation_id,
                                 :workspace_id, :disposition)
                            ON CONFLICT (tool_request_id, operation_id) DO NOTHING
                            RETURNING observation_id, tool_request_id, operation_id,
                                      external_workspace_id, disposition, created_at
                            """
                        ),
                        {
                            "observation_id": observation_id,
                            "tool_request_id": request.tool_call_id,
                            "operation_id": operation.operation_id,
                            "workspace_id": operation.workspace_id,
                            "disposition": disposition,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                row = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT observation_id, tool_request_id, operation_id,
                                       external_workspace_id, disposition, created_at
                                FROM entity_research_provider_observation
                                WHERE tool_request_id=:tool_request_id
                                  AND operation_id=:operation_id
                                """
                            ),
                            {
                                "tool_request_id": request.tool_call_id,
                                "operation_id": operation.operation_id,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
        observed = self._row(cast(Mapping[str, object], row))
        if observed.disposition != disposition:
            raise EntityResearchToolAuthorityError(
                "provider operation observation replay changed its disposition"
            )
        return observed

    @staticmethod
    def _row(row: Mapping[str, object]) -> ProviderOperationObservation:
        return ProviderOperationObservation(
            observation_id=cast(UUID, row["observation_id"]),
            tool_request_id=cast(UUID, row["tool_request_id"]),
            operation_id=cast(UUID, row["operation_id"]),
            workspace_id=str(row["external_workspace_id"]),
            disposition=str(row["disposition"]),
            created_at=cast(datetime, row["created_at"]),
        )

    async def causation_for(self, operation_id: UUID) -> ProviderOperationCausation | None:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT request_row.subject_type, request_row.target_entity_id,
                                   request_row.agent_turn_id, request_row.agent_execution_id,
                                   request_row.tool_request_id, request_row.tool_name,
                                   request_row.tool_version, request_row.tool_input_sha256,
                                   request_row.parent_operation_ref,
                                   request_row.parent_observation_ref,
                                   request_row.follow_up_reason,
                                   turn_row.started_at AS agent_turn_started_at,
                                   event_row.occurred_at AS tool_call_recorded_at,
                                   operation_row.created_at AS provider_operation_reserved_at,
                                   attempt.dispatched_at AS provider_dispatched_at
                            FROM entity_research_provider_observation observation
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=observation.tool_request_id
                            JOIN entity_research_agent_turn turn_row
                              ON turn_row.agent_turn_id=request_row.agent_turn_id
                            JOIN entity_research_agent_event event_row
                              ON event_row.event_id=request_row.tool_event_id
                            JOIN external_research_operation operation_row
                              ON operation_row.id=observation.operation_id
                            JOIN LATERAL (
                                SELECT dispatched_at FROM external_research_attempt
                                WHERE operation_id=operation_row.id AND dispatched_at IS NOT NULL
                                ORDER BY ordinal LIMIT 1
                            ) attempt ON TRUE
                            WHERE observation.operation_id=:operation_id
                              AND observation.disposition='caused'
                            """
                        ),
                        {"operation_id": operation_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return ProviderOperationCausation(
            subject_type=ResearchSubjectType(str(row["subject_type"])),
            target_entity_id=cast(UUID, row["target_entity_id"]),
            provider_operation_ref=f"external-research-operation:{operation_id}",
            agent_turn_id=cast(UUID, row["agent_turn_id"]),
            agent_execution_id=cast(UUID, row["agent_execution_id"]),
            tool_call_id=cast(UUID, row["tool_request_id"]),
            tool_name=str(row["tool_name"]),
            tool_version=int(cast(int, row["tool_version"])),
            tool_input_sha256=str(row["tool_input_sha256"]),
            agent_turn_started_at=cast(datetime, row["agent_turn_started_at"]),
            tool_call_recorded_at=cast(datetime, row["tool_call_recorded_at"]),
            provider_operation_reserved_at=cast(datetime, row["provider_operation_reserved_at"]),
            provider_dispatched_at=cast(datetime, row["provider_dispatched_at"]),
            parent_operation_ref=cast(str | None, row["parent_operation_ref"]),
            parent_observation_ref=cast(str | None, row["parent_observation_ref"]),
            follow_up_reason=(
                ResearchFollowUpReason(str(row["follow_up_reason"]))
                if row["follow_up_reason"] is not None
                else None
            ),
        )


class EntityResearchResultStore:
    """Validate and retain a complete provider/claim projection before exposing it."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: ConnFactory,
        inline_max_bytes: int = 24_000,
    ) -> None:
        if inline_max_bytes < 1:
            raise ValueError("inline result byte cap must be positive")
        self._storage = storage
        self._conn_factory = conn_factory
        self._inline_max_bytes = inline_max_bytes

    async def persist(
        self,
        *,
        request: GovernedResearchToolRequest,
        observation: ProviderOperationObservation,
        draft: ExternalResearchProjectionDraft,
    ) -> PersistedResearchToolResult:
        if observation.tool_request_id != request.tool_call_id:
            raise EntityResearchResultIntegrityError("result observation belongs to another tool")
        if observation.operation_id != draft.operation_id:
            raise EntityResearchResultIntegrityError("result draft belongs to another operation")
        if not set(draft.requested_field_keys).issubset(request.field_keys):
            raise EntityResearchResultIntegrityError("result draft widens governed fields")
        result_id = uuid5(
            _RESULT_NAMESPACE,
            f"{request.tool_call_id}:{draft.operation_id}",
        )
        existing = await self._load_existing(result_id=result_id, request=request)
        if existing is not None:
            return existing

        async with self._conn_factory() as conn:
            lineage = await self._lineage(
                conn,
                request=request,
                operation_id=draft.operation_id,
                snapshot_id=draft.snapshot_id,
            )
            await self._validate_artifacts(conn, request=request, lineage=lineage)
            await self._validate_fields(
                conn,
                request=request,
                draft=draft,
                lineage=lineage,
            )

            fields = draft.fields
            provisional = self._result(
                request=request,
                result_id=result_id,
                lineage=lineage,
                fields=fields,
                delivery=ResearchResultDelivery.INLINE_COMPLETE,
            )
            value_artifacts: dict[str, str] = {}
            if len(_canonical_bytes(provisional)) > self._inline_max_bytes:
                indexed: list[ResearchFieldResultProjection] = []
                for field in fields:
                    if field.outcome is not ResearchFieldOutcome.FOUND:
                        indexed.append(field)
                        continue
                    value_bytes = _canonical_bytes(
                        {"field_key": field.field_key, "value": field.value}
                    )
                    value_key = await capture_discovery_artifact(
                        conn,
                        self._storage,
                        workspace_id=str(lineage["workspace_id"]),
                        content=value_bytes,
                        media_type="application/json",
                        source_key=str(lineage["source_key"]),
                    )
                    value_artifacts[field.field_key] = value_key
                    indexed.append(
                        field.model_copy(
                            update={
                                "value": None,
                                "value_ref": f"research-value:{result_id}:{field.field_key}",
                            }
                        )
                    )
                fields = tuple(indexed)
                result = self._result(
                    request=request,
                    result_id=result_id,
                    lineage=lineage,
                    fields=fields,
                    delivery=ResearchResultDelivery.INDEXED_COMPLETE,
                )
            else:
                result = provisional

            result_bytes = _canonical_bytes(result)
            result_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=str(lineage["workspace_id"]),
                content=result_bytes,
                media_type="application/json",
                source_key=str(lineage["source_key"]),
            )
            result_sha = content_address(result_bytes)
            if not result_key.endswith(result_sha):
                raise EntityResearchResultIntegrityError("result artifact address changed")
            subject_kind = request.subject_type.value
            await bind_discovery_artifact_subject(
                conn,
                workspace_id=str(lineage["workspace_id"]),
                artifact_key_value=result_key,
                subject_kind=subject_kind,
                subject_entity_id=EntityId(request.target_entity_id),
                reference_kind="entity_research_result",
                reference_id=str(result_id),
            )
            for field_key, value_key in value_artifacts.items():
                await bind_discovery_artifact_subject(
                    conn,
                    workspace_id=str(lineage["workspace_id"]),
                    artifact_key_value=value_key,
                    subject_kind=subject_kind,
                    subject_entity_id=EntityId(request.target_entity_id),
                    reference_kind="entity_research_value",
                    reference_id=f"{result_id}:{field_key}",
                )
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_result
                        (result_id, tool_request_id, provider_observation_id, operation_id,
                         snapshot_id, workspace_id, subject_type, target_entity_id,
                         result_artifact_key, result_sha256, delivery, requested_field_keys)
                    VALUES
                        (:result_id, :tool_request_id, :provider_observation_id, :operation_id,
                         :snapshot_id, :workspace_id, :subject_type, :target_entity_id,
                         :result_artifact_key, :result_sha256, :delivery,
                         :requested_field_keys)
                    """
                ),
                {
                    "result_id": result_id,
                    "tool_request_id": request.tool_call_id,
                    "provider_observation_id": observation.observation_id,
                    "operation_id": draft.operation_id,
                    "snapshot_id": draft.snapshot_id,
                    "workspace_id": lineage["workspace_id"],
                    "subject_type": request.subject_type.value,
                    "target_entity_id": request.target_entity_id,
                    "result_artifact_key": result_key,
                    "result_sha256": result_sha,
                    "delivery": result.delivery.value,
                    "requested_field_keys": list(result.requested_field_keys),
                },
            )
            for field_ordinal, field in enumerate(result.fields):
                claim_ids = [_claim_id(ref) for ref in field.claim_refs]
                await conn.execute(
                    text(
                        """
                        INSERT INTO entity_research_result_field
                            (result_id, ordinal, field_key, outcome, claim_delta, claim_refs,
                             decision_refs, value_artifact_key, workspace_id,
                             verification_status)
                        VALUES
                            (:result_id, :ordinal, :field_key, :outcome, :claim_delta,
                             :claim_refs, :decision_refs, :value_artifact_key, :workspace_id,
                             :verification_status)
                        """
                    ),
                    {
                        "result_id": result_id,
                        "ordinal": field_ordinal,
                        "field_key": field.field_key,
                        "outcome": field.outcome.value,
                        "claim_delta": field.claim_delta.value,
                        "claim_refs": claim_ids,
                        "decision_refs": list(field.decision_refs),
                        "value_artifact_key": value_artifacts.get(field.field_key),
                        "workspace_id": lineage["workspace_id"],
                        "verification_status": field.verification_status,
                    },
                )
                for evidence_ordinal, evidence in enumerate(field.evidence):
                    evidence_id = _prefixed_uuid(evidence.evidence_ref, "research-evidence:")
                    await conn.execute(
                        text(
                            """
                            INSERT INTO entity_research_result_evidence
                                (evidence_id, result_id, field_ordinal, evidence_ordinal,
                                 artifact_key, workspace_id, source_key, source_url,
                                 provider_source_id, evidence_span_sha256)
                            VALUES
                                (:evidence_id, :result_id, :field_ordinal, :evidence_ordinal,
                                 :artifact_key, :workspace_id, :source_key, :source_url,
                                 :provider_source_id, :evidence_span_sha256)
                            """
                        ),
                        {
                            "evidence_id": evidence_id,
                            "result_id": result_id,
                            "field_ordinal": field_ordinal,
                            "evidence_ordinal": evidence_ordinal,
                            "artifact_key": _artifact_key(evidence.artifact_ref),
                            "workspace_id": lineage["workspace_id"],
                            "source_key": evidence.source_key,
                            "source_url": evidence.source_url,
                            "provider_source_id": evidence.provider_source_id,
                            "evidence_span_sha256": hashlib.sha256(
                                evidence.evidence_span.encode()
                            ).hexdigest(),
                        },
                    )
        return result

    async def _lineage(
        self,
        conn: AsyncConnection,
        *,
        request: GovernedResearchToolRequest,
        operation_id: UUID,
        snapshot_id: UUID,
    ) -> dict[str, object]:
        row = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT operation.workspace_id, operation.project_run_id,
                               operation.subject_kind::text AS subject_kind,
                               operation.account_id, operation.contact_id, operation.source_key,
                               operation.request_artifact_key,
                               snapshot.response_artifact_key,
                               snapshot.normalization_artifact_key,
                               snapshot.provider_request_id,
                               snapshot.provider_reported_cost_cents,
                               receipt.id AS receipt_id, receipt.receipt_artifact_key,
                               receipt.provider_reported_cost_cents AS receipt_reported_cost,
                               receipt.settled_cost_cents
                        FROM external_research_operation operation
                        JOIN external_research_snapshot snapshot
                          ON snapshot.operation_id=operation.id
                         AND snapshot.workspace_id=operation.workspace_id
                        JOIN external_research_receipt receipt
                          ON receipt.operation_id=operation.id
                         AND receipt.workspace_id=operation.workspace_id
                        WHERE operation.id=:operation_id AND snapshot.id=:snapshot_id
                        """
                    ),
                    {"operation_id": operation_id, "snapshot_id": snapshot_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise EntityResearchResultIntegrityError(
                "result requires a ready snapshot and settled receipt"
            )
        target_id = (
            row["account_id"]
            if request.subject_type is ResearchSubjectType.ACCOUNT
            else row["contact_id"]
        )
        if (
            str(row["workspace_id"]) == ""
            or str(row["workspace_id"]) != str(await self._request_workspace(conn, request))
            or row["project_run_id"] != await self._request_project_run(conn, request)
            or str(row["subject_kind"]) != request.subject_type.value
            or target_id != request.target_entity_id
            or str(row["source_key"]) not in request.source_keys
            or row["provider_reported_cost_cents"] != row["receipt_reported_cost"]
        ):
            raise EntityResearchResultIntegrityError(
                "external result lineage crosses governed request authority"
            )
        result_rows = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT artifact_key, source_url, source_title
                        FROM external_research_result_artifact
                        WHERE snapshot_id=:snapshot_id ORDER BY ordinal
                        """
                    ),
                    {"snapshot_id": snapshot_id},
                )
            )
            .mappings()
            .all()
        )
        return {
            **dict(row),
            "operation_id": operation_id,
            "result_artifacts": result_rows,
        }

    async def _request_workspace(
        self, conn: AsyncConnection, request: GovernedResearchToolRequest
    ) -> str:
        value = (
            await conn.execute(
                text(
                    "SELECT workspace_id FROM entity_research_tool_request "
                    "WHERE tool_request_id=:tool_request_id"
                ),
                {"tool_request_id": request.tool_call_id},
            )
        ).scalar_one()
        return cast(str, value)

    async def _request_project_run(
        self, conn: AsyncConnection, request: GovernedResearchToolRequest
    ) -> UUID:
        value = (
            await conn.execute(
                text(
                    "SELECT project_run_id FROM entity_research_tool_request "
                    "WHERE tool_request_id=:tool_request_id"
                ),
                {"tool_request_id": request.tool_call_id},
            )
        ).scalar_one()
        return cast(UUID, value)

    async def _validate_artifacts(
        self,
        conn: AsyncConnection,
        *,
        request: GovernedResearchToolRequest,
        lineage: Mapping[str, object],
    ) -> None:
        workspace_id = str(lineage["workspace_id"])
        keys = {
            str(lineage["request_artifact_key"]),
            str(lineage["response_artifact_key"]),
            str(lineage["normalization_artifact_key"]),
            str(lineage["receipt_artifact_key"]),
            *(
                str(row["artifact_key"])
                for row in cast(Sequence[Mapping[str, object]], lineage["result_artifacts"])
            ),
        }
        for key in keys:
            await read_verified_artifact(
                conn,
                self._storage,
                storage_key=key,
                workspace_id=workspace_id,
            )
        del request

    async def _validate_fields(
        self,
        conn: AsyncConnection,
        *,
        request: GovernedResearchToolRequest,
        draft: ExternalResearchProjectionDraft,
        lineage: Mapping[str, object],
    ) -> None:
        all_claim_refs = tuple(ref for field in draft.fields for ref in field.claim_refs)
        claim_ids = [_claim_id(ref) for ref in all_claim_refs]
        claim_rows: dict[UUID, Mapping[str, object]] = {}
        if claim_ids:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, entity_id, field_key, value_json, source_key, source_url,
                                   artifact_key, source_operation_ref, source_snapshot_ref,
                                   evidence_span, confidence, verification_status::text,
                                   corroborations, workspace_id
                            FROM claim WHERE id=ANY(:claim_ids)
                            """
                        ),
                        {"claim_ids": claim_ids},
                    )
                )
                .mappings()
                .all()
            )
            claim_rows = {cast(UUID, row["id"]): cast(Mapping[str, object], row) for row in rows}
            if set(claim_rows) != set(claim_ids):
                raise EntityResearchResultIntegrityError("result cites an absent claim")
        workspace_id = str(lineage["workspace_id"])
        for field in draft.fields:
            field_claim_rows: list[Mapping[str, object]] = [
                claim_rows[_claim_id(ref)] for ref in field.claim_refs
            ]
            current_lineage = 0
            for row in field_claim_rows:
                if (
                    row["entity_id"] != request.target_entity_id
                    or str(row["field_key"]) != field.field_key
                    or (
                        row["workspace_id"] is not None and str(row["workspace_id"]) != workspace_id
                    )
                ):
                    raise EntityResearchResultIntegrityError(
                        "result claim crosses target, field, or workspace authority"
                    )
                if str(row["source_operation_ref"]) == str(draft.operation_id) and str(
                    row["source_snapshot_ref"]
                ) == str(draft.snapshot_id):
                    if str(row["source_key"]) not in request.source_keys:
                        raise EntityResearchResultIntegrityError(
                            "result claim's causative source was not governed"
                        )
                    current_lineage += 1
            if (
                field.claim_delta
                in {
                    ResearchClaimDelta.ACCEPTED,
                    ResearchClaimDelta.CORROBORATING,
                    ResearchClaimDelta.CONFLICTING,
                }
                and current_lineage == 0
            ):
                raise EntityResearchResultIntegrityError(
                    "claim delta contains no claim from the causative operation"
                )
            if field.outcome is ResearchFieldOutcome.FOUND:
                if not any(
                    serialize_value_json(row["value_json"]) == serialize_value_json(field.value)
                    for row in field_claim_rows
                ):
                    raise EntityResearchResultIntegrityError(
                        "found result value differs from its candidate claims"
                    )
                if field.claim_delta is ResearchClaimDelta.ACCEPTED and any(
                    int(cast(int, row["corroborations"])) > 0 for row in field_claim_rows
                ):
                    raise EntityResearchResultIntegrityError(
                        "corroborated claim was projected as merely accepted"
                    )
                if field.claim_delta is ResearchClaimDelta.CORROBORATING and not any(
                    int(cast(int, row["corroborations"])) > 0 for row in field_claim_rows
                ):
                    raise EntityResearchResultIntegrityError(
                        "corroborating result has no corroborated claim state"
                    )
            if field.claim_delta is not ResearchClaimDelta.REJECTED and any(
                str(row["verification_status"]) == "rejected" for row in field_claim_rows
            ):
                raise EntityResearchResultIntegrityError(
                    "rejected claim was projected as an admitted finding"
                )
            for evidence in field.evidence:
                artifact = _artifact_key(evidence.artifact_ref)
                _, data = await read_verified_artifact(
                    conn,
                    self._storage,
                    storage_key=artifact,
                    workspace_id=workspace_id,
                )
                if not _json_contains_text(data, evidence.evidence_span):
                    raise EntityResearchResultIntegrityError(
                        "projected evidence span is absent from retained artifact"
                    )
                if field_claim_rows and not any(
                    str(row["artifact_key"]) == artifact
                    and str(row["evidence_span"]) == evidence.evidence_span
                    for row in field_claim_rows
                ):
                    raise EntityResearchResultIntegrityError(
                        "projected evidence differs from claim provenance"
                    )

    def _result(
        self,
        *,
        request: GovernedResearchToolRequest,
        result_id: UUID,
        lineage: Mapping[str, object],
        fields: tuple[ResearchFieldResultProjection, ...],
        delivery: ResearchResultDelivery,
    ) -> PersistedResearchToolResult:
        result_artifacts = tuple(
            f"artifact:{row['artifact_key']}"
            for row in cast(Sequence[Mapping[str, object]], lineage["result_artifacts"])
        )
        if not result_artifacts:
            result_artifacts = (f"artifact:{lineage['response_artifact_key']}",)
        return PersistedResearchToolResult(
            subject_type=request.subject_type,
            target_entity_id=request.target_entity_id,
            operation_ref=f"external-research-operation:{lineage['operation_id']}",
            result_ref=f"research-result:{result_id}",
            request_artifact_ref=f"artifact:{lineage['request_artifact_key']}",
            raw_response_artifact_refs=(f"artifact:{lineage['response_artifact_key']}",),
            retained_result_artifact_refs=result_artifacts,
            normalized_result_artifact_ref=f"artifact:{lineage['normalization_artifact_key']}",
            provider_receipt_ref=f"external-research-receipt:{lineage['receipt_id']}",
            cost_settlement_ref=f"external-research-cost-settlement:{lineage['receipt_id']}",
            requested_field_keys=tuple(field.field_key for field in fields),
            fields=fields,
            delivery=delivery,
            read_tool_address=(
                None
                if delivery is ResearchResultDelivery.INLINE_COMPLETE
                else f"read_research_result(result_ref=research-result:{result_id})"
            ),
            provider_reported_cost_cents=Decimal(str(lineage["receipt_reported_cost"])),
            cost_cents=Decimal(str(lineage["settled_cost_cents"])),
        )

    async def _load_existing(
        self,
        *,
        result_id: UUID,
        request: GovernedResearchToolRequest,
    ) -> PersistedResearchToolResult | None:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT result.result_artifact_key, result.workspace_id,
                                   result.result_sha256, request_row.research_run_id,
                                   request_row.job_id, request_row.target_entity_id
                            FROM entity_research_result result
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=result.tool_request_id
                            WHERE result.result_id=:result_id
                            """
                        ),
                        {"result_id": result_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            if (
                row["research_run_id"] != request.research_run_id
                or row["job_id"] != request.job_id
                or row["target_entity_id"] != request.target_entity_id
            ):
                raise EntityResearchResultIntegrityError("result replay crosses exact job scope")
            _, data = await read_verified_artifact(
                conn,
                self._storage,
                storage_key=str(row["result_artifact_key"]),
                workspace_id=str(row["workspace_id"]),
            )
        if content_address(data) != str(row["result_sha256"]):
            raise EntityResearchResultIntegrityError("result artifact digest differs from index")
        return PersistedResearchToolResult.model_validate_json(data)

    async def read_result(
        self,
        *,
        active: ActiveEntityResearchToolExecution,
        result_ref: str,
    ) -> PersistedResearchToolResult:
        result_id = _prefixed_uuid(result_ref, "research-result:")
        authorization = active.context.authorization
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT result.result_artifact_key, result.workspace_id,
                                   result.result_sha256, request_row.research_run_id,
                                   request_row.job_id, request_row.target_entity_id
                            FROM entity_research_result result
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=result.tool_request_id
                            WHERE result.result_id=:result_id
                            """
                        ),
                        {"result_id": result_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is None or (
                row["research_run_id"] != authorization.research_run_id
                or row["job_id"] != authorization.job_id
                or row["target_entity_id"] != authorization.subject_entity_id
                or str(row["workspace_id"]) != str(authorization.workspace_id)
            ):
                raise EntityResearchToolAuthorityError("research result is outside the exact job")
            _, data = await read_verified_artifact(
                conn,
                self._storage,
                storage_key=str(row["result_artifact_key"]),
                workspace_id=str(row["workspace_id"]),
            )
            result = PersistedResearchToolResult.model_validate_json(data)
            if result.delivery is ResearchResultDelivery.INLINE_COMPLETE:
                return result
            fields: list[ResearchFieldResultProjection] = []
            for ordinal, field in enumerate(result.fields):
                if field.outcome is not ResearchFieldOutcome.FOUND:
                    fields.append(field)
                    continue
                value_key = (
                    await conn.execute(
                        text(
                            """
                            SELECT value_artifact_key FROM entity_research_result_field
                            WHERE result_id=:result_id AND ordinal=:ordinal
                            """
                        ),
                        {"result_id": result_id, "ordinal": ordinal},
                    )
                ).scalar_one()
                if value_key is None:
                    raise EntityResearchResultIntegrityError("indexed value artifact is absent")
                _, value_data = await read_verified_artifact(
                    conn,
                    self._storage,
                    storage_key=str(value_key),
                    workspace_id=str(row["workspace_id"]),
                )
                try:
                    value_payload = json.loads(value_data)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise EntityResearchResultIntegrityError(
                        "indexed value artifact is malformed"
                    ) from exc
                if value_payload.get("field_key") != field.field_key:
                    raise EntityResearchResultIntegrityError(
                        "indexed value belongs to another field"
                    )
                fields.append(field.model_copy(update={"value": value_payload.get("value")}))
        return result.model_copy(
            update={
                "fields": tuple(fields),
                "delivery": ResearchResultDelivery.INLINE_COMPLETE,
                "read_tool_address": None,
            }
        )

    async def read_evidence(
        self,
        *,
        active: ActiveEntityResearchToolExecution,
        request: ReadResearchEvidenceInput,
    ) -> ResearchEvidenceReadPage:
        evidence_id = _prefixed_uuid(request.evidence_ref, "research-evidence:")
        authorization = active.context.authorization
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT evidence.artifact_key, evidence.workspace_id,
                                   request_row.research_run_id, request_row.job_id,
                                   request_row.target_entity_id
                            FROM entity_research_result_evidence evidence
                            JOIN entity_research_result result
                              ON result.result_id=evidence.result_id
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=result.tool_request_id
                            WHERE evidence.evidence_id=:evidence_id
                              AND request_row.research_run_id=:research_run_id
                              AND request_row.job_id=:job_id
                              AND request_row.target_entity_id=:target_entity_id
                              AND evidence.workspace_id=:workspace_id
                            ORDER BY result.created_at DESC, result.result_id DESC
                            LIMIT 1
                            """
                        ),
                        {
                            "evidence_id": evidence_id,
                            "research_run_id": authorization.research_run_id,
                            "job_id": authorization.job_id,
                            "target_entity_id": authorization.subject_entity_id,
                            "workspace_id": str(authorization.workspace_id),
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None or (
                row["research_run_id"] != authorization.research_run_id
                or row["job_id"] != authorization.job_id
                or row["target_entity_id"] != authorization.subject_entity_id
                or str(row["workspace_id"]) != str(authorization.workspace_id)
            ):
                raise EntityResearchToolAuthorityError("research evidence is outside the exact job")
            _, data = await read_verified_artifact(
                conn,
                self._storage,
                storage_key=str(row["artifact_key"]),
                workspace_id=str(row["workspace_id"]),
            )
        end = min(len(data), request.offset + request.max_bytes)
        if request.offset > len(data):
            raise EntityResearchResultIntegrityError("evidence offset exceeds retained content")
        return ResearchEvidenceReadPage(
            evidence_ref=request.evidence_ref,
            artifact_ref=f"artifact:{row['artifact_key']}",
            offset=request.offset,
            next_offset=end,
            complete=end == len(data),
            content=data[request.offset : end].decode("utf-8", errors="replace"),
            content_sha256=content_address(data),
        )


class GovernedEntityResearchToolFactory:
    """Compose exact account/contact surfaces from provider actions and engine-owned tools."""

    def __init__(
        self,
        *,
        requests: EntityResearchToolRequestStore,
        causation: EntityResearchProviderCausationStore,
        results: EntityResearchResultStore,
    ) -> None:
        self._requests = requests
        self._causation = causation
        self._results = results

    def compose(
        self,
        *,
        surface: EntityAgentToolSurface,
        provider_actions: Mapping[str, ProviderActionBinding],
        engine_tools: Mapping[str, EntityResearchToolBinding],
    ) -> tuple[EntityResearchToolBinding, ...]:
        reserved_reads = {"read_research_result", "read_evidence"}
        if set(provider_actions).intersection(reserved_reads) or set(engine_tools).intersection(
            reserved_reads
        ):
            raise EntityResearchToolAuthorityError("R4 read tools are engine-owned")
        if set(provider_actions).intersection(engine_tools):
            raise EntityResearchToolAuthorityError("one semantic tool has two owners")
        misplaced_provider_tools = set(engine_tools).intersection(_PROVIDER_CAPABLE_TOOL_NAMES)
        if misplaced_provider_tools:
            raise EntityResearchToolAuthorityError(
                "provider-capable semantic tools require governed provider actions: "
                f"{sorted(misplaced_provider_tools)}"
            )
        unknown_provider_tools = set(provider_actions) - _PROVIDER_CAPABLE_TOOL_NAMES
        if unknown_provider_tools:
            raise EntityResearchToolAuthorityError(
                "non-provider semantic tools cannot be composed as provider actions: "
                f"{sorted(unknown_provider_tools)}"
            )
        expected = set(surface.tool_names)
        observed = set(provider_actions) | set(engine_tools) | reserved_reads
        if observed != expected:
            raise EntityResearchToolAuthorityError(
                "governed tool composition differs from exact surface: "
                f"missing={sorted(expected - observed)} extra={sorted(observed - expected)}"
            )

        bindings: dict[str, EntityResearchToolBinding] = dict(engine_tools)
        for name, binding in provider_actions.items():
            bindings[name] = EntityResearchToolBinding(
                tool=self._provider_tool(name=name, action=binding.action),
                version=binding.version,
            )
        bindings["read_research_result"] = EntityResearchToolBinding(
            tool=self._read_result_tool(), version=1
        )
        bindings["read_evidence"] = EntityResearchToolBinding(
            tool=self._read_evidence_tool(), version=1
        )
        return tuple(bindings[name] for name in surface.tool_names)

    def _provider_tool(self, *, name: str, action: EntityResearchProviderAction) -> StructuredTool:
        async def invoke(**values: object) -> dict[str, JsonValue]:
            semantic = EntityResearchSemanticToolInput.model_validate(values)
            active = current_entity_research_tool_execution()
            request = await self._requests.record(active=active, semantic=semantic)

            async def before_dispatch(operation: ExternalResearchOperationRow) -> None:
                await self._causation.bind_before_dispatch(
                    request=request,
                    operation=operation,
                )

            drafts = tuple(await action.execute(request, before_dispatch=before_dispatch))
            if not drafts:
                raise EntityResearchResultIntegrityError(
                    "provider action returned no complete result or external wait"
                )
            covered = tuple(
                field_key for draft in drafts for field_key in draft.requested_field_keys
            )
            if len(covered) != len(set(covered)) or set(covered) != set(request.field_keys):
                raise EntityResearchResultIntegrityError(
                    "provider action bundles do not partition every governed field exactly once"
                )
            persisted: list[PersistedResearchToolResult] = []
            for draft in drafts:
                operation_row = await self._causation.get_operation(draft.operation_id)
                observation = await self._causation.observe(
                    request=request,
                    operation=operation_row,
                )
                persisted.append(
                    await self._results.persist(
                        request=request,
                        observation=observation,
                        draft=draft,
                    )
                )
            batch = EntityResearchToolResultBatch(
                tool_request_ref=f"entity-research-tool-request:{request.tool_call_id}",
                results=tuple(persisted),
            )
            return cast(dict[str, JsonValue], batch.model_dump(mode="json"))

        return StructuredTool.from_function(
            coroutine=invoke,
            name=name,
            description=(
                "Run one governed, persisted research action for selected fields and sources. "
                "Returns complete normalized field outcomes, claim deltas, evidence, cost, and "
                "lineage only after durable persistence."
            ),
            args_schema=EntityResearchSemanticToolInput,
        )

    def _read_result_tool(self) -> StructuredTool:
        async def invoke(result_ref: str) -> dict[str, JsonValue]:
            result = await self._results.read_result(
                active=current_entity_research_tool_execution(),
                result_ref=result_ref,
            )
            return cast(dict[str, JsonValue], result.model_dump(mode="json"))

        return StructuredTool.from_function(
            coroutine=invoke,
            name="read_research_result",
            description="Losslessly read one complete persisted result in this exact job.",
            args_schema=ReadResearchResultInput,
        )

    def _read_evidence_tool(self) -> StructuredTool:
        async def invoke(**values: object) -> dict[str, JsonValue]:
            page = await self._results.read_evidence(
                active=current_entity_research_tool_execution(),
                request=ReadResearchEvidenceInput.model_validate(values),
            )
            return cast(dict[str, JsonValue], page.model_dump(mode="json"))

        return StructuredTool.from_function(
            coroutine=invoke,
            name="read_evidence",
            description="Read a bounded lossless page from retained evidence in this exact job.",
            args_schema=ReadResearchEvidenceInput,
        )


__all__ = [
    "EntityResearchProviderAction",
    "EntityResearchProviderCausationStore",
    "EntityResearchResultIntegrityError",
    "EntityResearchResultStore",
    "EntityResearchToolAuthorityError",
    "EntityResearchToolRequestStore",
    "EntityResearchToolResultBatch",
    "ExternalResearchProjectionDraft",
    "GovernedEntityResearchToolFactory",
    "ProviderActionBinding",
    "ProviderOperationObservation",
    "ResearchEvidenceReadPage",
]
