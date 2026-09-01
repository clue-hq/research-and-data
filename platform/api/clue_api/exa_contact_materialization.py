"""Verified Exa contact snapshots through the governed contact-field path (M8C C4)."""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.contact_snapshot_resolver import GroundedContactSnapshotResolver
from clue_api.exa_contact_compiler import ExaDeepContactAcquisitionPreflight
from clue_core import (
    AccountEntity,
    ClaimId,
    ContactEntity,
    ContactResearchIntent,
    ContactResearchPolicyPin,
    EffectiveFieldSourcePlan,
    EntityId,
    ExternalResearchAcquisitionRequest,
    ExternalResearchSnapshotRef,
    ExternalResearchSubjectKind,
    FieldClass,
    FieldKey,
    PreSpendGate,
    Resolver,
    RunId,
    classify_field_key,
)
from clue_research.claimstore import (
    FieldRegistryScope,
    get_effective_field,
    record_run_lineage,
)
from clue_research.directives import effective_account_research_directive
from clue_research.durable import (
    list_external_research_result_artifacts,
    list_ready_external_research_snapshots,
)
from clue_research.icp import get_icp_version
from clue_research.identity import get_account, get_contact, surviving_id
from clue_research.profiling.contact import fill_contact_field
from clue_research.resolvers import SynthesizedField
from clue_research.resolvers.exa import (
    SOURCE_KEY,
    ExaDeepConfig,
    ExaDeepContactNormalization,
    ExaDeepContactSearchRequest,
    ExaDeepContactTargetLock,
    normalize_exa_contact_deep_snapshot,
    parse_exa_deep_response,
)
from clue_research.resolvers.exa.deep_contract import ExaDeepResult
from clue_research.sources import bind_resolver_overrides
from clue_storage import ArtifactIntegrityError, StorageBackend, read_verified_artifact


class ExaDeepContactSnapshotError(RuntimeError):
    """A ready contact snapshot cannot be proven safe for offline materialization."""


class ExaDeepContactMaterializedField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    claim_refs: tuple[ClaimId, ...] = ()
    stop_reason: str


class ExaDeepContactMaterializationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    snapshot_reference_ids: tuple[str, ...]
    operation_reference_ids: tuple[str, ...]
    fields: tuple[ExaDeepContactMaterializedField, ...]


@dataclass(frozen=True)
class ExaDeepContactResolverBundle:
    resolver: Resolver
    source_plans: Mapping[str, EffectiveFieldSourcePlan]
    snapshot_reference_ids: tuple[str, ...]
    operation_reference_ids: tuple[str, ...]


async def _verified_json(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    key: str,
    workspace_id: str,
) -> bytes:
    try:
        return (
            await read_verified_artifact(
                conn,
                storage,
                storage_key=key,
                workspace_id=workspace_id,
            )
        )[1]
    except ArtifactIntegrityError as exc:
        raise ExaDeepContactSnapshotError(str(exc)) from exc


def _request_properties(request: ExaDeepContactSearchRequest) -> frozenset[str]:
    try:
        table = request.field_key_by_alias
    except ValueError as exc:
        raise ExaDeepContactSnapshotError(
            "stored contact request has no structured field map"
        ) from exc
    return frozenset(str(field_key) for field_key in table.values())


async def _build_exa_contact_snapshot_resolver(
    *,
    intent: ContactResearchIntent,
    snapshots: Sequence[ExternalResearchSnapshotRef],
    allowed_field_keys: Collection[str],
    storage: StorageBackend,
    conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]],
) -> ExaDeepContactResolverBundle:
    if not snapshots:
        raise ExaDeepContactSnapshotError("contact materialization requires a ready Exa snapshot")
    allowed = frozenset(allowed_field_keys)
    if not allowed:
        raise ExaDeepContactSnapshotError("contact materialization requires admitted facet fields")

    fields: list[SynthesizedField] = []
    source_plans: dict[str, EffectiveFieldSourcePlan] = {}
    shadowed: set[str] = set()
    seen_snapshots: set[str] = set()
    snapshot_refs: list[str] = []
    operation_refs: list[str] = []
    observed_at = datetime.now(UTC)

    for snapshot in snapshots:
        if (
            snapshot.source_key != SOURCE_KEY
            or snapshot.subject_kind is not ExternalResearchSubjectKind.CONTACT
            or snapshot.account_id != intent.account_entity_id
            or snapshot.contact_id != intent.contact_entity_id
            or snapshot.workspace_id != intent.workspace_id
        ):
            raise ExaDeepContactSnapshotError("snapshot crosses its exact contact/account scope")
        if snapshot.fresh_until <= observed_at:
            raise ExaDeepContactSnapshotError("contact snapshot expired before materialization")
        snapshot_ref = str(snapshot.snapshot_id)
        if snapshot_ref in seen_snapshots:
            raise ExaDeepContactSnapshotError("the same contact snapshot was supplied twice")
        seen_snapshots.add(snapshot_ref)

        try:
            async with conn_factory() as conn:
                response_payload = json.loads(
                    await _verified_json(
                        conn,
                        storage,
                        key=snapshot.response_artifact_key,
                        workspace_id=snapshot.workspace_id,
                    )
                )
                stored = ExaDeepContactNormalization.model_validate_json(
                    await _verified_json(
                        conn,
                        storage,
                        key=snapshot.normalization_artifact_key,
                        workspace_id=snapshot.workspace_id,
                    )
                )
                request_artifact = json.loads(
                    await _verified_json(
                        conn,
                        storage,
                        key=snapshot.request_artifact_key,
                        workspace_id=snapshot.workspace_id,
                    )
                )
                indexed_results = await list_external_research_result_artifacts(
                    conn,
                    workspace_id=snapshot.workspace_id,
                    snapshot_id=snapshot.snapshot_id,
                )
                verified_results = {
                    item.source_url: (
                        item,
                        ExaDeepResult.model_validate_json(
                            await _verified_json(
                                conn,
                                storage,
                                key=item.artifact_key,
                                workspace_id=snapshot.workspace_id,
                            )
                        ),
                    )
                    for item in indexed_results
                }
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ExaDeepContactSnapshotError(
                "stored contact Exa snapshot JSON is malformed"
            ) from exc

        if not isinstance(request_artifact, dict):
            raise ExaDeepContactSnapshotError("stored contact request artifact is not an object")
        if request_artifact.get("contract") != "exa-search-contact-deep-acquisition-c4-request-v1":
            raise ExaDeepContactSnapshotError(
                "stored contact request contract is absent or unknown"
            )
        if request_artifact.get("contact_intent_sha256") != intent.sha256():
            raise ExaDeepContactSnapshotError("stored contact request belongs to another intent")
        if (
            request_artifact.get("contact_selection_id") != str(intent.selection_id)
            or request_artifact.get("contact_selection_sha256") != intent.selection_sha256
        ):
            raise ExaDeepContactSnapshotError(
                "stored contact request belongs to another selected-contact authority"
            )
        try:
            durable_request = ExternalResearchAcquisitionRequest.model_validate(
                request_artifact["lineage"]
            )
            request = ExaDeepContactSearchRequest.model_validate(request_artifact["wire_request"])
            target = ExaDeepContactTargetLock.model_validate(
                request_artifact["contact_target_lock"]
            )
            plans = tuple(
                EffectiveFieldSourcePlan.model_validate(value)
                for value in request_artifact["field_source_plans"]
            )
            config = ExaDeepConfig.model_validate(request_artifact["exa_config"])
            ExaDeepContactAcquisitionPreflight(
                request=durable_request,
                selection_id=intent.selection_id,
                selection_sha256=intent.selection_sha256,
                intent_sha256=intent.sha256(),
                exa_request=request,
                target_lock=target,
                field_source_plans=plans,
                exa_config=config,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExaDeepContactSnapshotError(
                "stored contact request cannot reconstruct its accepted C3 preflight"
            ) from exc
        try:
            if not isinstance(response_payload, dict):
                raise TypeError("stored Exa contact response artifact is not an object")
            response = parse_exa_deep_response(request, response_payload)
        except (TypeError, ValueError) as exc:
            raise ExaDeepContactSnapshotError(
                "stored contact Exa snapshot JSON is malformed"
            ) from exc
        if (
            durable_request.request_fingerprint != snapshot.request_fingerprint
            or durable_request.workspace_id != snapshot.workspace_id
            or durable_request.account_id != snapshot.account_id
            or durable_request.contact_id != snapshot.contact_id
        ):
            raise ExaDeepContactSnapshotError("snapshot differs from its immutable request lineage")

        requested = _request_properties(request)
        unauthorized = requested - allowed
        if unauthorized:
            raise ExaDeepContactSnapshotError(
                "contact snapshot requested fields outside the selected intent: "
                f"{sorted(unauthorized)!r}"
            )
        recomputed = normalize_exa_contact_deep_snapshot(
            request,
            response,
            target=target,
            config=config,
        )
        if recomputed != stored:
            raise ExaDeepContactSnapshotError(
                "stored contact normalization differs from exact-target recomputation"
            )
        if response.request_id != snapshot.provider_request_id:
            raise ExaDeepContactSnapshotError(
                "contact snapshot provider request id is inconsistent"
            )
        if recomputed.synthesis.cost_cents != snapshot.provider_reported_cost_cents:
            raise ExaDeepContactSnapshotError("contact snapshot provider cost is inconsistent")
        if recomputed.all_null != snapshot.all_null:
            raise ExaDeepContactSnapshotError(
                "contact snapshot all-null disposition is inconsistent"
            )

        response_by_url = {str(item.url): item for item in response.results}
        if len(verified_results) != len(indexed_results):
            raise ExaDeepContactSnapshotError("contact result artifact URLs are not unique")
        if set(verified_results) != set(response_by_url):
            raise ExaDeepContactSnapshotError(
                "contact result index differs from the retained provider response"
            )
        artifact_by_url: dict[str, str] = {}
        for source_url, (indexed, persisted) in verified_results.items():
            if (
                persisted != response_by_url[source_url]
                or indexed.source_url != str(persisted.url)
                or indexed.source_title != persisted.title
            ):
                raise ExaDeepContactSnapshotError(
                    "contact result artifact differs from its response or relational index"
                )
            artifact_by_url[source_url] = indexed.artifact_key

        plan_by_field = {str(plan.field_key): plan for plan in plans}
        if set(plan_by_field) != set(requested):
            raise ExaDeepContactSnapshotError(
                "contact request fields differ from source-plan authority"
            )
        active = requested - shadowed
        for field_key in active:
            source_plans[field_key] = plan_by_field[field_key]
        for field in recomputed.synthesis.fields:
            key = str(field.field_key)
            if key not in requested:
                raise ExaDeepContactSnapshotError(
                    "normalized contact field was absent from request"
                )
            if key not in active:
                continue
            evidence_artifact = artifact_by_url.get(field.source_url)
            if evidence_artifact is None:
                raise ExaDeepContactSnapshotError(
                    "grounded contact field has no immutable result artifact"
                )
            fields.append(
                SynthesizedField.model_validate(
                    field.model_copy(
                        update={
                            "artifact_key": evidence_artifact,
                            "source_operation_ref": str(snapshot.operation_id),
                            "source_snapshot_ref": snapshot_ref,
                            "source_request_ref": snapshot.provider_request_id,
                        }
                    ).model_dump(mode="python")
                )
            )
        shadowed.update(requested)
        snapshot_refs.append(snapshot_ref)
        operation_refs.append(str(snapshot.operation_id))

    if shadowed != allowed:
        missing = sorted(allowed - shadowed)
        raise ExaDeepContactSnapshotError(
            f"ready contact snapshots do not cover every selected facet field: {missing!r}"
        )
    return ExaDeepContactResolverBundle(
        resolver=GroundedContactSnapshotResolver(
            contact_entity_id=intent.contact_entity_id,
            fields=fields,
        ),
        source_plans=source_plans,
        snapshot_reference_ids=tuple(snapshot_refs),
        operation_reference_ids=tuple(operation_refs),
    )


async def _require_current_subject(
    conn: AsyncConnection,
    *,
    intent: ContactResearchIntent,
) -> tuple[AccountEntity, ContactEntity]:
    account = await get_account(conn, intent.account_entity_id)
    contact = await get_contact(conn, intent.contact_entity_id)
    if (
        account is None
        or account.workspace_id != intent.workspace_id
        or await surviving_id(conn, account.id, account.as_entity().entity_type) != account.id
    ):
        raise ExaDeepContactSnapshotError("contact employer is absent, foreign, or non-canonical")
    if (
        contact is None
        or contact.workspace_id != intent.workspace_id
        or contact.account_entity_id != account.id
        or await surviving_id(conn, contact.id, contact.as_entity().entity_type) != contact.id
    ):
        raise ExaDeepContactSnapshotError("contact is absent, foreign, merged, or cross-account")
    return account, contact


class ExaDeepContactSnapshotResolverProvider:
    """Resolve one selected contact only from adopted, fresh, immutable Exa snapshots."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]],
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    async def resolver_bundle(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: ContactResearchPolicyPin,
        allowed_field_keys: Collection[str] | None = None,
        snapshot_reference_ids: Collection[str] | None = None,
    ) -> ExaDeepContactResolverBundle:
        intent.selection.require_effective_policy(effective_policy)
        if SOURCE_KEY not in intent.source_plan:
            raise ExaDeepContactSnapshotError("selected contact intent does not authorize Exa")
        selected_facet_fields = frozenset(
            str(field_key)
            for field_key in intent.field_keys
            if classify_field_key(field_key) is FieldClass.CONTACT_FACET
        )
        facet_fields = (
            selected_facet_fields if allowed_field_keys is None else frozenset(allowed_field_keys)
        )
        if not facet_fields.issubset(selected_facet_fields):
            raise ExaDeepContactSnapshotError(
                "contact materialization fields widen the selected intent"
            )
        if not facet_fields:
            raise ExaDeepContactSnapshotError("selected contact intent has no Exa facet fields")
        async with self._conn_factory() as conn:
            await _require_current_subject(conn, intent=intent)
            effective = await effective_account_research_directive(
                conn,
                workspace_id=intent.workspace_id,
                directive_id=intent.research_directive.directive_id,
                account_id=intent.account_entity_id,
                expected_pin=intent.research_directive,
            )
            if (
                not effective.privacy_policy.contact_profiling_allowed
                or SOURCE_KEY not in effective.source_policy.allowed_source_keys
            ):
                raise ExaDeepContactSnapshotError(
                    "current confirmed directive does not authorize Exa contact research"
                )
            snapshots = await list_ready_external_research_snapshots(
                conn,
                workspace_id=intent.workspace_id,
                project_run_id=intent.project_run_id,
                subject_kind=ExternalResearchSubjectKind.CONTACT,
                account_id=intent.account_entity_id,
                contact_id=intent.contact_entity_id,
                source_key=SOURCE_KEY,
                research_directive_id=intent.research_directive.directive_id,
                research_directive_version=intent.research_directive.version,
                research_directive_sha256=intent.research_directive.canonical_json_sha256,
                research_override_id=intent.research_directive.override_id,
                research_override_sha256=intent.research_directive.override_sha256,
                contact_selection_id=intent.selection_id,
                contact_selection_sha256=intent.selection_sha256,
                contact_intent_sha256=intent.sha256(),
            )
        if snapshot_reference_ids is not None:
            wanted = frozenset(snapshot_reference_ids)
            snapshots = tuple(
                snapshot for snapshot in snapshots if str(snapshot.snapshot_id) in wanted
            )
            if {str(snapshot.snapshot_id) for snapshot in snapshots} != wanted:
                raise ExaDeepContactSnapshotError(
                    "contact materialization named an absent ready snapshot"
                )
        return await _build_exa_contact_snapshot_resolver(
            intent=intent,
            snapshots=snapshots,
            allowed_field_keys=facet_fields,
            storage=self._storage,
            conn_factory=self._conn_factory,
        )


class ExaDeepContactSnapshotMaterializer:
    """Materialize exact-bound snapshot fields through ``fill_contact_field`` only."""

    def __init__(
        self,
        *,
        provider: ExaDeepContactSnapshotResolverProvider,
        conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]],
    ) -> None:
        self._provider = provider
        self._conn_factory = conn_factory

    async def materialize(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: ContactResearchPolicyPin,
        run_id: RunId,
        pre_spend_gate: PreSpendGate | None = None,
        field_keys: Collection[str] | None = None,
        snapshot_reference_ids: Collection[str] | None = None,
    ) -> ExaDeepContactMaterializationResult:
        selected_fields = (
            tuple(
                str(field_key)
                for field_key in intent.field_keys
                if classify_field_key(field_key) is FieldClass.CONTACT_FACET
            )
            if field_keys is None
            else tuple(field_keys)
        )
        bundle = await self._provider.resolver_bundle(
            intent=intent,
            effective_policy=effective_policy,
            allowed_field_keys=selected_fields,
            snapshot_reference_ids=snapshot_reference_ids,
        )
        results: list[ExaDeepContactMaterializedField] = []
        async with self._conn_factory() as conn:
            # FI-2 P2 (spec §3): the caller's ``run_id`` is a per-tool-call id derived from the
            # launch research run, and it is what every facet claim below carries — so it is the id
            # the project lens must resolve. Registered once here, in the same transaction as those
            # writes; idempotent, so a replayed tool call re-registers harmlessly.
            await record_run_lineage(
                conn,
                run_id=UUID(str(run_id)),
                workspace_id=intent.workspace_id,
                kind="contact_research",
                project_id=intent.project_id,
                project_run_id=UUID(str(intent.project_run_id)),
            )
            account, contact = await _require_current_subject(conn, intent=intent)
            effective = await effective_account_research_directive(
                conn,
                workspace_id=intent.workspace_id,
                directive_id=intent.research_directive.directive_id,
                account_id=intent.account_entity_id,
                expected_pin=intent.research_directive,
            )
            spec = await get_icp_version(
                conn,
                intent.workspace_id,
                effective.icp_key,
                effective.icp_version,
            )
            if spec is None:
                raise ExaDeepContactSnapshotError("contact snapshot ICP pin cannot be resolved")
            with bind_resolver_overrides({SOURCE_KEY: bundle.resolver}):
                for field_key in selected_fields:
                    if classify_field_key(field_key) is not FieldClass.CONTACT_FACET:
                        continue
                    stored_plan = bundle.source_plans.get(str(field_key))
                    if stored_plan is None:
                        raise ExaDeepContactSnapshotError(
                            f"contact snapshot lacks source authority for {field_key!r}"
                        )
                    definition = await get_effective_field(
                        conn,
                        scope=FieldRegistryScope.for_workspace(intent.workspace_id),
                        field_key=str(field_key),
                    )
                    if definition is None or not definition.active:
                        raise ExaDeepContactSnapshotError(
                            f"contact snapshot field {field_key!r} is no longer registered"
                        )
                    filled = await fill_contact_field(
                        conn,
                        contact,
                        account,
                        definition.field_def,
                        run_id=run_id,
                        workspace_id=intent.workspace_id,
                        tier=effective.effort_policy.tier,
                        spec=spec,
                        pre_spend_gate=pre_spend_gate,
                        planning_budget_envelope=effective.effort_policy.budget_cap_cents,
                        required_effective_source_plan=stored_plan,
                    )
                    results.append(
                        ExaDeepContactMaterializedField(
                            field_key=field_key,
                            claim_refs=tuple(filled.claim_refs),
                            stop_reason=filled.stop_reason,
                        )
                    )
        return ExaDeepContactMaterializationResult(
            contact_entity_id=intent.contact_entity_id,
            snapshot_reference_ids=bundle.snapshot_reference_ids,
            operation_reference_ids=bundle.operation_reference_ids,
            fields=tuple(results),
        )


__all__ = [
    "ExaDeepContactMaterializationResult",
    "ExaDeepContactMaterializedField",
    "ExaDeepContactResolverBundle",
    "ExaDeepContactSnapshotError",
    "ExaDeepContactSnapshotMaterializer",
    "ExaDeepContactSnapshotResolverProvider",
]
