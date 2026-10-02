"""A4 MACHINERY — who the page is about, who the committee is, and which claims each section gets.

Three jobs, all of them reads:

* :func:`resolve_subject` / :func:`client_context` turn ids into the two small objects the prompt's
  page header carries — the person or account being written about, and the client reading.
* :func:`committee_members` expands an account into the people an account page speaks about: every
  contact under the account that the store actually holds a live claim for, in persona-rank order.
* :func:`gather_section_inputs` is the filter. It reads the subject's live claims **once** and
  hands each section exactly the rows its recipe allows, with three exclusions applied and
  counted: special-category values never enter any section; ``outreach_safe=false`` rows enter
  only the restricted sections; and under a verifying posture an unverified tier-4 row is held
  back. Near-duplicates are folded (T2) and what survives is ordered deterministically.

Live claims, deliberately — not the merge. The merge answers "what is the current value of this
field"; a page shows *everything the research found*, several rows of the same field included.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.personas import persona_rank
from clue_api.arv2.display.recipes import SectionRecipe
from clue_api.arv2.display.render import DisplayClaim, dedupe_near_duplicates, display_claim
from clue_api.arv2.errors import Arv2Error
from clue_config import Settings
from clue_core import Claim, EntityId, UseClass, VerificationStatus
from clue_research.claimstore import claims_for_entities
from clue_research.claimstore.tenancy import WorkspaceScope

SubjectKind = Literal["account", "contact"]

#: The committee facts a :class:`SubjectRef` carries. Both are plain ``contact.*`` fields.
PERSONA_KEY = "contact.persona"
TITLE_KEY = "contact.current_title"

#: A claim on one of these prefixes is about a *person*; anything else is about the account.
_CONTACT_PREFIX = "contact."


class SubjectNotFound(Arv2Error):
    """The requested account or contact is not in this workspace (or does not exist)."""


@dataclass(frozen=True)
class SubjectRef:
    """Who a page is about, with the account it hangs under. Ids never reach the model."""

    kind: SubjectKind
    id: str
    name: str
    account_id: str
    account_name: str
    account_domain: str | None
    persona: str | None = None
    title: str | None = None
    membership_state: Literal["candidate", "supported", "needs_verification", "excluded"] | None = (
        None
    )
    membership_gaps: tuple[str, ...] = ()
    outreach_eligible: bool = False

    def to_prompt(self) -> dict[str, str]:
        """The ``subject`` object of the page header — names only, never an id or a domain."""
        payload: dict[str, str] = {"kind": self.kind, "name": self.name}
        if self.persona is not None:
            payload["persona"] = self.persona
        if self.title is not None:
            payload["title"] = self.title
        payload["account"] = self.account_name
        return payload


@dataclass(frozen=True)
class ClientContext:
    """Who is reading: the workspace's brand, and what the client sells (D2 decision 7)."""

    name: str
    what_we_sell: str

    def to_prompt(self) -> dict[str, str]:
        """The ``client`` object of the page header."""
        return {"name": self.name, "what_we_sell": self.what_we_sell}


@dataclass(frozen=True)
class SectionInput:
    """One section's claims, plus what was held back from it and why.

    The three counters are the section's honest account of its own gaps: a section that renders
    empty because every row was special-category reads differently from one the research never
    filled, and the writer's caller can say so.
    """

    recipe: SectionRecipe
    claims: tuple[DisplayClaim, ...]
    deduped: Mapping[str, str]
    excluded_sensitive: int = 0
    excluded_unsafe: int = 0
    excluded_unverified: int = 0

    @property
    def empty(self) -> bool:
        """No claim survived the filter — a real answer, and the prompt says so."""
        return not self.claims


# -- subjects -----------------------------------------------------------------------------------


_ACCOUNT_SQL = text(
    """
    SELECT id, canonical_name, primary_domain
    FROM account_entity
    WHERE id = :subject_id AND workspace_id = :workspace_id
    """
)

_CONTACT_SQL = text(
    """
    SELECT contact.id AS contact_id,
           contact.full_name,
           account.id AS account_id,
           account.canonical_name,
           account.primary_domain
    FROM contact_entity contact
    JOIN account_entity account ON account.id = contact.account_entity_id
    WHERE contact.id = :subject_id AND contact.workspace_id = :workspace_id
    """
)


def _as_uuid(subject_id: str, *, kind: str) -> uuid.UUID:
    try:
        return uuid.UUID(subject_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise SubjectNotFound(f"{kind} id {subject_id!r} is not an entity id") from exc


def _string_value(value: object, *, inner_key: str) -> str | None:
    """A claim value as a plain string: the string itself, or an older pack's wrapped object."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        inner = value.get(inner_key)
        if inner is None:
            return None
        rendered = str(inner).strip()
        return rendered or None
    return None


async def _committee_facts(
    conn: AsyncConnection, contact_ids: Sequence[EntityId], *, workspace_id: str
) -> dict[str, tuple[str | None, str | None]]:
    """``{contact id: (persona, title)}`` from each contact's latest live claim on those fields.

    ``claims_for_entities`` orders by ``field_key, collected_at DESC, id``, so the first row seen
    for a ``(contact, field)`` pair is the latest one.
    """
    if not contact_ids:
        return {}
    rows = await claims_for_entities(
        conn,
        list(contact_ids),
        [PERSONA_KEY, TITLE_KEY],
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    facts: dict[str, tuple[str | None, str | None]] = {}
    for claim in rows:
        entity = str(claim.entity_id)
        persona, title = facts.get(entity, (None, None))
        if str(claim.field_key) == PERSONA_KEY and persona is None:
            persona = _string_value(claim.value_json, inner_key="persona")
        elif str(claim.field_key) == TITLE_KEY and title is None:
            title = _string_value(claim.value_json, inner_key="title")
        facts[entity] = (persona, title)
    return facts


async def resolve_subject(
    conn: AsyncConnection, *, workspace_id: str, kind: SubjectKind, subject_id: str
) -> SubjectRef:
    """The account or contact ``subject_id`` names, or :class:`SubjectNotFound`.

    Workspace-scoped by construction: a row belonging to another workspace is *not found* here,
    the same fail-closed answer the toolbelt's account/contact guard gives.
    """
    entity = _as_uuid(subject_id, kind=kind)
    params = {"subject_id": entity, "workspace_id": workspace_id}
    if kind == "account":
        row = (await conn.execute(_ACCOUNT_SQL, params)).mappings().one_or_none()
        if row is None:
            raise SubjectNotFound(f"account {subject_id} is not in workspace {workspace_id!r}")
        return SubjectRef(
            kind="account",
            id=str(row["id"]),
            name=row["canonical_name"],
            account_id=str(row["id"]),
            account_name=row["canonical_name"],
            account_domain=row["primary_domain"],
        )

    row = (await conn.execute(_CONTACT_SQL, params)).mappings().one_or_none()
    if row is None:
        raise SubjectNotFound(f"contact {subject_id} is not in workspace {workspace_id!r}")
    contact_id = EntityId(row["contact_id"])
    persona, title = (await _committee_facts(conn, [contact_id], workspace_id=workspace_id)).get(
        str(contact_id), (None, None)
    )
    return SubjectRef(
        kind="contact",
        id=str(contact_id),
        name=row["full_name"] or "",
        account_id=str(row["account_id"]),
        account_name=row["canonical_name"],
        account_domain=row["primary_domain"],
        persona=persona,
        title=title,
    )


_BRAND_SQL = text(
    """
    SELECT name FROM brand
    WHERE workspace_id = :workspace_id
    ORDER BY created_at, brand_id
    LIMIT 1
    """
)

_WORKSPACE_SQL = text("SELECT name FROM workspace WHERE workspace_id = :workspace_id")


async def client_context(
    conn: AsyncConnection, *, workspace_id: str, settings: Settings
) -> ClientContext:
    """Who is reading the page: the workspace's first brand, else the workspace's own name.

    ``what_we_sell`` is configuration until Track O's company-overview artifact supplies it
    (D2 decision 7) — never guessed from claims.
    """
    params = {"workspace_id": workspace_id}
    name = (await conn.execute(_BRAND_SQL, params)).scalar_one_or_none()
    if name is None:
        name = (await conn.execute(_WORKSPACE_SQL, params)).scalar_one_or_none()
    return ClientContext(
        name=str(name) if name else workspace_id,
        what_we_sell=settings.arv2_display_client_pitch,
    )


# -- the committee ------------------------------------------------------------------------------


#: Every live contact under the account that the store actually holds a claim for. The claim
#: predicate is the workspace scope's own (public-footprint ∪ this workspace's private), never
#: ``claim.workspace_id`` alone — inside the subquery its unqualified column names bind to
#: ``claim``, which is the table the rule is about. A contact with no claims has nothing to say on
#: a page, and a merged loser is not a person: both are excluded.
_MEMBERS_TEMPLATE = """
    SELECT contact.id AS contact_id,
           contact.full_name,
           account.id AS account_id,
           account.canonical_name,
           account.primary_domain
    FROM contact_entity contact
    JOIN account_entity account ON account.id = contact.account_entity_id
    WHERE contact.account_entity_id = :account_id
      AND contact.workspace_id = :workspace_id
      AND contact.merged_into IS NULL
      AND EXISTS (
          SELECT 1 FROM claim
          WHERE claim.entity_id = contact.id
            AND claim.superseded_by IS NULL
            AND {scope_sql}
      )
"""


async def committee_members(
    conn: AsyncConnection, *, workspace_id: str, account_id: str
) -> list[SubjectRef]:
    """The people an account page speaks about, each with their persona and title.

    **The ARV2 committee, in one place.** The rule is the contacts under this account that hold at
    least one live claim, ordered by persona rank and then by name (founder ruling 2026-09-09:
    ARV2's own rows are the only truth, and the old research lane's coverage table is not one of
    them). The ordering lives here rather than at the read surface so the generated page and the
    committee card can never disagree about who is on the committee *or* in what order.

    R3 will give the committee rows of its own. When it does, this function is the single place
    that changes.
    """
    account = _as_uuid(account_id, kind="account")
    scope_sql, scope_params = WorkspaceScope.for_workspace(workspace_id).predicate()
    rows = [
        dict(row)
        for row in (
            await conn.execute(
                text(_MEMBERS_TEMPLATE.format(scope_sql=scope_sql)),
                {"workspace_id": workspace_id, "account_id": account, **scope_params},
            )
        ).mappings()
    ]

    contact_ids = [EntityId(uuid.UUID(str(row["contact_id"]))) for row in rows]
    facts = await _committee_facts(conn, contact_ids, workspace_id=workspace_id)
    members: list[SubjectRef] = []
    for row in rows:
        contact_id = str(row["contact_id"])
        persona, title = facts.get(contact_id, (None, None))
        members.append(
            SubjectRef(
                kind="contact",
                id=contact_id,
                name=str(row["full_name"] or ""),
                account_id=str(row["account_id"]),
                account_name=str(row["canonical_name"]),
                account_domain=(
                    str(row["primary_domain"]) if row["primary_domain"] is not None else None
                ),
                persona=persona,
                title=title,
            )
        )
    # Persona rank, then name — and then the id, so two namesakes on one committee still come back
    # in the same order on every read rather than in whatever order the planner returned them.
    members.sort(key=lambda member: (persona_rank(member.persona), member.name, member.id))
    return members


# -- the recipe input filter --------------------------------------------------------------------


def _is_sensitive(claim: Claim) -> bool:
    return claim.use_class is UseClass.SENSITIVE


def _is_unverified_synthesis(claim: Claim) -> bool:
    """Decision 1: under a verifying posture, an unverified tier-4 row is not shown."""
    return claim.source_tier == 4 and claim.verification_status is not VerificationStatus.VERIFIED


def _candidates(
    claims: Sequence[Claim],
    *,
    recipe: SectionRecipe,
    subject_entities: frozenset[str],
    contact_entities: frozenset[str],
    account_entities: frozenset[str],
) -> list[Claim]:
    """The claims this section may consider, before the exclusions.

    A restricted section is not a field recipe: it exists to show the operator every fact they must
    not use, so it takes **all** of the subject's unsafe rows, plus whatever its own keys allow.
    Everything else takes its keys only. ``contact.*`` keys resolve over the people of the page
    (the committee on an account page, the subject on a contact page); every other key resolves
    over the account.
    """
    allowed = frozenset(recipe.allowed_field_keys)
    picked: dict[str, Claim] = {}
    for claim in claims:
        entity = str(claim.entity_id)
        field_key = str(claim.field_key)
        if recipe.restricted and not claim.outreach_safe and entity in subject_entities:
            picked[str(claim.id)] = claim
            continue
        if field_key not in allowed:
            continue
        routed = contact_entities if field_key.startswith(_CONTACT_PREFIX) else account_entities
        if entity in routed:
            picked[str(claim.id)] = claim
    return list(picked.values())


def _dedupe_per_subject(
    claims: Sequence[DisplayClaim],
) -> tuple[list[DisplayClaim], dict[str, str]]:
    """Fold near-duplicates *within* one person (or the account), never across two of them.

    Two committee members legitimately hold the same certification, persona or title, and folding
    those rows would delete a person from the page rather than tidy it. The T2 fold groups by
    ``(field_key, outreach_safe)`` over whatever set it is given, so the subject grouping belongs
    here — this is where the page's people are known.
    """
    groups: dict[str | None, list[DisplayClaim]] = {}
    for claim in claims:
        groups.setdefault(claim.subject, []).append(claim)
    survivors: list[DisplayClaim] = []
    dropped: dict[str, str] = {}
    for group in groups.values():
        kept, folded = dedupe_near_duplicates(group)
        survivors.extend(kept)
        dropped.update(folded)
    return survivors, dropped


async def gather_section_inputs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject: SubjectRef,
    recipes: Sequence[SectionRecipe],
    people: Sequence[SubjectRef],
    settings: Settings,
) -> list[SectionInput]:
    """Every section's claims, from one workspace-scoped read of the subject's live claims.

    One read for the whole page (decision 5): the account, the subject, and — on an account page —
    every committee member, with no field filter, because a restricted section needs rows no recipe
    names. The per-recipe selection is then pure Python over those rows.
    """
    is_contact_page = subject.kind == "contact"
    account_entities = frozenset({subject.account_id})
    contact_entities = (
        frozenset({subject.id}) if is_contact_page else frozenset(person.id for person in people)
    )
    subject_entities = (
        frozenset({subject.id, subject.account_id}) if is_contact_page else account_entities
    )
    names: dict[str, str] = {person.id: person.name for person in people}
    if is_contact_page:
        names[subject.id] = subject.name

    entity_ids = [
        EntityId(uuid.UUID(value))
        for value in dict.fromkeys([*account_entities, *contact_entities, *subject_entities])
    ]
    claims = await claims_for_entities(
        conn, entity_ids, scope=WorkspaceScope.for_workspace(workspace_id)
    )

    sections: list[SectionInput] = []
    for recipe in recipes:
        candidates = _candidates(
            claims,
            recipe=recipe,
            subject_entities=subject_entities,
            contact_entities=contact_entities,
            account_entities=account_entities,
        )
        sensitive = unsafe = unverified = 0
        kept: list[DisplayClaim] = []
        for claim in candidates:
            if _is_sensitive(claim):
                sensitive += 1
                continue
            if settings.verification_enabled and _is_unverified_synthesis(claim):
                unverified += 1
                continue
            if not recipe.restricted and not claim.outreach_safe:
                unsafe += 1
                continue
            kept.append(display_claim(claim, subject=names.get(str(claim.entity_id))))
        survivors, dropped = _dedupe_per_subject(kept)
        survivors.sort(key=lambda c: (c.priority, c.field_key, c.collected_at, c.claim_id))
        sections.append(
            SectionInput(
                recipe=recipe,
                claims=tuple(survivors),
                deduped=dropped,
                excluded_sensitive=sensitive,
                excluded_unsafe=unsafe,
                excluded_unverified=unverified,
            )
        )
    return sections
