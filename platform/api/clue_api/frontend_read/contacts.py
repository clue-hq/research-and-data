"""FI-2 slice 1, Task 4 — the contacts union under one account.

``GET /frontend/v1/accounts/{account_id}/contacts`` and
``GET /frontend/v1/accounts/{account_id}/contacts/{contact_id}``: the buying committee of one
account, unioned across every project that targets it, served through the governed reader.

**This endpoint owns no eligibility logic.** It composes three existing authorities and translates
their verdicts to Band-2:

1. **membership** — ``project_account`` says which projects target this account, in the recorded
   first-add-wins order (element 0 is the primary project);
2. **committee membership + product/run scoping** — :class:`ContactEligibilityResolver`, one per
   targeting project, each bound to that project's ``(project_run, product)`` via
   :func:`~clue_api.frontend_read.account_detail.latest_project_run_context` — THE recorded
   per-project context rule, **imported, never re-derived**. The resolver is the FI-1 §4.5 ruling
   made structural: ``identity.contact_ids_for_account`` knows nothing about run membership,
   product scope, canonicalization or governance, so it is never used here. A member whose
   role/persona claim is not strongly bound, whose role is implausible, or whose contact row is
   erased does not come back — and this module does not second-guess that;
3. **display governance** — :func:`~clue_api.research_view_governance.display_allowed`, the *same*
   predicate C7 statement governance applies, imported rather than copied. A copy would be free to
   drift from the policy C7 enforces, which is the one thing a second read surface over the same
   personal data must not do.

**Two honest absences, and why only one of them is marked.** A field can be missing here for two
different reasons and the wire distinguishes them:

* the claim exists and is current, but the workspace policy refuses to *display* it (a
  special-category value, or a use-class this workspace does not show) → the value is **absent**
  and the slot carries ``restricted: true``. That is C7's ``ResearchAvailability.RESTRICTED``
  expressed at Band-2: no reason string, no leaked provider or timestamp, just "withheld";
* the claim is weakly bound, so the merge never promotes it to current truth (``can_be_promoted``)
  → there is no statement at all, and the field is simply **absent, unmarked**. Marking it
  ``restricted`` would report a research gap as a policy decision.

Neither path ever fabricates a value, and neither is a crash.

**What is deliberately not on the wire** (FI-1 G1–G4, reconciling the frontend's proposed contact
shape): no ``avatarUrl`` (G1 — no avatar pipeline exists and inventing one would mean scraping),
no ``socials`` array (G2 — LinkedIn is a resolved *identity strong key*, an X/Twitter handle is
not), no email address or email-status capability (G3 — this slice serves no channel data), and no
evidence URLs (G4 v1 — provenance chips are non-link). ``provider`` is the raw ``claim.source_key``:
no source display-name surface exists anywhere in the platform, and inventing a label map here
would be exactly the presentation mapping Band-2 forbids.

**``signals`` counts signal TYPES.** The chip is ``{"typeCount": n}`` — one per signal *field* that
currently holds a display-eligible statement, never one per item inside a list-valued facet (the
founder's 2026-08-08 unit ruling, FI-1 §9). The field is named for the unit it carries so a
frontend reading ``signals.count`` cannot quietly assume "five recent posts" where the backend
means "one signal type is present"; ``n`` is bounded by ``len(CONTACT_SIGNAL_FIELD_KEYS)``.

**Live-data reality.** ``resolve_account`` reads ``account_run.references_index``, whose only
production writer sits behind the M8D R1 quarantine, so on live data every committee is empty until
the R11 DEEP-phase bridge lands. An empty committee is therefore a 200 with an empty list — the
current production answer, and the correct one either way ("no committee researched yet" is not a
missing account).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.contact_eligibility import ContactEligibilityResolver, GovernedCommitteeContact
from clue_api.frontend_read.account_detail import AccountNotFound, latest_project_run_context
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.committee import (
    committee_member_displayable,
    current_claims,
    request_bound_conn_factory,
)
from clue_api.research_view_governance import display_allowed
from clue_core import (
    CONTACT_PROFESSIONAL_FIELD_KEYS,
    Claim,
    ContactEntity,
    EntityId,
    EntityType,
    Persona,
    reference_time,
)
from clue_db import ConnFactory
from clue_research.compliance import WorkspacePolicy, load_workspace_policy
from clue_research.identity import get_account, get_contacts, surviving_id
from clue_research.membership import ProjectMembership, memberships_for_accounts
from clue_research.profiling.committee import CURRENT_TITLE
from clue_research.profiling.fields import FACET_PUBLIC_APPEARANCES

#: ``contact.facet.recent_post`` is registered in ``claimstore.CORE_PACK`` (the two proof rows of
#: the facet field-class live there, not in the M8 facet pack) and has no exported constant, so the
#: key is named here; ``contact.facet.public_appearances`` does, and is imported.
FACET_RECENT_POST = "contact.facet.recent_post"

#: The facet families the row's ``signals`` chip counts (FI-1 G7) — the signal **types**, and the
#: ceiling on ``signals.typeCount``. This is a **display selection** over registered facet fields,
#: not a registry attribute — no field declares "I am a signal" — so it is enumerated here, at the
#: one place that renders it, rather than pretending to be derived.
#: Widening it is a one-tuple change; ``tests/api/test_frontend_read_contacts.py`` asserts both keys
#: still resolve to registered ``contact.facet.*`` fields, so a pack rename fails loudly instead of
#: silently counting zero forever.
CONTACT_SIGNAL_FIELD_KEYS: tuple[str, ...] = (FACET_RECENT_POST, FACET_PUBLIC_APPEARANCES)


class ContactNotFound(LookupError):
    """No governed committee member with that id exists under this account."""


# --- the wire vocabulary ----------------------------------------------------------------------


class RoleOnCommittee(WireModel):
    """The member's committee role and how confident the inference is.

    ``value`` is a :class:`~clue_core.Persona` value: the governed resolver refuses a member whose
    role and persona disagree, so the two are the same closed 4-value vocabulary, served raw.
    ``confidence`` is the role claim's own inference confidence (clamped by the M8.3 plausibility
    gate), ``null`` when the claim carries none — never a fabricated 1.0.
    """

    value: str
    confidence: float | None = None


class ContactSignals(WireModel):
    """How many signal **types** this member currently has a display-eligible statement for.

    ``typeCount``, not ``count``, because that is literally what it measures and the founder's
    2026-08-08 ruling fixed the unit: one display-eligible *field* counts once, whatever its value
    holds. A list-valued facet with five public appearances therefore contributes **1**, not 5 —
    ``5`` would need a per-item unit the ruling did not adopt. The ceiling is
    ``len(CONTACT_SIGNAL_FIELD_KEYS)``.

    A *statement* is the current value of a signal field — the same unit C7 governs — so the count
    is bounded by :data:`CONTACT_SIGNAL_FIELD_KEYS`, not by claim history. Counting superseded
    claims would report how often we looked, not how much we know; counting display-denied ones
    would leak the existence of exactly the data the policy withholds.
    """

    type_count: int


class GovernedFact(WireModel):
    """One professional field's current value — or its withheld slot.

    When ``restricted`` is true the value is absent and so are ``observedAt``/``provider``: the
    caller learns that a policy withheld something, and nothing more.
    """

    field_key: str
    value: JsonValue | None = None
    observed_at: datetime | None = None
    provider: str | None = None
    restricted: bool = False


class EvidenceChip(WireModel):
    """A non-link provenance chip (FI-1 G4 v1): which source, and when it stated it."""

    provider: str
    observed_at: datetime


class ContactRow(WireModel):
    """One governed committee member, as the contacts table renders them."""

    id: uuid.UUID
    name: str | None = None
    title: str | None = None
    # The scalar counterpart of :class:`GovernedFact`'s ``restricted``: ``title`` has no object slot
    # to carry a marker, so absence alone could not distinguish "withheld" from "unknown". A
    # deviation from the task plan's row sketch, recorded here because Task 5 copies the *as-built*
    # shape into the frontend contract.
    title_restricted: bool = False
    persona: Persona
    role_on_committee: RoleOnCommittee
    # The resolved identity strong key from ``contact_entity`` — not a claim, and the only social
    # link on the wire (G2). It is protected by the member's governed *existence*, not by a column
    # write: DSAR erasure tombstones the claims (role/persona included), and a member without a
    # current strongly-bound role/persona claim never comes back from the resolver, so this row is
    # never built for them. The column itself is NOT nulled by erasure (only ``verified_email`` is)
    # — the identity spine survives so a re-encounter still resolves rather than re-creating the
    # person the platform was asked to stop holding data about.
    linkedin_url: str | None = None
    project_ids: tuple[str, ...] = ()
    signals: ContactSignals


class ContactProfile(ContactRow):
    """One member's full profile: the row, plus account identity, facts and provenance."""

    account_id: uuid.UUID
    account_name: str
    professional_facts: tuple[GovernedFact, ...] = ()
    evidence: tuple[EvidenceChip, ...] = ()
    # Set when the requested contact id was a merged loser: the body is the survivor's.
    redirected_from: uuid.UUID | None = None


class ContactListMeta(WireModel):
    """``total`` is the whole committee: this list is not paginated (a committee is bounded by
    construction — four personas over one account — so a cursor would be ceremony)."""

    total: int


class ContactListResponse(WireModel):
    """``{data, meta}`` — the same envelope the accounts list serves."""

    data: tuple[ContactRow, ...]
    meta: ContactListMeta


# --- composition ------------------------------------------------------------------------------


class _CommitteeUnion:
    """Every governed member of this account, with the projects that target them.

    A member reached through several projects is held **once**, in their *primary* (first-add-wins)
    targeting project's governed view: that project's run decided which claims are in scope, and
    blending two runs' claim sets would risk showing product A's title beside product B's role.
    The projects are unioned; the claims are not.
    """

    def __init__(self) -> None:
        self.members: dict[EntityId, GovernedCommitteeContact] = {}
        self.project_ids: dict[EntityId, list[str]] = defaultdict(list)

    def add(self, member: GovernedCommitteeContact, *, project_id: str) -> None:
        self.members.setdefault(member.contact_entity_id, member)
        if project_id not in self.project_ids[member.contact_entity_id]:
            self.project_ids[member.contact_entity_id].append(project_id)


async def _resolve_account(
    conn: AsyncConnection, *, workspace_id: str, account_id: uuid.UUID
) -> tuple[EntityId, str]:
    """The account's canonical id and name, or :class:`AccountNotFound`.

    Merged losers follow ``surviving_id`` (matching the detail endpoint), and an unknown id is
    indistinguishable from another workspace's id so the path cannot probe a foreign id space.
    """
    canonical = await surviving_id(conn, EntityId(account_id), EntityType.ACCOUNT)
    account = await get_account(conn, canonical)
    if account is None or account.workspace_id != workspace_id:
        raise AccountNotFound(str(account_id))
    return canonical, account.canonical_name


async def _resolve_union(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    workspace_id: str,
    memberships: Sequence[ProjectMembership],
) -> _CommitteeUnion:
    # The resolver reads through the request's OWN connection, never a second one from the pool: a
    # request that already holds a pool connection and then asks for another (once per targeting
    # project) can self-deadlock on an exhausted pool under load — see
    # ``committee.request_bound_conn_factory``.
    bound = request_bound_conn_factory(conn)
    union = _CommitteeUnion()
    # Memberships only — deliberate, and an asymmetry worth naming: the account detail's
    # ``researchStatus``/``projectSections`` honestly surface a project that produced research on
    # this account *without* a membership row, but this union never visits such a project, so its
    # committee members can surface nowhere on this surface. That state should not occur (it is an
    # anomaly, not a mode); iterating research lineage instead would attribute one project's
    # committee to an account it does not target, which is the worse failure.
    for membership in memberships:
        context = await latest_project_run_context(
            conn, workspace_id=workspace_id, project_id=membership.project_id
        )
        if context is None:
            # A project that has never started a run has no committee context — its committee is
            # genuinely unknown, which is not the same as empty, and guessing another project's run
            # would attribute one project's research to another.
            continue
        resolver = ContactEligibilityResolver(
            project_run_id=context.project_run_id,
            product_id=context.product_id,
            conn_factory=bound,
        )
        for member in await resolver.resolve_account(
            account_entity_id=account_id, workspace_id=workspace_id
        ):
            union.add(member, project_id=membership.project_id)
    return union


def _role_confidence(member: GovernedCommitteeContact) -> float | None:
    """The role claim's own ``confidence``, or ``None`` — never the claim-level confidence, which
    is a source-quality score rather than the role inference's."""
    role = next(
        (item.claim for item in member.claims if item.claim.id == member.role_claim_id), None
    )
    value = role.value_json if role is not None else None
    confidence = value.get("confidence") if isinstance(value, dict) else None
    # ``bool`` is an ``int`` in Python; a boolean confidence would be a schema violation, and
    # rendering it as 1.0/0.0 would invent a number the inference never produced.
    return (
        float(confidence)
        if isinstance(confidence, int | float) and not isinstance(confidence, bool)
        else None
    )


def _professional_facts(
    claims: dict[str, Claim], policy: WorkspacePolicy
) -> tuple[GovernedFact, ...]:
    """The governed professional fields this member holds, in their registered order.

    Registered order (``CONTACT_PROFESSIONAL_FIELD_KEYS``) rather than alphabetical: the tuple is
    frozen in ``core`` and reads title → function → level → team → location → relationship, which is
    the fields' own declared order, not a display decision taken here.
    """
    facts: list[GovernedFact] = []
    for field_key in CONTACT_PROFESSIONAL_FIELD_KEYS:
        claim = claims.get(field_key)
        if claim is None:
            continue
        if not display_allowed(claim, policy):
            facts.append(GovernedFact(field_key=field_key, restricted=True))
            continue
        facts.append(
            GovernedFact(
                field_key=field_key,
                value=claim.value_json,
                observed_at=reference_time(claim),
                provider=claim.source_key,
            )
        )
    return tuple(facts)


def _signal_type_count(claims: dict[str, Claim], policy: WorkspacePolicy) -> int:
    """How many of the signal *fields* currently hold a display-eligible statement (one each)."""
    return sum(
        1
        for field_key in CONTACT_SIGNAL_FIELD_KEYS
        if (claim := claims.get(field_key)) is not None and display_allowed(claim, policy)
    )


def _evidence(claims: dict[str, Claim], policy: WorkspacePolicy) -> tuple[EvidenceChip, ...]:
    """One chip per distinct source backing something we actually showed, newest statement wins.

    "Display-eligible" here means the workspace-policy sense — :func:`display_allowed` over the
    resolver's current claims — not ``GovernedContactClaim.display_eligible``, which the resolver
    sets ``True`` on everything it selects and which therefore gates nothing on its own. A
    policy-withheld claim must not announce itself through its provenance, so it contributes no
    chip. One chip per provider (rather than per claim) because the chip answers "who told us
    this?", and repeating a source once per field would be noise, not provenance.
    """
    latest: dict[str, datetime] = {}
    for claim in claims.values():
        if claim.source_key is None or not display_allowed(claim, policy):
            continue
        at = reference_time(claim)
        known = latest.get(claim.source_key)
        if known is None or at > known:
            latest[claim.source_key] = at
    return tuple(
        EvidenceChip(provider=provider, observed_at=observed_at)
        for provider, observed_at in sorted(latest.items())
    )


def _build_row(
    member: GovernedCommitteeContact,
    *,
    entity: ContactEntity | None,
    project_ids: Sequence[str],
    claims: dict[str, Claim],
    policy: WorkspacePolicy,
) -> ContactRow:
    """The list row — and, via ``model_dump``, the shared half of the profile, so the two shapes
    cannot drift into disagreeing about the same member."""
    title_claim = claims.get(CURRENT_TITLE)
    shown = title_claim is not None and display_allowed(title_claim, policy)
    # ``contact.current_title`` is a registered ``str`` field. A non-string value would be a
    # registry violation, and rendering ``str(...)`` of whatever arrived would fabricate a title —
    # so it serves as unknown rather than as a stringified object.
    title = title_claim.value_json if shown and title_claim is not None else None
    return ContactRow(
        id=uuid.UUID(str(member.contact_entity_id)),
        name=None if entity is None else entity.full_name,
        title=title if isinstance(title, str) else None,
        title_restricted=title_claim is not None and not shown,
        persona=member.persona,
        role_on_committee=RoleOnCommittee(
            value=member.role_on_committee, confidence=_role_confidence(member)
        ),
        linkedin_url=None if entity is None else entity.linkedin_url,
        project_ids=tuple(project_ids),
        signals=ContactSignals(type_count=_signal_type_count(claims, policy)),
    )


# --- the read models --------------------------------------------------------------------------


async def read_account_contacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
) -> ContactListResponse:
    """The governed committee union for one account (empty when nothing has been researched)."""
    canonical, _name = await _resolve_account(
        conn, workspace_id=workspace_id, account_id=account_id
    )
    memberships = (
        await memberships_for_accounts(
            conn, workspace_id=workspace_id, account_ids=[uuid.UUID(str(canonical))]
        )
    ).get(uuid.UUID(str(canonical)), ())
    union = await _resolve_union(
        conn,
        account_id=canonical,
        workspace_id=workspace_id,
        memberships=memberships,
    )
    policy = await load_workspace_policy(conn, workspace_id=workspace_id)
    entities = await get_contacts(conn, tuple(union.members))

    rows = [
        _build_row(
            member,
            entity=entities.get(contact_id),
            project_ids=union.project_ids[contact_id],
            claims=current_claims(member),
            policy=policy,
        )
        for contact_id, member in union.members.items()
        if committee_member_displayable(member, policy)
    ]
    rows.sort(key=lambda row: (row.persona.value, str(row.id)))
    return ContactListResponse(data=tuple(rows), meta=ContactListMeta(total=len(rows)))


async def read_contact_profile(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> ContactProfile:
    """One member's profile, or :class:`ContactNotFound`.

    The URL is account-scoped, so committee membership *of this account* is the addressability rule:
    a contact row that exists but sits on no committee here is a 404, exactly like an unknown id.
    A merged **contact** follows ``surviving_id`` and is served with ``redirected_from`` set; a
    merged *account* in the URL is followed silently (``redirected_from`` stays ``None``), so a
    client correcting a stale account link must compare ``account_id`` with the id it asked for.
    """
    canonical_account, account_name = await _resolve_account(
        conn, workspace_id=workspace_id, account_id=account_id
    )
    canonical_contact = await surviving_id(conn, EntityId(contact_id), EntityType.CONTACT)
    memberships = (
        await memberships_for_accounts(
            conn, workspace_id=workspace_id, account_ids=[uuid.UUID(str(canonical_account))]
        )
    ).get(uuid.UUID(str(canonical_account)), ())
    union = await _resolve_union(
        conn,
        account_id=canonical_account,
        workspace_id=workspace_id,
        memberships=memberships,
    )
    member = union.members.get(canonical_contact)
    policy = await load_workspace_policy(conn, workspace_id=workspace_id)
    if member is None or not committee_member_displayable(member, policy):
        raise ContactNotFound(str(contact_id))

    claims = current_claims(member)
    row = _build_row(
        member,
        entity=(await get_contacts(conn, (canonical_contact,))).get(canonical_contact),
        project_ids=union.project_ids[canonical_contact],
        claims=claims,
        policy=policy,
    )
    return ContactProfile(
        **row.model_dump(),
        account_id=uuid.UUID(str(canonical_account)),
        account_name=account_name,
        professional_facts=_professional_facts(claims, policy),
        evidence=_evidence(claims, policy),
        redirected_from=None if canonical_contact == EntityId(contact_id) else contact_id,
    )


# --- the routes -------------------------------------------------------------------------------


def _account_404() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "ACCOUNT_NOT_FOUND", "message": "no such account in this workspace"},
    )


def register_contact_routes(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    """Register the two account-scoped contact routes on the `/frontend/v1` router."""

    @router.get("/accounts/{account_id}/contacts")
    async def list_account_contacts(
        workspace_id: WorkspaceDep, account_id: uuid.UUID
    ) -> ContactListResponse:
        async with conn_factory() as conn:
            try:
                return await read_account_contacts(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                )
            except AccountNotFound as exc:
                raise _account_404() from exc

    @router.get("/accounts/{account_id}/contacts/{contact_id}")
    async def get_contact_profile(
        workspace_id: WorkspaceDep, account_id: uuid.UUID, contact_id: uuid.UUID
    ) -> ContactProfile:
        async with conn_factory() as conn:
            try:
                return await read_contact_profile(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                    contact_id=contact_id,
                )
            except AccountNotFound as exc:
                raise _account_404() from exc
            except ContactNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "CONTACT_NOT_FOUND",
                        "message": "no such contact on this account's committee",
                    },
                ) from exc
