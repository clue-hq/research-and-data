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
from collections.abc import Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.blocks import (
    cited_claim_ids,
    compose_display_block,
    live_blocks,
    shared_blocks,
    stale_sections,
)
from clue_api.arv2.display.fleet_handler import display_page_payload
from clue_api.arv2.display.gather import (
    PERSONA_KEY,
    TITLE_KEY,
    SubjectKind,
    SubjectRef,
    committee_members,
    gather_section_inputs,
    resolve_subject,
)
from clue_api.arv2.display.page import (
    RunnerFactory,
    default_runner_factory,
    ensure_page,
    people_of,
)
from clue_api.arv2.display.personas import persona_display, persona_label
from clue_api.arv2.display.recipes import (
    PAGE_SUBJECT_KIND,
    Page,
    SectionRecipe,
    read_recipes,
)
from clue_api.arv2.errors import Arv2Error, ProviderHalted, ProviderTransportError
from clue_api.arv2.fleet_task import (
    ARV2_DISPLAY_DEDUP_PREFIX,
    ARV2_DISPLAY_TASK_PRIORITY,
    arv2_display_work_id,
)
from clue_api.arv2.provider_ledger import ArtifactSink
from clue_api.frontend_read.contract_v1 import AccountContact, BuyingCommitteeMember
from clue_api.frontend_read.v1_shared import arv2_display_allowed, email_facts
from clue_api.provider_incidents import open_incidents, provider_display, reason_words
from clue_api.url_safety import safe_public_url
from clue_config import Secrets, Settings
from clue_core import Claim, EntityId
from clue_core.provider_failures import ProviderFailure, classify_http
from clue_db import ConnFactory
from clue_fleet import FleetTaskKind, WorkQueue
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
    "PENDING_MESSAGE",
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

#: The one sentence a section carries while the fleet is writing it (founder ruling 2026-09-21).
PENDING_MESSAGE = "Synthesis in progress, please wait a few seconds."

#: How long one web process waits before re-offering an account's contact pages on open. The table
#: behind it is in-process, like the regeneration table: a second web process offers its own round,
#: which the fleet's work id folds into the same task.
_CONTACT_OFFER_COOLDOWN_S = 60.0

#: The newest settled person job per committee member — the job a member's page is written under,
#: so its sections' spend is stamped against the research that produced their claims.
_SETTLED_MEMBER_JOBS = text(
    """
    SELECT DISTINCT ON (subject_entity_id) subject_entity_id, job_id
    FROM arv2_research_job
    WHERE workspace_id = :workspace_id
      AND subject_type = 'person'
      AND subject_entity_id = ANY(CAST(:member_ids AS uuid[]))
      AND status IN ('completed', 'needs_review')
    ORDER BY subject_entity_id, finished_at DESC NULLS LAST
    """
)

#: Which of those members already have a contact page written — the ones an open must not re-offer.
_MEMBERS_WITH_A_PAGE = text(
    """
    SELECT DISTINCT subject_id FROM display_block
    WHERE workspace_id = :workspace_id AND subject_kind = 'contact' AND page = 'contact'
      AND subject_id = ANY(CAST(:member_ids AS uuid[])) AND superseded_at IS NULL
    """
)

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

    ``unavailable_message`` is the one sentence the empty sections carry when a provider stopped
    serving us — the same words the research card and the failed chat turn use, so a reader meets
    one explanation wherever the outage surfaces. It is ``None`` whenever the page is empty for any
    other reason (nothing researched yet, a recipe that matched nothing): an empty section is a
    correct answer, and only an outage gets an excuse.

    ``pending`` names the empty sections a fleet task is on its way to write — only ever non-empty
    on a scheduling seam (:attr:`DisplayPages.schedules`), and only for sections whose recipe
    actually matched claims. A section that matches nothing is never pending: the placeholder
    sentence is a promise, and an empty section nobody will fill must not make one.
    """

    display_block: dict[str, Any]
    cited_claim_ids: tuple[str, ...]
    generated: tuple[str, ...]
    stale: tuple[str, ...]
    degraded_reason: str | None
    unavailable_message: str | None = None
    pending: tuple[str, ...] = ()
    research_quality: dict[str, Any] | None = None


#: The failures a read absorbs. ``Arv2Error`` covers the lane's own typed failures (a halted or
#: unreachable provider are subclasses, named separately for legibility); ``OSError`` covers the
#: raw sink's filesystem; ``ValueError`` covers a reply the runner could not make sense of. A
#: database error is deliberately *not* here — it is not a display failure, and swallowing it
#: would serve a page composed from a transaction that is already broken.
_DEGRADING = (Arv2Error, ProviderHalted, ProviderTransportError, OSError, ValueError)

#: The provider that writes display sections. A page has exactly one generator, so an incident
#: open against any other provider says nothing about why this page is blank.
_GENERATION_PROVIDER = "openrouter"


def _classify(exc: BaseException) -> ProviderFailure | None:
    """A degrading failure as a provider verdict, or ``None`` when no provider is to blame.

    A halt carries the provider, the status and the reason the wrapper read off the body, so the
    same :func:`classify_http` that classified it on the spend path classifies it again here — a
    latched halt has no status, and there is nothing honest to say from one, so it falls through
    to the open incident instead of being guessed at as a timeout. A transport error never reached
    HTTP at all, which :func:`classify_http` spells as ``status=None``: a timeout-class failure.
    Everything else (a filesystem fault, an unusable reply) is ours, not the provider's.
    """
    if isinstance(exc, ProviderHalted):
        if exc.http_status is None:
            return None
        return classify_http(exc.provider, exc.http_status, exc.reason_code)
    if isinstance(exc, ProviderTransportError):
        return classify_http(exc.provider, None, exc.last_error)
    return None


def _unavailable_sentence(provider: str, kind: str, reason: str) -> str:
    """The shared outage sentence, in the empty section's voice."""
    verb = "refused" if kind == "refusal" else "failing"
    return (
        f"Not generated: {provider_display(provider).lower()} {verb} "
        f"({reason_words(reason)}). Retries automatically."
    )


class DisplayPages:
    """The read surface's access to the D2 display layer: one instance per composed router.

    One instance, not one per request, because the in-flight regeneration table has to outlive the
    request that scheduled the work — that table is what makes "one rewrite per page, however many
    people are looking at it" true.

    **With a ``queue``, this seam is a scheduler, not a writer** (plan 2026-09-21). It serves the
    blocks that are stored, works out which of the missing sections a write would actually fill,
    offers *one* fleet task for the page, and marks exactly those sections ``pending`` with
    :data:`PENDING_MESSAGE`; opening an account additionally offers the contact pages of its
    settled committee members. Nothing is written on the request, so no browser waits on a model
    and no page is paid for twice. **Without one** it is the D3 inline writer described above: it
    writes the missing sections during the request and repairs stale ones on a background task.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        secrets: Secrets | None,
        conn_factory: ConnFactory,
        runner_factory: RunnerFactory | None = None,
        artifacts: ArtifactSink | None = None,
        queue: WorkQueue | None = None,
    ) -> None:
        self._settings = settings
        self._conn_factory = conn_factory
        self._queue = queue
        #: ``(workspace, account) -> monotonic clock of the last contact-page round offered``.
        self._contact_offers: dict[tuple[str, str], float] = {}
        self._runner_factory = (
            runner_factory
            if runner_factory is not None
            else _production_runner_factory(settings, secrets)
        )
        self._artifacts = artifacts
        self._regenerating: dict[tuple[str, str, str, str], asyncio.Task[None]] = {}
        if self._runner_factory is not None and artifacts is None:
            # Stated once, at composition, rather than discovered as a page that never fills in:
            # slice 1b makes the artifact sink part of what a write costs, so a seam without one
            # serves stored blocks only.
            log.warning(
                "frontend_read.display.regeneration_disabled",
                reason="no artifact store composed",
            )

    @property
    def settings(self) -> Settings:
        """The deployment settings this composer was built with — the fit thresholds and the
        Brandfetch client id the reads need, exposed so a read can share them without a second
        ``Settings`` in the same process."""
        return self._settings

    @property
    def generates(self) -> bool:
        """Whether a page may be written: a runner to write it AND a sink for its raw bodies.

        Both halves, not just the key: slice 1b put the sections' spend on
        ``provider_call_ledger``, and a ledger row cites the artifact its reply became — so a seam
        with no artifact store cannot record what a page costs and does not write one. It serves
        what is stored instead, the same fail-closed-before-spend posture a missing key has.
        """
        return self._runner_factory is not None and self._artifacts is not None

    @property
    def schedules(self) -> bool:
        """Whether a read hands page writes to the fleet instead of writing inline."""
        return self._queue is not None and self._settings.arv2_display_generate_on_read

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
        project_id: str | None = None,
        context_id: uuid.UUID | None = None,
        account_id: uuid.UUID | None = None,
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
        from clue_api.arv2.quality_pages import read_page
        from clue_api.arv2.quality_read import select_quality_context

        selection = await select_quality_context(
            conn,
            workspace_id=workspace_id,
            subject_id=uuid.UUID(subject_id),
            subject_kind=subject_kind,
            account_id=account_id,
            project_id=project_id,
            context_id=context_id,
        )
        if selection is not None:
            if selection.scope is not None and selection.context_id is not None:
                try:
                    value = await read_page(
                        conn, selection.scope, context_id=selection.context_id, page=page
                    )
                    value["research_quality"]["contexts"] = selection.metadata["contexts"]
                    return PageRead(**value)
                except ValueError:
                    # A stopped or not-yet-started generation has no usable narrative. Never
                    # fall through to the unscoped Luna owner because a quality page is pending.
                    pass
            recipes = await read_recipes(conn, page, workspace_id=workspace_id)
            block = compose_display_block(page, recipes, {})
            metadata = {k: v for k, v in selection.metadata.items() if k != "committee"}
            block["researchQuality"] = metadata
            return PageRead(
                display_block=block,
                cited_claim_ids=(),
                generated=(),
                stale=(),
                degraded_reason=None,
                research_quality=metadata,
            )
        recipes = await read_recipes(conn, page, workspace_id=workspace_id)
        expansion = await _expansion(
            conn, workspace_id=workspace_id, subject_kind=subject_kind, subject_id=subject_id
        )

        generated: tuple[str, ...] = ()
        degraded_reason: str | None = None
        degrading_failure: ProviderFailure | None = None
        pending: tuple[str, ...] = ()
        if generate and self.schedules:
            pending = await self._offer_missing_and_stale(
                conn,
                workspace_id=workspace_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                page=page,
                recipes=recipes,
                expansion=expansion,
            )
            if subject_kind == "account":
                await self._offer_members_on_open(
                    conn, workspace_id=workspace_id, account_id=subject_id
                )
        elif generate and self.generates:
            assert self._runner_factory is not None and self._artifacts is not None
            try:
                result = await ensure_page(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    page=page,
                    settings=self._settings,
                    runner_factory=self._runner_factory,
                    artifacts=self._artifacts,
                    spend_conn_factory=self._conn_factory,
                    regenerate_stale=False,
                )
            except _DEGRADING as exc:
                degraded_reason = type(exc).__name__
                degrading_failure = _classify(exc)
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
        # Only the inline path repairs staleness in-process: a scheduling seam already offered the
        # page task above, and a second, in-process rewrite would pay for the same sections twice.
        if stale_keys and generate and not self.schedules:
            self.schedule_regeneration(
                workspace_id=workspace_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                page=page,
            )
        shared = await shared_blocks(
            conn,
            workspace_id=workspace_id,
            page=page,
            recipes=recipes,
            subject_id=subject_id,
            # ``_expansion`` already resolved the committee, in committee order, as
            # everything after the subject itself — re-reading it here would be a second
            # query that could disagree with the one the staleness scan used.
            member_ids=list(expansion[1:]) if subject_kind == "account" else [],
        )
        display_block = compose_display_block(page, recipes, blocks, shared=shared)
        # A section a fleet task is about to write says so, and says the one sentence. ``pending``
        # is stamped on EVERY section (``False`` where nothing is coming) so the wire shape does
        # not change with the seam's configuration — the contract's default is the same ``False``.
        for section in display_block["sections"]:
            section["pending"] = section["key"] in pending
            if section["pending"]:
                section["emptyMessage"] = PENDING_MESSAGE
        # Why the empty sections are empty, when the answer is a provider and not the research.
        # The classified halt speaks first (it is THIS read's own failure); otherwise an incident
        # that is open right now explains a page a previous, already-degraded read left behind.
        unavailable: str | None = None
        if degrading_failure is not None:
            unavailable = _unavailable_sentence(
                degrading_failure.provider, degrading_failure.kind, degrading_failure.reason
            )
        else:
            live = await open_incidents(conn, providers=[_GENERATION_PROVIDER])
            if live:
                unavailable = _unavailable_sentence(live[0].provider, live[0].kind, live[0].reason)
        if unavailable is not None:
            for section in display_block["sections"]:
                if section["empty"] and section["key"] not in blocks:
                    section["emptyMessage"] = unavailable
        display_block["researchQuality"] = {
            "qualityState": "legacy",
            "refreshPending": bool(pending),
            "gaps": [],
            "contexts": [],
        }
        return PageRead(
            display_block=display_block,
            cited_claim_ids=cited_claim_ids(recipes, blocks, shared),
            generated=generated,
            stale=stale_keys,
            degraded_reason=degraded_reason,
            unavailable_message=unavailable,
            pending=pending,
            research_quality={
                "qualityState": "legacy",
                "refreshPending": bool(pending),
                "gaps": [],
                "contexts": [],
            },
        )

    # -- scheduling: the fleet writes the page, this read only offers it -----------------------

    async def _offer_missing_and_stale(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        subject_kind: SubjectKind,
        subject_id: str,
        page: Page,
        recipes: Sequence[SectionRecipe],
        expansion: Sequence[str],
    ) -> tuple[str, ...]:
        """Offer this page's task when anything on it needs writing; return the keys that will be.

        A missing section is *pending* only when the gather step (no model call) says its recipe
        matched claims: the placeholder sentence is a promise, and a section that matches nothing
        keeps the ordinary empty state. A stale section is served as stored and re-offered; it is
        never pending, because it is not empty.

        A recipe with ``shared_from`` owns no block on this page, so it is neither missing nor
        pending here and this page's task would not write it. What it needs instead is its
        *owner's* page: :meth:`_offer_owner_pages` re-offers that page when the owner's block has
        gone stale, on the owner's own subject.
        """
        recipes_owned = [recipe for recipe in recipes if recipe.shared_from is None]
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
            recipes=recipes_owned,
            blocks=blocks,
        )
        await self._offer_owner_pages(
            conn,
            workspace_id=workspace_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            page=page,
            recipes=recipes,
            expansion=expansion,
        )
        missing = [recipe for recipe in recipes_owned if recipe.section_key not in blocks]
        would_write: tuple[str, ...] = ()
        if missing:
            subject = await resolve_subject(
                conn, workspace_id=workspace_id, kind=subject_kind, subject_id=subject_id
            )
            members = (
                await committee_members(
                    conn, workspace_id=workspace_id, account_id=subject.account_id
                )
                if subject.kind == "account"
                else []
            )
            people, _ = people_of(subject, members)
            inputs = await gather_section_inputs(
                conn,
                workspace_id=workspace_id,
                subject=subject,
                recipes=missing,
                people=people,
                settings=self._settings,
            )
            would_write = tuple(item.recipe.section_key for item in inputs if not item.empty)
        if not would_write and not stale:
            return ()
        offered = await self._offer_page(
            workspace_id=workspace_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            page=page,
        )
        return would_write if offered else ()

    async def _offer_owner_pages(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        subject_kind: SubjectKind,
        subject_id: str,
        page: Page,
        recipes: Sequence[SectionRecipe],
        expansion: Sequence[str],
    ) -> None:
        """Re-offer the OWNER page of every shared section whose owner block has gone stale.

        A sharer is never pending and never repaired here: the words belong to another page, so
        the honest repair is to offer *that* page, on *that* subject. An owner on the sharer's own
        subject (insights ``context-only`` ← the overview's ``watch-outs``) is one offer; an owner
        per committee member (``contact-insights`` ← each member's ``why-this-person``) is one
        offer per stale member. An owner nobody has written yet is not offered from here — the
        owner's own screen, and the on-open contact sweep, are what write it the first time.
        """
        members = list(expansion[1:]) if subject_kind == "account" else []
        for recipe in recipes:
            if recipe.shared_from is None:
                continue
            owner_page, owner_key = recipe.shared_from
            owner_kind = PAGE_SUBJECT_KIND[owner_page]
            owners = (
                [(subject_kind, subject_id, expansion)]
                if owner_kind == PAGE_SUBJECT_KIND[page]
                else [(owner_kind, member, [member, subject_id]) for member in members]
            )
            for owner_subject_kind, owner_subject_id, owner_expansion in owners:
                owner_blocks = await live_blocks(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind=owner_subject_kind,
                    subject_id=owner_subject_id,
                    page=owner_page,
                )
                if owner_key not in owner_blocks:
                    continue
                owner_recipes = [
                    other
                    for other in await read_recipes(conn, owner_page, workspace_id=workspace_id)
                    if other.section_key == owner_key
                ]
                owner_stale = await stale_sections(
                    conn,
                    workspace_id=workspace_id,
                    subject_ids=list(owner_expansion),
                    recipes=owner_recipes,
                    blocks=owner_blocks,
                )
                if owner_stale:
                    await self._offer_page(
                        workspace_id=workspace_id,
                        subject_kind=owner_subject_kind,
                        subject_id=owner_subject_id,
                        page=owner_page,
                    )

    async def _offer_page(
        self,
        *,
        workspace_id: str,
        subject_kind: SubjectKind,
        subject_id: str,
        page: Page,
        job_id: uuid.UUID | None = None,
    ) -> bool:
        """One page task on the fleet; ``True`` when the offer landed.

        Landed means new, re-opened, or already queued — every one of those means the page will be
        written. ``False`` only when the queue itself failed, which is logged and never raised into
        a read: a reader still gets their page, and the sections are then served honestly empty
        rather than promising a write that was never offered.
        """
        assert self._queue is not None
        try:
            await self._queue.enqueue(
                kind=FleetTaskKind.ARV2_DISPLAY_PAGE,
                work_id=arv2_display_work_id(subject_kind, subject_id, page),
                dedup_key=f"{ARV2_DISPLAY_DEDUP_PREFIX}{subject_kind}:{subject_id}:{page}",
                priority=ARV2_DISPLAY_TASK_PRIORITY,
                payload=display_page_payload(
                    workspace_id=workspace_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    page=page,
                    job_id=job_id,
                ),
                reopen_terminal=True,
            )
        except Exception as exc:  # noqa: BLE001 — a queue outage must not fail a read
            log.warning(
                "frontend_read.display.offer_failed",
                workspace_id=workspace_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                page=page,
                error=str(exc),
            )
            return False
        return True

    async def _offer_members_on_open(
        self, conn: AsyncConnection, *, workspace_id: str, account_id: str
    ) -> None:
        """The account's contact pages, at most once a minute per account per web process."""
        key = (workspace_id, account_id)
        last = self._contact_offers.get(key)
        now = monotonic()
        if last is not None and now - last < _CONTACT_OFFER_COOLDOWN_S:
            return
        self._contact_offers[key] = now
        await self.offer_contact_pages(conn, workspace_id=workspace_id, account_id=account_id)

    async def offer_contact_pages(
        self, conn: AsyncConnection, *, workspace_id: str, account_id: str
    ) -> int:
        """Spec 2026-09-12 §2 "on open": offer the contact page of every committee member with a
        settled person job and no live page. Idempotent on the fleet by work id; returns how many
        offers landed. A seam with no queue offers nothing."""
        if not self.schedules:
            return 0
        from clue_api.arv2.quality_read import select_quality_context

        if (
            await select_quality_context(
                conn, workspace_id=workspace_id, subject_id=uuid.UUID(account_id)
            )
            is not None
        ):
            return 0  # Quality generations own all page refreshes, including person pages.
        members = await committee_members(conn, workspace_id=workspace_id, account_id=account_id)
        if not members:
            return 0
        member_ids = [uuid.UUID(member.id) for member in members]
        settled = {
            str(row["subject_entity_id"]): row["job_id"]
            for row in (
                await conn.execute(
                    _SETTLED_MEMBER_JOBS, {"workspace_id": workspace_id, "member_ids": member_ids}
                )
            ).mappings()
        }
        written = {
            str(row["subject_id"])
            for row in (
                await conn.execute(
                    _MEMBERS_WITH_A_PAGE, {"workspace_id": workspace_id, "member_ids": member_ids}
                )
            ).mappings()
        }
        offered = 0
        for member in members:
            if member.id not in settled or member.id in written:
                continue
            if await self._offer_page(
                workspace_id=workspace_id,
                subject_kind="contact",
                subject_id=member.id,
                page="contact",
                job_id=settled[member.id],
            ):
                offered += 1
        return offered

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
        if not self.generates:
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
            if not self.generates:  # pragma: no cover - guarded at the scheduler
                return
            assert self._runner_factory is not None and self._artifacts is not None
            async with self._conn_factory() as conn:
                await ensure_page(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    page=page,
                    settings=self._settings,
                    runner_factory=self._runner_factory,
                    artifacts=self._artifacts,
                    spend_conn_factory=self._conn_factory,
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


# -- the committee -------------------------------------------------------------------------------


def _membership_gap_text(reason: str) -> str:
    """Keep diagnostic reason codes in the assessment, not in product copy."""
    return {
        "committee_assessment_not_applicable": "The proposed buying role needs verification.",
        "affiliation_refuted": "Evidence contradicts employment at this company.",
        "current_affiliation_not_established": "Current employment at this company is unverified.",
    }.get(reason, "Committee membership needs further verification.")


async def committee(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: str,
    project_id: str | None = None,
    context_id: uuid.UUID | None = None,
) -> list[SubjectRef]:
    """The account's committee, in the order the screens show it: persona rank, then name.

    A thin call on purpose. D2's :func:`committee_members` decides both *who* is on the committee
    (the contacts holding a live claim) and *in what order* — a second sort here is how a card and
    a generated page start listing one account's committee two different ways. This name stays so
    the read surface has one committee entry point of its own to import.
    """
    from clue_api.arv2.quality_read import select_quality_context
    from clue_api.arv2.quality_relationships import CommitteeMember as QualityMember

    selection = await select_quality_context(
        conn,
        workspace_id=workspace_id,
        subject_id=uuid.UUID(account_id),
        project_id=project_id,
        context_id=context_id,
    )
    if selection is None:
        return await committee_members(conn, workspace_id=workspace_id, account_id=account_id)
    if selection.scope is None:
        return []
    states = [
        QualityMember.model_validate(m)
        for m in selection.metadata["committee"]
        if m["state"] != "excluded"
    ]
    people = await get_contacts(conn, [EntityId(m.contact_id) for m in states])
    return [
        SubjectRef(
            kind="contact",
            id=str(m.contact_id),
            name=people[EntityId(m.contact_id)].full_name or str(m.contact_id),
            account_id=account_id,
            account_name=selection.scope.account_name,
            account_domain=selection.scope.account_domain,
            persona=m.proposed_role if m.state == "supported" else m.state,
            membership_state=m.state,
            membership_gaps=tuple(dict.fromkeys(_membership_gap_text(gap) for gap in m.gaps)),
            outreach_eligible=m.outreach_eligible,
        )
        for m in states
        if EntityId(m.contact_id) in people
    ]


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
                membership_state=member.membership_state,
                membership_gaps=member.membership_gaps,
                outreach_eligible=member.outreach_eligible,
                why_they_matter="Buying responsibility has not been established."
                if member.membership_state not in (None, "supported")
                else _why_they_matter(
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
