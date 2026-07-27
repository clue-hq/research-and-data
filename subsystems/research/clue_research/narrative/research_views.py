"""Deterministic C7 account/contact research-view composition.

The composer in this module owns no identity, score, committee, activity, execution, coverage, or
claim truth. Those species arrive through narrow injected readers. The composer only target-locks
their outputs, resolves claim statements through the injected governance seam, orders the frozen
semantic sections, builds complete reverse provenance, and computes a source-state hash.

The nine-block projection at the bottom is a compatibility adapter over references in the composed
view. It deliberately carries no research values or connective prose.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, model_validator

from clue_core import (
    AccountResearchView,
    Claim,
    ClaimFlavor,
    ClaimId,
    ContactResearchView,
    DossierBlockKind,
    EntityType,
    EvidenceActionDescriptor,
    FreshnessState,
    OutreachDecision,
    ResearchAvailability,
    ResearchCoverageSummary,
    ResearchItemState,
    ResearchOwnedReference,
    ResearchPersonalizationItem,
    ResearchProvenanceRef,
    ResearchSection,
    ResearchSectionKind,
    ResearchStatement,
    ResearchStatementId,
    ResearchStatementKind,
    ResearchStatusSummary,
    ResearchSubjectRef,
    ResearchSupportRef,
    ResearchView,
    ResearchViewId,
    ResearchViewItem,
    ResearchViewReadRequest,
    ReuseScope,
    VerificationStatus,
    canonical_json,
    compatibility_block_kind,
)


class ResearchViewCompositionError(ValueError):
    """A reader returned data outside the exact requested scope or frozen C7 contract."""


class ResearchStatementCandidate(BaseModel):
    """One claim assigned to a semantic section by the owning reader/field registry.

    A direct candidate carries no supports. A derived candidate carries the exact immutable,
    ordered support set from ``claim_derivation``. The composer never invents a support edge or
    chooses a section from free-form claim text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    section_kind: ResearchSectionKind
    claim: Claim
    supports: tuple[ResearchSupportRef, ...] = ()

    @model_validator(mode="after")
    def _candidate_matches_claim_flavor(self) -> ResearchStatementCandidate:
        if self.claim.claim_flavor is ClaimFlavor.FIELD_CLAIM and self.supports:
            raise ValueError("a direct candidate cannot carry derivation supports")
        if self.claim.claim_flavor is ClaimFlavor.DERIVED and not self.supports:
            raise ValueError("a derived candidate requires its complete support set")
        if self.claim.claim_flavor is ClaimFlavor.DISCOVERY:
            raise ValueError("discovery provenance is not a display statement")
        ordinals = tuple(support.ordinal for support in self.supports)
        if ordinals != tuple(range(len(self.supports))):
            raise ValueError("candidate supports must have contiguous ordinals from zero")
        return self


class StatementGovernanceResult(BaseModel):
    """Current display/outreach disposition supplied by the governance authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: ResearchItemState
    evidence_actions: tuple[EvidenceActionDescriptor, ...] = ()

    @model_validator(mode="after")
    def _hidden_results_have_no_actions(self) -> StatementGovernanceResult:
        if self.state.availability is not ResearchAvailability.AVAILABLE and self.evidence_actions:
            raise ValueError("a non-available statement cannot expose evidence actions")
        return self


class ResearchSectionSeed(BaseModel):
    """Reference-only owner output for one semantic section.

    ``empty_availability`` and ``reason_codes`` let an owner distinguish unknown, unavailable,
    redacted, and restricted emptiness without C7 fabricating an explanation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ResearchSectionKind
    references: tuple[ResearchOwnedReference, ...] = ()
    empty_availability: ResearchAvailability = ResearchAvailability.UNKNOWN
    reason_codes: tuple[str, ...] = ("unresearched",)

    @model_validator(mode="after")
    def _empty_state_is_only_for_empty_sections(self) -> ResearchSectionSeed:
        if self.empty_availability is ResearchAvailability.AVAILABLE:
            raise ValueError("empty_availability cannot be available")
        if not self.references and not self.reason_codes:
            raise ValueError("an empty owner section requires an explicit reason code")
        return self


class CanonicalSubjectRead(BaseModel):
    """Canonical subject plus owner-held identity/execution references."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: ResearchSubjectRef
    sections: tuple[ResearchSectionSeed, ...]

    @model_validator(mode="after")
    def _only_subject_header_sections(self) -> CanonicalSubjectRead:
        allowed = {ResearchSectionKind.IDENTITY, ResearchSectionKind.RESEARCH_STATUS}
        if any(section.kind not in allowed for section in self.sections):
            raise ValueError("canonical subject reads may contain only identity/research status")
        return self


class CoverageViewRead(BaseModel):
    """C1-owned reference/count projection and its explicit coverage-gap section."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: ResearchCoverageSummary
    section: ResearchSectionSeed

    @model_validator(mode="after")
    def _section_is_coverage(self) -> CoverageViewRead:
        if self.section.kind is not ResearchSectionKind.COVERAGE_GAPS:
            raise ValueError("coverage reader must return the coverage_gaps section")
        owner_refs = {reference.owner_ref for reference in self.section.references}
        if not owner_refs.issubset(set(self.summary.coverage_ref_ids)):
            raise ValueError("coverage summary must index every visible coverage owner reference")
        return self


@runtime_checkable
class CanonicalSubjectReader(Protocol):
    async def read_subject(
        self, request: ResearchViewReadRequest
    ) -> CanonicalSubjectRead | None: ...


@runtime_checkable
class DirectClaimReader(Protocol):
    async def read_direct_claims(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> tuple[ResearchStatementCandidate, ...]: ...


@runtime_checkable
class DerivedClaimReader(Protocol):
    async def read_derived_claims(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> tuple[ResearchStatementCandidate, ...]: ...


@runtime_checkable
class FitResultReader(Protocol):
    async def read_fit(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> ResearchSectionSeed: ...


@runtime_checkable
class CommitteeViewReader(Protocol):
    async def read_committee(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> ResearchSectionSeed: ...


@runtime_checkable
class CoverageViewReader(Protocol):
    async def read_coverage(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> CoverageViewRead: ...


@runtime_checkable
class ActivityReferenceReader(Protocol):
    async def read_activity(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> ResearchSectionSeed: ...


@runtime_checkable
class StatementGovernanceReader(Protocol):
    async def resolve_statement(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
        candidate: ResearchStatementCandidate,
    ) -> StatementGovernanceResult: ...


ACCOUNT_SECTION_ORDER: tuple[ResearchSectionKind, ...] = (
    ResearchSectionKind.IDENTITY,
    ResearchSectionKind.RESEARCH_STATUS,
    ResearchSectionKind.SUMMARY,
    ResearchSectionKind.ABOUT,
    ResearchSectionKind.FIT,
    ResearchSectionKind.INSIGHTS,
    ResearchSectionKind.COMMITTEE,
    ResearchSectionKind.ACTIVITY,
    ResearchSectionKind.COVERAGE_GAPS,
)

CONTACT_SECTION_ORDER: tuple[ResearchSectionKind, ...] = (
    ResearchSectionKind.IDENTITY,
    ResearchSectionKind.RESEARCH_STATUS,
    ResearchSectionKind.COMMITTEE,
    ResearchSectionKind.SUMMARY,
    ResearchSectionKind.PROFESSIONAL_SIGNALS,
    ResearchSectionKind.EVIDENCE,
    ResearchSectionKind.QUOTES,
    ResearchSectionKind.BACKGROUND,
    ResearchSectionKind.CAREER,
    ResearchSectionKind.EDUCATION,
    ResearchSectionKind.PUBLICATIONS,
    ResearchSectionKind.AWARDS,
    ResearchSectionKind.PERSONALIZATION,
    ResearchSectionKind.COVERAGE_GAPS,
)


_VIEW_NAMESPACE = uuid5(NAMESPACE_URL, "clue-hq:c7:research-view:1.0")
_STATEMENT_NAMESPACE = uuid5(NAMESPACE_URL, "clue-hq:c7:research-statement:1.0")


def _statement_id(
    subject: ResearchSubjectRef,
    candidate: ResearchStatementCandidate,
) -> ResearchStatementId:
    identity = ":".join(
        (
            str(subject.entity_id),
            str(subject.canonical_entity_version),
            str(candidate.claim.id),
            candidate.claim.product_id or "-",
        )
    )
    return ResearchStatementId(uuid5(_STATEMENT_NAMESPACE, identity))


def _sort_items(items: Iterable[ResearchViewItem]) -> tuple[ResearchViewItem, ...]:
    def key(item: ResearchViewItem) -> tuple[str, str, str]:
        if isinstance(item, ResearchStatement):
            return ("statement", str(item.field_key), str(item.claim_id))
        if isinstance(item, ResearchPersonalizationItem):
            return (
                "personalization",
                str(item.statement.field_key),
                str(item.statement.claim_id),
            )
        return ("reference", item.data_species.value, str(item.item_id))

    return tuple(sorted(items, key=key))


def _statement_from_item(item: ResearchViewItem) -> ResearchStatement | None:
    if isinstance(item, ResearchStatement):
        return item
    if isinstance(item, ResearchPersonalizationItem):
        return item.statement
    return None


def _status_summary(sections: Sequence[ResearchSection]) -> ResearchStatusSummary:
    statements = {
        statement.statement_id: statement
        for section in sections
        for item in section.items
        if (statement := _statement_from_item(item)) is not None
    }
    return ResearchStatusSummary(
        total_statement_count=len(statements),
        available_statement_count=sum(
            statement.state.availability is ResearchAvailability.AVAILABLE
            for statement in statements.values()
        ),
        stale_statement_count=sum(
            statement.state.freshness is FreshnessState.STALE for statement in statements.values()
        ),
        restricted_statement_count=sum(
            statement.state.availability
            in {ResearchAvailability.RESTRICTED, ResearchAvailability.REDACTED}
            for statement in statements.values()
        ),
        unknown_section_count=sum(
            section.availability is ResearchAvailability.UNKNOWN for section in sections
        ),
    )


def _provenance_index(
    sections: Sequence[ResearchSection],
) -> tuple[ResearchProvenanceRef, ...]:
    statements = {
        statement.statement_id: statement
        for section in sections
        for item in section.items
        if (statement := _statement_from_item(item)) is not None
    }
    return tuple(
        ResearchProvenanceRef(
            statement_id=statement.statement_id,
            claim_id=statement.claim_id,
            statement_kind=statement.statement_kind,
            support_claim_ids=tuple(support.claim_id for support in statement.supports),
        )
        for statement in sorted(
            statements.values(),
            key=lambda value: (str(value.field_key), str(value.claim_id)),
        )
    )


def _source_state_sha256(
    *,
    request: ResearchViewReadRequest,
    subject: ResearchSubjectRef,
    sections: Sequence[ResearchSection],
    coverage: ResearchCoverageSummary,
) -> str:
    """Hash underlying source items independent of frontend section grouping."""

    unique_items: dict[tuple[str, str], dict[str, object]] = {}
    for section in sections:
        for item in section.items:
            if isinstance(item, ResearchStatement):
                key = ("statement", str(item.statement_id))
                payload = item.model_dump(mode="json")
            elif isinstance(item, ResearchPersonalizationItem):
                key = ("personalization", str(item.item_id))
                payload = item.model_dump(mode="json")
            else:
                key = ("reference", str(item.item_id))
                payload = item.model_dump(mode="json")
            unique_items[key] = payload
    payload = {
        "schema_version": request.schema_version,
        "workspace_id": request.workspace_id,
        "project_id": request.project_id,
        "project_run_id": str(request.project_run_id),
        "subject": subject.model_dump(mode="json"),
        "product_id": request.product_id,
        "items": [
            unique_items[key]
            for key in sorted(unique_items, key=lambda value: (value[0], value[1]))
        ],
        "coverage": coverage.model_dump(mode="json"),
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


class DeterministicResearchViewComposer:
    """Compose one exact live view from injected authorities without calling a model."""

    def __init__(
        self,
        *,
        subjects: CanonicalSubjectReader,
        direct_claims: DirectClaimReader,
        derived_claims: DerivedClaimReader,
        fit: FitResultReader,
        committee: CommitteeViewReader,
        coverage: CoverageViewReader,
        activity: ActivityReferenceReader,
        governance: StatementGovernanceReader,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._subjects = subjects
        self._direct_claims = direct_claims
        self._derived_claims = derived_claims
        self._fit = fit
        self._committee = committee
        self._coverage = coverage
        self._activity = activity
        self._governance = governance
        self._clock = clock or (lambda: datetime.now(UTC))

    async def compose(self, request: ResearchViewReadRequest) -> ResearchView:
        subject_read = await self._subjects.read_subject(request)
        if subject_read is None:
            raise ResearchViewCompositionError("subject_not_found")
        subject = subject_read.subject
        if subject.entity_id != request.subject_entity_id:
            raise ResearchViewCompositionError("subject_mismatch")

        section_order = (
            ACCOUNT_SECTION_ORDER
            if subject.entity_type is EntityType.ACCOUNT
            else CONTACT_SECTION_ORDER
        )
        seeds = list(subject_read.sections)
        seeds.extend(
            (
                await self._fit.read_fit(request, subject),
                await self._committee.read_committee(request, subject),
                await self._activity.read_activity(request, subject),
            )
        )
        coverage_read = await self._coverage.read_coverage(request, subject)
        seeds.append(coverage_read.section)

        direct = await self._direct_claims.read_direct_claims(request, subject)
        derived = await self._derived_claims.read_derived_claims(request, subject)
        if any(candidate.claim.claim_flavor is not ClaimFlavor.FIELD_CLAIM for candidate in direct):
            raise ResearchViewCompositionError("direct_reader_flavor_mismatch")
        if any(candidate.claim.claim_flavor is not ClaimFlavor.DERIVED for candidate in derived):
            raise ResearchViewCompositionError("derived_reader_flavor_mismatch")
        candidates = tuple(
            sorted(
                (*direct, *derived),
                key=lambda value: (
                    value.section_kind.value,
                    str(value.claim.field_key),
                    str(value.claim.id),
                ),
            )
        )

        items_by_section: dict[ResearchSectionKind, list[ResearchViewItem]] = {
            kind: [] for kind in section_order
        }
        empty_state: dict[ResearchSectionKind, tuple[ResearchAvailability, tuple[str, ...]]] = (
            dict.fromkeys(
                section_order,
                (ResearchAvailability.UNKNOWN, ("unresearched",)),
            )
        )
        for seed in seeds:
            if seed.kind not in items_by_section:
                if seed.references:
                    raise ResearchViewCompositionError(
                        f"section_not_allowed_for_subject:{seed.kind.value}"
                    )
                continue
            items_by_section[seed.kind].extend(seed.references)
            empty_state[seed.kind] = (seed.empty_availability, seed.reason_codes)

        seen_candidates: set[tuple[UUID, ResearchSectionKind]] = set()
        for candidate in candidates:
            key = (UUID(str(candidate.claim.id)), candidate.section_kind)
            if key in seen_candidates:
                raise ResearchViewCompositionError("duplicate_statement_candidate")
            seen_candidates.add(key)
            if candidate.section_kind not in items_by_section:
                raise ResearchViewCompositionError(
                    f"section_not_allowed_for_subject:{candidate.section_kind.value}"
                )
            statement = await self._resolve_statement(request, subject, candidate)
            if candidate.section_kind is ResearchSectionKind.PERSONALIZATION:
                if statement.state.outreach_decision is OutreachDecision.ALLOWED:
                    items_by_section[candidate.section_kind].append(
                        ResearchPersonalizationItem(
                            item_id=f"personalization:{statement.statement_id}",
                            statement=statement,
                            selection_reason_code="outreach_eligible",
                        )
                    )
                else:
                    empty_state[candidate.section_kind] = (
                        ResearchAvailability.RESTRICTED,
                        ("no_outreach_eligible_statement",),
                    )
                continue
            items_by_section[candidate.section_kind].append(statement)

        sections = tuple(
            self._section(
                subject=subject,
                kind=kind,
                items=_sort_items(items_by_section[kind]),
                empty=empty_state[kind],
            )
            for kind in section_order
        )
        source_hash = _source_state_sha256(
            request=request,
            subject=subject,
            sections=sections,
            coverage=coverage_read.summary,
        )
        view_id = ResearchViewId(
            uuid5(
                _VIEW_NAMESPACE,
                ":".join(
                    (
                        request.workspace_id,
                        request.project_id,
                        str(request.project_run_id),
                        str(subject.entity_id),
                        request.product_id or "-",
                        source_hash,
                    )
                ),
            )
        )
        common = {
            "view_id": view_id,
            "workspace_id": request.workspace_id,
            "project_id": request.project_id,
            "project_run_id": request.project_run_id,
            "subject": subject,
            "product_id": request.product_id,
            "composed_at": self._clock(),
            "source_state_sha256": source_hash,
            "status_summary": _status_summary(sections),
            "sections": sections,
            "provenance_index": _provenance_index(sections),
            "coverage_summary": coverage_read.summary,
        }
        if subject.entity_type is EntityType.ACCOUNT:
            return AccountResearchView.model_validate(common)
        return ContactResearchView.model_validate(common)

    async def _resolve_statement(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
        candidate: ResearchStatementCandidate,
    ) -> ResearchStatement:
        claim = candidate.claim
        if claim.entity_id != subject.entity_id or claim.entity_type is not subject.entity_type:
            raise ResearchViewCompositionError("subject_mismatch")
        if (
            claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            and claim.workspace_id != request.workspace_id
        ):
            raise ResearchViewCompositionError("workspace_mismatch")
        if claim.product_id is not None and claim.product_id != request.product_id:
            raise ResearchViewCompositionError("product_mismatch")
        if claim.product_id is not None and request.product_id is None:
            raise ResearchViewCompositionError("product_mismatch")

        governance = await self._governance.resolve_statement(request, subject, candidate)
        state = governance.state
        if (
            state.availability is ResearchAvailability.AVAILABLE
            and claim.verification_status
            not in {VerificationStatus.VERIFIED, VerificationStatus.FLAGGED}
        ):
            raise ResearchViewCompositionError("verification_mismatch")
        if (
            claim.verification_status is VerificationStatus.REJECTED
            and state.verification is not VerificationStatus.REJECTED
        ):
            raise ResearchViewCompositionError("verification_mismatch")
        if (
            state.outreach_decision is OutreachDecision.ALLOWED
            and claim.entity_type is not EntityType.CONTACT
        ):
            raise ResearchViewCompositionError("outreach_subject_mismatch")

        available = state.availability is ResearchAvailability.AVAILABLE
        return ResearchStatement(
            statement_id=_statement_id(subject, candidate),
            subject=subject,
            field_key=claim.field_key,
            value_json=claim.value_json if available else None,
            statement_kind=(
                ResearchStatementKind.DERIVED
                if claim.claim_flavor is ClaimFlavor.DERIVED
                else ResearchStatementKind.DIRECT
            ),
            claim_id=claim.id,
            supports=candidate.supports,
            product_id=claim.product_id,
            state=state,
            confidence=claim.confidence,
            observed_at=claim.observed_at,
            collected_at=claim.collected_at,
            identity_binding=claim.identity_binding,
            use_class=claim.use_class,
            evidence_actions=governance.evidence_actions if available else (),
        )

    @staticmethod
    def _section(
        *,
        subject: ResearchSubjectRef,
        kind: ResearchSectionKind,
        items: tuple[ResearchViewItem, ...],
        empty: tuple[ResearchAvailability, tuple[str, ...]],
    ) -> ResearchSection:
        del subject  # The view model performs the exact relation/subject validation.
        if items:
            return ResearchSection(
                section_id=f"research.{kind.value}",
                kind=kind,
                block_kind=compatibility_block_kind(kind),
                availability=ResearchAvailability.AVAILABLE,
                items=items,
            )
        availability, reasons = empty
        return ResearchSection(
            section_id=f"research.{kind.value}",
            kind=kind,
            block_kind=compatibility_block_kind(kind),
            availability=availability,
            reason_codes=reasons,
        )


class ResearchBlockItemRef(BaseModel):
    """One body-free reference in the legacy nine-block adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    item_kind: str
    statement_id: ResearchStatementId | None = None
    claim_id: ClaimId | None = None
    owner_ref: str | None = None

    @model_validator(mode="after")
    def _exactly_one_reference_shape(self) -> ResearchBlockItemRef:
        statement_shape = self.statement_id is not None and self.claim_id is not None
        owner_shape = self.owner_ref is not None
        if statement_shape == owner_shape:
            raise ValueError("block item must be either a statement ref or owner ref")
        return self


class ResearchBlockProjection(BaseModel):
    """One compatibility block; items remain references to the canonical live view."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    block_kind: DossierBlockKind
    source_section_ids: tuple[str, ...] = ()
    items: tuple[ResearchBlockItemRef, ...] = ()


class NineBlockResearchProjection(BaseModel):
    """Reference-only projection over all nine frozen dossier block kinds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    view_id: ResearchViewId
    source_state_sha256: str
    blocks: tuple[ResearchBlockProjection, ...]
    provenance_index: tuple[ResearchProvenanceRef, ...]


def project_nine_blocks(view: ResearchView) -> NineBlockResearchProjection:
    """Project a composed view losslessly into the frozen nine-block vocabulary.

    Semantic sections that share ``signal`` are combined. Section labels, research values, and
    prose are not copied. ``source_state_sha256`` is carried unchanged because grouping is not
    source state.
    """

    sections_by_block: dict[DossierBlockKind, list[ResearchSection]] = {
        kind: [] for kind in DossierBlockKind
    }
    for section in view.sections:
        if section.block_kind is not None:
            sections_by_block[section.block_kind].append(section)

    blocks: list[ResearchBlockProjection] = []
    for block_kind in DossierBlockKind:
        sections = sections_by_block[block_kind]
        refs: list[ResearchBlockItemRef] = []
        for section in sections:
            for item in section.items:
                statement = _statement_from_item(item)
                if statement is not None:
                    refs.append(
                        ResearchBlockItemRef(
                            item_id=(
                                str(item.item_id)
                                if isinstance(item, ResearchPersonalizationItem)
                                else str(statement.statement_id)
                            ),
                            item_kind=item.item_kind,
                            statement_id=statement.statement_id,
                            claim_id=statement.claim_id,
                        )
                    )
                else:
                    if not isinstance(item, ResearchOwnedReference):  # pragma: no cover
                        raise TypeError("unexpected research-view item")
                    refs.append(
                        ResearchBlockItemRef(
                            item_id=str(item.item_id),
                            item_kind=item.item_kind,
                            owner_ref=str(item.owner_ref),
                        )
                    )
        blocks.append(
            ResearchBlockProjection(
                block_kind=block_kind,
                source_section_ids=tuple(section.section_id for section in sections),
                items=tuple(refs),
            )
        )

    return NineBlockResearchProjection(
        schema_version=view.schema_version,
        view_id=view.view_id,
        source_state_sha256=view.source_state_sha256,
        blocks=tuple(blocks),
        provenance_index=view.provenance_index,
    )
