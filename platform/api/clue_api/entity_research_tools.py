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
from enum import StrEnum
from typing import Annotated, Protocol, Self, cast, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.entity_research_contracts import (
    EntityResearchToolBinding,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    ActiveEntityResearchToolExecution,
    EntityResearchExternalWait,
    current_entity_research_tool_execution,
)
from clue_agents.entity_research_tools import (
    EntityResearchSemanticToolInput,
    ReadResearchEvidenceInput,
    ReadResearchResultInput,
)
from clue_core import EntityId, serialize_value_json
from clue_core.entity_research import (
    EntityAgentToolSurface,
    FieldSourceAuthority,
    GovernedResearchToolRequest,
    PersistedResearchToolResult,
    ProviderOperationCausation,
    ResearchClaimDelta,
    ResearchDiscoveredSubjectProjection,
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


class EntityResearchProviderWait(RuntimeError):
    """A provider-neutral joined operation that must suspend the durable entity job."""

    def __init__(self, operation: ProviderOperationReservation) -> None:
        super().__init__(f"provider operation is still pending: {operation.operation_ref}")
        self.operation = operation


class ProviderOperationObservation(BaseModel):
    """One tool's relation to an operation; only caused is provider-spend causation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: UUID
    tool_request_id: UUID
    operation_ref: NonEmptyStr
    workspace_id: NonEmptyStr
    disposition: str
    created_at: datetime


class ProviderObservationDisposition(StrEnum):
    CAUSED = "caused"
    REPLAY = "replay_observation"
    JOINED = "joined_observation"


class ProviderOperationReservation(BaseModel):
    """Provider-neutral immutable operation identity projected before any dispatch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_kind: NonEmptyStr
    operation_ref: NonEmptyStr
    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    project_run_id: UUID
    subject_type: ResearchSubjectType
    target_entity_id: UUID
    parent_account_id: UUID | None = None
    source_key: NonEmptyStr
    field_keys: tuple[NonEmptyStr, ...] = ()
    request_artifact_ref: NonEmptyStr
    reserved_at: datetime
    dispatched_at: datetime | None = None
    observation_disposition: ProviderObservationDisposition

    @model_validator(mode="after")
    def _scope_is_exact(self) -> Self:
        if self.reserved_at.utcoffset() is None:
            raise ValueError("provider operation reservation time must be timezone-aware")
        if self.dispatched_at is not None and (
            self.dispatched_at.utcoffset() is None or self.dispatched_at < self.reserved_at
        ):
            raise ValueError("provider dispatch time must follow its durable reservation")
        if self.subject_type is ResearchSubjectType.CONTACT:
            if self.parent_account_id is None:
                raise ValueError("contact provider operation requires a parent account")
        elif self.parent_account_id is not None:
            raise ValueError("account provider operation cannot carry a parent account")
        if len(self.field_keys) != len(set(self.field_keys)):
            raise ValueError("provider operation field keys must be unique")
        if any(
            not field_key.startswith(f"{self.subject_type.value}.") for field_key in self.field_keys
        ):
            raise ValueError("provider operation contains a cross-axis field")
        return self


class ProviderResultLineage(BaseModel):
    """Complete durable provider artifacts and settlement loaded from its owning ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: ProviderOperationReservation
    snapshot_ref: NonEmptyStr
    raw_response_artifact_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    retained_result_artifact_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    normalized_result_artifact_ref: NonEmptyStr
    provider_receipt_ref: NonEmptyStr
    cost_settlement_ref: NonEmptyStr
    provider_request_id: NonEmptyStr
    provider_reported_cost_cents: Decimal = Field(ge=0)
    settled_cost_cents: Decimal = Field(ge=0)


class ProviderResearchProjectionDraft(BaseModel):
    """Claim-engine output awaiting R4 relational/artifact integrity validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: ProviderOperationReservation
    snapshot_ref: NonEmptyStr
    requested_field_keys: tuple[NonEmptyStr, ...] = ()
    fields: tuple[ResearchFieldResultProjection, ...] = ()
    discovered_subjects: tuple[ResearchDiscoveredSubjectProjection, ...] = ()

    @model_validator(mode="after")
    def _complete_index(self) -> Self:
        returned = tuple(field.field_key for field in self.fields)
        if len(returned) != len(set(returned)) or set(returned) != set(self.requested_field_keys):
            raise ValueError("projection draft must cover each requested field exactly once")
        if not self.fields and not self.discovered_subjects:
            raise ValueError("projection draft requires fields or discovered subjects")
        return self


# Compatibility name for the first concrete Exa adapter; the shape itself is provider-neutral.
ExternalResearchProjectionDraft = ProviderResearchProjectionDraft


class EntityResearchToolResultBatch(BaseModel):
    """One semantic call may compile into several provider-safe schema bundles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_request_ref: NonEmptyStr
    results: tuple[PersistedResearchToolResult, ...] = Field(min_length=1)
    current_state_sha256: Sha256
    yield_count: int = Field(ge=0)


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
        before_dispatch: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
    ) -> Sequence[ProviderResearchProjectionDraft]: ...


@runtime_checkable
class ProviderResultLineageReader(Protocol):
    """Load one ready result from the provider ledger that owns provider_kind."""

    async def load(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: ProviderOperationReservation,
        snapshot_ref: str,
    ) -> ProviderResultLineage: ...


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

    def __init__(
        self,
        *,
        conn_factory: ConnFactory,
        storage: StorageBackend | None = None,
        prior_context_max_bytes: int = 16_000,
    ) -> None:
        if prior_context_max_bytes < 1_024:
            raise ValueError("prior research context cap must be at least 1024 bytes")
        self._conn_factory = conn_factory
        self._storage = storage
        self._prior_context_max_bytes = prior_context_max_bytes

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
        is_follow_up = semantic.parent_operation_ref is not None
        if not is_follow_up and not set(semantic.questions).issubset(selection.research_questions):
            raise EntityResearchToolAuthorityError("semantic tool widened confirmed questions")
        if active.call.tool_name not in context.tool_surface.tool_names:
            raise EntityResearchToolAuthorityError("semantic tool is outside the exact surface")

        requested_authority: list[FieldSourceAuthority] = []
        for authority in selection.field_source_authority:
            if authority.field_key not in semantic.field_keys:
                continue
            sources = tuple(
                source for source in authority.source_keys if source in semantic.source_keys
            )
            if not sources:
                raise EntityResearchToolAuthorityError(
                    f"field {authority.field_key!r} has no authorized requested source"
                )
            requested_authority.append(
                FieldSourceAuthority(field_key=authority.field_key, source_keys=sources)
            )
        if semantic.field_keys and (
            {item.field_key for item in requested_authority} != set(semantic.field_keys)
            or {source for item in requested_authority for source in item.source_keys}
            != set(semantic.source_keys)
        ):
            raise EntityResearchToolAuthorityError(
                "semantic tool requested an unauthorized field/source pairing"
            )

        tool_request_id = uuid5(
            _TOOL_REQUEST_NAMESPACE,
            f"{context.agent_turn_id}:{active.call.tool_call_id}",
        )
        prior_result_sha256: str | None = None
        prior_research_context: str | None = None
        async with self._conn_factory() as conn:
            if is_follow_up:
                parent_result_id = _prefixed_uuid(
                    cast(str, semantic.parent_observation_ref),
                    "research-result:",
                )
                parent = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT parent_result.provider_operation_ref,
                                       parent_result.result_sha256,
                                       parent_result.result_artifact_key,
                                       parent_result.workspace_id
                                FROM entity_research_result parent_result
                                JOIN entity_research_tool_request parent_request
                                  ON parent_request.tool_request_id=parent_result.tool_request_id
                                WHERE parent_result.result_id=:parent_result_id
                                  AND parent_result.provider_operation_ref=:parent_operation_ref
                                  AND parent_request.research_run_id=:research_run_id
                                  AND parent_request.job_id=:job_id
                                  AND parent_request.subject_type=:subject_type
                                  AND parent_request.target_entity_id=:target_entity_id
                                  AND parent_request.workspace_id=:workspace_id
                                """
                            ),
                            {
                                "parent_result_id": parent_result_id,
                                "parent_operation_ref": semantic.parent_operation_ref,
                                "research_run_id": authorization.research_run_id,
                                "job_id": authorization.job_id,
                                "subject_type": authorization.subject_type.value,
                                "target_entity_id": authorization.subject_entity_id,
                                "workspace_id": authorization.workspace_id,
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                if parent is None:
                    raise EntityResearchToolAuthorityError(
                        "follow-up parent observation is outside the exact job"
                    )
                if self._storage is None:
                    raise EntityResearchToolAuthorityError(
                        "follow-up requires the persisted-result storage reader"
                    )
                prior_result_sha256 = str(parent["result_sha256"])
                _, prior_bytes = await read_verified_artifact(
                    conn,
                    self._storage,
                    storage_key=str(parent["result_artifact_key"]),
                    workspace_id=str(parent["workspace_id"]),
                )
                if content_address(prior_bytes) != prior_result_sha256:
                    raise EntityResearchResultIntegrityError(
                        "follow-up parent artifact differs from its durable digest"
                    )
                prior_research_context = self._bounded_prior_context(prior_bytes)

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
            field_source_authority=tuple(requested_authority),
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
            prior_result_sha256=prior_result_sha256,
            prior_research_context=prior_research_context,
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
            "field_source_authority": serialize_value_json(
                [item.model_dump(mode="json") for item in request.field_source_authority]
            ),
            "questions": list(request.questions),
            "budget_reservation_key": request.budget_reservation_key,
            "idempotency_key": request.idempotency_key,
            "parent_operation_ref": request.parent_operation_ref,
            "parent_observation_ref": request.parent_observation_ref,
            "follow_up_reason": (
                request.follow_up_reason.value if request.follow_up_reason is not None else None
            ),
            "prior_result_sha256": request.prior_result_sha256,
            "prior_research_context": request.prior_research_context,
        }
        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_tool_request
                        (tool_request_id, agent_turn_id, agent_execution_id, tool_event_id,
                         raw_tool_call_id, research_run_id, job_id, subject_type,
                         target_entity_id, parent_account_id, workspace_id, project_id,
                         product_id, project_run_id, tool_name, tool_version,
                         tool_input_sha256, field_plan_ref, source_plan_ref, field_keys,
                         source_keys, field_source_authority, questions,
                         budget_reservation_key, idempotency_key, parent_operation_ref,
                         parent_observation_ref, follow_up_reason, prior_result_sha256,
                         prior_research_context)
                    VALUES
                        (:tool_request_id, :agent_turn_id, :agent_execution_id, :tool_event_id,
                         :raw_tool_call_id, :research_run_id, :job_id, :subject_type,
                         :target_entity_id, :parent_account_id, :workspace_id, :project_id,
                         :product_id, :project_run_id, :tool_name, :tool_version,
                         :tool_input_sha256, :field_plan_ref, :source_plan_ref, :field_keys,
                         :source_keys, CAST(:field_source_authority AS jsonb), :questions,
                         :budget_reservation_key, :idempotency_key, :parent_operation_ref,
                         :parent_observation_ref, :follow_up_reason, :prior_result_sha256,
                         :prior_research_context)
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
                                   source_keys, field_source_authority, questions,
                                   budget_reservation_key, idempotency_key, parent_operation_ref,
                                   parent_observation_ref, follow_up_reason, prior_result_sha256,
                                   prior_research_context
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
                "field_source_authority",
                "questions",
                "budget_reservation_key",
                "idempotency_key",
                "parent_operation_ref",
                "parent_observation_ref",
                "follow_up_reason",
                "prior_result_sha256",
                "prior_research_context",
            )
        }
        normalized = dict(observed)
        for key in ("field_keys", "source_keys", "questions"):
            normalized[key] = list(normalized[key])
        normalized["field_source_authority"] = serialize_value_json(
            normalized["field_source_authority"]
        )
        if normalized != comparable:
            raise EntityResearchToolAuthorityError(
                "tool request id replayed with different immutable authority"
            )
        return request

    def _bounded_prior_context(self, data: bytes) -> str:
        """Return attributable prior facts, not just lineage, under a hard prompt-size cap."""

        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EntityResearchResultIntegrityError(
                "follow-up parent result artifact is malformed"
            ) from exc
        complete = _canonical_bytes(payload)
        if len(complete) <= self._prior_context_max_bytes:
            return complete.decode("utf-8")
        if not isinstance(payload, Mapping):
            raise EntityResearchResultIntegrityError("follow-up parent result is not an object")

        def compact_field(field: Mapping[str, object]) -> dict[str, object | None]:
            return {
                "field_key": field.get("field_key"),
                "outcome": field.get("outcome"),
                "value": field.get("value"),
                "value_ref": field.get("value_ref"),
                "claim_refs": field.get("claim_refs"),
                "verification_status": field.get("verification_status"),
            }

        compact = {
            "result_ref": payload.get("result_ref"),
            "operation_ref": payload.get("operation_ref"),
            "subject_type": payload.get("subject_type"),
            "target_entity_id": payload.get("target_entity_id"),
            "fields": [
                compact_field(field)
                for field in payload.get("fields", [])
                if isinstance(field, Mapping)
            ],
            "discovered_subjects": [
                {
                    "subject_type": subject.get("subject_type"),
                    "target_entity_id": subject.get("target_entity_id"),
                    "parent_account_id": subject.get("parent_account_id"),
                    "identity_claim_refs": subject.get("identity_claim_refs"),
                    "association_evidence_refs": subject.get("association_evidence_refs"),
                    "fields": [
                        compact_field(field)
                        for field in subject.get("fields", [])
                        if isinstance(field, Mapping)
                    ],
                }
                for subject in payload.get("discovered_subjects", [])
                if isinstance(subject, Mapping)
            ],
        }
        compact_bytes = _canonical_bytes(compact)
        if len(compact_bytes) > self._prior_context_max_bytes:
            raise EntityResearchResultIntegrityError(
                "prior result index exceeds the bounded follow-up context contract"
            )
        return compact_bytes.decode("utf-8")


class EntityResearchProviderCausationStore:
    """Bind provider-neutral causes before dispatch and retain replay/join observations."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    @staticmethod
    def _assert_scope(
        request: GovernedResearchToolRequest,
        operation: ProviderOperationReservation,
    ) -> None:
        expected_parent = (
            request.parent_account_id
            if request.subject_type is ResearchSubjectType.CONTACT
            else None
        )
        authority = {
            item.field_key: frozenset(item.source_keys) for item in request.field_source_authority
        }
        if (
            operation.workspace_id == ""
            or operation.subject_type is not request.subject_type
            or operation.target_entity_id != request.target_entity_id
            or operation.parent_account_id != expected_parent
            or operation.source_key not in request.source_keys
            or not set(operation.field_keys).issubset(request.field_keys)
            or (bool(request.field_keys) != bool(operation.field_keys))
            or any(
                operation.source_key not in authority.get(field_key, frozenset())
                for field_key in operation.field_keys
            )
        ):
            raise EntityResearchToolAuthorityError(
                "provider operation crosses governed tool request authority"
            )

    async def _project_operation(
        self,
        conn: AsyncConnection,
        *,
        request: GovernedResearchToolRequest,
        operation: ProviderOperationReservation,
    ) -> None:
        self._assert_scope(request, operation)
        await conn.execute(
            text(
                """
                INSERT INTO entity_research_provider_operation
                    (operation_ref, provider_kind, workspace_id, project_id, project_run_id,
                     subject_type, target_entity_id, parent_account_id, source_key,
                     field_keys, request_artifact_ref, reserved_at, dispatched_at)
                VALUES
                    (:operation_ref, :provider_kind, :workspace_id, :project_id, :project_run_id,
                     :subject_type, :target_entity_id, :parent_account_id, :source_key,
                     :field_keys, :request_artifact_ref, :reserved_at, :dispatched_at)
                ON CONFLICT (operation_ref) DO UPDATE
                SET dispatched_at=COALESCE(
                    entity_research_provider_operation.dispatched_at,
                    EXCLUDED.dispatched_at
                )
                """
            ),
            {
                "operation_ref": operation.operation_ref,
                "provider_kind": operation.provider_kind,
                "workspace_id": operation.workspace_id,
                "project_id": operation.project_id,
                "project_run_id": operation.project_run_id,
                "subject_type": operation.subject_type.value,
                "target_entity_id": operation.target_entity_id,
                "parent_account_id": operation.parent_account_id,
                "source_key": operation.source_key,
                "field_keys": list(operation.field_keys),
                "request_artifact_ref": operation.request_artifact_ref,
                "reserved_at": operation.reserved_at,
                "dispatched_at": operation.dispatched_at,
            },
        )
        row = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT provider_kind, workspace_id, project_id, project_run_id,
                               subject_type, target_entity_id, parent_account_id, source_key,
                               field_keys, request_artifact_ref, reserved_at, dispatched_at
                        FROM entity_research_provider_operation
                        WHERE operation_ref=:operation_ref
                        """
                    ),
                    {"operation_ref": operation.operation_ref},
                )
            )
            .mappings()
            .one()
        )
        observed = (
            str(row["provider_kind"]),
            str(row["workspace_id"]),
            str(row["project_id"]),
            row["project_run_id"],
            str(row["subject_type"]),
            row["target_entity_id"],
            row["parent_account_id"],
            str(row["source_key"]),
            tuple(row["field_keys"]),
            str(row["request_artifact_ref"]),
            row["reserved_at"],
        )
        expected = (
            operation.provider_kind,
            operation.workspace_id,
            operation.project_id,
            operation.project_run_id,
            operation.subject_type.value,
            operation.target_entity_id,
            operation.parent_account_id,
            operation.source_key,
            operation.field_keys,
            operation.request_artifact_ref,
            operation.reserved_at,
        )
        if observed != expected:
            raise EntityResearchToolAuthorityError(
                "provider operation reference replayed with different immutable authority"
            )
        if operation.dispatched_at is not None and row["dispatched_at"] != operation.dispatched_at:
            raise EntityResearchToolAuthorityError(
                "provider operation dispatch time changed across observations"
            )

    async def bind_before_dispatch(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: ProviderOperationReservation,
    ) -> ProviderOperationObservation:
        if (
            operation.observation_disposition is not ProviderObservationDisposition.CAUSED
            or operation.dispatched_at is not None
        ):
            raise EntityResearchToolAuthorityError(
                "before-dispatch causation requires a newly reserved undispatched operation"
            )
        async with self._conn_factory() as conn:
            await self._project_operation(conn, request=request, operation=operation)
            existing = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT observation_id, tool_request_id, provider_operation_ref,
                                   external_workspace_id, disposition, created_at
                            FROM entity_research_provider_observation
                            WHERE provider_operation_ref=:operation_ref
                              AND disposition='caused'
                            """
                        ),
                        {"operation_ref": operation.operation_ref},
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                return self._row(cast(Mapping[str, object], existing))
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO entity_research_provider_observation
                                (observation_id, tool_request_id, provider_operation_ref,
                                 external_workspace_id, disposition)
                            VALUES
                                (:observation_id, :tool_request_id, :operation_ref,
                                 :workspace_id, 'caused')
                            ON CONFLICT DO NOTHING
                            RETURNING observation_id, tool_request_id, provider_operation_ref,
                                      external_workspace_id, disposition, created_at
                            """
                        ),
                        {
                            "observation_id": uuid4(),
                            "tool_request_id": request.tool_call_id,
                            "operation_ref": operation.operation_ref,
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
                                SELECT observation_id, tool_request_id, provider_operation_ref,
                                       external_workspace_id, disposition, created_at
                                FROM entity_research_provider_observation
                                WHERE provider_operation_ref=:operation_ref
                                  AND disposition='caused'
                                """
                            ),
                            {"operation_ref": operation.operation_ref},
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
        operation: ProviderOperationReservation,
    ) -> ProviderOperationObservation:
        async with self._conn_factory() as conn:
            await self._project_operation(conn, request=request, operation=operation)
            own = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT observation_id, tool_request_id, provider_operation_ref,
                                   external_workspace_id, disposition, created_at
                            FROM entity_research_provider_observation
                            WHERE tool_request_id=:tool_request_id
                              AND provider_operation_ref=:operation_ref
                            """
                        ),
                        {
                            "tool_request_id": request.tool_call_id,
                            "operation_ref": operation.operation_ref,
                        },
                    )
                )
                .mappings()
                .first()
            )
        if own is not None:
            observed = self._row(cast(Mapping[str, object], own))
            if (
                operation.observation_disposition is not ProviderObservationDisposition.CAUSED
                and observed.disposition != operation.observation_disposition.value
            ):
                raise EntityResearchToolAuthorityError(
                    "provider operation observation replay changed its disposition"
                )
            return observed
        if operation.observation_disposition is ProviderObservationDisposition.CAUSED:
            raise EntityResearchToolAuthorityError(
                "causative provider observation was not recorded before dispatch"
            )
        return await self._record(
            request=request,
            operation=operation,
            disposition=operation.observation_disposition.value,
        )

    async def _record(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: ProviderOperationReservation,
        disposition: str,
    ) -> ProviderOperationObservation:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            INSERT INTO entity_research_provider_observation
                                (observation_id, tool_request_id, provider_operation_ref,
                                 external_workspace_id, disposition)
                            VALUES
                                (:observation_id, :tool_request_id, :operation_ref,
                                 :workspace_id, :disposition)
                            ON CONFLICT (tool_request_id, provider_operation_ref) DO NOTHING
                            RETURNING observation_id, tool_request_id, provider_operation_ref,
                                      external_workspace_id, disposition, created_at
                            """
                        ),
                        {
                            "observation_id": uuid4(),
                            "tool_request_id": request.tool_call_id,
                            "operation_ref": operation.operation_ref,
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
                                SELECT observation_id, tool_request_id, provider_operation_ref,
                                       external_workspace_id, disposition, created_at
                                FROM entity_research_provider_observation
                                WHERE tool_request_id=:tool_request_id
                                  AND provider_operation_ref=:operation_ref
                                """
                            ),
                            {
                                "tool_request_id": request.tool_call_id,
                                "operation_ref": operation.operation_ref,
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
            operation_ref=str(row["provider_operation_ref"]),
            workspace_id=str(row["external_workspace_id"]),
            disposition=str(row["disposition"]),
            created_at=cast(datetime, row["created_at"]),
        )

    async def causation_for(
        self,
        operation_ref: str | UUID,
    ) -> ProviderOperationCausation | None:
        if isinstance(operation_ref, UUID):
            operation_ref = f"external-research-operation:{operation_ref}"
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
                                   operation_row.operation_ref,
                                   operation_row.reserved_at AS provider_operation_reserved_at,
                                   operation_row.dispatched_at AS provider_dispatched_at
                            FROM entity_research_provider_observation observation
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=observation.tool_request_id
                            JOIN entity_research_agent_turn turn_row
                              ON turn_row.agent_turn_id=request_row.agent_turn_id
                            JOIN entity_research_agent_event event_row
                              ON event_row.event_id=request_row.tool_event_id
                            JOIN entity_research_provider_operation operation_row
                              ON operation_row.operation_ref=observation.provider_operation_ref
                            WHERE observation.provider_operation_ref=:operation_ref
                              AND observation.disposition='caused'
                            """
                        ),
                        {"operation_ref": operation_ref},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        if row["provider_dispatched_at"] is None:
            raise EntityResearchResultIntegrityError(
                "causative provider operation has no durable dispatch timestamp"
            )
        return ProviderOperationCausation(
            subject_type=ResearchSubjectType(str(row["subject_type"])),
            target_entity_id=cast(UUID, row["target_entity_id"]),
            provider_operation_ref=str(row["operation_ref"]),
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


class ExternalResearchResultLineageReader:
    """Adapt the existing durable Exa/external-research ledger to the R4 provider seam."""

    provider_kind = "external_research"

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def load(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: ProviderOperationReservation,
        snapshot_ref: str,
    ) -> ProviderResultLineage:
        operation_id = _prefixed_uuid(operation.operation_ref, "external-research-operation:")
        snapshot_id = _prefixed_uuid(snapshot_ref, "external-research-snapshot:")
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT operation.workspace_id, operation.project_id,
                                   operation.project_run_id,
                                   operation.subject_kind::text AS subject_kind,
                                   operation.account_id, operation.contact_id,
                                   operation.source_key, operation.request_artifact_key,
                                   operation.created_at,
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
                    "external result requires a ready snapshot and settled receipt"
                )
            result_artifacts = tuple(
                f"artifact:{value}"
                for value in (
                    await conn.execute(
                        text(
                            "SELECT artifact_key FROM external_research_result_artifact "
                            "WHERE snapshot_id=:snapshot_id ORDER BY ordinal"
                        ),
                        {"snapshot_id": snapshot_id},
                    )
                ).scalars()
            )

        target = (
            row["account_id"]
            if request.subject_type is ResearchSubjectType.ACCOUNT
            else row["contact_id"]
        )
        parent = row["account_id"] if request.subject_type is ResearchSubjectType.CONTACT else None
        expected = (
            operation.workspace_id,
            operation.project_id,
            operation.project_run_id,
            operation.subject_type.value,
            operation.target_entity_id,
            operation.parent_account_id,
            operation.source_key,
            operation.request_artifact_ref,
        )
        observed = (
            str(row["workspace_id"]),
            str(row["project_id"]),
            row["project_run_id"],
            str(row["subject_kind"]),
            target,
            parent,
            str(row["source_key"]),
            f"artifact:{row['request_artifact_key']}",
        )
        if (
            observed != expected
            or row["provider_reported_cost_cents"] != row["receipt_reported_cost"]
        ):
            raise EntityResearchResultIntegrityError(
                "external result lineage crosses provider-operation authority"
            )
        if operation.provider_kind != self.provider_kind:
            raise EntityResearchResultIntegrityError(
                "external lineage reader received another provider kind"
            )
        if str(row["source_key"]) not in request.source_keys:
            raise EntityResearchResultIntegrityError(
                "external result source was not authorized by the tool request"
            )
        response_ref = f"artifact:{row['response_artifact_key']}"
        return ProviderResultLineage(
            operation=operation,
            snapshot_ref=snapshot_ref,
            raw_response_artifact_refs=(response_ref,),
            retained_result_artifact_refs=result_artifacts or (response_ref,),
            normalized_result_artifact_ref=f"artifact:{row['normalization_artifact_key']}",
            provider_receipt_ref=f"external-research-receipt:{row['receipt_id']}",
            cost_settlement_ref=f"external-research-cost-settlement:{row['receipt_id']}",
            provider_request_id=str(row["provider_request_id"]),
            provider_reported_cost_cents=Decimal(str(row["receipt_reported_cost"])),
            settled_cost_cents=Decimal(str(row["settled_cost_cents"])),
        )


class EntityResearchResultStore:
    """Validate and retain a complete provider/claim projection before exposing it."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: ConnFactory,
        inline_max_bytes: int = 24_000,
        message_max_bytes: int = 256_000,
        lineage_readers: Mapping[str, ProviderResultLineageReader] | None = None,
    ) -> None:
        if inline_max_bytes < 1:
            raise ValueError("inline result byte cap must be positive")
        if message_max_bytes < inline_max_bytes:
            raise ValueError("result message cap cannot be below the inline threshold")
        self._storage = storage
        self._conn_factory = conn_factory
        self._inline_max_bytes = inline_max_bytes
        self._message_max_bytes = message_max_bytes
        if lineage_readers is None:
            lineage_readers = {
                ExternalResearchResultLineageReader.provider_kind: (
                    ExternalResearchResultLineageReader(conn_factory=conn_factory)
                )
            }
        self._lineage_readers = dict(lineage_readers)

    async def persist(
        self,
        *,
        request: GovernedResearchToolRequest,
        observation: ProviderOperationObservation,
        draft: ProviderResearchProjectionDraft,
    ) -> PersistedResearchToolResult:
        if observation.tool_request_id != request.tool_call_id:
            raise EntityResearchResultIntegrityError("result observation belongs to another tool")
        if observation.operation_ref != draft.operation.operation_ref:
            raise EntityResearchResultIntegrityError("result draft belongs to another operation")
        if not set(draft.requested_field_keys).issubset(request.field_keys):
            raise EntityResearchResultIntegrityError("result draft widens governed fields")
        if not set(draft.requested_field_keys).issubset(draft.operation.field_keys):
            raise EntityResearchResultIntegrityError(
                "result draft widens the causative provider operation fields"
            )
        result_id = uuid5(
            _RESULT_NAMESPACE,
            f"{request.tool_call_id}:{draft.operation.operation_ref}",
        )
        existing = await self._load_existing(result_id=result_id, request=request)
        if existing is not None:
            return existing

        reader = self._lineage_readers.get(draft.operation.provider_kind)
        if reader is None:
            raise EntityResearchResultIntegrityError(
                f"no lineage reader is composed for provider {draft.operation.provider_kind!r}"
            )
        lineage = await reader.load(
            request=request,
            operation=draft.operation,
            snapshot_ref=draft.snapshot_ref,
        )
        async with self._conn_factory() as conn:
            await self._validate_artifacts(conn, request=request, lineage=lineage)
            await self._validate_fields(
                conn,
                request=request,
                draft=draft,
                lineage=lineage,
            )

            fields = draft.fields
            discovered_subjects = draft.discovered_subjects
            provisional = self._result(
                request=request,
                result_id=result_id,
                lineage=lineage,
                fields=fields,
                discovered_subjects=discovered_subjects,
                delivery=ResearchResultDelivery.INLINE_COMPLETE,
            )
            value_artifacts: dict[tuple[UUID, str], str] = {}
            if len(_canonical_bytes(provisional)) > self._inline_max_bytes:
                fields = await self._index_fields(
                    conn,
                    result_id=result_id,
                    subject_entity_id=request.target_entity_id,
                    fields=fields,
                    lineage=lineage,
                    value_artifacts=value_artifacts,
                )
                indexed_subjects: list[ResearchDiscoveredSubjectProjection] = []
                for subject in discovered_subjects:
                    indexed_subjects.append(
                        subject.model_copy(
                            update={
                                "fields": await self._index_fields(
                                    conn,
                                    result_id=result_id,
                                    subject_entity_id=subject.target_entity_id,
                                    fields=subject.fields,
                                    lineage=lineage,
                                    value_artifacts=value_artifacts,
                                )
                            }
                        )
                    )
                discovered_subjects = tuple(indexed_subjects)
                result = self._result(
                    request=request,
                    result_id=result_id,
                    lineage=lineage,
                    fields=fields,
                    discovered_subjects=discovered_subjects,
                    delivery=ResearchResultDelivery.INDEXED_COMPLETE,
                )
            else:
                result = provisional

            result_bytes = self._agent_message_bytes(result)
            result_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=lineage.operation.workspace_id,
                content=result_bytes,
                media_type="application/json",
                source_key=lineage.operation.source_key,
            )
            result_sha = content_address(result_bytes)
            if not result_key.endswith(result_sha):
                raise EntityResearchResultIntegrityError("result artifact address changed")
            subject_kind = request.subject_type.value
            await bind_discovery_artifact_subject(
                conn,
                workspace_id=lineage.operation.workspace_id,
                artifact_key_value=result_key,
                subject_kind=subject_kind,
                subject_entity_id=EntityId(request.target_entity_id),
                reference_kind="entity_research_result",
                reference_id=str(result_id),
            )
            for (entity_id, field_key), value_key in value_artifacts.items():
                await bind_discovery_artifact_subject(
                    conn,
                    workspace_id=lineage.operation.workspace_id,
                    artifact_key_value=value_key,
                    subject_kind=(
                        request.subject_type.value
                        if entity_id == request.target_entity_id
                        else ResearchSubjectType.CONTACT.value
                    ),
                    subject_entity_id=EntityId(entity_id),
                    reference_kind="entity_research_value",
                    reference_id=f"{result_id}:{entity_id}:{field_key}",
                )
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_result
                        (result_id, tool_request_id, provider_observation_id,
                         provider_operation_ref, provider_snapshot_ref, workspace_id,
                         subject_type, target_entity_id,
                         result_artifact_key, result_sha256, delivery, requested_field_keys)
                    VALUES
                        (:result_id, :tool_request_id, :provider_observation_id,
                         :provider_operation_ref, :provider_snapshot_ref, :workspace_id,
                         :subject_type, :target_entity_id,
                         :result_artifact_key, :result_sha256, :delivery,
                         :requested_field_keys)
                    """
                ),
                {
                    "result_id": result_id,
                    "tool_request_id": request.tool_call_id,
                    "provider_observation_id": observation.observation_id,
                    "provider_operation_ref": draft.operation.operation_ref,
                    "provider_snapshot_ref": draft.snapshot_ref,
                    "workspace_id": lineage.operation.workspace_id,
                    "subject_type": request.subject_type.value,
                    "target_entity_id": request.target_entity_id,
                    "result_artifact_key": result_key,
                    "result_sha256": result_sha,
                    "delivery": result.delivery.value,
                    "requested_field_keys": list(result.requested_field_keys),
                },
            )
            flattened = self._flatten_result_fields(
                result,
                parent_account_id=request.parent_account_id,
            )
            for field_ordinal, (field_subject_type, field_target_id, parent_id, field) in enumerate(
                flattened
            ):
                claim_ids = [_claim_id(ref) for ref in field.claim_refs]
                await conn.execute(
                    text(
                        """
                        INSERT INTO entity_research_result_field
                            (result_id, ordinal, subject_type, target_entity_id,
                             parent_account_id, field_key, outcome, claim_delta,
                             claim_refs, decision_refs, value_artifact_key, workspace_id,
                             verification_status)
                        VALUES
                            (:result_id, :ordinal, :subject_type, :target_entity_id,
                             :parent_account_id, :field_key, :outcome, :claim_delta,
                             :claim_refs, :decision_refs, :value_artifact_key, :workspace_id,
                             :verification_status)
                        """
                    ),
                    {
                        "result_id": result_id,
                        "ordinal": field_ordinal,
                        "subject_type": field_subject_type.value,
                        "target_entity_id": field_target_id,
                        "parent_account_id": parent_id,
                        "field_key": field.field_key,
                        "outcome": field.outcome.value,
                        "claim_delta": field.claim_delta.value,
                        "claim_refs": claim_ids,
                        "decision_refs": list(field.decision_refs),
                        "value_artifact_key": value_artifacts.get(
                            (field_target_id, field.field_key)
                        ),
                        "workspace_id": lineage.operation.workspace_id,
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
                            "workspace_id": lineage.operation.workspace_id,
                            "source_key": evidence.source_key,
                            "source_url": evidence.source_url,
                            "provider_source_id": evidence.provider_source_id,
                            "evidence_span_sha256": hashlib.sha256(
                                evidence.evidence_span.encode()
                            ).hexdigest(),
                        },
                    )
        return result

    def _agent_message_bytes(self, result: PersistedResearchToolResult) -> bytes:
        """Measure the final inline/indexed projection, never the smaller provisional shape."""

        value = _canonical_bytes(result)
        if len(value) > self._message_max_bytes:
            raise EntityResearchResultIntegrityError(
                "complete result index exceeds the configured agent-message bound"
            )
        return value

    async def _index_fields(
        self,
        conn: AsyncConnection,
        *,
        result_id: UUID,
        subject_entity_id: UUID,
        fields: tuple[ResearchFieldResultProjection, ...],
        lineage: ProviderResultLineage,
        value_artifacts: dict[tuple[UUID, str], str],
    ) -> tuple[ResearchFieldResultProjection, ...]:
        indexed: list[ResearchFieldResultProjection] = []
        for field in fields:
            if field.outcome is not ResearchFieldOutcome.FOUND:
                indexed.append(field)
                continue
            value_bytes = _canonical_bytes(
                {
                    "subject_entity_id": str(subject_entity_id),
                    "field_key": field.field_key,
                    "value": field.value,
                }
            )
            value_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=lineage.operation.workspace_id,
                content=value_bytes,
                media_type="application/json",
                source_key=lineage.operation.source_key,
            )
            value_artifacts[(subject_entity_id, field.field_key)] = value_key
            indexed.append(
                field.model_copy(
                    update={
                        "value": None,
                        "value_ref": (
                            f"research-value:{result_id}:{subject_entity_id}:{field.field_key}"
                        ),
                    }
                )
            )
        return tuple(indexed)

    @staticmethod
    def _flatten_result_fields(
        result: PersistedResearchToolResult,
        *,
        parent_account_id: UUID | None,
    ) -> tuple[tuple[ResearchSubjectType, UUID, UUID | None, ResearchFieldResultProjection], ...]:
        values = [
            (
                result.subject_type,
                result.target_entity_id,
                parent_account_id if result.subject_type is ResearchSubjectType.CONTACT else None,
                field,
            )
            for field in result.fields
        ]
        values.extend(
            (
                subject.subject_type,
                subject.target_entity_id,
                subject.parent_account_id,
                field,
            )
            for subject in result.discovered_subjects
            for field in subject.fields
        )
        return tuple(values)

    async def _validate_artifacts(
        self,
        conn: AsyncConnection,
        *,
        request: GovernedResearchToolRequest,
        lineage: ProviderResultLineage,
    ) -> None:
        workspace_id = lineage.operation.workspace_id
        keys = {
            _artifact_key(lineage.operation.request_artifact_ref),
            *(_artifact_key(ref) for ref in lineage.raw_response_artifact_refs),
            *(_artifact_key(ref) for ref in lineage.retained_result_artifact_refs),
            _artifact_key(lineage.normalized_result_artifact_ref),
        }
        for key in keys:
            await read_verified_artifact(
                conn,
                self._storage,
                storage_key=key,
                workspace_id=workspace_id,
            )
        if lineage.operation.target_entity_id != request.target_entity_id:
            raise EntityResearchResultIntegrityError("lineage artifact belongs to another target")

    async def _validate_fields(
        self,
        conn: AsyncConnection,
        *,
        request: GovernedResearchToolRequest,
        draft: ProviderResearchProjectionDraft,
        lineage: ProviderResultLineage,
    ) -> None:
        field_units: list[tuple[ResearchSubjectType, UUID, ResearchFieldResultProjection]] = [
            (request.subject_type, request.target_entity_id, field) for field in draft.fields
        ]
        for subject in draft.discovered_subjects:
            if request.subject_type is not ResearchSubjectType.ACCOUNT:
                raise EntityResearchResultIntegrityError(
                    "only account research may project discovered contacts"
                )
            admitted = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM contact_entity WHERE id=:contact_id "
                        "AND account_entity_id=:account_id AND status <> 'merged'"
                    ),
                    {
                        "contact_id": subject.target_entity_id,
                        "account_id": request.target_entity_id,
                    },
                )
            ).scalar_one_or_none()
            if admitted is None:
                raise EntityResearchResultIntegrityError(
                    "discovered contact is not identity-resolved under the exact account"
                )
            await self._validate_subject_refs(conn, subject=subject)
            field_units.extend(
                (ResearchSubjectType.CONTACT, subject.target_entity_id, field)
                for field in subject.fields
            )

        all_claim_refs = tuple(ref for _, _, field in field_units for ref in field.claim_refs)
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
        workspace_id = lineage.operation.workspace_id
        allowed_by_field = {
            item.field_key: frozenset(item.source_keys) for item in request.field_source_authority
        }
        for subject_type, target_entity_id, field in field_units:
            field_claim_rows: list[Mapping[str, object]] = [
                claim_rows[_claim_id(ref)] for ref in field.claim_refs
            ]
            current_lineage = 0
            for row in field_claim_rows:
                if (
                    row["entity_id"] != target_entity_id
                    or str(row["field_key"]) != field.field_key
                    or (
                        row["workspace_id"] is not None and str(row["workspace_id"]) != workspace_id
                    )
                ):
                    raise EntityResearchResultIntegrityError(
                        "result claim crosses target, field, or workspace authority"
                    )
                if self._reference_matches(
                    row["source_operation_ref"], draft.operation.operation_ref
                ) and self._reference_matches(row["source_snapshot_ref"], draft.snapshot_ref):
                    allowed_sources = allowed_by_field.get(field.field_key)
                    if subject_type is request.subject_type and (
                        allowed_sources is None or str(row["source_key"]) not in allowed_sources
                    ):
                        raise EntityResearchResultIntegrityError(
                            "result claim violates exact field/source authority"
                        )
                    if subject_type is ResearchSubjectType.CONTACT and (
                        str(row["source_key"]) != draft.operation.source_key
                    ):
                        raise EntityResearchResultIntegrityError(
                            "discovered contact claim uses another causative source"
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
                if subject_type is request.subject_type:
                    allowed_sources = allowed_by_field.get(field.field_key, frozenset())
                    if evidence.source_key not in allowed_sources:
                        raise EntityResearchResultIntegrityError(
                            "projected evidence violates exact field/source authority"
                        )

    async def _validate_subject_refs(
        self,
        conn: AsyncConnection,
        *,
        subject: ResearchDiscoveredSubjectProjection,
    ) -> None:
        refs = subject.strong_identity_claim_refs + subject.association_evidence_refs
        if not all(ref.startswith("claim:") for ref in refs):
            raise EntityResearchResultIntegrityError(
                "discovered contact admission currently requires durable claim references"
            )
        ids = [_claim_id(ref) for ref in refs]
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT id, entity_id FROM claim WHERE id=ANY(:claim_ids) "
                        "AND superseded_by IS NULL"
                    ),
                    {"claim_ids": ids},
                )
            )
            .mappings()
            .all()
        )
        if {cast(UUID, row["id"]) for row in rows} != set(ids) or any(
            row["entity_id"] != subject.target_entity_id for row in rows
        ):
            raise EntityResearchResultIntegrityError(
                "discovered contact admission references absent or foreign identity evidence"
            )

    @staticmethod
    def _reference_matches(stored: object, reference: str) -> bool:
        value = str(stored)
        return value == reference or value == reference.rsplit(":", 1)[-1]

    def _result(
        self,
        *,
        request: GovernedResearchToolRequest,
        result_id: UUID,
        lineage: ProviderResultLineage,
        fields: tuple[ResearchFieldResultProjection, ...],
        discovered_subjects: tuple[ResearchDiscoveredSubjectProjection, ...],
        delivery: ResearchResultDelivery,
    ) -> PersistedResearchToolResult:
        return PersistedResearchToolResult(
            subject_type=request.subject_type,
            target_entity_id=request.target_entity_id,
            operation_ref=lineage.operation.operation_ref,
            result_ref=f"research-result:{result_id}",
            request_artifact_ref=lineage.operation.request_artifact_ref,
            raw_response_artifact_refs=lineage.raw_response_artifact_refs,
            retained_result_artifact_refs=lineage.retained_result_artifact_refs,
            normalized_result_artifact_ref=lineage.normalized_result_artifact_ref,
            provider_receipt_ref=lineage.provider_receipt_ref,
            cost_settlement_ref=lineage.cost_settlement_ref,
            requested_field_keys=tuple(field.field_key for field in fields),
            fields=fields,
            discovered_subjects=discovered_subjects,
            delivery=delivery,
            read_tool_address=(
                None
                if delivery is ResearchResultDelivery.INLINE_COMPLETE
                else f"read_research_result(result_ref=research-result:{result_id})"
            ),
            provider_reported_cost_cents=lineage.provider_reported_cost_cents,
            cost_cents=lineage.settled_cost_cents,
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
                                   request_row.job_id, request_row.subject_type,
                                   request_row.target_entity_id,
                                   request_row.parent_account_id,
                                   request_row.workspace_id AS request_workspace_id
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
                or str(row["subject_type"]) != request.subject_type.value
                or row["target_entity_id"] != request.target_entity_id
                or row["parent_account_id"] != request.parent_account_id
                or str(row["workspace_id"]) != str(row["request_workspace_id"])
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

    async def refresh_state(self, request: GovernedResearchToolRequest) -> str:
        """Fold immutable request/observation/result history into the job's current-state digest."""

        async with self._conn_factory() as conn:
            initial_state = (
                await conn.execute(
                    text(
                        "SELECT initial_state_sha256 FROM entity_research_job "
                        "WHERE job_id=:job_id AND research_run_id=:research_run_id FOR UPDATE"
                    ),
                    {"job_id": request.job_id, "research_run_id": request.research_run_id},
                )
            ).scalar_one_or_none()
            if initial_state is None:
                raise EntityResearchResultIntegrityError(
                    "cannot advance state for an absent entity-research job"
                )
            requests = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT tool_request_id, tool_input_sha256, idempotency_key,
                                   parent_operation_ref, parent_observation_ref,
                                   prior_result_sha256
                            FROM entity_research_tool_request
                            WHERE job_id=:job_id ORDER BY created_at, tool_request_id
                            """
                        ),
                        {"job_id": request.job_id},
                    )
                )
                .mappings()
                .all()
            )
            observations = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT observation.tool_request_id,
                                   observation.provider_operation_ref,
                                   observation.disposition,
                                   operation.provider_kind, operation.source_key,
                                   operation.field_keys, operation.request_artifact_ref,
                                   operation.reserved_at, operation.dispatched_at
                            FROM entity_research_provider_observation observation
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=observation.tool_request_id
                            JOIN entity_research_provider_operation operation
                              ON operation.operation_ref=observation.provider_operation_ref
                            WHERE request_row.job_id=:job_id
                            ORDER BY observation.created_at, observation.observation_id
                            """
                        ),
                        {"job_id": request.job_id},
                    )
                )
                .mappings()
                .all()
            )
            results = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT result.tool_request_id, result.provider_operation_ref,
                                   result.provider_snapshot_ref, result.result_sha256,
                                   result.delivery
                            FROM entity_research_result result
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=result.tool_request_id
                            WHERE request_row.job_id=:job_id
                            ORDER BY result.created_at, result.result_id
                            """
                        ),
                        {"job_id": request.job_id},
                    )
                )
                .mappings()
                .all()
            )
            digest = canonical_sha256(
                {
                    "contract": "m8d-entity-research-state-v2",
                    "initial_state_sha256": str(initial_state),
                    "requests": [self._json_row(row) for row in requests],
                    "observations": [self._json_row(row) for row in observations],
                    "results": [self._json_row(row) for row in results],
                }
            )
            await conn.execute(
                text(
                    "UPDATE entity_research_job SET current_state_sha256=:digest, "
                    "updated_at=now() WHERE job_id=:job_id"
                ),
                {"digest": digest, "job_id": request.job_id},
            )
        return digest

    @staticmethod
    def _json_row(row: Mapping[str, object] | RowMapping) -> dict[str, object]:
        return {
            key: str(value) if isinstance(value, (UUID, Decimal, datetime)) else value
            for key, value in row.items()
        }

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
                                   request_row.job_id, request_row.target_entity_id,
                                   request_row.parent_account_id
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
                or row["parent_account_id"] != authorization.parent_account_id
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
            rebuilt: dict[tuple[UUID, str], ResearchFieldResultProjection] = {}
            for ordinal, (_, target_id, _, field) in enumerate(
                self._flatten_result_fields(
                    result,
                    parent_account_id=authorization.parent_account_id,
                )
            ):
                if field.outcome is not ResearchFieldOutcome.FOUND:
                    rebuilt[(target_id, field.field_key)] = field
                    continue
                value_row = (
                    (
                        await conn.execute(
                            text(
                                """
                            SELECT value_artifact_key, target_entity_id, field_key
                            FROM entity_research_result_field
                            WHERE result_id=:result_id AND ordinal=:ordinal
                            """
                            ),
                            {"result_id": result_id, "ordinal": ordinal},
                        )
                    )
                    .mappings()
                    .one()
                )
                if (
                    value_row["target_entity_id"] != target_id
                    or str(value_row["field_key"]) != field.field_key
                ):
                    raise EntityResearchResultIntegrityError(
                        "indexed value row belongs to another subject or field"
                    )
                value_key = value_row["value_artifact_key"]
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
                if value_payload.get("field_key") != field.field_key or value_payload.get(
                    "subject_entity_id"
                ) != str(target_id):
                    raise EntityResearchResultIntegrityError(
                        "indexed value belongs to another subject or field"
                    )
                rebuilt[(target_id, field.field_key)] = field.model_copy(
                    update={"value": value_payload.get("value")}
                )
            fields = tuple(
                rebuilt[(result.target_entity_id, field.field_key)] for field in result.fields
            )
            discovered = tuple(
                subject.model_copy(
                    update={
                        "fields": tuple(
                            rebuilt[(subject.target_entity_id, field.field_key)]
                            for field in subject.fields
                        )
                    }
                )
                for subject in result.discovered_subjects
            )
        return result.model_copy(
            update={
                "fields": fields,
                "discovered_subjects": discovered,
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
        if request.offset > len(data):
            raise EntityResearchResultIntegrityError("evidence offset exceeds retained content")
        try:
            data[: request.offset].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise EntityResearchResultIntegrityError(
                "evidence offset must be a UTF-8 code-point boundary"
            ) from exc
        end = min(len(data), request.offset + request.max_bytes)
        while end > request.offset:
            try:
                content = data[request.offset : end].decode("utf-8", errors="strict")
                break
            except UnicodeDecodeError as exc:
                if exc.reason not in {"unexpected end of data", "invalid continuation byte"}:
                    raise EntityResearchResultIntegrityError(
                        "retained evidence is not valid UTF-8"
                    ) from exc
                end -= 1
        else:
            if request.offset == len(data):
                content = ""
            else:
                raise EntityResearchResultIntegrityError(
                    "evidence page size is too small for the next UTF-8 code point"
                )
        return ResearchEvidenceReadPage(
            evidence_ref=request.evidence_ref,
            artifact_ref=f"artifact:{row['artifact_key']}",
            offset=request.offset,
            next_offset=end,
            complete=end == len(data),
            content=content,
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

            async def before_dispatch(
                operation: ProviderOperationReservation,
            ) -> ProviderOperationObservation:
                return await self._causation.bind_before_dispatch(
                    request=request,
                    operation=operation,
                )

            try:
                drafts = tuple(await action.execute(request, before_dispatch=before_dispatch))
            except EntityResearchProviderWait as wait:
                await self._causation.observe(request=request, operation=wait.operation)
                current_state = await self._results.refresh_state(request)
                raise EntityResearchExternalWait(
                    wait_ref=wait.operation.operation_ref,
                    current_state_sha256=current_state,
                ) from wait
            if not drafts:
                raise EntityResearchResultIntegrityError(
                    "provider action returned no complete result or external wait"
                )
            covered = tuple(
                field_key for draft in drafts for field_key in draft.requested_field_keys
            )
            has_discovered = any(draft.discovered_subjects for draft in drafts)
            if (
                len(covered) != len(set(covered))
                or set(covered) != set(request.field_keys)
                or (not covered and not has_discovered)
            ):
                raise EntityResearchResultIntegrityError(
                    "provider bundles must partition fields or return grounded discovered subjects"
                )
            persisted: list[PersistedResearchToolResult] = []
            for draft in drafts:
                observation = await self._causation.observe(
                    request=request,
                    operation=draft.operation,
                )
                persisted.append(
                    await self._results.persist(
                        request=request,
                        observation=observation,
                        draft=draft,
                    )
                )
            current_state = await self._results.refresh_state(request)
            yield_count = sum(
                1
                for result in persisted
                for field in (
                    result.fields
                    + tuple(
                        field for subject in result.discovered_subjects for field in subject.fields
                    )
                )
                if field.outcome is ResearchFieldOutcome.FOUND
            ) + sum(len(result.discovered_subjects) for result in persisted)
            batch = EntityResearchToolResultBatch(
                tool_request_ref=f"entity-research-tool-request:{request.tool_call_id}",
                results=tuple(persisted),
                current_state_sha256=current_state,
                yield_count=yield_count,
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
    "EntityResearchProviderWait",
    "EntityResearchResultIntegrityError",
    "EntityResearchResultStore",
    "EntityResearchToolAuthorityError",
    "EntityResearchToolRequestStore",
    "EntityResearchToolResultBatch",
    "ExternalResearchProjectionDraft",
    "GovernedEntityResearchToolFactory",
    "ProviderActionBinding",
    "ProviderObservationDisposition",
    "ProviderOperationObservation",
    "ProviderOperationReservation",
    "ProviderResearchProjectionDraft",
    "ProviderResultLineage",
    "ProviderResultLineageReader",
    "ResearchEvidenceReadPage",
]
