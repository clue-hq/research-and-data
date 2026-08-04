"""Request-scoped database readers for production C7 research views."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.contact_eligibility import ContactEligibilityResolver
from clue_core import (
    ClaimId,
    EntityId,
    EntityType,
    ResearchAvailability,
    ResearchCoverageSummary,
    ResearchDataSpecies,
    ResearchOwnedReference,
    ResearchReferenceRelation,
    ResearchSectionKind,
    ResearchSubjectRef,
    ResearchViewReadRequest,
)
from clue_research.claimstore import (
    ResearchViewFieldRoute,
    WorkspaceScope,
    claims_by_ids,
    current_field_claims_resolved_for_product,
    derivation_supports_batch,
    list_research_view_routes,
    live_derived_claims_for_research_view,
)
from clue_research.coverage import list_attempts, list_decisions
from clue_research.discovery_scoring import (
    AmbiguousFitProjection,
    exact_fit_projection,
)
from clue_research.durable import (
    AccountRunRow,
    ProjectRunRow,
    find_account_runs_for_entity,
    get_project_run,
    list_subject_activity,
)
from clue_research.identity import (
    canonical_member_ids,
    get_account,
    get_contact,
)
from clue_research.narrative import (
    CanonicalSubjectRead,
    CoverageViewRead,
    ResearchSectionSeed,
    ResearchStatementCandidate,
)


class ResearchViewScopeNotFound(LookupError):
    """Opaque missing/foreign/ambiguous C7 scope."""


@dataclass(frozen=True)
class ResolvedResearchViewScope:
    request: ResearchViewReadRequest
    project_run: ProjectRunRow
    account_run: AccountRunRow
    subject: ResearchSubjectRef
    canonical_member_entity_ids: tuple[EntityId, ...]
    routes: tuple[ResearchViewFieldRoute, ...]
    account_entity_id: EntityId

    @property
    def workspace_scope(self) -> WorkspaceScope:
        return WorkspaceScope.for_workspace(self.request.workspace_id)


def _reference_uuids(account_run: AccountRunRow) -> frozenset[UUID]:
    values: set[UUID] = set()
    for references in account_run.references_index.values():
        for raw in references:
            try:
                values.add(UUID(str(raw)))
            except (TypeError, ValueError):
                continue
    return frozenset(values)


class ResearchViewScopeResolver:
    """Resolve workspace/project/run/product/subject once inside the read snapshot."""

    async def resolve(
        self,
        conn: AsyncConnection,
        request: ResearchViewReadRequest,
    ) -> ResolvedResearchViewScope:
        project_run = await get_project_run(conn, request.project_run_id)
        if (
            project_run is None
            or project_run.workspace_id != request.workspace_id
            or project_run.project_id != request.project_id
            or project_run.product_id != request.product_id
        ):
            raise ResearchViewScopeNotFound("research_view_scope_not_found")

        requested_type = request.subject_entity_type
        account = (
            await get_account(conn, request.subject_entity_id)
            if requested_type in {None, EntityType.ACCOUNT}
            else None
        )
        contact = (
            await get_contact(conn, request.subject_entity_id)
            if account is None and requested_type in {None, EntityType.CONTACT}
            else None
        )
        if account is not None:
            if account.workspace_id != request.workspace_id or account.merged_into is not None:
                raise ResearchViewScopeNotFound("research_view_scope_not_found")
            subject_type = EntityType.ACCOUNT
            account_id = account.id
            subject = ResearchSubjectRef(
                entity_id=account.id,
                entity_type=EntityType.ACCOUNT,
                canonical_entity_version=account.canonical_version,
            )
        elif contact is not None:
            if contact.workspace_id != request.workspace_id or contact.merged_into is not None:
                raise ResearchViewScopeNotFound("research_view_scope_not_found")
            parent = await get_account(conn, contact.account_entity_id)
            if (
                parent is None
                or parent.workspace_id != request.workspace_id
                or parent.merged_into is not None
            ):
                raise ResearchViewScopeNotFound("research_view_scope_not_found")
            subject_type = EntityType.CONTACT
            account_id = parent.id
            subject = ResearchSubjectRef(
                entity_id=contact.id,
                entity_type=EntityType.CONTACT,
                canonical_entity_version=contact.canonical_version,
                parent_account_id=parent.id,
            )
        else:
            raise ResearchViewScopeNotFound("research_view_scope_not_found")

        matches = await find_account_runs_for_entity(
            conn,
            project_run_id=request.project_run_id,
            entity_id=account_id,
        )
        if len(matches) != 1:
            raise ResearchViewScopeNotFound("research_view_scope_not_found")
        account_run = matches[0]
        members = await canonical_member_ids(
            conn,
            subject.entity_id,
            subject_type,
            workspace_id=request.workspace_id,
        )
        if not members:
            raise ResearchViewScopeNotFound("research_view_scope_not_found")

        if subject_type is EntityType.CONTACT:
            raw_refs = _reference_uuids(account_run)
            referenced_claims = await claims_by_ids(
                conn,
                tuple(ClaimId(value) for value in raw_refs),
                scope=WorkspaceScope.for_workspace(request.workspace_id),
            )
            admitted = UUID(str(subject.entity_id)) in raw_refs or any(
                claim.entity_type is EntityType.CONTACT
                and claim.entity_id in set(members)
                and claim.product_id == request.product_id
                for claim in referenced_claims.values()
            )
            if not admitted:
                raise ResearchViewScopeNotFound("research_view_scope_not_found")

        routes = await list_research_view_routes(
            conn,
            entity_type=subject_type,
            view_schema_version=request.schema_version,
        )
        return ResolvedResearchViewScope(
            request=request,
            project_run=project_run,
            account_run=account_run,
            subject=subject,
            canonical_member_entity_ids=members,
            routes=routes,
            account_entity_id=account_id,
        )


class DbCanonicalSubjectReader:
    def __init__(self, scope: ResolvedResearchViewScope) -> None:
        self._scope = scope

    async def read_subject(self, request: ResearchViewReadRequest) -> CanonicalSubjectRead | None:
        if request != self._scope.request:
            return None
        subject = self._scope.subject
        identity = ResearchOwnedReference(
            item_id=f"identity:{subject.entity_type.value}:{subject.entity_id}",
            subject=subject,
            data_species=ResearchDataSpecies.IDENTITY,
            relation=ResearchReferenceRelation.SUBJECT,
            owner_ref=(
                f"identity:{subject.entity_type.value}:{subject.entity_id}:"
                f"v{subject.canonical_entity_version}"
            ),
        )
        status = ResearchOwnedReference(
            item_id=f"execution:{self._scope.account_run.id}",
            subject=subject,
            data_species=ResearchDataSpecies.EXECUTION,
            relation=ResearchReferenceRelation.SUBJECT,
            owner_ref=f"account-run:{self._scope.account_run.id}",
            product_id=request.product_id,
        )
        return CanonicalSubjectRead(
            subject=subject,
            canonical_member_entity_ids=tuple(
                UUID(str(value)) for value in self._scope.canonical_member_entity_ids
            ),
            sections=(
                ResearchSectionSeed(
                    kind=ResearchSectionKind.IDENTITY,
                    references=(identity,),
                ),
                ResearchSectionSeed(
                    kind=ResearchSectionKind.RESEARCH_STATUS,
                    references=(status,),
                ),
            ),
        )


class DbDirectClaimReader:
    def __init__(self, conn: AsyncConnection, scope: ResolvedResearchViewScope) -> None:
        self._conn = conn
        self._scope = scope

    async def read_direct_claims(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> tuple[ResearchStatementCandidate, ...]:
        if request != self._scope.request or subject != self._scope.subject:
            return ()
        values = await current_field_claims_resolved_for_product(
            self._conn,
            member_entity_ids=self._scope.canonical_member_entity_ids,
            routes=self._scope.routes,
            scope=self._scope.workspace_scope,
            product_id=request.product_id,
            allowed_run_ids=(
                str(request.project_run_id),
                str(self._scope.account_run.id),
            ),
        )
        return tuple(
            ResearchStatementCandidate(
                section_kind=value.route.section_kind,
                claim=value.claim,
            )
            for value in values
        )


class DbDerivedClaimReader:
    def __init__(self, conn: AsyncConnection, scope: ResolvedResearchViewScope) -> None:
        self._conn = conn
        self._scope = scope

    async def read_derived_claims(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> tuple[ResearchStatementCandidate, ...]:
        if request != self._scope.request or subject != self._scope.subject:
            return ()
        roots = await live_derived_claims_for_research_view(
            self._conn,
            member_entity_ids=self._scope.canonical_member_entity_ids,
            routes=self._scope.routes,
            scope=self._scope.workspace_scope,
            product_id=request.product_id,
            allowed_run_ids=(
                str(request.project_run_id),
                str(self._scope.account_run.id),
            ),
        )
        supports_by_root = await derivation_supports_batch(
            self._conn, tuple(claim.id for _route, claim in roots)
        )
        candidates: list[ResearchStatementCandidate] = []
        for route, claim in roots:
            supports = supports_by_root.get(claim.id, ())
            if not supports or tuple(item.ordinal for item in supports) != tuple(
                range(len(supports))
            ):
                continue
            candidates.append(
                ResearchStatementCandidate(
                    section_kind=route.section_kind,
                    claim=claim,
                    supports=supports,
                )
            )
        return tuple(candidates)


class DbFitResultReader:
    def __init__(self, conn: AsyncConnection, scope: ResolvedResearchViewScope) -> None:
        self._conn = conn
        self._scope = scope

    async def read_fit(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> ResearchSectionSeed:
        if subject.entity_type is EntityType.CONTACT:
            return ResearchSectionSeed(
                kind=ResearchSectionKind.FIT,
                empty_availability=ResearchAvailability.UNAVAILABLE,
                reason_codes=("not_applicable",),
            )
        if request.product_id is None:
            return ResearchSectionSeed(
                kind=ResearchSectionKind.FIT,
                reason_codes=("product_score_missing",),
            )
        try:
            projection = await exact_fit_projection(
                self._conn,
                member_entity_ids=self._scope.canonical_member_entity_ids,
                workspace_id=request.workspace_id,
                project_run_id=request.project_run_id,
                icp_key=self._scope.project_run.icp_key,
                icp_version=self._scope.project_run.icp_version,
                product_id=request.product_id,
            )
        except AmbiguousFitProjection:
            return ResearchSectionSeed(
                kind=ResearchSectionKind.FIT,
                empty_availability=ResearchAvailability.RESTRICTED,
                reason_codes=("score_conflict",),
            )
        if projection is None:
            return ResearchSectionSeed(
                kind=ResearchSectionKind.FIT,
                reason_codes=("product_score_missing",),
            )
        reference = ResearchOwnedReference(
            item_id=f"score:{projection.claim.id}",
            subject=subject,
            data_species=ResearchDataSpecies.SCORE,
            relation=ResearchReferenceRelation.SUBJECT,
            owner_ref=f"score-claim:{projection.claim.id}",
            product_id=request.product_id,
            evidence_claim_ids=projection.evidence_claim_ids,
        )
        return ResearchSectionSeed(
            kind=ResearchSectionKind.FIT,
            references=(reference,),
        )


@asynccontextmanager
async def _borrowed_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    yield conn


class DbCommitteeViewReader:
    def __init__(self, conn: AsyncConnection, scope: ResolvedResearchViewScope) -> None:
        self._conn = conn
        self._scope = scope

    async def read_committee(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> ResearchSectionSeed:
        resolver = ContactEligibilityResolver(
            project_run_id=request.project_run_id,
            product_id=request.product_id,
            conn_factory=lambda: _borrowed_connection(self._conn),
        )
        contacts = await resolver.resolve_account(
            account_entity_id=self._scope.account_entity_id,
            workspace_id=request.workspace_id,
        )
        if subject.entity_type is EntityType.CONTACT:
            contacts = tuple(
                item for item in contacts if item.contact_entity_id == subject.entity_id
            )
            relation = ResearchReferenceRelation.SUBJECT
        else:
            relation = ResearchReferenceRelation.COMMITTEE_MEMBER
        references = tuple(
            ResearchOwnedReference(
                item_id=f"committee:{self._scope.account_run.id}:{item.contact_entity_id}",
                subject=ResearchSubjectRef(
                    entity_id=item.contact_entity_id,
                    entity_type=EntityType.CONTACT,
                    canonical_entity_version=item.canonical_entity_version,
                    parent_account_id=self._scope.account_entity_id,
                ),
                data_species=ResearchDataSpecies.COMMITTEE,
                relation=relation,
                owner_ref=f"committee:{self._scope.account_run.id}:{item.contact_entity_id}",
                product_id=request.product_id,
                evidence_claim_ids=tuple(
                    dict.fromkeys(
                        (
                            item.role_claim_id,
                            item.persona_claim_id,
                            *(claim.claim.id for claim in item.display_claims),
                        )
                    )
                ),
            )
            for item in contacts
        )
        return ResearchSectionSeed(
            kind=ResearchSectionKind.COMMITTEE,
            references=references,
            reason_codes=("no_eligible_committee_member",),
        )


class DbCoverageViewReader:
    def __init__(self, conn: AsyncConnection, scope: ResolvedResearchViewScope) -> None:
        self._conn = conn
        self._scope = scope

    async def read_coverage(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> CoverageViewRead:
        if subject.entity_type is EntityType.CONTACT:
            return CoverageViewRead(
                summary=ResearchCoverageSummary(
                    required_field_count=0,
                    filled_field_count=0,
                    terminal_gap_count=0,
                    blocked_field_count=0,
                    budget_exhausted_field_count=0,
                ),
                section=ResearchSectionSeed(
                    kind=ResearchSectionKind.COVERAGE_GAPS,
                    reason_codes=("contact_coverage_not_persisted",),
                ),
            )
        plan = self._scope.account_run.plan_json
        aspects_value = plan.get("aspects") if isinstance(plan, dict) else None
        aspects = aspects_value if isinstance(aspects_value, list) else ()
        required: set[str] = set()
        for aspect in aspects:
            if not isinstance(aspect, dict):
                continue
            field_keys = aspect.get("field_keys")
            if not isinstance(field_keys, list):
                continue
            required.update(str(field) for field in field_keys if isinstance(field, str))
        attempts = await list_attempts(
            self._conn,
            workspace_id=request.workspace_id,
            run_id=self._scope.account_run.id,
            entity_id=self._scope.account_entity_id,
        )
        decisions = await list_decisions(
            self._conn,
            workspace_id=request.workspace_id,
            run_id=self._scope.account_run.id,
            entity_id=self._scope.account_entity_id,
        )
        latest = {}
        for decision in decisions:
            latest[decision.field_key] = decision
        statuses: dict[str, str | None] = {}
        for field in required:
            current_decision = latest.get(field)
            terminal_status = (
                current_decision.terminal_status if current_decision is not None else None
            )
            statuses[field] = terminal_status.value if terminal_status is not None else None
        references = tuple(
            ResearchOwnedReference(
                item_id=f"coverage:{decision.id}",
                subject=subject,
                data_species=ResearchDataSpecies.COVERAGE,
                relation=ResearchReferenceRelation.SUBJECT,
                owner_ref=f"coverage-decision:{decision.id}",
                product_id=request.product_id,
                evidence_claim_ids=decision.claim_refs,
            )
            for decision in sorted(latest.values(), key=lambda item: (item.field_key, str(item.id)))
            if decision.field_key in required
        )
        owner_refs = tuple(reference.owner_ref for reference in references)
        filled = sum(value == "filled" for value in statuses.values())
        terminal = sum(value == "unfilled_terminal" for value in statuses.values())
        blocked = sum(value == "blocked_by_policy" for value in statuses.values())
        budget = sum(value == "budget_exhausted" for value in statuses.values())
        summary = ResearchCoverageSummary(
            coverage_ref_ids=owner_refs,
            required_field_count=len(required),
            filled_field_count=filled,
            terminal_gap_count=terminal,
            blocked_field_count=blocked,
            budget_exhausted_field_count=budget,
        )
        reasons = (
            ("coverage_ledger_empty",)
            if not references and not attempts
            else ("coverage_gaps_present",)
        )
        return CoverageViewRead(
            summary=summary,
            section=ResearchSectionSeed(
                kind=ResearchSectionKind.COVERAGE_GAPS,
                references=references,
                reason_codes=reasons,
            ),
        )


class DbActivityReferenceReader:
    def __init__(self, conn: AsyncConnection, scope: ResolvedResearchViewScope) -> None:
        self._conn = conn
        self._scope = scope

    async def read_activity(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> ResearchSectionSeed:
        if subject.entity_type is EntityType.CONTACT:
            return ResearchSectionSeed(
                kind=ResearchSectionKind.ACTIVITY,
                empty_availability=ResearchAvailability.UNAVAILABLE,
                reason_codes=("not_applicable",),
            )
        rows = await list_subject_activity(
            self._conn,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            project_run_id=request.project_run_id,
            account_run_id=self._scope.account_run.id,
            subject_entity_id=subject.entity_id,
            subject_entity_type=subject.entity_type,
            product_id=request.product_id,
            limit=50,
        )
        references = tuple(
            ResearchOwnedReference(
                item_id=f"activity:{row.activity_id}",
                subject=subject,
                data_species=ResearchDataSpecies.ACTIVITY,
                relation=ResearchReferenceRelation.SUBJECT,
                owner_ref=f"subject-activity:{row.activity_id}",
                product_id=request.product_id,
            )
            for row in rows
        )
        return ResearchSectionSeed(
            kind=ResearchSectionKind.ACTIVITY,
            references=references,
            reason_codes=("no_subject_bound_activity",),
        )


__all__ = [
    "DbActivityReferenceReader",
    "DbCanonicalSubjectReader",
    "DbCommitteeViewReader",
    "DbCoverageViewReader",
    "DbDerivedClaimReader",
    "DbDirectClaimReader",
    "DbFitResultReader",
    "ResearchViewScopeNotFound",
    "ResearchViewScopeResolver",
    "ResolvedResearchViewScope",
]
