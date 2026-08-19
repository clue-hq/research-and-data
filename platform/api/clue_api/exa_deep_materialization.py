"""Offline Exa Deep snapshot materialization behind the shared resolver seam (M8B E2)."""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_wiring import (
    AccountResolverBindingAvailability,
    AccountResolverBindings,
)
from clue_core import (
    AccountEntity,
    EntityId,
    ExternalResearchSnapshotRef,
    FieldDef,
    ProjectRunId,
    ResearchDirectivePin,
    Resolver,
    account_axis_field_keys,
)
from clue_research.directives import effective_account_research_directive
from clue_research.durable import (
    find_active_external_research_operation_for_materialization,
    list_external_research_result_artifacts,
    list_ready_external_research_snapshots,
)
from clue_research.identity import get_account
from clue_research.resolvers import GroundedSynthesisResolver, SynthesisResult, SynthesizedField
from clue_research.resolvers.exa import (
    SOURCE_KEY,
    ExaDeepNormalization,
    ExaDeepSearchRequest,
    normalize_exa_deep_snapshot,
    parse_exa_deep_response,
)
from clue_research.resolvers.exa.deep_contract import ExaDeepResult
from clue_storage import ArtifactIntegrityError, StorageBackend, read_verified_artifact


class ExaDeepSnapshotError(RuntimeError):
    """A ready snapshot cannot be proven safe for offline materialization."""


class _OneAccountLookup:
    def __init__(self, account: AccountEntity) -> None:
        self._account = account

    def key_for(self, entity_id: EntityId) -> AccountEntity | None:
        return self._account if entity_id == self._account.id else None


class _ReadySnapshotBackend:
    """In-memory, read-only synthesis backend; every byte is verified before construction."""

    materialization_only = True

    def __init__(self, *, account_id: EntityId, fields: Sequence[SynthesizedField]) -> None:
        self._account_id = account_id
        grouped: dict[str, list[SynthesizedField]] = {}
        for field in fields:
            grouped.setdefault(str(field.field_key), []).append(field)
        self._fields = {key: tuple(values) for key, values in grouped.items()}

    def synthesize(self, account: AccountEntity, field: FieldDef) -> SynthesisResult:
        if account.id != self._account_id:
            return SynthesisResult()
        return SynthesisResult(
            fields=self._fields.get(str(field.field_key), ()),
            cost_cents=Decimal(0),
        )


def _resolver(account: AccountEntity, fields: Sequence[SynthesizedField]) -> Resolver:
    return cast(
        Resolver,
        GroundedSynthesisResolver(
            _ReadySnapshotBackend(account_id=account.id, fields=fields),
            _OneAccountLookup(account),
            source_key=SOURCE_KEY,
            default_cost_cents=Decimal(0),
        ),
    )


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
        raise ExaDeepSnapshotError(str(exc)) from exc


async def _build_exa_deep_snapshot_resolver(
    *,
    account: AccountEntity,
    snapshots: Sequence[ExternalResearchSnapshotRef],
    allowed_field_keys: Collection[str],
    storage: StorageBackend,
    conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]],
) -> Resolver:
    """Build one account-scoped resolver from ready E1 snapshots, with no provider fallback."""

    if not snapshots:
        raise ExaDeepSnapshotError("Exa Deep materialization requires a ready snapshot")
    allowed = frozenset(allowed_field_keys)
    if not allowed:
        raise ExaDeepSnapshotError("Exa Deep materialization requires admitted directive fields")
    fields: list[SynthesizedField] = []
    seen_snapshot_ids: set[str] = set()
    shadowed_field_keys: set[str] = set()
    observed_at = datetime.now(UTC)
    for snapshot in snapshots:
        if snapshot.source_key != SOURCE_KEY:
            raise ExaDeepSnapshotError("snapshot source does not match Exa Deep")
        if snapshot.account_id != account.id or snapshot.workspace_id != account.workspace_id:
            raise ExaDeepSnapshotError("snapshot crosses its resolved account or workspace")
        if snapshot.fresh_until <= observed_at:
            raise ExaDeepSnapshotError("snapshot expired before materialization")
        snapshot_ref = str(snapshot.snapshot_id)
        if snapshot_ref in seen_snapshot_ids:
            raise ExaDeepSnapshotError("the same snapshot was supplied more than once")
        seen_snapshot_ids.add(snapshot_ref)

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
                stored_normalization = ExaDeepNormalization.model_validate_json(
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
                if not isinstance(request_artifact, dict):
                    raise TypeError("stored Exa request artifact is not an object")
                request_json = request_artifact.get("wire_request")
                if not isinstance(request_json, dict):
                    raise TypeError("stored Exa request lacks its immutable wire body")
                request = ExaDeepSearchRequest.model_validate(request_json)
                if not isinstance(response_payload, dict):
                    raise TypeError("stored Exa response artifact is not an object")
                response = parse_exa_deep_response(request, response_payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ExaDeepSnapshotError("stored Exa snapshot JSON is malformed") from exc
        requested_field_keys = frozenset(
            str(field_key) for field_key in request.field_key_by_alias.values()
        )
        unauthorized = requested_field_keys - allowed
        if unauthorized:
            raise ExaDeepSnapshotError(
                "snapshot requested fields outside the effective directive: "
                f"{sorted(unauthorized)!r}"
            )
        recomputed = normalize_exa_deep_snapshot(request, response)
        if recomputed != stored_normalization:
            raise ExaDeepSnapshotError("stored Exa normalization differs from recomputation")
        if response.request_id != snapshot.provider_request_id:
            raise ExaDeepSnapshotError("snapshot provider request id is inconsistent")
        if recomputed.synthesis.cost_cents != snapshot.provider_reported_cost_cents:
            raise ExaDeepSnapshotError("snapshot provider cost is inconsistent")
        if recomputed.all_null != snapshot.all_null:
            raise ExaDeepSnapshotError("snapshot all-null disposition is inconsistent")

        response_by_url = {str(item.url): item for item in response.results}
        if len(verified_results) != len(indexed_results):
            raise ExaDeepSnapshotError("snapshot result artifact URLs are not unique")
        if set(verified_results) != set(response_by_url):
            raise ExaDeepSnapshotError("result index differs from the retained provider response")
        artifact_by_url: dict[str, str] = {}
        for source_url, (indexed, persisted) in verified_results.items():
            if (
                persisted != response_by_url[source_url]
                or indexed.source_url != str(persisted.url)
                or indexed.source_title != persisted.title
            ):
                raise ExaDeepSnapshotError(
                    "result artifact differs from its response or relational index"
                )
            artifact_by_url[source_url] = indexed.artifact_key

        active_field_keys = requested_field_keys - shadowed_field_keys
        for field in recomputed.synthesis.fields:
            key = str(field.field_key)
            if key not in requested_field_keys:
                raise ExaDeepSnapshotError("normalized field was absent from its request")
            if key not in active_field_keys:
                continue
            artifact_key = artifact_by_url.get(field.source_url)
            if artifact_key is None:
                raise ExaDeepSnapshotError("grounded field has no immutable result artifact")
            fields.append(
                SynthesizedField.model_validate(
                    field.model_copy(
                        update={
                            "artifact_key": artifact_key,
                            "source_operation_ref": str(snapshot.operation_id),
                            "source_snapshot_ref": snapshot_ref,
                            "source_request_ref": snapshot.provider_request_id,
                        }
                    ).model_dump(mode="python")
                )
            )
        shadowed_field_keys.update(requested_field_keys)
    return _resolver(account, fields)


class ExaDeepSnapshotResolverProvider:
    """Create typed, account-scoped Exa bindings only from adopted ready snapshots."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]],
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    async def resolver_bindings(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        research_directive: ResearchDirectivePin | None,
    ) -> AccountResolverBindings:
        if research_directive is None:
            raise ExaDeepSnapshotError("materialization requires a confirmed directive pin")
        if research_directive.account_id != account_entity_id:
            raise ExaDeepSnapshotError("directive pin belongs to another account")
        async with self._conn_factory() as conn:
            account = await get_account(conn, account_entity_id)
            if account is None or account.workspace_id != workspace_id:
                raise ExaDeepSnapshotError("account is absent or belongs to another workspace")
            effective = await effective_account_research_directive(
                conn,
                workspace_id=workspace_id,
                directive_id=research_directive.directive_id,
                account_id=account_entity_id,
                expected_pin=research_directive,
            )
            if SOURCE_KEY not in set(effective.source_policy.allowed_source_keys):
                return AccountResolverBindings(
                    availability=AccountResolverBindingAvailability.NOT_APPLICABLE,
                    bindings={SOURCE_KEY: _resolver(account, ())},
                    reason_code="exa_deep_not_authorized_by_effective_directive",
                )
            snapshots = await list_ready_external_research_snapshots(
                conn,
                workspace_id=workspace_id,
                project_run_id=project_run_id,
                account_id=account_entity_id,
                source_key=SOURCE_KEY,
                research_directive_id=research_directive.directive_id,
                research_directive_version=research_directive.version,
                research_directive_sha256=research_directive.canonical_json_sha256,
                research_override_id=research_directive.override_id,
                research_override_sha256=research_directive.override_sha256,
            )
            active = None
            if not snapshots:
                active = await find_active_external_research_operation_for_materialization(
                    conn,
                    workspace_id=workspace_id,
                    project_run_id=project_run_id,
                    account_id=account_entity_id,
                    source_key=SOURCE_KEY,
                    research_directive_id=research_directive.directive_id,
                    research_directive_version=research_directive.version,
                    research_directive_sha256=research_directive.canonical_json_sha256,
                    research_override_id=research_directive.override_id,
                    research_override_sha256=research_directive.override_sha256,
                )
        if not snapshots:
            if active is not None:
                return AccountResolverBindings(
                    availability=AccountResolverBindingAvailability.WAITING_EXTERNAL,
                    bindings={},
                    reason_code="exa_deep_acquisition_in_progress",
                    operation_ref=str(active.operation_id),
                    retry_after=(
                        active.dispatch_lease_expires_at
                        if active.dispatch_lease_expires_at is not None
                        else datetime.now(UTC) + timedelta(seconds=30)
                    ),
                )
            return AccountResolverBindings(
                availability=AccountResolverBindingAvailability.REQUIRED_MISSING,
                bindings={},
                reason_code="exa_deep_snapshot_required_but_not_ready",
            )
        resolver = await _build_exa_deep_snapshot_resolver(
            account=account,
            snapshots=snapshots,
            allowed_field_keys=account_axis_field_keys(effective.field_keys),
            storage=self._storage,
            conn_factory=self._conn_factory,
        )
        return AccountResolverBindings(
            availability=AccountResolverBindingAvailability.READY,
            bindings={SOURCE_KEY: resolver},
            snapshot_refs=tuple(str(snapshot.snapshot_id) for snapshot in snapshots),
            audit_refs=tuple(str(snapshot.operation_id) for snapshot in snapshots),
        )


__all__ = ["ExaDeepSnapshotError", "ExaDeepSnapshotResolverProvider"]
