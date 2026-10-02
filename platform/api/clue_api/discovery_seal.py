"""D5 composition: immutable discovery manifests, seal-aware phase, and scoring reader.

The durable repository owns lifecycle truth; this API-root module is the only place that combines
that truth with object storage and phase-handler composition. It performs no provider I/O.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    DiscoveryAccountManifest,
    DiscoveryBatchId,
    DiscoveryBatchState,
    DiscoveryExternalWait,
    DiscoveryPhaseCompletion,
    DiscoverySealBlocker,
    DiscoveryWakeReason,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
    ProjectRunId,
    SealedDiscoveryAccounts,
    evaluate_discovery_seal,
)
from clue_core.entity_research import SealedDiscoveryLaunchReceipt
from clue_db import ConnFactory, transaction
from clue_research.durable import (
    DiscoveryBatchManifestBundle,
    DiscoveryNotFound,
    DiscoveryReplayConflict,
    DiscoverySealConflict,
    discovery_manifest_members,
    get_current_discovery_batch,
    get_discovery_batch,
    get_discovery_batch_manifest,
    get_discovery_batch_seal,
    get_discovery_batch_status,
    get_discovery_field_resolution,
    get_discovery_plan,
    list_discovery_gap_operations,
    put_discovery_batch_manifest,
    read_discovery_seal_readiness,
    seal_discovery_batch,
)
from clue_storage import ArtifactNotFound, StorageBackend, content_address

_MANIFEST_SOURCE = "discovery_seal"
_WAIT_INTERVAL = timedelta(minutes=5)


class DiscoveryBatchStarter(Protocol):
    """Originate the current run's durable acquisition before the seal handler waits on it."""

    async def ensure_started(self, ctx: PhaseContext) -> DiscoveryBatchId: ...


class DiscoveryRequiredFieldResolver(Protocol):
    """Drive pending required-field work after the readiness transaction closes."""

    async def ensure_terminal(self, ctx: PhaseContext, batch_id: DiscoveryBatchId) -> object: ...


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


async def _capture_manifest(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    payload: dict[str, JsonValue],
) -> tuple[str, str]:
    from clue_research.durable import capture_discovery_artifact

    body = _canonical_json(payload)
    key = await capture_discovery_artifact(
        conn,
        storage,
        workspace_id=workspace_id,
        content=body,
        media_type="application/json",
        source_key=_MANIFEST_SOURCE,
    )
    return key, content_address(body)


async def build_discovery_batch_manifest(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    batch_id: DiscoveryBatchId,
) -> DiscoveryBatchManifestBundle:
    """Build/reuse the four canonical artifacts and their immutable relational proof."""

    requested = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
    if requested is None:
        raise DiscoveryNotFound(f"discovery batch {batch_id}")
    batch = await get_current_discovery_batch(
        conn,
        workspace_id=workspace_id,
        project_run_id=requested.project_run_id,
        for_update=True,
    )
    if batch is None or batch.id != requested.id:
        raise DiscoveryReplayConflict("only the exact current generation can build final manifests")
    existing = await get_discovery_batch_manifest(
        conn, workspace_id=workspace_id, batch_id=batch_id
    )
    if existing is not None:
        return existing
    plan_row = await get_discovery_plan(
        conn, workspace_id=workspace_id, plan_id=batch.discovery_plan_id
    )
    if plan_row is None:
        raise DiscoveryNotFound(f"discovery plan {batch.discovery_plan_id}")
    readiness = await read_discovery_seal_readiness(
        conn, workspace_id=workspace_id, batch_id=batch_id
    )
    blockers = tuple(
        blocker
        for blocker in evaluate_discovery_seal(readiness).blockers
        if blocker is not DiscoverySealBlocker.FINAL_MANIFESTS
    )
    if blockers:
        from clue_research.durable import DiscoverySealBlocked

        raise DiscoverySealBlocked(blockers)

    account_ids, claim_ids, raw_keys = await discovery_manifest_members(
        conn, workspace_id=workspace_id, batch_id=batch_id
    )
    plan = plan_row.plan
    account_payload = cast(
        dict[str, JsonValue],
        DiscoveryAccountManifest(
            workspace_id=workspace_id,
            discovery_batch_id=batch.id,
            project_id=batch.project_id,
            project_run_id=batch.project_run_id,
            icp_key=batch.icp_key,
            icp_version=batch.icp_version,
            discovery_plan_id=batch.discovery_plan_id,
            plan_sha256=plan_row.plan_sha256,
            generation=batch.generation,
            account_ids=account_ids,
        ).model_dump(mode="json"),
    )
    claim_payload: dict[str, JsonValue] = {
        "contract": "discovery-claim-manifest-v1",
        "workspace_id": workspace_id,
        "discovery_batch_id": str(batch.id),
        "project_id": batch.project_id,
        "project_run_id": str(batch.project_run_id),
        "claim_ids": [str(value) for value in claim_ids],
    }
    raw_payload: dict[str, JsonValue] = {
        "contract": "discovery-raw-artifact-manifest-v1",
        "workspace_id": workspace_id,
        "discovery_batch_id": str(batch.id),
        "project_id": batch.project_id,
        "project_run_id": str(batch.project_run_id),
        "artifact_keys": list(raw_keys),
    }
    counts = (
        (
            await conn.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM discovery_item_snapshot item
                       JOIN discovery_operation operation
                         ON operation.id = item.operation_id
                        AND operation.workspace_id = item.workspace_id
                       WHERE operation.workspace_id = :workspace_id
                         AND operation.batch_id = :batch_id) AS observed,
                      (SELECT count(*) FROM discovery_candidate_link candidate
                       WHERE candidate.workspace_id = :workspace_id
                         AND candidate.batch_id = :batch_id
                         AND candidate.admission_status = 'excluded') AS excluded
                    """
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        )
        .mappings()
        .one()
    )
    searched_channels = tuple(
        str(value)
        for value in (
            await conn.execute(
                text(
                    "SELECT DISTINCT source_key FROM discovery_operation "
                    "WHERE workspace_id = :workspace_id AND batch_id = :batch_id "
                    "ORDER BY source_key"
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        ).scalars()
    )
    claim_counts = (
        (
            await conn.execute(
                text(
                    """
                    SELECT
                      (SELECT count(DISTINCT edge.claim_id)
                       FROM discovery_field_claim edge
                       JOIN discovery_field_resolution resolution
                         ON resolution.id = edge.resolution_id
                        AND resolution.workspace_id = edge.workspace_id
                       WHERE resolution.workspace_id = :workspace_id
                         AND resolution.batch_id = :batch_id) AS field_resolution,
                      (SELECT count(DISTINCT provider_claim_id)
                       FROM (
                         SELECT materialized.id AS provider_claim_id
                         FROM discovery_candidate_link candidate
                         JOIN discovery_item_snapshot item
                           ON item.id = candidate.item_snapshot_id
                          AND item.workspace_id = candidate.workspace_id
                         JOIN claim materialized
                           ON materialized.entity_id = candidate.survivor_entity_id
                          AND materialized.artifact_key = item.raw_artifact_key
                         WHERE candidate.workspace_id = :workspace_id
                           AND candidate.batch_id = :batch_id
                           AND candidate.admission_status IN ('admitted', 'merged')
                         UNION
                         SELECT provider_claim_id
                         FROM discovery_gap_field_result
                         WHERE workspace_id = :workspace_id
                           AND discovery_batch_id = :batch_id
                           AND provider_claim_id IS NOT NULL
                       ) provider_claims) AS provider_materialized
                    """
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        )
        .mappings()
        .one()
    )
    gap_operation_ids = tuple(
        str(value)
        for value in (
            await conn.execute(
                text(
                    "SELECT id FROM discovery_gap_operation "
                    "WHERE workspace_id=:workspace_id AND discovery_batch_id=:batch_id ORDER BY id"
                ),
                {"workspace_id": workspace_id, "batch_id": batch_id},
            )
        ).scalars()
    )
    coverage_payload: dict[str, JsonValue] = {
        "contract": "discovery-coverage-report-v1",
        "workspace_id": workspace_id,
        "discovery_batch_id": str(batch.id),
        "project_id": batch.project_id,
        "project_run_id": str(batch.project_run_id),
        "icp_key": batch.icp_key,
        "icp_version": batch.icp_version,
        "generation": batch.generation,
        "requested_result_count": sum(search.requested_count for search in plan.searches),
        "observed_item_count": int(counts["observed"]),
        "admitted_account_count": len(account_ids),
        "excluded_candidate_count": int(counts["excluded"]),
        "searched_channels": cast(JsonValue, list(searched_channels)),
        "unsearched_channels": cast(JsonValue, sorted(set(plan.channels) - set(searched_channels))),
        "coverage_is_exhaustive": False,
        "sealed_claim_count": len(claim_ids),
        "field_resolution_claim_count": int(claim_counts["field_resolution"]),
        "materialized_provider_claim_count": int(claim_counts["provider_materialized"]),
        "discovery_gap_operation_ids": cast(JsonValue, list(gap_operation_ids)),
    }
    account_key, account_sha = await _capture_manifest(
        conn, storage, workspace_id=workspace_id, payload=account_payload
    )
    claim_key, claim_sha = await _capture_manifest(
        conn, storage, workspace_id=workspace_id, payload=claim_payload
    )
    raw_key, raw_sha = await _capture_manifest(
        conn, storage, workspace_id=workspace_id, payload=raw_payload
    )
    coverage_key, coverage_sha = await _capture_manifest(
        conn, storage, workspace_id=workspace_id, payload=coverage_payload
    )
    return await put_discovery_batch_manifest(
        conn,
        workspace_id=workspace_id,
        bundle=DiscoveryBatchManifestBundle(
            batch_id=batch.id,
            workspace_id=workspace_id,
            project_id=batch.project_id,
            project_run_id=batch.project_run_id,
            icp_key=batch.icp_key,
            icp_version=batch.icp_version,
            discovery_plan_id=batch.discovery_plan_id,
            plan_sha256=plan_row.plan_sha256,
            generation=batch.generation,
            account_ids=account_ids,
            claim_ids=claim_ids,
            raw_artifact_keys=raw_keys,
            coverage_payload=coverage_payload,
            account_manifest_artifact_key=account_key,
            account_manifest_sha256=account_sha,
            claim_manifest_artifact_key=claim_key,
            claim_manifest_sha256=claim_sha,
            raw_manifest_artifact_key=raw_key,
            raw_manifest_sha256=raw_sha,
            coverage_report_artifact_key=coverage_key,
            coverage_report_sha256=coverage_sha,
        ),
    )


def _completion(seal: object) -> DiscoveryPhaseCompletion:
    from clue_core import DiscoveryBatchSeal

    typed = DiscoveryBatchSeal.model_validate(seal)
    return DiscoveryPhaseCompletion(
        discovery_batch_id=typed.batch_id,
        discovery_batch_seal_ref=typed.seal_sha256,
        account_manifest_ref=typed.account_manifest_artifact_key,
        claim_manifest_ref=typed.claim_id_manifest_key,
        coverage_report_ref=typed.coverage_report_ref,
        provider_receipt_manifest_ref=typed.raw_artifact_manifest_key,
    )


class DurableDiscoveryPhaseHandler:
    """Seal-aware DISCOVERY handler with optional production batch origination.

    Provider I/O is deliberately invoked only after the repository transaction has closed.  Once
    a starter is configured, absence of a batch can never fall through to legacy discovery.
    """

    phase = ProjectPhase.DISCOVERY

    def __init__(
        self,
        *,
        storage: StorageBackend,
        fallback: PhaseHandler,
        starter: DiscoveryBatchStarter | None = None,
        required_field_resolver: DiscoveryRequiredFieldResolver | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._storage = storage
        self._fallback = fallback
        self._starter = starter
        self._required_field_resolver = required_field_resolver
        self._conn_factory = conn_factory

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        started = False
        attempted_required_fields = False
        while True:
            need_start = False
            need_required_fields = False
            required_fields_batch_id: DiscoveryBatchId | None = None
            use_fallback = False
            async with self._conn_factory() as conn:
                batch = await get_current_discovery_batch(
                    conn,
                    workspace_id=ctx.workspace_id,
                    project_run_id=ctx.project_run_id,
                    for_update=True,
                )
                if batch is None:
                    use_fallback = self._starter is None
                    need_start = self._starter is not None and not started
                    if self._starter is not None and started:
                        raise DiscoveryNotFound(
                            "discovery starter returned without creating the current batch"
                        )
                else:
                    if (
                        batch.project_id != ctx.project_id
                        or batch.icp_key != ctx.icp_key
                        or batch.icp_version != ctx.icp_version
                    ):
                        raise DiscoveryReplayConflict(
                            "current discovery batch differs from phase lineage"
                        )
                    if batch.state in {
                        DiscoveryBatchState.PAUSED_BY_USER,
                        DiscoveryBatchState.FAILED_TERMINAL,
                        DiscoveryBatchState.CANCELLED_UNSEALED,
                    }:
                        return PhaseResult(
                            status=PhaseStatus.PAUSED,
                            payload={
                                "discovery_batch_id": str(batch.id),
                                "batch_state": batch.state.value,
                                "failure_code": batch.failure_code,
                                "replacement_batch_id": (
                                    str(batch.replacement_batch_id)
                                    if batch.replacement_batch_id is not None
                                    else None
                                ),
                            },
                        )
                    seal = await get_discovery_batch_seal(
                        conn, workspace_id=ctx.workspace_id, batch_id=batch.id
                    )
                    if seal is None:
                        manifest = await get_discovery_batch_manifest(
                            conn, workspace_id=ctx.workspace_id, batch_id=batch.id
                        )
                        readiness = await read_discovery_seal_readiness(
                            conn,
                            workspace_id=ctx.workspace_id,
                            batch_id=batch.id,
                            draft=manifest.seal_draft if manifest is not None else None,
                        )
                        blockers = evaluate_discovery_seal(readiness).blockers
                        non_manifest = tuple(
                            blocker
                            for blocker in blockers
                            if blocker is not DiscoverySealBlocker.FINAL_MANIFESTS
                        )
                        gap_owned = {
                            DiscoverySealBlocker.REQUIRED_FIELDS,
                            DiscoverySealBlocker.OPERATION_TERMINALITY,
                            DiscoverySealBlocker.DISPATCH_RECEIPTS,
                            DiscoverySealBlocker.SPEND_RECONCILIATION,
                        }
                        gap_operations = await list_discovery_gap_operations(
                            conn,
                            workspace_id=ctx.workspace_id,
                            batch_id=batch.id,
                        )
                        gap_requires_drive = any(
                            operation.terminal_at is None for operation in gap_operations
                        )
                        if (
                            (
                                DiscoverySealBlocker.REQUIRED_FIELDS in non_manifest
                                or gap_requires_drive
                            )
                            and self._required_field_resolver is not None
                            and not attempted_required_fields
                            and set(non_manifest).issubset(gap_owned)
                        ):
                            need_required_fields = True
                            required_fields_batch_id = batch.id
                        elif not non_manifest:
                            manifest = manifest or await build_discovery_batch_manifest(
                                conn,
                                self._storage,
                                workspace_id=ctx.workspace_id,
                                batch_id=batch.id,
                            )
                            seal = await seal_discovery_batch(
                                conn,
                                workspace_id=ctx.workspace_id,
                                batch_id=batch.id,
                                draft=manifest.seal_draft,
                            )
                        elif not need_required_fields:
                            status = await get_discovery_batch_status(
                                conn, workspace_id=ctx.workspace_id, batch_id=batch.id
                            )
                            operation_owned = {
                                DiscoverySealBlocker.OPERATION_TERMINALITY,
                                DiscoverySealBlocker.DISPATCH_RECEIPTS,
                                DiscoverySealBlocker.PROVIDER_EVENTS,
                                DiscoverySealBlocker.FINAL_RECONCILIATION,
                                DiscoverySealBlocker.PAGINATION_EXHAUSTION,
                                DiscoverySealBlocker.ITEM_MATERIALIZATION,
                                DiscoverySealBlocker.SPEND_RECONCILIATION,
                            }
                            reason = (
                                DiscoveryWakeReason.SCHEDULED_POLL
                                if any(blocker in operation_owned for blocker in non_manifest)
                                else DiscoveryWakeReason.FIELD_MATERIALIZATION
                            )
                            wait = DiscoveryExternalWait(
                                discovery_batch_id=batch.id,
                                pending_operation_ids=status.pending_operation_ids,
                                next_poll_at=(
                                    status.next_poll_at or datetime.now(UTC) + _WAIT_INTERVAL
                                ),
                                wake_reason=reason,
                                blockers=non_manifest,
                            )
                            return PhaseResult(
                                status=PhaseStatus.WAITING_EXTERNAL,
                                payload=wait.model_dump(mode="json"),
                            )
                    if not need_required_fields:
                        assert seal is not None
                        completion = _completion(seal)
                        return PhaseResult(
                            status=PhaseStatus.COMPLETED,
                            accounts_processed=seal.account_count,
                            cost_cents=seal.cost_cents_charged,
                            payload=completion.model_dump(mode="json"),
                        )
            if need_start:
                assert self._starter is not None
                # Never hold a DB transaction/row lock across the potentially paid provider call.
                await self._starter.ensure_started(ctx)
                started = True
                continue
            if need_required_fields:
                assert self._required_field_resolver is not None
                assert required_fields_batch_id is not None
                # This may be paid provider work. Never hold readiness locks across it.
                await self._required_field_resolver.ensure_terminal(ctx, required_fields_batch_id)
                attempted_required_fields = True
                continue
            if use_fallback:
                return await self._fallback.run(ctx)
            raise AssertionError("unreachable durable discovery phase state")


class DbSealedDiscoveryAccountManifestReader:
    """Verify and read only the exact immutable D5 account manifest used by scoring."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    async def read(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        icp_key: str,
        icp_version: int,
        discovery_receipt: SealedDiscoveryLaunchReceipt | None = None,
    ) -> SealedDiscoveryAccounts | None:
        run_id = project_run_id
        async with self._conn_factory() as conn:
            batch = (
                await get_discovery_batch(
                    conn,
                    workspace_id=workspace_id,
                    batch_id=DiscoveryBatchId(discovery_receipt.discovery_batch_id),
                )
                if discovery_receipt is not None
                else await get_current_discovery_batch(
                    conn, workspace_id=workspace_id, project_run_id=run_id
                )
            )
            if batch is None:
                return None
            if (
                batch.icp_key != icp_key
                or batch.icp_version != icp_version
                or batch.state is not DiscoveryBatchState.SEALED
            ):
                raise DiscoverySealConflict("research requires the exact sealed generation")
            seal = await get_discovery_batch_seal(
                conn, workspace_id=workspace_id, batch_id=batch.id
            )
            bundle = await get_discovery_batch_manifest(
                conn, workspace_id=workspace_id, batch_id=batch.id
            )
            if seal is None or bundle is None:
                raise DiscoverySealConflict("sealed discovery manifest lineage is incomplete")
            if discovery_receipt is not None and (
                batch.generation != discovery_receipt.discovery_generation
                or seal.seal_sha256 != discovery_receipt.discovery_seal_sha256
                or bundle.account_manifest_artifact_key != discovery_receipt.account_manifest_ref
                or bundle.account_manifest_sha256 != discovery_receipt.account_manifest_sha256
                or bundle.claim_manifest_artifact_key != discovery_receipt.claim_manifest_ref
                or bundle.claim_manifest_sha256 != discovery_receipt.claim_manifest_sha256
            ):
                raise DiscoverySealConflict("stored discovery lineage differs from launch receipt")
            if (
                bundle.account_manifest_artifact_key != seal.account_manifest_artifact_key
                or bundle.account_manifest_sha256 != seal.account_manifest_sha256
                or bundle.raw_manifest_artifact_key != seal.raw_artifact_manifest_key
                or bundle.claim_manifest_artifact_key != seal.claim_id_manifest_key
                or bundle.coverage_report_artifact_key != seal.coverage_report_ref
            ):
                raise DiscoverySealConflict("sealed discovery manifest lineage is incomplete")
            artifact_row = (
                await conn.execute(
                    text(
                        "SELECT content_sha256 FROM artifact "
                        "WHERE workspace_id = :workspace_id AND storage_key = :key "
                        "AND erased_at IS NULL AND purged_at IS NULL"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "key": bundle.account_manifest_artifact_key,
                    },
                )
            ).scalar_one_or_none()
            if artifact_row != bundle.account_manifest_sha256:
                raise DiscoverySealConflict("account manifest artifact is absent or erased")
            try:
                body = await self._storage.get(bundle.account_manifest_artifact_key)
            except ArtifactNotFound as exc:
                raise DiscoverySealConflict("account manifest artifact body is absent") from exc
            if content_address(body) != bundle.account_manifest_sha256:
                raise DiscoverySealConflict("account manifest artifact hash mismatch")
            manifest = DiscoveryAccountManifest.model_validate_json(body)
            # Membership was captured once, before sealing. Recomputing it from the live claim
            # store here lets later Account-profile claims mutate an old generation and falsely
            # invalidate an intact seal. The relational bundle plus the two content-addressed
            # artifacts are the immutable post-seal authority.
            account_ids = bundle.account_ids
            claim_ids = bundle.claim_ids
            if (
                manifest.workspace_id != workspace_id
                or manifest.discovery_batch_id != batch.id
                or manifest.project_id != batch.project_id
                or manifest.project_run_id != run_id
                or manifest.icp_key != icp_key
                or manifest.icp_version != icp_version
                or manifest.discovery_plan_id != batch.discovery_plan_id
                or manifest.plan_sha256 != seal.plan_sha256
                or manifest.plan_sha256 != bundle.plan_sha256
                or manifest.generation != batch.generation
                or manifest.account_ids != bundle.account_ids
                or manifest.account_ids != account_ids
                or len(manifest.account_ids) != seal.account_count
            ):
                raise DiscoverySealConflict("account manifest differs from its immutable seal")

            try:
                claim_body = await self._storage.get(bundle.claim_manifest_artifact_key)
            except ArtifactNotFound as exc:
                raise DiscoverySealConflict("claim manifest artifact body is absent") from exc
            if content_address(claim_body) != bundle.claim_manifest_sha256:
                raise DiscoverySealConflict("claim manifest artifact hash mismatch")
            try:
                claim_manifest = json.loads(claim_body)
            except (TypeError, ValueError) as exc:
                raise DiscoverySealConflict("claim manifest artifact is not valid JSON") from exc
            expected_claim_ids = [str(value) for value in claim_ids]
            if (
                not isinstance(claim_manifest, dict)
                or claim_manifest.get("contract") != "discovery-claim-manifest-v1"
                or claim_manifest.get("workspace_id") != workspace_id
                or claim_manifest.get("discovery_batch_id") != str(batch.id)
                or claim_manifest.get("project_id") != batch.project_id
                or claim_manifest.get("project_run_id") != str(run_id)
                or claim_manifest.get("claim_ids") != expected_claim_ids
                or bundle.claim_ids != claim_ids
            ):
                raise DiscoverySealConflict("claim manifest differs from its immutable seal")

            plan_row = await get_discovery_plan(
                conn, workspace_id=workspace_id, plan_id=batch.discovery_plan_id
            )
            if plan_row is None or plan_row.plan_sha256 != seal.plan_sha256:
                raise DiscoverySealConflict("sealed discovery plan lineage is incomplete")
            required_criteria = tuple(
                dict.fromkeys(
                    criterion.description
                    for search in plan_row.plan.searches
                    for criterion in search.criteria
                )
            )
            resolutions = []
            for account_id in manifest.account_ids:
                for field_key in plan_row.plan.required_account_fields:
                    resolution = await get_discovery_field_resolution(
                        conn,
                        workspace_id=workspace_id,
                        batch_id=batch.id,
                        account_entity_id=account_id,
                        logical_field_key=str(field_key),
                    )
                    if resolution is None or not resolution.is_seal_terminal:
                        raise DiscoverySealConflict(
                            "sealed discovery required-field decisions are incomplete"
                        )
                    resolutions.append(resolution)
            return SealedDiscoveryAccounts(
                discovery_batch_id=batch.id,
                seal_sha256=seal.seal_sha256,
                account_manifest_ref=bundle.account_manifest_artifact_key,
                account_ids=manifest.account_ids,
                claim_manifest_ref=bundle.claim_manifest_artifact_key,
                claim_ids=tuple(ClaimId(value) for value in claim_ids),
                required_criteria=required_criteria,
                required_account_fields=plan_row.plan.required_account_fields,
                field_resolutions=tuple(resolutions),
            )


__all__ = [
    "DbSealedDiscoveryAccountManifestReader",
    "DiscoveryRequiredFieldResolver",
    "DurableDiscoveryPhaseHandler",
    "build_discovery_batch_manifest",
]
