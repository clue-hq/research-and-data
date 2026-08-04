"""E2 offline Exa Deep snapshot materialization behind the shared resolver seam.

Acquisition and settlement are E1-owned.  This module accepts only ready immutable snapshot
references, revalidates their stored request/response/normalization exchange, attaches durable
operation/snapshot/request and result-artifact lineage to provider-neutral synthesized fields, and
returns an ordinary ``Resolver``.  Calling that resolver performs no storage, database, network,
credential, or spend operation.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from typing import cast

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.exa_deep_acquisition import load_exa_deep_snapshot
from clue_core import (
    AccountEntity,
    EntityId,
    ExternalResearchSnapshotRef,
    FieldDef,
    ProjectRunId,
    ResearchDirectivePin,
    Resolver,
)
from clue_research.directives import effective_account_research_directive
from clue_research.durable import (
    list_external_research_result_artifacts,
    list_ready_external_research_snapshots,
)
from clue_research.identity import get_account
from clue_research.resolvers import (
    GroundedSynthesisResolver,
    SynthesisResult,
    SynthesizedField,
)
from clue_research.resolvers.exa import (
    SOURCE_KEY,
    ExaDeepNormalization,
    ExaDeepSearchRequest,
    field_key_from_exa_alias,
    normalize_exa_deep_snapshot,
)
from clue_storage import StorageBackend


class ExaDeepSnapshotError(RuntimeError):
    """A ready snapshot cannot be proven safe for offline materialization."""


class _OneAccountLookup:
    def __init__(self, account: AccountEntity) -> None:
        self._account = account

    def key_for(self, entity_id: EntityId) -> AccountEntity | None:
        return self._account if entity_id == self._account.id else None


class _ReadySnapshotBackend:
    """In-memory, read-only synthesis backend; every byte was validated before construction."""

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
        # E1 owns the one settled operation cost.  Returning zero prevents per-field duplication.
        return SynthesisResult(
            fields=self._fields.get(str(field.field_key), ()),
            cost_cents=Decimal(0),
        )


async def build_exa_deep_snapshot_resolver(
    *,
    account: AccountEntity,
    snapshots: Sequence[ExternalResearchSnapshotRef],
    allowed_field_keys: Collection[str],
    storage: StorageBackend,
    conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]],
) -> Resolver:
    """Build one account-scoped resolver from ready E1 snapshots, with no provider fallback."""

    if not snapshots:
        raise ExaDeepSnapshotError("Exa Deep materialization requires at least one ready snapshot")
    allowed = frozenset(allowed_field_keys)
    if not allowed:
        raise ExaDeepSnapshotError("Exa Deep materialization requires admitted directive fields")
    fields: list[SynthesizedField] = []
    seen_snapshot_ids: set[str] = set()
    # Snapshots arrive newest-first.  A newer request owns the outcome for every field it asked
    # for, including null or unsupported outcomes; an older value must never resurrect behind a
    # newer miss.  Overlap is expected when a refresh repacks bundles, so shadow rather than fail.
    shadowed_field_keys: set[str] = set()
    for snapshot in snapshots:
        if snapshot.source_key != SOURCE_KEY:
            raise ExaDeepSnapshotError("snapshot source does not match the Exa Deep adapter")
        if snapshot.account_id != account.id:
            raise ExaDeepSnapshotError("snapshot belongs to another resolved account")
        if snapshot.workspace_id != account.workspace_id:
            raise ExaDeepSnapshotError("snapshot belongs to another workspace")
        snapshot_ref = str(snapshot.snapshot_id)
        if snapshot_ref in seen_snapshot_ids:
            raise ExaDeepSnapshotError("the same snapshot was supplied more than once")
        seen_snapshot_ids.add(snapshot_ref)

        response, stored_normalization_json = await load_exa_deep_snapshot(
            storage=storage,
            snapshot=snapshot,
        )
        stored_normalization = ExaDeepNormalization.model_validate(stored_normalization_json)
        request_artifact = json.loads(await storage.get(snapshot.request_artifact_key))
        if not isinstance(request_artifact, dict):
            raise ExaDeepSnapshotError("stored Exa request artifact is not a JSON object")
        request_json = request_artifact.get("wire_request")
        if not isinstance(request_json, dict):
            raise ExaDeepSnapshotError("stored Exa request artifact lacks the immutable wire body")
        request = ExaDeepSearchRequest.model_validate(request_json)
        properties = request.output_schema.get("properties")
        if not isinstance(properties, dict):  # independently enforced by the request model
            raise ExaDeepSnapshotError("stored Exa request has no structured field map")
        requested_field_keys = frozenset(
            str(field_key_from_exa_alias(alias)) for alias in properties
        )
        unauthorized = requested_field_keys - allowed
        if unauthorized:
            raise ExaDeepSnapshotError(
                "snapshot requested fields outside the exact effective directive: "
                f"{sorted(unauthorized)!r}"
            )
        recomputed = normalize_exa_deep_snapshot(request, response)
        if recomputed != stored_normalization:
            raise ExaDeepSnapshotError(
                "stored Exa normalization differs from the request/response-derived value"
            )
        if (
            response.request_id != snapshot.provider_request_id
            or recomputed.request_id != snapshot.provider_request_id
        ):
            raise ExaDeepSnapshotError("snapshot provider request id is inconsistent")
        if recomputed.synthesis.cost_cents != snapshot.provider_reported_cost_cents:
            raise ExaDeepSnapshotError("snapshot provider cost is inconsistent")
        if recomputed.all_null != snapshot.all_null:
            raise ExaDeepSnapshotError("snapshot all-null disposition is inconsistent")

        async with conn_factory() as conn:
            result_artifacts = await list_external_research_result_artifacts(
                conn,
                workspace_id=snapshot.workspace_id,
                snapshot_id=snapshot.snapshot_id,
            )
        artifact_by_url = {item.source_url: item.artifact_key for item in result_artifacts}
        if len(artifact_by_url) != len(result_artifacts):
            raise ExaDeepSnapshotError("snapshot result artifact URLs are not unique")
        active_field_keys = requested_field_keys - shadowed_field_keys
        for field in recomputed.synthesis.fields:
            key = str(field.field_key)
            if key not in requested_field_keys:
                raise ExaDeepSnapshotError("normalized field was absent from its stored request")
            if key not in active_field_keys:
                continue
            artifact_key = artifact_by_url.get(field.source_url)
            if artifact_key is None:
                raise ExaDeepSnapshotError(
                    "grounded field has no matching immutable result artifact"
                )
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
        # Mark requested outcomes, not only claim candidates.  Null, unsupported, and
        # below-confidence outcomes must also shadow an older candidate for the same field.
        shadowed_field_keys.update(requested_field_keys)

    backend = _ReadySnapshotBackend(account_id=account.id, fields=fields)
    return cast(
        Resolver,
        GroundedSynthesisResolver(
            backend,
            _OneAccountLookup(account),
            source_key=SOURCE_KEY,
            default_cost_cents=Decimal(0),
        ),
    )


class ExaDeepSnapshotResolverProvider:
    """Resolve exact-run ready snapshots into task-scoped source bindings for account research."""

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
    ) -> Mapping[str, Resolver]:
        if research_directive is None:
            raise ExaDeepSnapshotError(
                "snapshot materialization requires a confirmed directive pin"
            )
        if research_directive.account_id != account_entity_id:
            raise ExaDeepSnapshotError("directive pin belongs to another account")
        async with self._conn_factory() as conn:
            account = await get_account(conn, account_entity_id)
            if account is None or account.workspace_id != workspace_id:
                raise ExaDeepSnapshotError(
                    "snapshot materialization account is absent or cross-workspace"
                )
            effective = await effective_account_research_directive(
                conn,
                workspace_id=workspace_id,
                directive_id=research_directive.directive_id,
                account_id=account_entity_id,
                expected_pin=research_directive,
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
        resolver = await build_exa_deep_snapshot_resolver(
            account=account,
            snapshots=snapshots,
            allowed_field_keys=effective.field_keys,
            storage=self._storage,
            conn_factory=self._conn_factory,
        )
        return {SOURCE_KEY: resolver}


__all__ = [
    "ExaDeepSnapshotError",
    "ExaDeepSnapshotResolverProvider",
    "build_exa_deep_snapshot_resolver",
]
