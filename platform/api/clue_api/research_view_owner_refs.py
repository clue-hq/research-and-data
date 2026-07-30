"""Authenticated batch resolution for C7 non-claim owner references."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.contact_eligibility import ContactEligibilityResolver
from clue_api.research_view_readers import ResearchViewScopeResolver
from clue_core import (
    ClaimId,
    EntityType,
    ResearchDataSpecies,
    ResearchOwnedReference,
    ResearchViewReadRequest,
)
from clue_db import ConnFactory, repeatable_read_transaction
from clue_research.claimstore import claims_by_ids
from clue_research.coverage import list_decisions
from clue_research.durable import list_subject_activity
from clue_research.identity import get_account, get_contact


class OwnerReferenceResolutionError(ValueError):
    """A requested reference is stale, foreign, malformed, or no longer in the current view."""


class OwnerReferenceResolution(BaseModel):
    """One current owner result, versioned and ETagged independently from the C7 aggregate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: ResearchOwnedReference
    owner_version: str
    value_json: JsonValue
    etag: str


def _etag(reference: ResearchOwnedReference, owner_version: str, value: JsonValue) -> str:
    body = json.dumps(
        {
            "reference": reference.model_dump(mode="json"),
            "owner_version": owner_version,
            "value": value,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(body).hexdigest()


def _tail_uuid(owner_ref: str) -> UUID:
    try:
        return UUID(owner_ref.rsplit(":", 1)[-1])
    except ValueError as exc:
        raise OwnerReferenceResolutionError("owner_reference_unresolvable") from exc


class ProductionOwnerReferenceResolver:
    """Resolve only references emitted by the current governed view in one read snapshot."""

    def __init__(
        self,
        composer: Any,
        *,
        conn_factory: ConnFactory = repeatable_read_transaction,
        scope_resolver: ResearchViewScopeResolver | None = None,
    ) -> None:
        self._composer = composer
        self._conn_factory = conn_factory
        self._scope_resolver = scope_resolver or ResearchViewScopeResolver()

    async def resolve(
        self,
        request: ResearchViewReadRequest,
        references: tuple[ResearchOwnedReference, ...],
    ) -> tuple[OwnerReferenceResolution, ...]:
        if len(references) > 100:
            raise OwnerReferenceResolutionError("owner_reference_batch_too_large")
        async with self._conn_factory() as conn:
            view = await self._composer.compose_on_connection(conn, request)
            scope = await self._scope_resolver.resolve(conn, request)
            current = {
                (item.item_id, item.owner_ref): item
                for section in view.sections
                for item in section.items
                if isinstance(item, ResearchOwnedReference)
            }
            requested: list[ResearchOwnedReference] = []
            for reference in references:
                emitted = current.get((reference.item_id, reference.owner_ref))
                if emitted is None or emitted != reference:
                    raise OwnerReferenceResolutionError("owner_reference_not_current")
                requested.append(reference)

            score_ids = tuple(
                ClaimId(_tail_uuid(item.owner_ref))
                for item in requested
                if item.data_species is ResearchDataSpecies.SCORE
            )
            scores = await claims_by_ids(conn, score_ids, scope=scope.workspace_scope)

            committee_by_id = {}
            if any(
                item.data_species is ResearchDataSpecies.COMMITTEE for item in requested
            ):
                committee_rows = await ContactEligibilityResolver(
                    project_run_id=request.project_run_id,
                    product_id=request.product_id,
                    conn_factory=lambda: _borrowed(conn),
                ).resolve_account(
                    account_entity_id=scope.account_entity_id,
                    workspace_id=request.workspace_id,
                )
                committee_by_id = {
                    item.contact_entity_id: item for item in committee_rows
                }

            coverage_by_id = {}
            if any(item.data_species is ResearchDataSpecies.COVERAGE for item in requested):
                coverage_rows = await list_decisions(
                    conn,
                    workspace_id=request.workspace_id,
                    run_id=scope.account_run.id,
                    entity_id=scope.account_entity_id,
                )
                coverage_by_id = {
                    UUID(str(item.id)): item for item in coverage_rows
                }

            activity_ids = tuple(
                _tail_uuid(item.owner_ref)
                for item in requested
                if item.data_species is ResearchDataSpecies.ACTIVITY
            )
            activity_by_id: dict[UUID, dict[str, JsonValue]] = {}
            if activity_ids:
                rows = await list_subject_activity(
                    conn,
                    workspace_id=request.workspace_id,
                    project_id=request.project_id,
                    project_run_id=request.project_run_id,
                    account_run_id=scope.account_run.id,
                    subject_entity_id=request.subject_entity_id,
                    subject_entity_type=scope.subject.entity_type,
                    product_id=request.product_id,
                    limit=100,
                )
                activity_by_id = {
                    row.activity_id: {
                        "event_kind": row.event_kind,
                        "owner_event_ref": row.owner_event_ref,
                        "actor_category": row.actor_category,
                        "occurred_at": row.occurred_at.isoformat(),
                    }
                    for row in rows
                    if row.activity_id in activity_ids
                }

            account = await get_account(conn, scope.account_entity_id)
            contact = (
                await get_contact(conn, scope.subject.entity_id)
                if scope.subject.entity_type is EntityType.CONTACT
                else None
            )
            return tuple(
                self._resolve_one(
                    reference,
                    scope=scope,
                    account=account,
                    contact=contact,
                    scores=scores,
                    committee=committee_by_id,
                    coverage=coverage_by_id,
                    activity=activity_by_id,
                )
                for reference in requested
            )

    @staticmethod
    def _resolve_one(
        reference: ResearchOwnedReference,
        *,
        scope: Any,
        account: Any,
        contact: Any,
        scores: Any,
        committee: Any,
        coverage: Any,
        activity: Any,
    ) -> OwnerReferenceResolution:
        species = reference.data_species
        if species is ResearchDataSpecies.IDENTITY:
            entity = contact if reference.subject.entity_type is EntityType.CONTACT else account
            if entity is None:
                raise OwnerReferenceResolutionError("owner_reference_unresolvable")
            value: JsonValue = entity.model_dump(mode="json")
            version = f"canonical:{entity.canonical_version}"
        elif species is ResearchDataSpecies.EXECUTION:
            value = {
                "account_run_id": str(scope.account_run.id),
                "account_run_status": scope.account_run.status.value,
                "account_run_sub_phase": (
                    scope.account_run.sub_phase.value
                    if scope.account_run.sub_phase is not None
                    else None
                ),
                "tier": scope.account_run.tier,
                "project_run_phase": scope.project_run.phase.value,
                "project_run_status": scope.project_run.status.value,
                "updated_at": scope.account_run.updated_at.isoformat(),
            }
            version = f"account-run:{scope.account_run.updated_at.isoformat()}"
        elif species is ResearchDataSpecies.SCORE:
            claim_id = ClaimId(_tail_uuid(reference.owner_ref))
            claim = scores.get(claim_id)
            if claim is None:
                raise OwnerReferenceResolutionError("owner_reference_unresolvable")
            value = {
                "claim_id": str(claim.id),
                "field_key": str(claim.field_key),
                "score": claim.value_json,
                "evidence_claim_ids": [
                    str(claim_id) for claim_id in reference.evidence_claim_ids
                ],
            }
            version = f"claim:{claim.id}"
        elif species is ResearchDataSpecies.COMMITTEE:
            item = committee.get(reference.subject.entity_id)
            if item is None:
                raise OwnerReferenceResolutionError("owner_reference_unresolvable")
            value = {
                "contact_entity_id": str(item.contact_entity_id),
                "account_entity_id": str(item.account_entity_id),
                "persona": item.persona.value,
                "role_on_committee": item.role_on_committee,
                "display_claim_ids": [
                    str(claim.claim.id) for claim in item.display_claims
                ],
                "personalization_claim_ids": [
                    str(claim.claim.id) for claim in item.personalization_claims
                ],
            }
            version = f"committee:{item.role_claim_id}:{item.persona_claim_id}"
        elif species is ResearchDataSpecies.COVERAGE:
            item = coverage.get(_tail_uuid(reference.owner_ref))
            if item is None:
                raise OwnerReferenceResolutionError("owner_reference_unresolvable")
            value = item.model_dump(mode="json")
            version = f"coverage-decision:{item.id}"
        elif species is ResearchDataSpecies.ACTIVITY:
            event_id = _tail_uuid(reference.owner_ref)
            value = activity.get(event_id)
            if value is None:
                raise OwnerReferenceResolutionError("owner_reference_unresolvable")
            version = f"subject-activity:{event_id}"
        else:
            raise OwnerReferenceResolutionError("owner_reference_species_not_supported")
        return OwnerReferenceResolution(
            reference=reference,
            owner_version=version,
            value_json=value,
            etag=_etag(reference, version, value),
        )


class _borrowed:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> AsyncConnection:
        return self._conn

    async def __aexit__(self, *_args: object) -> None:
        return None


__all__ = [
    "OwnerReferenceResolution",
    "OwnerReferenceResolutionError",
    "ProductionOwnerReferenceResolver",
]
