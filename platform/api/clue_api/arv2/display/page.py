"""A4 MACHINERY — the page: what is already written, what must be written, and what it cost.

This is the module every other one in the package exists for. :func:`ensure_page` answers one
question — *give me this page* — and the honest answer is rarely "write all of it": most of a page
is usually already stored, some of it has gone stale under a newer claim, and some of it has
nothing to say at all. So the work is decided before a single model call is made:

1. who the page is about (:mod:`~clue_api.arv2.display.gather`), and who it speaks about;
2. what is stored and what has gone stale (:mod:`~clue_api.arv2.display.blocks`);
3. which sections actually have claims — a section with no input is **skipped**, never written
   from nothing, and is named in ``skipped_empty`` so the caller can say why it is blank;
4. the missing sections, written **concurrently**, each one through its own runner, each one
   floor-checked and (once) rewritten if it cited something it should not have;
5. the writes, applied **sequentially** afterwards.

The two structural rules of step 4/5 are worth stating plainly. Each section gets its **own**
runner, so each gets its own :class:`~clue_api.arv2.calls.ProviderCaller` and its own ledger
arithmetic — the page's spend is then the sum of what the callers metered, never a sum of numbers
a model reported. And **no database work happens inside a task**: a SQLAlchemy ``AsyncConnection``
is a single-flight object, so every insert lands after the gather, in recipe order, on the one
connection the caller owns.

Nothing here writes a claim, and nothing here decides what is true. A page is a *rendering* of the
research, so a stale page is regenerated and a wrong page is not — the fix for a wrong page is a
better claim.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.display.blocks import (
    cited_claim_ids,
    compose_display_block,
    insert_block,
    live_blocks,
    shared_blocks,
    stale_sections,
    supersede_blocks,
)
from clue_api.arv2.display.evidence import evidence_for_ids
from clue_api.arv2.display.floor import (
    apply_floor,
    check_floor,
    forbidden_aliases_for,
    verbatim_annotations,
)
from clue_api.arv2.display.gather import (
    ClientContext,
    SectionInput,
    SubjectKind,
    SubjectRef,
    client_context,
    committee_members,
    gather_section_inputs,
    resolve_subject,
)
from clue_api.arv2.display.recipes import (
    PAGE_SUBJECT_KIND,
    Page,
    SectionRecipe,
    read_recipes,
)
from clue_api.arv2.display.runner import LunaSectionRunner, SectionDraft
from clue_api.arv2.errors import Arv2Error
from clue_api.arv2.provider_ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.sinks import LedgerSink, RawSink
from clue_api.arv2.transport import HttpxTransport
from clue_config import GatewayConfig, Secrets, Settings
from clue_db import ConnFactory

#: A page is written by calling this: one runner per section, so one caller and one ledger each.
RunnerFactory = Callable[[RawSink, LedgerSink], LunaSectionRunner]

#: What the activity feed says when a page is written, by page (decision 12).
PAGE_WRITTEN_TEXT: dict[str, str] = {
    "overview": "Overview written",
    "insights": "Insights written",
    "contact": "Contact page written",
}

#: Re-exported: ``PAGE_SUBJECT_KIND`` is page-grammar data and lives in
#: :mod:`~clue_api.arv2.display.recipes`, so a shared section can ask whose page its owner is
#: without importing the page machinery. Kept importable from here for existing callers.
__all__ = [
    "PAGE_SUBJECT_KIND",
    "PAGE_WRITTEN_TEXT",
    "PageResult",
    "PageSubjectMismatch",
    "RunnerFactory",
    "default_runner_factory",
    "ensure_page",
    "people_of",
    "record_page_written",
]


class PageSubjectMismatch(Arv2Error):
    """The page asked for does not describe this kind of subject."""


# -- the production runner factory ----------------------------------------------------------------


def default_runner_factory(settings: Settings, secrets: Secrets) -> RunnerFactory:
    """The factory a real page uses: live HTTP, one caller per section over the section's sinks.

    The key is read **now**, not when a section is written, so a command with no key configured
    fails before it opens a database connection rather than half-way through a page.
    """
    key = secrets.openrouter_api_key
    if key is None or not key.get_secret_value().strip():
        raise Arv2Error("CLUE_OPENROUTER_API_KEY is unset")
    base_url = GatewayConfig().base_url
    model = settings.arv2_display_model
    timeout_s = settings.arv2_display_timeout_s

    def build(raw: RawSink, ledger: LedgerSink) -> LunaSectionRunner:
        caller = ProviderCaller(
            transport=HttpxTransport(), raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)
        )
        return LunaSectionRunner(
            caller, api_key=key, base_url=base_url, model=model, timeout_s=timeout_s
        )

    return build


# -- the activity event ---------------------------------------------------------------------------


_ACTIVITY_SQL = text(
    """
    INSERT INTO account_activity_event
        (workspace_id, account_entity_id, kind, actor_kind, text, action, occurred_at,
         project_id, ref_json)
    VALUES (:workspace_id, :account_id, 'summary', 'clue', :text, :action, :occurred_at,
            NULL, CAST(:ref_json AS jsonb))
    """
)


async def record_page_written(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: str,
    page: str,
    regenerated: bool,
    contact_id: str | None,
    now: datetime,
) -> None:
    """Decision 12: one ``summary`` event per page write, authored by Clue, never by a person.

    One event per *page*, not per section: the feed answers "what happened to this account", and
    five rows saying a fifth of a page was written is noise rather than history. A contact page
    hangs under its account (that is where the feed lives) and names the person in ``ref_json``.
    """
    await conn.execute(
        _ACTIVITY_SQL,
        {
            "workspace_id": workspace_id,
            "account_id": account_id,
            "text": PAGE_WRITTEN_TEXT[page],
            "action": f"{page} {'regenerated' if regenerated else 'generated'}",
            "occurred_at": now,
            "ref_json": json.dumps({"contact_id": contact_id}) if contact_id else None,
        },
    )


# -- the result -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class PageResult:
    """One page, plus the honest account of how it came to look like this.

    ``display_block`` is the whole page — stored sections included — while ``generated``,
    ``regenerated``, ``skipped_empty``, ``stale_served`` and ``failed`` describe only what this
    call did. A caller can therefore render the page and, separately, tell the operator that two
    sections were served as they were, one was rewritten, one had nothing to say, and one could
    not be written at all.

    ``failed`` is the section keys whose model reply was unusable twice over. Their drafts are
    **not** stored, so the next call retries them as ordinary missing sections; their ``checks``
    are still here, because an operator asking "why is that section blank" deserves the answer.
    """

    page: str
    subject: SubjectRef
    display_block: dict[str, Any]
    generated: tuple[str, ...]
    regenerated: tuple[str, ...]
    skipped_empty: tuple[str, ...]
    stale_served: tuple[str, ...]
    failed: tuple[str, ...]
    cost_usd: Decimal
    checks: dict[str, dict[str, Any]]
    evidence: list[dict[str, Any]]
    cited_claim_ids: tuple[str, ...]


# -- writing one section --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Written:
    """One section's draft, the input it was written from, and the runner that spent the money."""

    section: SectionInput
    draft: SectionDraft
    runner: LunaSectionRunner


async def _write_section(
    *,
    page: str,
    subject: SubjectRef,
    client: ClientContext,
    recipes: Sequence[SectionRecipe],
    section: SectionInput,
    people: Sequence[SubjectRef],
    settings: Settings,
    runner_factory: RunnerFactory,
    raw: BufferedRawSink,
    ledger: BufferedLedger,
    semaphore: asyncio.Semaphore,
) -> _Written:
    """Write one section: the call, the floor, one rewrite if the floor was violated.

    The rewrite is sent with the **same** section input, so the alias table is byte-identical and
    the forbidden aliases still name the claims the first draft cited. If the model violates the
    floor twice, the offending items are dropped: a page that says less is always better than a
    page that says something it must not.

    ``write_section`` is synchronous and network-bound, so it runs on a worker thread; the
    semaphore is what bounds how many sections are in flight at once.
    """
    runner = runner_factory(raw, ledger)
    async with semaphore:
        draft = await asyncio.to_thread(
            runner.write_section,
            page=page,
            subject=subject,
            client=client,
            recipes=recipes,
            section=section,
            people=people,
        )
        report = check_floor(draft, section)
        regenerated = not report.ok
        if regenerated:
            draft = await asyncio.to_thread(
                runner.write_section,
                page=page,
                subject=subject,
                client=client,
                recipes=recipes,
                section=section,
                people=people,
                forbidden_aliases=forbidden_aliases_for(report, draft.aliases),
            )
            report = check_floor(draft, section)
            if not report.ok:
                draft = apply_floor(draft, report)

    checks = dict(draft.checks)
    checks["floor_regenerated"] = regenerated
    checks["verbatim"] = (
        verbatim_annotations(draft, section) if settings.evidence_verbatim_check == "on" else None
    )
    return _Written(section=section, draft=replace(draft, checks=checks), runner=runner)


# -- the page -------------------------------------------------------------------------------------


def people_of(
    subject: SubjectRef, members: Sequence[SubjectRef]
) -> tuple[list[SubjectRef], list[str]]:
    """The page's people, and every entity id its staleness scan must watch.

    A contact page is about one person *and* their account (an account fact can go stale under
    them); an account page is about the account *and* its committee.
    """
    if subject.kind == "contact":
        return [subject], [subject.id, subject.account_id]
    return list(members), [subject.id, *(person.id for person in members)]


async def ensure_page(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_kind: SubjectKind,
    subject_id: str,
    page: Page,
    settings: Settings,
    runner_factory: RunnerFactory,
    artifacts: ArtifactSink,
    spend_conn_factory: ConnFactory,
    force: bool = False,
    regenerate_stale: bool = False,
    job_id: UUID | None = None,
) -> PageResult:
    """The page, writing only the sections that are missing (or, on request, stale).

    ``force`` retires every live block first and rewrites the whole page. ``regenerate_stale``
    rewrites the sections the research has moved underneath; without it, a stale section is served
    exactly as it was written and named in ``stale_served`` — the operator decides whether to
    spend, and the page never silently costs money it was not asked to spend.

    All writes happen on ``conn`` inside the caller's transaction: a page is one atomic
    replacement of its own sections, or it is none of them.

    The sections' provider spend does NOT ride ``conn``: their rows and raw bodies are drained
    after the sections return, sequentially, under ``spend_conn_factory`` (D2, slice 1b) — so a
    caller that rolls the page back (``--dry-run``) still records the money it spent. A page
    belongs to an account, not a project or a run, so the rows are workspace spend.

    ``job_id`` is the research job whose claims this page is written from, when the caller
    knows it (the settle-time task does; a read does not): the page's spend then shows where
    the research spend shows.
    """
    if PAGE_SUBJECT_KIND[page] != subject_kind:
        raise PageSubjectMismatch(f"the {page} page is about a {PAGE_SUBJECT_KIND[page]}")

    now = datetime.now(UTC)
    subject = await resolve_subject(
        conn, workspace_id=workspace_id, kind=subject_kind, subject_id=subject_id
    )
    client = await client_context(conn, workspace_id=workspace_id, settings=settings)
    recipes = await read_recipes(conn, page, workspace_id=workspace_id)
    members = (
        await committee_members(conn, workspace_id=workspace_id, account_id=subject.account_id)
        if subject.kind == "account"
        else []
    )
    people, expansion = people_of(subject, members)
    # A recipe with ``shared_from`` owns no block: it is never gathered, never written, and never
    # scanned for staleness here — the owner's page does all three, and this page renders the
    # result. Only the owned recipes decide what this call has to spend money on.
    recipes_owned = [recipe for recipe in recipes if recipe.shared_from is None]

    stored = await live_blocks(
        conn,
        workspace_id=workspace_id,
        subject_kind=subject_kind,
        subject_id=subject.id,
        page=page,
    )
    stale = await stale_sections(
        conn,
        workspace_id=workspace_id,
        subject_ids=expansion,
        recipes=recipes_owned,
        blocks=stored,
    )
    stale_keys = {entry.section_key for entry in stale}

    if force:
        await supersede_blocks(
            conn,
            workspace_id=workspace_id,
            subject_kind=subject_kind,
            subject_id=subject.id,
            page=page,
            section_keys=[recipe.section_key for recipe in recipes_owned],
            now=now,
        )
        missing = list(recipes_owned)
    else:
        missing = [
            recipe
            for recipe in recipes_owned
            if recipe.section_key not in stored
            or (regenerate_stale and recipe.section_key in stale_keys)
        ]
    missing_keys = {recipe.section_key for recipe in missing}
    stale_served = tuple(
        entry.section_key for entry in stale if entry.section_key not in missing_keys
    )

    inputs = (
        await gather_section_inputs(
            conn,
            workspace_id=workspace_id,
            subject=subject,
            recipes=missing,
            people=people,
            settings=settings,
        )
        if missing
        else []
    )
    skipped_empty = tuple(item.recipe.section_key for item in inputs if item.empty)
    to_write = [item for item in inputs if not item.empty]

    semaphore = asyncio.Semaphore(max(1, settings.arv2_display_max_parallel))
    buffers = [(BufferedRawSink(), BufferedLedger()) for _ in to_write]
    try:
        written: list[_Written] = list(
            await asyncio.gather(
                *(
                    _write_section(
                        page=page,
                        subject=subject,
                        client=client,
                        recipes=recipes,
                        section=item,
                        people=people,
                        settings=settings,
                        runner_factory=runner_factory,
                        raw=raw,
                        ledger=ledger,
                        semaphore=semaphore,
                    )
                    for item, (raw, ledger) in zip(to_write, buffers, strict=True)
                )
            )
        )
    finally:
        # One connection, one section at a time: a drain inside the gather would race on it.
        # A fully-stored read buffered nothing, so it opens no spend connection at all.
        if buffers:
            async with spend_conn_factory() as spend_conn:
                for raw, ledger in buffers:
                    await drain_provider_calls(
                        spend_conn,
                        raw=raw,
                        ledger=ledger,
                        artifacts=artifacts,
                        stamp=LedgerStamp(workspace_id=workspace_id, job_id=job_id),
                    )

    # A section the model failed to write twice is *not* stored. Persisting its empty draft would
    # turn a transient provider failure into a section that reads blank on every later visit until
    # something made it stale; leaving it unwritten means the next call simply tries again.
    usable = [entry for entry in written if not entry.draft.checks.get("reply_invalid")]
    failed = tuple(
        entry.section.recipe.section_key
        for entry in written
        if entry.draft.checks.get("reply_invalid")
    )

    for entry in usable:
        await insert_block(
            conn,
            workspace_id=workspace_id,
            subject_kind=subject_kind,
            subject_id=subject.id,
            page=page,
            recipe=entry.section.recipe,
            draft=entry.draft,
            section=entry.section,
            now=now,
        )

    generated = tuple(entry.section.recipe.section_key for entry in usable)
    regenerated = tuple(key for key in generated if key in stored)
    if generated:
        await record_page_written(
            conn,
            workspace_id=workspace_id,
            account_id=subject.account_id,
            page=page,
            regenerated=bool(regenerated),
            contact_id=subject.id if subject.kind == "contact" else None,
            now=now,
        )

    blocks = await live_blocks(
        conn,
        workspace_id=workspace_id,
        subject_kind=subject_kind,
        subject_id=subject.id,
        page=page,
    )
    shared = await shared_blocks(
        conn,
        workspace_id=workspace_id,
        page=page,
        recipes=recipes,
        subject_id=subject.id,
        member_ids=[member.id for member in members],
    )
    display_block = compose_display_block(page, recipes, blocks, shared=shared)
    cited = cited_claim_ids(recipes, blocks, shared)
    evidence = await evidence_for_ids(conn, workspace_id=workspace_id, claim_ids=cited)

    return PageResult(
        page=page,
        subject=subject,
        display_block=display_block,
        generated=generated,
        regenerated=regenerated,
        skipped_empty=skipped_empty,
        stale_served=stale_served,
        failed=failed,
        cost_usd=sum(
            (entry.runner.totals().usd for entry in written),
            start=Decimal(0),
        ),
        checks={entry.section.recipe.section_key: dict(entry.draft.checks) for entry in written},
        evidence=[ref.to_wire() for ref in evidence],
        cited_claim_ids=cited,
    )
