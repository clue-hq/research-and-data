"""The Head of ABM reads this project's own ARV2 rows, instead of remembering them.

An agent that only knows what its own thread launched is wrong the moment a human imports a list,
approves a discovery candidate in the app, or opens a second thread. These tools close that gap:
they are effect-free reads over the rows that already exist — the project's accounts and the state
of each account's research here — so "how many accounts do we have, and how many are researched?"
is answered from the database rather than from the transcript.

Three properties are deliberate, and each one is a test:

* **Effect-free, and classified as such.** ``READ`` + ``EFFECT_FREE``: a read never launches
  anything, buys anything or approves anything, so replaying a turn that contained one is free.
* **Absence is a typed refusal, never an empty success.** A project this workspace cannot see
  comes back as ``project_not_found``, because an empty account list is a *statement* — "this
  project has no accounts" — and it would be a lie about a project that is simply not ours.
* **Scope is ambient.** The workspace comes from :class:`~clue_toolbelt.ToolContext`, never from
  the model; the project id is an untrusted input, checked against that workspace before any row
  is read.

All three reads sit behind one :class:`Arv2ReadService` seam: one protocol the toolbelt tools
call, one :class:`DbArv2ReadService` that opens one transaction per call.

Two of them wear two faces. ``read_account_research`` and ``read_discovery_run`` are registered at
``@1`` *and* at a paged ``@2`` that takes ``offset``/``limit`` and answers with ``next_offset``, so
a run of sixty companies or an account of two hundred claims is walked to the end instead of being
cut at the first page. ``@1`` is frozen — a promoted profile pins its schema digest, and that pin
is exactly how a contract that changed underneath it gets noticed — so the new inputs arrive at a
new address rather than by editing the old one.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.discovery_store import (
    SHOWN_DISPOSITIONS,
    VERIFIED_PREDICATE,
    CandidateRow,
    list_candidates,
)
from clue_api.arv2.discovery_store import read_discovery_run as read_discovery_run_row
from clue_api.arv2.display.blocks import live_blocks
from clue_api.arv2.display.recipes import read_recipes
from clue_api.arv2.errors import Arv2Error
from clue_config import Settings
from clue_core import Claim, EntityId, UseClass, VerificationStatus
from clue_db import ConnFactory, transaction
from clue_research.claimstore import WorkspaceScope, claims_for_entities
from clue_spine import get_project
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailed,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "BODY_CHARS",
    "EVIDENCE_CHARS",
    "MAX_ACCOUNTS",
    "MAX_CANDIDATES",
    "MAX_CLAIMS",
    "READ_REFERENCES_BUDGET_BYTES",
    "AccountClaimView",
    "AccountOverviewSection",
    "AccountResearch",
    "Arv2ReadRefused",
    "Arv2ReadService",
    "DbArv2ReadService",
    "DiscoveryCandidateView",
    "DiscoveryRunView",
    "ProjectAccountView",
    "ProjectAccountsPage",
    "ReadAccountResearchInput",
    "ReadAccountResearchOutput",
    "ReadAccountResearchTool",
    "ReadAccountResearchV2Input",
    "ReadAccountResearchV2Tool",
    "ReadDiscoveryRunInput",
    "ReadDiscoveryRunOutput",
    "ReadDiscoveryRunTool",
    "ReadDiscoveryRunV2Input",
    "ReadDiscoveryRunV2Output",
    "ReadDiscoveryRunV2Tool",
    "ReadProjectAccountsInput",
    "ReadProjectAccountsOutput",
    "ReadProjectAccountsTool",
    "build_arv2_paged_read_tools",
    "build_arv2_read_tools",
    "claim_prefixes",
    "list_project_accounts",
    "read_account_research",
    "read_discovery_run",
    "receipt_bytes",
]

#: The hard ceiling on one read. A tool result is context the model pays for on every later turn,
#: so the page is bounded by construction rather than by the caller's good manners.
MAX_ACCOUNTS = 200


class Arv2ReadRefused(Arv2Error):
    """A read cannot be served, and the caller is told exactly which prerequisite is missing.

    ``code`` is stable and machine-readable; the toolbelt tools turn it straight into a
    :class:`~clue_toolbelt.PreconditionFailure`. Codes: ``project_not_found``,
    ``account_not_found``, ``overview_not_written``, ``account_not_researched``,
    ``no_claims_under_prefix``, ``offset_past_end``, ``offset_not_paged``,
    ``discovery_run_not_found``, ``no_discovery_run``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# =================================================================================================
# read 1: the project's accounts
# =================================================================================================


class ProjectAccountView(BaseModel, frozen=True):
    """One account in a project: who it is, where its research stands, and how it got here."""

    account_entity_id: str
    name: str
    domain: str | None
    #: ``arv2_research_job.status`` verbatim — ``not_started`` / ``in_progress`` / ``needs_review``
    #: / ``completed`` / ``suspended``. An account with no job at all reads ``not_started``.
    research_status: str
    #: The account has been researched before **and** is being researched again right now.
    refreshing: bool
    added_via: str
    added_at: str


@dataclass(frozen=True, slots=True)
class ProjectAccountsPage:
    """One bounded page of a project's accounts, plus how many there are in total."""

    project_id: str
    total: int
    accounts: tuple[ProjectAccountView, ...]


#: The optional name/domain filter, written once so the page and the total measure one population.
#: ``CAST(:query AS text) IS NULL`` rather than a Python-assembled predicate: the statement is one
#: prepared shape either way, and the pattern is always bound rather than interpolated.
_ACCOUNT_QUERY_FILTER = """
      AND (
          CAST(:query AS text) IS NULL
          OR a.canonical_name ILIKE :pattern
          OR a.primary_domain ILIKE :pattern
      )"""

#: The project's accounts with each one's research state, in one statement.
#:
#: ``merged_into IS NULL`` drops merge losers: a merged account is the same company under another
#: id, and listing it twice would make a project look bigger than it is. The lateral join takes the
#: account's newest ARV2 **account** job — person jobs share this table and the account column, and
#: a contact still being researched is not the account being re-researched. ``refreshing`` is the
#: narrow claim it sounds like: the latest run is live *and* an earlier one completed, so the
#: account already has research on it and is getting more — and "earlier" is the same **tuple**
#: compare ``frontend_read.v1_shared._ARV2_RESEARCH_STATUS`` uses, because both statements order
#: "latest" by ``(created_at, job_id)`` and so both must break a ``created_at`` tie the same way.
#: Two jobs written in one transaction would otherwise read ``refreshing: false`` to the agent and
#: "Refreshing" on the screen.
#:
#: The row order is the accounts screen's own default (``created_at DESC, id DESC``), so "the first
#: ten accounts" means the same ten to the agent and to the marketer looking at the table.
_LIST_PROJECT_ACCOUNTS = text(
    f"""
    SELECT a.id, a.canonical_name, a.primary_domain, pa.added_via, pa.added_at,
           j.status AS research_status,
           EXISTS (SELECT 1 FROM arv2_research_job j2
                   WHERE j2.workspace_id = :ws AND j2.account_entity_id = a.id
                     AND j2.subject_type = 'account'
                     AND j2.status IN ('not_started', 'in_progress')
                     AND EXISTS (SELECT 1 FROM arv2_research_job j3
                                 WHERE j3.workspace_id = :ws AND j3.account_entity_id = a.id
                                   AND j3.subject_type = 'account' AND j3.status = 'completed'
                                   AND (j3.created_at, j3.job_id)
                                       < (j2.created_at, j2.job_id))) AS refreshing
    FROM project_account pa
    JOIN account_entity a ON a.id = pa.account_entity_id AND a.merged_into IS NULL
    LEFT JOIN LATERAL (
      SELECT status FROM arv2_research_job j
      WHERE j.workspace_id = :ws AND j.account_entity_id = a.id AND j.subject_type = 'account'
      ORDER BY j.created_at DESC, j.job_id DESC LIMIT 1
    ) j ON TRUE
    WHERE pa.workspace_id = :ws AND pa.project_id = :project{_ACCOUNT_QUERY_FILTER}
    ORDER BY a.created_at DESC, a.id DESC
    LIMIT :limit OFFSET :offset
    """
)

#: The total counts the rows the listing *can show*, which is why it repeats the listing's own
#: ``merged_into IS NULL`` join **and** its filter: "showing 100 of 240" must be two measurements
#: of one population, and counting a merge loser (or a name the filter excluded) the page can never
#: serve would make the remainder unreachable.
_COUNT_PROJECT_ACCOUNTS = text(
    f"""
    SELECT count(*)
    FROM project_account pa
    JOIN account_entity a ON a.id = pa.account_entity_id AND a.merged_into IS NULL
    WHERE pa.workspace_id = :ws AND pa.project_id = :project{_ACCOUNT_QUERY_FILTER}
    """
)


def _ilike_pattern(query: str | None) -> str:
    """``query`` as a contains-pattern, with LIKE's own metacharacters neutered.

    A human typing ``100%`` or ``a_b`` is naming a company, not writing a pattern; unescaped, the
    first would match every account and the second would match one character too many. Backslash
    goes first — it is the escape character Postgres LIKE uses by default, so escaping it after the
    others would re-escape their escapes.
    """

    if query is None:
        return "%"
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def list_project_accounts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    limit: int,
    query: str | None = None,
    offset: int = 0,
) -> ProjectAccountsPage:
    """The project's accounts with their research status. Raises when the project is not ours."""

    project = await get_project(conn, project_id)
    if project is None or project.workspace_id != workspace_id:
        # Fail-closed and indistinguishable: another workspace's project is not "empty", it is
        # absent — the same answer a project id that never existed gets.
        raise Arv2ReadRefused("project_not_found", f"no project {project_id} in this workspace")
    params: dict[str, Any] = {
        "ws": workspace_id,
        "project": project_id,
        "limit": limit,
        "offset": offset,
        "query": query,
        "pattern": _ilike_pattern(query),
    }
    rows = (await conn.execute(_LIST_PROJECT_ACCOUNTS, params)).mappings().all()
    # The total measures the FILTERED population: the model pages within the answer it asked for.
    total = int((await conn.execute(_COUNT_PROJECT_ACCOUNTS, params)).scalar_one())
    accounts = tuple(
        ProjectAccountView(
            account_entity_id=str(row["id"]),
            name=str(row["canonical_name"]),
            domain=str(row["primary_domain"]) if row["primary_domain"] is not None else None,
            # No job is "never researched", which is what a born job would say too.
            research_status=str(row["research_status"] or "not_started"),
            refreshing=bool(row["refreshing"]),
            added_via=str(row["added_via"]),
            added_at=row["added_at"].isoformat(),
        )
        for row in rows
    )
    return ProjectAccountsPage(project_id=project_id, total=total, accounts=accounts)


# =================================================================================================
# read 2: one account's research
# =================================================================================================


class AccountOverviewSection(BaseModel, frozen=True):
    """One written section of an account's overview page, as it was stored."""

    section_key: str
    #: ``display_block.body_json`` as JSON text, capped at :data:`BODY_CHARS`. Text rather than a
    #: nested object because the stored body has no bound of its own — nothing in the display
    #: package limits how many items a section holds or how long one item is — and an unbounded
    #: blob is context the model pays for on every later turn of the thread.
    body_text: str
    #: The body was longer than the cap and the tail is not here.
    body_truncated: bool
    cited_claim_ids: tuple[str, ...]
    generated_at: str


class AccountClaimView(BaseModel, frozen=True):
    """One live claim about an account: the value, and what stands behind it."""

    claim_id: str
    field_key: str
    value: Any
    source_url: str | None
    #: The evidence span, clipped — a quote is here to be *checked*, not reproduced whole. A
    #: clipped span ends in ``…`` so a partial quote is never presented as a complete one.
    evidence: str
    #: The span was longer than :data:`EVIDENCE_CHARS`; what is here is its opening.
    evidence_truncated: bool
    tier: int
    #: ``claim.verification_status`` — ``unverified`` / ``verified`` / ``rejected``. Served so the
    #: model can say *how* a fact is known, not only what it is.
    verification_status: str | None
    #: ``claim.outreach_safe`` — false rows never reach here; the field carries the fact anyway so
    #: the shape does not change if the gate ever admits a restricted section.
    outreach_safe: bool | None
    collected_at: str


@dataclass(frozen=True, slots=True)
class AccountResearch:
    """What research holds about one account, in whichever of the two shapes was asked for."""

    account_entity_id: str
    account_name: str
    section: str
    overview: tuple[AccountOverviewSection, ...]
    claims: tuple[AccountClaimView, ...]
    truncated: bool
    #: How many live claims the display gate held back, by reason: ``sensitive``, ``unverified``,
    #: ``outreach_unsafe``. Counted rather than silently dropped, exactly as ``SectionInput`` does
    #: for the page — an empty answer with a count is a fact; an empty answer alone is a lie.
    excluded: dict[str, int]
    #: Where this page started in the account's servable claims (``0`` for the overview).
    offset: int
    #: Where the next page starts, or ``None`` when this page ends the list.
    next_offset: int | None
    #: The account's claim families with their servable counts — the prefixes a narrowed read
    #: may ask for. The whole account's, never this page's: a narrowed read still says what
    #: else is there, so a wrong guess costs one call rather than a series of them.
    prefixes: dict[str, int]


#: The hard ceiling on one claims read, for the same reason as :data:`MAX_ACCOUNTS`: a researched
#: account can hold hundreds of claims, and the model pays for every one of them on every later
#: turn. Over the cap the read says so (``truncated``) instead of quietly dropping the tail.
MAX_CLAIMS = 120

#: An evidence span is a quotation the reader may *check*; a whole article is not. Clipped rather
#: than dropped, because a truncated quote still tells the reader what kind of sentence it came
#: from — and the full span is one evidence read away. A clipped span ends with the ellipsis and
#: never exceeds this length, so the marker costs a character of the quote rather than adding one.
EVIDENCE_CHARS = 240

#: The cap on one overview section's serialized body. The stored body is ``{intro, items, checks,
#: cited_flags, cost_usd, call:{…}}`` and nothing in the display package bounds ``items`` — so the
#: honest answer to "how large can a section be?" was "unbounded" until this.
BODY_CHARS = 6000

#: The budget for one read's ``references``. The runtime records every governed result as a
#: ``GovernedOperationReceipt`` whose canonical ``reference_values`` must stay under 16 KiB
#: (``clue_agents/execution.py``); a result over it is discarded *after* the read ran, which is
#: how 72 claims became "the agent cannot read this account" on 2026-09-13. 12 KiB leaves room
#: for the envelope fields (ids, name, counts) and for the receipt's own wrapper.
READ_REFERENCES_BUDGET_BYTES = 12 * 1024


def receipt_bytes(value: object) -> int:
    """How many bytes ``value`` occupies in a receipt — the receipt's own encoding, so the bound
    measured here is the bound the runtime enforces."""

    return len(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    )


def _take_within_budget(items: Sequence[dict[str, Any]], *, budget: int) -> tuple[int, bool]:
    """How many leading ``items`` fit in ``budget`` bytes when encoded as one JSON array.

    Always admits at least one item (a single over-budget item is the caller's to clip), and
    returns whether anything was left out. Linear, not bisected: pages are a few dozen items.
    """

    if not items:
        return 0, False
    used = 2  # the array's brackets
    count = 0
    for item in items:
        size = receipt_bytes(item) + (1 if count else 0)  # the comma
        if count and used + size > budget:
            break
        used += size
        count += 1
    return count, count < len(items)


#: What a clipped string ends with. One character, so the cap is the cap.
_ELLIPSIS = "…"

_OVERVIEW_PAGE = "overview"


def _clip(value: str, limit: int) -> tuple[str, bool]:
    """``value`` within ``limit`` characters, and whether anything was cut.

    The ellipsis replaces the last kept character rather than following it: a caller that trusts
    the cap must be able to trust it, marker included.
    """

    if len(value) <= limit:
        return value, False
    return value[: limit - 1] + _ELLIPSIS, True


#: The account, as this workspace may see it. ``merged_into IS NULL`` refuses a merge loser by
#: name rather than serving the wrong company's research under the id the caller asked about.
_ACCOUNT_IN_WORKSPACE = text(
    """
    SELECT id, canonical_name FROM account_entity
    WHERE id = :id AND workspace_id = :ws AND merged_into IS NULL
    """
)


async def _account_in_workspace(
    conn: AsyncConnection, *, workspace_id: str, account_entity_id: str
) -> tuple[UUID, str]:
    """The account's id and name, or the refusal that says it is not ours to read."""

    try:
        account_uuid = UUID(account_entity_id)
    except ValueError:
        # A malformed id is indistinguishable from an absent one on purpose: both mean "there is
        # no such account here", and the model does not need to learn the id format from an error.
        raise Arv2ReadRefused(
            "account_not_found", f"no account {account_entity_id} in this workspace"
        ) from None
    row = (
        (await conn.execute(_ACCOUNT_IN_WORKSPACE, {"id": account_uuid, "ws": workspace_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise Arv2ReadRefused(
            "account_not_found", f"no account {account_entity_id} in this workspace"
        )
    return account_uuid, str(row["canonical_name"])


async def _overview_sections(
    conn: AsyncConnection, *, workspace_id: str, account_uuid: UUID
) -> tuple[tuple[AccountOverviewSection, ...], bool]:
    """The account's written overview in the order the overview page itself serves it, bounded by
    the receipt's budget, plus whether anything was left out.

    :data:`BODY_CHARS` bounds one section; nothing bounded the *page*, and a handful of capped
    sections is past the receipt on its own. What fits is served, and the cut is said out loud.
    """

    blocks = await live_blocks(
        conn,
        workspace_id=workspace_id,
        subject_kind="account",
        subject_id=str(account_uuid),
        page=_OVERVIEW_PAGE,
    )
    if not blocks:
        raise Arv2ReadRefused(
            "overview_not_written",
            "this account's overview has not been written yet; read section='claims' or open "
            "the account in the app",
        )
    # The recipes are the page's own running order (this workspace's overrides included), so the
    # agent reads the sections in the order the marketer sees them. A block whose section the
    # recipes no longer carry still gets served — it was written, so it is research — and sorts
    # after the known ones by key, which is also the whole order when no recipes are loaded.
    recipes = await read_recipes(conn, _OVERVIEW_PAGE, workspace_id=workspace_id)
    position = {recipe.section_key: index for index, recipe in enumerate(recipes)}
    ordered = sorted(
        blocks.values(),
        key=lambda block: (position.get(block.section_key, len(position)), block.section_key),
    )
    sections: list[AccountOverviewSection] = []
    for block in ordered:
        # ``sort_keys`` so two attempts of one turn serialize identical bytes, and
        # ``ensure_ascii=False`` so a quote the writer used stays the character the human typed.
        body_text, body_truncated = _clip(
            json.dumps(block.body_json, sort_keys=True, ensure_ascii=False), BODY_CHARS
        )
        sections.append(
            AccountOverviewSection(
                section_key=block.section_key,
                body_text=body_text,
                body_truncated=body_truncated,
                cited_claim_ids=block.cited_claim_ids,
                generated_at=block.generated_at.isoformat(),
            )
        )
    fitted, cut = _take_within_budget(
        [section.model_dump() for section in sections], budget=READ_REFERENCES_BUDGET_BYTES
    )
    if fitted == 1 and cut:
        # The first section is all that fits. Clip its body to what the budget actually leaves it
        # — a section whose own body is over budget would otherwise be served whole and thrown
        # away by the receipt, which is the bug this bound exists for. When the body already fits
        # the room, ``_clip`` is a no-op and the section is served exactly as it was built.
        head = sections[0]
        room = READ_REFERENCES_BUDGET_BYTES - receipt_bytes({**head.model_dump(), "body_text": ""})
        body_text, body_clipped = _clip(head.body_text, max(room, 200))
        sections[0] = head.model_copy(
            update={
                "body_text": body_text,
                "body_truncated": head.body_truncated or body_clipped,
            }
        )
    return tuple(sections[:fitted]), cut


def _is_sensitive(claim: Claim) -> bool:
    return claim.use_class is UseClass.SENSITIVE


def claim_prefixes(claims: Iterable[Claim]) -> dict[str, int]:
    """The claim families on an account: the first two dotted segments of each field key, with
    a count.

    Two segments, so ``account.resonance.culture`` and ``account.resonance.frustrations`` are
    one family while ``core.legal_name`` — which has no third segment — is its own. Sorted by
    count, then name, so the model reads the biggest family first.
    """

    counts: Counter[str] = Counter(
        ".".join(str(claim.field_key).split(".")[:2]) for claim in claims
    )
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _is_unverified_synthesis(claim: Claim) -> bool:
    """Under a verifying posture, an unjudged tier-4 synthesis is not a fact yet."""

    return claim.source_tier == 4 and claim.verification_status is not VerificationStatus.VERIFIED


async def _account_claims(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_uuid: UUID,
    field_prefix: str | None,
    settings: Settings,
    offset: int,
    limit: int,
) -> tuple[tuple[AccountClaimView, ...], bool, dict[str, int], int | None, dict[str, int]]:
    """One page of the account's live claims under ``field_prefix``, **gated exactly as the account
    page gates them**, bounded, plus whether more is left, what was held back, where the next
    page starts, and which claim families the account holds.

    The gate is :mod:`clue_api.arv2.display.gather`'s, predicate for predicate: a special-category
    value never leaves the store, an unjudged tier-4 synthesis is held back under a verifying
    posture, and an ``outreach_safe=false`` row is held back outright (this read has no restricted
    section to put one in). Without it the agent could tell a founder, in chat, a fact the account
    page deliberately refuses to print — and call it verified, because the tool said so.

    Exclusions are **counted, not hidden**: an account whose every claim is held back comes back
    with an empty list and a non-zero ``excluded``, which says "there is something here and you may
    not have it" rather than "there is nothing here". The gate runs over the whole account
    *before* ``field_prefix`` narrows it, so ``excluded`` counts the account rather than the
    matching subset — and the families it reports are the account's, which is the point: a read
    that guessed the wrong prefix is answered with the right ones instead of with a bare no.

    The page is bounded twice: by ``limit`` — what the caller asked for, itself capped at
    :data:`MAX_CLAIMS` — and by :data:`READ_REFERENCES_BUDGET_BYTES`, the receipt's own encoding,
    which is the binding one on a real account. A page ends at whichever comes first. Whatever does
    not fit is not dropped: the next offset says where to continue.

    The claims read spans every project of the workspace that researched this account: the store
    holds account truth, not a per-project lens.
    """

    # Scoped by the claim store's own tenant filter, never by a hand-written workspace predicate:
    # the scope object is the one place that knows public-footprint claims are shared and private
    # ones are not.
    claims = await claims_for_entities(
        conn,
        [EntityId(account_uuid)],
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    if not claims:
        raise Arv2ReadRefused("account_not_researched", "no claims about this account yet")
    # ``claims_for_entities`` already orders by ``(field_key, collected_at DESC, id)``, which is
    # the grouping the agent reads: one field's newest value first.
    #
    # The gate runs first and ``field_prefix`` narrows second, so the families below are the
    # account's *servable* ones — never a family made entirely of claims the caller may not have.
    excluded = {"sensitive": 0, "unverified": 0, "outreach_unsafe": 0}
    gated: list[Claim] = []
    for claim in claims:
        if _is_sensitive(claim):
            excluded["sensitive"] += 1
            continue
        if settings.verification_enabled and _is_unverified_synthesis(claim):
            excluded["unverified"] += 1
            continue
        if not claim.outreach_safe:
            excluded["outreach_unsafe"] += 1
            continue
        gated.append(claim)

    prefixes = claim_prefixes(gated)
    kept = [
        claim for claim in gated if field_prefix is None or claim.field_key.startswith(field_prefix)
    ]
    if field_prefix is not None and not kept:
        # Only a *narrowed* read refuses: an unnarrowed one whose every claim is held back is the
        # empty-list-with-counts answer promised above, not a missing prefix.
        #
        # A distinct code: the account IS researched, and saying otherwise because one prefix came
        # back empty is a false statement about the account in the machine-readable half. The
        # families come with it — the 2026-09-13 turn asked for 'firmographic', was told only
        # that nothing matched, and guessed again.
        listed = ", ".join(f"{name} ({count})" for name, count in list(prefixes.items())[:12])
        raise Arv2ReadRefused(
            "no_claims_under_prefix",
            f"this account has claims, but none under {field_prefix!r}; its families are: {listed}",
        )

    if offset >= len(kept) and offset > 0:
        # An offset past the end is the caller's mistake, not an empty account: answering it with
        # "no claims" would be a false statement about an account that has some.
        raise Arv2ReadRefused(
            "offset_past_end",
            f"this account has {len(kept)} servable claims; offset {offset} is past the end",
        )
    window = kept[offset : offset + limit]
    views: list[AccountClaimView] = []
    for claim in window:
        evidence, evidence_truncated = _clip(claim.evidence_span or "", EVIDENCE_CHARS)
        views.append(
            AccountClaimView(
                claim_id=str(claim.id),
                field_key=str(claim.field_key),
                value=claim.value_json,
                source_url=claim.source_url,
                evidence=evidence,
                evidence_truncated=evidence_truncated,
                tier=int(claim.source_tier),
                verification_status=str(claim.verification_status),
                outreach_safe=bool(claim.outreach_safe),
                collected_at=claim.collected_at.isoformat(),
            )
        )
    fitted, cut = _take_within_budget(
        [view.model_dump() for view in views], budget=READ_REFERENCES_BUDGET_BYTES
    )
    served = tuple(views[:fitted])
    end = offset + len(served)
    truncated = cut or end < len(kept)
    return served, truncated, excluded, (end if truncated else None), prefixes


async def read_account_research(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_entity_id: str,
    section: str,
    settings: Settings,
    field_prefix: str | None = None,
    offset: int = 0,
    limit: int = MAX_CLAIMS,
) -> AccountResearch:
    """What research found about one account: its written overview, or its live claims.

    The two sections answer two different questions — "what do we say about them?" and "what do we
    actually know, and who says so?" — so one read never serves both: the unasked half is empty,
    and an unwritten overview is a refusal rather than an account that looks unresearched.

    Claims are paged by ``offset`` under two ceilings — ``limit``, what the caller asked for, and
    the receipt's byte budget — and the page ends at whichever binds first. ``limit`` defaults to
    :data:`MAX_CLAIMS`, which is the shape ``read_account_research@1`` asks for: that version has
    no ``limit`` of its own, so the budget alone bounds its page, exactly as it always did.

    The overview is not paged (a cut overview tells the model to read the claims instead), so an
    offset on it is refused rather than ignored, and ``limit`` — like ``field_prefix`` — says
    nothing about it.
    """

    account_uuid, name = await _account_in_workspace(
        conn, workspace_id=workspace_id, account_entity_id=account_entity_id
    )
    overview: tuple[AccountOverviewSection, ...] = ()
    claims: tuple[AccountClaimView, ...] = ()
    truncated = False
    excluded = {"sensitive": 0, "unverified": 0, "outreach_unsafe": 0}
    next_offset: int | None = None
    prefixes: dict[str, int] = {}
    if section == "overview":
        if offset != 0:
            raise Arv2ReadRefused("offset_not_paged", "the overview is not paged; omit offset")
        overview, truncated = await _overview_sections(
            conn, workspace_id=workspace_id, account_uuid=account_uuid
        )
    else:
        claims, truncated, excluded, next_offset, prefixes = await _account_claims(
            conn,
            workspace_id=workspace_id,
            account_uuid=account_uuid,
            field_prefix=field_prefix,
            settings=settings,
            offset=offset,
            limit=limit,
        )
    return AccountResearch(
        account_entity_id=str(account_uuid),
        account_name=name,
        section=section,
        overview=overview,
        claims=claims,
        truncated=truncated,
        excluded=excluded,
        offset=offset,
        next_offset=next_offset,
        prefixes=prefixes,
    )


# =================================================================================================
# read 3: one discovery run
# =================================================================================================


class DiscoveryCandidateView(BaseModel):
    """One company a discovery run surfaced, with the verdict the verifier gave it."""

    #: ``serialize_by_alias`` is load-bearing, not decoration: the runner's canonical form is
    #: ``model_dump(mode="json")`` with no ``by_alias``, so without it the durable, journaled copy
    #: of a result would say ``pass_`` while the live result said ``pass``. ``populate_by_name``
    #: keeps the Python constructor call ``DiscoveryCandidateView(pass_=...)`` working.
    model_config = ConfigDict(frozen=True, populate_by_name=True, serialize_by_alias=True)

    name: str
    domain: str
    #: Which §4 pass surfaced it — ``strict`` (the full criteria) or ``relaxed`` (the widened
    #: re-search). ``pass`` is the schema's word on both sides of the wire; the trailing underscore
    #: is Python's. The runner re-validates a dumped result in JSON mode, so the model must accept
    #: what it serializes — the 2026-09-13 live defect was a serialization-only alias.
    pass_: str = Field(
        validation_alias=AliasChoices("pass", "pass_"),
        serialization_alias="pass",
    )
    #: ``arv2_discovery_candidate.disposition``: ``pending`` until verified, then ``pass`` /
    #: ``partial`` / ``unclear`` / ``duplicate_of_existing`` / ``not_chosen_before``.
    disposition: str
    #: The human's approval — ``approved``, or nothing at all. There is no recorded rejection.
    decision: str | None
    fit: float | None


@dataclass(frozen=True, slots=True)
class DiscoveryRunView:
    """One discovery run: what was asked for, what came back, and who is on the shortlist."""

    run_id: str
    status: str
    icp_key: str
    icp_version: int
    target_count: int
    asked: int | None
    found: int
    verified: int
    shown: int
    approved: int
    relaxed_requested: bool
    started_at: str | None
    finished_at: str | None
    candidates: tuple[DiscoveryCandidateView, ...]
    candidate_total: int
    #: Where this page started in the run's ordered candidates.
    offset: int
    #: Where the next page starts, or ``None`` when this page ends the list — the same walk the
    #: claims read offers, so "read to the end" is one habit rather than two.
    next_offset: int | None


#: The hard ceiling on one candidate list, for the same reason as :data:`MAX_ACCOUNTS`: a run can
#: surface dozens of companies and every one of them is context the model pays for on every later
#: turn. ``candidate_total`` always reports the whole run, so a short list is never a small run.
MAX_CANDIDATES = 50

#: The project's newest discovery run. ``created_at DESC, run_id DESC`` is the project card's own
#: ordering (``project_status._LATEST_DISCOVERY``), so the agent and the app agree on which run is
#: "the" run when two were launched in the same instant.
_LATEST_DISCOVERY_RUN = text(
    """
    SELECT run_id FROM arv2_discovery_run
    WHERE workspace_id = :ws AND project_id = :project
    ORDER BY created_at DESC, run_id DESC
    LIMIT 1
    """
)

#: The three tallies a human asks for by other names: "how many did we check?", "how many are
#: worth looking at?", "how many did we take?". "Checked" is
#: :data:`~clue_api.arv2.discovery_store.VERIFIED_PREDICATE` — a candidate with a verdict — shared
#: with ``status.md`` and the Target-accounts poll, because the pre-spend dispositions
#: (``duplicate_of_existing``, ``not_chosen_before``) are stamped before any gate is asked and
#: counting them as verified made the agent say the platform had checked companies it had skipped.
#: Every sub-select names the tenant: ``arv2_discovery_candidate.run_id`` is a single-column FK, so
#: nothing in the schema forces a candidate's workspace to equal its run's.
_DISCOVERY_COUNTS = text(
    f"""
    SELECT
      (SELECT count(*) FROM arv2_discovery_candidate c
        WHERE c.run_id = :run AND c.workspace_id = :ws
          AND {VERIFIED_PREDICATE}) AS verified,
      (SELECT count(*) FROM arv2_discovery_candidate c
        WHERE c.run_id = :run AND c.workspace_id = :ws
          AND c.disposition = ANY(:shown)) AS shown,
      (SELECT count(*) FROM arv2_discovery_candidate c
        WHERE c.run_id = :run AND c.workspace_id = :ws
          AND c.decision = 'approved') AS approved
    """
)


def _candidate_order(candidate: CandidateRow) -> tuple[int, bool, float, str]:
    """Shown first, then best fit, then by name — the shortlist a human would read top-down.

    A candidate with no fit sorts *after* every scored one rather than as a zero: an unscored
    company is unknown, not bad, and a truncated list must not drop scored companies for it.
    """

    return (
        0 if candidate.disposition in SHOWN_DISPOSITIONS else 1,
        candidate.fit is None,
        -(candidate.fit or 0.0),
        candidate.name,
    )


async def read_discovery_run(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    run_id: str | None,
    limit: int,
    offset: int = 0,
) -> DiscoveryRunView:
    """One discovery run of this project — the newest, or the one named — with its candidates.

    The project is checked first, so "that run is not this project's" and "that project is not
    yours" stay two different answers, and a run of *another* project is refused by name rather
    than served to a caller who happened to guess its id.

    ``offset``/``limit`` walk the ordered candidates, and ``next_offset`` names where to continue —
    a run of sixty companies is read in pages instead of being silently cut at the first twenty-
    five. ``candidate_total`` is the whole run on every page, so a page never reads as a small run.
    """

    project = await get_project(conn, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise Arv2ReadRefused("project_not_found", f"no project {project_id} in this workspace")
    if run_id is None:
        latest = (
            await conn.execute(_LATEST_DISCOVERY_RUN, {"ws": workspace_id, "project": project_id})
        ).scalar_one_or_none()
        if latest is None:
            raise Arv2ReadRefused("no_discovery_run", "this project has not run discovery yet")
        run_uuid = UUID(str(latest))
    else:
        try:
            run_uuid = UUID(run_id)
        except ValueError:
            # A malformed id and an absent one read alike: both mean "there is no such run here".
            raise Arv2ReadRefused(
                "discovery_run_not_found", f"no discovery run {run_id} in this project"
            ) from None
    run = await read_discovery_run_row(conn, run_id=run_uuid)
    # The store's read is not scoped, so the scope is checked here: a run of another workspace or
    # another project of this workspace is absent, not readable.
    if run is None or run.workspace_id != workspace_id or run.project_id != project_id:
        raise Arv2ReadRefused(
            "discovery_run_not_found", f"no discovery run {run_uuid} in this project"
        )
    counts = (
        (
            await conn.execute(
                _DISCOVERY_COUNTS,
                {"run": run_uuid, "ws": workspace_id, "shown": list(SHOWN_DISPOSITIONS)},
            )
        )
        .mappings()
        .one()
    )
    # ``list_candidates`` filters on ``run_id`` alone, and the FK is single-column — so the rows
    # are scoped HERE, the same way the tallies above are. The two halves of one answer must agree
    # about whether the FK is trusted: a row whose workspace is not the run's would otherwise be
    # listed and counted into ``candidate_total`` while being excluded from ``shown``.
    candidates = sorted(
        (
            candidate
            for candidate in await list_candidates(conn, run_id=run_uuid)
            if candidate.workspace_id == workspace_id
        ),
        key=_candidate_order,
    )
    window = candidates[offset : offset + limit]
    end = offset + len(window)
    # A window that advanced nothing cannot name a next page: ``read_discovery_run@1``'s
    # tallies-only shape (``candidate_limit=0``) would otherwise point a caller back at the very
    # offset it just read, and an offset past the end would promise a page that is not there.
    next_offset = end if window and end < len(candidates) else None
    return DiscoveryRunView(
        run_id=str(run.run_id),
        status=str(run.status),
        icp_key=run.icp_key,
        icp_version=int(run.icp_version),
        target_count=int(run.target_count),
        asked=None if run.asked is None else int(run.asked),
        # A run still in flight has neither counter yet; "found 0 so far" is the honest reading.
        found=int(run.found_strict or 0) + int(run.found_relaxed or 0),
        verified=int(counts["verified"]),
        shown=int(counts["shown"]),
        approved=int(counts["approved"]),
        relaxed_requested=bool(run.relaxed_requested),
        started_at=None if run.started_at is None else run.started_at.isoformat(),
        finished_at=None if run.finished_at is None else run.finished_at.isoformat(),
        candidates=tuple(
            DiscoveryCandidateView(
                name=candidate.name,
                domain=candidate.domain,
                pass_=str(candidate.pass_),
                disposition=str(candidate.disposition),
                decision=candidate.decision,
                fit=None if candidate.fit is None else float(candidate.fit),
            )
            for candidate in window
        ),
        # The whole run, never the page: "the top 25 of 60" is one measurement and its remainder.
        candidate_total=len(candidates),
        offset=offset,
        next_offset=next_offset,
    )


# =================================================================================================
# the service seam + its production implementation
# =================================================================================================


class Arv2ReadService(Protocol):
    """What the read tools call. One transaction per call is the implementation's business.

    One seam serves both versions of the paged reads: ``offset``/``limit`` are always passed
    explicitly, and it is the *tool* that decides what its own contract asks for — ``@1``, which
    has no paging input, asks for the substrate's own ceiling, and ``@2`` asks for what the model
    requested. A seam with a default would let those two disagree quietly.
    """

    async def list_project_accounts(
        self,
        *,
        workspace_id: str,
        project_id: str,
        limit: int,
        query: str | None,
        offset: int,
    ) -> ProjectAccountsPage: ...

    async def read_account_research(
        self,
        *,
        workspace_id: str,
        account_entity_id: str,
        section: str,
        field_prefix: str | None,
        offset: int,
        limit: int,
    ) -> AccountResearch: ...

    async def read_discovery_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        run_id: str | None,
        offset: int,
        limit: int,
    ) -> DiscoveryRunView: ...


class DbArv2ReadService:
    """The production service: one transaction per read, and nothing else — reads need no storage
    and no queue, so this composes on every deployment that has a database.

    It does need ``settings``, for one reason: the claims read mirrors the account page's display
    gate, and one arm of that gate (hold back an unjudged tier-4 synthesis) is only armed under a
    verifying posture. Reading the flag from the same ``Settings`` the page reads is what keeps
    chat and app telling one story rather than two.
    """

    def __init__(self, *, settings: Settings, conn_factory: ConnFactory = transaction) -> None:
        self._settings = settings
        self._conn_factory = conn_factory

    async def list_project_accounts(
        self,
        *,
        workspace_id: str,
        project_id: str,
        limit: int,
        query: str | None,
        offset: int,
    ) -> ProjectAccountsPage:
        async with self._conn_factory() as conn:
            return await list_project_accounts(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                limit=limit,
                query=query,
                offset=offset,
            )

    async def read_account_research(
        self,
        *,
        workspace_id: str,
        account_entity_id: str,
        section: str,
        field_prefix: str | None,
        offset: int,
        limit: int,
    ) -> AccountResearch:
        async with self._conn_factory() as conn:
            return await read_account_research(
                conn,
                workspace_id=workspace_id,
                account_entity_id=account_entity_id,
                section=section,
                field_prefix=field_prefix,
                settings=self._settings,
                offset=offset,
                limit=limit,
            )

    async def read_discovery_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        run_id: str | None,
        offset: int,
        limit: int,
    ) -> DiscoveryRunView:
        async with self._conn_factory() as conn:
            return await read_discovery_run(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                run_id=run_id,
                offset=offset,
                limit=limit,
            )


def _not_composed() -> tuple[PreconditionFailure, ...]:
    return (
        PreconditionFailure(
            reason_code="arv2_reads_not_composed",
            message="the ARV2 read surface is not composed on this deployment",
        ),
    )


# =================================================================================================
# the tools
# =================================================================================================


class ReadProjectAccountsInput(ToolInput):
    project_id: str
    limit: int = Field(default=100, ge=1, le=MAX_ACCOUNTS)
    #: A name or domain fragment, case-insensitive. Without it, an account past the first page is
    #: reachable only by paging — and a model that reads one short page and stops would tell the
    #: human their account is not in the project.
    query: str | None = Field(default=None, max_length=120)
    #: How many rows to skip. With ``limit`` this walks a project larger than one page.
    offset: int = Field(default=0, ge=0)


class ReadProjectAccountsOutput(ToolOutput):
    project_id: str
    total: int
    #: The project's accounts. ``total`` is the whole **filtered** membership; ``len(accounts)`` is
    #: the page, so the model can say "showing 100 of 240" rather than guessing at the rest.
    accounts: tuple[ProjectAccountView, ...]


class ReadProjectAccountsTool(Tool):
    """List one project's accounts with each account's research status."""

    name = "read_project_accounts"
    version = "1"
    model_description = (
        "List the accounts in one project with each account's research status (not_started, "
        "in_progress, needs_review, completed, suspended) and how it joined the project. Filter "
        "by name or domain to find one account; page with limit and offset when total is larger "
        "than the page you received. Read this before saying how many accounts there are, which "
        "are researched, or before proposing more discovery. Effect-free. "
        "Manual: .deepagent/skills/manual-tools/v2/SKILL.md#read_project_accounts"
    )
    input_model: ClassVar[type[ToolInput]] = ReadProjectAccountsInput
    output_model: ClassVar[type[ToolOutput]] = ReadProjectAccountsOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="current project_account rows + each account's latest ARV2 account job",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_id", "limit", "query", "offset")
    )
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5).
    pin_requirements = ("project",)

    def __init__(self, service: Arv2ReadService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        del inputs, ctx
        return _not_composed() if self._service is None else ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadProjectAccountsInput)
        assert self._service is not None
        try:
            page = await self._service.list_project_accounts(
                # The tenant is AMBIENT authority, never model-authored.
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                limit=inputs.limit,
                query=inputs.query,
                offset=inputs.offset,
            )
        except Arv2ReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        output = ReadProjectAccountsOutput(
            project_id=page.project_id,
            total=page.total,
            accounts=page.accounts,
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())


class ReadAccountResearchInput(ToolInput):
    account_entity_id: str
    section: Literal["overview", "claims"] = "overview"
    #: Claims only: ``account.resonance`` narrows a researched account's claims to one family
    #: rather than making the model read all of them to find three.
    field_prefix: str | None = Field(default=None, max_length=80)
    #: Claims only: continue from ``next_offset`` of the previous page. ``0`` starts over.
    offset: int = Field(default=0, ge=0)


class ReadAccountResearchOutput(ToolOutput):
    account_entity_id: str
    account_name: str
    section: str
    #: The written sections when ``section='overview'``, else empty.
    overview: tuple[AccountOverviewSection, ...]
    #: The account's servable claims when ``section='claims'``, else empty.
    claims: tuple[AccountClaimView, ...]
    #: More exists than this page holds: continue with ``offset = next_offset`` (claims), or read
    #: the claims when a long overview was cut.
    truncated: bool
    #: What the account pages' own gate held back, by reason: ``sensitive``, ``unverified``,
    #: ``outreach_unsafe``. A non-zero count means "there is more here, and it is not servable".
    excluded: dict[str, int]
    #: Where this page started in the account's servable claims.
    offset: int
    #: Where the next page starts, or ``None`` when this page ends the list.
    next_offset: int | None
    #: The account's claim families with their servable counts.
    prefixes: dict[str, int]


class ReadAccountResearchTool(Tool):
    """Read one account's written overview, or the claims underneath it."""

    name = "read_account_research"
    version = "1"
    model_description = (
        "Read what research found about one account. section='overview' returns the written "
        "overview sections (prose citing claim ids); when the overview is not written yet the "
        "read refuses with overview_not_written — then read section='claims'. section='claims' "
        "returns the claims the account pages show, one page at a time: follow next_offset "
        "until it is null, or narrow with field_prefix to one of the families listed in "
        "'prefixes' (e.g. 'account.resonance', 'core'). Sensitive, unverified tier-4 and "
        "outreach-unsafe claims are held back and counted in 'excluded'. Read this before "
        "saying anything specific about an account. Effect-free. "
        "Manual: .deepagent/skills/manual-tools/v2/SKILL.md#read_account_research"
    )
    input_model: ClassVar[type[ToolInput]] = ReadAccountResearchInput
    output_model: ClassVar[type[ToolOutput]] = ReadAccountResearchOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="the account's live display_block rows and its live claims",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("account_entity_id", "section", "field_prefix", "offset")
    )
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5).
    pin_requirements = ("project",)

    def __init__(self, service: Arv2ReadService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        del inputs, ctx
        return _not_composed() if self._service is None else ()

    def _claims_limit(self, inputs: ReadAccountResearchInput) -> int:
        """How many claims this version's contract asks for.

        ``@1`` has no ``limit`` input and never will — a profile pins this contract's digest — so
        it asks for the substrate's own ceiling and is bounded by the receipt's byte budget alone,
        exactly as it was before the paged ``@2`` existed. ``@2`` overrides this with what the
        model asked for.
        """

        del inputs
        return MAX_CLAIMS

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadAccountResearchInput)
        assert self._service is not None
        try:
            research = await self._service.read_account_research(
                # The tenant is AMBIENT authority, never model-authored.
                workspace_id=ctx.workspace_id,
                account_entity_id=inputs.account_entity_id,
                section=inputs.section,
                field_prefix=inputs.field_prefix,
                offset=inputs.offset,
                limit=self._claims_limit(inputs),
            )
        except Arv2ReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        output = ReadAccountResearchOutput(
            account_entity_id=research.account_entity_id,
            account_name=research.account_name,
            section=research.section,
            overview=research.overview,
            claims=research.claims,
            truncated=research.truncated,
            excluded=research.excluded,
            offset=research.offset,
            next_offset=research.next_offset,
            prefixes=research.prefixes,
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())


class ReadAccountResearchV2Input(ReadAccountResearchInput):
    """``@1``'s inputs plus the page size the model may ask for.

    A subclass rather than a copy: the two versions read the same rows and mean the same thing by
    ``section``, ``field_prefix`` and ``offset``, and ``@1``'s own schema — pinned by the promoted
    profile's digest — must not move because ``@2`` gained a field.
    """

    #: Claims only: how many claims this page may hold. The receipt's byte budget is the other
    #: ceiling and usually the binding one, so a page may come back shorter than this and say so
    #: with ``next_offset``; asking for fewer is how a model reads three families cheaply instead
    #: of paying for a hundred claims it will not quote.
    limit: int = Field(default=40, ge=1, le=MAX_CLAIMS)


class ReadAccountResearchV2Tool(ReadAccountResearchTool):
    """``read_account_research@2``: ``@1`` with a caller-chosen page size.

    Everything else is ``@1``'s — the same service seam, the same refusals, the same gate, the
    same output shape (which already carried ``offset``/``next_offset``). Only the *input* moved,
    which is precisely why this is a new address: a changed input schema at ``@1`` would break the
    digest pin a promoted profile holds, and that pin is what notices a silent contract change.
    """

    version = "2"
    model_description = (
        "Read what research found about one account. section='overview' returns the written "
        "overview sections (prose citing claim ids); when the overview is not written yet the "
        "read refuses with overview_not_written — then read section='claims'. section='claims' "
        "returns the claims the account pages show, one page at a time: set limit for how many "
        "you want (default 40), follow next_offset until it is null, or narrow with field_prefix "
        "to one of the families listed in 'prefixes' (e.g. 'account.resonance', 'core'). A page "
        "can come back shorter than limit and still name a next_offset. Sensitive, unverified "
        "tier-4 and outreach-unsafe claims are held back and counted in 'excluded'. Read this "
        "before saying anything specific about an account. Effect-free. "
        "Manual: .deepagent/skills/manual-tools/v2/SKILL.md#read_account_research"
    )
    input_model: ClassVar[type[ToolInput]] = ReadAccountResearchV2Input
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("account_entity_id", "section", "field_prefix", "offset", "limit")
    )

    def _claims_limit(self, inputs: ReadAccountResearchInput) -> int:
        assert isinstance(inputs, ReadAccountResearchV2Input)
        return inputs.limit


class ReadDiscoveryRunInput(ToolInput):
    project_id: str
    #: Omitted means the project's newest run, which is what "how did discovery go?" means.
    run_id: str | None = None
    #: ``0`` asks for the tallies alone — the shape a "how many did we approve?" turn wants
    #: without paying for a company list it will not read.
    candidate_limit: int = Field(default=25, ge=0, le=MAX_CANDIDATES)


class ReadDiscoveryRunOutput(ToolOutput):
    run_id: str
    status: str
    icp_key: str
    icp_version: int
    #: How many accounts the human asked discovery for.
    target_count: int
    #: How many companies the long list was asked to return, once the provider was called.
    asked: int | None
    #: Strict plus relaxed — the companies the run actually brought back.
    found: int
    #: How many candidates the verifier actually judged against the ICP — the ones that carry a
    #: verdict. Companies skipped before any gate (already an account, surfaced and not chosen
    #: before) are NOT counted here; they are in ``candidate_total``.
    verified: int
    shown: int
    approved: int
    relaxed_requested: bool
    started_at: str | None
    finished_at: str | None
    #: The run's candidates, shown-first and best-fit-first.
    candidates: tuple[DiscoveryCandidateView, ...]
    #: The run's whole candidate count, so a bounded list never reads as a small run.
    candidate_total: int


class ReadDiscoveryRunTool(Tool):
    """Read one discovery run: what it asked for, what it found, and the top candidates."""

    name = "read_discovery_run"
    version = "1"
    model_description = (
        "Read the project's latest discovery run (or one by id): status, what was asked for and "
        "found, how many candidates the verifier judged against the ICP, how many were shown and "
        "approved, and the top candidates with their verdict. Read this before proposing another "
        "discovery, and to answer what discovery found. It approves nothing. Effect-free. "
        "Manual: .deepagent/skills/manual-tools/v2/SKILL.md#read_discovery_run"
    )
    input_model: ClassVar[type[ToolInput]] = ReadDiscoveryRunInput
    output_model: ClassVar[type[ToolOutput]] = ReadDiscoveryRunOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="the project's latest arv2_discovery_run row and its candidates",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_id", "run_id", "candidate_limit")
    )
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5).
    pin_requirements = ("project",)

    def __init__(self, service: Arv2ReadService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        del inputs, ctx
        return _not_composed() if self._service is None else ()

    async def _read(
        self, *, project_id: str, run_id: str | None, offset: int, limit: int, ctx: ToolContext
    ) -> DiscoveryRunView:
        """The run, or a typed refusal — written once, because both versions read it the same way
        and differ only in which window they ask for."""

        assert self._service is not None
        try:
            return await self._service.read_discovery_run(
                # The tenant is AMBIENT authority, never model-authored.
                workspace_id=ctx.workspace_id,
                project_id=project_id,
                run_id=run_id,
                offset=offset,
                limit=limit,
            )
        except Arv2ReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused

    def _result(self, output: ReadDiscoveryRunOutput) -> ToolResult:
        # ``by_alias`` is what turns ``pass_`` back into the schema's ``pass``; it is the only
        # aliased field on this surface, so the whole dump takes it.
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(by_alias=True)
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadDiscoveryRunInput)
        run = await self._read(
            project_id=inputs.project_id,
            run_id=inputs.run_id,
            # ``@1`` has no offset: its one page starts at the top, which is what its contract has
            # always said. The whole run is still reported as ``candidate_total``.
            offset=0,
            limit=inputs.candidate_limit,
            ctx=ctx,
        )
        return self._result(ReadDiscoveryRunOutput(**_discovery_fields(run)))


class ReadDiscoveryRunV2Input(ToolInput):
    project_id: str
    #: Omitted means the project's newest run, which is what "how did discovery go?" means.
    run_id: str | None = None
    #: How many candidates to skip. With ``limit`` this walks a run larger than one page —
    #: continue from the previous page's ``next_offset``; ``0`` starts at the top.
    offset: int = Field(default=0, ge=0)
    #: How many candidates this page may hold, best first.
    limit: int = Field(default=25, ge=1, le=MAX_CANDIDATES)


class ReadDiscoveryRunV2Output(ReadDiscoveryRunOutput):
    """``@1``'s run report plus where this page sits in the run's candidates."""

    #: Where this page started in the run's ordered candidates.
    offset: int
    #: Where the next page starts, or ``None`` when this page ends the list.
    next_offset: int | None


class ReadDiscoveryRunV2Tool(ReadDiscoveryRunTool):
    """``read_discovery_run@2``: ``@1`` with the candidate list paged rather than cut.

    ``@1`` served the top ``candidate_limit`` companies and nothing else — a run of sixty was read
    as twenty-five, and the remaining thirty-five were reachable only by a number the tool never
    named. ``@2`` replaces that one input with ``offset``/``limit`` and reports ``next_offset``, so
    the rest of the run is reachable by following it to ``None``. The tallies, the ordering and
    every refusal are ``@1``'s, unchanged.

    A new address rather than an edit: ``@1``'s input schema is pinned by the promoted profile's
    digest, and that pin exists precisely to notice a contract that changed underneath it.
    """

    version = "2"
    model_description = (
        "Read the project's latest discovery run (or one by id): status, what was asked for and "
        "found, how many candidates the verifier judged against the ICP, how many were shown and "
        "approved, and the candidates with their verdict, best first. Page with offset and limit "
        "(default 25) and follow next_offset until it is null to see every candidate; "
        "candidate_total is the whole run on every page. Read this before proposing another "
        "discovery, and to answer what discovery found. It approves nothing. Effect-free. "
        "Manual: .deepagent/skills/manual-tools/v2/SKILL.md#read_discovery_run"
    )
    input_model: ClassVar[type[ToolInput]] = ReadDiscoveryRunV2Input
    output_model: ClassVar[type[ToolOutput]] = ReadDiscoveryRunV2Output
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_id", "run_id", "offset", "limit")
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadDiscoveryRunV2Input)
        run = await self._read(
            project_id=inputs.project_id,
            run_id=inputs.run_id,
            offset=inputs.offset,
            limit=inputs.limit,
            ctx=ctx,
        )
        return self._result(
            ReadDiscoveryRunV2Output(
                **_discovery_fields(run), offset=run.offset, next_offset=run.next_offset
            )
        )


def _discovery_fields(run: DiscoveryRunView) -> dict[str, Any]:
    """The run as both output versions carry it, mapped once so the two cannot drift."""

    return {
        "run_id": run.run_id,
        "status": run.status,
        "icp_key": run.icp_key,
        "icp_version": run.icp_version,
        "target_count": run.target_count,
        "asked": run.asked,
        "found": run.found,
        "verified": run.verified,
        "shown": run.shown,
        "approved": run.approved,
        "relaxed_requested": run.relaxed_requested,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "candidates": run.candidates,
        "candidate_total": run.candidate_total,
    }


def build_arv2_read_tools(service: Arv2ReadService | None) -> tuple[Tool, ...]:
    """The lane's read surface. Registered always; composed wherever there is a database.

    Registering it uncomposed is deliberate, for the reason its ARV2 neighbours give: the
    platform's tool surface stays complete (the authority audit sees every tool), and an agent that
    reaches for a read on a deployment without the lane gets the named ``arv2_reads_not_composed``
    refusal rather than an ``UnknownTool`` it cannot explain. Unlike its launching neighbours these
    three have no flag: they read rows that already exist and spend nothing to do it.
    """

    return (
        ReadProjectAccountsTool(service),
        ReadAccountResearchTool(service),
        ReadDiscoveryRunTool(service),
    )


def build_arv2_paged_read_tools(service: Arv2ReadService | None) -> tuple[Tool, ...]:
    """The two reads whose inputs learned to page, at their own addresses.

    Separate from :func:`build_arv2_read_tools` because these two are **not** their names' default
    alias yet: `head-of-abm@v55` pins the ``@1`` contracts, and a default that disagreed with the
    promoted profile's pin would hand an unversioned caller the version nobody holds — the same
    reasoning that kept ``open_icp_confirmation_gate@1`` the default until its profile moved. The
    grant, the recipe address and the alias move together in one later, reviewed step; until then
    these register frozen-and-ungranted beside their ``@1`` siblings, on the same composition
    (one service, one refusal code).
    """

    return (
        ReadAccountResearchV2Tool(service),
        ReadDiscoveryRunV2Tool(service),
    )
