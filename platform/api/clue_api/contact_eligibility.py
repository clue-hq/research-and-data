"""Production contact-eligibility composition for C7.6.

This module is the API-root join between identity, durable account-run references, the claim
store, committee/contact profiling, and the compliance use-decision ledger.  The sibling research
packages remain independent: narrative keeps its two injected protocols, while C7 and M12 consume
adapters over the same governed result.

The resolver deliberately separates:

* display eligibility — a canonical, non-erased committee member with live, product-matching,
  strongly-bound role/persona claims; and
* personalization eligibility — a displayable ``contact.facet.*`` claim that additionally has a
  current use decision allowing outreach.

That distinction is the newer dossier contract: a professional contact may remain visible even
when a personal hook is restricted, but the restricted hook can never enter positioning or the
legacy outreach-eligible handoff surface.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from clue_core import (
    CONTACT_PROFESSIONAL_FIELD_KEYS,
    Claim,
    ClaimId,
    CommitteeMember,
    EntityId,
    EntityType,
    IdentityBinding,
    Persona,
    ProfileClaimView,
    ProjectRunId,
    ResearchAvailability,
    ResearchDataSpecies,
    ResearchOwnedReference,
    ResearchReferenceRelation,
    ResearchSectionKind,
    ResearchSubjectRef,
    ResearchViewReadRequest,
    UseDecision,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import (
    WorkspaceScope,
    active_merge_policy,
    claims_by_ids,
    merge_claims,
)
from clue_research.compliance import latest_use_decisions
from clue_research.durable import find_account_runs_for_entity
from clue_research.identity import (
    contact_ids_for_account,
    get_account,
    get_contacts,
    surviving_id,
    surviving_ids,
)
from clue_research.narrative import (
    CommitteeContact,
    FacetHook,
    HandoffCommitteeMember,
    ResearchSectionSeed,
)
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE


def _as_profile_view(claim: Claim) -> ProfileClaimView:
    return ProfileClaimView(
        claim_id=claim.id,
        value_json=claim.value_json,
        evidence_span=claim.evidence_span,
        source_tier=claim.source_tier,
        identity_binding=claim.identity_binding,
        use_class=claim.use_class,
    )


def _all_reference_ids(references_index: dict[str, list[str]]) -> tuple[ClaimId, ...]:
    """Parse UUID-shaped account-run references.

    ``committee_contacts`` contains contact ids rather than claim ids. Passing those UUIDs through
    ``claims_by_ids`` is harmless: the claim-store seam simply omits non-claim ids. Keeping this
    parsing generic means C7 does not duplicate the deep orchestrator's section vocabulary.
    """

    parsed: set[ClaimId] = set()
    for values in references_index.values():
        for value in values:
            try:
                parsed.add(ClaimId(UUID(value)))
            except (TypeError, ValueError):
                continue
    return tuple(sorted(parsed, key=str))


class GovernedContactClaim(BaseModel):
    """One live product-matching contact claim and its independent use disposition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: Claim
    use_decision: UseDecision | None = None
    display_eligible: bool = True
    personalization_eligible: bool = False


class GovernedCommitteeContact(BaseModel):
    """The single shared eligibility result consumed by C7 and both M12 committee seams."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    account_entity_id: EntityId
    persona: Persona
    role_on_committee: str
    role_claim_id: ClaimId
    persona_claim_id: ClaimId
    claims: tuple[GovernedContactClaim, ...]
    canonical_entity_version: int
    product_id: str | None = None

    @property
    def display_claims(self) -> tuple[GovernedContactClaim, ...]:
        return tuple(item for item in self.claims if item.display_eligible)

    @property
    def personalization_claims(self) -> tuple[GovernedContactClaim, ...]:
        return tuple(item for item in self.claims if item.personalization_eligible)


class ContactEligibilityResolver:
    """Resolve an exact run/product's canonical governed committee.

    The durable ``account_run.references_index`` is the product/run membership authority: claims
    from another project run are never considered even if they are newer current truth for the
    same contact. Every selected committee/contact claim must also have an exact ``product_id``
    match (including ``None`` for legacy/product-neutral runs), so product A relevance cannot enter
    product B's handoff.
    """

    def __init__(
        self,
        *,
        project_run_id: ProjectRunId,
        product_id: str | None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._project_run_id = project_run_id
        self._product_id = product_id
        self._conn_factory = conn_factory

    @property
    def project_run_id(self) -> ProjectRunId:
        return self._project_run_id

    @property
    def product_id(self) -> str | None:
        return self._product_id

    async def resolve_account(
        self,
        *,
        account_entity_id: EntityId,
        workspace_id: str,
    ) -> tuple[GovernedCommitteeContact, ...]:
        async with self._conn_factory() as conn:
            account = await get_account(conn, account_entity_id)
            if (
                account is None
                or account.workspace_id != workspace_id
                or await surviving_id(conn, account_entity_id, EntityType.ACCOUNT)
                != account_entity_id
            ):
                return ()

            account_runs = await find_account_runs_for_entity(
                conn,
                project_run_id=self._project_run_id,
                entity_id=account_entity_id,
            )
            if len(account_runs) != 1:
                return ()
            account_run = account_runs[0]

            referenced = await claims_by_ids(
                conn,
                _all_reference_ids(account_run.references_index),
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            product_claims = tuple(
                claim
                for claim in referenced.values()
                if claim.entity_type is EntityType.CONTACT
                and claim.product_id == self._product_id
                and (
                    str(claim.field_key) in {PERSONA, ROLE_ON_COMMITTEE}
                    or str(claim.field_key) in CONTACT_PROFESSIONAL_FIELD_KEYS
                    or str(claim.field_key).startswith("contact.facet.")
                    or str(claim.field_key) == "contact.class"
                )
            )
            if not product_claims:
                return ()

            live_contacts = set(await contact_ids_for_account(conn, account_entity_id))
            redirects = await surviving_ids(
                conn,
                tuple({claim.entity_id for claim in product_claims}),
                EntityType.CONTACT,
                workspace_id=workspace_id,
            )
            contacts_by_id = await get_contacts(
                conn, tuple(set(redirects.values()) & live_contacts)
            )
            by_contact: dict[EntityId, list[Claim]] = defaultdict(list)
            for claim in product_claims:
                canonical_id = redirects.get(claim.entity_id)
                if canonical_id is None:
                    continue
                if canonical_id not in live_contacts:
                    continue
                contact = contacts_by_id.get(canonical_id)
                if (
                    contact is None
                    or contact.workspace_id != workspace_id
                    or contact.account_entity_id != account_entity_id
                ):
                    continue
                # Identity canonicalization re-keys claims during merge. A stale loser-keyed
                # reference is accepted only when it resolves to the live survivor, and the
                # resulting view always exposes that survivor.
                by_contact[canonical_id].append(
                    claim.model_copy(update={"entity_id": canonical_id})
                    if claim.entity_id != canonical_id
                    else claim
                )

            all_ids = tuple(claim.id for claims in by_contact.values() for claim in claims)
            use_decisions = await latest_use_decisions(conn, all_ids)
            resolved = [
                self._resolve_contact_claims(
                    contact_entity_id=contact_id,
                    account_entity_id=account_entity_id,
                    canonical_entity_version=contacts_by_id[contact_id].canonical_version,
                    claims=claims,
                    use_decisions=use_decisions,
                )
                for contact_id, claims in by_contact.items()
            ]
            return tuple(
                sorted(
                    (contact for contact in resolved if contact is not None),
                    key=lambda value: (value.persona.value, str(value.contact_entity_id)),
                )
            )

    async def resolve_contact(
        self,
        *,
        contact_entity_id: EntityId,
        account_entity_id: EntityId,
        workspace_id: str,
    ) -> GovernedCommitteeContact | None:
        """Resolve contact detail through the same account-list decision.

        A merged loser redirects to its canonical survivor; an erased/ineligible contact returns
        ``None``. This method exists so C7 contact detail cannot drift from the account committee
        list, M12 handoff, or positioning eligibility.
        """

        async with self._conn_factory() as conn:
            canonical_id = await surviving_id(conn, contact_entity_id, EntityType.CONTACT)
        contacts = await self.resolve_account(
            account_entity_id=account_entity_id,
            workspace_id=workspace_id,
        )
        return next(
            (contact for contact in contacts if contact.contact_entity_id == canonical_id),
            None,
        )

    def _resolve_contact_claims(
        self,
        *,
        contact_entity_id: EntityId,
        account_entity_id: EntityId,
        canonical_entity_version: int,
        claims: Iterable[Claim],
        use_decisions: dict[ClaimId, UseDecision],
    ) -> GovernedCommitteeContact | None:
        by_field: dict[str, list[Claim]] = defaultdict(list)
        for claim in claims:
            by_field[str(claim.field_key)].append(claim)

        now = datetime.now(UTC)
        merge_policy = active_merge_policy()  # resolved once per contact (toggle-aware default)
        role_current = merge_claims(by_field.get(ROLE_ON_COMMITTEE, ()), None, merge_policy, now)
        persona_current = merge_claims(by_field.get(PERSONA, ()), None, merge_policy, now)
        if role_current is None or persona_current is None:
            return None
        by_id = {claim.id: claim for claim in claims}
        role_claim = by_id[role_current.provenance.claim_id]
        persona_claim = by_id[persona_current.provenance.claim_id]
        # Membership itself is identity-bearing. A missing/weak binding cannot establish that this
        # canonical person holds the selected product's committee role.
        if (
            role_claim.identity_binding is not IdentityBinding.STRONG
            or persona_claim.identity_binding is not IdentityBinding.STRONG
        ):
            return None

        role_value = role_claim.value_json
        if not isinstance(role_value, dict) or role_value.get("plausible") is False:
            return None
        role = str(role_value.get("role", ""))
        try:
            persona = Persona(str(persona_claim.value_json))
        except ValueError:
            return None
        if role != persona.value:
            return None

        selected: list[GovernedContactClaim] = []
        for field_key, contenders in by_field.items():
            current = merge_claims(contenders, None, merge_policy, now)
            if current is None:
                continue
            claim = by_id[current.provenance.claim_id]
            decision = use_decisions.get(claim.id)
            is_facet = field_key.startswith("contact.facet.")
            selected.append(
                GovernedContactClaim(
                    claim=claim,
                    use_decision=decision,
                    display_eligible=True,
                    personalization_eligible=(
                        is_facet
                        and claim.identity_binding is IdentityBinding.STRONG
                        and decision is not None
                        and decision.usable_for_outreach
                    ),
                )
            )
        selected.sort(key=lambda item: (str(item.claim.field_key), str(item.claim.id)))
        return GovernedCommitteeContact(
            contact_entity_id=contact_entity_id,
            account_entity_id=account_entity_id,
            persona=persona,
            role_on_committee=role,
            role_claim_id=role_claim.id,
            persona_claim_id=persona_claim.id,
            claims=tuple(selected),
            product_id=self._product_id,
            canonical_entity_version=canonical_entity_version,
        )


class ProductionHandoffCommitteeReader:
    """Production adapter satisfying both narrative committee protocols."""

    def __init__(self, resolver: ContactEligibilityResolver) -> None:
        self._resolver = resolver

    async def committee_for_handoff(
        self,
        *,
        account_entity_id: EntityId,
        workspace_id: str,
    ) -> tuple[HandoffCommitteeMember, ...]:
        contacts = await self._resolver.resolve_account(
            account_entity_id=account_entity_id,
            workspace_id=workspace_id,
        )
        members: list[HandoffCommitteeMember] = []
        for contact in contacts:
            displayed = contact.display_claims
            members.append(
                HandoffCommitteeMember(
                    member=CommitteeMember(
                        contact_entity_id=contact.contact_entity_id,
                        persona=contact.persona,
                        role_on_committee=contact.role_on_committee,
                        profile_claims=tuple(_as_profile_view(item.claim) for item in displayed),
                    ),
                    use_decisions={
                        item.claim.id: item.use_decision
                        for item in displayed
                        if item.use_decision is not None
                    },
                )
            )
        return tuple(members)

    async def committee_for(
        self,
        *,
        account_entity_id: EntityId,
        workspace_id: str,
    ) -> tuple[CommitteeContact, ...]:
        contacts = await self._resolver.resolve_account(
            account_entity_id=account_entity_id,
            workspace_id=workspace_id,
        )
        return tuple(
            CommitteeContact(
                contact_entity_id=contact.contact_entity_id,
                persona=contact.persona,
                role_on_committee=contact.role_on_committee,
                facets=tuple(
                    FacetHook(claim=item.claim, decision=item.use_decision)
                    for item in contact.display_claims
                    if str(item.claim.field_key).startswith("contact.facet.")
                ),
            )
            for contact in contacts
        )


class GovernedCommitteeViewReader:
    """C7 reference-only committee adapter over the shared eligibility resolver."""

    def __init__(self, resolver: ContactEligibilityResolver) -> None:
        self._resolver = resolver

    async def read_committee(
        self,
        request: ResearchViewReadRequest,
        subject: ResearchSubjectRef,
    ) -> ResearchSectionSeed:
        if request.product_id != self._resolver.product_id:
            return ResearchSectionSeed(
                kind=ResearchSectionKind.COMMITTEE,
                empty_availability=ResearchAvailability.RESTRICTED,
                reason_codes=("product_scope_mismatch",),
            )
        if subject.entity_type is EntityType.ACCOUNT:
            contacts = await self._resolver.resolve_account(
                account_entity_id=subject.entity_id,
                workspace_id=request.workspace_id,
            )
            relation = ResearchReferenceRelation.COMMITTEE_MEMBER
        else:
            assert subject.parent_account_id is not None
            contact = await self._resolver.resolve_contact(
                contact_entity_id=subject.entity_id,
                account_entity_id=subject.parent_account_id,
                workspace_id=request.workspace_id,
            )
            contacts = () if contact is None else (contact,)
            relation = ResearchReferenceRelation.SUBJECT

        references = tuple(
            ResearchOwnedReference(
                item_id=f"committee:{contact.contact_entity_id}:{self._resolver.project_run_id}",
                subject=ResearchSubjectRef(
                    entity_id=contact.contact_entity_id,
                    entity_type=EntityType.CONTACT,
                    canonical_entity_version=contact.canonical_entity_version,
                    parent_account_id=contact.account_entity_id,
                ),
                data_species=ResearchDataSpecies.COMMITTEE,
                relation=relation,
                owner_ref=f"committee:{self._resolver.project_run_id}:{contact.contact_entity_id}",
                product_id=contact.product_id,
                evidence_claim_ids=tuple(item.claim.id for item in contact.display_claims),
            )
            for contact in contacts
        )
        return ResearchSectionSeed(
            kind=ResearchSectionKind.COMMITTEE,
            references=references,
            empty_availability=ResearchAvailability.UNKNOWN,
            reason_codes=("no_eligible_committee_member",),
        )


def build_contact_eligibility_resolver(
    *,
    project_run_id: ProjectRunId,
    product_id: str | None,
    conn_factory: ConnFactory = transaction,
) -> ContactEligibilityResolver:
    return ContactEligibilityResolver(
        project_run_id=project_run_id,
        product_id=product_id,
        conn_factory=conn_factory,
    )


def build_production_handoff_committee_reader(
    resolver: ContactEligibilityResolver,
) -> ProductionHandoffCommitteeReader:
    return ProductionHandoffCommitteeReader(resolver)


def build_governed_committee_view_reader(
    resolver: ContactEligibilityResolver,
) -> GovernedCommitteeViewReader:
    return GovernedCommitteeViewReader(resolver)


__all__ = [
    "ContactEligibilityResolver",
    "GovernedCommitteeContact",
    "GovernedContactClaim",
    "GovernedCommitteeViewReader",
    "ProductionHandoffCommitteeReader",
    "build_contact_eligibility_resolver",
    "build_governed_committee_view_reader",
    "build_production_handoff_committee_reader",
]
