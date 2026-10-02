"""Production C7 statement governance and evidence descriptor evaluation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.url_safety import safe_public_url
from clue_core import (
    Claim,
    ClaimFlavor,
    ClaimId,
    DisplayDecision,
    EntityId,
    EntityType,
    EvidenceAccessDecision,
    EvidenceAccessRequest,
    EvidenceActionDescriptor,
    EvidenceActionKind,
    FreshnessState,
    IdentityBinding,
    OutreachDecision,
    ResearchAvailability,
    ResearchConflictState,
    ResearchItemState,
    ResearchSectionKind,
    ResearchSubjectRef,
    ResearchViewReadRequest,
    UseClass,
    VerificationStatus,
    reference_time,
)
from clue_db import ConnFactory, repeatable_read_transaction
from clue_research.claimstore import (
    DerivationDependencyResolution,
    DerivationDependencyResolver,
    DerivationDependencyState,
    WorkspaceScope,
    claims_by_ids,
    current_field_claims_resolved_for_product,
    derivation_supports,
    list_research_view_routes,
)
from clue_research.compliance import (
    WorkspacePolicy,
    latest_use_decisions,
    load_workspace_policy,
    standing_objections,
)
from clue_research.narrative import (
    ResearchStatementCandidate,
    StatementGovernanceResult,
)

_ACTION_NAMESPACE = uuid5(NAMESPACE_URL, "clue-hq:c7:evidence-action:1.0")


def _action_id(
    request: ResearchViewReadRequest,
    claim_id: ClaimId,
    kind: EvidenceActionKind,
) -> UUID:
    return uuid5(
        _ACTION_NAMESPACE,
        ":".join(
            (
                request.workspace_id,
                request.project_id,
                str(request.project_run_id),
                str(request.subject_entity_id),
                str(claim_id),
                kind.value,
            )
        ),
    )


def _evidence_actions(
    request: ResearchViewReadRequest,
    claim: Claim,
) -> tuple[EvidenceActionDescriptor, ...]:
    actions: list[EvidenceActionDescriptor] = []
    if safe_public_url(claim.source_url):
        actions.append(
            EvidenceActionDescriptor(
                kind=EvidenceActionKind.OPEN_PUBLIC_SOURCE,
                claim_id=claim.id,
                action_id=_action_id(request, claim.id, EvidenceActionKind.OPEN_PUBLIC_SOURCE),
                provider_label=claim.source_key,
            )
        )
    if claim.source_key is not None:
        actions.append(
            EvidenceActionDescriptor(
                kind=EvidenceActionKind.VIEW_API_PROVENANCE,
                claim_id=claim.id,
                action_id=_action_id(request, claim.id, EvidenceActionKind.VIEW_API_PROVENANCE),
                provider_label=claim.source_key,
            )
        )
    if claim.artifact_key is not None:
        actions.append(
            EvidenceActionDescriptor(
                kind=EvidenceActionKind.REQUEST_ARTIFACT_PREVIEW,
                claim_id=claim.id,
                action_id=_action_id(
                    request, claim.id, EvidenceActionKind.REQUEST_ARTIFACT_PREVIEW
                ),
                provider_label=claim.source_key,
            )
        )
    return tuple(actions)


def display_allowed(claim: Claim, policy: WorkspacePolicy) -> bool:
    """Whether ``claim`` may be *shown* to a workspace actor under ``policy``.

    Public (it was ``_display_allowed`` until FI-2 slice 1) because it is THE display gate, and a
    second read surface now needs it: the `/frontend/v1` contacts endpoints apply exactly this
    predicate so a field C7 hides can never be visible on the accounts flow. Sharing the one
    function is the point — a copy in the read layer would be free to drift from the policy C7
    enforces. Behaviour is unchanged: account claims are always displayable (governance here is
    personal-data governance); a contact claim needs a strong identity binding (by default) and a
    use-class the workspace policy permits, with ``sensitive`` fail-closed.
    """

    if claim.entity_type is EntityType.ACCOUNT:
        return True
    if (
        policy.display_requires_strong_contact_binding
        and claim.identity_binding is not IdentityBinding.STRONG
    ):
        return False
    if claim.use_class is UseClass.PROFESSIONAL_PUBLIC:
        return policy.display_professional_public
    if claim.use_class is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE:
        return policy.display_personal_public_non_sensitive
    if claim.use_class is UseClass.SENSITIVE:
        return policy.display_sensitive
    return False


def _dependency_reason(
    resolution: DerivationDependencyResolution,
) -> str:
    reasons = " ".join(resolution.reason_codes)
    if "retention" in reasons:
        return "dependency_retention_expired"
    if "erased" in reasons or "objection" in reasons:
        return "dependency_erased"
    if "workspace" in reasons:
        return "dependency_scope_restricted"
    if "stale" in reasons:
        return "dependency_stale"
    if "flagged" in reasons or "conflict" in reasons:
        return "dependency_review_required"
    if "rejected" in reasons:
        return "dependency_rejected"
    return "dependency_unavailable"


class CurrentStatementGovernanceEvaluator:
    """Batch evaluator over one request-scoped read transaction."""

    def __init__(
        self,
        conn: AsyncConnection,
        *,
        member_entity_ids: Sequence[UUID],
        allowed_run_ids: Sequence[str] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._conn = conn
        self._member_entity_ids = frozenset(UUID(str(value)) for value in member_entity_ids)
        self._allowed_run_ids = tuple(dict.fromkeys(allowed_run_ids))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._dependencies = DerivationDependencyResolver()

    async def evaluate(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
        candidates: Sequence[ResearchStatementCandidate],
    ) -> dict[ClaimId, StatementGovernanceResult]:
        if not candidates:
            return {}
        scope = WorkspaceScope.for_workspace(request.workspace_id)
        root_ids = tuple(dict.fromkeys(candidate.claim.id for candidate in candidates))
        roots = await claims_by_ids(self._conn, root_ids, scope=scope)
        routes = await list_research_view_routes(
            self._conn,
            entity_type=subject.entity_type,
            view_schema_version=request.schema_version,
        )
        current_direct = await current_field_claims_resolved_for_product(
            self._conn,
            member_entity_ids=tuple(EntityId(value) for value in self._member_entity_ids),
            routes=routes,
            scope=scope,
            product_id=request.product_id,
            allowed_run_ids=self._allowed_run_ids,
        )
        current_direct_ids = {item.claim.id for item in current_direct}
        derived_ids = tuple(
            claim_id
            for claim_id, claim in roots.items()
            if claim.claim_flavor is ClaimFlavor.DERIVED
        )
        resolutions = await self._dependencies.resolve_many(self._conn, derived_ids, scope=scope)
        dependency_ids = tuple(
            dict.fromkeys(
                claim_id
                for resolution in resolutions.values()
                for claim_id in resolution.required_transitive_claim_ids
            )
        )
        dependencies = await claims_by_ids(self._conn, dependency_ids, scope=scope)
        all_claims = {**dependencies, **roots}
        policy = await load_workspace_policy(self._conn, workspace_id=request.workspace_id)
        personal = tuple(
            claim for claim in all_claims.values() if claim.entity_type is EntityType.CONTACT
        )
        use = await latest_use_decisions(self._conn, tuple(claim.id for claim in personal))
        objections = await standing_objections(
            self._conn,
            workspace_id=request.workspace_id,
            contact_entity_ids=tuple(claim.entity_id for claim in personal),
        )
        ttl_rows = (
            await self._conn.execute(
                text(
                    "SELECT field_key, freshness_ttl FROM field_definition "
                    "WHERE field_key IN :field_keys"
                ).bindparams(bindparam("field_keys", expanding=True)),
                {"field_keys": list({str(candidate.claim.field_key) for candidate in candidates})},
            )
        ).all()
        ttls: dict[str, timedelta | None] = {str(row[0]): row[1] for row in ttl_rows}
        conflict_rows = (
            await self._conn.execute(
                text(
                    """
                    SELECT entity_id, field_key
                    FROM conflict_flag
                    WHERE entity_id IN :entity_ids
                      AND field_key IN :field_keys
                      AND resolved_by IS NULL
                    """
                ).bindparams(
                    bindparam("entity_ids", expanding=True),
                    bindparam("field_keys", expanding=True),
                ),
                {
                    "entity_ids": list(self._member_entity_ids),
                    "field_keys": list(
                        {str(candidate.claim.field_key) for candidate in candidates}
                    ),
                },
            )
        ).all()
        conflicts = {(UUID(str(row[0])), str(row[1])) for row in conflict_rows}

        results: dict[ClaimId, StatementGovernanceResult] = {}
        for candidate in candidates:
            claim = roots.get(candidate.claim.id)
            if claim is None:
                results[candidate.claim.id] = self._hidden(
                    candidate.claim,
                    availability=ResearchAvailability.REDACTED,
                    freshness=FreshnessState.EXPIRED,
                    reason="claim_unavailable_or_erased",
                )
                continue
            if (
                UUID(str(claim.entity_id)) not in self._member_entity_ids
                or claim.entity_type is not subject.entity_type
                or (claim.product_id is not None and claim.product_id != request.product_id)
            ):
                results[claim.id] = self._hidden(
                    claim,
                    availability=ResearchAvailability.RESTRICTED,
                    freshness=FreshnessState.STALE,
                    reason="scope_mismatch",
                )
                continue

            resolution = resolutions.get(claim.id)
            required = (
                tuple(
                    dependencies[claim_id]
                    for claim_id in resolution.required_transitive_claim_ids
                    if claim_id in dependencies
                )
                if resolution is not None
                else ()
            )
            freshness = self._freshness(claim, ttls.get(str(claim.field_key)))
            conflict = (
                UUID(str(claim.entity_id)),
                str(claim.field_key),
            ) in conflicts or claim.verification_status is VerificationStatus.FLAGGED

            if claim.verification_status is VerificationStatus.REJECTED:
                results[claim.id] = self._hidden(
                    claim,
                    availability=ResearchAvailability.UNAVAILABLE,
                    freshness=freshness,
                    reason="verification_rejected",
                )
                continue
            if claim.verification_status not in {
                VerificationStatus.VERIFIED,
                VerificationStatus.FLAGGED,
            }:
                results[claim.id] = self._hidden(
                    claim,
                    availability=ResearchAvailability.UNAVAILABLE,
                    freshness=freshness,
                    reason="verification_incomplete",
                )
                continue
            if claim.claim_flavor is ClaimFlavor.FIELD_CLAIM and claim.id not in current_direct_ids:
                results[claim.id] = self._hidden(
                    claim,
                    availability=ResearchAvailability.UNAVAILABLE,
                    freshness=freshness,
                    reason="claim_not_current",
                )
                continue
            if (
                resolution is not None
                and resolution.state is not DerivationDependencyState.ELIGIBLE_FRESH
            ):
                availability = {
                    DerivationDependencyState.REDACTED: ResearchAvailability.REDACTED,
                    DerivationDependencyState.RESTRICTED: ResearchAvailability.RESTRICTED,
                }.get(resolution.state, ResearchAvailability.UNAVAILABLE)
                results[claim.id] = self._hidden(
                    claim,
                    availability=availability,
                    freshness=resolution.freshness or freshness,
                    reason=_dependency_reason(resolution),
                )
                continue
            if not display_allowed(claim, policy) or any(
                not display_allowed(item, policy) for item in required
            ):
                results[claim.id] = self._hidden(
                    claim,
                    availability=ResearchAvailability.RESTRICTED,
                    freshness=freshness,
                    reason="display_policy_denied",
                )
                continue

            outreach = OutreachDecision.NOT_APPLICABLE
            reasons: list[str] = []
            if claim.entity_type is EntityType.CONTACT:
                governed_personal = (claim, *required)
                allowed = all(
                    item.entity_type is not EntityType.CONTACT
                    or (
                        item.identity_binding is IdentityBinding.STRONG
                        and item.use_class is not UseClass.SENSITIVE
                        and (decision := use.get(item.id)) is not None
                        and decision.usable_for_outreach
                        and item.entity_id not in objections
                    )
                    for item in governed_personal
                )
                outreach = OutreachDecision.ALLOWED if allowed else OutreachDecision.DENIED
                if not allowed:
                    reasons.append("outreach_policy_denied")
            if conflict:
                reasons.append("review_required")
                if claim.entity_type is EntityType.CONTACT:
                    outreach = OutreachDecision.DENIED
            state = ResearchItemState(
                availability=ResearchAvailability.AVAILABLE,
                verification=claim.verification_status,
                freshness=freshness,
                conflict=(
                    ResearchConflictState.REVIEW_REQUIRED
                    if conflict
                    else ResearchConflictState.NONE
                ),
                display_decision=DisplayDecision.ALLOWED,
                outreach_decision=outreach,
                reason_codes=tuple(dict.fromkeys(reasons)),
            )
            results[claim.id] = StatementGovernanceResult(
                state=state,
                evidence_actions=_evidence_actions(request, claim),
            )
        return results

    def _freshness(self, claim: Claim, ttl: timedelta | None) -> FreshnessState:
        if ttl is None:
            return FreshnessState.FRESH
        return (
            FreshnessState.STALE
            if self._clock() - reference_time(claim) > ttl
            else FreshnessState.FRESH
        )

    @staticmethod
    def _hidden(
        claim: Claim,
        *,
        availability: ResearchAvailability,
        freshness: FreshnessState,
        reason: str,
    ) -> StatementGovernanceResult:
        return StatementGovernanceResult(
            state=ResearchItemState(
                availability=availability,
                verification=claim.verification_status,
                freshness=freshness,
                display_decision=DisplayDecision.DENIED,
                outreach_decision=(
                    OutreachDecision.DENIED
                    if claim.entity_type is EntityType.CONTACT
                    else OutreachDecision.NOT_APPLICABLE
                ),
                reason_codes=(reason,),
            )
        )


class ProductionStatementGovernanceReader:
    """Connection-bound batch adapter used by the deterministic composer."""

    def __init__(self, evaluator: CurrentStatementGovernanceEvaluator) -> None:
        self._evaluator = evaluator

    async def resolve_statements(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
        candidates: tuple[ResearchStatementCandidate, ...],
    ) -> Mapping[ClaimId, StatementGovernanceResult]:
        return await self._evaluator.evaluate(request, subject, candidates)

    async def resolve_statement(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
        candidate: ResearchStatementCandidate,
    ) -> StatementGovernanceResult:
        return (await self.resolve_statements(request, subject, (candidate,)))[candidate.claim.id]


class ProductionEvidenceAccessAuthorizer:
    """Re-evaluate a persisted evidence action against current statement governance."""

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = repeatable_read_transaction,
    ) -> None:
        self._conn_factory = conn_factory

    async def authorize(self, request: EvidenceAccessRequest) -> EvidenceAccessDecision:
        async with self._conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT s.project_run_id, s.product_id, s.subject_entity_type,
                               sec.section_kind
                        FROM research_view_snapshot_evidence_action action
                        JOIN research_view_snapshot_item item
                          ON item.snapshot_id = action.snapshot_id
                         AND item.section_ordinal = action.section_ordinal
                         AND item.ordinal = action.item_ordinal
                        JOIN research_view_snapshot_section sec
                          ON sec.snapshot_id = action.snapshot_id
                         AND sec.ordinal = action.section_ordinal
                        JOIN research_view_snapshot s ON s.snapshot_id = action.snapshot_id
                        WHERE action.action_id = :action_id
                          AND action.statement_id = :statement_id
                          AND action.claim_id = :claim_id
                          AND item.item_subject_entity_id = :subject_entity_id
                          AND s.workspace_id = :workspace_id
                          AND s.project_id = :project_id
                        ORDER BY s.created_at DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "action_id": request.action_id,
                        "statement_id": request.statement_id,
                        "claim_id": request.claim_id,
                        "subject_entity_id": request.subject_entity_id,
                        "workspace_id": request.workspace_id,
                        "project_id": request.project_id,
                    },
                )
            ).first()
            if row is None:
                return EvidenceAccessDecision(
                    allowed=False,
                    action_kind=EvidenceActionKind.UNAVAILABLE,
                    claim_id=request.claim_id,
                    reason_codes=("action_not_found",),
                )
            from clue_api.research_view_readers import (  # local import avoids composition cycle
                ResearchViewScopeNotFound,
                ResearchViewScopeResolver,
            )

            read_request = ResearchViewReadRequest(
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                project_run_id=row[0],
                subject_entity_id=request.subject_entity_id,
                subject_entity_type=EntityType(str(row[2])),
                product_id=row[1],
            )
            try:
                resolved = await ResearchViewScopeResolver().resolve(conn, read_request)
            except ResearchViewScopeNotFound:
                return EvidenceAccessDecision(
                    allowed=False,
                    action_kind=EvidenceActionKind.UNAVAILABLE,
                    claim_id=request.claim_id,
                    reason_codes=("scope_not_found",),
                )
            claims = await claims_by_ids(
                conn,
                (request.claim_id,),
                scope=resolved.workspace_scope,
            )
            claim = claims.get(request.claim_id)
            if claim is None:
                erased = bool(
                    (
                        await conn.execute(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM dsar_tombstone "
                                "WHERE erased_claim_id = :claim_id "
                                "AND workspace_id = :workspace_id)"
                            ),
                            {
                                "claim_id": request.claim_id,
                                "workspace_id": request.workspace_id,
                            },
                        )
                    ).scalar_one()
                )
                return EvidenceAccessDecision(
                    allowed=False,
                    action_kind=(
                        EvidenceActionKind.REDACTED if erased else EvidenceActionKind.UNAVAILABLE
                    ),
                    claim_id=request.claim_id,
                    reason_codes=("claim_erased",) if erased else ("claim_unavailable",),
                )
            supports = (
                await derivation_supports(conn, claim.id)
                if claim.claim_flavor is ClaimFlavor.DERIVED
                else ()
            )
            candidate = ResearchStatementCandidate(
                section_kind=ResearchSectionKind(str(row[3])),
                claim=claim,
                supports=supports,
            )
            evaluator = CurrentStatementGovernanceEvaluator(
                conn,
                member_entity_ids=resolved.canonical_member_entity_ids,
                allowed_run_ids=resolved.allowed_run_ids,
            )
            result = (
                await evaluator.evaluate(
                    read_request,
                    resolved.subject,
                    (candidate,),
                )
            )[claim.id]
            action = next(
                (
                    item
                    for item in result.evidence_actions
                    if item.action_id == request.action_id and item.kind is request.desired_action
                ),
                None,
            )
            if result.state.availability is not ResearchAvailability.AVAILABLE or action is None:
                return EvidenceAccessDecision(
                    allowed=False,
                    action_kind=(
                        EvidenceActionKind.REDACTED
                        if result.state.availability is ResearchAvailability.REDACTED
                        else EvidenceActionKind.UNAVAILABLE
                    ),
                    claim_id=request.claim_id,
                    reason_codes=result.state.reason_codes or ("current_policy_denied",),
                )
            return EvidenceAccessDecision(
                allowed=True,
                action_kind=request.desired_action,
                claim_id=request.claim_id,
                reason_codes=("current_policy_allowed",),
            )


__all__ = [
    "CurrentStatementGovernanceEvaluator",
    "ProductionStatementGovernanceReader",
    "ProductionEvidenceAccessAuthorizer",
    "display_allowed",
]
