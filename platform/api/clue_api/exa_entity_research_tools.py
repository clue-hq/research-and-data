"""Exa Search Deep composition behind the provider-neutral M8D R4 semantic tool seam."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.entity_research_contracts import canonical_sha256
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    EntityResearchProviderAction,
    EntityResearchProviderWait,
    EntityResearchResultIntegrityError,
    ExternalResearchProjectionDraft,
    ProviderObservationDisposition,
    ProviderOperationObservation,
    ProviderOperationReservation,
)
from clue_api.exa_contact_acquisition import ExaDeepContactAcquisitionService
from clue_api.exa_contact_materialization import ExaDeepContactSnapshotMaterializer
from clue_api.exa_deep_acquisition import (
    ExaDeepAcquisitionCoordinator,
    ExaDeepAcquisitionOutcome,
    ExaDeepAcquisitionResult,
    compile_exa_deep_acquisition_plan,
)
from clue_api.exa_deep_materialization import ExaDeepSnapshotResolverProvider
from clue_core import (
    ContactResearchIntent,
    ContactResearchPolicyPin,
    Entity,
    EntityId,
    EntityType,
    ExternalResearchSnapshotId,
    ProjectRunId,
    ResearchDirectivePin,
    ResearchMode,
    RunId,
    decode_jsonb_scalar,
)
from clue_core.entity_research import (
    GovernedResearchToolRequest,
    ResearchClaimDelta,
    ResearchEvidenceProjection,
    ResearchFieldOutcome,
    ResearchFieldResultProjection,
    ResearchSubjectType,
)
from clue_research.claimstore import (
    FieldRegistryScope,
    get_effective_field,
    record_run_lineage,
)
from clue_research.durable.external_research import ExternalResearchOperationRow
from clue_research.identity import get_account
from clue_research.resolvers.exa import (
    DEFAULT_EXA_CONFIG,
    SOURCE_KEY,
    ExaDeepConfig,
    ExaDeepFieldSpec,
    ExaDeepRequestBoundExceeded,
)
from clue_research.sources import bind_resolver_overrides, resolve_field
from clue_storage import StorageBackend, read_verified_artifact

ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r4:research-evidence")
_MATERIALIZATION_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r4:exa-contact-materialization-run")
_ACCOUNT_MATERIALIZATION_RUN_NAMESPACE = uuid5(
    NAMESPACE_URL, "clue:m8d:r5:exa-account-materialization-run"
)
# The planning sentence a comprehensive directive needs when it carries no human-authored
# directional question. Shared with the composition root, whose budget reservation must size
# itself against the *same* request the action will compile.
DEFAULT_ACCOUNT_RESEARCH_INTENT = (
    "Target-lock research to this canonical account and answer only the admitted "
    "structured fields with inspectable evidence."
)
# Both are terminal in the external ledger and can never yield a snapshot: the operation was
# dispatched, the provider answered or refused, and no retry of this exact request will change it.
_UNPRODUCTIVE_OUTCOMES = frozenset(
    {
        ExaDeepAcquisitionOutcome.FAILED_TERMINAL,
        ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
    }
)


async def _settle_unproductive_bundles(
    items: Sequence[ExaDeepAcquisitionResult],
    *,
    projector: ExaEntityResearchProjectionBuilder,
    field_keys_for: Callable[[ExaDeepAcquisitionResult], tuple[str, ...]],
    caused_refs: set[str],
    settle_terminal: Callable[
        [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
    ],
) -> frozenset[str]:
    """Give every dispatched-but-unproductive bundle a durable terminal disposition.

    Without this the bundle stays reserved-never-dispatched on the entity-research ledger, which
    execution closure refuses to count as an attempt, so its fields can never settle and the whole
    tool call fails identically on every replay.
    """

    settled: set[str] = set()
    for item in items:
        operation_ref = f"external-research-operation:{item.operation.operation_id}"
        descriptor = await projector.operation(
            item.operation,
            disposition=(
                ProviderObservationDisposition.CAUSED
                if operation_ref in caused_refs
                else ProviderObservationDisposition.REPLAY
            ),
            include_dispatch=True,
            field_keys=field_keys_for(item),
        )
        await settle_terminal(descriptor)
        settled.update(descriptor.field_keys)
    return frozenset(settled)


def _external_operation_id(reference: str) -> UUID:
    prefix = "external-research-operation:"
    if not reference.startswith(prefix):
        raise EntityResearchResultIntegrityError("Exa adapter received another operation type")
    try:
        return UUID(reference.removeprefix(prefix))
    except ValueError as exc:
        raise EntityResearchResultIntegrityError("Exa operation reference is malformed") from exc


def _evidence_ref(
    *, operation_id: UUID, field_key: str, artifact_key: str, evidence_span: str
) -> str:
    digest = hashlib.sha256(evidence_span.encode()).hexdigest()
    return (
        "research-evidence:"
        f"{uuid5(_EVIDENCE_NAMESPACE, f'{operation_id}:{field_key}:{artifact_key}:{digest}')}"
    )


class ExaEntityResearchProjectionBuilder:
    """Project Exa normalization plus claim-engine decisions into the frozen R0 result shape."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: ConnFactory,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    async def operation(
        self,
        row: ExternalResearchOperationRow,
        *,
        disposition: ProviderObservationDisposition,
        include_dispatch: bool,
        field_keys: tuple[str, ...],
    ) -> ProviderOperationReservation:
        """Project the external ledger's immutable authority into the provider-neutral bridge."""

        async with self._conn_factory() as conn:
            operation = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT operation.created_at,
                                   (SELECT min(attempt.dispatched_at)
                                    FROM external_research_attempt attempt
                                    WHERE attempt.operation_id=operation.id
                                      AND attempt.dispatched_at IS NOT NULL) AS dispatched_at
                            FROM external_research_operation operation
                            WHERE operation.id=:operation_id
                              AND operation.workspace_id=:workspace_id
                            """
                        ),
                        {
                            "operation_id": row.operation_id,
                            "workspace_id": row.workspace_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
        if operation is None:
            raise EntityResearchResultIntegrityError("Exa operation disappeared before projection")
        return ProviderOperationReservation(
            provider_kind="external_research",
            operation_ref=f"external-research-operation:{row.operation_id}",
            workspace_id=row.workspace_id,
            project_id=row.project_id,
            project_run_id=row.project_run_id,
            subject_type=ResearchSubjectType(row.subject_kind.value),
            target_entity_id=UUID(str(row.subject_entity_id)),
            parent_account_id=(
                UUID(str(row.account_id))
                if row.subject_kind.value == ResearchSubjectType.CONTACT.value
                else None
            ),
            source_key=row.source_key,
            field_keys=field_keys,
            request_artifact_ref=f"artifact:{row.request_artifact_key}",
            reserved_at=operation["created_at"],
            dispatched_at=operation["dispatched_at"] if include_dispatch else None,
            observation_disposition=disposition,
        )

    async def build(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: ProviderOperationReservation,
        snapshot_id: UUID,
    ) -> ExternalResearchProjectionDraft:
        operation_id = _external_operation_id(operation.operation_ref)
        async with self._conn_factory() as conn:
            snapshot = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT snapshot.workspace_id, snapshot.normalization_artifact_key,
                                   snapshot.provider_request_id, operation.subject_kind::text,
                                   operation.account_id, operation.contact_id,
                                   operation.source_key
                            FROM external_research_snapshot snapshot
                            JOIN external_research_operation operation
                              ON operation.id=snapshot.operation_id
                             AND operation.workspace_id=snapshot.workspace_id
                            WHERE snapshot.id=:snapshot_id
                              AND snapshot.operation_id=:operation_id
                            """
                        ),
                        {"snapshot_id": snapshot_id, "operation_id": operation_id},
                    )
                )
                .mappings()
                .first()
            )
            if snapshot is None:
                raise EntityResearchResultIntegrityError("Exa projection snapshot is absent")
            target_id = (
                snapshot["account_id"]
                if request.subject_type is ResearchSubjectType.ACCOUNT
                else snapshot["contact_id"]
            )
            if (
                str(snapshot["workspace_id"]) != str(await self._request_workspace(conn, request))
                or str(snapshot["subject_kind"]) != request.subject_type.value
                or target_id != request.target_entity_id
                or str(snapshot["source_key"]) != SOURCE_KEY
            ):
                raise EntityResearchResultIntegrityError(
                    "Exa projection crosses exact workspace or subject"
                )
            _, normalization_bytes = await read_verified_artifact(
                conn,
                self._storage,
                storage_key=str(snapshot["normalization_artifact_key"]),
                workspace_id=str(snapshot["workspace_id"]),
            )
            try:
                normalization = cast(dict[str, Any], json.loads(normalization_bytes))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EntityResearchResultIntegrityError(
                    "Exa normalization artifact is malformed"
                ) from exc
            result_artifacts = {
                str(row["source_url"]): str(row["artifact_key"])
                for row in (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT source_url, artifact_key
                                FROM external_research_result_artifact
                                WHERE snapshot_id=:snapshot_id
                                """
                            ),
                            {"snapshot_id": snapshot_id},
                        )
                    )
                    .mappings()
                    .all()
                )
            }
            claims = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, entity_id, field_key, value_json, source_key, source_url,
                                   artifact_key, evidence_span, confidence,
                                   verification_status::text, corroborations,
                                   source_operation_ref, source_snapshot_ref, collected_at
                            FROM claim
                            WHERE entity_id=:target_entity_id
                              AND field_key=ANY(:field_keys)
                              AND source_operation_ref=:operation_ref
                              AND source_snapshot_ref=:snapshot_ref
                              AND superseded_by IS NULL
                            ORDER BY collected_at DESC, id
                            """
                        ),
                        {
                            "target_entity_id": request.target_entity_id,
                            "field_keys": list(request.field_keys),
                            "operation_ref": str(operation_id),
                            "snapshot_ref": str(snapshot_id),
                        },
                    )
                )
                .mappings()
                .all()
            )
            claims_by_field: dict[str, list[Mapping[str, object]]] = {
                field_key: [] for field_key in request.field_keys
            }
            for row in claims:
                claims_by_field[str(row["field_key"])].append(cast(Mapping[str, object], row))
            field_results: list[ResearchFieldResultProjection] = []
            for field_key in request.field_keys:
                field_results.append(
                    await self._field(
                        conn,
                        request=request,
                        field_key=field_key,
                        operation_id=operation_id,
                        snapshot_id=snapshot_id,
                        normalization_artifact_key=str(snapshot["normalization_artifact_key"]),
                        provider_request_id=str(snapshot["provider_request_id"]),
                        normalization=normalization,
                        result_artifacts=result_artifacts,
                        claims=claims_by_field[field_key],
                    )
                )
            fields = tuple(field_results)
        return ExternalResearchProjectionDraft(
            operation=operation,
            snapshot_ref=f"external-research-snapshot:{snapshot_id}",
            requested_field_keys=request.field_keys,
            fields=fields,
        )

    async def _request_workspace(
        self, conn: AsyncConnection, request: GovernedResearchToolRequest
    ) -> str:
        return cast(
            str,
            (
                await conn.execute(
                    text(
                        "SELECT workspace_id FROM entity_research_tool_request "
                        "WHERE tool_request_id=:tool_request_id"
                    ),
                    {"tool_request_id": request.tool_call_id},
                )
            ).scalar_one(),
        )

    async def bundle_field_keys(
        self,
        snapshot_id: ExternalResearchSnapshotId,
        *,
        admitted_field_keys: Sequence[str],
    ) -> tuple[str, ...]:
        """Read the immutable wire schema to partition a multi-bundle semantic result."""

        async with self._conn_factory() as conn:
            payload = (
                await conn.execute(
                    text(
                        "SELECT request_json FROM external_research_operation operation "
                        "JOIN external_research_snapshot snapshot "
                        "ON snapshot.operation_id=operation.id WHERE snapshot.id=:snapshot_id"
                    ),
                    {"snapshot_id": snapshot_id},
                )
            ).scalar_one()
        if not isinstance(payload, Mapping):
            raise EntityResearchResultIntegrityError("Exa stored wire request is malformed")
        wire = payload.get("request_payload")
        if not isinstance(wire, Mapping):
            raise EntityResearchResultIntegrityError("Exa stored request payload is malformed")
        schema = wire.get("outputSchema")
        prompt = wire.get("systemPrompt")
        if (
            not isinstance(schema, Mapping)
            or not isinstance(schema.get("properties"), Mapping)
            or not isinstance(prompt, str)
        ):
            raise EntityResearchResultIntegrityError("Exa stored wire schema is malformed")
        from clue_research.resolvers.exa.deep_contract import exa_alias_field_keys

        # The stored request declares its own alias generation, so a bundle compiled under the
        # legacy hex aliases keeps partitioning correctly after the compiler moved to short ones.
        try:
            table = exa_alias_field_keys(
                system_prompt=prompt,
                aliases=cast(Mapping[str, object], schema["properties"]),
            )
        except ValueError as exc:
            raise EntityResearchResultIntegrityError("Exa stored wire schema is malformed") from exc
        keys = tuple(str(field_key) for field_key in table.values())
        if not set(keys).issubset(admitted_field_keys):
            raise EntityResearchResultIntegrityError("Exa bundle widened governed fields")
        return keys

    async def _field(
        self,
        conn: AsyncConnection,
        *,
        request: GovernedResearchToolRequest,
        field_key: str,
        operation_id: UUID,
        snapshot_id: UUID,
        normalization_artifact_key: str,
        provider_request_id: str,
        normalization: Mapping[str, Any],
        result_artifacts: Mapping[str, str],
        claims: Sequence[Mapping[str, object]],
    ) -> ResearchFieldResultProjection:
        if claims:
            conflict = (
                await conn.execute(
                    text(
                        """
                            SELECT conflicting_claim_ids
                            FROM conflict_flag
                            WHERE entity_id=:entity_id AND field_key=:field_key
                              AND resolved_by IS NULL
                            """
                    ),
                    {"entity_id": request.target_entity_id, "field_key": field_key},
                )
            ).scalar_one_or_none()
            current_claims = list(claims)
            if conflict:
                conflict_ids = [UUID(str(value)) for value in conflict]
                extra = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT id, entity_id, field_key, value_json, source_key,
                                       source_url, artifact_key, evidence_span, confidence,
                                       verification_status::text, corroborations,
                                       source_operation_ref, source_snapshot_ref, collected_at
                                FROM claim WHERE id=ANY(:claim_ids)
                                ORDER BY collected_at DESC, id
                                """
                            ),
                            {"claim_ids": conflict_ids},
                        )
                    )
                    .mappings()
                    .all()
                )
                current_claims = [cast(Mapping[str, object], row) for row in extra]
                return ResearchFieldResultProjection(
                    field_key=field_key,
                    outcome=ResearchFieldOutcome.CONFLICT,
                    claim_delta=ResearchClaimDelta.CONFLICTING,
                    claim_refs=tuple(f"claim:{row['id']}" for row in current_claims),
                    decision_refs=(f"conflict:{request.target_entity_id}:{field_key}",),
                    evidence=self._claim_evidence(
                        field_key=field_key,
                        operation_id=operation_id,
                        provider_request_id=provider_request_id,
                        claims=current_claims,
                    ),
                    confidence=max(float(cast(float, row["confidence"])) for row in current_claims),
                    verification_status="flagged_conflict",
                )
            winner = current_claims[0]
            corroborating = any(int(cast(int, row["corroborations"])) > 0 for row in current_claims)
            return ResearchFieldResultProjection(
                field_key=field_key,
                outcome=ResearchFieldOutcome.FOUND,
                value=decode_jsonb_scalar(winner["value_json"]),
                claim_delta=(
                    ResearchClaimDelta.CORROBORATING
                    if corroborating
                    else ResearchClaimDelta.ACCEPTED
                ),
                claim_refs=tuple(f"claim:{row['id']}" for row in current_claims),
                evidence=self._claim_evidence(
                    field_key=field_key,
                    operation_id=operation_id,
                    provider_request_id=provider_request_id,
                    claims=current_claims,
                ),
                confidence=max(float(cast(float, row["confidence"])) for row in current_claims),
                verification_status=str(winner["verification_status"]),
            )

        synthesis_fields = {
            str(item["field_key"]): item
            for item in normalization.get("synthesis", {}).get("fields", [])
        }
        if field_key in synthesis_fields:
            raise EntityResearchResultIntegrityError(
                f"Exa normalized {field_key!r}, but claim materialization is incomplete"
            )
        matching = self._citations(normalization, field_key=field_key)
        rejected = [
            item
            for item in matching
            if item.get("target_binding") in {"unresolved", "contradictory"}
        ]
        if rejected:
            evidence = self._citation_evidence(
                field_key=field_key,
                operation_id=operation_id,
                provider_request_id=provider_request_id,
                citations=rejected,
                result_artifacts=result_artifacts,
            )
            reasons = tuple(
                str(reason)
                for item in rejected
                for reason in cast(Sequence[object], item.get("reason_codes", ()))
            )
            return ResearchFieldResultProjection(
                field_key=field_key,
                outcome=ResearchFieldOutcome.REJECTED,
                claim_delta=ResearchClaimDelta.REJECTED,
                decision_refs=(
                    f"artifact:{normalization_artifact_key}#/citations/{field_key}",
                    *(f"target-binding-reason:{reason}" for reason in dict.fromkeys(reasons)),
                ),
                evidence=evidence,
                confidence=max(
                    (float(self._citation(item).get("confidence", 0.0)) for item in rejected),
                    default=None,
                ),
                verification_status="target_rejected",
            )
        unsupported = [
            item
            for item in matching
            if self._citation(item).get("status") in {"unsupported", "below_confidence"}
        ]
        if unsupported:
            evidence = self._citation_evidence(
                field_key=field_key,
                operation_id=operation_id,
                provider_request_id=provider_request_id,
                citations=unsupported,
                result_artifacts=result_artifacts,
            )
            return ResearchFieldResultProjection(
                field_key=field_key,
                outcome=ResearchFieldOutcome.UNSUPPORTED,
                claim_delta=ResearchClaimDelta.NONE,
                evidence=evidence,
                verification_status="unsupported_grounding",
            )
        return ResearchFieldResultProjection(
            field_key=field_key,
            outcome=ResearchFieldOutcome.NULL,
            claim_delta=ResearchClaimDelta.NONE,
            verification_status="explicit_null",
        )

    @staticmethod
    def _citations(normalization: Mapping[str, Any], *, field_key: str) -> list[Mapping[str, Any]]:
        values: list[Mapping[str, Any]] = []
        for raw in normalization.get("citations", []):
            if not isinstance(raw, Mapping):
                continue
            citation = ExaEntityResearchProjectionBuilder._citation(raw)
            if str(citation.get("field_key", "")) == field_key:
                values.append(raw)
        return values

    @staticmethod
    def _citation(value: Mapping[str, Any]) -> Mapping[str, Any]:
        nested = value.get("citation")
        return nested if isinstance(nested, Mapping) else value

    def _claim_evidence(
        self,
        *,
        field_key: str,
        operation_id: UUID,
        provider_request_id: str,
        claims: Sequence[Mapping[str, object]],
    ) -> tuple[ResearchEvidenceProjection, ...]:
        evidence: list[ResearchEvidenceProjection] = []
        seen: set[tuple[str, str]] = set()
        for claim in claims:
            artifact_key = str(claim["artifact_key"])
            span = str(claim["evidence_span"])
            identity = (artifact_key, span)
            if not artifact_key or not span or identity in seen:
                continue
            seen.add(identity)
            evidence.append(
                ResearchEvidenceProjection(
                    evidence_ref=_evidence_ref(
                        operation_id=operation_id,
                        field_key=field_key,
                        artifact_key=artifact_key,
                        evidence_span=span,
                    ),
                    source_key=str(claim["source_key"]),
                    provider_source_id=provider_request_id,
                    source_url=str(claim["source_url"]),
                    artifact_ref=f"artifact:{artifact_key}",
                    evidence_span=span,
                )
            )
        return tuple(evidence)

    def _citation_evidence(
        self,
        *,
        field_key: str,
        operation_id: UUID,
        provider_request_id: str,
        citations: Sequence[Mapping[str, Any]],
        result_artifacts: Mapping[str, str],
    ) -> tuple[ResearchEvidenceProjection, ...]:
        evidence: list[ResearchEvidenceProjection] = []
        for item in citations:
            citation = self._citation(item)
            span = citation.get("evidence_span")
            source_url = citation.get("source_url")
            if not isinstance(span, str) or not span or not isinstance(source_url, str):
                continue
            artifact_key = result_artifacts.get(source_url)
            if artifact_key is None:
                raise EntityResearchResultIntegrityError(
                    "Exa citation has no retained result artifact"
                )
            evidence.append(
                ResearchEvidenceProjection(
                    evidence_ref=_evidence_ref(
                        operation_id=operation_id,
                        field_key=field_key,
                        artifact_key=artifact_key,
                        evidence_span=span,
                    ),
                    source_key=SOURCE_KEY,
                    provider_source_id=provider_request_id,
                    source_url=source_url,
                    artifact_ref=f"artifact:{artifact_key}",
                    evidence_span=span,
                )
            )
        return tuple(evidence)


class ExaContactSemanticResearchAction(EntityResearchProviderAction):
    """Reuse C3/C4 acquisition and claim materialization for one exact contact job."""

    def __init__(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: ContactResearchPolicyPin,
        acquisition: ExaDeepContactAcquisitionService,
        materializer: ExaDeepContactSnapshotMaterializer,
        projector: ExaEntityResearchProjectionBuilder,
        run_id: RunId,
        observation_window: str,
        entity_research_job_id: UUID | None = None,
    ) -> None:
        self._intent = intent
        self._policy = effective_policy
        self._acquisition = acquisition
        self._materializer = materializer
        self._projector = projector
        self._run_id = run_id
        self._observation_window = observation_window
        self._entity_research_job_id = entity_research_job_id

    async def execute(
        self,
        request: GovernedResearchToolRequest,
        *,
        before_dispatch: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
        settle_terminal: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
    ) -> Sequence[ExternalResearchProjectionDraft]:
        facet_fields = tuple(
            str(field_key)
            for field_key in self._intent.field_keys
            if str(field_key).startswith("contact.facet.")
        )
        if (
            request.subject_type is not ResearchSubjectType.CONTACT
            or request.target_entity_id != self._intent.contact_entity_id
            or request.parent_account_id != self._intent.account_entity_id
            or set(request.source_keys) != {SOURCE_KEY}
            or not set(request.field_keys).issubset(facet_fields)
        ):
            raise EntityResearchResultIntegrityError(
                "Exa contact semantic request differs from exact selected intent"
            )
        observation_window = self._observation_window
        reuse_context_ref: str | None = None
        if request.parent_operation_ref is not None:
            assert request.follow_up_reason is not None
            assert request.parent_observation_ref is not None
            reuse_context_ref = canonical_sha256(
                {
                    "parent_operation_ref": request.parent_operation_ref,
                    "parent_observation_ref": request.parent_observation_ref,
                    "follow_up_reason": request.follow_up_reason.value,
                    "prior_result_sha256": request.prior_result_sha256,
                    "field_keys": request.field_keys,
                    "questions": request.questions,
                }
            )
            observation_window = (
                f"{observation_window}:follow-up:"
                f"{reuse_context_ref[:16]}:"
                f"{request.follow_up_reason.value}"
            )
        caused_refs: set[str] = set()

        async def bind_external_before_dispatch(row: ExternalResearchOperationRow) -> None:
            descriptor = await self._projector.operation(
                row,
                disposition=ProviderObservationDisposition.CAUSED,
                include_dispatch=False,
                field_keys=request.field_keys,
            )
            observation = await before_dispatch(descriptor)
            if (
                observation.tool_request_id == request.tool_call_id
                and observation.disposition == ProviderObservationDisposition.CAUSED.value
            ):
                caused_refs.add(descriptor.operation_ref)

        acquired = await self._acquisition.acquire_intent(
            intent=self._intent,
            effective_policy=self._policy,
            observation_window=observation_window,
            before_dispatch=bind_external_before_dispatch,
            field_keys=request.field_keys,
            directional_questions=request.questions,
            reuse_context_ref=reuse_context_ref,
            prior_research_context=request.prior_research_context,
            entity_research_job_id=self._entity_research_job_id,
        )
        waiting = [
            result
            for result in acquired.results
            if result.outcome is ExaDeepAcquisitionOutcome.JOINED_IN_FLIGHT
        ]
        if waiting:
            first = waiting[0]
            raise EntityResearchProviderWait(
                await self._projector.operation(
                    first.operation,
                    disposition=ProviderObservationDisposition.JOINED,
                    include_dispatch=True,
                    field_keys=request.field_keys,
                )
            )
        ready = [
            result
            for result in acquired.results
            if result.outcome
            in {ExaDeepAcquisitionOutcome.READY, ExaDeepAcquisitionOutcome.REPLAYED}
            and result.snapshot is not None
        ]
        if not ready and all(
            result.outcome in _UNPRODUCTIVE_OUTCOMES for result in acquired.results
        ):
            # Every dispatched bundle is terminal without a snapshot. Settle them so execution
            # closure sees real attempts; the tool layer turns the empty draft set into a governed
            # rejection. A mixed ready/unproductive batch still raises: contact bundles are all
            # projected over the same request field set, so there is no honest field partition.
            await _settle_unproductive_bundles(
                acquired.results,
                projector=self._projector,
                field_keys_for=lambda _result: request.field_keys,
                caused_refs=caused_refs,
                settle_terminal=settle_terminal,
            )
            return ()
        if len(ready) != len(acquired.results):
            raise EntityResearchResultIntegrityError(
                "Exa contact action did not produce a settled ready snapshot"
            )
        await self._materializer.materialize(
            intent=self._intent,
            effective_policy=self._policy,
            run_id=RunId(
                uuid5(
                    _MATERIALIZATION_RUN_NAMESPACE,
                    f"{self._run_id}:{request.tool_call_id}",
                )
            ),
            field_keys=request.field_keys,
            snapshot_reference_ids=tuple(
                str(result.snapshot.snapshot_id) for result in ready if result.snapshot is not None
            ),
        )
        drafts: list[ExternalResearchProjectionDraft] = []
        for result in ready:
            assert result.snapshot is not None
            operation_ref = f"external-research-operation:{result.operation.operation_id}"
            disposition = (
                ProviderObservationDisposition.CAUSED
                if operation_ref in caused_refs
                else ProviderObservationDisposition.REPLAY
            )
            operation = await self._projector.operation(
                result.operation,
                disposition=disposition,
                include_dispatch=True,
                field_keys=request.field_keys,
            )
            bundle_fields = await self._projector.bundle_field_keys(
                result.snapshot.snapshot_id,
                admitted_field_keys=request.field_keys,
            )
            drafts.append(
                await self._projector.build(
                    request=request.model_copy(update={"field_keys": bundle_fields}),
                    operation=operation,
                    snapshot_id=UUID(str(result.snapshot.snapshot_id)),
                )
            )
        return tuple(drafts)


class ExaAccountSemanticResearchAction(EntityResearchProviderAction):
    """Bundle qualitative fields and materialize only the agent-selected Exa attempt."""

    def __init__(
        self,
        *,
        workspace_id: str,
        project_id: str,
        project_run_id: ProjectRunId,
        account_id: EntityId,
        icp_key: str,
        icp_version: int,
        research_directive: ResearchDirectivePin,
        acquisition: ExaDeepAcquisitionCoordinator,
        snapshots: ExaDeepSnapshotResolverProvider,
        projector: ExaEntityResearchProjectionBuilder,
        conn_factory: ConnFactory,
        observation_window: str,
        research_intent: str,
        freshness_policy_ref: str,
        freshness_seconds: int,
        cost_cents_reserved_per_bundle: Decimal,
        entity_research_job_id: UUID | None = None,
        config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
    ) -> None:
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._project_run_id = project_run_id
        self._account_id = account_id
        self._icp_key = icp_key
        self._icp_version = icp_version
        self._directive = research_directive
        self._acquisition = acquisition
        self._snapshots = snapshots
        self._projector = projector
        self._conn_factory = conn_factory
        self._observation_window = observation_window
        self._research_intent = research_intent
        self._freshness_policy_ref = freshness_policy_ref
        self._freshness_seconds = freshness_seconds
        self._reserved_per_bundle = cost_cents_reserved_per_bundle
        self._entity_research_job_id = entity_research_job_id
        self._config = config

    async def execute(
        self,
        request: GovernedResearchToolRequest,
        *,
        before_dispatch: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
        settle_terminal: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
    ) -> Sequence[ExternalResearchProjectionDraft]:
        if (
            request.subject_type is not ResearchSubjectType.ACCOUNT
            or request.target_entity_id != self._account_id
            or set(request.source_keys) != {SOURCE_KEY}
            or not request.field_keys
        ):
            raise EntityResearchResultIntegrityError(
                "Exa account request differs from the exact selected account/source"
            )
        async with self._conn_factory() as conn:
            account = await get_account(conn, self._account_id)
            if account is None or account.workspace_id != self._workspace_id:
                raise EntityResearchResultIntegrityError("Exa account target is absent or foreign")
            effective_fields = []
            for field_key in request.field_keys:
                effective = await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(self._workspace_id),
                    field_key=field_key,
                )
                if (
                    effective is None
                    or effective.value_schema is None
                    or SOURCE_KEY not in effective.field_def.tier_plan
                ):
                    raise EntityResearchResultIntegrityError(
                        f"Exa field {field_key!r} lacks an effective schema/source authorization"
                    )
                effective_fields.append(effective)
        # A comprehensive account directive may be fully bounded by field/source authority and
        # carry no separate human-authored directional question. Exa still needs an internal
        # non-empty planning sentence; compile that mechanically from the exact field-bound task
        # instead of making the user approve redundant prose.
        intent = self._research_intent or DEFAULT_ACCOUNT_RESEARCH_INTENT
        observation_window = self._observation_window
        if request.parent_operation_ref is not None:
            intent = (
                f"{intent}\n\nAdditive follow-up reason: {request.follow_up_reason}. "
                "Use the prior result as context and seek new evidence.\n"
                f"Prior result context:\n{request.prior_research_context}"
            )
            follow_up_digest = canonical_sha256(
                {
                    "tool": str(request.tool_call_id),
                    "prior": request.prior_result_sha256,
                }
            )
            observation_window = f"{observation_window}:follow-up:{follow_up_digest[:16]}"
        try:
            plan = compile_exa_deep_acquisition_plan(
                workspace_id=self._workspace_id,
                project_id=self._project_id,
                project_run_id=self._project_run_id,
                account=account,
                icp_key=self._icp_key,
                icp_version=self._icp_version,
                research_directive=self._directive,
                fields=tuple(
                    ExaDeepFieldSpec(
                        field_key=effective.field_def.field_key,
                        value_schema=cast(dict[str, JsonValue], effective.value_schema),
                    )
                    for effective in effective_fields
                ),
                research_intent=intent,
                additional_queries=request.questions,
                observation_window=observation_window,
                freshness_policy_ref=self._freshness_policy_ref,
                freshness_seconds=self._freshness_seconds,
                cost_cents_reserved_per_bundle=self._reserved_per_bundle,
                entity_research_job_id=self._entity_research_job_id,
                config=self._config,
            )
        except ExaDeepRequestBoundExceeded as bound:
            # Nothing was reserved or dispatched — the request text is simply too long, and above
            # it is the model's own follow-up reason plus the prior result context that grew it.
            # Live, this killed a whole account job as a raw ValueError; it is an ordinary
            # request-shape violation, so refuse it repairably instead.
            raise EntityResearchGovernedRejection(
                "research_request_shape_rejected",
                f"{bound}; shorten the follow-up reason, request the remaining fields without "
                "the prior-result follow-up, or finalize honestly with the gap",
            ) from bound
        caused_refs: set[str] = set()
        operation_fields: dict[UUID, tuple[str, ...]] = {}
        acquired = []
        for bundle in plan.bundles:
            bundle_fields = tuple(
                str(field_key) for field_key in bundle.exa_request.field_key_by_alias.values()
            )

            async def bind_external_before_dispatch(
                row: ExternalResearchOperationRow,
                *,
                exact_fields: tuple[str, ...] = bundle_fields,
            ) -> None:
                operation_fields[row.operation_id] = exact_fields
                descriptor = await self._projector.operation(
                    row,
                    disposition=ProviderObservationDisposition.CAUSED,
                    include_dispatch=False,
                    field_keys=exact_fields,
                )
                observation = await before_dispatch(descriptor)
                if (
                    observation.tool_request_id == request.tool_call_id
                    and observation.disposition == ProviderObservationDisposition.CAUSED.value
                ):
                    caused_refs.add(descriptor.operation_ref)

            item = await self._acquisition.acquire(
                bundle, before_dispatch=bind_external_before_dispatch
            )
            operation_fields.setdefault(item.operation.operation_id, bundle_fields)
            acquired.append(item)
        waiting = [
            item for item in acquired if item.outcome is ExaDeepAcquisitionOutcome.JOINED_IN_FLIGHT
        ]
        if waiting:
            raise EntityResearchProviderWait(
                await self._projector.operation(
                    waiting[0].operation,
                    disposition=ProviderObservationDisposition.JOINED,
                    include_dispatch=True,
                    field_keys=operation_fields[waiting[0].operation.operation_id],
                )
            )
        ready = [
            item
            for item in acquired
            if item.outcome in {ExaDeepAcquisitionOutcome.READY, ExaDeepAcquisitionOutcome.REPLAYED}
            and item.snapshot is not None
        ]
        unproductive = [item for item in acquired if item.outcome in _UNPRODUCTIVE_OUTCOMES]
        if len(ready) + len(unproductive) != len(acquired):
            raise EntityResearchResultIntegrityError(
                "Exa account action did not produce settled ready snapshots"
            )
        settled_fields = await _settle_unproductive_bundles(
            unproductive,
            projector=self._projector,
            field_keys_for=lambda item: operation_fields[item.operation.operation_id],
            caused_refs=caused_refs,
            settle_terminal=settle_terminal,
        )
        if not ready:
            return ()
        effective_fields = [
            effective
            for effective in effective_fields
            if effective.field_def.field_key not in settled_fields
        ]
        bindings = await self._snapshots.resolver_bindings(
            workspace_id=self._workspace_id,
            project_run_id=self._project_run_id,
            account_entity_id=self._account_id,
            research_directive=self._directive,
        )
        resolver = bindings.bindings.get(SOURCE_KEY)
        if resolver is None:
            raise EntityResearchResultIntegrityError(
                "ready Exa account snapshots did not produce a snapshot resolver"
            )
        run_id = RunId(
            uuid5(
                _ACCOUNT_MATERIALIZATION_RUN_NAMESPACE,
                f"{request.research_run_id}:{request.tool_call_id}",
            )
        )
        # FI-2 P2 (spec §3): this derived per-tool-call run — not the launch ``research_run_id`` —
        # is what every claim below carries, so it is the id the project lens must resolve. The
        # field loop takes one connection per field, so there is no single transaction to join;
        # registering first is the safe direction (a run that wrote nothing is inert, an
        # unattributable claim is not). Idempotent, so a replayed tool call re-registers harmlessly.
        async with self._conn_factory() as conn:
            await record_run_lineage(
                conn,
                run_id=run_id,
                workspace_id=self._workspace_id,
                kind="entity_research",
                project_id=self._project_id,
                project_run_id=UUID(str(self._project_run_id)),
            )
        with bind_resolver_overrides({SOURCE_KEY: resolver}):
            for effective in effective_fields:
                async with self._conn_factory() as conn:
                    await resolve_field(
                        conn,
                        Entity(entity_id=self._account_id, entity_type=EntityType.ACCOUNT),
                        effective.field_def.model_copy(update={"tier_plan": (SOURCE_KEY,)}),
                        mode=ResearchMode.ACCOUNT_PROFILING,
                        run_id=run_id,
                        workspace_id=self._workspace_id,
                    )
                    # No claim is the correct materialization for an explicit provider null.
                    # ``ExaEntityResearchProjectionBuilder._field`` below distinguishes that
                    # honest empty from rejected/unsupported evidence and still fails closed if
                    # the normalization contains a synthesized value without a durable claim.
                    # Requiring one claim for every requested field here made comprehensive
                    # research impossible whenever Exa correctly answered "not found".
        drafts: list[ExternalResearchProjectionDraft] = []
        for item in ready:
            assert item.snapshot is not None
            operation_ref = f"external-research-operation:{item.operation.operation_id}"
            operation = await self._projector.operation(
                item.operation,
                disposition=(
                    ProviderObservationDisposition.CAUSED
                    if operation_ref in caused_refs
                    else ProviderObservationDisposition.REPLAY
                ),
                include_dispatch=True,
                field_keys=operation_fields[item.operation.operation_id],
            )
            bundle_fields = await self._projector.bundle_field_keys(
                item.snapshot.snapshot_id,
                admitted_field_keys=request.field_keys,
            )
            drafts.append(
                await self._projector.build(
                    request=request.model_copy(update={"field_keys": bundle_fields}),
                    operation=operation,
                    snapshot_id=UUID(str(item.snapshot.snapshot_id)),
                )
            )
        return tuple(drafts)


__all__ = [
    "DEFAULT_ACCOUNT_RESEARCH_INTENT",
    "ExaAccountSemanticResearchAction",
    "ExaContactSemanticResearchAction",
    "ExaEntityResearchProjectionBuilder",
]
