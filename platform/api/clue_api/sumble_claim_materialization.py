"""Shared Sumble snapshot -> append-only claim -> merge/corroboration materialization."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from clue_core import (
    Claim,
    ClaimId,
    Entity,
    EntityId,
    EntityType,
    ProjectRunId,
    ResearchMode,
    RunId,
    canonical_json,
    revalidate_with,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import (
    FieldRegistryScope,
    WorkspaceScope,
    claims_for,
    current_value,
    get_effective_field,
    insert_claim,
    load_core_pack,
    record_run_lineage,
)
from clue_research.identity import canonical_member_ids
from clue_research.resolvers.sumble import (
    MappingSumbleSnapshotLookup,
    SumbleSnapshot,
    SumbleSourceKey,
    build_sumble_resolvers,
)
from clue_research.sources import seed_source_manifests
from clue_research.verification import Corroborator


class SumbleClaimMaterializationError(RuntimeError):
    pass


class SumbleFieldDisposition(StrEnum):
    CONFIRMED_MISSING = "confirmed_missing"
    RESOLVED = "resolved"
    CORROBORATED = "corroborated"
    CONFLICT = "conflict"


class SumbleMaterializedField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    disposition: SumbleFieldDisposition
    provider_claim_id: ClaimId | None = None
    current_claim_id: ClaimId | None = None
    conflicting_claim_ids: tuple[ClaimId, ...] = ()
    reason_code: str


class SumbleClaimMaterializer:
    """Normalize only durable snapshots and preserve independent provider claims on replay."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def seed(self) -> None:
        async with self._conn_factory() as conn:
            await load_core_pack(conn)
            await seed_source_manifests(conn)

    async def materialize(
        self,
        *,
        workspace_id: str,
        project_id: str,
        project_run_id: ProjectRunId,
        account_id: EntityId,
        field_key: str,
        source_key: str,
        snapshot: SumbleSnapshot,
        source_operation_ref: str | None = None,
        source_snapshot_ref: str | None = None,
        source_request_ref: str | None = None,
    ) -> SumbleMaterializedField:
        if snapshot.artifact_key is None:
            raise SumbleClaimMaterializationError("Sumble claim input is not a durable snapshot")
        async with self._conn_factory() as conn:
            field = await get_effective_field(
                conn,
                scope=FieldRegistryScope.for_workspace(workspace_id),
                field_key=field_key,
            )
        if field is None:
            raise SumbleClaimMaterializationError(
                f"Sumble materialization field {field_key} vanished"
            )
        if source_key not in field.field_def.tier_plan:
            raise SumbleClaimMaterializationError(
                f"field plan no longer admits {source_key} for {field_key}"
            )
        # FI-2 P2 (spec §3): every Sumble claim is stamped with the project run itself as its
        # ``run_id`` (the M8C C1 lineage trigger requires it), so that is the id the project lens
        # must resolve. Registered once per materialized field, before the claim write below;
        # idempotent, so the run's later fields (and any replay) re-register harmlessly.
        async with self._conn_factory() as conn:
            await record_run_lineage(
                conn,
                run_id=UUID(str(project_run_id)),
                workspace_id=workspace_id,
                kind="enrichment",
                project_id=project_id,
                project_run_id=UUID(str(project_run_id)),
            )
        typed_source = cast(SumbleSourceKey, source_key)
        resolver = build_sumble_resolvers(
            MappingSumbleSnapshotLookup({(account_id, typed_source): snapshot})
        )[typed_source]
        candidates = resolver.resolve(
            Entity(entity_id=account_id, entity_type=EntityType.ACCOUNT), field.field_def
        )
        if not candidates:
            return SumbleMaterializedField(
                disposition=SumbleFieldDisposition.CONFIRMED_MISSING,
                reason_code="sumble_terminal_field_absent",
            )
        if len(candidates) != 1:
            raise SumbleClaimMaterializationError("Sumble field normalized to multiple claims")
        candidate = revalidate_with(
            candidates[0],
            source_key=source_key,
            run_id=RunId(project_run_id),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            cost_cents=Decimal(0),
            source_operation_ref=source_operation_ref,
            source_snapshot_ref=source_snapshot_ref,
            source_request_ref=source_request_ref,
        )
        claim_id = await self._ensure_claim(
            workspace_id=workspace_id,
            account_id=account_id,
            candidate=candidate,
        )
        corroboration = await Corroborator(conn_factory=self._conn_factory).evaluate(
            account_id,
            field_key,
            scope=WorkspaceScope.for_workspace(workspace_id),
            entity_type=EntityType.ACCOUNT,
        )
        async with self._conn_factory() as conn:
            merged = await current_value(
                conn,
                account_id,
                field_key,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
        if corroboration.conflict or (merged is not None and merged.conflict):
            conflicts = corroboration.conflicting_claim_ids or (
                merged.conflicting_claim_ids if merged is not None else ()
            )
            return SumbleMaterializedField(
                disposition=SumbleFieldDisposition.CONFLICT,
                provider_claim_id=claim_id,
                conflicting_claim_ids=conflicts,
                reason_code="authoritative_sources_disagree",
            )
        corroborated = any(
            claim_id in group.claim_ids and group.independent_sources >= 2
            for group in corroboration.value_groups
        )
        return SumbleMaterializedField(
            disposition=(
                SumbleFieldDisposition.CORROBORATED
                if corroborated
                else SumbleFieldDisposition.RESOLVED
            ),
            provider_claim_id=claim_id,
            current_claim_id=(merged.provenance.claim_id if merged is not None else claim_id),
            reason_code=("independent_sources_agree" if corroborated else "sumble_native_value"),
        )

    async def _ensure_claim(
        self,
        *,
        workspace_id: str,
        account_id: EntityId,
        candidate: Claim,
    ) -> ClaimId:
        async with self._conn_factory() as conn:
            members = await canonical_member_ids(
                conn,
                account_id,
                EntityType.ACCOUNT,
                workspace_id=workspace_id,
            )
            matches: list[Claim] = []
            for member in members:
                matches.extend(
                    claim
                    for claim in await claims_for(
                        conn,
                        member,
                        candidate.field_key,
                        scope=WorkspaceScope.for_workspace(workspace_id),
                    )
                    if claim.source_key == candidate.source_key
                    and claim.artifact_key == candidate.artifact_key
                    and canonical_json(claim.value_json) == canonical_json(candidate.value_json)
                    and claim.source_operation_ref == candidate.source_operation_ref
                    and claim.source_snapshot_ref == candidate.source_snapshot_ref
                    and claim.source_request_ref == candidate.source_request_ref
                )
            if len(matches) > 1:
                raise SumbleClaimMaterializationError(
                    "duplicate equivalent Sumble claims already exist"
                )
            return matches[0].id if matches else await insert_claim(conn, candidate)


__all__ = [
    "SumbleClaimMaterializationError",
    "SumbleClaimMaterializer",
    "SumbleFieldDisposition",
    "SumbleMaterializedField",
]
