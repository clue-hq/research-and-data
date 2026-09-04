"""M8D R5 executable account-agent acceptance on isolated Postgres and fixture providers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import ConfigDict, PrivateAttr, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

import clue_agents.entity_research_runtime as runtime_module
from clue_agents.account_entity_research import (
    AccountBuyingUnitScope,
    DiscoverBuyingCommitteeInput,
)
from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import (
    EntityResearchAgentResult,
    EntityResearchToolCall,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
    current_entity_research_tool_execution,
)
from clue_api.account_entity_research import (
    AccountResearchAuthorityError,
    AccountResearchExecutionGuard,
    AccountResearchFinalizationEngine,
    AccountResearchStateStore,
)
from clue_api.account_entity_research_composition import (
    AccountResearchDefinitionResolver,
    StaticAccountResearchProviderActions,
    account_research_profile_sha256,
)
from clue_api.entity_research_runtime_wiring import DbEntityResearchAgentJournal
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    EntityResearchProviderAction,
    EntityResearchProviderCausationStore,
    EntityResearchResultIntegrityError,
    EntityResearchResultStore,
    EntityResearchToolRequestStore,
    ExternalResearchResultLineageReader,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
    ProviderObservationDisposition,
    ProviderOperationObservation,
    ProviderOperationReservation,
    ProviderResearchProjectionDraft,
    ProviderResultLineage,
    ProviderResultLineageReader,
)
from clue_api.exa_deep_acquisition import ExaDeepAcquisitionCoordinator
from clue_api.exa_deep_materialization import ExaDeepSnapshotResolverProvider
from clue_api.exa_entity_research_tools import (
    ExaAccountSemanticResearchAction,
    ExaEntityResearchProjectionBuilder,
)
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_committee_source import SumbleCommitteeSource
from clue_api.sumble_entity_research_tools import SumbleCommitteeSemanticResearchAction
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_core import (
    Claim,
    ClaimProvenanceKind,
    CommitteeAcquisitionRequest,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    Persona,
    ProjectRunId,
    ResearchCommitteePlan,
    ResearchMode,
    ReuseScope,
    RunId,
    UseClass,
    discovery_claim,
    revalidate_with,
    serialize_value_json,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    EntityResearchSelection,
    FieldSourceAuthority,
    GovernedResearchToolRequest,
    PersistedResearchToolResult,
    ResearchClaimDelta,
    ResearchDiscoveredSubjectProjection,
    ResearchEvidenceProjection,
    ResearchFieldOutcome,
    ResearchFieldResultProjection,
    ResearchFinalizationOutcome,
    ResearchResultDelivery,
    ResearchRunKind,
    ResearchRunLifecycleContract,
    ResearchSubjectType,
)
from clue_fleet import DbEntityResearchJobStore, EntityResearchRunEnvelope
from clue_fleet.entity_research import EntityResearchExecutionFence
from clue_research.claimstore import WorkspaceScope, claims_for, insert_claim
from clue_research.durable import insert_account_run, pin_account_run_research_directive
from clue_research.durable.discovery import capture_discovery_artifact
from clue_research.identity import get_account, insert_contact_entity
from clue_research.profiling.committee import (
    CURRENT_TITLE,
    PERSONA,
    ROLE_ON_COMMITTEE,
    load_committee_pack,
)
from clue_research.profiling.committee.results import CommitteeMemberRef, CommitteeResult
from clue_research.profiling.committee.sources import (
    CandidateFactProvenance,
    CandidateProfessionalFact,
    CommitteePersonCandidate,
)
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from clue_research.resolvers.sumble.teams import TEAMS_SOURCE_KEY
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from clue_storage import FsStorage, StorageBackend
from tests.agents.test_entity_research_runtime_r3 import Checkpointers
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.api.test_exa_deep_acquisition_e1 import _payload as _exa_payload
from tests.api.test_exa_deep_acquisition_e1 import _Transport as _ExaTransport
from tests.api.test_sumble_committee_acquisition_s2b import _CommitteeTransport
from tests.api.test_sumble_committee_acquisition_s2b import _setup as _committee_setup
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn as durable_rollback_conn
from tests.fleet.entity_research_r2_helpers import run_envelope
from tests.profiling.conftest import (
    FakeGateway,
    rollback_conn,
    seed_packs,
)
from tests.profiling.conftest import (
    migrated_db as migrated_db,
)
from tests.profiling.conftest import (
    require_profiling_db as require_profiling_db,
)

_PAIN = "account.operational_pain"
_MOVES = "account.strategic_moves"
_HIRING = "account.hiring_velocity_eng"
_QUALITATIVE_QUESTION = "Where is administrative work creating avoidable burden?"
_STRUCTURED_QUESTION = "What is the current hiring velocity for operational roles?"
#: What ``_FixtureAccountProviders`` answers an account-field call with, per field.
_R5_FIELD_VALUES: Mapping[str, object] = {
    _PAIN: "Referral intake depends on repeated manual fax reconciliation.",
    _MOVES: "The practice is expanding its centralized referral program.",
    _HIRING: 4,
}
_COMMITTEE_QUESTION = "Who participates in this product buying decision at the same office?"


class _NestedConnFactory:
    """Isolate each composed service call while the outer test owns final rollback."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncConnection]:
        async with self._conn.begin_nested():
            yield self._conn


class _Models:
    def __init__(self, model: BaseChatModel) -> None:
        self.model = model

    def build(self, **_kwargs: object) -> BaseChatModel:
        return self.model


class _DecisionModel(BaseChatModel):
    """Stateful test mind that bases every next call on the preceding persisted tool result."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    account_id: UUID
    scope_id: UUID
    _result_refs: list[str] = PrivateAttr(default_factory=list)
    _observed_committee_plan: dict[str, Any] | None = PrivateAttr(default=None)
    _observed_first_result: bool = PrivateAttr(default=False)
    _justification: str | None = PrivateAttr(default=None)
    _bound_tools: tuple[str, ...] = PrivateAttr(default=())
    _committee_subjects: tuple[tuple[UUID, UUID], ...] = PrivateAttr(default=())
    _inference_attempt: int = PrivateAttr(default=0)
    _inference_claim_refs: tuple[str, str] | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "m8d-r5-observing-account-agent"

    @property
    def observed_committee_plan(self) -> dict[str, Any] | None:
        return self._observed_committee_plan

    @property
    def observed_first_result(self) -> bool:
        return self._observed_first_result

    @property
    def justification(self) -> str | None:
        return self._justification

    @property
    def bound_tools(self) -> tuple[str, ...]:
        return self._bound_tools

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        del tool_choice, kwargs
        self._bound_tools = tuple(
            str(item.get("name") or item.get("function", {}).get("name"))
            if isinstance(item, dict)
            else str(getattr(item, "name", getattr(item, "__name__", "")))
            for item in tools
        )
        return self

    @staticmethod
    def _payload(message: ToolMessage) -> dict[str, Any]:
        content = message.content
        if isinstance(content, str):
            return cast(dict[str, Any], json.loads(content))
        if isinstance(content, dict):
            return cast(dict[str, Any], content)
        raise AssertionError(f"unexpected R5 tool payload: {type(content)!r}")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        tools = [message for message in messages if isinstance(message, ToolMessage)]
        if not tools:
            response = AIMessage(
                content="",
                tool_calls=[{"name": "read_account_research_state", "args": {}, "id": "r5-read"}],
            )
        else:
            last = tools[-1]
            payload = self._payload(last)
            if last.name == "read_account_research_state":
                assert payload["result_refs"] == []
                self._observed_committee_plan = payload["committee_plan"]
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "research_account_deep",
                            "args": {
                                "field_keys": [_PAIN, _MOVES],
                                "source_keys": ["exa_deep"],
                                "questions": [_QUALITATIVE_QUESTION],
                            },
                            "id": "r5-exa",
                        }
                    ],
                )
            elif last.name == "research_account_deep":
                results = payload["results"]
                assert {item["field_key"] for item in results[0]["fields"]} == {
                    _PAIN,
                    _MOVES,
                }
                assert all(item["evidence"] for item in results[0]["fields"])
                self._result_refs.extend(item["result_ref"] for item in results)
                self._observed_first_result = True
                self._justification = (
                    "The qualitative result resolved pain and strategic moves but left the "
                    "independent structured hiring field unresolved."
                )
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "enrich_account",
                            "args": {
                                "field_keys": [_HIRING],
                                "source_keys": ["sumble_jobs"],
                                "questions": [_STRUCTURED_QUESTION],
                            },
                            "id": "r5-sumble-structured",
                        }
                    ],
                )
            elif last.name == "enrich_account":
                results = payload["results"]
                assert results[0]["fields"][0]["field_key"] == _HIRING
                self._result_refs.extend(item["result_ref"] for item in results)
                evidence_ref = results[0]["fields"][0]["evidence"][0]["evidence_ref"]
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "discover_buying_committee",
                            "args": {
                                "field_keys": [],
                                "source_keys": ["sumble_people"],
                                "questions": [_COMMITTEE_QUESTION],
                                "buying_unit_scope": {
                                    "scope_id": str(self.scope_id),
                                    "account_entity_id": str(self.account_id),
                                    "office_label": "Boston gastroenterology practice",
                                    "locality": "Boston",
                                    "region": "Massachusetts",
                                    "target_functions": ["Operations"],
                                    "evidence_refs": [evidence_ref],
                                    "match_policy": "same_office_strict",
                                },
                            },
                            "id": "r5-committee",
                        }
                    ],
                )
            elif last.name == "discover_buying_committee":
                results = payload["results"]
                assert len(results[0]["discovered_subjects"]) == 2
                self._result_refs.extend(item["result_ref"] for item in results)
                self._committee_subjects = tuple(
                    (
                        UUID(item["target_entity_id"]),
                        UUID(item["fields"][0]["claim_refs"][0].removeprefix("claim:")),
                    )
                    for item in results[0]["discovered_subjects"]
                )
                first_contact, first_evidence = self._committee_subjects[0]
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "record_committee_role_inferences",
                            "args": {
                                "inferences": [
                                    {
                                        "contact_entity_id": str(uuid4()),
                                        "role": "champion",
                                        "confidence": 0.87,
                                        "reasoning": "The operations leader owns the workflow.",
                                        "evidence_claim_ids": [str(first_evidence)],
                                    }
                                ]
                            },
                            "id": "r5-role-outsider",
                        }
                    ],
                )
            elif last.name == "record_committee_role_inferences":
                first_contact, first_evidence = self._committee_subjects[0]
                _, second_evidence = self._committee_subjects[1]
                if self._inference_attempt == 0:
                    assert payload["error"] == "governed_research_rejection"
                    assert "outside" in payload["detail"]
                    next_evidence = second_evidence
                    call_id = "r5-role-cross-contact"
                elif self._inference_attempt == 1:
                    assert payload["error"] == "governed_research_rejection"
                    assert "evidence" in payload["detail"]
                    next_evidence = first_evidence
                    call_id = "r5-role-valid"
                elif self._inference_attempt == 2:
                    assert payload["committee_member_count"] == 2
                    assert payload["inferred_member_count"] == 1
                    assert payload["needs_review"] == 1
                    assert payload["committee_status"] == "needs_review"
                    recorded = payload["recorded_inferences"]
                    assert len(recorded) == 1
                    self._inference_claim_refs = (
                        recorded[0]["role_claim_ref"],
                        recorded[0]["persona_claim_ref"],
                    )
                    next_evidence = first_evidence
                    call_id = "r5-role-replay"
                else:
                    recorded = payload["recorded_inferences"]
                    assert self._inference_claim_refs == (
                        recorded[0]["role_claim_ref"],
                        recorded[0]["persona_claim_ref"],
                    )
                    response = AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "assess_account_coverage",
                                "args": {
                                    "result_refs": self._result_refs,
                                    "assessment_note": (
                                        "All selected account fields are grounded and one "
                                        "committee member has a cited role inference."
                                    ),
                                },
                                "id": "r5-coverage",
                            }
                        ],
                    )
                    self._inference_attempt += 1
                    return ChatResult(generations=[ChatGeneration(message=response)])
                self._inference_attempt += 1
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "record_committee_role_inferences",
                            "args": {
                                "inferences": [
                                    {
                                        "contact_entity_id": str(first_contact),
                                        "role": "champion",
                                        "confidence": 0.87,
                                        "reasoning": "The operations leader owns the workflow.",
                                        "evidence_claim_ids": [str(next_evidence)],
                                    }
                                ]
                            },
                            "id": call_id,
                        }
                    ],
                )
            elif last.name == "assess_account_coverage":
                assert payload["committee_status"] == "needs_review"
                assert payload["committee_needs_review"] == 1
                assert "committee_roles_uninferred" in payload["review_flags"]
                assert payload["unresolved_field_keys"] == []
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "finalize_account_research",
                            "args": {
                                "coverage_ledger_ref": payload["coverage_ledger_ref"],
                                "requested_outcome": "needs_review",
                            },
                            "id": "r5-finalize-tool",
                        }
                    ],
                )
            elif last.name == "finalize_account_research":
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ResearchFinalizationProposal",
                            "args": payload,
                            "id": "r5-typed-final",
                        }
                    ],
                )
            else:  # pragma: no cover - a new unexpected tool fails the acceptance loudly
                raise AssertionError(f"unexpected R5 tool result: {last.name}")
        return ChatResult(generations=[ChatGeneration(message=response)])


class _FixtureLineageReader(ProviderResultLineageReader):
    provider_kind = "r5_fixture"

    def __init__(self) -> None:
        self.values: dict[str, ProviderResultLineage] = {}

    async def load(
        self,
        *,
        request: object,
        operation: ProviderOperationReservation,
        snapshot_ref: str,
    ) -> ProviderResultLineage:
        del request
        value = self.values[operation.operation_ref]
        assert value.snapshot_ref == snapshot_ref
        return value


class _FixtureAccountProviders(EntityResearchProviderAction):
    """Provider fixture: real durability/claim plumbing, deterministic external bytes."""

    provider_kind = "r5_fixture"

    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: Callable[[], Any],
        contacts: tuple[UUID, UUID],
        lineage: _FixtureLineageReader,
        field_values: Mapping[str, object] | None = None,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory
        self._contacts = contacts
        self._lineage = lineage
        # The three R5 fields this fixture has always answered, plus anything a caller adds.
        # Additive on purpose: a suite that researches a *different* field (FI-2 slice 3 buys a
        # project-relative one) supplies its value here instead of copying the whole
        # claim/artifact plumbing below.
        self._field_values: Mapping[str, object] = {**_R5_FIELD_VALUES, **(field_values or {})}
        self.calls: list[str] = []

    async def execute(
        self,
        request: Any,
        *,
        before_dispatch: Callable[[ProviderOperationReservation], Any],
        settle_terminal: Callable[[ProviderOperationReservation], Any],
    ) -> Sequence[ProviderResearchProjectionDraft]:
        del settle_terminal
        active = current_entity_research_tool_execution()
        authorization = active.context.authorization
        self.calls.append(request.tool_name)
        source_key = request.source_keys[0]
        operation_ref = f"r5-fixture-operation:{request.tool_call_id}"
        snapshot_ref = f"r5-fixture-snapshot:{request.tool_call_id}"
        provider_request_id = f"r5-provider-request-{request.tool_call_id}"
        async with self._conn_factory() as conn:
            request_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=authorization.workspace_id,
                content=json.dumps(
                    {"tool": request.tool_name, "fields": list(request.field_keys)},
                    sort_keys=True,
                ).encode(),
                media_type="application/json",
                source_key=source_key,
            )
        reserved_at = datetime.now(UTC)
        reserved = ProviderOperationReservation(
            provider_kind=self.provider_kind,
            operation_ref=operation_ref,
            workspace_id=authorization.workspace_id,
            project_id=authorization.project_id,
            project_run_id=authorization.project_run_id,
            subject_type=ResearchSubjectType.ACCOUNT,
            target_entity_id=authorization.subject_entity_id,
            source_key=source_key,
            field_keys=request.field_keys,
            request_artifact_ref=f"artifact:{request_key}",
            reserved_at=reserved_at,
            observation_disposition=ProviderObservationDisposition.CAUSED,
        )
        observed: ProviderOperationObservation = await before_dispatch(reserved)
        assert observed.disposition == ProviderObservationDisposition.CAUSED.value
        dispatched = reserved.model_copy(update={"dispatched_at": datetime.now(UTC)})

        if request.tool_name == "discover_buying_committee":
            draft, raw_key, normalized_key = await self._committee(
                request=request,
                operation=dispatched,
                snapshot_ref=snapshot_ref,
                provider_request_id=provider_request_id,
            )
            cost = Decimal("1.25")
        else:
            draft, raw_key, normalized_key = await self._account_fields(
                request=request,
                operation=dispatched,
                snapshot_ref=snapshot_ref,
                provider_request_id=provider_request_id,
            )
            cost = Decimal("1.00") if source_key == "exa_deep" else Decimal("0.50")
        self._lineage.values[operation_ref] = ProviderResultLineage(
            operation=dispatched,
            snapshot_ref=snapshot_ref,
            raw_response_artifact_refs=(f"artifact:{raw_key}",),
            retained_result_artifact_refs=(f"artifact:{raw_key}",),
            normalized_result_artifact_ref=f"artifact:{normalized_key}",
            provider_receipt_ref=f"r5-provider-receipt:{request.tool_call_id}",
            cost_settlement_ref=f"r5-cost-settlement:{request.tool_call_id}",
            provider_request_id=provider_request_id,
            provider_reported_cost_cents=cost,
            settled_cost_cents=cost,
        )
        return (draft,)

    async def _account_fields(
        self,
        *,
        request: Any,
        operation: ProviderOperationReservation,
        snapshot_ref: str,
        provider_request_id: str,
    ) -> tuple[ProviderResearchProjectionDraft, str, str]:
        values: Mapping[str, object] = self._field_values
        spans = {
            field: f"Grounded evidence for {field}: {values[field]}" for field in request.field_keys
        }
        async with self._conn_factory() as conn:
            raw_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.workspace_id,
                content=json.dumps({"evidence": spans}, sort_keys=True).encode(),
                media_type="application/json",
                source_key=operation.source_key,
            )
            normalized_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.workspace_id,
                content=json.dumps({"fields": values}, sort_keys=True).encode(),
                media_type="application/json",
                source_key=operation.source_key,
            )
            projections: list[ResearchFieldResultProjection] = []
            for field_key in request.field_keys:
                claim = Claim(
                    entity_id=EntityId(request.target_entity_id),
                    entity_type=EntityType.ACCOUNT,
                    field_key=field_key,
                    value_json=cast(Any, values[field_key]),
                    source_url="https://example.test/account-evidence",
                    source_key=operation.source_key,
                    artifact_key=raw_key,
                    source_operation_ref=operation.operation_ref,
                    source_snapshot_ref=snapshot_ref,
                    source_request_ref=provider_request_id,
                    source_tier=4 if operation.source_key == "exa_deep" else 1,
                    extraction_method=(
                        ExtractionMethod.LLM_SYNTHESIS
                        if operation.source_key == "exa_deep"
                        else ExtractionMethod.API
                    ),
                    evidence_span=spans[field_key],
                    confidence=0.91,
                    run_id=RunId(request.research_run_id),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                    workspace_id=operation.workspace_id,
                    product_id=current_entity_research_tool_execution().context.authorization.product_id,
                )
                claim_id = await insert_claim(conn, claim, validate_field=False)
                projections.append(
                    ResearchFieldResultProjection(
                        field_key=field_key,
                        outcome=ResearchFieldOutcome.FOUND,
                        value=cast(Any, values[field_key]),
                        claim_delta=ResearchClaimDelta.ACCEPTED,
                        claim_refs=(f"claim:{claim_id}",),
                        evidence=(
                            ResearchEvidenceProjection(
                                evidence_ref=f"research-evidence:{uuid4()}",
                                source_key=operation.source_key,
                                provider_source_id=provider_request_id,
                                source_url="https://example.test/account-evidence",
                                artifact_ref=f"artifact:{raw_key}",
                                evidence_span=spans[field_key],
                            ),
                        ),
                        confidence=0.91,
                        verification_status="unverified",
                    )
                )
        return (
            ProviderResearchProjectionDraft(
                operation=operation,
                snapshot_ref=snapshot_ref,
                requested_field_keys=request.field_keys,
                fields=tuple(projections),
            ),
            raw_key,
            normalized_key,
        )

    async def _committee(
        self,
        *,
        request: Any,
        operation: ProviderOperationReservation,
        snapshot_ref: str,
        provider_request_id: str,
    ) -> tuple[ProviderResearchProjectionDraft, str, str]:
        semantic = DiscoverBuyingCommitteeInput.model_validate(
            current_entity_research_tool_execution().call.arguments
        )
        scope = semantic.buying_unit_scope
        spans = {
            str(self._contacts[0]): "Jordan Lee is VP Operations in the Boston office.",
            str(self._contacts[1]): "Morgan Patel is CFO in the Boston office.",
        }
        async with self._conn_factory() as conn:
            evidence_ref = scope.evidence_refs[0]
            evidence_id = UUID(evidence_ref.removeprefix("research-evidence:"))
            in_scope = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM entity_research_result_evidence evidence "
                        "JOIN entity_research_result result ON result.result_id=evidence.result_id "
                        "JOIN entity_research_tool_request request_row "
                        "ON request_row.tool_request_id=result.tool_request_id "
                        "WHERE evidence.evidence_id=:evidence_id AND request_row.job_id=:job_id"
                    ),
                    {"evidence_id": evidence_id, "job_id": request.job_id},
                )
            ).scalar_one_or_none()
            assert in_scope == 1
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_committee_scope
                        (scope_id, tool_request_id, research_run_id, job_id, workspace_id,
                         account_entity_id, scope_json, scope_sha256)
                    VALUES (:scope_id, :tool_request_id, :run_id, :job_id, :workspace_id,
                            :account_id, CAST(:scope_json AS jsonb), :scope_sha)
                    """
                ),
                {
                    "scope_id": scope.scope_id,
                    "tool_request_id": request.tool_call_id,
                    "run_id": request.research_run_id,
                    "job_id": request.job_id,
                    "workspace_id": operation.workspace_id,
                    "account_id": request.target_entity_id,
                    "scope_json": serialize_value_json(scope.model_dump(mode="json")),
                    "scope_sha": canonical_sha256(scope),
                },
            )
            raw_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.workspace_id,
                content=json.dumps({"people": spans}, sort_keys=True).encode(),
                media_type="application/json",
                source_key=operation.source_key,
            )
            normalized_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.workspace_id,
                content=json.dumps(
                    {"office": "Boston", "contacts": [str(value) for value in self._contacts]},
                    sort_keys=True,
                ).encode(),
                media_type="application/json",
                source_key=operation.source_key,
            )
            subjects: list[ResearchDiscoveredSubjectProjection] = []
            for contact_id, title in zip(
                self._contacts,
                ("VP Operations", "Chief Financial Officer"),
                strict=True,
            ):
                discovery = discovery_claim(
                    entity_id=EntityId(contact_id),
                    entity_type=EntityType.CONTACT,
                    field_key="contact.discovery.committee_candidate",
                    value_json={"office": "Boston", "title": title},
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    confidence=0.95,
                    run_id=RunId(request.research_run_id),
                    research_mode=ResearchMode.COMMITTEE_DISCOVERY,
                    found_via="sumble_people",
                    matched_signal="same office and target buying function",
                    discovery_confidence=0.95,
                    source_url="https://example.test/organization-map",
                    evidence_span=spans[str(contact_id)],
                )
                discovery = revalidate_with(
                    discovery,
                    source_key=operation.source_key,
                    artifact_key=raw_key,
                    source_operation_ref=operation.operation_ref,
                    source_snapshot_ref=snapshot_ref,
                    source_request_ref=provider_request_id,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                    workspace_id=operation.workspace_id,
                    product_id=current_entity_research_tool_execution().context.authorization.product_id,
                )
                discovery_id = await insert_claim(conn, discovery, validate_field=False)
                professional = Claim(
                    entity_id=EntityId(contact_id),
                    entity_type=EntityType.CONTACT,
                    field_key="contact.profile.title",
                    value_json=title,
                    source_url="https://example.test/organization-map",
                    source_key=operation.source_key,
                    artifact_key=raw_key,
                    source_operation_ref=operation.operation_ref,
                    source_snapshot_ref=snapshot_ref,
                    source_request_ref=provider_request_id,
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    evidence_span=spans[str(contact_id)],
                    confidence=0.95,
                    run_id=RunId(request.research_run_id),
                    research_mode=ResearchMode.COMMITTEE_DISCOVERY,
                    identity_binding=IdentityBinding.STRONG,
                    use_class=UseClass.PROFESSIONAL_PUBLIC,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                    workspace_id=operation.workspace_id,
                    product_id=current_entity_research_tool_execution().context.authorization.product_id,
                )
                professional_id = await insert_claim(conn, professional, validate_field=False)
                subjects.append(
                    ResearchDiscoveredSubjectProjection(
                        subject_type=ResearchSubjectType.CONTACT,
                        target_entity_id=contact_id,
                        parent_account_id=request.target_entity_id,
                        strong_identity_claim_refs=(f"claim:{discovery_id}",),
                        association_evidence_refs=(f"claim:{discovery_id}",),
                        fields=(
                            ResearchFieldResultProjection(
                                field_key="contact.profile.title",
                                outcome=ResearchFieldOutcome.FOUND,
                                value=title,
                                claim_delta=ResearchClaimDelta.ACCEPTED,
                                claim_refs=(f"claim:{professional_id}",),
                                evidence=(
                                    ResearchEvidenceProjection(
                                        evidence_ref=f"research-evidence:{uuid4()}",
                                        source_key=operation.source_key,
                                        provider_source_id=provider_request_id,
                                        source_url="https://example.test/organization-map",
                                        artifact_ref=f"artifact:{raw_key}",
                                        evidence_span=spans[str(contact_id)],
                                    ),
                                ),
                                confidence=0.95,
                                verification_status="unverified",
                            ),
                        ),
                    )
                )
        return (
            ProviderResearchProjectionDraft(
                operation=operation,
                snapshot_ref=snapshot_ref,
                discovered_subjects=tuple(subjects),
            ),
            raw_key,
            normalized_key,
        )


def _account_envelope(
    *,
    account_id: UUID,
    workspace_id: str,
    project_id: str,
    product_id: str,
    project_run_id: UUID,
    profile_sha256: str,
    directive_ref: str,
    directive_sha256: str,
) -> EntityResearchRunEnvelope:
    base = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
    original = base.lifecycle.selection
    selection = EntityResearchSelection.model_validate(
        original.model_copy(
            update={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "product_id": product_id,
                "project_run_id": project_run_id,
                "directive_ref": directive_ref,
                "directive_sha256": directive_sha256,
                "subjects": (
                    original.subjects[0].model_copy(update={"subject_entity_id": account_id}),
                ),
                "admitted_field_keys": (_PAIN, _MOVES, _HIRING),
                "admitted_source_keys": ("exa_deep", "sumble_jobs", "sumble_people"),
                "field_source_authority": (
                    FieldSourceAuthority(field_key=_PAIN, source_keys=("exa_deep",)),
                    FieldSourceAuthority(field_key=_MOVES, source_keys=("exa_deep",)),
                    FieldSourceAuthority(
                        field_key=_HIRING,
                        source_keys=("sumble_jobs", "exa_deep"),
                    ),
                ),
                "committee_source_keys": ("sumble_people",),
                "research_questions": (
                    _QUALITATIVE_QUESTION,
                    _STRUCTURED_QUESTION,
                    _COMMITTEE_QUESTION,
                ),
            }
        ).model_dump(mode="python")
    )
    lifecycle = ResearchRunLifecycleContract.model_validate(
        base.lifecycle.model_copy(update={"selection": selection}).model_dump(mode="python")
    )
    original_job = base.jobs[0]
    authorization = EntityResearchJobAuthorization.model_validate(
        original_job.authorization.model_copy(
            update={
                "subject_entity_id": account_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "product_id": product_id,
                "project_run_id": project_run_id,
                "selection": selection,
                "agent_profile_ref": "agent-profile:account-research:v2",
                "agent_profile_sha256": profile_sha256,
            }
        ).model_dump(mode="python")
    )
    return EntityResearchRunEnvelope.model_validate(
        base.model_copy(
            update={
                "lifecycle": lifecycle,
                "jobs": (
                    original_job.model_copy(
                        update={
                            "authorization": authorization,
                            "budget_cap_cents": Decimal("10"),
                        }
                    ),
                ),
                "budget_cap_cents": Decimal("10"),
            }
        ).model_dump(mode="python")
    )


def test_r5_account_agent_observes_results_decides_and_finalizes_without_contact_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r5-artifacts")
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            await load_client_knowledge_pack(conn)
            await seed_source_manifests(conn)
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            workspace_id = fixture.discovery_fixture.workspace_id
            project_id = fixture.discovery_fixture.project_id
            product_id = fixture.discovery_fixture.product_id
            account_id = UUID(str(fixture.selected_account_id))
            _, prior_account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                product_id=product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(_PAIN, _MOVES, _HIRING),
                allowed_source_keys=("exa_deep", "sumble_jobs", "sumble_people"),
            )
            prior_directive = prior_account_spec.research_directive
            assert prior_directive is not None
            prior_account_run_id = RunId(uuid4())
            await insert_account_run(
                conn,
                account_run_id=prior_account_run_id,
                project_run_id=fixture.project_run_id,
                entity_id=fixture.selected_account_id,
                tier="high",
            )
            await pin_account_run_research_directive(
                conn,
                account_run_id=prior_account_run_id,
                pin=prior_directive,
            )
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                product_id=product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(_PAIN, _MOVES, _HIRING),
                allowed_source_keys=("exa_deep", "sumble_jobs", "sumble_people"),
                predecessor_id=prior_directive.directive_id,
            )
            directive = account_spec.research_directive
            assert directive is not None
            await insert_account_run(
                conn,
                account_run_id=fixture.expected_account_run_id,
                project_run_id=fixture.project_run_id,
                entity_id=fixture.selected_account_id,
                tier="high",
            )
            await pin_account_run_research_directive(
                conn,
                account_run_id=fixture.expected_account_run_id,
                pin=directive,
            )
            contacts = (
                UUID(
                    str(
                        await insert_contact_entity(
                            conn,
                            account_entity_id=fixture.selected_account_id,
                            full_name="Jordan Lee",
                            linkedin_url="https://linkedin.com/in/jordan-lee-r5",
                        )
                    )
                ),
                UUID(
                    str(
                        await insert_contact_entity(
                            conn,
                            account_entity_id=fixture.selected_account_id,
                            full_name="Morgan Patel",
                            linkedin_url="https://linkedin.com/in/morgan-patel-r5",
                        )
                    )
                ),
            )
            connection = _NestedConnFactory(conn)
            envelope = _account_envelope(
                account_id=account_id,
                workspace_id=workspace_id,
                project_id=project_id,
                product_id=product_id,
                project_run_id=UUID(str(fixture.project_run_id)),
                profile_sha256=account_research_profile_sha256(),
                directive_ref=directive.directive_ref,
                directive_sha256=directive.canonical_json_sha256,
            )
            jobs = DbEntityResearchJobStore(conn_factory=connection)
            await jobs.launch(envelope)
            authorization = envelope.jobs[0].authorization
            stored_job = await jobs.get_job(authorization.job_id)
            assert stored_job is not None
            live_job = stored_job.model_copy(
                update={"active_worker_id": "r5-test-worker", "lease_generation": 1}
            )
            fence = EntityResearchExecutionFence(
                task_id=uuid4(),
                worker_id="r5-test-worker",
                lease_generation=1,
                task_attempt=1,
            )
            lineage = _FixtureLineageReader()
            providers = _FixtureAccountProviders(
                storage=storage,
                conn_factory=connection,
                contacts=contacts,
                lineage=lineage,
            )
            exa_payload = _exa_payload()
            exa_payload["costDollars"]["total"] = 0.07
            exa_transport = _ExaTransport(exa_payload)
            exa_action = ExaAccountSemanticResearchAction(
                workspace_id=workspace_id,
                project_id=project_id,
                project_run_id=ProjectRunId(fixture.project_run_id),
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                research_directive=directive,
                acquisition=ExaDeepAcquisitionCoordinator(
                    transport=exa_transport,
                    storage=storage,
                    conn_factory=connection,
                ),
                snapshots=ExaDeepSnapshotResolverProvider(
                    storage=storage,
                    conn_factory=connection,
                ),
                projector=ExaEntityResearchProjectionBuilder(
                    storage=storage,
                    conn_factory=connection,
                ),
                conn_factory=connection,
                observation_window=f"m8d-r5:{authorization.research_run_id}:account",
                research_intent="Grounded referral operations and strategic change research.",
                freshness_policy_ref="freshness:m8d-r5-test-v1",
                freshness_seconds=3600,
                cost_cents_reserved_per_bundle=Decimal("8"),
            )
            result_store = EntityResearchResultStore(
                storage=storage,
                conn_factory=connection,
                lineage_readers={
                    ExternalResearchResultLineageReader.provider_kind: (
                        ExternalResearchResultLineageReader(conn_factory=connection)
                    ),
                    lineage.provider_kind: lineage,
                },
            )
            tool_factory = GovernedEntityResearchToolFactory(
                requests=EntityResearchToolRequestStore(
                    conn_factory=connection,
                    storage=storage,
                ),
                causation=EntityResearchProviderCausationStore(conn_factory=connection),
                results=result_store,
            )
            state = AccountResearchStateStore(conn_factory=connection)
            actions = {
                authorization.job_id: {
                    "research_account_deep": ProviderActionBinding(
                        action=exa_action,
                        version=1,
                    ),
                    "enrich_account": ProviderActionBinding(action=providers, version=1),
                    "discover_buying_committee": ProviderActionBinding(
                        action=providers,
                        version=1,
                    ),
                }
            }
            resolver = AccountResearchDefinitionResolver(
                tools=tool_factory,
                state=state,
                provider_actions=StaticAccountResearchProviderActions(actions),
                model_policy=ModelPolicy(
                    model_id="r5-test-model",
                    timeout_s=10,
                    max_retries=0,
                    max_output_tokens=4096,
                    temperature=0,
                ),
                conn_factory=connection,
            )
            definition = await resolver.resolve(job=live_job, fence=fence)
            # The steering bundle the mind is actually built from: the authorization-pinned
            # profile stays v2 (every launched job carries that ref at rest), while the prompt and
            # both skills — the decision rubric and the tool operations manual — are the live v3
            # steering. The manual must reach the resolved system prompt, not just the catalog.
            resources = definition.context.resources
            assert (resources.profile.ref, resources.profile.version) == (
                "agent-profile:account-research:v2",
                "v2",
            )
            assert resources.profile.sha256 == authorization.agent_profile_sha256
            assert (resources.prompt.ref, resources.prompt.version) == (
                "agent-prompt:account-research:v3",
                "v3",
            )
            assert tuple((skill.ref, skill.version) for skill in resources.skills) == (
                ("agent-skill:governed-account-research:v3", "v3"),
                ("agent-skill:account-tool-operations-manual:v3", "v3"),
            )
            manual = " ".join(resources.skills[1].body.split())
            assert "Never send an identical call after a refusal." in manual
            # The confirmed committee plan reaches the agent before its first tool choice.
            assert directive.directive_ref in definition.task_instruction
            assert "- functions: Operations" in definition.task_instruction
            assert "- levels: Director" in definition.task_instruction
            assert "- personas: champion" in definition.task_instruction
            assert "- candidate_cap: 4" in definition.task_instruction
            guard = AccountResearchExecutionGuard(conn_factory=connection)
            with pytest.raises(
                AccountResearchAuthorityError,
                match="first Exa account call must include every primary Exa field",
            ):
                await guard.authorize_tool(
                    context=definition.context,
                    call=EntityResearchToolCall(
                        tool_call_id="r5-forbidden-single-field-exa",
                        tool_name="research_account_deep",
                        tool_version=1,
                        tool_input_sha256="f" * 64,
                        arguments={
                            "field_keys": [_PAIN],
                            "source_keys": ["exa_deep"],
                            "questions": [_QUALITATIVE_QUESTION],
                        },
                    ),
                    journal_event_ref="entity-agent-journal:r5-forbidden",
                )
            with pytest.raises(
                AccountResearchAuthorityError,
                match="Exa fallback fields require a preceding structured-source attempt",
            ):
                await guard.authorize_tool(
                    context=definition.context,
                    call=EntityResearchToolCall(
                        tool_call_id="r5-forbidden-premature-exa-fallback",
                        tool_name="research_account_deep",
                        tool_version=1,
                        tool_input_sha256="e" * 64,
                        arguments={
                            "field_keys": [_HIRING],
                            "source_keys": ["exa_deep"],
                            "questions": [_STRUCTURED_QUESTION],
                        },
                    ),
                    journal_event_ref="entity-agent-journal:r5-forbidden-fallback",
                )
            model = _DecisionModel(account_id=account_id, scope_id=uuid4())
            journal = DbEntityResearchAgentJournal(conn_factory=connection)
            create_agent_calls: list[str] = []
            real_create_agent: Any = runtime_module.create_agent

            def spy_create_agent(*args: object, **kwargs: object) -> Any:
                create_agent_calls.append(str(kwargs.get("name")))
                return real_create_agent(*args, **kwargs)

            monkeypatch.setattr(runtime_module, "create_agent", spy_create_agent)
            runtime = EntityResearchAgentRuntime(
                factory=EntityResearchAgentFactory(
                    models=_Models(model),
                    journal=journal,
                    guard=guard,
                ),
                checkpointers=Checkpointers(),
                journal=journal,
                finalizer=AccountResearchFinalizationEngine(conn_factory=connection),
            )
            outcome = await runtime.run(definition=definition)
            assert isinstance(outcome, EntityResearchAgentResult)
            assert outcome.finalization_receipt is not None
            assert (
                outcome.finalization_receipt.proposal.outcome
                is ResearchFinalizationOutcome.NEEDS_REVIEW
            )
            assert outcome.finalization_receipt.verification.all_passed()
            assert create_agent_calls == ["clue-entity-account"]
            assert model.observed_committee_plan == {
                "directive_ref": directive.directive_ref,
                "functions": ["Operations"],
                "levels": ["Director"],
                "teams": [],
                "personas": ["champion"],
                "candidate_cap": 4,
                "questions": [],
            }
            assert model.observed_first_result
            assert model.justification is not None and "hiring field" in model.justification
            assert exa_transport.calls == 1
            assert providers.calls == ["enrich_account", "discover_buying_committee"]
            assert "research_account_deep" in model.bound_tools
            assert "discover_buying_committee" in model.bound_tools
            assert "record_committee_role_inferences" in model.bound_tools
            assert not any(name.startswith("research_contact") for name in model.bound_tools)

            scope = WorkspaceScope.for_workspace(workspace_id)
            inferred = await claims_for(
                conn,
                EntityId(contacts[0]),
                ROLE_ON_COMMITTEE,
                scope=scope,
            )
            personas = await claims_for(conn, EntityId(contacts[0]), PERSONA, scope=scope)
            assert len(inferred) == len(personas) == 1
            role_claim = inferred[0]
            persona_claim = personas[0]
            assert role_claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
            assert int(role_claim.source_tier) == 4
            assert role_claim.provenance_kind is ClaimProvenanceKind.PLATFORM_INFERRED
            assert role_claim.identity_binding is IdentityBinding.STRONG
            assert role_claim.value_json == {
                "role": Persona.CHAMPION.value,
                "confidence": 0.87,
                "plausible": True,
                "rationale": "The operations leader owns the workflow.",
            }
            assert persona_claim.value_json == Persona.CHAMPION.value
            assert role_claim.evidence_span == "Jordan Lee is VP Operations in the Boston office."
            assert role_claim.source_url == "https://example.test/organization-map"
            assert role_claim.run_id == RunId(authorization.research_run_id)
            coverage_claim_refs = set(
                (
                    await conn.execute(
                        text(
                            "SELECT claim_refs FROM entity_research_account_coverage "
                            "WHERE job_id=:job_id ORDER BY created_at DESC LIMIT 1"
                        ),
                        {"job_id": authorization.job_id},
                    )
                ).scalar_one()
            )
            assert {
                f"claim:{role_claim.id}",
                f"claim:{persona_claim.id}",
            } <= coverage_claim_refs
            persisted_coverage = (
                (
                    await conn.execute(
                        text(
                            "SELECT committee_status, review_flags, coverage_json "
                            "FROM entity_research_account_coverage WHERE job_id=:job_id "
                            "ORDER BY created_at DESC LIMIT 1"
                        ),
                        {"job_id": authorization.job_id},
                    )
                )
                .mappings()
                .one()
            )
            assert persisted_coverage["committee_status"] == "needs_review"
            assert "committee_roles_uninferred" in persisted_coverage["review_flags"]
            assert persisted_coverage["coverage_json"]["committee_needs_review"] == 1
            assert (
                await claims_for(
                    conn,
                    EntityId(contacts[1]),
                    ROLE_ON_COMMITTEE,
                    scope=scope,
                )
                == []
            )
            human_count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim WHERE run_id=:run_id "
                        "AND extraction_method='human'"
                    ),
                    {"run_id": authorization.research_run_id},
                )
            ).scalar_one()
            assert human_count == 0

            counts = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT
                              (SELECT count(*) FROM entity_research_result result
                               JOIN entity_research_tool_request request_row
                                 ON request_row.tool_request_id=result.tool_request_id
                               WHERE request_row.job_id=:job_id) AS result_count,
                              (SELECT count(*) FROM entity_research_account_committee_scope
                               WHERE job_id=:job_id) AS scope_count,
                              (SELECT count(*) FROM entity_research_account_coverage
                               WHERE job_id=:job_id) AS coverage_count,
                              (SELECT count(*) FROM entity_research_account_finalization_intent
                               WHERE job_id=:job_id) AS intent_count,
                              (SELECT count(*) FROM entity_research_tool_request
                               WHERE research_run_id=:run_id AND subject_type='contact')
                                AS contact_request_count,
                              (SELECT spent_cents FROM entity_research_job
                               WHERE job_id=:job_id) AS job_spent,
                              (SELECT spent_cents FROM entity_research_run
                               WHERE research_run_id=:run_id) AS run_spent
                            """
                        ),
                        {"job_id": authorization.job_id, "run_id": authorization.research_run_id},
                    )
                )
                .mappings()
                .one()
            )
            assert counts["result_count"] == 3
            assert counts["scope_count"] == 1
            assert counts["coverage_count"] == 1
            assert counts["intent_count"] == 1
            assert counts["contact_request_count"] == 0
            assert Decimal(counts["job_spent"]) == Decimal("8.75")
            assert Decimal(counts["run_spent"]) == Decimal("8.75")

            # FI-2 P2: the account claims this run wrote carry a per-tool-call materialization run
            # id (not the launch research run id) — every one of them is registered and
            # project-attributed, so the project lens can back-join them.
            unattributed = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim "
                        "WHERE entity_id=:account_id AND source_key='exa_deep' "
                        "AND run_id NOT IN (SELECT run_id FROM run_lineage "
                        "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                        "AND kind='entity_research')"
                    ),
                    {
                        "account_id": authorization.subject_entity_id,
                        "workspace_id": authorization.workspace_id,
                        "project_id": authorization.project_id,
                    },
                )
            ).scalar_one()
            assert unattributed == 0
            written_claims = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim "
                        "WHERE entity_id=:account_id AND source_key='exa_deep'"
                    ),
                    {"account_id": authorization.subject_entity_id},
                )
            ).scalar_one()
            assert written_claims > 0

    run_async(scenario())


def test_r5_committee_input_forbids_field_and_follow_up_authority() -> None:
    account_id = uuid4()
    base: dict[str, object] = {
        "field_keys": [],
        "source_keys": ["sumble_people"],
        "questions": ["Which exact people form this buying committee?"],
        "buying_unit_scope": {
            "scope_id": str(uuid4()),
            "account_entity_id": str(account_id),
            "office_label": "Boston office",
            "locality": "Boston",
            "region": "Massachusetts",
            "target_functions": ["Operations", "Finance"],
            "evidence_refs": [f"research-evidence:{uuid4()}"],
        },
    }
    assert DiscoverBuyingCommitteeInput.model_validate(base).field_keys == ()

    with pytest.raises(ValidationError) as field_error:
        DiscoverBuyingCommitteeInput.model_validate(
            {**base, "field_keys": ["account.operational_pain"]}
        )
    assert field_error.value.errors()[0]["loc"] == ("field_keys",)
    with pytest.raises(ValidationError) as lineage_error:
        DiscoverBuyingCommitteeInput.model_validate(
            {
                **base,
                "parent_operation_ref": f"provider-operation:{uuid4()}",
                "parent_observation_ref": f"research-result:{uuid4()}",
                "follow_up_reason": "contradiction_resolution",
            }
        )
    assert {item["loc"] for item in lineage_error.value.errors()} == {
        ("parent_operation_ref",),
        ("parent_observation_ref",),
        ("follow_up_reason",),
    }


def _committee_call(*, account_id: UUID, target_functions: Sequence[str]) -> AccountBuyingUnitScope:
    """One agent-authored committee tool call, validated exactly as the engine receives it."""

    return DiscoverBuyingCommitteeInput.model_validate(
        {
            "field_keys": [],
            "source_keys": ["sumble_people"],
            "questions": ["Which exact people form this buying committee?"],
            "buying_unit_scope": {
                "scope_id": str(uuid4()),
                "account_entity_id": str(account_id),
                "office_label": "Boston office",
                "locality": "Boston",
                "region": "Massachusetts",
                "target_functions": list(target_functions),
                "evidence_refs": [f"research-evidence:{uuid4()}"],
            },
        }
    ).buying_unit_scope


_R5_TEST_COMMITTEE_PLAN = ResearchCommitteePlan(
    functions=("Operations", "Finance"),
    levels=("Director",),
    personas=("champion",),
    candidate_cap=4,
)


def test_r5_committee_scope_cannot_invent_a_function_outside_the_confirmed_plan() -> None:
    account_id = uuid4()
    with pytest.raises(EntityResearchGovernedRejection) as invented:
        SumbleCommitteeSemanticResearchAction._validate_scope_against_plan(
            _committee_call(account_id=account_id, target_functions=["Operations", "Marketing"]),
            plan=_R5_TEST_COMMITTEE_PLAN,
        )
    assert "Marketing" in str(invented.value)
    assert "Operations, Finance" in str(invented.value)

    # A plan function is a confirmed selector, never a substring to widen from.
    for widened in (["Operation"], ["Operations and Finance"], ["Financial Planning"]):
        with pytest.raises(EntityResearchGovernedRejection):
            SumbleCommitteeSemanticResearchAction._validate_scope_against_plan(
                _committee_call(account_id=account_id, target_functions=widened),
                plan=_R5_TEST_COMMITTEE_PLAN,
            )


def test_r5_committee_scope_within_the_confirmed_plan_passes_the_engine_check() -> None:
    account_id = uuid4()
    # Narrowing the confirmed plan for one office is the agent's job; casing is not authority.
    for admitted in (["Operations"], ["operations", "FINANCE"], ["Operations", "Finance"]):
        SumbleCommitteeSemanticResearchAction._validate_scope_against_plan(
            _committee_call(account_id=account_id, target_functions=admitted),
            plan=_R5_TEST_COMMITTEE_PLAN,
        )
    # A plan that confirmed no functions bounds nothing, and the static R5 seam carries no plan.
    for unbounded in (ResearchCommitteePlan(), None):
        SumbleCommitteeSemanticResearchAction._validate_scope_against_plan(
            _committee_call(account_id=account_id, target_functions=["Marketing"]),
            plan=unbounded,
        )


def test_r5_contract_separates_committee_sources_and_allows_grounded_empty_committee() -> None:
    base = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH).lifecycle.selection
    assert base.committee_source_keys == ("sumble_people",)
    assert all(
        "sumble_people" not in authority.source_keys for authority in base.field_source_authority
    )
    operation = ProviderOperationReservation(
        provider_kind="sumble_committee",
        operation_ref=f"committee-operation:{uuid4()}",
        workspace_id=base.workspace_id,
        project_id=base.project_id,
        project_run_id=base.project_run_id,
        subject_type=ResearchSubjectType.ACCOUNT,
        target_entity_id=base.subjects[0].subject_entity_id,
        source_key="sumble_people",
        field_keys=(),
        request_artifact_ref="artifact:request",
        reserved_at=datetime.now(UTC),
        observation_disposition=ProviderObservationDisposition.CAUSED,
    )
    draft = ProviderResearchProjectionDraft(
        operation=operation,
        snapshot_ref="committee-snapshot:confirmed-empty",
        confirmed_empty_discovery=True,
    )
    assert draft.confirmed_empty_discovery
    persisted = PersistedResearchToolResult(
        subject_type=ResearchSubjectType.ACCOUNT,
        target_entity_id=base.subjects[0].subject_entity_id,
        operation_ref=operation.operation_ref,
        result_ref=f"research-result:{uuid4()}",
        request_artifact_ref="artifact:request",
        raw_response_artifact_refs=("artifact:raw",),
        retained_result_artifact_refs=("artifact:retained",),
        normalized_result_artifact_ref="artifact:normalized",
        provider_receipt_ref="receipt:committee",
        cost_settlement_ref="settlement:committee",
        confirmed_empty_discovery=True,
        delivery=ResearchResultDelivery.INLINE_COMPLETE,
        provider_reported_cost_cents=Decimal(0),
        cost_cents=Decimal(0),
    )
    assert persisted.confirmed_empty_discovery
    assert AccountResearchStateStore._committee_coverage_status(
        result_count=1,
        member_count=0,
        scope_count=1,
        ambiguous_count=0,
        confirmed_empty_count=1,
    ) == ("complete", ())
    assert AccountResearchStateStore._committee_coverage_status(
        result_count=1,
        member_count=0,
        scope_count=1,
        ambiguous_count=0,
        confirmed_empty_count=0,
    ) == ("partial", ("committee_no_identity_admitted_member",))


def test_sumble_committee_wait_preserves_causal_owner_and_labels_only_joiners() -> None:
    assert (
        SumbleCommitteeSemanticResearchAction._wait_disposition(caused=True)
        is ProviderObservationDisposition.CAUSED
    )
    assert (
        SumbleCommitteeSemanticResearchAction._wait_disposition(caused=False)
        is ProviderObservationDisposition.JOINED
    )


def test_r5_committee_office_filter_admits_only_people_facts_in_the_exact_buying_unit() -> None:
    scope = AccountBuyingUnitScope(
        scope_id=uuid4(),
        account_entity_id=uuid4(),
        office_label="Boston patient-access office",
        facility_name="Boston Gastro Center",
        locality="Boston",
        region="Massachusetts",
        business_unit="Patient Access",
        target_functions=("Operations", "Finance"),
        evidence_refs=("research-evidence:7c9e6f1a-2b3d-4e5f-8a91-0c1d2e3f4a5b",),
        match_policy="same_office_strict",
    )

    def candidate(
        *, name: str, locality: str, function: str, with_people_fact: bool = True
    ) -> CommitteePersonCandidate:
        facts = (
            (
                CandidateProfessionalFact(
                    field_key="contact.current_title",
                    value_json={
                        "title": "VP Operations",
                        "office": "Boston Gastro Center",
                        "locality": locality,
                        "region": "Massachusetts",
                        "business_unit": "Patient Access",
                        "function": function,
                    },
                    provenance_kind=CandidateFactProvenance.PROVIDER_RETURNED,
                    source_key=PEOPLE_SOURCE_KEY,
                    source_tier=1,
                    source_url="https://sumble.example/people/fixture",
                    evidence_span="Provider-returned current role and office.",
                    artifact_key="sumble/people/fixture",
                    source_operation_ref="committee-operation:fixture",
                    source_snapshot_ref="committee-snapshot:fixture",
                    source_request_ref="sumble-request:fixture",
                ),
            )
            if with_people_fact
            else ()
        )
        return CommitteePersonCandidate(
            source_key=PEOPLE_SOURCE_KEY,
            linkedin_url=f"https://linkedin.com/in/{name.casefold().replace(' ', '-')}",
            full_name=name,
            title=f"VP {function}",
            job_function=function,
            team_names=("Patient Access",),
            geo={"city": locality, "region": "Massachusetts"},
            source_url="https://sumble.example/people/fixture",
            professional_facts=facts,
        )

    selected_candidate = candidate(name="Boston Operator", locality="Boston", function="Operations")
    wrong_function = candidate(name="Boston Engineer", locality="Boston", function="Engineering")
    wrong_office = candidate(name="Seattle Operator", locality="Seattle", function="Operations")
    ungrounded_office = candidate(
        name="Unknown Operator",
        locality="Boston",
        function="Operations",
        with_people_fact=False,
    )
    selected, excluded, ambiguous = SumbleCommitteeSemanticResearchAction._office_candidates(
        (selected_candidate, wrong_function, wrong_office, ungrounded_office),
        scope=scope,
    )
    assert selected == (selected_candidate,)
    assert excluded == 1
    assert ambiguous == 2


def test_r5_committee_filter_accepts_exact_provider_employer_as_organization_wide_unit() -> None:
    account_id = uuid4()
    scope = AccountBuyingUnitScope(
        scope_id=uuid4(),
        account_entity_id=account_id,
        office_label="Exact organization-wide buying unit",
        business_unit="New Jersey Brain and Spine",
        target_functions=("Executive", "Operations"),
        evidence_refs=("research-evidence:1d2e3f4a-5b6c-4d7e-8f90-a1b2c3d4e5f6",),
    )

    def candidate(*, name: str, employer: str) -> CommitteePersonCandidate:
        facts = (
            CandidateProfessionalFact(
                field_key="contact.organization_relationship",
                value_json={
                    "relationship": "current_employee",
                    "basis": "provider_returned_current_employer",
                    "organization_id": 42,
                    "organization_name": employer,
                },
                provenance_kind=CandidateFactProvenance.PROVIDER_RETURNED,
                source_key=PEOPLE_SOURCE_KEY,
                source_tier=1,
                source_url="https://sumble.example/people/fixture",
                evidence_span="Provider-returned person row.",
                artifact_key="sumble/people/fixture",
                source_operation_ref="committee-operation:fixture",
                source_snapshot_ref="committee-snapshot:fixture",
                source_request_ref="sumble-request:fixture",
            ),
        )
        return CommitteePersonCandidate(
            source_key=PEOPLE_SOURCE_KEY,
            linkedin_url=f"https://linkedin.com/in/{name.casefold().replace(' ', '-')}",
            full_name=name,
            title="Chief Executive Officer",
            job_function="Executive",
            geo={"city": "Bloomingdale", "region": "New Jersey"},
            source_url="https://sumble.example/people/fixture",
            professional_facts=facts,
        )

    exact = candidate(name="Exact Executive", employer="New Jersey Brain and Spine")
    foreign = candidate(name="Foreign Executive", employer="Other Practice")
    selected, excluded, ambiguous = SumbleCommitteeSemanticResearchAction._office_candidates(
        (exact, foreign),
        scope=scope,
    )

    assert selected == (exact,)
    assert excluded == 0
    assert ambiguous == 1


def test_r5_committee_filter_matches_provider_values_never_schema_keys() -> None:
    """A scope term must match provider-returned evidence, not our own JSON structure.

    Serializing whole fact objects let a business unit named like a schema key (for example
    "Relationship" or "Current Employee") match every candidate through the serialized keys
    ``relationship``/``current_employee`` rather than through any provider value.
    """

    account_id = uuid4()
    scope = AccountBuyingUnitScope(
        scope_id=uuid4(),
        account_entity_id=account_id,
        office_label="Organization-wide unit named like a schema key",
        business_unit="Current Employee",
        target_functions=("Executive",),
        evidence_refs=("research-evidence:1d2e3f4a-5b6c-4d7e-8f90-a1b2c3d4e5f6",),
    )
    candidate = CommitteePersonCandidate(
        source_key=PEOPLE_SOURCE_KEY,
        linkedin_url="https://linkedin.com/in/schema-key-candidate",
        full_name="Schema Key Candidate",
        title="Chief Executive Officer",
        job_function="Executive",
        geo={"city": "Bloomingdale", "region": "New Jersey"},
        source_url="https://sumble.example/people/fixture",
        professional_facts=(
            CandidateProfessionalFact(
                field_key="contact.organization_relationship",
                value_json={
                    "relationship": "current_employee",
                    "organization_id": 42,
                    "organization_name": "New Jersey Brain and Spine",
                },
                provenance_kind=CandidateFactProvenance.PROVIDER_RETURNED,
                source_key=PEOPLE_SOURCE_KEY,
                source_tier=1,
                source_url="https://sumble.example/people/fixture",
                evidence_span="Provider-returned person row.",
                artifact_key="sumble/people/fixture",
                source_operation_ref="committee-operation:fixture",
                source_snapshot_ref="committee-snapshot:fixture",
                source_request_ref="sumble-request:fixture",
            ),
        ),
    )
    selected, excluded, ambiguous = SumbleCommitteeSemanticResearchAction._office_candidates(
        (candidate,),
        scope=scope,
    )
    # No provider value contains "Current Employee": the candidate routes to review instead of
    # being admitted through the serialized ``current_employee`` schema token.
    assert selected == ()
    assert ambiguous == 1
    assert excluded == 0


def test_r5_office_gate_admits_the_live_paramus_candidate_vetoed_by_region_spelling() -> None:
    """Live canary regression (2026-08-06, njbrainspine.com, real Sumble rows).

    The agent declared a strict Paramus office with region "NJ"; Sumble spells "New Jersey".
    Requiring every declared location tier as a raw substring vetoed a provider-perfect
    candidate (locality matched, exact current employer, admitted function). The most specific
    declared tier now governs; coarser containers corroborate but cannot veto — and a candidate
    evidencing no declared tier still routes to review, never to admission.
    """

    account_id = uuid4()
    scope = AccountBuyingUnitScope(
        scope_id=uuid4(),
        account_entity_id=account_id,
        office_label="New Jersey Brain and Spine — Paramus office",
        facility_name="650 From Road, Suite 220",
        locality="Paramus",
        region="NJ",
        country="United States",
        target_functions=("Executive", "Operations", "Marketing"),
        evidence_refs=("research-evidence:2e3f4a5b-6c7d-4e8f-9a01-b2c3d4e5f6a7",),
        match_policy="same_office_strict",
    )

    def live_candidate(*, name: str, title: str, function: str, location: str):
        return CommitteePersonCandidate(
            source_key=PEOPLE_SOURCE_KEY,
            linkedin_url=f"https://linkedin.com/in/{name.casefold().replace(' ', '-')}",
            full_name=name,
            title=title,
            job_function=function,
            geo={},
            source_url="https://sumble.example/people/live",
            professional_facts=(
                CandidateProfessionalFact(
                    field_key="contact.current_location",
                    value_json={"location": location, "country": "United States"},
                    provenance_kind=CandidateFactProvenance.PROVIDER_RETURNED,
                    source_key=PEOPLE_SOURCE_KEY,
                    source_tier=1,
                    source_url="https://sumble.example/people/live",
                    evidence_span="Provider-returned person row.",
                    artifact_key="sumble/people/live",
                    source_operation_ref="committee-operation:live",
                    source_snapshot_ref="committee-snapshot:live",
                    source_request_ref="sumble-request:live",
                ),
            ),
        )

    paramus_cmo = live_candidate(
        name="Amanda Haro",
        title="Chief Marketing Officer",
        function="Marketing",
        location="Paramus, New Jersey, United States",
    )
    bloomingdale_ceo = live_candidate(
        name="Jeanmarie Falco",
        title="Chief Executive Officer",
        function="Executive",
        location="Bloomingdale, New Jersey, United States",
    )
    nyc_manager = live_candidate(
        name="Angelica Ienczmionka",
        title="Manager, Business Operations & Strategy",
        function="Operations",
        location="New York, New York, United States",
    )
    selected, excluded, ambiguous = SumbleCommitteeSemanticResearchAction._office_candidates(
        (paramus_cmo, bloomingdale_ceo, nyc_manager),
        scope=scope,
    )
    assert selected == (paramus_cmo,)
    assert excluded == 0
    assert ambiguous == 2  # other-office candidates stay review-routed, never admitted

    # A region-only scope matches either spelling of the same US state — and nothing else.
    region_only = AccountBuyingUnitScope(
        scope_id=uuid4(),
        account_entity_id=account_id,
        office_label="New Jersey organization-wide unit",
        region="NJ",
        target_functions=("Executive", "Operations", "Marketing"),
        evidence_refs=("research-evidence:2e3f4a5b-6c7d-4e8f-9a01-b2c3d4e5f6a7",),
        match_policy="same_office_strict",
    )
    selected, _excluded, ambiguous = SumbleCommitteeSemanticResearchAction._office_candidates(
        (paramus_cmo, bloomingdale_ceo, nyc_manager),
        scope=region_only,
    )
    assert selected == (paramus_cmo, bloomingdale_ceo)
    assert ambiguous == 1


def _millennium_candidates() -> tuple[
    CommitteePersonCandidate,
    CommitteePersonCandidate,
    CommitteePersonCandidate,
    CommitteePersonCandidate,
]:
    """The live v8 committee shape (job 4e1bc4fd / operation 8500325f, 2026-08-20).

    Millennium Physician Group is a 913-person multi-site physician group whose declared scope was
    the Fort Myers headquarters.  Sumble returned seven real people; the provider's own location
    values placed almost none of them in Fort Myers, so the strict office gate admitted zero.
    """

    def candidate(
        *, name: str, title: str, function: str, location: str | None, with_people_fact: bool = True
    ) -> CommitteePersonCandidate:
        facts: tuple[CandidateProfessionalFact, ...] = ()
        if with_people_fact:
            value: dict[str, Any] = {"country": "United States"}
            if location is not None:
                value["location"] = location
            facts = (
                CandidateProfessionalFact(
                    field_key="contact.current_location",
                    value_json=value,
                    provenance_kind=CandidateFactProvenance.PROVIDER_RETURNED,
                    source_key=PEOPLE_SOURCE_KEY,
                    source_tier=1,
                    source_url="https://sumble.example/people/millennium",
                    evidence_span="Provider-returned person row.",
                    artifact_key="sumble/people/millennium",
                    source_operation_ref="committee-operation:millennium",
                    source_snapshot_ref="committee-snapshot:millennium",
                    source_request_ref="sumble-request:millennium",
                ),
            )
        return CommitteePersonCandidate(
            source_key=PEOPLE_SOURCE_KEY,
            linkedin_url=f"https://linkedin.com/in/{name.casefold().replace(' ', '-')}",
            full_name=name,
            title=title,
            job_function=function,
            geo={},
            source_url="https://sumble.example/people/millennium",
            professional_facts=facts,
        )

    fort_myers_engineer = candidate(
        name="Fort Myers Engineer",
        title="Staff Software Engineer",
        function="Engineering",
        location="Fort Myers, Florida, United States",
    )
    naples_executive = candidate(
        name="Naples Executive",
        title="Chief Executive Officer",
        function="Executive",
        location="Naples, Florida, United States",
    )
    unplaced_operator = candidate(
        name="Unplaced Operator",
        title="VP Operations",
        function="Operations",
        location=None,
    )
    ungrounded_clinician = candidate(
        name="Ungrounded Clinician",
        title="Chief Medical Officer",
        function="Clinical",
        location="Fort Myers, Florida, United States",
        with_people_fact=False,
    )
    return (fort_myers_engineer, naples_executive, unplaced_operator, ungrounded_clinician)


def _millennium_scope(*, match_policy: str | None = None) -> AccountBuyingUnitScope:
    """The exact scope the account agent declared live, replayed byte-for-byte apart from ids."""

    fields: dict[str, Any] = {
        "scope_id": uuid4(),
        "account_entity_id": uuid4(),
        "office_label": "Fort Myers, Florida headquarters",
        "locality": "Fort Myers",
        "region": "Florida",
        "country": "US",
        "target_functions": ("Executive", "Clinical", "Operations", "Administration", "Finance"),
        "evidence_refs": ("claim:26267450-f2ef-43a9-a173-4aaac129b022",),
    }
    if match_policy is not None:
        fields["match_policy"] = match_policy
    return AccountBuyingUnitScope(**fields)


def test_company_wide_policy_retires_the_office_veto_on_the_live_millennium_shape() -> None:
    """Founder rulings 2026-08-20: office placement, source path, and function string all retire.

    This shape was written when only the office veto had fallen, and it then asserted that the
    grounding and function gates still stood. The later ruling took those two as well: under
    ``company_wide`` every provider-returned candidate is admitted, so the same four rows that
    once split 2/1/1 now come back whole.
    """

    engineer, naples, unplaced, ungrounded = _millennium_candidates()
    candidates = (engineer, naples, unplaced, ungrounded)
    selected, excluded, ambiguous = SumbleCommitteeSemanticResearchAction._office_candidates(
        candidates,
        scope=_millennium_scope(match_policy="company_wide"),
    )

    assert selected == candidates
    assert (excluded, ambiguous) == (0, 0)


def test_same_office_strict_classifies_the_live_millennium_shape_exactly_as_before() -> None:
    """The retired policy stays selectable and byte-identical when named explicitly."""

    engineer, naples, unplaced, ungrounded = _millennium_candidates()
    selected, excluded, ambiguous = SumbleCommitteeSemanticResearchAction._office_candidates(
        (engineer, naples, unplaced, ungrounded),
        scope=_millennium_scope(match_policy="same_office_strict"),
    )

    assert selected == ()
    assert excluded == 1  # engineer evidences Fort Myers but fails the function gate
    assert ambiguous == 3  # naples + unplaced (office) and ungrounded (no people fact)


def test_buying_unit_scope_defaults_to_company_wide_and_still_accepts_a_declared_office() -> None:
    """A scope built without ``match_policy`` carries the new default, office fields intact."""

    default_scope = _millennium_scope()
    assert default_scope.match_policy == "company_wide"
    # The declared office survives as descriptive/audit context under the new default.
    assert (default_scope.locality, default_scope.region, default_scope.country) == (
        "Fort Myers",
        "Florida",
        "US",
    )
    assert _millennium_scope(match_policy="same_office_strict").match_policy == "same_office_strict"
    with pytest.raises(ValidationError):
        _millennium_scope(match_policy="nearest_metro")

    # And the default policy is what the semantic tool input carries end to end.
    committee_input = DiscoverBuyingCommitteeInput(
        source_keys=("sumble_people",),
        buying_unit_scope=default_scope,
    )
    assert committee_input.buying_unit_scope.match_policy == "company_wide"


def test_persisted_buying_unit_scope_records_its_policy_and_replays_under_it() -> None:
    """The durable scope row and its replay guard both carry the policy explicitly.

    ``_persist_scope`` stores ``scope.model_dump(mode="json")`` and hashes it, and re-reads refuse
    a changed sha ("buying-unit scope replay changed"). A ``company_wide`` scope must therefore
    persist that literal, and a historical ``same_office_strict`` scope must keep hashing to what
    it recorded — the new default can never silently repoint an already-stored scope.
    """

    scope_id, account_id = uuid4(), uuid4()

    def scope(*, match_policy: str) -> AccountBuyingUnitScope:
        return AccountBuyingUnitScope(
            scope_id=scope_id,
            account_entity_id=account_id,
            office_label="Fort Myers, Florida headquarters",
            locality="Fort Myers",
            region="Florida",
            country="US",
            target_functions=("Executive",),
            evidence_refs=("claim:26267450-f2ef-43a9-a173-4aaac129b022",),
            match_policy=match_policy,
        )

    company_wide, strict = (
        scope(match_policy="company_wide"),
        scope(match_policy="same_office_strict"),
    )
    assert company_wide.model_dump(mode="json")["match_policy"] == "company_wide"
    assert strict.model_dump(mode="json")["match_policy"] == "same_office_strict"
    # Replay of the identical declaration is stable...
    assert canonical_sha256(company_wide) == canonical_sha256(scope(match_policy="company_wide"))
    # ...and the policy is inside the hash, so a replay that changed it is caught, never absorbed.
    assert canonical_sha256(company_wide) != canonical_sha256(strict)


def test_account_coverage_field_axis_admits_core_launch_fields(tmp_path: Path) -> None:
    """A settled ``core.*`` account field is storable on the R5 coverage row.

    The launch path now admits the account axis (CORE | ACCOUNT | ACCOUNT_RESONANCE | PACK), so a
    job that settles ``core.industry`` writes it into ``completed_field_keys`` /
    ``unresolved_field_keys``.  The original field-axis CHECK accepted only ``account.%`` keys and
    would have failed that write at finalization.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r5-core-axis-coverage")
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            await load_client_knowledge_pack(conn)
            await seed_source_manifests(conn)
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            workspace_id = fixture.discovery_fixture.workspace_id
            account_id = UUID(str(fixture.selected_account_id))
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(_PAIN, _MOVES, _HIRING),
                allowed_source_keys=("exa_deep", "sumble_jobs", "sumble_people"),
            )
            directive = account_spec.research_directive
            assert directive is not None
            await insert_account_run(
                conn,
                account_run_id=fixture.expected_account_run_id,
                project_run_id=fixture.project_run_id,
                entity_id=fixture.selected_account_id,
                tier="high",
            )
            await pin_account_run_research_directive(
                conn,
                account_run_id=fixture.expected_account_run_id,
                pin=directive,
            )
            connection = _NestedConnFactory(conn)
            envelope = _account_envelope(
                account_id=account_id,
                workspace_id=workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                project_run_id=UUID(str(fixture.project_run_id)),
                profile_sha256=account_research_profile_sha256(),
                directive_ref=directive.directive_ref,
                directive_sha256=directive.canonical_json_sha256,
            )
            await DbEntityResearchJobStore(conn_factory=connection).launch(envelope)
            coverage_id = uuid4()
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_coverage
                        (coverage_id, research_run_id, job_id, workspace_id, account_entity_id,
                         result_refs, completed_field_keys, unresolved_field_keys,
                         unresolved_reasons, committee_result_refs, committee_member_ids,
                         committee_status, review_flags, claim_refs, evidence_refs,
                         coverage_json, coverage_sha256)
                    VALUES
                        (:coverage_id, :run_id, :job_id, :workspace_id, :account_id,
                         '{}', :completed, :unresolved, :reasons,
                         '{}', '{}', 'complete', '{}', '{}', '{}',
                         CAST('{}' AS jsonb), :sha)
                    """
                ),
                {
                    "coverage_id": coverage_id,
                    "run_id": envelope.lifecycle.run_id,
                    "job_id": envelope.jobs[0].authorization.job_id,
                    "workspace_id": workspace_id,
                    "account_id": account_id,
                    "completed": ["core.industry", _PAIN],
                    "unresolved": ["core.primary_tech_stack"],
                    "reasons": ["no_supported_source"],
                    "sha": "0" * 64,
                },
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT completed_field_keys, unresolved_field_keys "
                            "FROM entity_research_account_coverage WHERE coverage_id=:id"
                        ),
                        {"id": coverage_id},
                    )
                )
                .mappings()
                .one()
            )
            assert stored["completed_field_keys"] == ["core.industry", _PAIN]
            assert stored["unresolved_field_keys"] == ["core.primary_tech_stack"]

            # The axis itself still holds: a contact field is not account coverage.
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO entity_research_account_coverage "
                            "(coverage_id, research_run_id, job_id, workspace_id, "
                            " account_entity_id, result_refs, completed_field_keys, "
                            " unresolved_field_keys, unresolved_reasons, committee_result_refs, "
                            " committee_member_ids, committee_status, review_flags, claim_refs, "
                            " evidence_refs, coverage_json, coverage_sha256) "
                            "VALUES (:coverage_id, :run_id, :job_id, :workspace_id, :account_id, "
                            " '{}', :completed, '{}', '{}', '{}', '{}', 'complete', '{}', '{}', "
                            " '{}', CAST('{}' AS jsonb), :sha)"
                        ),
                        {
                            "coverage_id": uuid4(),
                            "run_id": envelope.lifecycle.run_id,
                            "job_id": envelope.jobs[0].authorization.job_id,
                            "workspace_id": workspace_id,
                            "account_id": account_id,
                            "completed": ["contact.current_title"],
                            "sha": "0" * 64,
                        },
                    )

    run_async(scenario())


def _committee_tool_request(durable: CommitteeAcquisitionRequest) -> GovernedResearchToolRequest:
    """The governed committee request the R5 engine journals before the provider action runs."""
    return GovernedResearchToolRequest(
        research_run_id=uuid4(),
        job_id=uuid4(),
        subject_type=ResearchSubjectType.ACCOUNT,
        target_entity_id=UUID(str(durable.account_id)),
        agent_turn_id=uuid4(),
        agent_execution_id=uuid4(),
        tool_call_id=uuid4(),
        tool_name="discover_buying_committee",
        tool_version=1,
        tool_input_sha256=canonical_sha256({"tool": "discover_buying_committee"}),
        field_plan_ref="field-plan:d2-committee",
        source_plan_ref="source-plan:d2-committee",
        source_keys=(PEOPLE_SOURCE_KEY,),
        questions=(_COMMITTEE_QUESTION,),
        budget_reservation_key="budget:d2-committee",
        idempotency_key="idempotency:d2-committee",
    )


def test_r5_production_committee_action_defers_role_inference_to_the_agent(tmp_path: Path) -> None:
    """The production Sumble committee action discovers + identity-resolves, and judges no roles.

    Contract §5.2 steps 1-2: discovery/identity is the provider action's job; the committee role is
    the responsible account agent's judgment (written back by its own tool). So a production
    committee call now spends nothing on role inference, writes NO ``contact.role_on_committee`` /
    ``contact.persona`` claim, and still projects every admitted member as a discovered subject
    carrying its provider-returned People facts. Between this and the agent's role write, a
    committee legitimately has members and no roles — the ratified intermediate state."""

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with durable_rollback_conn(seed_pack=True) as conn:
            durable = await _committee_setup(conn, storage, workspace_id="ws-d2-committee")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=_CommitteeTransport(),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                poll_after_seconds=30,
            )
            preflight = compile_sumble_committee_preflight(durable, cents_per_credit=Decimal("0.5"))
            ready = await coordinator.start(preflight)
            for _ in range(2):  # the People submission settles on the polling path
                await conn.execute(
                    text(
                        "UPDATE committee_acquisition_operation SET next_poll_at=:past WHERE id=:id"
                    ),
                    {
                        "id": ready.operation.operation_id,
                        "past": datetime.now(UTC) - timedelta(seconds=1),
                    },
                )
                ready = await coordinator.start(preflight)
            assert ready.operation.state.value == "ready"

            account = await get_account(conn, durable.account_id)
            assert account is not None
            source = SumbleCommitteeSource(
                operation_ids={durable.account_id: ready.operation.operation_id},
                storage=storage,
                conn_factory=same_connection,
            )
            selected = tuple(await source.find_candidates(account, limit=durable.people_limit))
            assert selected

            await seed_packs(conn)
            gateway = FakeGateway()
            action = SumbleCommitteeSemanticResearchAction(
                preflight=preflight,
                coordinator=coordinator,
                storage=storage,
                conn_factory=same_connection,
                gateway=gateway,
                role_model="d2-role-model",
            )
            committee = await action._discover_committee_members(
                conn,
                account_entity_id=durable.account_id,
                run_id=RunId(UUID(str(durable.project_run_id))),
                workspace_id=durable.workspace_id,
                selected=selected,
                budget_cap_cents=durable.money_budget_cap_cents,
            )

            assert committee.admitted == len(selected)
            assert len(committee.members) == committee.admitted
            assert gateway.complete_calls == 0  # no role model was consulted at all
            assert committee.needs_review == len(committee.members)
            scope = WorkspaceScope.for_workspace(durable.workspace_id)
            for member in committee.members:
                assert member.persona is None
                assert member.role_claim_id is None
                assert (
                    await claims_for(conn, member.contact_entity_id, ROLE_ON_COMMITTEE, scope=scope)
                    == []
                )
                assert await claims_for(conn, member.contact_entity_id, PERSONA, scope=scope) == []
                assert member.professional_claim_ids  # the People facts are durable
            assert committee.committee() == ()  # nothing handoff-shaped without a role

            # The projection is role-independent: roleless members still flow through as
            # discovered subjects carrying their provider-returned People facts.
            request = _committee_tool_request(durable)
            provider_operation = action._committee_descriptor(
                ready.operation,
                disposition=ProviderObservationDisposition.CAUSED,
                include_dispatch=True,
            )
            # In production the engine journals the reservation through ``before_dispatch``
            # before the action projects against it; do the same so the projection's FK holds.
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_provider_operation
                        (operation_ref, provider_kind, workspace_id, project_id, project_run_id,
                         subject_type, target_entity_id, parent_account_id, source_key,
                         field_keys, request_artifact_ref, reserved_at, dispatched_at)
                    VALUES
                        (:operation_ref, :provider_kind, :workspace_id, :project_id,
                         :project_run_id, :subject_type, :target_entity_id, :parent_account_id,
                         :source_key, :field_keys, :request_artifact_ref, :reserved_at,
                         :dispatched_at)
                    """
                ),
                {
                    "operation_ref": provider_operation.operation_ref,
                    "provider_kind": provider_operation.provider_kind,
                    "workspace_id": provider_operation.workspace_id,
                    "project_id": provider_operation.project_id,
                    "project_run_id": provider_operation.project_run_id,
                    "subject_type": provider_operation.subject_type.value,
                    "target_entity_id": provider_operation.target_entity_id,
                    "parent_account_id": provider_operation.parent_account_id,
                    "source_key": provider_operation.source_key,
                    "field_keys": list(provider_operation.field_keys),
                    "request_artifact_ref": provider_operation.request_artifact_ref,
                    "reserved_at": provider_operation.reserved_at,
                    "dispatched_at": provider_operation.dispatched_at,
                },
            )
            snapshot_ref, subjects = await action._persist_committee_projection(
                request=request,
                operation=ready.operation,
                provider_operation=provider_operation,
                committee=committee,
                excluded=0,
                ambiguous=0,
            )
            assert snapshot_ref.startswith("committee-snapshot:")
            assert len(subjects) == len(committee.members)
            subject = subjects[0]
            assert subject.subject_type is ResearchSubjectType.CONTACT
            assert subject.target_entity_id == UUID(str(committee.members[0].contact_entity_id))
            assert subject.parent_account_id == request.target_entity_id
            assert subject.fields
            assert str(CURRENT_TITLE) in {field.field_key for field in subject.fields}
            assert all(
                field.outcome is ResearchFieldOutcome.FOUND
                and field.claim_delta is ResearchClaimDelta.ACCEPTED
                and field.evidence
                for field in subject.fields
            )

            # ...and the provider-returned floor is a floor, not a hole: an admitted member with
            # no provider fact at all from this operation is still refused. What retired is the
            # People-vs-Teams discrimination, not the requirement to be grounded in the operation
            # that was actually paid for.
            starved = CommitteeResult(
                account_entity_id=committee.account_entity_id,
                members=(
                    CommitteeMemberRef(
                        contact_entity_id=committee.members[0].contact_entity_id,
                        discovery_claim_id=committee.members[0].discovery_claim_id,
                    ),
                ),
                coverage=committee.coverage,
                admitted=1,
                needs_review=1,
            )
            with pytest.raises(
                EntityResearchResultIntegrityError, match="lacks provider-returned facts"
            ):
                await action._persist_committee_projection(
                    request=request,
                    operation=ready.operation,
                    provider_operation=provider_operation,
                    committee=starved,
                    excluded=0,
                    ambiguous=0,
                )

    run_async(scenario())


def _millennium_v9_candidates() -> tuple[CommitteePersonCandidate, ...]:
    """The live v9 committee shape (job ``cd6a779e`` / operation ``8500325f``, 2026-08-20).

    Seven real, provider-returned, *current* Millennium Physician Group employees at CXO/SVP
    level. Three arrived on the People page and four only through the Teams organization map, so
    their facts are stamped ``sumble_teams``. Live result under the pre-ruling ladder: one
    admitted, two excluded because the provider spells the function "Physician" where the plan
    said "Clinical", and four routed to review purely because their facts came from Teams.
    """

    def candidate(
        *, name: str, title: str, function: str, source_key: str
    ) -> CommitteePersonCandidate:
        return CommitteePersonCandidate(
            source_key=PEOPLE_SOURCE_KEY,
            linkedin_url=f"https://linkedin.com/in/{name.casefold().replace(' ', '-')}",
            full_name=name,
            title=title,
            job_function=function,
            geo={},
            source_url="https://sumble.example/people/millennium",
            professional_facts=(
                CandidateProfessionalFact(
                    field_key="contact.current_location",
                    value_json={
                        "location": "Fort Myers, Florida, United States",
                        "country": "United States",
                    },
                    provenance_kind=CandidateFactProvenance.PROVIDER_RETURNED,
                    source_key=source_key,
                    source_tier=1,
                    source_url="https://sumble.example/people/millennium",
                    evidence_span="Provider-returned person row.",
                    artifact_key=f"sumble/{source_key}/millennium",
                    source_operation_ref="committee-operation:millennium-v9",
                    source_snapshot_ref=f"committee-snapshot:millennium-v9:{source_key}",
                    source_request_ref=f"sumble-request:{source_key}:millennium-v9",
                ),
            ),
        )

    return (
        # The People page — the only path the pre-ruling ladder could admit from.
        candidate(
            name="Lenny Brunson",
            title="Divisional CIO",
            function="Information Technology",
            source_key=PEOPLE_SOURCE_KEY,
        ),
        candidate(
            name="Alejandro Perez-Trepichio MD",
            title="Chief Medical Officer",
            function="Physician",
            source_key=PEOPLE_SOURCE_KEY,
        ),
        candidate(
            name="Zenobia Brown MD",
            title="SVP Population Health",
            function="Physician",
            source_key=PEOPLE_SOURCE_KEY,
        ),
        # The Teams organization map — provider data too, bought in the same paid operation.
        candidate(
            name="Brian Fox",
            title="Board Member",
            function="Board of Directors",
            source_key=TEAMS_SOURCE_KEY,
        ),
        candidate(
            name="Tesha Simpson",
            title="Chief Operating Officer",
            function="Executive",
            source_key=TEAMS_SOURCE_KEY,
        ),
        candidate(
            name="Truly Peterson MD",
            title="Chief Quality Officer",
            function="Uncategorized",
            source_key=TEAMS_SOURCE_KEY,
        ),
        candidate(
            name="Dionne Leverette",
            title="SVP Human Resources",
            function="Executive",
            source_key=TEAMS_SOURCE_KEY,
        ),
    )


def _millennium_v9_scope(*, match_policy: str | None = None) -> AccountBuyingUnitScope:
    fields: dict[str, Any] = {
        "scope_id": uuid4(),
        "account_entity_id": uuid4(),
        "office_label": "Fort Myers, Florida headquarters",
        "locality": "Fort Myers",
        "region": "Florida",
        "country": "US",
        "target_functions": (
            "Executive",
            "Clinical",
            "Operations",
            "Administration",
            "Information Technology",
        ),
        "evidence_refs": ("claim:26267450-f2ef-43a9-a173-4aaac129b022",),
    }
    if match_policy is not None:
        fields["match_policy"] = match_policy
    return AccountBuyingUnitScope(**fields)


def test_company_wide_admits_every_provider_returned_candidate_on_the_live_v9_shape() -> None:
    """Founder ruling 2026-08-20: the truth floor is provider-returned, and nothing more.

    A candidate Sumble returned — from the People page **or** from the Teams organization map —
    is admissible ground. The two mechanical judgment gates that survived the office retirement
    die here: the ``sumble_people`` source-key grounding filter (Teams rows are provider data
    too) and the ``target_functions`` string match ("Clinical" vs the provider's "Physician"
    excluded two real CXOs). Function vocabulary and persona judgment are the agent's work,
    taught by the operations manual, not enforced by string equality in the engine.
    """

    candidates = _millennium_v9_candidates()
    selected, excluded, ambiguous = SumbleCommitteeSemanticResearchAction._office_candidates(
        candidates, scope=_millennium_v9_scope(match_policy="company_wide")
    )

    assert selected == candidates
    assert (excluded, ambiguous) == (0, 0)


def test_same_office_strict_pins_exactly_what_the_provider_returned_floor_retired() -> None:
    """The explicitly-selected strict policy still classifies the live v9 shape as it did.

    This is the negative control for the ruling: under ``same_office_strict`` the same seven
    candidates reproduce the exact live board — one admitted, two excluded on the function
    string, four routed to review for arriving via Teams — so the two retired gates are visible
    precisely where they used to fire.
    """

    candidates = _millennium_v9_candidates()
    selected, excluded, ambiguous = SumbleCommitteeSemanticResearchAction._office_candidates(
        candidates, scope=_millennium_v9_scope(match_policy="same_office_strict")
    )

    assert selected == (candidates[0],)
    assert (excluded, ambiguous) == (2, 4)


def test_target_functions_is_advisory_and_may_be_empty_end_to_end() -> None:
    """``target_functions`` no longer gates admission, so an empty set is a legal declaration.

    The field stays (it is how the agent records the confirmed plan's functions for audit and
    narrowing), but it is descriptive: a scope that declares none still admits every
    provider-returned candidate, and the plan-widening guard has nothing to refuse.
    """

    empty = AccountBuyingUnitScope(
        scope_id=uuid4(),
        account_entity_id=uuid4(),
        office_label="Fort Myers, Florida headquarters",
        locality="Fort Myers",
        target_functions=(),
        evidence_refs=("claim:26267450-f2ef-43a9-a173-4aaac129b022",),
    )
    assert empty.target_functions == ()
    assert empty.match_policy == "company_wide"

    # It survives the semantic tool input the agent actually sends...
    committee_input = DiscoverBuyingCommitteeInput(
        source_keys=(PEOPLE_SOURCE_KEY,),
        buying_unit_scope=empty,
    )
    assert committee_input.buying_unit_scope.target_functions == ()

    # ...the plan-widening guard (an empty declaration widens nothing)...
    SumbleCommitteeSemanticResearchAction._validate_scope_against_plan(
        empty,
        plan=ResearchCommitteePlan(functions=("Executive",)),
    )

    # ...and the admission floor itself.
    candidates = _millennium_v9_candidates()
    selected, excluded, ambiguous = SumbleCommitteeSemanticResearchAction._office_candidates(
        candidates, scope=empty
    )
    assert selected == candidates
    assert (excluded, ambiguous) == (0, 0)
