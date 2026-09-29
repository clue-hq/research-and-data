"""The contacts under one account: the table and the contact page (contract v1, ARV2 E4/E5).

``GET /frontend/v1/accounts/{account_id}/contacts`` and
``GET /frontend/v1/accounts/{account_id}/contacts/{contact_id}``, plus the contact evidence stream
and the single-contact work-email lookup.

Both screens are served from the *same* people the account detail's committee card shows:
:func:`~clue_api.frontend_read.display_pages.committee` (D2's ``committee_members`` — the contacts
under this account that hold at least one live claim, ordered by persona rank then name) decides
membership and order once, so a marketer cannot see three contacts on the account and two in the
table. Nothing below re-derives a display rule — the title, the email chip, the persona tone, the
influence default and the labels all come from the shared helpers, and every personal claim passes
:func:`~clue_api.frontend_read.v1_shared.arv2_display_allowed` before it is rendered.

**E4 and E5 have deliberately different addressability rules.** A row's ``profileAction`` is
``"page"`` only for a committee member the read actually found claims for, while E5 serves any
contact **under this account** that holds a live claim or a written page section — research writes
about people the latest committee row does not list, and 404ing them would hide research the
platform paid for. The two are consistent in the direction that matters: every linked row is
servable; a servable contact may simply not be listed.

Every source is read in a fixed number of batched statements: a per-member lookup is what turns a
four-person table into nine statements, and is what the suite's statement-count guard prevents.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response
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
from clue_api.frontend_read.account_detail import AccountNotFound
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.contact_email_lookup import (
    ContactEmailLookupService,
    ContactEmailLookupView,
    EmailLookupTarget,
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
from clue_api.frontend_read.evidence_stream import (
    evidence_artifact_response,
    read_live_artifact,
)
from clue_api.frontend_read.v1_shared import (
    Influence,
    account_logo_path,
    contact_last_modified,
    current_position_start,
    custom_field_evidence_for,
    custom_fields_for,
    education_label,
    email_facts,
    iso_utc,
    linkedin_label,
    location_label,
    persona_display,
    persona_influence,
    persona_tone,
    research_evidence_for,
    tenure,
)
from clue_api.url_safety import safe_public_url
from clue_core import Claim, ClaimId, ContactEntity, EntityId, EntityType
from clue_db import ConnFactory
from clue_research.claimstore import (
    WorkspaceScope,
    claims_for_entities,
    current_values,
)
from clue_research.compliance import WorkspacePolicy, load_workspace_policy
from clue_research.identity import get_account, get_contact, get_contacts, surviving_id
from clue_research.profiling.committee import CURRENT_LOCATION
from clue_research.profiling.fields import FACET_ALMA_MATER, FACET_CAREER_HISTORY
from clue_storage import StorageBackend


class ContactNotFound(LookupError):
    """No servable contact with that id exists under this account in this workspace."""


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
        # The wire gets display text; the tone and the influence default keep reading the
        # vocabulary value beside it (D4-b decision 5). ``persona`` is required non-empty, and
        # :func:`_persona_of` never returns an empty string, so the fallback is unreachable.
        persona=persona_display(persona) or persona,
        persona_tone=persona_tone(persona),
        influence=_influence(displayable(latest.get(ROLE_KEY), policy), persona),
        email_status=facts.status,
        email_label=facts.label,
        socials=("linkedin",) if safe_public_url(linkedin) else (),
        profile_action="page" if has_page else "none",
    )


async def read_account_contacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
    project_id: str | None = None,
    context_id: uuid.UUID | None = None,
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
    members = await committee(
        conn,
        workspace_id=workspace_id,
        account_id=str(canonical),
        project_id=project_id,
        context_id=context_id,
    )
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
                has_page=bool(own) or member.membership_state is not None,
            )
        )
    rows = [
        row.model_copy(
            update={
                "membership_state": member.membership_state,
                "outreach_eligible": member.outreach_eligible,
                "membership_gaps": member.membership_gaps,
                **(
                    {"influence": None}
                    if member.membership_state not in (None, "supported")
                    else {}
                ),
                **(
                    {"persona": persona_display(member.persona) or "Needs verification"}
                    if member.membership_state
                    else {}
                ),
            }
        )
        for row, member in zip(rows, members, strict=True)
    ]
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
    """The follower count when it is a non-negative integer, from either shape the store holds.

    The registry sketch is ``{"followers": n}``; the provider's own record (what the answer key
    actually stores, found by the Zafran walk) nests it as ``{"network": {"followers_count": n}}``.
    Both are read; anything else — a string, a bool, a negative — is served as unknown.
    """
    value = None if claim is None else claim.value_json
    if not isinstance(value, dict):
        return None
    followers = value.get("followers")
    if followers is None:
        network = value.get("network")
        followers = network.get("followers_count") if isinstance(network, dict) else None
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
    if isinstance(value, dict):
        # The provider's own record (the answer key's shape, found by the Zafran walk): one flag
        # per badge — ``{"creator": true, "premium": true, "hiring": false, …}``.
        flag = value.get(_CREATOR_BADGE)
        return flag if isinstance(flag, bool) else None
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
                persona=persona_display(
                    _persona_of(displayable(latest.get((member.id, PERSONA_KEY)), policy))
                ),
            )
        )
    return tuple(refs)


def _same_entity(left: str, right: str) -> bool:
    """Whether two written entity ids name the same row (hyphenation and case are not identity)."""
    try:
        return uuid.UUID(left) == uuid.UUID(right)
    except (ValueError, AttributeError, TypeError):
        return False


async def read_contact_profile(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
    contact_id: uuid.UUID,
    display: DisplayPages,
    now: datetime,
    project_id: str | None = None,
    context_id: uuid.UUID | None = None,
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
    from clue_api.arv2.quality_read import select_quality_context

    selection = await select_quality_context(
        conn,
        workspace_id=workspace_id,
        subject_id=uuid.UUID(str(canonical_contact)),
        subject_kind="contact",
        account_id=uuid.UUID(str(canonical_account)),
        project_id=project_id,
        context_id=context_id,
    )
    if not _same_entity(subject.account_id, str(canonical_account)) and (
        selection is None or selection.scope is None
    ):
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
        project_id=project_id,
        context_id=context_id,
        account_id=uuid.UUID(str(canonical_account)),
        generate=bool(live),
    )
    if not live and not _has_stored_section(page) and selection is None:
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

    members = await committee(
        conn,
        workspace_id=workspace_id,
        account_id=str(canonical_account),
        project_id=project_id,
        context_id=context_id,
    )
    own_member = next((m for m in members if m.id == str(canonical_contact)), None)
    if selection is not None:
        row = row.model_copy(
            update={
                "membership_state": own_member.membership_state if own_member else "excluded",
                "membership_gaps": own_member.membership_gaps
                if own_member
                else ("Not in this project's committee.",),
                "outreach_eligible": bool(own_member and own_member.outreach_eligible),
                "persona": persona_display(own_member.persona) if own_member else "Excluded",
                **(
                    {"influence": None}
                    if not own_member or own_member.membership_state != "supported"
                    else {}
                ),
            }
        )
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

    custom_fields = await custom_fields_for(
        conn,
        workspace_id=workspace_id,
        account_ids=[canonical_contact],
        entity_kind="contact",
        policy=policy,
    )
    field_evidence = await custom_field_evidence_for(
        conn,
        workspace_id=workspace_id,
        subject_id=canonical_contact,
        entity_kind="contact",
        policy=policy,
    )
    evidence = list({record.claim_id: record for record in [*evidence, *field_evidence]}.values())

    # The account's mark-type logo, if it carries one (founder ruling 2026-09-11) — one small
    # neutral read, served through the platform's logo route like the accounts list does.
    account_logo = await current_values(
        conn,
        [EntityId(canonical_account)],
        ("core.logo_url",),
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    logo_value = account_logo.get((EntityId(canonical_account), "core.logo_url"))
    account_row = await get_account(conn, canonical_account)

    return AccountContactDetailResponseV1(
        data=AccountContactDetailV1(
            **row.model_dump(by_alias=False),
            account_id=str(canonical_account),
            account_name=account_name,
            account_logo_path=account_logo_path(
                canonical_account,
                None if logo_value is None else logo_value.value_json,
                domain=None if account_row is None else account_row.primary_domain,
                settings=display.settings,
            ),
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
            custom_fields=tuple(custom_fields.get(canonical_contact, ())),
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


async def _served_claim_ids(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_id: EntityId,
    display: DisplayPages,
    project_id: str | None = None,
    context_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
) -> frozenset[str]:
    """Every claim id this person's contact page actually serves evidence for.

    The same union :func:`read_contact_profile` composes into ``researchEvidence``: what the page
    cites, plus the two chips that find their evidence by claim id (ruling R5). Composing it here
    rather than calling the reader is what keeps this an authorisation check — ``generate=False``
    is load-bearing, so a GET that authorises can neither write a section nor schedule a rewrite,
    and is safe to retry.
    """
    page = await display.page(
        conn,
        workspace_id=workspace_id,
        subject_kind="contact",
        subject_id=str(contact_id),
        page=CONTACT_PAGE,
        project_id=project_id,
        context_id=context_id,
        account_id=account_id,
        generate=False,
    )
    served = set(page.cited_claim_ids)
    policy = await load_workspace_policy(conn, workspace_id=workspace_id)
    latest = _latest(
        _by_field(
            await claims_for_entities(
                conn,
                [contact_id],
                [WORK_EMAIL_KEY, CURRENT_LOCATION],
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
        )
    )
    email_claim_id = email_facts(displayable(latest.get(WORK_EMAIL_KEY), policy)).claim_id
    if email_claim_id is not None:
        served.add(email_claim_id)
    location_claim = displayable(latest.get(CURRENT_LOCATION), policy)
    # The reader only serves the location chip's claim id when the value actually renders a label,
    # so an unrenderable location authorises nothing here either.
    if location_claim is not None and location_label(location_claim.value_json) is not None:
        served.add(str(location_claim.id))
    served.update(
        row.claim_id
        for row in await custom_field_evidence_for(
            conn,
            workspace_id=workspace_id,
            subject_id=contact_id,
            entity_kind="contact",
            policy=policy,
        )
    )
    return frozenset(served)


def register_contact_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    evidence_storage: StorageBackend | None = None,
    contact_email_lookup: ContactEmailLookupService | None = None,
    allow_local_mutations: bool = False,
    display: DisplayPages,
) -> None:
    """Register the account-scoped contact routes on the `/frontend/v1` router.

    ``display`` is the D3 display seam the composition root shares across every endpoint that
    serves a generated page — one instance, so two screens looking at the same person schedule one
    rewrite between them. A ``?contract=`` query parameter is accepted and ignored: it selected
    between the FI-2 and v1 payloads until the FI-2 half was deleted (2026-09-09).
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
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        project_id: Annotated[str | None, Query(alias="projectId")] = None,
        context_id: Annotated[uuid.UUID | None, Query(alias="contextId")] = None,
    ) -> AccountContactsResponseV1:
        async with conn_factory() as conn:
            try:
                served = await read_account_contacts(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                    project_id=project_id,
                    context_id=context_id,
                )
                # Spec 2026-09-12 §2 "on open": the contacts tab is one of the three opens that
                # start the members' pages. Idempotent on the fleet; a seam without a queue is a
                # no-op here. The canonical (survivor) id, the same one the read resolved — a
                # merged loser's id names no committee.
                canonical, _name = await _resolve_account(
                    conn, workspace_id=workspace_id, account_id=account_id
                )
                await display.offer_contact_pages(
                    conn, workspace_id=workspace_id, account_id=str(canonical)
                )
                return served
            except AccountNotFound as exc:
                raise _account_404() from exc

    @router.get("/accounts/{account_id}/contacts/{contact_id}")
    async def get_contact_profile(
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
        contact_id: uuid.UUID,
        project_id: Annotated[str | None, Query(alias="projectId")] = None,
        context_id: Annotated[uuid.UUID | None, Query(alias="contextId")] = None,
    ) -> AccountContactDetailResponseV1:
        async with conn_factory() as conn:
            try:
                return await read_contact_profile(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                    contact_id=contact_id,
                    display=display,
                    now=datetime.now(UTC),
                    project_id=project_id,
                    context_id=context_id,
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
        project_id: Annotated[str | None, Query(alias="projectId")] = None,
        context_id: Annotated[uuid.UUID | None, Query(alias="contextId")] = None,
    ) -> Response:
        """Stream evidence only when this person's own contact page actually serves it."""

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
            survivor = await surviving_id(conn, EntityId(contact_id), EntityType.CONTACT)
            try:
                subject = await resolve_subject(
                    conn, workspace_id=workspace_id, kind="contact", subject_id=str(survivor)
                )
            except SubjectNotFound as exc:
                raise _evidence_404() from exc
            from clue_api.arv2.quality_read import select_quality_context

            selection = await select_quality_context(
                conn,
                workspace_id=workspace_id,
                subject_id=survivor,
                subject_kind="contact",
                account_id=canonical_account,
                project_id=project_id,
                context_id=context_id,
            )
            if not _same_entity(subject.account_id, str(canonical_account)) and (
                selection is None or selection.scope is None
            ):
                raise _evidence_404()
            served = await _served_claim_ids(
                conn,
                workspace_id=workspace_id,
                contact_id=survivor,
                display=display,
                project_id=project_id,
                context_id=context_id,
                account_id=canonical_account,
            )
            if str(claim_id) not in served:
                raise _evidence_404()
            typed_claim_id = ClaimId(claim_id)
            from clue_research.claimstore.quality import inspectable_claims_by_ids

            resolved = await inspectable_claims_by_ids(
                conn,
                workspace_id=workspace_id,
                claim_ids=[typed_claim_id],
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
        """Resolve the lookup subject, refusing anyone the contacts table does not list.

        The addressability rule is D2's committee — the contacts under this account that hold a
        live claim, which is exactly the set :func:`read_account_contacts` serves. A lookup is
        started from a row of that table, so a subject that is not on it is a 404 rather than a
        provider call the screen could never show the result of.
        """
        async with conn_factory() as conn:
            try:
                canonical_account, _account_name = await _resolve_account(
                    conn, workspace_id=workspace_id, account_id=account_id
                )
            except AccountNotFound as exc:
                raise _account_404() from exc
            canonical_contact = await surviving_id(conn, EntityId(contact_id), EntityType.CONTACT)
            members = await committee(
                conn, workspace_id=workspace_id, account_id=str(canonical_account)
            )
            if not any(_same_entity(member.id, str(canonical_contact)) for member in members):
                raise _contact_404()
            account = await get_account(conn, canonical_account)
            contact = await get_contact(conn, canonical_contact)
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
