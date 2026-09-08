"""FI-2 slice 1, Task 4 — the contacts union under one account.

``GET /frontend/v1/accounts/{account_id}/contacts`` and
``GET /frontend/v1/accounts/{account_id}/contacts/{contact_id}``: the buying committee of one
account, unioned across every project that targets it, served through the governed reader.

**This endpoint owns no eligibility logic.** It composes three existing authorities and translates
their verdicts to Band-2:

1. **membership** — ``project_account`` says which projects target this account, in the recorded
   first-add-wins order (element 0 is the primary project);
2. **committee membership + product/run scoping** —
   :func:`~clue_api.frontend_read.committee.read_governed_committee`, the shared addressability seam
   used by Account detail, Contacts list and Contact detail. It owns the latest-run context,
   governed resolver and display-policy decision once; this module only projects its members;
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
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.gather import (
    PERSONA_KEY,
    TITLE_KEY,
    SubjectNotFound,
    SubjectRef,
    resolve_subject,
)
from clue_api.arv2.display.recipes import Page
from clue_api.auth_wiring import principal_from_request
from clue_api.client_context_binding import workspace_client_entity_id
from clue_api.contact_eligibility import GovernedCommitteeContact
from clue_api.frontend_read.account_detail import AccountNotFound
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import ContractDep, WorkspaceDep
from clue_api.frontend_read.committee import (
    current_claims,
    read_governed_committee,
)
from clue_api.frontend_read.contact_email_lookup import (
    ContactEmailLookupService,
    ContactEmailLookupView,
    EmailLookupTarget,
    latest_contact_email_lookups,
)
from clue_api.frontend_read.contract_v1 import (
    AccountContactDetailResponseV1,
    AccountContactDetailV1,
    AccountContactsMeta,
    AccountContactsResponseV1,
    AccountContactSummaryV1,
    ResearchContactReference,
    ResearchDisplayBlock,
)
from clue_api.frontend_read.display_pages import (
    DEFAULT_PERSONA,
    ROLE_KEY,
    WORK_EMAIL_KEY,
    DisplayPages,
    PageRead,
    committee,
    committee_claims,
    displayable,
    title_of,
)
from clue_api.frontend_read.evidence import (
    EvidenceReference,
    evidence_artifact_response,
    evidence_reference,
    live_artifact_claim_ids,
    read_live_artifact,
)
from clue_api.frontend_read.prose import CONTACT_OVERVIEW_FIELD, ProseRead, read_prose
from clue_api.frontend_read.v1_shared import (
    Influence,
    contact_last_modified,
    current_position_start,
    education_label,
    email_facts,
    iso_utc,
    linkedin_label,
    location_label,
    persona_influence,
    persona_tone,
    research_evidence_for,
    tenure,
)
from clue_api.research_view_governance import display_allowed, safe_public_url
from clue_core import (
    CONTACT_PROFESSIONAL_FIELD_KEYS,
    Claim,
    ClaimId,
    ContactEntity,
    EntityId,
    EntityType,
    Persona,
    reference_time,
)
from clue_db import ConnFactory
from clue_research.claimstore import (
    FieldFilters,
    FieldRegistryScope,
    WorkspaceScope,
    active_merge_policy,
    claims_by_ids,
    claims_for_entities,
    list_effective_fields,
    merge_claims,
)
from clue_research.compliance import WorkspacePolicy, load_workspace_policy
from clue_research.identity import get_account, get_contact, get_contacts, surviving_id
from clue_research.membership import memberships_for_accounts
from clue_research.profiling.committee import CURRENT_LOCATION, CURRENT_TITLE
from clue_research.profiling.fields import (
    FACET_ALMA_MATER,
    FACET_CAREER_HISTORY,
    FACET_PUBLIC_APPEARANCES,
)
from clue_storage import StorageBackend

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
    gate), ``null`` when the claim carries none — never a fabricated 1.0. ``reasoning`` is the
    agent-authored rationale from that same governed role claim, not a read-layer reconstruction.
    """

    value: str
    confidence: float | None = None
    reasoning: str | None = None


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
    claim_id: str | None = None
    value: JsonValue | None = None
    observed_at: datetime | None = None
    provider: str | None = None
    restricted: bool = False


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
    # Durable provider-observed email acquisition. ``None`` means the user has never requested a
    # lookup; addresses remain separate from canonical ``verified_email``.
    email_lookup: ContactEmailLookupView | None = None


class ContactProfile(ContactRow):
    """One member's full profile: the row, plus account identity, facts and provenance."""

    account_id: uuid.UUID
    account_name: str
    overview: ProseRead
    professional_facts: tuple[GovernedFact, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
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


async def _resolve_account(
    conn: AsyncConnection, *, workspace_id: str, account_id: uuid.UUID
) -> tuple[EntityId, str]:
    """The account's canonical id and name, or :class:`AccountNotFound`.

    Merged losers follow ``surviving_id`` (matching the detail endpoint), and an unknown id is
    indistinguishable from another workspace's id so the path cannot probe a foreign id space.
    """
    canonical = await surviving_id(conn, EntityId(account_id), EntityType.ACCOUNT)
    account = await get_account(conn, canonical)
    client_entity_id = await workspace_client_entity_id(conn, workspace_id=workspace_id)
    if account is None or account.workspace_id != workspace_id or canonical == client_entity_id:
        raise AccountNotFound(str(account_id))
    return canonical, account.canonical_name


def _role_on_committee(member: GovernedCommitteeContact) -> RoleOnCommittee:
    """Project the role claim's judgment without inventing confidence or reasoning."""

    role = next(
        (item.claim for item in member.claims if item.claim.id == member.role_claim_id), None
    )
    value = role.value_json if role is not None else None
    confidence = value.get("confidence") if isinstance(value, dict) else None
    rationale = value.get("rationale") if isinstance(value, dict) else None
    # ``bool`` is an ``int`` in Python; a boolean confidence would be a schema violation, and
    # rendering it as 1.0/0.0 would invent a number the inference never produced.
    role_confidence = (
        float(confidence)
        if isinstance(confidence, int | float) and not isinstance(confidence, bool)
        else None
    )
    role_reasoning = rationale.strip() if isinstance(rationale, str) and rationale.strip() else None
    return RoleOnCommittee(
        value=member.role_on_committee,
        confidence=role_confidence,
        reasoning=role_reasoning,
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
                claim_id=str(claim.id),
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


async def _evidence(
    conn: AsyncConnection,
    *,
    claims: dict[str, Claim],
    policy: WorkspacePolicy,
    workspace_id: str,
) -> tuple[EvidenceReference, ...]:
    """One evidence record per displayed current claim, never per provider bucket.

    Mapping the item to ``claim_id`` + ``field_key`` is what lets a reviewer tell which statement
    the span supports.  A policy-withheld claim contributes no record at all, so neither its value
    nor its provider, timestamp, URL, span, confidence, or retained-artifact existence leaks.
    """

    displayed = tuple(claim for claim in claims.values() if display_allowed(claim, policy))
    if not displayed:
        return ()
    artifact_claim_ids = await live_artifact_claim_ids(
        conn, claims=displayed, workspace_id=workspace_id
    )
    definitions = {
        str(item.field_def.field_key): item.field_def
        for item in await list_effective_fields(
            conn,
            scope=FieldRegistryScope.for_workspace(workspace_id),
            filters=FieldFilters(active=None),
            include_retired=True,
        )
    }
    now = datetime.now(UTC)
    merge_policy = active_merge_policy()
    references: list[EvidenceReference] = []
    for claim in sorted(displayed, key=lambda item: (str(item.field_key), str(item.id))):
        definition = definitions.get(str(claim.field_key))
        current = merge_claims(
            (claim,),
            None if definition is None else definition.freshness_ttl,
            merge_policy,
            now,
        )
        references.append(
            evidence_reference(
                claim,
                freshness=None if current is None else current.freshness_state,
                artifact_available=str(claim.id) in artifact_claim_ids,
            )
        )
    return tuple(references)


def _build_row(
    member: GovernedCommitteeContact,
    *,
    entity: ContactEntity | None,
    project_ids: Sequence[str],
    claims: dict[str, Claim],
    policy: WorkspacePolicy,
    email_lookup: ContactEmailLookupView | None = None,
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
        role_on_committee=_role_on_committee(member),
        linkedin_url=None if entity is None else entity.linkedin_url,
        project_ids=tuple(project_ids),
        signals=ContactSignals(type_count=_signal_type_count(claims, policy)),
        email_lookup=email_lookup,
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
    union, policy = await read_governed_committee(
        conn,
        account_id=canonical,
        workspace_id=workspace_id,
        memberships=memberships,
    )
    entities = await get_contacts(conn, tuple(union.members))
    email_lookups = await latest_contact_email_lookups(
        conn,
        workspace_id=workspace_id,
        contact_ids=tuple(uuid.UUID(str(item)) for item in union.members),
    )

    rows = [
        _build_row(
            member,
            entity=entities.get(contact_id),
            project_ids=union.project_ids[contact_id],
            claims=current_claims(member),
            policy=policy,
            email_lookup=email_lookups.get(uuid.UUID(str(contact_id))),
        )
        for contact_id, member in union.members.items()
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
    union, policy = await read_governed_committee(
        conn,
        account_id=canonical_account,
        workspace_id=workspace_id,
        memberships=memberships,
    )
    member = union.members.get(canonical_contact)
    if member is None:
        raise ContactNotFound(str(contact_id))

    claims = current_claims(member)
    overview = await read_prose(
        conn,
        entity_id=canonical_contact,
        field_key=CONTACT_OVERVIEW_FIELD,
        scope=WorkspaceScope.for_workspace(workspace_id),
        display_allowed=lambda claim: display_allowed(claim, policy),
    )
    row = _build_row(
        member,
        entity=(await get_contacts(conn, (canonical_contact,))).get(canonical_contact),
        project_ids=union.project_ids[canonical_contact],
        claims=claims,
        policy=policy,
        email_lookup=(
            await latest_contact_email_lookups(
                conn,
                workspace_id=workspace_id,
                contact_ids=(uuid.UUID(str(canonical_contact)),),
            )
        ).get(uuid.UUID(str(canonical_contact))),
    )
    return ContactProfile(
        **row.model_dump(),
        account_id=uuid.UUID(str(canonical_account)),
        account_name=account_name,
        overview=overview,
        professional_facts=_professional_facts(claims, policy),
        evidence=await _evidence(
            conn,
            claims=claims,
            policy=policy,
            workspace_id=workspace_id,
        ),
        redirected_from=None if canonical_contact == EntityId(contact_id) else contact_id,
    )


# --- contract v1 (ARV2 D3, E4/E5) --------------------------------------------------------------
#
# The ARV2 contacts table and contact page, served from the *same* people the account detail's
# committee card shows: :func:`~clue_api.frontend_read.display_pages.committee` decides membership
# and order (persona rank, then name) once, so a marketer cannot see three contacts on the account
# and two in the table. Nothing below re-derives a display rule — the title, the email chip, the
# persona tone, the influence default and the labels all come from the shared helpers.
#
# **E4 and E5 have deliberately different addressability rules.** A row's ``profileAction`` is
# ``"page"`` only for a committee member the read actually found claims for, while E5 serves any
# contact **under this account** that holds a live claim or a written page section — the answer
# key's non-committee people have real pages. The two are consistent in the direction that matters:
# every linked row is servable; a servable contact may simply not be listed.

#: The page the contact detail serves. Named so the reader and the evidence route cannot drift.
CONTACT_PAGE: Page = "contact"

#: The person's own facts the contact page's rail renders, beyond the committee four.
NETWORK_STATISTICS = "contact.network_statistics"
MEMBER_BADGES = "contact.member_badges"
REPORTS_TO = "contact.reports_to"
BEST_CHANNEL = "contact.facet.best_channel"

#: The three influence values the contract's ``influence`` Literal admits. A committee role claim
#: carrying anything else is ignored in favour of the persona default rather than served raw.
_INFLUENCE_VALUES: frozenset[str] = frozenset({"High", "Medium", "Low"})

#: A claim at or below this ``signal_priority`` is a *signal* for the header count (P1/P2).
_SIGNAL_PRIORITY_CEILING = 2

#: The badge that makes ``linkedinCreator`` true, matched case-insensitively inside the provider's
#: own badge value (a list of strings, or a single string).
_CREATOR_BADGE = "creator"

#: A contact with no safe LinkedIn URL still has a contact page, and ``linkedinUrl`` is a
#: **required** ``HttpUrl`` in contract v1 — so the chip points at the site root rather than at a
#: fabricated ``/in/<guessed-handle>`` (which would be a made-up profile) or the whole profile
#: 404ing over a missing link. Recorded as a D3 follow-up: the honest fix is to make the field
#: nullable in the next contract revision, which is a frontend change, not a backend one.
LINKEDIN_SITE_URL = "https://www.linkedin.com/"
LINKEDIN_SITE_LABEL = "LinkedIn"

_CONTACT_UPDATED_AT = text(
    """
    SELECT updated_at FROM contact_entity
    WHERE id = :contact_id AND workspace_id = :workspace_id
    """
)


def _by_field(claims: Sequence[Claim]) -> dict[str, list[Claim]]:
    """``field key -> that field's live claims, newest first``.

    ``claims_for_entities`` orders by ``field_key, collected_at DESC, id``, so each list is already
    newest-first and ``[0]`` is the latest — the same tie-break the merge itself uses.
    """
    grouped: dict[str, list[Claim]] = {}
    for claim in claims:
        grouped.setdefault(str(claim.field_key), []).append(claim)
    return grouped


def _latest(grouped: Mapping[str, list[Claim]]) -> dict[str, Claim]:
    """The newest live claim per field."""
    return {field_key: claims[0] for field_key, claims in grouped.items() if claims}


def _persona_of(claim: Claim | None) -> str:
    """The row's persona: this person's own displayable ``contact.persona``, else ``user``.

    One rule for both endpoints, and it is the display-gated form of the persona the account
    detail's committee card shows — a card and a table must not disagree about who someone is.
    ``user`` is the neutral member of the vocabulary: it claims no influence the claims do not.
    """
    value = None if claim is None else claim.value_json
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_PERSONA


def _influence(role_claim: Claim | None, persona: str) -> Influence:
    """The committee role's own ``influence`` when it carries one, else the persona default (S8)."""
    value = None if role_claim is None else role_claim.value_json
    stated = value.get("influence") if isinstance(value, dict) else None
    if isinstance(stated, str) and stated in _INFLUENCE_VALUES:
        return cast(Influence, stated)
    return persona_influence(persona)


def _summary_row(
    *,
    contact_id: str,
    name: str,
    latest: Mapping[str, Claim],
    entity: ContactEntity | None,
    policy: WorkspacePolicy,
    has_page: bool,
) -> AccountContactSummaryV1:
    """One contacts-table row — E4's whole payload, and the head of E5's.

    Shared by both endpoints on purpose: the contact page repeats the table row verbatim, and a
    second construction of it is a second place for the two screens to describe one person
    differently. ``avatarUrl`` is omitted (no avatar pipeline exists, D0 ruling G1) and ``socials``
    carries ``linkedin`` only when the *entity's* resolved strong key is a safe public URL.
    """
    persona = _persona_of(displayable(latest.get(PERSONA_KEY), policy))
    facts = email_facts(displayable(latest.get(WORK_EMAIL_KEY), policy))
    linkedin = None if entity is None else entity.linkedin_url
    return AccountContactSummaryV1(
        id=contact_id,
        name=name,
        title=title_of(displayable(latest.get(TITLE_KEY), policy)),
        persona=persona,
        persona_tone=persona_tone(persona),
        influence=_influence(displayable(latest.get(ROLE_KEY), policy), persona),
        email_status=facts.status,
        email_label=facts.label,
        socials=("linkedin",) if safe_public_url(linkedin) else (),
        profile_action="page" if has_page else "none",
    )


async def read_account_contacts_v1(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
) -> AccountContactsResponseV1:
    """The account's contacts table in **contract v1** (decisions 2, 12, 13).

    The rows are the coverage committee in the screens' own order — persona rank, then name — read
    through the one shared :func:`~clue_api.frontend_read.display_pages.committee` builder, so this
    table and the account detail's committee card can never disagree about membership. Every row's
    facts come from ONE batched claim read over the whole committee: a per-member lookup here is
    what turns a four-person table into nine statements.

    An account whose research has published no committee is a 200 with an empty list — "nobody has
    been resolved yet" is not a missing account.
    """
    canonical, _name = await _resolve_account(
        conn, workspace_id=workspace_id, account_id=account_id
    )
    members = await committee(conn, workspace_id=workspace_id, account_id=str(canonical))
    if not members:
        return AccountContactsResponseV1(data=(), meta=AccountContactsMeta(total=0))

    policy = await load_workspace_policy(conn, workspace_id=workspace_id)
    latest = await committee_claims(conn, workspace_id=workspace_id, members=members)
    entities = await get_contacts(conn, [EntityId(uuid.UUID(member.id)) for member in members])

    rows: list[AccountContactSummaryV1] = []
    for member in members:
        own = {
            field_key: claim
            for (entity_id, field_key), claim in latest.items()
            if entity_id == member.id
        }
        entity = entities.get(EntityId(uuid.UUID(member.id)))
        rows.append(
            _summary_row(
                contact_id=member.id,
                # Required non-empty in the contract: the committee row's own name, else the
                # entity's, else the id — ugly, but true, and better than an unnamed row.
                name=member.name or (entity.full_name if entity else None) or member.id,
                latest=own,
                entity=entity,
                policy=policy,
                # ``page`` is offered for a member this read actually found claims for. E5's
                # addressability rule is wider (any live claim, or a written section), so a linked
                # row is always servable — the reverse is deliberately not promised.
                has_page=bool(own),
            )
        )
    return AccountContactsResponseV1(data=tuple(rows), meta=AccountContactsMeta(total=len(rows)))


def _has_stored_section(page: PageRead) -> bool:
    """Whether this page has anything written on it at all.

    A section is ``empty`` when no block exists *or* the block said nothing, so this is the honest
    reading of "there is a page here": a stored block with no items and no intro is not a page a
    person can look at, and treating it as one would make a blank contact addressable.
    """
    sections = page.display_block.get("sections")
    rows = sections if isinstance(sections, list) else []
    return any(isinstance(section, Mapping) and not section.get("empty", True) for section in rows)


def _signal_count(claims: Sequence[Claim]) -> int:
    """How many of the person's live claims are outreach-usable signals (P1/P2)."""
    return sum(
        1
        for claim in claims
        if claim.signal_priority <= _SIGNAL_PRIORITY_CEILING and claim.outreach_safe
    )


def _recent_signals_label(count: int) -> str:
    """``"No signals yet"`` / ``"1 signal"`` / ``"n signals"`` — required non-empty in v1."""
    if count == 0:
        return "No signals yet"
    return "1 signal" if count == 1 else f"{count} signals"


def _linkedin(entity: ContactEntity | None) -> tuple[str, str]:
    """``(label, url)`` for the contact header's LinkedIn chip. See :data:`LINKEDIN_SITE_URL`."""
    url = None if entity is None else entity.linkedin_url
    if url is not None and safe_public_url(url):
        return linkedin_label(url) or LINKEDIN_SITE_LABEL, url
    return LINKEDIN_SITE_LABEL, LINKEDIN_SITE_URL


def _followers(claim: Claim | None) -> int | None:
    """``contact.network_statistics.followers`` when it is a non-negative integer."""
    value = None if claim is None else claim.value_json
    followers = value.get("followers") if isinstance(value, dict) else None
    if isinstance(followers, bool) or not isinstance(followers, int) or followers < 0:
        return None
    return followers


def _creator_badge(claim: Claim | None) -> bool | None:
    """Whether the provider's badges name this person a creator; ``None`` when none were recorded.

    ``None`` rather than ``False`` for a missing claim: the contract's field is optional, and "we
    were never told" is a different answer from "the provider says they are not one".
    """
    if claim is None:
        return None
    value = claim.value_json
    if isinstance(value, str):
        return _CREATOR_BADGE in value.casefold()
    if isinstance(value, list):
        return any(isinstance(badge, str) and _CREATOR_BADGE in badge.casefold() for badge in value)
    return None


def _tenure_start(claims: Sequence[Claim], policy: WorkspacePolicy) -> date | None:
    """The start of the job this person is still in, from their newest usable career history.

    The newest displayable claim wins; a history stored as prose yields no date, so the next one is
    tried rather than the header losing its tenure to one unparseable row.
    """
    for claim in claims:
        if displayable(claim, policy) is None:
            continue
        start = current_position_start(claim.value_json)
        if start is not None:
            return start
    return None


def _string_fact(claim: Claim | None) -> str | None:
    """A declared-``str`` claim as the non-empty string it is; never a stringified object."""
    value = None if claim is None else claim.value_json
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _reports(
    *,
    contact_id: str,
    account_id: str,
    members: Sequence[SubjectRef],
    latest: Mapping[tuple[str, str], Claim],
    policy: WorkspacePolicy,
) -> tuple[ResearchContactReference, ...]:
    """The committee members whose ``contact.reports_to`` names this person, in committee order."""
    refs: list[ResearchContactReference] = []
    for member in members:
        if member.id == contact_id:
            continue
        claim = displayable(latest.get((member.id, REPORTS_TO)), policy)
        value = None if claim is None else claim.value_json
        target = value.get("contact_id") if isinstance(value, dict) else None
        if not isinstance(target, str) or not _same_entity(target, contact_id):
            continue
        refs.append(
            ResearchContactReference(
                account_id=account_id,
                contact_id=member.id,
                name=member.name or member.id,
                title=title_of(displayable(latest.get((member.id, TITLE_KEY)), policy)),
                persona=_persona_of(displayable(latest.get((member.id, PERSONA_KEY)), policy)),
            )
        )
    return tuple(refs)


def _same_entity(left: str, right: str) -> bool:
    """Whether two written entity ids name the same row (hyphenation and case are not identity)."""
    try:
        return uuid.UUID(left) == uuid.UUID(right)
    except (ValueError, AttributeError, TypeError):
        return False


async def read_contact_profile_v1(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
    contact_id: uuid.UUID,
    display: DisplayPages,
    now: datetime,
) -> AccountContactDetailResponseV1:
    """One contact page in **contract v1** (decisions 13, 14), or :class:`ContactNotFound`.

    **Addressability is wider than the committee** (the E5 ruling): a contact that sits under this
    account in this workspace and holds at least one live claim — or one written page section — has
    a page, whether or not the latest coverage row put them on the committee. The answer key's
    non-committee people are real people the research wrote about, and 404ing them would hide
    research the platform paid for. A contact with neither claims nor a page is the honest 404.

    A merged **contact** is followed silently (this contract has no ``redirectedFrom`` slot), and so
    is a merged account, exactly as the v1 account detail does.

    ``display.page`` is asked to generate only when the person has claims to write from: a
    claimless subject has nothing any section could say, so paying a model to discover that would
    be spend with a known answer.
    """
    canonical_account, account_name = await _resolve_account(
        conn, workspace_id=workspace_id, account_id=account_id
    )
    canonical_contact = await surviving_id(conn, EntityId(contact_id), EntityType.CONTACT)
    try:
        subject = await resolve_subject(
            conn, workspace_id=workspace_id, kind="contact", subject_id=str(canonical_contact)
        )
    except SubjectNotFound as exc:
        raise ContactNotFound(str(contact_id)) from exc
    if not _same_entity(subject.account_id, str(canonical_account)):
        raise ContactNotFound(str(contact_id))

    live = await claims_for_entities(
        conn, [canonical_contact], scope=WorkspaceScope.for_workspace(workspace_id)
    )
    page = await display.page(
        conn,
        workspace_id=workspace_id,
        subject_kind="contact",
        subject_id=str(canonical_contact),
        page=CONTACT_PAGE,
        generate=bool(live),
    )
    if not live and not _has_stored_section(page):
        raise ContactNotFound(str(contact_id))

    policy = await load_workspace_policy(conn, workspace_id=workspace_id)
    grouped = _by_field(live)
    latest = _latest(grouped)
    entity = (await get_contacts(conn, (canonical_contact,))).get(canonical_contact)
    updated_at = (
        await conn.execute(
            _CONTACT_UPDATED_AT,
            {"contact_id": canonical_contact, "workspace_id": workspace_id},
        )
    ).scalar_one()

    row = _summary_row(
        contact_id=str(canonical_contact),
        name=subject.name or (entity.full_name if entity else None) or str(canonical_contact),
        latest=latest,
        entity=entity,
        policy=policy,
        # The page this request is serving: reaching here IS the proof it is addressable.
        has_page=True,
    )

    members = await committee(conn, workspace_id=workspace_id, account_id=str(canonical_account))
    member_facts = await committee_claims(
        conn,
        workspace_id=workspace_id,
        members=members,
        field_keys=(TITLE_KEY, PERSONA_KEY, REPORTS_TO),
    )

    email = email_facts(displayable(latest.get(WORK_EMAIL_KEY), policy))
    location_claim = displayable(latest.get(CURRENT_LOCATION), policy)
    location = None if location_claim is None else location_label(location_claim.value_json)
    location_claim_id = (
        str(location_claim.id) if location_claim is not None and location is not None else None
    )
    started = _tenure_start(grouped.get(FACET_CAREER_HISTORY, ()), policy)
    tenure_label, employment_started_at = (
        tenure(started, now=now.date()) if started is not None else (None, None)
    )
    linkedin_chip_label, linkedin_url = _linkedin(entity)
    # The drawer's ids: what the page cites, then the two chips that find their evidence by claim
    # id (ruling R5), deduped in that order so the page's own order leads.
    evidence = await research_evidence_for(
        conn,
        workspace_id=workspace_id,
        claim_ids=dict.fromkeys(
            (
                *page.cited_claim_ids,
                *(item for item in (email.claim_id, location_claim_id) if item is not None),
            )
        ),
    )

    return AccountContactDetailResponseV1(
        data=AccountContactDetailV1(
            **row.model_dump(by_alias=False),
            account_id=str(canonical_account),
            account_name=account_name,
            # No logo pipeline exists (D0 ruling S2): explicitly null, never a guessed path.
            account_logo_path=None,
            recent_signals_label=_recent_signals_label(_signal_count(live)),
            linkedin_label=linkedin_chip_label,
            linkedin_url=linkedin_url,
            email_verified_at=email.verified_at,
            email_claim_id=email.claim_id,
            location_label=location,
            location_claim_id=location_claim_id,
            best_first_channel_label=_string_fact(displayable(latest.get(BEST_CHANNEL), policy)),
            education_label=education_label(
                claim.value_json
                if (claim := displayable(latest.get(FACET_ALMA_MATER), policy)) is not None
                else None
            ),
            tenure_label=tenure_label,
            employment_started_at=employment_started_at,
            linkedin_followers=_followers(displayable(latest.get(NETWORK_STATISTICS), policy)),
            linkedin_creator=_creator_badge(displayable(latest.get(MEMBER_BADGES), policy)),
            reports=_reports(
                contact_id=str(canonical_contact),
                account_id=str(canonical_account),
                members=members,
                latest=member_facts,
                policy=policy,
            ),
            # The two slots the display layer replaced. ``overviewParagraphs`` is the dummy's
            # legacy prose and ``evidence`` its legacy per-source rows; ``contactDisplay`` and
            # ``researchEvidence`` are where this person's page and its provenance actually live.
            overview_paragraphs=(),
            evidence=(),
            research_evidence=tuple(evidence),
            # Always present, even when every section is empty: an all-empty block is still a
            # block, and the frontend renders the page grammar from it.
            contact_display=ResearchDisplayBlock.model_validate(page.display_block),
            last_modified_at=iso_utc(
                await contact_last_modified(
                    conn, contact_id=canonical_contact, updated_at=updated_at
                )
            ),
        )
    )


# --- the routes -------------------------------------------------------------------------------


def _account_404() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "ACCOUNT_NOT_FOUND", "message": "no such account in this workspace"},
    )


def _evidence_404() -> HTTPException:
    """The one answer the evidence route gives to every refusal.

    Unknown account, unknown contact, a claim this workspace cannot see, a claim with no retained
    blob and an unauthorised one are all the same 404: the caller learns nothing about which of
    them it was, so the route cannot be used to probe another workspace's ids.
    """
    return HTTPException(
        status_code=404,
        detail={"code": "EVIDENCE_NOT_FOUND", "message": "no such evidence in this workspace"},
    )


async def _v1_page_cites(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: EntityId,
    contact_id: uuid.UUID,
    claim_id: uuid.UUID,
    display: DisplayPages,
) -> bool:
    """Whether the v1 contact page for this person, under this account, cites ``claim_id``.

    ``generate=False`` is load-bearing: this asks only what the **stored** blocks cite, so a GET
    that authorises can neither write a section nor schedule a rewrite (and is safe to retry).
    """
    survivor = await surviving_id(conn, EntityId(contact_id), EntityType.CONTACT)
    try:
        subject = await resolve_subject(
            conn, workspace_id=workspace_id, kind="contact", subject_id=str(survivor)
        )
    except SubjectNotFound:
        return False
    if not _same_entity(subject.account_id, str(account_id)):
        return False
    page = await display.page(
        conn,
        workspace_id=workspace_id,
        subject_kind="contact",
        subject_id=str(survivor),
        page=CONTACT_PAGE,
        generate=False,
    )
    return str(claim_id) in page.cited_claim_ids


def register_contact_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    evidence_storage: StorageBackend | None = None,
    contact_email_lookup: ContactEmailLookupService | None = None,
    allow_local_mutations: bool = False,
    display: DisplayPages,
) -> None:
    """Register the two account-scoped contact routes on the `/frontend/v1` router.

    Two routes, two contracts each (the D3 ruling): ``?contract=v1`` selects the ARV2 contacts
    table and contact page, its absence keeps the FI-2 payloads byte-for-byte. ``display`` is the
    D3 display seam the composition root shares across every endpoint that serves a generated page
    — one instance, so two screens looking at the same person schedule one rewrite between them.
    """

    def _contact_404() -> HTTPException:
        return HTTPException(
            status_code=404,
            detail={
                "code": "CONTACT_NOT_FOUND",
                "message": "no such contact on this account's committee",
            },
        )

    @router.get("/accounts/{account_id}/contacts")
    async def list_account_contacts(
        workspace_id: WorkspaceDep, account_id: uuid.UUID, mode: ContractDep
    ) -> ContactListResponse | AccountContactsResponseV1:
        async with conn_factory() as conn:
            try:
                if mode == "v1":
                    return await read_account_contacts_v1(
                        conn,
                        workspace_id=workspace_id,
                        account_id=account_id,
                    )
                return await read_account_contacts(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                )
            except AccountNotFound as exc:
                raise _account_404() from exc

    @router.get("/accounts/{account_id}/contacts/{contact_id}")
    async def get_contact_profile(
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        contact_id: uuid.UUID,
        mode: ContractDep,
    ) -> ContactProfile | AccountContactDetailResponseV1:
        async with conn_factory() as conn:
            try:
                if mode == "v1":
                    return await read_contact_profile_v1(
                        conn,
                        workspace_id=workspace_id,
                        account_id=account_id,
                        contact_id=contact_id,
                        display=display,
                        now=datetime.now(UTC),
                    )
                return await read_contact_profile(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                    contact_id=contact_id,
                )
            except AccountNotFound as exc:
                raise _account_404() from exc
            except ContactNotFound as exc:
                raise _contact_404() from exc

    @router.get("/accounts/{account_id}/contacts/{contact_id}/evidence/{claim_id}")
    async def get_contact_evidence_artifact(
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        contact_id: uuid.UUID,
        claim_id: uuid.UUID,
    ) -> Response:
        """Stream evidence only while a current Contact read actually exposes it.

        "A current Contact read" is the **union** of both contracts while both are served: the
        FI-2 profile's own ``evidence`` rows, and the claim ids the v1 contact page cites. The two
        expose genuinely different sets — the FI-2 profile is committee-only and names no account
        claim, while a contact section legitimately speaks about the person's account — so
        authorising against one of them alone would make a citation chip the ARV2 page renders open
        onto a 404. The v1 half is consulted only after the FI-2 half declines, so an FI-2-only
        deployment pays nothing for it, and it is consulted with ``generate=False``: an
        authorisation check must never be a spend path, nor schedule one.
        """

        if evidence_storage is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "EVIDENCE_SERVICE_UNAVAILABLE",
                    "message": "retained evidence is temporarily unavailable",
                },
            )
        async with conn_factory() as conn:
            try:
                canonical_account, _account_name = await _resolve_account(
                    conn, workspace_id=workspace_id, account_id=account_id
                )
            except AccountNotFound as exc:
                raise _evidence_404() from exc
            try:
                profile: ContactProfile | None = await read_contact_profile(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                    contact_id=contact_id,
                )
            except ContactNotFound:
                # Not on this account's committee — the FI-2 profile is a 404 for them, but the v1
                # page below may still exist and cite this claim (the E5 addressability ruling).
                profile = None
            authorized = profile is not None and any(
                reference.claim_id == str(claim_id) and reference.protected_artifact_available
                for reference in profile.evidence
            )
            if not authorized:
                authorized = await _v1_page_cites(
                    conn,
                    workspace_id=workspace_id,
                    account_id=canonical_account,
                    contact_id=contact_id,
                    claim_id=claim_id,
                    display=display,
                )
            if not authorized:
                raise _evidence_404()
            typed_claim_id = ClaimId(claim_id)
            resolved = await claims_by_ids(
                conn,
                (typed_claim_id,),
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            claim = resolved.get(typed_claim_id)
            if claim is None:
                raise _evidence_404()
            artifact = await read_live_artifact(
                conn,
                claim=claim,
                workspace_id=workspace_id,
                storage=evidence_storage,
            )
            if artifact is None:
                raise _evidence_404()
            return evidence_artifact_response(artifact)

    def _requester(request: Request) -> str:
        principal = principal_from_request(request)
        if principal is not None:
            principal.require("research.launch")
            return principal.user_id
        if allow_local_mutations:
            return "local-development-user"
        raise HTTPException(
            status_code=401,
            detail={
                "code": "UNAUTHORIZED",
                "message": "an authenticated session is required for email lookup",
            },
        )

    async def _lookup_target(
        *, workspace_id: str, account_id: uuid.UUID, contact_id: uuid.UUID
    ) -> EmailLookupTarget:
        async with conn_factory() as conn:
            try:
                profile = await read_contact_profile(
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
            account = await get_account(conn, EntityId(profile.account_id))
            contact = await get_contact(conn, EntityId(profile.id))
        if account is None or contact is None or not contact.full_name or not contact.linkedin_url:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "EMAIL_LOOKUP_IDENTITY_INCOMPLETE",
                    "message": (
                        "this contact does not have the identity anchors required for lookup"
                    ),
                },
            )
        return EmailLookupTarget(
            workspace_id=workspace_id,
            account_id=uuid.UUID(str(account.id)),
            contact_id=uuid.UUID(str(contact.id)),
            full_name=contact.full_name,
            linkedin_url=contact.linkedin_url,
            account_name=account.canonical_name,
            primary_domain=account.primary_domain,
        )

    @router.post("/accounts/{account_id}/contacts/{contact_id}/email-lookup")
    async def start_contact_email_lookup(
        request: Request,
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        contact_id: uuid.UUID,
    ) -> ContactEmailLookupView:
        if contact_email_lookup is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "EMAIL_LOOKUP_UNAVAILABLE",
                    "message": "email enrichment is not configured for this environment",
                },
            )
        target = await _lookup_target(
            workspace_id=workspace_id, account_id=account_id, contact_id=contact_id
        )
        try:
            return await contact_email_lookup.start(target=target, requested_by=_requester(request))
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "EMAIL_LOOKUP_WITHHELD",
                    "message": "email lookup is unavailable for this contact",
                },
            ) from exc

    @router.post("/accounts/{account_id}/contacts/{contact_id}/email-lookup/{lookup_id}/poll")
    async def poll_contact_email_lookup(
        request: Request,
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        contact_id: uuid.UUID,
        lookup_id: uuid.UUID,
    ) -> ContactEmailLookupView:
        if contact_email_lookup is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "EMAIL_LOOKUP_UNAVAILABLE",
                    "message": "email enrichment is not configured for this environment",
                },
            )
        _requester(request)
        target = await _lookup_target(
            workspace_id=workspace_id, account_id=account_id, contact_id=contact_id
        )
        try:
            return await contact_email_lookup.poll(
                workspace_id=workspace_id,
                account_id=target.account_id,
                contact_id=target.contact_id,
                lookup_id=lookup_id,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "EMAIL_LOOKUP_NOT_FOUND",
                    "message": "no such email lookup for this contact",
                },
            ) from exc
