"""A project's accounts and buying committee, reduced to what Clue may write into a CRM
(CRM integration Phase 3, Task 4; rulings R-8.7, R-12.1, R-12.2, R-12.5, R-12.6).

:func:`project_targets` reads the project's accounts (merge losers left out), each account's fit
for **this** project, its committee (the ARV2 committee rule,
:func:`~clue_api.arv2.display.gather.committee_members_for_accounts`) and the few person fields the
personal-data rule allows: name, job title, buying role, a verified work email and the LinkedIn
profile. Every value carries the claim ids it came from, so a write can record them (R-8.7). A
value Clue holds but may not offer is named in the contact's ``withheld`` with the reason, in
plain words.

The person-data gate (R-12.5): a value comes only from a live claim that the read gate would serve
(:func:`~clue_api.arv2.read_tools.claim_gate_reason`: not sensitive, not marked unsafe for
outreach) and whose identity binding is not ``weak``. A work email is offered only when its
verdict is ``verified_smtp`` (R-12.2). The LinkedIn URL comes from the contact row, and only when
none of the contact's claims read here is a weak identity match. Phone numbers, interests, posts
and ``contact.facet.*`` are never read.

Only the latest **live** claim of a field is considered. A superseded or ``rejected`` claim is not
live: it is dropped before the latest is picked, so it is never offered and never hides an older
live claim (a rejection is the only mark the identity gate and a reviewer leave on a wrong-person
match). A field whose every claim was rejected is withheld as "rejected". A live claim that may not
be offered is not replaced by an older one: the newest live claim is what Clue currently knows.

Contacts are capped per page (``contacts_limit``); ``total_contacts`` says how many the page's
committees hold, and ``contacts_note`` says so in words when some were cut.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.gather import committee_members_for_accounts
from clue_api.arv2.read_tools import claim_gate_reason
from clue_api.crm.composio_gateway import CrmProvider
from clue_api.crm.write_actions import WRITE_ACTIONS
from clue_api.frontend_read.v1_shared import fit_band
from clue_config import Settings
from clue_core import Claim, EntityId, IdentityBinding, VerificationStatus
from clue_research.claimstore import claims_for_entities
from clue_research.claimstore.run_lineage import project_run_ids
from clue_research.claimstore.tenancy import WorkspaceScope

__all__ = [
    "ProjectTargets",
    "TargetAccount",
    "TargetContact",
    "TargetValue",
    "hubspot_buying_role",
    "hubspot_tier",
    "project_targets",
    "split_name",
]

FIT_KEY = "account.scoring.fit"
PERSONA_KEY = "contact.persona"
ROLE_KEY = "contact.role_on_committee"
TITLE_KEY = "contact.current_title"
EMAIL_KEY = "core.work_email"
_CONTACT_KEYS = (PERSONA_KEY, ROLE_KEY, TITLE_KEY, EMAIL_KEY)
#: How each field is named in ``withheld``. Persona and role both make the buying role.
_LABELS = {
    TITLE_KEY: "title",
    PERSONA_KEY: "buying role",
    ROLE_KEY: "buying role",
    EMAIL_KEY: "email",
}

#: The only work-email verdict Clue writes (R-12.2).
VERIFIED_EMAIL = "verified_smtp"

FitBand = Literal["high", "medium", "low"]
_BAND: dict[str, FitBand] = {"High": "high", "Medium": "medium", "Low": "low"}

#: R-12.1: Clue's fit band → HubSpot's ICP tier (values verified on a live portal).
_TIER_BY_BAND = {"High": "tier_1", "Medium": "tier_2", "Low": "tier_3"}

#: R-12.6: Clue's persona → HubSpot's buying role (verified against the portal's own options).
#: Salesforce has no standard field, so no role is offered there.
_HUBSPOT_BUYING_ROLE = {
    "champion": "CHAMPION",
    "economic_buyer": "BUDGET_HOLDER",
    "technical_evaluator": "INFLUENCER",
    "blocker": "BLOCKER",
    "user": "END_USER",
}

#: Why a claim is held back, in the words a person reads.
_REASON_WORDS = {
    "sensitive": "sensitive",
    "unverified": "not yet verified",
    "outreach_unsafe": "marked not safe for outreach",
    "weak": "identity not confirmed",
}

#: The most contacts one page returns.
MAX_TARGET_CONTACTS = 200

#: The CRM object an account is on each provider, as the write executor records it in
#: ``crm_record_link`` (the ``object`` of the provider's company/account create action:
#: HubSpot "company", Salesforce "account").
_ACCOUNT_OBJECT: dict[str, str] = {
    spec.provider: spec.object for spec in WRITE_ACTIONS.values() if spec.kind == "create_company"
}


@dataclass(frozen=True)
class TargetValue:
    value: str
    #: The claims the value came from; empty only for an entity column (name, domain, LinkedIn).
    claim_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class TargetAccount:
    account_entity_id: str
    name: str
    domain: str | None
    fit_band: FitBand | None
    #: Offered only on HubSpot, and only when the project scored the account (R-12.1).
    hubspot_icp_tier: TargetValue | None
    #: The CRM record this account already is on this connection, when Clue knows it.
    crm_record_id: str | None
    #: The fit Clue holds but may not use, and why ("fit: rejected").
    withheld: tuple[str, ...] = ()


@dataclass(frozen=True)
class TargetContact:
    contact_entity_id: str
    account_entity_id: str
    first_name: TargetValue | None
    last_name: TargetValue
    job_title: TargetValue | None
    #: Offered only on HubSpot (R-12.6); combining it with the roles the CRM contact already has
    #: is the writer's job.
    buying_role: TargetValue | None
    work_email: TargetValue | None
    linkedin_url: TargetValue | None
    #: Each field Clue holds but may not offer, and why ("email: not verified (catch_all_valid)").
    withheld: tuple[str, ...]
    crm_record_id: str | None


@dataclass(frozen=True)
class ProjectTargets:
    accounts: list[TargetAccount]
    contacts: list[TargetContact]
    #: The project's accounts (after ``account_ids``), of which ``accounts`` is one page.
    total_accounts: int
    #: The contacts the page's committees hold, of which ``contacts`` is at most
    #: ``contacts_limit``.
    total_contacts: int = 0
    #: Set, in plain words, when contacts were cut to the limit.
    contacts_note: str | None = None


def split_name(full_name: str) -> tuple[str | None, str]:
    """One word is a last name with no first name; otherwise the first word is the first name
    and the rest is the last name."""
    words = full_name.split()
    if len(words) <= 1:
        return None, " ".join(words)
    return words[0], " ".join(words[1:])


def hubspot_tier(fit: float | None, *, settings: Settings) -> str | None:
    """HubSpot's ICP tier for a fit score, from the same bands the screens use (R-12.1)."""
    band = fit_band(fit, settings=settings)
    return None if band is None else _TIER_BY_BAND[band]


def hubspot_buying_role(persona: str | None) -> str | None:
    """HubSpot's buying role for a Clue persona (R-12.6); ``None`` for no or an unknown persona."""
    return _HUBSPOT_BUYING_ROLE.get(persona or "")


# -- the reads ----------------------------------------------------------------------------------

_ACCOUNTS = """
    SELECT a.id, a.canonical_name, a.primary_domain, count(*) OVER () AS total
    FROM project_account pa
    JOIN account_entity a
      ON a.id = pa.account_entity_id AND a.workspace_id = pa.workspace_id
     AND a.merged_into IS NULL
    WHERE pa.workspace_id = :ws AND pa.project_id = :project{filter}
    ORDER BY a.created_at DESC, a.id DESC
    LIMIT :limit OFFSET :offset
"""

_COUNT = """
    SELECT count(*)
    FROM project_account pa
    JOIN account_entity a
      ON a.id = pa.account_entity_id AND a.workspace_id = pa.workspace_id
     AND a.merged_into IS NULL
    WHERE pa.workspace_id = :ws AND pa.project_id = :project{filter}
"""

_LINKEDIN = text(
    "SELECT id, linkedin_url FROM contact_entity "
    "WHERE workspace_id = :ws AND id = ANY(CAST(:ids AS uuid[]))"
)

_LINKS = text(
    "SELECT clue_entity_id, crm_id FROM crm_record_link "
    "WHERE connection_id = :connection AND crm_object = :object "
    "AND clue_entity_id = ANY(CAST(:ids AS uuid[])) "
    "ORDER BY linked_at, crm_id"
)


async def project_targets(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    connection_id: UUID | None,
    provider: CrmProvider | None,
    settings: Settings,
    account_ids: Sequence[str] | None = None,
    include_contacts: bool = True,
    offset: int = 0,
    limit: int = 200,
    contacts_limit: int = MAX_TARGET_CONTACTS,
) -> ProjectTargets:
    """One page of the project's accounts and, with ``include_contacts``, their committees.

    ``account_ids`` narrows to those accounts (an id that is not the project's is not served;
    a malformed one raises :class:`ValueError`). Without a connection, no CRM record id is known;
    without a provider, no tier or buying role is offered.
    """
    params: dict[str, Any] = {"ws": workspace_id, "project": project_id}
    account_filter = ""
    if account_ids is not None:
        account_filter = " AND a.id = ANY(CAST(:ids AS uuid[]))"
        params["ids"] = [uuid.UUID(str(value)) for value in account_ids]
    rows = (
        await conn.execute(
            text(_ACCOUNTS.format(filter=account_filter)),
            {**params, "limit": limit, "offset": offset},
        )
    ).all()
    if not rows:
        # Past the last page (or nothing at all): the window count has no row to ride on.
        total = (
            await conn.execute(text(_COUNT.format(filter=account_filter)), params)
        ).scalar_one()
        return ProjectTargets(accounts=[], contacts=[], total_accounts=int(total))

    scope = WorkspaceScope.for_workspace(workspace_id)
    page_ids = [EntityId(uuid.UUID(str(row.id))) for row in rows]
    fits, fit_withheld = await _project_fits(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        account_ids=page_ids,
        scope=scope,
        settings=settings,
    )
    account_links = (
        await _links(conn, connection_id, _ACCOUNT_OBJECT[provider], page_ids)
        if provider is not None
        else {}
    )
    accounts: list[TargetAccount] = []
    for row in rows:
        account_id = str(row.id)
        fit = fits.get(account_id)
        score = _fit_score(fit)
        band = fit_band(score, settings=settings)
        tier = hubspot_tier(score, settings=settings)
        accounts.append(
            TargetAccount(
                account_entity_id=account_id,
                name=str(row.canonical_name),
                domain=str(row.primary_domain) if row.primary_domain is not None else None,
                fit_band=_BAND[band] if band is not None else None,
                hubspot_icp_tier=(
                    TargetValue(tier, (UUID(str(fit.id)),))
                    if provider == "hubspot" and tier is not None and fit is not None
                    else None
                ),
                crm_record_id=account_links.get(account_id),
                withheld=fit_withheld.get(account_id, ()),
            )
        )

    contacts: list[TargetContact] = []
    total_contacts = 0
    note: str | None = None
    if include_contacts:
        contacts, total_contacts = await _committee_contacts(
            conn,
            workspace_id=workspace_id,
            account_ids=[str(account_id) for account_id in page_ids],
            connection_id=connection_id,
            provider=provider,
            scope=scope,
            settings=settings,
            contacts_limit=contacts_limit,
        )
        if total_contacts > len(contacts):
            note = (
                f"Showing {len(contacts)} of the {total_contacts} committee contacts of these "
                "accounts. Read fewer accounts at a time (limit, or account_ids) to see the rest."
            )
    return ProjectTargets(
        accounts=accounts,
        contacts=contacts,
        total_accounts=int(rows[0].total),
        total_contacts=total_contacts,
        contacts_note=note,
    )


async def _project_fits(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    account_ids: Sequence[EntityId],
    scope: WorkspaceScope,
    settings: Settings,
) -> tuple[dict[str, Claim], dict[str, tuple[str, ...]]]:
    """Each account's latest live, offerable fit claim **for this project**, and for the accounts
    whose fit may not be used, why.

    A fit is project-relative: it is scored against the project's ICP, and a run is attributed to
    its project by ``run_lineage``. A fit another project scored is not this project's fit.
    """
    runs = set(await project_run_ids(conn, workspace_id=workspace_id, project_id=project_id))
    if not runs:
        return {}, {}
    latest: dict[str, Claim] = {}
    rejected: set[str] = set()
    for claim in await claims_for_entities(conn, list(account_ids), [FIT_KEY], scope=scope):
        entity = str(claim.entity_id)
        if claim.run_id not in runs:
            continue
        if not _live(claim):
            rejected.add(entity)
            continue
        # The first live row of an entity is its newest (``collected_at DESC``).
        latest.setdefault(entity, claim)
    fits: dict[str, Claim] = {}
    withheld: dict[str, tuple[str, ...]] = {
        entity: ("fit: rejected",) for entity in rejected if entity not in latest
    }
    for entity, claim in latest.items():
        reason = claim_gate_reason(claim, settings=settings)
        if reason is None:
            fits[entity] = claim
        else:
            withheld[entity] = (f"fit: {_REASON_WORDS.get(reason, reason)}",)
    return fits, withheld


def _fit_score(claim: Claim | None) -> float | None:
    if claim is None:
        return None
    value = claim.value_json
    raw = value.get("value") if isinstance(value, Mapping) else value
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


async def _links(
    conn: AsyncConnection, connection_id: UUID | None, crm_object: str, ids: Sequence[EntityId]
) -> dict[str, str]:
    """``{entity id: crm id}`` for the entities this connection already links (oldest link)."""
    if connection_id is None or not ids:
        return {}
    links: dict[str, str] = {}
    rows = await conn.execute(
        _LINKS,
        {"connection": connection_id, "object": crm_object, "ids": [UUID(str(i)) for i in ids]},
    )
    for row in rows:
        links.setdefault(str(row.clue_entity_id), str(row.crm_id))
    return links


def _live(claim: Claim) -> bool:
    """Not superseded and not rejected: the only claims a value may come from."""
    return (
        claim.superseded_by is None and claim.verification_status is not VerificationStatus.REJECTED
    )


def _withheld_reason(claim: Claim, *, settings: Settings) -> str | None:
    """Why ``claim`` may not be offered (R-12.5), or ``None`` when it may."""
    reason = claim_gate_reason(claim, settings=settings)
    if reason is None and claim.identity_binding is IdentityBinding.WEAK:
        reason = "weak"
    return None if reason is None else _REASON_WORDS.get(reason, reason)


def _text(value: object, *, inner_key: str) -> str | None:
    """A claim value as plain text: the string itself, or the wrapped object's ``inner_key``."""
    if isinstance(value, Mapping):
        value = value.get(inner_key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def _committee_contacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_ids: Sequence[str],
    connection_id: UUID | None,
    provider: CrmProvider | None,
    scope: WorkspaceScope,
    settings: Settings,
    contacts_limit: int,
) -> tuple[list[TargetContact], int]:
    """The page's committee contacts (at most ``contacts_limit``) and how many there are."""
    committees = await committee_members_for_accounts(
        conn, workspace_id=workspace_id, account_ids=account_ids
    )
    # Account page order, then the committee's own order (persona rank, name).
    members = [member for account in account_ids for member in committees.get(account, [])]
    # A person with no name cannot be written into a CRM: they are not a target.
    members = [member for member in members if member.name.strip()]
    total = len(members)
    members = members[:contacts_limit]
    if not members:
        return [], total
    contact_ids = [EntityId(uuid.UUID(member.id)) for member in members]
    linkedin = {
        str(row.id): row.linkedin_url
        for row in await conn.execute(
            _LINKEDIN, {"ws": workspace_id, "ids": [UUID(str(i)) for i in contact_ids]}
        )
    }
    links = await _links(conn, connection_id, "contact", contact_ids)
    claims_by_contact: dict[str, list[Claim]] = {}
    for claim in await claims_for_entities(conn, contact_ids, _CONTACT_KEYS, scope=scope):
        claims_by_contact.setdefault(str(claim.entity_id), []).append(claim)

    contacts: list[TargetContact] = []
    for member in members:
        claims = [claim for claim in claims_by_contact.get(member.id, []) if _live(claim)]
        rejected = {
            str(claim.field_key)
            for claim in claims_by_contact.get(member.id, [])
            if claim.verification_status is VerificationStatus.REJECTED
        }
        latest: dict[str, Claim] = {}
        for claim in claims:  # newest first within a field
            latest.setdefault(str(claim.field_key), claim)
        # A field (persona and role together for the buying role) whose every claim was
        # rejected is withheld as such; its value is never named.
        withheld = [
            f"{label}: rejected"
            for label in dict.fromkeys(_LABELS.values())
            if (label != "buying role" or provider == "hubspot")
            and any(_LABELS[key] == label for key in rejected)
            and not any(_LABELS[key] == label for key in latest)
        ]

        title_claim = _offered(latest, TITLE_KEY, "title", withheld, settings=settings)
        title = _text(title_claim.value_json, inner_key="title") if title_claim else None

        buying_role: TargetValue | None = None
        if provider == "hubspot":
            buying_role = _buying_role(latest, settings=settings, withheld=withheld)

        work_email: TargetValue | None = None
        email_claim = _offered(latest, EMAIL_KEY, "email", withheld, settings=settings)
        if email_claim is not None:
            value = email_claim.value_json
            address = _text(value, inner_key="address")
            status = value.get("status") if isinstance(value, Mapping) else None
            if address is not None and status == VERIFIED_EMAIL:
                work_email = TargetValue(address, (UUID(str(email_claim.id)),))
            elif address is not None:
                withheld.append(f"email: not verified ({status or 'no verification recorded'})")

        # LinkedIn needs at least one fact about this person that may be offered, and no weak
        # identity match among the live facts read: a URL with nothing confirming whose it is
        # is not offered.
        linkedin_value: TargetValue | None = None
        url = linkedin.get(member.id)
        if url:
            confirmed = [
                claim
                for claim in latest.values()
                if _withheld_reason(claim, settings=settings) is None
            ]
            if any(claim.identity_binding is IdentityBinding.WEAK for claim in claims):
                withheld.append("LinkedIn: identity not confirmed")
            elif not confirmed:
                withheld.append("LinkedIn: nothing confirmed about this person")
            else:
                linkedin_value = TargetValue(str(url), ())

        first, last = split_name(member.name)
        contacts.append(
            TargetContact(
                contact_entity_id=member.id,
                account_entity_id=member.account_id,
                first_name=TargetValue(first, ()) if first is not None else None,
                last_name=TargetValue(last, ()),
                job_title=(
                    TargetValue(title, (UUID(str(title_claim.id)),))
                    if title is not None and title_claim is not None
                    else None
                ),
                buying_role=buying_role,
                work_email=work_email,
                linkedin_url=linkedin_value,
                withheld=tuple(withheld),
                crm_record_id=links.get(member.id),
            )
        )
    return contacts, total


def _offered(
    latest: Mapping[str, Claim],
    field_key: str,
    label: str,
    withheld: list[str],
    *,
    settings: Settings,
) -> Claim | None:
    """The field's latest claim when it may be offered; otherwise ``None``, with the reason
    added to ``withheld``."""
    claim = latest.get(field_key)
    if claim is None:
        return None
    reason = _withheld_reason(claim, settings=settings)
    if reason is not None:
        withheld.append(f"{label}: {reason}")
        return None
    return claim


def _buying_role(
    latest: Mapping[str, Claim], *, settings: Settings, withheld: list[str]
) -> TargetValue | None:
    """The HubSpot buying role from the persona claim, else from the role-on-committee claim.

    Both claims that name the same persona are cited; a claim that may not be offered is never
    cited, and when every source is held back the role is withheld with the first reason.
    """
    sources: list[tuple[Claim, str | None]] = []
    persona_claim = latest.get(PERSONA_KEY)
    if persona_claim is not None:
        sources.append((persona_claim, _text(persona_claim.value_json, inner_key="persona")))
    role_claim = latest.get(ROLE_KEY)
    if role_claim is not None:
        sources.append((role_claim, _text(role_claim.value_json, inner_key="role")))
    reasons: list[str] = []
    usable: list[tuple[Claim, str]] = []
    for claim, persona in sources:
        reason = _withheld_reason(claim, settings=settings)
        if reason is not None:
            reasons.append(reason)
        elif persona is not None and hubspot_buying_role(persona) is not None:
            usable.append((claim, persona))
    if not usable:
        if reasons:
            withheld.append(f"buying role: {reasons[0]}")
        return None
    persona = usable[0][1]
    role = hubspot_buying_role(persona)
    assert role is not None
    cited = tuple(UUID(str(claim.id)) for claim, named in usable if named == persona)
    return TargetValue(role, cited)
