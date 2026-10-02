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

**R11.5 — where the committee's claim references come from.** The resolver used to read one source
only: ``account_run.references_index``, whose sole production writer is the R1-quarantined M8A/C
orchestrator.  Every real M8D run therefore resolved an empty committee, which starved C7/FI-2's
committee sections and made Lane E's value narrative refuse ``committee_unavailable`` on live data
(the ``[LaneE×R11/C7]`` HB-1 gap).  The fix is at the *reference source only* — see
:class:`ClaimReferenceSource` and :func:`default_claim_reference_source`.  Everything below the
source (the product-exact filter, contact liveness, survivor redirects, the use-decision gate,
merge, and the deterministic sort) is shared and unchanged, so the sources cannot drift into
several governance regimes.

**ARV2 R3 — the ARV2 lane leads that chain (founder ruling 2026-09-09).** ARV2's own rows are the
only truth for the accounts screens, and ARV2 records a committee as claims on the person:
:class:`Arv2CommitteeReferenceSource` reads them and answers first, with the two legacy sources
left behind it for accounts only the old lane ever researched.  It is a third *source*, nothing
more — the governance below it is the same shared code.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_coverage import (
    latest_account_research_run_id,
    read_account_coverage_in_run,
)
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
    claims_for_entities,
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


#: The prefix the M8D coverage ledger stamps on every claim reference it records.
_COVERAGE_CLAIM_PREFIX = "claim:"


def _coverage_claim_ids(claim_refs: Iterable[str]) -> tuple[ClaimId, ...]:
    """Parse ``claim:<uuid>`` coverage references, tolerating anything else.

    Deliberately as forgiving as :func:`_all_reference_ids`: the coverage ledger is a reference bag
    written by the research runtime, and a reference this reader cannot parse is one it must ignore
    rather than one that may break a committee read.
    """

    parsed: set[ClaimId] = set()
    for reference in claim_refs:
        try:
            parsed.add(ClaimId(UUID(reference.removeprefix(_COVERAGE_CLAIM_PREFIX))))
        except (TypeError, ValueError):
            continue
    return tuple(sorted(parsed, key=str))


class AccountClaimReferences(BaseModel):
    """The claim references one source holds for an account under a given project run.

    ``committee_member_ids`` is the membership axis, and ``None`` is meaningfully different from
    ``()``: ``None`` means *this source carries no membership list* (the legacy references index is
    itself a curated membership bag, so its claim set is self-scoping), while ``()`` means *this
    run resolved no committee member* and therefore admits nobody.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_ids: tuple[ClaimId, ...] = ()
    committee_member_ids: tuple[EntityId, ...] | None = None


class ClaimReferenceSource(Protocol):
    """Where a project run's committee claim references are read from (R11.5).

    A source returns ``None`` to mean "I do not apply to this project run" — which is what lets the
    chain below pick an authority — and an :class:`AccountClaimReferences` (possibly empty) to mean
    "I am the authority here, and this is the answer".  The distinction matters: an empty answer
    from the applicable source is an honest empty committee, never an invitation to consult a
    source the run has superseded.
    """

    async def read(
        self,
        conn: AsyncConnection,
        *,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        workspace_id: str,
    ) -> AccountClaimReferences | None: ...


class Arv2CommitteeReferenceSource:
    """ARV2 R3: the committee is whoever the claim store says holds a seat at this account.

    Founder ruling 2026-09-09 — ARV2's own rows are the only truth for the accounts screens. R3's
    committee step resolves a candidate, creates the contact entity under the account, and writes
    ``contact.persona`` / ``contact.role_on_committee`` / ``contact.current_title`` onto that
    person (strongly bound, citing the page that confirmed them). Those claims *are* the record of
    the committee — there is no separate membership ledger to consult, and this source reads no
    legacy table.

    Applicability is one question: does any live contact under this account hold a
    ``contact.persona`` claim? ``None`` when none does, which is what leaves the legacy sources in
    charge of an account only the old lane ever researched. When one does, this source is the
    authority for the account and hands the resolver every live claim of every seated contact —
    the seat pair the membership rule needs, plus the professional facts and facets the governed
    view is assembled from. Everything below the source (product-exact filtering, the
    strong-binding rule, the merge, the use-decision gate, the sort) is the shared governance, so
    the ARV2 answer is governed exactly like a coverage-sourced one.

    ``project_run_id`` is deliberately unused: an ARV2 committee claim is a fact about a person at
    an account, not a per-project-run artifact, so every project targeting the account reads the
    same seated people.
    """

    async def read(
        self,
        conn: AsyncConnection,
        *,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        workspace_id: str,
    ) -> AccountClaimReferences | None:
        # Merged losers included on purpose: a merge does not rewrite their immutable claims, so a
        # survivor whose facts all sit on a loser row would otherwise read as unseated. The
        # resolver redirects both the claims and the member ids through ``surviving_ids``.
        contacts = await contact_ids_for_account(conn, account_entity_id, include_merged=True)
        if not contacts:
            return None
        claims = await claims_for_entities(
            conn,
            list(contacts),
            scope=WorkspaceScope.for_workspace(workspace_id),
        )
        members = {claim.entity_id for claim in claims if str(claim.field_key) == PERSONA}
        if not members:
            return None
        return AccountClaimReferences(
            claim_ids=tuple(
                sorted((claim.id for claim in claims if claim.entity_id in members), key=str)
            ),
            committee_member_ids=tuple(sorted(members, key=str)),
        )


class EntityResearchCoverageReferenceSource:
    """M8D: the latest human-confirmed account-research fleet run's own coverage output.

    Applicability has two conditions, and the second is not pedantry.  The run must exist (R11 §6c
    latest-wins, workspace-scoped — resolved through the same shared rule the DEEP adapter and the
    verification selector use), **and** it must have published at least one coverage row.  A run
    that produced no coverage at all has not yet spoken about a single account, so treating it as
    the authority would silently blank a committee that a previous, completed pass legitimately
    resolved.  Once the run *has* published, it is the authority for every account in its
    selection: an account with no coverage row was not researched by it, and the honest answer is
    an empty committee rather than a fall-back to a source this run supersedes.

    Both conditions come from one statement (:func:`read_account_coverage_in_run`), and the run is
    resolved by id rather than as a whole supervised fleet row, so the bridge costs exactly one
    extra bounded lookup per ``resolve_account`` whichever source ends up answering.  That matters:
    this runs once per account on a committee surface whose composition path is query-budgeted.
    """

    async def read(
        self,
        conn: AsyncConnection,
        *,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        workspace_id: str,
    ) -> AccountClaimReferences | None:
        research_run_id = await latest_account_research_run_id(
            conn, UUID(str(project_run_id)), workspace_id=workspace_id
        )
        if research_run_id is None:
            return None
        lookup = await read_account_coverage_in_run(
            conn,
            research_run_id,
            account_entity_id=UUID(str(account_entity_id)),
            workspace_id=workspace_id,
        )
        if not lookup.run_has_coverage:
            return None
        if lookup.coverage is None:
            return AccountClaimReferences(committee_member_ids=())
        return AccountClaimReferences(
            claim_ids=_coverage_claim_ids(lookup.coverage.claim_refs),
            committee_member_ids=tuple(
                EntityId(value) for value in lookup.coverage.committee_member_ids
            ),
        )


class AccountRunReferenceIndexSource:
    """The legacy source: this project run's single ``account_run`` and its references index.

    Byte-identical to the pre-R11.5 read, including the "exactly one account run or nothing" rule —
    two account runs for one entity under one project run is an ambiguity this reader refuses to
    resolve, and zero is simply no research.  Historical and seeded runs keep resolving exactly the
    committee they did before the bridge existed.
    """

    async def read(
        self,
        conn: AsyncConnection,
        *,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        workspace_id: str,
    ) -> AccountClaimReferences | None:
        account_runs = await find_account_runs_for_entity(
            conn,
            project_run_id=project_run_id,
            entity_id=account_entity_id,
        )
        if len(account_runs) != 1:
            return AccountClaimReferences()
        return AccountClaimReferences(
            claim_ids=_all_reference_ids(account_runs[0].references_index)
        )


class ChainedClaimReferenceSource:
    """The first applicable source wins; no source applying is an empty committee."""

    def __init__(self, sources: Sequence[ClaimReferenceSource]) -> None:
        self._sources = tuple(sources)

    async def read(
        self,
        conn: AsyncConnection,
        *,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        workspace_id: str,
    ) -> AccountClaimReferences:
        for source in self._sources:
            found = await source.read(
                conn,
                project_run_id=project_run_id,
                account_entity_id=account_entity_id,
                workspace_id=workspace_id,
            )
            if found is not None:
                return found
        return AccountClaimReferences()


def default_claim_reference_source() -> ClaimReferenceSource:
    """ARV2 committee claims first, then M8D coverage, then the legacy references index.

    Order is the whole design, and ARV2 leads it (founder ruling 2026-09-09): an account whose
    committee the ARV2 lane has seated is described by that lane's own rows, and only an account
    it never seated falls through to the M8D coverage output, and then to what the retired
    orchestrator left behind.
    """

    return ChainedClaimReferenceSource(
        (
            Arv2CommitteeReferenceSource(),
            EntityResearchCoverageReferenceSource(),
            AccountRunReferenceIndexSource(),
        )
    )


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

    The project run's own research output is the product/run membership authority: claims from
    another project run are never considered even if they are newer current truth for the same
    contact.  Which durable record carries that output is the one thing R11.5 made pluggable
    (:class:`ClaimReferenceSource`) — M8D fleet coverage for a run that has it, the legacy
    ``account_run.references_index`` otherwise.  Every selected committee/contact claim must also
    have an exact ``product_id`` match (including ``None`` for legacy/product-neutral runs), so
    product A relevance cannot enter product B's handoff.
    """

    def __init__(
        self,
        *,
        project_run_id: ProjectRunId,
        product_id: str | None,
        conn_factory: ConnFactory = transaction,
        claim_reference_source: ClaimReferenceSource | None = None,
    ) -> None:
        self._project_run_id = project_run_id
        self._product_id = product_id
        self._conn_factory = conn_factory
        self._references = claim_reference_source or default_claim_reference_source()

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

            references = await self._references.read(
                conn,
                project_run_id=self._project_run_id,
                account_entity_id=account_entity_id,
                workspace_id=workspace_id,
            )
            if references is None:
                return ()

            referenced = await claims_by_ids(
                conn,
                references.claim_ids,
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
            # A source that carries a membership list (M8D coverage) additionally scopes the read to
            # it: a contact claim can be in the run's reference bag without that contact being on
            # the committee the run resolved. The member ids are redirected in the SAME call as the
            # claim ids — one query, and more importantly one redirect rule, so a member recorded
            # before an identity merge still matches the survivor its claims resolve to.
            members = references.committee_member_ids
            subjects = {claim.entity_id for claim in product_claims}
            redirects = await surviving_ids(
                conn,
                tuple(subjects if members is None else subjects | set(members)),
                EntityType.CONTACT,
                workspace_id=workspace_id,
            )
            member_scope: set[EntityId] | None = (
                None
                if members is None
                else {redirects[member] for member in members if member in redirects}
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
                if member_scope is not None and canonical_id not in member_scope:
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
    "AccountClaimReferences",
    "AccountRunReferenceIndexSource",
    "Arv2CommitteeReferenceSource",
    "ChainedClaimReferenceSource",
    "ClaimReferenceSource",
    "ContactEligibilityResolver",
    "EntityResearchCoverageReferenceSource",
    "GovernedCommitteeContact",
    "GovernedContactClaim",
    "GovernedCommitteeViewReader",
    "ProductionHandoffCommitteeReader",
    "build_contact_eligibility_resolver",
    "build_governed_committee_view_reader",
    "build_production_handoff_committee_reader",
    "default_claim_reference_source",
]
