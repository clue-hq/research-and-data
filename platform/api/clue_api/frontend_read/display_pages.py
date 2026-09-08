"""The display seam — the generated page a read serves, and the committee the screens show.

D2 built the page machinery: :func:`~clue_api.arv2.display.page.ensure_page` writes the sections a
page is missing, :func:`~clue_api.arv2.display.blocks.stale_sections` says which of them the
research has since moved underneath. This module is the *read surface's* half of that contract, and
it exists because a browser request has three constraints a CLI does not.

1. **A read never fails because a model did.** ``ensure_page`` is a spend path: the provider can be
   out of credit, the network can flap, a reply can be unusable. Every one of those is caught here
   and answered with the page as it is stored, plus a named ``degraded_reason`` — an honestly empty
   section is a correct answer, a 500 on an accounts screen is not.
2. **A read never pays for a rewrite.** ``ensure_page`` is called with ``regenerate_stale=False``,
   always. A stale section is served exactly as it was written and repaired *afterwards*, on a
   background task, so the person waiting on the request pays for missing sections only — and the
   page they are looking at is never silently more expensive than the one before it.
3. **Construction cannot raise.** :func:`~clue_api.arv2.display.page.default_runner_factory`
   refuses to build without a key, which is right for a command (fail before touching a database)
   and wrong for a router (a keyless deployment must still serve stored pages). So the key is
   checked *here*, and a seam with no runner is a pure projection: it composes what is stored and
   calls nothing.

The committee builders below sit in the same module for one reason: they read the same people the
account pages are written about, through the same display predicate
(:func:`~clue_api.frontend_read.v1_shared.arv2_display_allowed`), so the committee card and the
generated page can never disagree about who is on the committee or what their title is.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.blocks import (
    LiveBlock,
    compose_display_block,
    live_blocks,
    stale_sections,
)
from clue_api.arv2.display.gather import (
    PERSONA_KEY,
    TITLE_KEY,
    SubjectKind,
    SubjectRef,
    committee_members,
    resolve_subject,
)
from clue_api.arv2.display.page import (
    RunnerFactory,
    default_runner_factory,
    ensure_page,
)
from clue_api.arv2.display.personas import persona_display, persona_label
from clue_api.arv2.display.recipes import Page, SectionRecipe, read_recipes
from clue_api.arv2.errors import Arv2Error, ProviderHalted, ProviderTransportError
from clue_api.frontend_read.contract_v1 import AccountContact, BuyingCommitteeMember
from clue_api.frontend_read.v1_shared import arv2_display_allowed, email_facts
from clue_api.research_view_governance import safe_public_url
from clue_config import Secrets, Settings
from clue_core import Claim, EntityId
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_research.claimstore import WorkspaceScope, claims_for_entities
from clue_research.compliance import WorkspacePolicy
from clue_research.identity import get_contacts

__all__ = [
    "COMMITTEE_FIELD_KEYS",
    "DEFAULT_PERSONA",
    "DEFAULT_WHY_THEY_MATTER",
    "DERIVED_ROLE_MARKER",
    "DERIVED_ROLE_RATIONALE_PHRASE",
    "ROLE_KEY",
    "UNKNOWN_TITLE",
    "WORK_EMAIL_KEY",
    "DisplayPages",
    "PageRead",
    "buying_committee",
    "committee",
    "committee_claims",
    "displayable",
    "rail_contacts",
    "title_of",
]

log = get_logger("clue_api.frontend_read.display")

#: The person's own committee facts, read in one statement. ``core.work_email`` is here rather than
#: in a second read because the email chip and the title live on the same card.
WORK_EMAIL_KEY = "core.work_email"
ROLE_KEY = "contact.role_on_committee"
COMMITTEE_FIELD_KEYS: tuple[str, ...] = (TITLE_KEY, PERSONA_KEY, WORK_EMAIL_KEY, ROLE_KEY)

#: ``title`` and ``whyTheyMatter`` are required non-empty strings in contract v1, so an unknown one
#: needs a *documented* placeholder rather than an invented value. The em dash is the dummy's own
#: empty-cell glyph; "Committee member" states exactly what is known — that the research put this
#: person on the committee and recorded no reason.
UNKNOWN_TITLE = "—"
DEFAULT_WHY_THEY_MATTER = "Committee member"

#: The persona a member carries when the research recorded none. ``user`` is the neutral member of
#: the vocabulary — it claims no influence the claims do not support.
DEFAULT_PERSONA = "user"

#: How a ``contact.role_on_committee`` row says its rationale was **derived from the persona**
#: rather than researched — the D1 answer-key loader's write marker and the phrase it plants in the
#: rationale itself. Stated here rather than imported because a read surface must not depend on a
#: seed loader; ``tests/api/test_frontend_read_display_pages_db.py`` pins both against the loader's
#: own constants, so the two cannot drift apart in silence.
DERIVED_ROLE_MARKER = "derived_role_from_persona"
DERIVED_ROLE_RATIONALE_PHRASE = "role derived from the committee persona"


@dataclass(frozen=True)
class PageRead:
    """One page as a read surface serves it, plus what this read actually did.

    ``display_block`` is the wire shape :func:`compose_display_block` produces — the whole page, in
    recipe order, stored sections and empty ones alike. ``generated`` names the sections this
    request wrote; ``stale`` names the ones the research has moved underneath (served as they are,
    repaired in the background); ``degraded_reason`` is the exception class name when generation
    was attempted and failed, and ``None`` on every healthy read — including a read that never had
    a runner to begin with, because "not configured to generate" is not a degradation.
    """

    display_block: dict[str, Any]
    cited_claim_ids: tuple[str, ...]
    generated: tuple[str, ...]
    stale: tuple[str, ...]
    degraded_reason: str | None


#: The failures a read absorbs. ``Arv2Error`` covers the lane's own typed failures (a halted or
#: unreachable provider are subclasses, named separately for legibility); ``OSError`` covers the
#: raw sink's filesystem; ``ValueError`` covers a reply the runner could not make sense of. A
#: database error is deliberately *not* here — it is not a display failure, and swallowing it
#: would serve a page composed from a transaction that is already broken.
_DEGRADING = (Arv2Error, ProviderHalted, ProviderTransportError, OSError, ValueError)


class DisplayPages:
    """The read surface's access to the D2 display layer: one instance per composed router.

    One instance, not one per request, because the in-flight regeneration table has to outlive the
    request that scheduled the work — that table is what makes "one rewrite per page, however many
    people are looking at it" true.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        secrets: Secrets | None,
        conn_factory: ConnFactory,
        runner_factory: RunnerFactory | None = None,
    ) -> None:
        self._settings = settings
        self._conn_factory = conn_factory
        self._runner_factory = (
            runner_factory
            if runner_factory is not None
            else _production_runner_factory(settings, secrets)
        )
        self._regenerating: dict[tuple[str, str, str, str], asyncio.Task[None]] = {}

    @property
    def generates(self) -> bool:
        """Whether this seam can write a page at all (a key is configured and generation is on)."""
        return self._runner_factory is not None

    # -- the page ------------------------------------------------------------------------------

    async def page(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        subject_kind: SubjectKind,
        subject_id: str,
        page: Page,
        generate: bool = True,
    ) -> PageRead:
        """This subject's page: stored sections always, missing ones written when we can.

        The expansion (a contact's account, an account's committee) is resolved **first**, before
        any spend, so a subject that does not exist raises
        :class:`~clue_api.arv2.display.gather.SubjectNotFound` rather than being paid for; the ids
        it yields are also what the staleness scan watches, since a section mixing account and
        contact keys goes stale when either side moves.

        ``generate=False`` makes this read a **pure projection with no side effects**, whatever the
        seam is configured to do: no ``ensure_page`` call, and no background rewrite scheduled
        either. It exists for callers that need to know what a page *says* without being a reason
        for it to be written — the evidence route asks this seam which claims the page cites in
        order to decide whether a caller may stream one, and an authorisation check must never be
        a spend path (nor a scheduler: a GET that authorises must be safe to retry). ``generated``
        is then empty and ``degraded_reason`` is ``None``, because nothing was attempted; ``stale``
        is still computed and reported, since saying so costs nothing and a caller may want to
        know. A read that *does* want the page repaired simply leaves ``generate`` at its default.
        """
        recipes = await read_recipes(conn, page, workspace_id=workspace_id)
        expansion = await _expansion(
            conn, workspace_id=workspace_id, subject_kind=subject_kind, subject_id=subject_id
        )

        generated: tuple[str, ...] = ()
        degraded_reason: str | None = None
        if generate and self._runner_factory is not None:
            try:
                result = await ensure_page(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    page=page,
                    settings=self._settings,
                    runner_factory=self._runner_factory,
                    regenerate_stale=False,
                )
            except _DEGRADING as exc:
                degraded_reason = type(exc).__name__
                log.warning(
                    "frontend_read.display.generation_failed",
                    workspace_id=workspace_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    page=page,
                    reason=degraded_reason,
                    error=str(exc),
                )
            else:
                generated = result.generated

        # Composed from the live rows in both paths — the generated one included. ``ensure_page``
        # composes the same way, and reading it back once here is what keeps the degraded page and
        # the healthy page the same object built by the same code.
        blocks = await live_blocks(
            conn,
            workspace_id=workspace_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            page=page,
        )
        stale = await stale_sections(
            conn,
            workspace_id=workspace_id,
            subject_ids=expansion,
            recipes=recipes,
            blocks=blocks,
        )
        stale_keys = tuple(entry.section_key for entry in stale)
        if stale_keys and generate:
            self.schedule_regeneration(
                workspace_id=workspace_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                page=page,
            )
        return PageRead(
            display_block=compose_display_block(page, recipes, blocks),
            cited_claim_ids=_cited(recipes, blocks),
            generated=generated,
            stale=stale_keys,
            degraded_reason=degraded_reason,
        )

    # -- background regeneration ---------------------------------------------------------------

    def schedule_regeneration(
        self,
        *,
        workspace_id: str,
        subject_kind: SubjectKind,
        subject_id: str,
        page: Page,
    ) -> bool:
        """Start the background rewrite of this page's stale sections; ``True`` if one started.

        The in-flight table is keyed by the page itself, so ten people opening the same account
        while a rewrite is running schedule **one** rewrite between them. It is deliberately an
        in-process table: a second web process would schedule its own, which costs one extra page
        and cannot corrupt anything (``insert_block`` retires and replaces under the live index in
        one transaction).
        """
        if self._runner_factory is None:
            return False
        key = (workspace_id, subject_kind, subject_id, page)
        running = self._regenerating.get(key)
        if running is not None and not running.done():
            return False
        self._regenerating[key] = asyncio.create_task(
            self._regenerate(
                key,
                workspace_id=workspace_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                page=page,
            )
        )
        return True

    async def _regenerate(
        self,
        key: tuple[str, str, str, str],
        *,
        workspace_id: str,
        subject_kind: SubjectKind,
        subject_id: str,
        page: Page,
    ) -> None:
        """Rewrite the stale sections on the seam's own connection, and never raise.

        Its own connection because the request's is long gone by the time this runs; ``transaction``
        commits on exit, so the rewrite lands or it does not — the reader that scheduled it has
        already been served either way. Every failure is logged and dropped: nothing is waiting on
        this, and the next read will simply find the same section stale and try again.
        """
        try:
            if self._runner_factory is None:  # pragma: no cover - guarded at the scheduler
                return
            async with self._conn_factory() as conn:
                await ensure_page(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    page=page,
                    settings=self._settings,
                    runner_factory=self._runner_factory,
                    regenerate_stale=True,
                )
        except Exception as exc:  # noqa: BLE001 - a background task may never escalate
            log.warning(
                "frontend_read.display.regeneration_failed",
                workspace_id=workspace_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                page=page,
                reason=type(exc).__name__,
                error=str(exc),
            )
        finally:
            self._regenerating.pop(key, None)

    async def drain(self) -> None:
        """Await every in-flight regeneration. For tests and shutdown, never for a request."""
        tasks = list(self._regenerating.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _production_runner_factory(settings: Settings, secrets: Secrets | None) -> RunnerFactory | None:
    """The runner a real deployment writes pages with, or ``None`` when it cannot write any.

    The two conditions are checked here rather than left to ``default_runner_factory`` because that
    function raises on a missing key by design (a command must fail before it opens a database) and
    a router must not: an unconfigured deployment serves stored pages instead of refusing to start.
    """
    if not settings.arv2_display_generate_on_read or secrets is None:
        return None
    key = secrets.openrouter_api_key
    if key is None or not key.get_secret_value().strip():
        return None
    return default_runner_factory(settings, secrets)


async def _expansion(
    conn: AsyncConnection, *, workspace_id: str, subject_kind: SubjectKind, subject_id: str
) -> list[str]:
    """Every entity id this page draws from: the subject, plus who it speaks about."""
    if subject_kind == "contact":
        subject = await resolve_subject(
            conn, workspace_id=workspace_id, kind="contact", subject_id=subject_id
        )
        return [subject.id, subject.account_id]
    members = await committee_members(conn, workspace_id=workspace_id, account_id=subject_id)
    return [subject_id, *(member.id for member in members)]


def _cited(recipes: Sequence[SectionRecipe], blocks: Mapping[str, LiveBlock]) -> tuple[str, ...]:
    """Every claim the composed page cites, in recipe order, deduped."""
    return tuple(
        dict.fromkeys(
            claim_id
            for recipe in recipes
            if recipe.section_key in blocks
            for claim_id in blocks[recipe.section_key].cited_claim_ids
        )
    )


# -- the committee -------------------------------------------------------------------------------


async def committee(
    conn: AsyncConnection, *, workspace_id: str, account_id: str
) -> list[SubjectRef]:
    """The account's committee, in the order the screens show it: persona rank, then name.

    A thin call on purpose. D2's :func:`committee_members` decides both *who* is on the committee
    (the contacts holding a live claim) and *in what order* — a second sort here is how a card and
    a generated page start listing one account's committee two different ways. This name stays so
    the read surface has one committee entry point of its own to import.
    """
    return await committee_members(conn, workspace_id=workspace_id, account_id=account_id)


async def committee_claims(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    members: Sequence[SubjectRef],
    field_keys: Sequence[str] = COMMITTEE_FIELD_KEYS,
) -> dict[tuple[str, str], Claim]:
    """``(contact id, field key) -> the latest live claim``, for the whole committee in one read.

    ``claims_for_entities`` orders by ``field_key, collected_at DESC, id``, so the first row seen
    for a pair is the newest one — the same tie-break the merge itself uses. The read is
    entity-scoped *and* workspace-scoped, never ``claim.workspace_id`` alone.

    ``field_keys`` defaults to the card's own :data:`COMMITTEE_FIELD_KEYS`; a caller that needs a
    different slice of the same people (the contact page's ``reports`` chips read
    ``contact.reports_to`` over the committee) passes its own rather than opening a second read
    path that could disagree about which claim is the latest.
    """
    entity_ids = [EntityId(uuid.UUID(member.id)) for member in members]
    if not entity_ids:
        return {}
    rows = await claims_for_entities(
        conn,
        entity_ids,
        list(field_keys),
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    latest: dict[tuple[str, str], Claim] = {}
    for claim in rows:
        latest.setdefault((str(claim.entity_id), str(claim.field_key)), claim)
    return latest


def displayable(claim: Claim | None, policy: WorkspacePolicy) -> Claim | None:
    """``claim`` if the workspace's policy permits showing it, else ``None``."""
    if claim is None or not arv2_display_allowed(claim, policy):
        return None
    return claim


def title_of(claim: Claim | None) -> str | None:
    """A displayable ``contact.current_title`` as the string it is declared to be.

    A non-string value is a registry violation; stringifying it would put an object on the card, so
    the honest answer is that the title is unknown.
    """
    if claim is None:
        return None
    value = claim.value_json
    return value.strip() or None if isinstance(value, str) else None


def _is_derived_role(claim: Claim) -> bool:
    """Whether this role claim's rationale was *derived from the persona*, not researched.

    The D1 answer-key loader writes a ``contact.role_on_committee`` row for a person the run gave a
    persona but no role, and says so twice: a :data:`DERIVED_ROLE_MARKER` write marker, and a
    rationale that names itself (:data:`DERIVED_ROLE_RATIONALE_PHRASE`). Either is enough. Both are
    checked because the marker is the durable, machine-readable statement and the phrase survives a
    row that lost its markers — and the read must not put a sentence on a card that only restates
    the persona chip sitting next to it.
    """
    if (claim.write_markers or {}).get(DERIVED_ROLE_MARKER) is not None:
        return True
    value = claim.value_json
    rationale = value.get("rationale") if isinstance(value, dict) else None
    return isinstance(rationale, str) and DERIVED_ROLE_RATIONALE_PHRASE in rationale


def _why_they_matter(claim: Claim | None, *, title: str | None, persona: str | None) -> str:
    """The committee role's own rationale, or what is actually known about this person.

    ``contact.role_on_committee`` stores ``{"role": …, "rationale": …}``; a *researched* rationale
    is the sentence a human wrote (or a model was made to justify), and it is served verbatim — it
    is the only part of that object that is a reason.

    With no such sentence — no role claim, an empty rationale, or a rationale the loader derived
    from the persona (decision 4) — the card states what it knows instead of restating the chip
    beside it: ``"VP of Marketing · Economic buyer"`` when the title is known, and otherwise
    :data:`DEFAULT_WHY_THEY_MATTER`. A persona outside the vocabulary has no label, so it falls
    back the same way rather than printing a raw enum value at a marketer.
    """
    if claim is not None and not _is_derived_role(claim):
        value = claim.value_json
        rationale = value.get("rationale") if isinstance(value, dict) else None
        if isinstance(rationale, str) and rationale.strip():
            return rationale.strip()
    label = persona_label(persona)
    if title and label:
        return f"{title} · {label}"
    return DEFAULT_WHY_THEY_MATTER


async def buying_committee(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: str,
    members: Sequence[SubjectRef],
    policy: WorkspacePolicy,
) -> list[BuyingCommitteeMember]:
    """The committee card of the account detail, in ``members`` order.

    ``account_id`` is not read: the members were already resolved *for* that account and carry
    their own ids, and re-deriving membership here is how a card and a page start disagreeing. It
    stays on the signature because every caller has it and a builder that silently accepts members
    from another account would be worse.

    Three of the four contract fields have required, non-empty strings behind them, so each one
    names its placeholder rather than inventing a value: :data:`UNKNOWN_TITLE`,
    :data:`DEFAULT_PERSONA`, :data:`DEFAULT_WHY_THEY_MATTER`. ``linkedinUrl`` is the *entity's*
    column (not a claim) and survives only if it is a safe public URL.
    """
    latest = await committee_claims(conn, workspace_id=workspace_id, members=members)
    entities = await get_contacts(conn, [EntityId(uuid.UUID(member.id)) for member in members])

    served: list[BuyingCommitteeMember] = []
    for member in members:
        title = title_of(displayable(latest.get((member.id, TITLE_KEY)), policy))
        facts = email_facts(displayable(latest.get((member.id, WORK_EMAIL_KEY)), policy))
        entity = entities.get(EntityId(uuid.UUID(member.id)))
        url = None if entity is None else entity.linkedin_url
        persona = member.persona or DEFAULT_PERSONA
        served.append(
            BuyingCommitteeMember(
                contact_id=member.id,
                name=member.name,
                title=title or UNKNOWN_TITLE,
                # Display text on the wire, the vocabulary value everywhere below it: the card
                # says "Economic buyer", while ``_why_they_matter`` still reasons about
                # ``economic_buyer`` (D4-b decision 5). ``persona`` is a required non-empty string
                # here, so :func:`persona_display` never returns ``None`` for a real member.
                persona=persona_display(persona) or persona,
                email=facts.label,
                email_claim_id=facts.claim_id,
                linkedin_url=url if safe_public_url(url) else None,
                why_they_matter=_why_they_matter(
                    displayable(latest.get((member.id, ROLE_KEY)), policy),
                    title=title,
                    persona=persona,
                ),
            )
        )
    return served


async def rail_contacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    members: Sequence[SubjectRef],
    policy: WorkspacePolicy,
) -> list[AccountContact]:
    """The account rail's contact chips — the same people, told much less about.

    ``email_verified`` is true only for an address a mailbox probe actually confirmed *and* that
    the policy permits showing; every other state (a catch-all address, an unusable one, no claim
    at all) is ``False``, which is what the chip means. ``has_detail`` is always true: every
    committee member the screens list has a contact page.
    """
    latest = await committee_claims(conn, workspace_id=workspace_id, members=members)
    return [
        AccountContact(
            id=member.id,
            name=member.name,
            title=title_of(displayable(latest.get((member.id, TITLE_KEY)), policy)),
            # As on the committee card: the chip prints words, never the vocabulary value.
            persona=persona_display(member.persona),
            email_verified=(
                email_facts(
                    displayable(latest.get((member.id, WORK_EMAIL_KEY)), policy)
                ).verified_at
                is not None
            ),
            has_detail=True,
        )
        for member in members
    ]
