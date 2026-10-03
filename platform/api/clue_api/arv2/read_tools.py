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

All four reads sit behind one :class:`Arv2ReadService` seam: one protocol the toolbelt tools
call, one :class:`DbArv2ReadService` that opens one transaction per call. The fourth,
``read_claims``, is the general query underneath the account read's fixed one: the same claims and
the same display gate, asked by field family, source tier, verification status or date, about an
account or a contact.

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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.arv2.discovery_store import (
    SHOWN_DISPOSITIONS,
    VERIFIED_PREDICATE,
    CandidateRow,
    list_candidates,
    list_searches,
)
from clue_api.arv2.discovery_store import read_discovery_run as read_discovery_run_row
from clue_api.arv2.display.blocks import live_blocks
from clue_api.arv2.display.recipes import Page, read_recipes
from clue_api.arv2.errors import Arv2Error
from clue_config import Settings
from clue_core import Claim, EntityId, UseClass, VerificationStatus
from clue_db import ConnFactory, transaction
from clue_obs.langfuse import tag_entities
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
    "ClaimsQueryPage",
    "DbArv2ReadService",
    "DiscoveryCandidateV3View",
    "DiscoveryCandidateView",
    "DiscoveryRunView",
    "ProjectAccountView",
    "ProjectAccountsPage",
    "ReadAccountResearchInput",
    "ReadAccountResearchOutput",
    "ReadAccountResearchTool",
    "ReadAccountResearchV2Input",
    "ReadAccountResearchV2Tool",
    "ReadClaimsInput",
    "ReadClaimsOutput",
    "ReadClaimsTool",
    "ReadDiscoveryRunInput",
    "ReadDiscoveryRunOutput",
    "ReadDiscoveryRunTool",
    "ReadDiscoveryRunV2Input",
    "ReadDiscoveryRunV2Output",
    "ReadDiscoveryRunV2Tool",
    "ReadDiscoveryRunV3Input",
    "ReadDiscoveryRunV3Output",
    "ReadDiscoveryRunV3Tool",
    "ReadProjectAccountsInput",
    "ReadProjectAccountsOutput",
    "ReadProjectAccountsTool",
    "build_arv2_paged_read_tools",
    "build_arv2_read_tools",
    "claim_prefixes",
    "claims_page",
    "gate_claims",
    "list_project_accounts",
    "parse_since",
    "read_account_research",
    "read_claims",
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
    ``no_claims_under_prefix``, ``offset_past_end``, ``discovery_run_not_found``,
    ``no_discovery_run``, ``entity_not_found``, ``since_invalid``.
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
    #: ``display_block.body_json`` as JSON text, whole. Text rather than a nested object because the
    #: stored body has no bound of its own; the overview pages by whole section instead, so a long
    #: overview spreads across reads rather than losing its tail.
    body_text: str
    #: This one section is larger than a whole page on its own, so its tail is not here. Every
    #: other section is served complete.
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
    #: Where this page started: a claim index for claims, a section index for the overview.
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

_OVERVIEW_PAGE: Page = "overview"


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


def _claim_ids_in(value: object) -> tuple[str, ...]:
    """Every ``claimIds`` entry inside one served section body, in first-seen order."""
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if key == "claimIds" and isinstance(item, list):
                    found.extend(str(claim_id) for claim_id in item)
                else:
                    walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return tuple(dict.fromkeys(found))


_PAGE_WRITTEN_AT = text(
    """
    SELECT updated_at FROM arv2_research_page_current
    WHERE workspace_id = :ws AND context_id = :context AND subject_kind = 'account'
      AND subject_id = :subject AND page = 'overview'
    """
)


async def _current_lane_overview(
    conn: AsyncConnection, *, workspace_id: str, account_uuid: UUID, project_id: str | None
) -> list[AccountOverviewSection] | None:
    """The overview the current research lane wrote for this account in this project, as the
    account page serves it; ``None`` when the account has no current-lane research at all.

    Incident 2026-09-29: this read used to consult only the legacy display lane (blocks with no
    research context), so every overview the current lane wrote was invisible and the tool
    answered ``overview_not_written`` for a page the marketer could open. The page is chosen
    exactly as the account screen chooses it (``select_quality_context``): the calling turn's
    project when the context names one, otherwise the account's only researched project.
    """

    from clue_api.arv2.quality_pages import read_page
    from clue_api.arv2.quality_read import select_quality_context

    selection = await select_quality_context(
        conn, workspace_id=workspace_id, subject_id=account_uuid, project_id=project_id
    )
    if selection is None:
        return None
    if selection.scope is None or selection.context_id is None:
        raise Arv2ReadRefused(
            "overview_not_written",
            "this account was researched in more than one project and this read names none of "
            "them; read section='claims' or open the account in the app",
        )
    try:
        page = await read_page(
            conn, selection.scope, context_id=selection.context_id, page=_OVERVIEW_PAGE
        )
    except ValueError:
        # A stopped or not-yet-started generation has no usable narrative (the account screen
        # shows an empty page in the same case).
        raise Arv2ReadRefused(
            "overview_not_written",
            "this account's overview has not been written yet; read section='claims' or open "
            "the account in the app",
        ) from None
    written_at = (
        await conn.execute(
            _PAGE_WRITTEN_AT,
            {"ws": workspace_id, "context": selection.context_id, "subject": account_uuid},
        )
    ).scalar_one_or_none()
    sections: list[AccountOverviewSection] = []
    for section in page["display_block"]["sections"]:
        # A section with no words is not served; one whose refresh is merely due still is (the
        # account screen shows it too, marked pending).
        if not section.get("intro") and not section.get("items"):
            continue
        body = {
            key: section[key]
            for key in ("h1", "intro", "items", "restricted")
            if key in section and section[key] not in (None, [])
        }
        sections.append(
            AccountOverviewSection(
                section_key=str(section["key"]),
                body_text=json.dumps(body, sort_keys=True, ensure_ascii=False),
                body_truncated=False,
                cited_claim_ids=_claim_ids_in(body),
                generated_at="" if written_at is None else written_at.isoformat(),
            )
        )
    if not sections:
        raise Arv2ReadRefused(
            "overview_not_written",
            "this account's overview has not been written yet; read section='claims' or open "
            "the account in the app",
        )
    return sections


async def _overview_sections(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_uuid: UUID,
    project_id: str | None = None,
) -> list[AccountOverviewSection]:
    """The account's whole written overview, every section complete, in the order the overview
    page itself serves it. :func:`_overview_page` cuts it into receipt-sized pages.

    The current research lane's project-scoped page is read first; the legacy display lane's
    unscoped blocks only when the account has no current-lane research.
    """

    current = await _current_lane_overview(
        conn, workspace_id=workspace_id, account_uuid=account_uuid, project_id=project_id
    )
    if current is not None:
        return current
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
    legacy: list[AccountOverviewSection] = []
    for block in ordered:
        # ``sort_keys`` so two attempts of one turn serialize identical bytes, and
        # ``ensure_ascii=False`` so a quote the writer used stays the character the human typed.
        legacy.append(
            AccountOverviewSection(
                section_key=block.section_key,
                body_text=json.dumps(block.body_json, sort_keys=True, ensure_ascii=False),
                body_truncated=False,
                cited_claim_ids=block.cited_claim_ids,
                generated_at=block.generated_at.isoformat(),
            )
        )
    return legacy


def _overview_page(
    sections: Sequence[AccountOverviewSection], *, offset: int
) -> tuple[tuple[AccountOverviewSection, ...], bool, int | None]:
    """One page of the overview: the whole sections from ``offset`` that fit the receipt's byte
    budget, whether more remain, and the offset the next page starts at.

    ``offset`` counts sections, so a page never splits one. The only section that is ever cut is
    one that is larger than a whole page by itself: it is served alone, clipped to the page, and
    says so with ``body_truncated`` — served whole, the receipt would discard the entire read.
    """

    if offset >= len(sections) and offset > 0:
        raise Arv2ReadRefused(
            "offset_past_end",
            f"this overview has {len(sections)} sections; offset {offset} is past the end",
        )
    rest = list(sections[offset:])
    fitted, _ = _take_within_budget(
        [section.model_dump() for section in rest], budget=READ_REFERENCES_BUDGET_BYTES
    )
    page = rest[:fitted]
    if page and receipt_bytes([page[0].model_dump()]) > READ_REFERENCES_BUDGET_BYTES:
        page[0] = _clip_section_to_page(page[0])
    end = offset + len(page)
    more = end < len(sections)
    return tuple(page), more, (end if more else None)


def _clip_section_to_page(section: AccountOverviewSection) -> AccountOverviewSection:
    """``section`` with its body cut to the longest prefix that still fits one page.

    Measured in the receipt's own bytes, not characters, so a body of multi-byte text is held to
    the same bound the runtime enforces.
    """

    def fits(length: int) -> bool:
        body, _ = _clip(section.body_text, length)
        trial = section.model_copy(update={"body_text": body, "body_truncated": True})
        return receipt_bytes([trial.model_dump()]) <= READ_REFERENCES_BUDGET_BYTES

    low, high = 1, len(section.body_text)
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    body, _ = _clip(section.body_text, low)
    return section.model_copy(update={"body_text": body, "body_truncated": True})


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


def gate_claims(
    claims: Iterable[Claim], *, settings: Settings
) -> tuple[list[Claim], dict[str, int]]:
    """The claims a read may serve, and what it held back, by reason.

    This is :mod:`clue_api.arv2.display.gather`'s gate, predicate for predicate: a special-category
    value never leaves the store, an unjudged tier-4 synthesis is held back under a verifying
    posture, and an ``outreach_safe=false`` row is held back outright (a read has no restricted
    section to put one in). Without it a tool could tell a founder, in chat, a fact the account
    page deliberately refuses to print — and call it verified, because the tool said so.

    Written once and called by every claims-serving read, so a second read cannot come to a
    gentler answer than the first: ``read_claims`` holds back exactly what ``read_account_research``
    holds back because it is this function that decides, not each caller's copy of it.

    Exclusions are **counted, not hidden**: a subject whose every claim is held back comes back
    with an empty list and a non-zero count, which says "there is something here and you may not
    have it" rather than "there is nothing here".
    """

    excluded = {"sensitive": 0, "unverified": 0, "outreach_unsafe": 0}
    servable: list[Claim] = []
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
        servable.append(claim)
    return servable, excluded


def _claim_view(claim: Claim) -> AccountClaimView:
    """One claim as a read serves it: the value, and what stands behind it, clipped."""

    evidence, evidence_truncated = _clip(claim.evidence_span or "", EVIDENCE_CHARS)
    return AccountClaimView(
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


def claims_page(
    kept: Sequence[Claim], *, offset: int, limit: int
) -> tuple[tuple[AccountClaimView, ...], bool, int | None]:
    """One page of already-gated claims, plus whether more is left and where it starts.

    Bounded twice: by ``limit`` — what the caller asked for — and by
    :data:`READ_REFERENCES_BUDGET_BYTES`, the receipt's own encoding, which is the binding one on
    a real account. A page ends at whichever comes first, so it may come back shorter than
    ``limit`` and still name a next offset. Whatever does not fit is not dropped: the next offset
    says where to continue.

    Shared by every paged claims read, so the two ceilings mean one thing across the surface.
    """

    if offset >= len(kept) and offset > 0:
        # An offset past the end is the caller's mistake, not an empty subject: answering it with
        # "no claims" would be a false statement about something that has some.
        raise Arv2ReadRefused(
            "offset_past_end",
            f"this subject has {len(kept)} servable claims; offset {offset} is past the end",
        )
    views = [_claim_view(claim) for claim in kept[offset : offset + limit]]
    fitted, cut = _take_within_budget(
        [view.model_dump() for view in views], budget=READ_REFERENCES_BUDGET_BYTES
    )
    served = tuple(views[:fitted])
    end = offset + len(served)
    truncated = cut or end < len(kept)
    return served, truncated, (end if truncated else None)


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

    The gate is :func:`gate_claims`, the one every claims-serving read shares, and it runs over the
    whole account *before* ``field_prefix`` narrows it — so ``excluded`` counts the account rather
    than the matching subset, and the families reported are the account's, which is the point: a
    read that guessed the wrong prefix is answered with the right ones instead of with a bare no.

    The page is :func:`claims_page`'s, bounded by ``limit`` (itself capped at :data:`MAX_CLAIMS`)
    and by the receipt's byte budget, whichever binds first.

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
    gated, excluded = gate_claims(claims, settings=settings)

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

    served, truncated, next_offset = claims_page(kept, offset=offset, limit=limit)
    return served, truncated, excluded, next_offset, prefixes


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
    project_id: str | None = None,
) -> AccountResearch:
    """What research found about one account: its written overview, or its live claims.

    The two sections answer two different questions — "what do we say about them?" and "what do we
    actually know, and who says so?" — so one read never serves both: the unasked half is empty,
    and an unwritten overview is a refusal rather than an account that looks unresearched.

    Claims are paged by ``offset`` under two ceilings — ``limit``, what the caller asked for, and
    the receipt's byte budget — and the page ends at whichever binds first. ``limit`` defaults to
    :data:`MAX_CLAIMS`, which is the shape ``read_account_research@1`` asks for: that version has
    no ``limit`` of its own, so the budget alone bounds its page, exactly as it always did.

    The overview pages by whole section: ``offset`` counts sections and ``next_offset`` says where
    the next page starts, so a long overview is read across several calls rather than cut.
    ``limit`` — like ``field_prefix`` — says nothing about it.
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
        sections = await _overview_sections(
            conn, workspace_id=workspace_id, account_uuid=account_uuid, project_id=project_id
        )
        overview, truncated, next_offset = _overview_page(sections, offset=offset)
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
    #: ``partial`` / ``unclear`` / ``duplicate_of_existing`` / ``found_before``.
    disposition: str
    #: The human's approval — ``approved``, or nothing at all. There is no recorded rejection.
    decision: str | None
    fit: float | None


class DiscoveryCandidateV3View(DiscoveryCandidateView):
    """``read_discovery_run@3``'s candidate: ``@2``'s, plus the gate that excluded it.

    A subclass rather than a new field on :class:`DiscoveryCandidateView`, because that model is
    part of ``@1``/``@2``'s output schema and a promoted profile pins its digest.
    """

    #: The key of the ``must`` gate that failed or the ``must_not`` gate that passed, for a
    #: candidate whose disposition is ``excluded``; ``None`` for every other candidate.
    excluded_by_gate: str | None


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
    #: The run made the relaxed search — the strict searches came up short and the run allowed
    #: it. The name predates 2026-09-28, when a human asked for the relaxed pass separately; the
    #: field keeps it because the read's schema is pinned by every profile that grants it.
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
    #: The search the run made — ``websets`` or ``search`` (``/search``).
    source: str = "websets"
    #: Why the run ended (``filled``, ``dry``, ``round_cap``, ``wall_clock``, ``stopped``,
    #: ``failed``), or ``None`` while it is still searching and for a run from before the brief.
    end_reason: str | None = None
    #: The summary the platform wrote when the run ended — what the wake turn told the Head of ABM.
    summary: Mapping[str, Any] | None = None
    #: The companies a gate excluded, when the read asked for them apart (``excluded_apart``):
    #: then they are not among ``candidates`` and not in ``candidate_total``. Grouped by gate, then
    #: by name, and bounded like the candidate list. Empty when the read listed them inline.
    excluded: tuple[DiscoveryCandidateV3View, ...] = ()
    #: Every excluded company of the run when read apart, so a bounded list never reads as all.
    excluded_total: int = 0


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
#: (``duplicate_of_existing``, ``found_before``) are stamped before any gate is asked and
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
    excluded_apart: bool = False,
) -> DiscoveryRunView:
    """One discovery run of this project — the newest, or the one named — with its candidates.

    The project is checked first, so "that run is not this project's" and "that project is not
    yours" stay two different answers, and a run of *another* project is refused by name rather
    than served to a caller who happened to guess its id.

    ``offset``/``limit`` walk the ordered candidates, and ``next_offset`` names where to continue —
    a run of sixty companies is read in pages instead of being silently cut at the first twenty-
    five. ``candidate_total`` is the whole run on every page, so a page never reads as a small run.

    ``excluded_apart`` (``read_discovery_run@3``) takes the companies a gate excluded out of the
    paged candidates and returns them in ``excluded``, each with the gate that excluded it. Without
    it (``@1``/``@2``, whose output schemas are pinned) they stay listed inline, as ``excluded``.
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
    scoped = [
        candidate
        for candidate in await list_candidates(conn, run_id=run_uuid)
        if candidate.workspace_id == workspace_id
    ]
    excluded = (
        sorted(
            (candidate for candidate in scoped if candidate.disposition == "excluded"),
            key=lambda candidate: (candidate.excluded_by_gate or "", candidate.name),
        )
        if excluded_apart
        else []
    )
    candidates = sorted(
        (
            candidate
            for candidate in scoped
            if not (excluded_apart and candidate.disposition == "excluded")
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
        relaxed_requested=any(
            search.kind == "relaxed" for search in await list_searches(conn, run_id=run_uuid)
        ),
        started_at=None if run.started_at is None else run.started_at.isoformat(),
        finished_at=None if run.finished_at is None else run.finished_at.isoformat(),
        candidates=tuple(
            _candidate_view(candidate, with_gate=excluded_apart) for candidate in window
        ),
        # The whole run, never the page: "the top 25 of 60" is one measurement and its remainder.
        candidate_total=len(candidates),
        offset=offset,
        next_offset=next_offset,
        source=run.source,
        end_reason=run.end_reason,
        summary=run.summary,
        excluded=tuple(_candidate_v3_view(candidate) for candidate in excluded[:MAX_CANDIDATES]),
        excluded_total=len(excluded),
    )


def _candidate_fields(candidate: CandidateRow) -> dict[str, Any]:
    """The fields every candidate view carries, mapped once."""
    return {
        "name": candidate.name,
        "domain": candidate.domain,
        "pass_": str(candidate.pass_),
        "disposition": str(candidate.disposition),
        "decision": candidate.decision,
        "fit": None if candidate.fit is None else float(candidate.fit),
    }


def _candidate_v3_view(candidate: CandidateRow) -> DiscoveryCandidateV3View:
    """One candidate in ``@3``'s shape, with the gate that excluded it."""
    return DiscoveryCandidateV3View(
        **_candidate_fields(candidate), excluded_by_gate=candidate.excluded_by_gate
    )


def _candidate_view(candidate: CandidateRow, *, with_gate: bool) -> DiscoveryCandidateView:
    """One candidate in ``@3``'s shape (with its excluding gate) or ``@1``/``@2``'s."""
    if with_gate:
        return _candidate_v3_view(candidate)
    return DiscoveryCandidateView(**_candidate_fields(candidate))


# =================================================================================================
# read 4: the claims about one account or contact
# =================================================================================================


@dataclass(frozen=True, slots=True)
class ClaimsQueryPage:
    """One page of the claims a query matched, and what the whole subject holds."""

    entity_id: str
    #: ``account`` or ``contact`` — resolved from the rows, never asserted by the caller.
    entity_type: str
    claims: tuple[AccountClaimView, ...]
    #: What the display gate held back, by reason, over the WHOLE subject — never the page and
    #: never the filtered subset, for the same reason ``read_account_research`` counts that way.
    excluded: dict[str, int]
    #: The subject's servable claim families with their counts, so a query that matched nothing
    #: is answered with the families that exist rather than with a bare no.
    prefixes: dict[str, int]
    offset: int
    next_offset: int | None
    truncated: bool


#: The subject of a claims query, as this workspace may see it. Accounts and contacts share one
#: uuid space and one ``claim.entity_id`` column, so one statement answers "is this ours, and what
#: kind of thing is it?" — and ``merged_into IS NULL`` refuses a merge loser by name rather than
#: serving the survivor's claims under an id that is no longer anybody.
_ENTITY_IN_WORKSPACE = text(
    """
    SELECT 'account' AS entity_type FROM account_entity
     WHERE id = :id AND workspace_id = :ws AND merged_into IS NULL
    UNION ALL
    SELECT 'contact' AS entity_type FROM contact_entity
     WHERE id = :id AND workspace_id = :ws AND merged_into IS NULL
    LIMIT 1
    """
)


async def _entity_in_workspace(
    conn: AsyncConnection, *, workspace_id: str, entity_id: str
) -> tuple[UUID, str]:
    """The subject's id and kind, or the refusal that says it is not ours to read."""

    try:
        entity_uuid = UUID(entity_id)
    except ValueError:
        # A malformed id reads exactly like an absent one, as it does for the account read: both
        # mean "there is no such subject here", and the model does not learn the id format from
        # an error message.
        raise Arv2ReadRefused(
            "entity_not_found", f"no account or contact {entity_id} in this workspace"
        ) from None
    row = (
        (await conn.execute(_ENTITY_IN_WORKSPACE, {"id": entity_uuid, "ws": workspace_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise Arv2ReadRefused(
            "entity_not_found", f"no account or contact {entity_id} in this workspace"
        )
    return entity_uuid, str(row["entity_type"])


def parse_since(value: str) -> datetime:
    """``value`` as the instant a claim must have been collected at or after.

    An ISO-8601 date or datetime. A bare date means midnight UTC, and a naive datetime is read as
    UTC — claims are stored with an offset, and comparing an offset-aware column against a naive
    instant raises rather than filtering. A string that is neither is refused by name: silently
    ignoring an unparseable ``since`` would answer a narrowed question with the unnarrowed list
    and call it the answer.
    """

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise Arv2ReadRefused(
            "since_invalid",
            f"since must be an ISO-8601 date or datetime (e.g. '2026-09-01'); got {value!r}",
        ) from None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def read_claims(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    entity_id: str,
    settings: Settings,
    field_prefix: str | None = None,
    tier: int | None = None,
    verification_status: str | None = None,
    since: str | None = None,
    offset: int = 0,
    limit: int = MAX_CLAIMS,
) -> ClaimsQueryPage:
    """The live claims about one account or contact, filtered, gated and paged.

    The general query beside the account read's fixed one: "what do we actually know about this
    person, from a trusted source, since the campaign started?" is four filters over one claim
    list, and without them the model reads a hundred claims to quote three. The filters compose —
    each one narrows what the one before it left — and every one of them narrows what the gate
    already allowed, never what it held back.

    A query that matches nothing is an **empty page with its counts and families**, not a refusal:
    "no tier-1 claim about this person since June" is a true, useful sentence, and the families
    come back with it so the next call is a correction rather than another guess. Only three
    things are refusals: a subject this workspace cannot see (``entity_not_found``), a ``since``
    that is not a date (``since_invalid``), and an offset past the end (``offset_past_end``).

    The claims span every project of the workspace that researched this subject: the store holds
    entity truth, not a per-project lens.
    """

    entity_uuid, entity_type = await _entity_in_workspace(
        conn, workspace_id=workspace_id, entity_id=entity_id
    )
    collected_since = None if since is None else parse_since(since)
    # Scoped by the claim store's own tenant filter, never by a hand-written workspace predicate:
    # the scope object is the one place that knows public-footprint claims are shared and private
    # ones are not. The order is the store's — ``(field_key, collected_at DESC, id)`` — so one
    # field's newest value comes first, which is the grouping the agent reads.
    claims = await claims_for_entities(
        conn,
        [EntityId(entity_uuid)],
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    gated, excluded = gate_claims(claims, settings=settings)
    prefixes = claim_prefixes(gated)
    kept = [
        claim
        for claim in gated
        if (field_prefix is None or claim.field_key.startswith(field_prefix))
        and (tier is None or int(claim.source_tier) == tier)
        and (verification_status is None or str(claim.verification_status) == verification_status)
        and (collected_since is None or claim.collected_at >= collected_since)
    ]
    served, truncated, next_offset = claims_page(kept, offset=offset, limit=limit)
    return ClaimsQueryPage(
        entity_id=str(entity_uuid),
        entity_type=entity_type,
        claims=served,
        excluded=excluded,
        prefixes=prefixes,
        offset=offset,
        next_offset=next_offset,
        truncated=truncated,
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
        project_id: str | None = None,
    ) -> AccountResearch: ...

    async def read_discovery_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        run_id: str | None,
        offset: int,
        limit: int,
        excluded_apart: bool,
    ) -> DiscoveryRunView: ...

    async def read_claims(
        self,
        *,
        workspace_id: str,
        entity_id: str,
        field_prefix: str | None,
        tier: int | None,
        verification_status: str | None,
        since: str | None,
        offset: int,
        limit: int,
    ) -> ClaimsQueryPage: ...


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
        project_id: str | None = None,
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
                project_id=project_id,
            )

    async def read_discovery_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        run_id: str | None,
        offset: int,
        limit: int,
        excluded_apart: bool,
    ) -> DiscoveryRunView:
        async with self._conn_factory() as conn:
            return await read_discovery_run(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                run_id=run_id,
                offset=offset,
                limit=limit,
                excluded_apart=excluded_apart,
            )

    async def read_claims(
        self,
        *,
        workspace_id: str,
        entity_id: str,
        field_prefix: str | None,
        tier: int | None,
        verification_status: str | None,
        since: str | None,
        offset: int,
        limit: int,
    ) -> ClaimsQueryPage:
        async with self._conn_factory() as conn:
            return await read_claims(
                conn,
                workspace_id=workspace_id,
                entity_id=entity_id,
                field_prefix=field_prefix,
                tier=tier,
                verification_status=verification_status,
                since=since,
                settings=self._settings,
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
        + tool_manual_link("read_project_accounts")
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
    #: Continue from ``next_offset`` of the previous page, for claims and overview alike.
    #: ``0`` starts over.
    offset: int = Field(default=0, ge=0)


class ReadAccountResearchOutput(ToolOutput):
    account_entity_id: str
    account_name: str
    section: str
    #: The written sections when ``section='overview'``, else empty.
    overview: tuple[AccountOverviewSection, ...]
    #: The account's servable claims when ``section='claims'``, else empty.
    claims: tuple[AccountClaimView, ...]
    #: More exists than this page holds: continue with ``offset = next_offset``, for claims and
    #: overview sections alike.
    truncated: bool
    #: What the account pages' own gate held back, by reason: ``sensitive``, ``unverified``,
    #: ``outreach_unsafe``. A non-zero count means "there is more here, and it is not servable".
    excluded: dict[str, int]
    #: Where this page started: a claim index for claims, a section index for the overview.
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
        + tool_manual_link("read_account_research")
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
                # The project is AMBIENT too: the calling turn's (or design leg's) own project
                # picks which project's overview is served.
                project_id=ctx.project_id,
            )
        except Arv2ReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        tag_entities([research.account_entity_id])
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
        + tool_manual_link("read_account_research")
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
    #: verdict. Companies skipped before any gate (already in this project, found by an earlier
    #: discovery) are NOT counted here; they are in ``candidate_total``.
    verified: int
    shown: int
    approved: int
    #: The run made the relaxed search (the name predates 2026-09-28; see ``DiscoveryRunView``).
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
        + tool_manual_link("read_discovery_run")
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

    #: ``@3`` takes the excluded companies out of the candidate list; ``@1``/``@2`` list them
    #: inline, because their pinned output schema has nowhere else to put them.
    _excluded_apart: ClassVar[bool] = False

    async def _read(
        self, *, project_id: str, run_id: str | None, offset: int, limit: int, ctx: ToolContext
    ) -> DiscoveryRunView:
        """The run, or a typed refusal — written once, because every version reads it the same way
        and differs only in which window it asks for and where the excluded companies go."""

        assert self._service is not None
        try:
            return await self._service.read_discovery_run(
                # The tenant is AMBIENT authority, never model-authored.
                workspace_id=ctx.workspace_id,
                project_id=project_id,
                run_id=run_id,
                offset=offset,
                limit=limit,
                excluded_apart=self._excluded_apart,
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
        + tool_manual_link("read_discovery_run")
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


#: ``@3`` pages exactly as ``@2`` does; only what comes back changed.
ReadDiscoveryRunV3Input = ReadDiscoveryRunV2Input


class ReadDiscoveryRunV3Output(ReadDiscoveryRunV2Output):
    """``@2``'s page plus the run's end, its summary, and the companies its gates excluded."""

    #: The run's candidates without the excluded ones, shown-first and best-fit-first; each
    #: carries ``excluded_by_gate`` (always ``null`` here).
    candidates: tuple[DiscoveryCandidateV3View, ...]
    #: The search the run made: ``websets`` or ``search``.
    source: str
    #: Why the run ended — ``filled``, ``dry``, ``round_cap``, ``wall_clock``, ``stopped`` or
    #: ``failed`` — or ``null`` while it is still searching.
    end_reason: str | None
    #: What the platform told you when the run ended: asked, added, excluded, unclear, the gates
    #: that excluded companies with one example each, the last search's criteria pass rates, the
    #: searches run, why it ended and the spend. ``null`` until the run ends.
    summary: dict[str, Any] | None
    #: The companies a gate excluded, with the gate, grouped by gate then by name. They were
    #: never added to the project's accounts.
    excluded: tuple[DiscoveryCandidateV3View, ...]
    #: Every excluded company of the run; ``excluded`` holds at most 50 of them.
    excluded_total: int


class ReadDiscoveryRunV3Tool(ReadDiscoveryRunV2Tool):
    """``read_discovery_run@3``: ``@2`` for a run launched from the brief the Head of ABM wrote.

    Such a run ends for a reason and writes a summary, and its gates can exclude companies. ``@3``
    serves those three things and lists the excluded companies apart from the candidates, which
    stay the companies the human may be shown. The inputs, tallies, ordering and refusals are
    ``@2``'s. A new address because ``@2``'s output schema is pinned by `head-of-abm@v69`.
    """

    version = "3"
    model_description = (
        "Read the project's latest discovery run (or one by id): status, what was asked for and "
        "found, how many candidates the verifier judged against the ICP, how many were shown and "
        "approved, why the run ended and its summary, and the candidates with their verdict, best "
        "first. Companies a gate excluded are listed apart in excluded, each with the gate that "
        "excluded it. Page the candidates with offset and limit (default 25) and follow "
        "next_offset until it is null; candidate_total is the whole run on every page. Read this "
        "before proposing another discovery, and to answer what discovery found. It approves "
        "nothing. Effect-free. " + tool_manual_link("read_discovery_run")
    )
    output_model: ClassVar[type[ToolOutput]] = ReadDiscoveryRunV3Output
    _excluded_apart: ClassVar[bool] = True

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadDiscoveryRunV3Input)
        run = await self._read(
            project_id=inputs.project_id,
            run_id=inputs.run_id,
            offset=inputs.offset,
            limit=inputs.limit,
            ctx=ctx,
        )
        return self._result(
            ReadDiscoveryRunV3Output(
                **_discovery_fields(run),
                offset=run.offset,
                next_offset=run.next_offset,
                source=run.source,
                end_reason=run.end_reason,
                summary=None if run.summary is None else dict(run.summary),
                excluded=run.excluded,
                excluded_total=run.excluded_total,
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


class ReadClaimsInput(ToolInput):
    #: An account OR a contact: the store keys claims on one entity id, and so does this read.
    entity_id: str
    #: ``account.resonance`` narrows to one family — the families the subject actually has come
    #: back in ``prefixes`` on every answer, including an empty one.
    field_prefix: str | None = Field(default=None, max_length=80)
    #: The source tier: 1 deterministic API, 2 official source, 3 reputable third party, 4 LLM
    #: synthesis. Asking for 1–2 is how a turn quotes only what a deterministic source says.
    tier: int | None = Field(default=None, ge=1, le=4)
    verification_status: Literal["unverified", "verified", "rejected"] | None = None
    #: An ISO-8601 date or datetime; claims collected at or after it. "What have we learned since
    #: the campaign started?" is this field.
    since: str | None = None
    #: Continue from ``next_offset`` of the previous page. ``0`` starts over.
    offset: int = Field(default=0, ge=0)
    #: How many claims this page may hold. The receipt's byte budget is the other ceiling and
    #: usually the binding one, so a page may come back shorter than this and say so.
    limit: int = Field(default=40, ge=1, le=MAX_CLAIMS)


class ReadClaimsOutput(ToolOutput):
    entity_id: str
    #: ``account`` or ``contact``, resolved from the rows — the read says what it read.
    entity_type: str
    #: The matching claims, gated exactly as the account pages gate them. (``AccountClaimView``
    #: is the shape; the name is historical — a contact's claim is served in the same shape.)
    claims: tuple[AccountClaimView, ...]
    #: What the gate held back over the whole subject, by reason: ``sensitive``, ``unverified``,
    #: ``outreach_unsafe``. A non-zero count means "there is more here, and it is not servable".
    excluded: dict[str, int]
    #: The subject's servable claim families with their counts — the whole subject's, never this
    #: page's and never the filtered subset's, so a query that matched nothing still says what is
    #: there.
    prefixes: dict[str, int]
    #: Where this page started in the matching claims.
    offset: int
    #: Where the next page starts, or ``None`` when this page ends the list.
    next_offset: int | None
    #: More matched than this page holds: continue with ``offset = next_offset``.
    truncated: bool


class ReadClaimsTool(Tool):
    """Query the live claims about one account or contact."""

    name = "read_claims"
    version = "1"
    model_description = (
        "Query the live claims about one account or contact: by field family (field_prefix), "
        "source tier, verification status, or collected since a date; paged; the same display "
        "gate as the account pages. Use read_account_research for the written overview. "
        "Effect-free. " + tool_manual_link("read_claims")
    )
    input_model: ClassVar[type[ToolInput]] = ReadClaimsInput
    output_model: ClassVar[type[ToolOutput]] = ReadClaimsOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="the subject's live claims",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "entity_id",
            "field_prefix",
            "tier",
            "verification_status",
            "since",
            "offset",
            "limit",
        )
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
        assert isinstance(inputs, ReadClaimsInput)
        assert self._service is not None
        try:
            page = await self._service.read_claims(
                # The tenant is AMBIENT authority, never model-authored.
                workspace_id=ctx.workspace_id,
                entity_id=inputs.entity_id,
                field_prefix=inputs.field_prefix,
                tier=inputs.tier,
                verification_status=inputs.verification_status,
                since=inputs.since,
                offset=inputs.offset,
                limit=inputs.limit,
            )
        except Arv2ReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        tag_entities([page.entity_id])
        output = ReadClaimsOutput(
            entity_id=page.entity_id,
            entity_type=page.entity_type,
            claims=page.claims,
            excluded=page.excluded,
            prefixes=page.prefixes,
            offset=page.offset,
            next_offset=page.next_offset,
            truncated=page.truncated,
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())


def build_arv2_read_tools(service: Arv2ReadService | None) -> tuple[Tool, ...]:
    """The lane's read surface. Registered always; composed wherever there is a database.

    Registering it uncomposed is deliberate, for the reason its ARV2 neighbours give: the
    platform's tool surface stays complete (the authority audit sees every tool), and an agent that
    reaches for a read on a deployment without the lane gets the named ``arv2_reads_not_composed``
    refusal rather than an ``UnknownTool`` it cannot explain. Unlike its launching neighbours these
    four have no flag: they read rows that already exist and spend nothing to do it.

    ``read_claims`` is the newest of them, granted at `head-of-abm@v56` — the reviewed bump that
    pins its contract, mints the manual chapter that teaches it and admits it to the interaction
    slot. It registers here on the same service and with the same refusal as its three siblings.

    Two of the four register WITHOUT their name-only alias: `head-of-abm@v56` pins the paged
    ``@2`` of ``read_account_research`` and ``read_discovery_run``, so those defaults belong to
    :func:`build_arv2_paged_read_tools`. The composition root decides that, not this function.
    """

    return (
        ReadProjectAccountsTool(service),
        ReadAccountResearchTool(service),
        ReadDiscoveryRunTool(service),
        ReadClaimsTool(service),
    )


def build_arv2_paged_read_tools(service: Arv2ReadService | None) -> tuple[Tool, ...]:
    """The two reads whose inputs learned to page, at their own addresses.

    Separate from :func:`build_arv2_read_tools` because the two versions of each name move as a
    pair: `head-of-abm@v56` pins these ``@2`` contracts, so they hold the name-only alias and
    their ``@1`` siblings give it up. A default that disagreed with the promoted profile's pin
    would hand an unversioned caller the version nobody holds — the same reasoning that kept
    ``open_icp_confirmation_gate@1`` the default until its profile moved, applied in the other
    direction. The ``@1``s stay registered for replay of a turn pinned to recipe0-stage0@27 or
    earlier; the composition is otherwise identical (one service, one refusal code).
    """

    return (
        ReadAccountResearchV2Tool(service),
        ReadDiscoveryRunV2Tool(service),
    )
