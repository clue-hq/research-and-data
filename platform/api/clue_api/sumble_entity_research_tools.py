"""M8D R5 Sumble account enrichment projection behind the provider-neutral R4 seam."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.account_entity_research import (
    AccountBuyingUnitScope,
    DiscoverBuyingCommitteeInput,
)
from clue_agents.entity_research_runtime import current_entity_research_tool_execution
from clue_api.committee_eligibility import CommitteeEligibilityService
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    EntityResearchProviderAction,
    EntityResearchProviderWait,
    EntityResearchResultIntegrityError,
    ExternalResearchProjectionDraft,
    ProviderObservationDisposition,
    ProviderOperationObservation,
    ProviderOperationReservation,
    ProviderResultLineage,
    ProviderResultLineageReader,
    fold_rejected_operation_settlement,
)
from clue_api.sumble_account_gaps import (
    SumbleAccountGapNotEligible,
    SumbleAccountGapOutcome,
    SumbleAccountGapStarter,
)
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    SumbleCommitteeOutcome,
    SumbleCommitteePreflight,
)
from clue_api.sumble_committee_preparation import SumbleCommitteePreparationInputs
from clue_api.sumble_committee_source import SumbleCommitteeSource
from clue_core import (
    AccountGapFieldResult,
    AccountGapFieldState,
    AccountGapOperation,
    AccountGapOperationState,
    AccountGapSnapshotState,
    CommitteeAcquisitionOperation,
    CommitteeEligibilityOutcome,
    EntityId,
    LLMGateway,
    ProjectRunId,
    ResearchCommitteePlan,
    RunId,
    decode_jsonb_scalar,
    serialize_value_json,
)
from clue_core.entity_research import (
    GovernedResearchToolRequest,
    ResearchClaimDelta,
    ResearchDiscoveredSubjectProjection,
    ResearchEvidenceProjection,
    ResearchFieldOutcome,
    ResearchFieldResultProjection,
    ResearchSubjectType,
)
from clue_research.claimstore import record_run_lineage
from clue_research.durable import (
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
    list_account_gap_field_results,
    list_account_gap_snapshots,
    list_committee_acquisition_snapshots,
)
from clue_research.identity import get_account
from clue_research.profiling.committee import (
    CURRENT_LOCATION,
    JOB_FUNCTION,
    ORGANIZATION_RELATIONSHIP,
    TEAM_MEMBERSHIP,
    CommitteePersonCandidate,
    CommitteeResult,
    CommitteeSource,
    discover_committee,
)
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from clue_storage import StorageBackend

ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r5:sumble-account-evidence")


def _match_haystack(*values: object) -> str:
    """Fold provider-returned string values (never JSON keys) into one search haystack.

    Values are newline-delimited so a scope term can never match a phrase stitched together
    across two unrelated values.
    """

    parts: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            if value:
                parts.append(value)
        elif isinstance(value, Mapping):
            for item in value.values():
                collect(item)
        elif isinstance(value, Sequence):
            for item in value:
                collect(item)

    for value in values:
        collect(value)
    return "\n".join(parts).casefold()


# US state name <-> USPS abbreviation, both directions, for the region tier of the office gate.
# Providers spell regions out ("New Jersey") while an agent scope may abbreviate ("NJ"); in the
# first live canary that single spelling difference vetoed a provider-perfect Paramus candidate
# whose row satisfied locality, function, and exact current employer. Normalization is bounded to
# this one closed vocabulary; free-text geo is never guessed.
_US_STATE_BY_ABBREVIATION: Final[dict[str, str]] = {
    "al": "alabama",
    "ak": "alaska",
    "az": "arizona",
    "ar": "arkansas",
    "ca": "california",
    "co": "colorado",
    "ct": "connecticut",
    "de": "delaware",
    "fl": "florida",
    "ga": "georgia",
    "hi": "hawaii",
    "id": "idaho",
    "il": "illinois",
    "in": "indiana",
    "ia": "iowa",
    "ks": "kansas",
    "ky": "kentucky",
    "la": "louisiana",
    "me": "maine",
    "md": "maryland",
    "ma": "massachusetts",
    "mi": "michigan",
    "mn": "minnesota",
    "ms": "mississippi",
    "mo": "missouri",
    "mt": "montana",
    "ne": "nebraska",
    "nv": "nevada",
    "nh": "new hampshire",
    "nj": "new jersey",
    "nm": "new mexico",
    "ny": "new york",
    "nc": "north carolina",
    "nd": "north dakota",
    "oh": "ohio",
    "ok": "oklahoma",
    "or": "oregon",
    "pa": "pennsylvania",
    "ri": "rhode island",
    "sc": "south carolina",
    "sd": "south dakota",
    "tn": "tennessee",
    "tx": "texas",
    "ut": "utah",
    "vt": "vermont",
    "va": "virginia",
    "wa": "washington",
    "wv": "west virginia",
    "wi": "wisconsin",
    "wy": "wyoming",
    "dc": "district of columbia",
}
_US_STATE_ABBREVIATION_BY_NAME: Final[dict[str, str]] = {
    name: abbreviation for abbreviation, name in _US_STATE_BY_ABBREVIATION.items()
}


def _region_alternatives(region: str) -> tuple[str, ...]:
    """Return the declared region plus its US-state spelling twin, casefolded."""

    folded = region.casefold().strip()
    twin = _US_STATE_BY_ABBREVIATION.get(folded) or _US_STATE_ABBREVIATION_BY_NAME.get(folded)
    return (folded, twin) if twin else (folded,)


def _location_scope_match(scope: AccountBuyingUnitScope, *, haystack: str) -> bool:
    """Match the office scope against provider-returned location values, most specific first.

    The declared terms form a containment hierarchy (facility ⊂ locality ⊂ region ⊂ country).
    Only the most specific declared tier must be evidenced: once "Paramus" is present in the
    provider values, "New Jersey"/"United States" are containers of the same fact and requiring
    them independently can only manufacture false vetoes (the first live canary lost a perfect
    candidate to "NJ" vs "New Jersey"). A candidate whose values evidence no declared tier still
    fails closed to review — profile metros are never inferred to be office assignments.
    """

    if scope.facility_name is not None or scope.locality is not None:
        alternatives = tuple(
            value.casefold() for value in (scope.facility_name, scope.locality) if value is not None
        )
        return any(value in haystack for value in alternatives)
    if scope.region is not None:
        return any(value in haystack for value in _region_alternatives(scope.region))
    if scope.country is not None:
        return scope.country.casefold() in haystack
    return True


def _organization_names(facts: object) -> tuple[str, ...]:
    """Extract only the provider-returned current-employer organization names."""

    names: list[str] = []
    if isinstance(facts, Sequence):
        for fact in facts:
            if isinstance(fact, Mapping):
                name = fact.get("organization_name")
                if isinstance(name, str) and name:
                    names.append(name)
    return tuple(names)


def _operation_ref(operation: AccountGapOperation) -> str:
    return f"sumble-account-operation:{operation.operation_id}"


class SumbleEntityResearchLineageReader(ProviderResultLineageReader):
    """Read the immutable normalized projection joining Sumble's provider-owned ledgers."""

    def __init__(self, *, provider_kind: str, conn_factory: ConnFactory) -> None:
        self.provider_kind = provider_kind
        self._conn_factory = conn_factory

    async def load(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: ProviderOperationReservation,
        snapshot_ref: str,
    ) -> ProviderResultLineage:
        if operation.provider_kind != self.provider_kind:
            raise EntityResearchResultIntegrityError("Sumble lineage reader received another kind")
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT workspace_id, provider_snapshot_ref,
                                   normalized_result_artifact_key,
                                   raw_response_artifact_refs, retained_result_artifact_refs,
                                   provider_receipt_ref, cost_settlement_ref,
                                   provider_request_id, provider_reported_cost_cents,
                                   settled_cost_cents
                            FROM entity_research_sumble_projection
                            WHERE provider_operation_ref=:operation_ref
                            """
                        ),
                        {"operation_ref": operation.operation_ref},
                    )
                )
                .mappings()
                .first()
            )
            component_snapshot_refs = await self._component_snapshot_refs(
                conn,
                operation=operation,
            )
        if (
            row is None
            or str(row["workspace_id"]) != operation.workspace_id
            or str(row["provider_snapshot_ref"]) != snapshot_ref
            or request.target_entity_id != operation.target_entity_id
        ):
            raise EntityResearchResultIntegrityError("Sumble lineage crosses exact operation scope")
        return ProviderResultLineage(
            operation=operation,
            snapshot_ref=snapshot_ref,
            claim_source_snapshot_refs=component_snapshot_refs,
            raw_response_artifact_refs=tuple(
                str(value) for value in row["raw_response_artifact_refs"]
            ),
            retained_result_artifact_refs=tuple(
                str(value) for value in row["retained_result_artifact_refs"]
            ),
            normalized_result_artifact_ref=f"artifact:{row['normalized_result_artifact_key']}",
            provider_receipt_ref=str(row["provider_receipt_ref"]),
            cost_settlement_ref=str(row["cost_settlement_ref"]),
            provider_request_id=str(row["provider_request_id"]),
            provider_reported_cost_cents=Decimal(row["provider_reported_cost_cents"]),
            settled_cost_cents=Decimal(row["settled_cost_cents"]),
        )

    async def _component_snapshot_refs(
        self,
        conn: AsyncConnection,
        *,
        operation: ProviderOperationReservation,
    ) -> tuple[str, ...]:
        """Resolve claim-level snapshots from the immutable owning Sumble ledger.

        Account enrichment normalizes the organization lookup and the selected structured source
        into one aggregate entity-research snapshot, while every claim correctly retains the
        specific `account_gap_snapshot` that supplied it. Committee acquisition has the same
        shape for Teams and People. The generic result store must validate those claim refs against
        provider-owned rows rather than incorrectly requiring the aggregate ref on every claim.
        """

        try:
            operation_id = UUID(operation.operation_ref.rsplit(":", 1)[-1])
        except ValueError as error:
            raise EntityResearchResultIntegrityError(
                "Sumble operation reference is malformed"
            ) from error
        if self.provider_kind == "sumble_account":
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT source_key, request_fingerprint FROM account_gap_snapshot "
                            "WHERE operation_id=:operation_id AND workspace_id=:workspace_id "
                            "AND state='succeeded'"
                        ),
                        {
                            "operation_id": operation_id,
                            "workspace_id": operation.workspace_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            return tuple(
                sorted(
                    f"account-gap-snapshot:{operation_id}:{row['source_key']}:"
                    f"{row['request_fingerprint']}"
                    for row in rows
                )
            )
        if self.provider_kind == "sumble_committee":
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT source_key, request_fingerprint "
                            "FROM committee_acquisition_snapshot "
                            "WHERE operation_id=:operation_id AND workspace_id=:workspace_id "
                            "AND state='succeeded'"
                        ),
                        {
                            "operation_id": operation_id,
                            "workspace_id": operation.workspace_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            return tuple(
                sorted(
                    f"committee-snapshot:{operation_id}:{row['source_key']}:"
                    f"{row['request_fingerprint']}"
                    for row in rows
                )
            )
        raise EntityResearchResultIntegrityError("unknown Sumble provider lineage kind")


class SumbleAccountSemanticEnrichmentAction(EntityResearchProviderAction):
    """Run one exact structured-source field group, independent from qualitative Exa research."""

    provider_kind = "sumble_account"

    def __init__(
        self,
        *,
        starter: SumbleAccountGapStarter,
        storage: StorageBackend,
        conn_factory: ConnFactory,
        workspace_id: str,
        project_id: str,
        project_run_id: ProjectRunId,
        account_id: EntityId,
        field_expected_value_credits: Mapping[str, Decimal],
        provider_credit_cap: int,
        allow_unbounded_tech: bool = False,
        entity_research_job_id: UUID | None = None,
    ) -> None:
        self._starter = starter
        self._storage = storage
        self._conn_factory = conn_factory
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._project_run_id = project_run_id
        self._account_id = account_id
        self._values = dict(field_expected_value_credits)
        self._provider_credit_cap = provider_credit_cap
        self._allow_unbounded_tech = allow_unbounded_tech
        self._entity_research_job_id = entity_research_job_id

    async def execute(
        self,
        request: GovernedResearchToolRequest,
        *,
        before_dispatch: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
    ) -> Sequence[ExternalResearchProjectionDraft]:
        if (
            request.subject_type is not ResearchSubjectType.ACCOUNT
            or request.target_entity_id != self._account_id
            or set(request.field_keys) - set(self._values)
            or request.parent_operation_ref is not None
            or len(request.source_keys) != 1
            or any(
                tuple(item.source_keys) != request.source_keys
                for item in request.field_source_authority
            )
        ):
            raise EntityResearchGovernedRejection(
                "field_source_authority_mismatch",
                "Sumble account enrichment differs from exact structured field/source authority",
            )
        caused = False

        async def bind_sumble_before_dispatch(operation: AccountGapOperation) -> None:
            nonlocal caused
            descriptor = self._descriptor(
                operation,
                source_key=request.source_keys[0],
                field_keys=request.field_keys,
                disposition=ProviderObservationDisposition.CAUSED,
                include_dispatch=False,
            )
            observation = await before_dispatch(descriptor)
            caused = (
                observation.tool_request_id == request.tool_call_id
                and observation.disposition == ProviderObservationDisposition.CAUSED.value
            )

        try:
            result = await self._starter.start(
                workspace_id=self._workspace_id,
                project_run_id=self._project_run_id,
                account_id=self._account_id,
                field_expected_value_credits={key: self._values[key] for key in request.field_keys},
                provider_credit_cap=self._provider_credit_cap,
                # One composed action serves independently partitioned Sumble source calls.  The
                # directive-level authority may include tech, but only the tech partition should
                # carry that provider-specific approval; applying it to a simultaneous jobs or
                # organizations call makes the preflight correctly reject that non-tech call.
                allow_unbounded_tech=(
                    self._allow_unbounded_tech and "core.primary_tech_stack" in request.field_keys
                ),
                before_dispatch=bind_sumble_before_dispatch,
                entity_research_job_id=self._entity_research_job_id,
            )
        except SumbleAccountGapNotEligible as exc:
            # FI-2 §6.3(b), and *only* §6.3(b): the ladder found the field already confidently and
            # freshly answered.  The preflight refuses before any operation row or dispatch, so
            # this is a zero-spend, zero-state refusal of the request the agent made — the
            # model-repairable species (R10), not a job suspension.  The agent drops that field,
            # picks another admitted source, or finalizes with an honest gap.
            #
            # Deliberately the subclass, not the ``SumbleAccountGapEligibilityError`` family: the
            # other members (job authority lost, discovery seal conflicted, account not the
            # canonical survivor, a field mis-declared as project-relative) are facts about the
            # world that no choice of the agent's repairs, and they were suspending before §6.3(b)
            # existed.  Catching the base class here would have converted a fenced-out job's
            # authority failure into a turn it could keep taking.  (The legacy toolbelt path does
            # convert the whole family, to ``PreconditionFailed`` — a human-facing precondition,
            # not an agent turn.)
            raise EntityResearchGovernedRejection(
                "account_gap_ineligible",
                f"Sumble account enrichment is not eligible for this request: {exc}",
            ) from exc
        if result.outcome is SumbleAccountGapOutcome.JOINED_IN_FLIGHT:
            raise EntityResearchProviderWait(
                self._descriptor(
                    result.operation,
                    source_key=request.source_keys[0],
                    field_keys=request.field_keys,
                    disposition=ProviderObservationDisposition.JOINED,
                    include_dispatch=True,
                )
            )
        if result.outcome is SumbleAccountGapOutcome.FAILED_TERMINAL:
            # Deterministic provider refusal: zero-charge, diagnostics durable on the gap ledger.
            # The agent may pick another admitted source or finalize with an explicit gap.
            await fold_rejected_operation_settlement(
                self._conn_factory,
                request=request,
                operation_ref=_operation_ref(result.operation),
            )
            raise EntityResearchGovernedRejection(
                "provider_rejected",
                "Sumble account enrichment was terminally rejected by the provider "
                f"(failure_code={result.operation.failure_code or 'unrecorded'}); the durable "
                "operation ledger retains the exact provider diagnostic",
            )
        if (
            result.outcome
            not in {
                SumbleAccountGapOutcome.COMPLETED,
                SumbleAccountGapOutcome.REPLAYED,
            }
            or result.operation.state is not AccountGapOperationState.SUCCEEDED
        ):
            raise EntityResearchResultIntegrityError(
                f"Sumble account enrichment did not settle safely: {result.outcome.value}"
            )
        operation = self._descriptor(
            result.operation,
            source_key=request.source_keys[0],
            field_keys=request.field_keys,
            disposition=(
                ProviderObservationDisposition.CAUSED
                if caused
                else ProviderObservationDisposition.REPLAY
            ),
            include_dispatch=True,
        )
        snapshot_ref, fields = await self._persist_projection(
            request=request,
            operation=result.operation,
            provider_operation=operation,
        )
        return (
            ExternalResearchProjectionDraft(
                operation=operation,
                snapshot_ref=snapshot_ref,
                requested_field_keys=request.field_keys,
                fields=fields,
            ),
        )

    def _descriptor(
        self,
        operation: AccountGapOperation,
        *,
        source_key: str,
        field_keys: tuple[str, ...],
        disposition: ProviderObservationDisposition,
        include_dispatch: bool,
    ) -> ProviderOperationReservation:
        created = operation.created_at or datetime.now(UTC)
        return ProviderOperationReservation(
            provider_kind=self.provider_kind,
            operation_ref=_operation_ref(operation),
            workspace_id=operation.request.workspace_id,
            project_id=operation.request.project_id,
            project_run_id=UUID(str(operation.request.project_run_id)),
            subject_type=ResearchSubjectType.ACCOUNT,
            target_entity_id=UUID(str(operation.request.account_id)),
            source_key=source_key,
            field_keys=field_keys,
            request_artifact_ref=f"artifact:{operation.input_artifact_key}",
            reserved_at=created,
            dispatched_at=(operation.started_at if include_dispatch else None),
            observation_disposition=disposition,
        )

    async def _persist_projection(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: AccountGapOperation,
        provider_operation: ProviderOperationReservation,
    ) -> tuple[str, tuple[ResearchFieldResultProjection, ...]]:
        async with self._conn_factory() as conn:
            snapshots = await list_account_gap_snapshots(
                conn,
                workspace_id=self._workspace_id,
                operation_id=operation.operation_id,
            )
            field_results = {
                str(item.field_key): item
                for item in await list_account_gap_field_results(
                    conn,
                    workspace_id=self._workspace_id,
                    operation_id=operation.operation_id,
                )
            }
            claim_ids = {
                UUID(str(claim_id))
                for result in field_results.values()
                for claim_id in (
                    *((result.sumble_claim_id,) if result.sumble_claim_id else ()),
                    *result.conflicting_claim_ids,
                )
            }
            claims = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, field_key, value_json, source_key, source_url,
                                   artifact_key, evidence_span, confidence,
                                   verification_status::text, corroborations
                            FROM claim WHERE id=ANY(:claim_ids) ORDER BY collected_at DESC, id
                            """
                        ),
                        {"claim_ids": list(claim_ids)},
                    )
                )
                .mappings()
                .all()
                if claim_ids
                else ()
            )
            claims_by_id: dict[UUID, Mapping[str, object]] = {
                UUID(str(row["id"])): cast(Mapping[str, object], row) for row in claims
            }
            projected = tuple(
                self._field(
                    field_results[field_key],
                    claims_by_id=claims_by_id,
                    provider_request_id=";".join(
                        sorted(
                            str(item.provider_request_id)
                            for item in snapshots
                            if item.provider_request_id is not None
                        )
                    ),
                    operation_id=UUID(str(operation.operation_id)),
                )
                for field_key in request.field_keys
            )
            payload = {
                "contract": "m8d-r5-sumble-account-projection-v1",
                "operation": operation.model_dump(mode="json"),
                "snapshots": [item.model_dump(mode="json") for item in snapshots],
                "fields": [item.model_dump(mode="json") for item in projected],
            }
            normalized_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=self._workspace_id,
                content=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
                media_type="application/json",
                source_key=provider_operation.source_key,
            )
            await bind_discovery_artifact_subject(
                conn,
                workspace_id=self._workspace_id,
                artifact_key_value=normalized_key,
                subject_kind="account",
                subject_entity_id=self._account_id,
                reference_kind="entity_research_sumble_normalized",
                reference_id=provider_operation.operation_ref,
            )
            successful = [
                item
                for item in snapshots
                if item.state is AccountGapSnapshotState.SUCCEEDED
                and item.response_artifact_key is not None
            ]
            raw_refs = [f"artifact:{item.response_artifact_key}" for item in successful]
            if not raw_refs or operation.receipt_manifest_key is None:
                raise EntityResearchResultIntegrityError(
                    "settled Sumble account operation lacks raw response or receipt"
                )
            snapshot_ref = (
                f"sumble-account-snapshot:{operation.operation_id}:"
                f"{hashlib.sha256('|'.join(sorted(raw_refs)).encode()).hexdigest()}"
            )
            provider_request_id = ";".join(
                sorted(
                    str(item.provider_request_id)
                    for item in successful
                    if item.provider_request_id is not None
                )
            ) or str(operation.operation_id)
            values = {
                "operation_ref": provider_operation.operation_ref,
                "workspace_id": self._workspace_id,
                "snapshot_ref": snapshot_ref,
                "normalized_key": normalized_key,
                "raw_refs": raw_refs,
                "receipt_ref": f"artifact:{operation.receipt_manifest_key}",
                "settlement_ref": f"sumble-account-settlement:{operation.operation_id}",
                "provider_request_id": provider_request_id,
                "reported_cost": operation.cost_cents_charged,
                "settled_cost": operation.cost_cents_charged,
                "metadata": "{}",
            }
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_sumble_projection
                        (provider_operation_ref, workspace_id, provider_snapshot_ref,
                         normalized_result_artifact_key, raw_response_artifact_refs,
                         retained_result_artifact_refs, provider_receipt_ref,
                         cost_settlement_ref, provider_request_id,
                         provider_reported_cost_cents, settled_cost_cents, metadata_json)
                    VALUES (:operation_ref, :workspace_id, :snapshot_ref, :normalized_key,
                            :raw_refs, :raw_refs, :receipt_ref, :settlement_ref,
                            :provider_request_id, :reported_cost, :settled_cost,
                            CAST(:metadata AS jsonb))
                    ON CONFLICT (provider_operation_ref) DO NOTHING
                    """
                ),
                values,
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT provider_snapshot_ref, normalized_result_artifact_key "
                            "FROM entity_research_sumble_projection "
                            "WHERE provider_operation_ref=:operation_ref"
                        ),
                        {"operation_ref": provider_operation.operation_ref},
                    )
                )
                .mappings()
                .one()
            )
            if (
                str(stored["provider_snapshot_ref"]) != snapshot_ref
                or str(stored["normalized_result_artifact_key"]) != normalized_key
            ):
                raise EntityResearchResultIntegrityError("Sumble projection replay changed")
        return snapshot_ref, projected

    def _field(
        self,
        result: object,
        *,
        claims_by_id: Mapping[UUID, Mapping[str, object]],
        provider_request_id: str,
        operation_id: UUID,
    ) -> ResearchFieldResultProjection:
        field = cast("AccountGapFieldResult", result)
        if field.state is AccountGapFieldState.CONFIRMED_MISSING:
            return ResearchFieldResultProjection(
                field_key=str(field.field_key),
                outcome=ResearchFieldOutcome.NULL,
                claim_delta=ResearchClaimDelta.NONE,
                verification_status=field.reason_code or "confirmed_missing",
            )
        ids = tuple(
            UUID(str(value))
            for value in (
                field.conflicting_claim_ids
                if field.state is AccountGapFieldState.CONFLICT
                else ((field.sumble_claim_id,) if field.sumble_claim_id else ())
            )
        )
        rows = tuple(claims_by_id[value] for value in ids)
        evidence = tuple(
            ResearchEvidenceProjection(
                evidence_ref=(
                    f"research-evidence:{uuid5(_EVIDENCE_NAMESPACE, f'{operation_id}:{row["id"]}')}"
                ),
                source_key=str(row["source_key"]),
                provider_source_id=provider_request_id,
                source_url=str(row["source_url"]) if row["source_url"] else None,
                artifact_ref=f"artifact:{row['artifact_key']}",
                evidence_span=str(row["evidence_span"]),
            )
            for row in rows
        )
        if field.state is AccountGapFieldState.CONFLICT:
            return ResearchFieldResultProjection(
                field_key=str(field.field_key),
                outcome=ResearchFieldOutcome.CONFLICT,
                claim_delta=ResearchClaimDelta.CONFLICTING,
                claim_refs=tuple(f"claim:{value}" for value in ids),
                decision_refs=(f"conflict:{field.account_id}:{field.field_key}",),
                evidence=evidence,
                confidence=max(float(cast(Decimal, row["confidence"])) for row in rows),
                verification_status="flagged_conflict",
            )
        if not rows:
            raise EntityResearchResultIntegrityError("resolved Sumble field lacks its claim")
        row = rows[0]
        corroborating = field.state is AccountGapFieldState.CORROBORATED
        return ResearchFieldResultProjection(
            field_key=str(field.field_key),
            outcome=ResearchFieldOutcome.FOUND,
            value=decode_jsonb_scalar(row["value_json"]),
            claim_delta=(
                ResearchClaimDelta.CORROBORATING if corroborating else ResearchClaimDelta.ACCEPTED
            ),
            claim_refs=(f"claim:{row['id']}",),
            evidence=evidence,
            confidence=float(cast(Decimal, row["confidence"])),
            verification_status=str(row["verification_status"]),
        )


class _PreparedCommitteeSource(CommitteeSource):
    source_key = PEOPLE_SOURCE_KEY
    tier = 1

    def __init__(self, candidates: Sequence[CommitteePersonCandidate]) -> None:
        self._candidates = tuple(candidates)

    async def find_candidates(
        self, account: object, *, limit: int
    ) -> Sequence[CommitteePersonCandidate]:
        del account
        return self._candidates[:limit]


class SumbleCommitteeAgentInputResolver(Protocol):
    async def resolve(self) -> SumbleCommitteePreparationInputs: ...


class SumbleCommitteeSemanticResearchAction(EntityResearchProviderAction):
    """Acquire Teams/People, enforce the declared office, then project admitted members."""

    provider_kind = "sumble_committee"

    def __init__(
        self,
        *,
        preflight: SumbleCommitteePreflight | None = None,
        inputs: SumbleCommitteeAgentInputResolver | None = None,
        eligibility: CommitteeEligibilityService | None = None,
        coordinator: SumbleCommitteeAcquisitionCoordinator,
        storage: StorageBackend,
        conn_factory: ConnFactory,
        gateway: LLMGateway,
        role_model: str,
    ) -> None:
        if (preflight is None) == (inputs is None):
            raise ValueError("committee action requires exactly one static or run-scoped input")
        if inputs is not None and eligibility is None:
            raise ValueError("run-scoped committee input requires the complete S2 eligibility gate")
        self._preflight = preflight
        self._inputs = inputs
        self._eligibility = eligibility
        self._coordinator = coordinator
        self._storage = storage
        self._conn_factory = conn_factory
        self._gateway = gateway
        self._role_model = role_model

    async def execute(
        self,
        request: GovernedResearchToolRequest,
        *,
        before_dispatch: Callable[
            [ProviderOperationReservation], Awaitable[ProviderOperationObservation]
        ],
    ) -> Sequence[ExternalResearchProjectionDraft]:
        active = current_entity_research_tool_execution()
        semantic = DiscoverBuyingCommitteeInput.model_validate(active.call.arguments)
        scope = semantic.buying_unit_scope
        preflight, committee_plan = await self._resolve_inputs()
        durable = preflight.request
        self._validate_scope_against_plan(scope, plan=committee_plan)
        if (
            request.subject_type is not ResearchSubjectType.ACCOUNT
            or request.target_entity_id != durable.account_id
            or scope.account_entity_id != request.target_entity_id
            or set(request.source_keys) != {PEOPLE_SOURCE_KEY}
            or request.field_keys
            or request.parent_operation_ref is not None
        ):
            raise EntityResearchGovernedRejection(
                "committee_request_authority_mismatch",
                "Sumble committee request differs from exact account/people/scope authority",
            )
        await self._persist_scope(
            request=request,
            scope=scope,
            workspace_id=durable.workspace_id,
        )
        caused = False

        async def bind_sumble_before_dispatch(operation: object) -> None:
            nonlocal caused
            typed = cast("CommitteeAcquisitionOperation", operation)
            descriptor = self._committee_descriptor(
                typed,
                disposition=ProviderObservationDisposition.CAUSED,
                include_dispatch=False,
            )
            observation = await before_dispatch(descriptor)
            caused = caused or (
                observation.tool_request_id == request.tool_call_id
                and observation.disposition == ProviderObservationDisposition.CAUSED.value
            )

        acquired = await self._coordinator.start(
            preflight, before_dispatch=bind_sumble_before_dispatch
        )
        if acquired.outcome in {
            SumbleCommitteeOutcome.WAITING_EXTERNAL,
            SumbleCommitteeOutcome.JOINED_IN_FLIGHT,
            SumbleCommitteeOutcome.RATE_LIMITED,
        }:
            raise EntityResearchProviderWait(
                self._committee_descriptor(
                    acquired.operation,
                    # A newly dispatched asynchronous operation remains caused by this exact
                    # tool while it waits.  Only a later tool that joined an existing operation
                    # is a joined observation.  Re-labelling the causal row as joined made the
                    # immutable causation ledger reject honest Sumble polling waits.
                    disposition=self._wait_disposition(caused=caused),
                    include_dispatch=True,
                )
            )
        if acquired.outcome is SumbleCommitteeOutcome.FAILED_TERMINAL:
            # Deterministic provider refusal (for example a validated zero-charge HTTP 4xx): the
            # committee ledger retains the status and the provider's own bounded error body. The
            # agent decides — repair, another admitted source, or an explicit partial committee.
            await fold_rejected_operation_settlement(
                self._conn_factory,
                request=request,
                operation_ref=f"committee-operation:{acquired.operation.operation_id}",
            )
            raise EntityResearchGovernedRejection(
                "provider_rejected",
                "Sumble committee acquisition was terminally rejected "
                f"(failure_code={acquired.operation.failure_code or 'unrecorded'}); the durable "
                "committee ledger retains the exact provider diagnostic",
            )
        if acquired.outcome not in {
            SumbleCommitteeOutcome.READY,
            SumbleCommitteeOutcome.REPLAYED,
        }:
            raise EntityResearchResultIntegrityError(
                f"Sumble committee acquisition did not settle safely: {acquired.outcome.value}"
            )
        async with self._conn_factory() as conn:
            account = await get_account(conn, EntityId(request.target_entity_id))
        if account is None or account.workspace_id != durable.workspace_id:
            raise EntityResearchResultIntegrityError("committee account is absent or foreign")
        source = SumbleCommitteeSource(
            operation_ids={EntityId(request.target_entity_id): acquired.operation.operation_id},
            storage=self._storage,
            conn_factory=self._conn_factory,
        )
        candidates = tuple(await source.find_candidates(account, limit=durable.people_limit))
        selected, excluded, ambiguous = self._office_candidates(candidates, scope=scope)
        # Committee claims are stamped with the exact project run: the M8C C1 lineage trigger
        # refuses a Sumble professional claim whose run differs from its ready operation's
        # project_run_id (a synthetic per-tool-call run id was rejected live), and the project
        # run is also the correct idempotency domain — a repeat committee call replays the
        # existing member/role claims instead of superseding them per tool call.
        run_id = RunId(UUID(str(durable.project_run_id)))
        async with self._conn_factory() as conn:
            # FI-2 P2 (spec §3): register the committee run in the same transaction as the
            # role/persona/discovery claims ``discover_committee`` writes below. Idempotent, so a
            # repeat committee call re-registers harmlessly. Because this run id *is* the project
            # run, the enrichment materializer may already have registered it under its own kind —
            # first writer wins on ``kind``; the project attribution is identical either way.
            await record_run_lineage(
                conn,
                run_id=UUID(str(run_id)),
                workspace_id=durable.workspace_id,
                kind="committee",
                project_id=durable.project_id,
                project_run_id=UUID(str(durable.project_run_id)),
            )
            committee = await self._discover_committee_members(
                conn,
                account_entity_id=EntityId(request.target_entity_id),
                run_id=run_id,
                workspace_id=durable.workspace_id,
                selected=selected,
                budget_cap_cents=durable.money_budget_cap_cents,
            )
        operation = self._committee_descriptor(
            acquired.operation,
            disposition=(
                ProviderObservationDisposition.CAUSED
                if caused
                else ProviderObservationDisposition.REPLAY
            ),
            include_dispatch=True,
        )
        snapshot_ref, subjects = await self._persist_committee_projection(
            request=request,
            operation=acquired.operation,
            provider_operation=operation,
            committee=committee,
            excluded=excluded,
            ambiguous=ambiguous,
        )
        return (
            ExternalResearchProjectionDraft(
                operation=operation,
                snapshot_ref=snapshot_ref,
                discovered_subjects=subjects,
                confirmed_empty_discovery=not subjects,
            ),
        )

    async def _discover_committee_members(
        self,
        conn: AsyncConnection,
        *,
        account_entity_id: EntityId,
        run_id: RunId,
        workspace_id: str,
        selected: Sequence[CommitteePersonCandidate],
        budget_cap_cents: Decimal | None,
    ) -> CommitteeResult:
        """Discover + identity-resolve the office-admitted buying unit, WITHOUT judging roles.

        Contract §5.2 steps 1-2: this provider action's job is discovery and identity — who is
        really in the declared buying unit, with provider evidence behind them. The committee *role*
        is a judgment the responsible account agent makes, on the evidence, and writes back through
        its own governed tool. So discovery runs in ``agent_deferred`` mode: it makes no gateway
        call and writes no role/persona claim, and the admitted members come back roleless (visible
        as discovered subjects with their People facts). Between this and the agent's role write,
        a committee legitimately has members and no roles — that is honest, not incomplete."""
        return await discover_committee(
            conn,
            account_entity_id=account_entity_id,
            run_id=run_id,
            workspace_id=workspace_id,
            sources=(_PreparedCommitteeSource(selected),),
            gateway=self._gateway,
            role_model=self._role_model,
            source_plan=(PEOPLE_SOURCE_KEY,),
            budget_cap_cents=budget_cap_cents,
            role_inference="agent_deferred",
        )

    async def _resolve_inputs(
        self,
    ) -> tuple[SumbleCommitteePreflight, ResearchCommitteePlan | None]:
        if self._inputs is None:
            assert self._preflight is not None
            # Static construction remains a deterministic R5 test/historical seam. Production
            # uses the resolver path below so no eligibility decision or provider preparation can
            # occur before the responsible agent's committee tool call.  It carries no durable
            # committee plan, so it cannot bound the agent's declared target functions.
            return self._preflight, None
        prepared = await self._inputs.resolve()
        assert self._eligibility is not None
        decision = await self._eligibility.evaluate(
            prepared.preflight.request,
            authorization=prepared.authorization,
            proposed_cost_cents=prepared.preflight.maximum_cost_cents,
        )
        if decision.outcome not in {
            CommitteeEligibilityOutcome.ELIGIBLE,
            CommitteeEligibilityOutcome.REUSABLE,
        }:
            reasons = ",".join(
                reason for condition in decision.conditions for reason in condition.reason_codes
            )
            raise EntityResearchGovernedRejection(
                "committee_eligibility_rejected",
                "Sumble committee eligibility rejected before provider dispatch: " + reasons,
            )
        # REUSABLE is still valid execution authority: the durable coordinator performs an
        # exact-fingerprint replay and returns before claiming a provider dispatch. Rejecting it
        # here would turn the required zero-spend replay path into an agent-visible failure.
        return prepared.preflight, prepared.committee_plan

    @staticmethod
    def _validate_scope_against_plan(
        scope: AccountBuyingUnitScope, *, plan: ResearchCommitteePlan | None
    ) -> None:
        """The agent may narrow the confirmed committee functions; it may never invent one.

        Matching is exact and case-insensitive: a plan function is a confirmed selector, not a
        substring to be widened into a neighbouring function.
        """

        if plan is None or not plan.functions:
            return
        allowed = {str(value).casefold(): str(value) for value in plan.functions}
        offending = tuple(
            value for value in scope.target_functions if value.casefold() not in allowed
        )
        if offending:
            # An invented function is a repairable model mistake: refuse it back to the agent
            # (R10 partial-failure policy) rather than suspending the whole account job.
            raise EntityResearchGovernedRejection(
                "committee_scope_outside_plan",
                "buying-unit scope targets functions outside the confirmed committee plan: "
                f"{', '.join(offending)}; the plan allows: {', '.join(allowed.values())}",
            )

    @staticmethod
    def _wait_disposition(*, caused: bool) -> ProviderObservationDisposition:
        return (
            ProviderObservationDisposition.CAUSED
            if caused
            else ProviderObservationDisposition.JOINED
        )

    async def _persist_scope(
        self,
        *,
        request: GovernedResearchToolRequest,
        scope: AccountBuyingUnitScope,
        workspace_id: str,
    ) -> None:
        if not all(
            ref.startswith(("research-evidence:", "claim:", "research-result:"))
            for ref in scope.evidence_refs
        ):
            raise EntityResearchResultIntegrityError(
                "buying-unit scope requires durable account evidence references"
            )
        async with self._conn_factory() as conn:
            # Result/evidence references are scoped by their owning exact job. Claim references are
            # allowed only when the claim belongs to the account itself.
            for ref in scope.evidence_refs:
                if ref.startswith("research-result:"):
                    found = await conn.execute(
                        text(
                            "SELECT 1 FROM entity_research_result result JOIN "
                            "entity_research_tool_request request_row ON "
                            "request_row.tool_request_id=result.tool_request_id "
                            "WHERE result.result_id=:id AND request_row.job_id=:job_id"
                        ),
                        {
                            "id": UUID(ref.removeprefix("research-result:")),
                            "job_id": request.job_id,
                        },
                    )
                elif ref.startswith("research-evidence:"):
                    found = await conn.execute(
                        text(
                            "SELECT 1 FROM entity_research_result_evidence evidence JOIN "
                            "entity_research_result result ON result.result_id=evidence.result_id "
                            "JOIN entity_research_tool_request request_row ON "
                            "request_row.tool_request_id=result.tool_request_id "
                            "WHERE evidence.evidence_id=:id AND request_row.job_id=:job_id"
                        ),
                        {
                            "id": UUID(ref.removeprefix("research-evidence:")),
                            "job_id": request.job_id,
                        },
                    )
                else:
                    found = await conn.execute(
                        text("SELECT 1 FROM claim WHERE id=:id AND entity_id=:account_id"),
                        {
                            "id": UUID(ref.removeprefix("claim:")),
                            "account_id": request.target_entity_id,
                        },
                    )
                if found.scalar_one_or_none() is None:
                    raise EntityResearchResultIntegrityError(
                        "buying-unit scope cites evidence outside the exact account job"
                    )
            values = {
                "scope_id": scope.scope_id,
                "tool_request_id": request.tool_call_id,
                "run_id": request.research_run_id,
                "job_id": request.job_id,
                "workspace_id": workspace_id,
                "account_id": request.target_entity_id,
                "scope_json": serialize_value_json(scope.model_dump(mode="json")),
                "scope_sha": hashlib.sha256(
                    json.dumps(
                        scope.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            }
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_committee_scope
                        (scope_id, tool_request_id, research_run_id, job_id, workspace_id,
                         account_entity_id, scope_json, scope_sha256)
                    VALUES (:scope_id, :tool_request_id, :run_id, :job_id, :workspace_id,
                            :account_id, CAST(:scope_json AS jsonb), :scope_sha)
                    ON CONFLICT DO NOTHING
                    """
                ),
                values,
            )
            stored = tuple(
                (
                    await conn.execute(
                        text(
                            "SELECT scope_id, tool_request_id, research_run_id, job_id, "
                            "workspace_id, account_entity_id, scope_sha256 FROM "
                            "entity_research_account_committee_scope "
                            "WHERE scope_id=:scope_id OR tool_request_id=:tool_request_id "
                            "ORDER BY created_at, scope_id"
                        ),
                        {
                            "scope_id": scope.scope_id,
                            "tool_request_id": request.tool_call_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            if (
                len(stored) != 1
                or stored[0]["scope_id"] != scope.scope_id
                or stored[0]["research_run_id"] != request.research_run_id
                or stored[0]["job_id"] != request.job_id
                or str(stored[0]["workspace_id"]) != workspace_id
                or stored[0]["account_entity_id"] != request.target_entity_id
                or str(stored[0]["scope_sha256"]) != values["scope_sha"]
            ):
                raise EntityResearchResultIntegrityError("buying-unit scope replay changed")

    @staticmethod
    def _office_candidates(
        candidates: Sequence[CommitteePersonCandidate], *, scope: AccountBuyingUnitScope
    ) -> tuple[tuple[CommitteePersonCandidate, ...], int, int]:
        selected: list[CommitteePersonCandidate] = []
        excluded = ambiguous = 0
        for candidate in candidates:
            people_facts = tuple(
                fact
                for fact in candidate.professional_facts
                if fact.source_key == PEOPLE_SOURCE_KEY
            )
            facts_by_field: dict[str, list[object]] = {}
            for fact in candidate.professional_facts:
                facts_by_field.setdefault(str(fact.field_key), []).append(fact.value_json)
            # Every discriminator matches provider-returned *values* only. Serializing whole fact
            # objects let a scope term collide with structural JSON keys ("relationship",
            # "current_employee", "teams"), which is a match against our own schema, not against
            # evidence.
            location_haystack = _match_haystack(
                candidate.geo,
                facts_by_field.get(str(CURRENT_LOCATION), ()),
            )
            business_unit_haystack = _match_haystack(
                candidate.team_names,
                facts_by_field.get(str(TEAM_MEMBERSHIP), ()),
                # A buying unit may be the exact organization itself (common for a small
                # practice) rather than a provider-modeled sub-team.  Sumble's returned
                # current-employer organization *name* is a strong, inspectable organization
                # binding and may satisfy that organization-wide unit.  A title, free-text
                # location, or inferred employer never participates in this discriminator.
                _organization_names(facts_by_field.get(str(ORGANIZATION_RELATIONSHIP), ())),
            )
            function_haystack = _match_haystack(
                candidate.job_function,
                facts_by_field.get(str(JOB_FUNCTION), ()),
                # A title is an allowed fallback only inside the function dimension; it can
                # never satisfy an office, facility, or business-unit discriminator.
                candidate.title,
            )
            location_match = _location_scope_match(scope, haystack=location_haystack)
            business_unit_match = (
                scope.business_unit is None
                or scope.business_unit.casefold() in business_unit_haystack
            )
            function_match = any(
                value.casefold() in function_haystack for value in scope.target_functions
            )
            if not people_facts:
                ambiguous += 1
            elif location_match and business_unit_match and function_match:
                selected.append(candidate)
            elif not location_match or not business_unit_match:
                ambiguous += 1
            else:
                excluded += 1
        return tuple(selected), excluded, ambiguous

    def _committee_descriptor(
        self,
        operation: object,
        *,
        disposition: ProviderObservationDisposition,
        include_dispatch: bool,
    ) -> ProviderOperationReservation:
        typed = cast("CommitteeAcquisitionOperation", operation)
        created = typed.created_at or datetime.now(UTC)
        return ProviderOperationReservation(
            provider_kind=self.provider_kind,
            operation_ref=f"committee-operation:{typed.operation_id}",
            workspace_id=typed.request.workspace_id,
            project_id=typed.request.project_id,
            project_run_id=UUID(str(typed.request.project_run_id)),
            subject_type=ResearchSubjectType.ACCOUNT,
            target_entity_id=UUID(str(typed.request.account_id)),
            source_key=PEOPLE_SOURCE_KEY,
            field_keys=(),
            request_artifact_ref=f"artifact:{typed.input_artifact_key}",
            reserved_at=created,
            dispatched_at=typed.started_at if include_dispatch else None,
            observation_disposition=disposition,
        )

    async def _persist_committee_projection(
        self,
        *,
        request: GovernedResearchToolRequest,
        operation: object,
        provider_operation: ProviderOperationReservation,
        committee: object,
        excluded: int,
        ambiguous: int,
    ) -> tuple[str, tuple[ResearchDiscoveredSubjectProjection, ...]]:
        typed = cast("CommitteeAcquisitionOperation", operation)
        result = cast("CommitteeResult", committee)
        async with self._conn_factory() as conn:
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=typed.request.workspace_id,
                operation_id=typed.operation_id,
            )
            people_snapshot = next(
                item for item in snapshots if item.source_key == PEOPLE_SOURCE_KEY
            )
            if people_snapshot.response_artifact_key is None:
                raise EntityResearchResultIntegrityError("People committee snapshot lacks evidence")
            snapshot_ref = (
                f"committee-snapshot:{typed.operation_id}:{PEOPLE_SOURCE_KEY}:"
                f"{people_snapshot.request_fingerprint}"
            )
            subjects: list[ResearchDiscoveredSubjectProjection] = []
            for member in result.members:
                candidate_claim_ids = [UUID(str(value)) for value in member.professional_claim_ids]
                if candidate_claim_ids:
                    rows = (
                        (
                            await conn.execute(
                                text(
                                    """
                                    SELECT id, field_key, value_json, source_key, source_url,
                                           artifact_key, evidence_span, confidence,
                                           verification_status::text
                                    FROM claim WHERE id=ANY(:claim_ids)
                                      AND source_key=:source_key
                                      AND source_operation_ref=:operation_ref
                                      AND source_snapshot_ref=:snapshot_ref
                                    ORDER BY collected_at, id
                                    """
                                ),
                                {
                                    "claim_ids": candidate_claim_ids,
                                    "source_key": PEOPLE_SOURCE_KEY,
                                    "operation_ref": f"committee-operation:{typed.operation_id}",
                                    "snapshot_ref": snapshot_ref,
                                },
                            )
                        )
                        .mappings()
                        .all()
                    )
                else:
                    rows = ()
                if not rows:
                    raise EntityResearchResultIntegrityError(
                        "office-admitted committee member lacks direct People facts"
                    )
                fields = tuple(
                    ResearchFieldResultProjection(
                        field_key=str(row["field_key"]),
                        outcome=ResearchFieldOutcome.FOUND,
                        value=decode_jsonb_scalar(row["value_json"]),
                        claim_delta=ResearchClaimDelta.ACCEPTED,
                        claim_refs=(f"claim:{row['id']}",),
                        evidence=(
                            ResearchEvidenceProjection(
                                evidence_ref=self._committee_evidence_ref(
                                    typed.operation_id, row["id"]
                                ),
                                source_key=PEOPLE_SOURCE_KEY,
                                provider_source_id=(
                                    people_snapshot.provider_operation_id or str(typed.operation_id)
                                ),
                                source_url=(str(row["source_url"]) if row["source_url"] else None),
                                artifact_ref=f"artifact:{row['artifact_key']}",
                                evidence_span=str(row["evidence_span"]),
                            ),
                        ),
                        confidence=float(cast(Decimal, row["confidence"])),
                        verification_status=str(row["verification_status"]),
                    )
                    for row in rows
                )
                subjects.append(
                    ResearchDiscoveredSubjectProjection(
                        subject_type=ResearchSubjectType.CONTACT,
                        target_entity_id=UUID(str(member.contact_entity_id)),
                        parent_account_id=request.target_entity_id,
                        strong_identity_claim_refs=(f"claim:{member.discovery_claim_id}",),
                        association_evidence_refs=(f"claim:{member.discovery_claim_id}",),
                        fields=fields,
                    )
                )
            raw_refs = [
                f"artifact:{item.response_artifact_key}"
                for item in snapshots
                if item.response_artifact_key is not None
            ]
            payload = {
                "contract": "m8d-r5-sumble-office-committee-v1",
                "operation_id": str(typed.operation_id),
                "coverage": result.coverage.model_dump(mode="json"),
                "members": [item.model_dump(mode="json") for item in subjects],
                "excluded_candidate_count": excluded,
                "ambiguous_candidate_count": ambiguous,
            }
            normalized_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=typed.request.workspace_id,
                content=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
                media_type="application/json",
                source_key=PEOPLE_SOURCE_KEY,
            )
            await bind_discovery_artifact_subject(
                conn,
                workspace_id=typed.request.workspace_id,
                artifact_key_value=normalized_key,
                subject_kind="account",
                subject_entity_id=typed.request.account_id,
                reference_kind="entity_research_sumble_committee_normalized",
                reference_id=provider_operation.operation_ref,
            )
            if not raw_refs or typed.receipt_manifest_key is None:
                raise EntityResearchResultIntegrityError(
                    "settled committee operation lacks raw responses or receipt"
                )
            values = {
                "operation_ref": provider_operation.operation_ref,
                "workspace_id": typed.request.workspace_id,
                "snapshot_ref": snapshot_ref,
                "normalized_key": normalized_key,
                "raw_refs": raw_refs,
                "receipt_ref": f"artifact:{typed.receipt_manifest_key}",
                "settlement_ref": f"sumble-committee-settlement:{typed.operation_id}",
                "provider_request_id": (
                    people_snapshot.provider_operation_id or str(typed.operation_id)
                ),
                "reported_cost": typed.cost_cents_charged,
                "settled_cost": typed.cost_cents_charged,
                "metadata": serialize_value_json(
                    {
                        "excluded_candidate_count": excluded,
                        "ambiguous_candidate_count": ambiguous,
                    }
                ),
            }
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_sumble_projection
                        (provider_operation_ref, workspace_id, provider_snapshot_ref,
                         normalized_result_artifact_key, raw_response_artifact_refs,
                         retained_result_artifact_refs, provider_receipt_ref,
                         cost_settlement_ref, provider_request_id,
                         provider_reported_cost_cents, settled_cost_cents, metadata_json)
                    VALUES (:operation_ref, :workspace_id, :snapshot_ref, :normalized_key,
                            :raw_refs, :raw_refs, :receipt_ref, :settlement_ref,
                            :provider_request_id, :reported_cost, :settled_cost,
                            CAST(:metadata AS jsonb))
                    ON CONFLICT (provider_operation_ref) DO NOTHING
                    """
                ),
                values,
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT provider_snapshot_ref, normalized_result_artifact_key, "
                            "raw_response_artifact_refs, provider_receipt_ref, "
                            "cost_settlement_ref, provider_request_id, "
                            "provider_reported_cost_cents, settled_cost_cents, metadata_json "
                            "FROM entity_research_sumble_projection "
                            "WHERE provider_operation_ref=:operation_ref"
                        ),
                        {"operation_ref": provider_operation.operation_ref},
                    )
                )
                .mappings()
                .one()
            )
            if (
                str(stored["provider_snapshot_ref"]) != snapshot_ref
                or str(stored["normalized_result_artifact_key"]) != normalized_key
                or tuple(str(value) for value in stored["raw_response_artifact_refs"])
                != tuple(raw_refs)
                or str(stored["provider_receipt_ref"]) != values["receipt_ref"]
                or str(stored["cost_settlement_ref"]) != values["settlement_ref"]
                or str(stored["provider_request_id"]) != values["provider_request_id"]
                or Decimal(str(stored["provider_reported_cost_cents"]))
                != Decimal(str(values["reported_cost"]))
                or Decimal(str(stored["settled_cost_cents"]))
                != Decimal(str(values["settled_cost"]))
                or serialize_value_json(stored["metadata_json"]) != values["metadata"]
            ):
                raise EntityResearchResultIntegrityError(
                    "Sumble committee projection replay changed"
                )
        return snapshot_ref, tuple(subjects)

    @staticmethod
    def _committee_evidence_ref(operation_id: object, claim_id: object) -> str:
        identity = uuid5(_EVIDENCE_NAMESPACE, f"{operation_id}:{claim_id}")
        return f"research-evidence:{identity}"


__all__ = [
    "SumbleAccountSemanticEnrichmentAction",
    "SumbleCommitteeSemanticResearchAction",
    "SumbleEntityResearchLineageReader",
]
