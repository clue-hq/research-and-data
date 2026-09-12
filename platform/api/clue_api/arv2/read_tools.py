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
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.discovery_store import (
    PENDING_DISPOSITION,
    SHOWN_DISPOSITIONS,
    CandidateRow,
    list_candidates,
)
from clue_api.arv2.discovery_store import read_discovery_run as read_discovery_run_row
from clue_api.arv2.display.blocks import live_blocks
from clue_api.arv2.display.recipes import read_recipes
from clue_api.arv2.errors import Arv2Error
from clue_core import EntityId
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
    "EVIDENCE_CHARS",
    "MAX_ACCOUNTS",
    "MAX_CANDIDATES",
    "MAX_CLAIMS",
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
    "ReadDiscoveryRunInput",
    "ReadDiscoveryRunOutput",
    "ReadDiscoveryRunTool",
    "ReadProjectAccountsInput",
    "ReadProjectAccountsOutput",
    "ReadProjectAccountsTool",
    "list_project_accounts",
    "read_account_research",
    "read_discovery_run",
]

#: The hard ceiling on one read. A tool result is context the model pays for on every later turn,
#: so the page is bounded by construction rather than by the caller's good manners.
MAX_ACCOUNTS = 200


class Arv2ReadRefused(Arv2Error):
    """A read cannot be served, and the caller is told exactly which prerequisite is missing.

    ``code`` is stable and machine-readable; the toolbelt tools turn it straight into a
    :class:`~clue_toolbelt.PreconditionFailure`. Codes: ``project_not_found``,
    ``account_not_found``, ``overview_not_written``, ``account_not_researched``,
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


#: The project's accounts with each one's research state, in one statement.
#:
#: ``merged_into IS NULL`` drops merge losers: a merged account is the same company under another
#: id, and listing it twice would make a project look bigger than it is. The lateral join takes the
#: account's newest ARV2 **account** job — person jobs share this table and the account column, and
#: a contact still being researched is not the account being re-researched. ``refreshing`` is the
#: narrow claim it sounds like: the latest run is live *and* an earlier one completed, so the
#: account already has research on it and is getting more.
_LIST_PROJECT_ACCOUNTS = text(
    """
    SELECT a.id, a.canonical_name, a.primary_domain, pa.added_via, pa.added_at,
           j.status AS research_status,
           EXISTS (SELECT 1 FROM arv2_research_job j2
                   WHERE j2.workspace_id = :ws AND j2.account_entity_id = a.id
                     AND j2.subject_type = 'account'
                     AND j2.status IN ('not_started', 'in_progress')
                     AND EXISTS (SELECT 1 FROM arv2_research_job j3
                                 WHERE j3.workspace_id = :ws AND j3.account_entity_id = a.id
                                   AND j3.subject_type = 'account' AND j3.status = 'completed'
                                   AND j3.created_at < j2.created_at)) AS refreshing
    FROM project_account pa
    JOIN account_entity a ON a.id = pa.account_entity_id AND a.merged_into IS NULL
    LEFT JOIN LATERAL (
      SELECT status FROM arv2_research_job j
      WHERE j.workspace_id = :ws AND j.account_entity_id = a.id AND j.subject_type = 'account'
      ORDER BY j.created_at DESC, j.job_id DESC LIMIT 1
    ) j ON TRUE
    WHERE pa.workspace_id = :ws AND pa.project_id = :project
    ORDER BY a.canonical_name, a.id
    LIMIT :limit
    """
)

#: The total counts the rows the listing *can show*, which is why it repeats the listing's own
#: ``merged_into IS NULL`` join: "showing 100 of 240" must be two measurements of one population,
#: and counting a merge loser the page can never serve would make the remainder unreachable.
_COUNT_PROJECT_ACCOUNTS = text(
    """
    SELECT count(*)
    FROM project_account pa
    JOIN account_entity a ON a.id = pa.account_entity_id AND a.merged_into IS NULL
    WHERE pa.workspace_id = :ws AND pa.project_id = :project
    """
)


async def list_project_accounts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    limit: int,
) -> ProjectAccountsPage:
    """The project's accounts with their research status. Raises when the project is not ours."""

    project = await get_project(conn, project_id)
    if project is None or project.workspace_id != workspace_id:
        # Fail-closed and indistinguishable: another workspace's project is not "empty", it is
        # absent — the same answer a project id that never existed gets.
        raise Arv2ReadRefused("project_not_found", f"no project {project_id} in this workspace")
    params = {"ws": workspace_id, "project": project_id, "limit": limit}
    rows = (await conn.execute(_LIST_PROJECT_ACCOUNTS, params)).mappings().all()
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
    #: ``display_block.body_json`` verbatim — the same body the app renders, not a second shape.
    body: dict[str, Any]
    cited_claim_ids: tuple[str, ...]
    generated_at: str


class AccountClaimView(BaseModel, frozen=True):
    """One live claim about an account: the value, and what stands behind it."""

    claim_id: str
    field_key: str
    value: Any
    source_url: str | None
    #: The evidence span, clipped — a quote is here to be *checked*, not reproduced whole.
    evidence: str
    tier: int
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


#: The hard ceiling on one claims read, for the same reason as :data:`MAX_ACCOUNTS`: a researched
#: account can hold hundreds of claims, and the model pays for every one of them on every later
#: turn. Over the cap the read says so (``truncated``) instead of quietly dropping the tail.
MAX_CLAIMS = 120

#: An evidence span is a quotation the reader may *check*; a whole article is not. Clipped rather
#: than dropped, because a truncated quote still tells the reader what kind of sentence it came
#: from — and the full span is one evidence read away.
EVIDENCE_CHARS = 240

_OVERVIEW_PAGE = "overview"

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
) -> tuple[AccountOverviewSection, ...]:
    """The account's written overview, in the order the overview page itself serves it."""

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
    return tuple(
        AccountOverviewSection(
            section_key=block.section_key,
            body=block.body_json,
            cited_claim_ids=block.cited_claim_ids,
            generated_at=block.generated_at.isoformat(),
        )
        for block in ordered
    )


async def _account_claims(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_uuid: UUID,
    field_prefix: str | None,
) -> tuple[tuple[AccountClaimView, ...], bool]:
    """The account's live claims under ``field_prefix``, bounded, plus whether the tail was cut."""

    # Scoped by the claim store's own tenant filter, never by a hand-written workspace predicate:
    # the scope object is the one place that knows public-footprint claims are shared and private
    # ones are not.
    claims = await claims_for_entities(
        conn,
        [EntityId(account_uuid)],
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    # ``claims_for_entities`` already orders by ``(field_key, collected_at DESC, id)``, which is
    # the grouping the agent reads: one field's newest value first.
    matching = [
        claim
        for claim in claims
        if field_prefix is None or claim.field_key.startswith(field_prefix)
    ]
    if not matching:
        raise Arv2ReadRefused(
            "account_not_researched",
            f"no claims about this account{f' under {field_prefix}' if field_prefix else ''} yet",
        )
    return (
        tuple(
            AccountClaimView(
                claim_id=str(claim.id),
                field_key=str(claim.field_key),
                value=claim.value_json,
                source_url=claim.source_url,
                evidence=(claim.evidence_span or "")[:EVIDENCE_CHARS],
                tier=int(claim.source_tier),
                collected_at=claim.collected_at.isoformat(),
            )
            for claim in matching[:MAX_CLAIMS]
        ),
        len(matching) > MAX_CLAIMS,
    )


async def read_account_research(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_entity_id: str,
    section: str,
    field_prefix: str | None = None,
) -> AccountResearch:
    """What research found about one account: its written overview, or its live claims.

    The two sections answer two different questions — "what do we say about them?" and "what do we
    actually know, and who says so?" — so one read never serves both: the unasked half is empty,
    and an unwritten overview is a refusal rather than an account that looks unresearched.
    """

    account_uuid, name = await _account_in_workspace(
        conn, workspace_id=workspace_id, account_entity_id=account_entity_id
    )
    overview: tuple[AccountOverviewSection, ...] = ()
    claims: tuple[AccountClaimView, ...] = ()
    truncated = False
    if section == "overview":
        overview = await _overview_sections(
            conn, workspace_id=workspace_id, account_uuid=account_uuid
        )
    else:
        claims, truncated = await _account_claims(
            conn,
            workspace_id=workspace_id,
            account_uuid=account_uuid,
            field_prefix=field_prefix,
        )
    return AccountResearch(
        account_entity_id=str(account_uuid),
        account_name=name,
        section=section,
        overview=overview,
        claims=claims,
        truncated=truncated,
    )


# =================================================================================================
# read 3: one discovery run
# =================================================================================================


class DiscoveryCandidateView(BaseModel, frozen=True):
    """One company a discovery run surfaced, with the verdict the verifier gave it."""

    name: str
    domain: str
    #: Which §4 pass surfaced it — ``strict`` (the full criteria) or ``relaxed`` (the widened
    #: re-search). Serialized as ``pass``; the trailing underscore is Python's, not the schema's.
    pass_: str = Field(serialization_alias="pass")
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
#: worth looking at?", "how many did we take?". Verified is the complement of ``pending`` rather
#: than a list of its own, so a disposition added later counts as verified without touching this.
#: Every sub-select names the tenant: ``arv2_discovery_candidate.run_id`` is a single-column FK, so
#: nothing in the schema forces a candidate's workspace to equal its run's.
_DISCOVERY_COUNTS = text(
    """
    SELECT
      (SELECT count(*) FROM arv2_discovery_candidate c
        WHERE c.run_id = :run AND c.workspace_id = :ws
          AND c.disposition <> :pending) AS verified,
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
    candidate_limit: int,
) -> DiscoveryRunView:
    """One discovery run of this project — the newest, or the one named — with its candidates.

    The project is checked first, so "that run is not this project's" and "that project is not
    yours" stay two different answers, and a run of *another* project is refused by name rather
    than served to a caller who happened to guess its id.
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
                {
                    "run": run_uuid,
                    "ws": workspace_id,
                    "pending": PENDING_DISPOSITION,
                    "shown": list(SHOWN_DISPOSITIONS),
                },
            )
        )
        .mappings()
        .one()
    )
    candidates = sorted(await list_candidates(conn, run_id=run_uuid), key=_candidate_order)
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
            for candidate in candidates[:candidate_limit]
        ),
        # The whole run, never the page: "the top 25 of 60" is one measurement and its remainder.
        candidate_total=len(candidates),
    )


# =================================================================================================
# the service seam + its production implementation
# =================================================================================================


class Arv2ReadService(Protocol):
    """What the read tools call. One transaction per call is the implementation's business."""

    async def list_project_accounts(
        self, *, workspace_id: str, project_id: str, limit: int
    ) -> ProjectAccountsPage: ...

    async def read_account_research(
        self,
        *,
        workspace_id: str,
        account_entity_id: str,
        section: str,
        field_prefix: str | None,
    ) -> AccountResearch: ...

    async def read_discovery_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        run_id: str | None,
        candidate_limit: int,
    ) -> DiscoveryRunView: ...


class DbArv2ReadService:
    """The production service: one transaction per read, and nothing else — reads need no storage,
    no queue and no settings, so this composes on every deployment that has a database."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def list_project_accounts(
        self, *, workspace_id: str, project_id: str, limit: int
    ) -> ProjectAccountsPage:
        async with self._conn_factory() as conn:
            return await list_project_accounts(
                conn, workspace_id=workspace_id, project_id=project_id, limit=limit
            )

    async def read_account_research(
        self,
        *,
        workspace_id: str,
        account_entity_id: str,
        section: str,
        field_prefix: str | None,
    ) -> AccountResearch:
        async with self._conn_factory() as conn:
            return await read_account_research(
                conn,
                workspace_id=workspace_id,
                account_entity_id=account_entity_id,
                section=section,
                field_prefix=field_prefix,
            )

    async def read_discovery_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        run_id: str | None,
        candidate_limit: int,
    ) -> DiscoveryRunView:
        async with self._conn_factory() as conn:
            return await read_discovery_run(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                run_id=run_id,
                candidate_limit=candidate_limit,
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


class ReadProjectAccountsOutput(ToolOutput):
    project_id: str
    total: int
    #: ``ProjectAccountView`` rows. ``total`` is the whole membership; ``len(accounts)`` is the
    #: page, so the model can say "showing 100 of 240" rather than guessing at the rest.
    accounts: tuple[dict[str, Any], ...]


class ReadProjectAccountsTool(Tool):
    """List one project's accounts with each account's research status."""

    name = "read_project_accounts"
    version = "1"
    model_description = (
        "List the accounts in one project with each account's research status (not_started, "
        "in_progress, needs_review, completed, suspended) and how it joined the project. Read "
        "this before saying how many accounts there are, which are researched, or before "
        "proposing more discovery. Effect-free."
    )
    input_model: ClassVar[type[ToolInput]] = ReadProjectAccountsInput
    output_model: ClassVar[type[ToolOutput]] = ReadProjectAccountsOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="current project_account rows + each account's latest ARV2 account job",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_id", "limit"))
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
            )
        except Arv2ReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        output = ReadProjectAccountsOutput(
            project_id=page.project_id,
            total=page.total,
            accounts=tuple(account.model_dump() for account in page.accounts),
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())


class ReadAccountResearchInput(ToolInput):
    account_entity_id: str
    section: Literal["overview", "claims"] = "overview"
    #: Claims only: ``account.resonance`` narrows a researched account's claims to one family
    #: rather than making the model read all of them to find three.
    field_prefix: str | None = Field(default=None, max_length=80)


class ReadAccountResearchOutput(ToolOutput):
    account_entity_id: str
    account_name: str
    section: str
    #: ``AccountOverviewSection`` rows when ``section='overview'``, else empty.
    overview: tuple[dict[str, Any], ...]
    #: ``AccountClaimView`` rows when ``section='claims'``, else empty.
    claims: tuple[dict[str, Any], ...]
    #: The account holds more claims than one read serves; narrow with ``field_prefix``.
    truncated: bool


class ReadAccountResearchTool(Tool):
    """Read one account's written overview, or the claims underneath it."""

    name = "read_account_research"
    version = "1"
    model_description = (
        "Read what research found about one account: section='overview' returns the written "
        "overview sections (prose with the claim ids they cite); section='claims' returns the "
        "account's verified claims grouped by field (value, source, evidence, tier), optionally "
        "under a field prefix. Read this before saying anything specific about an account. "
        "Effect-free."
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
        safe_display_fields=("account_entity_id", "section", "field_prefix")
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
        assert isinstance(inputs, ReadAccountResearchInput)
        assert self._service is not None
        try:
            research = await self._service.read_account_research(
                # The tenant is AMBIENT authority, never model-authored.
                workspace_id=ctx.workspace_id,
                account_entity_id=inputs.account_entity_id,
                section=inputs.section,
                field_prefix=inputs.field_prefix,
            )
        except Arv2ReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        output = ReadAccountResearchOutput(
            account_entity_id=research.account_entity_id,
            account_name=research.account_name,
            section=research.section,
            overview=tuple(section.model_dump() for section in research.overview),
            claims=tuple(claim.model_dump() for claim in research.claims),
            truncated=research.truncated,
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())


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
    verified: int
    shown: int
    approved: int
    relaxed_requested: bool
    started_at: str | None
    finished_at: str | None
    #: ``DiscoveryCandidateView`` rows, shown-first and best-fit-first.
    candidates: tuple[dict[str, Any], ...]
    #: The run's whole candidate count, so a bounded list never reads as a small run.
    candidate_total: int


class ReadDiscoveryRunTool(Tool):
    """Read one discovery run: what it asked for, what it found, and the top candidates."""

    name = "read_discovery_run"
    version = "1"
    model_description = (
        "Read the project's latest discovery run (or one by id): status, what was asked for and "
        "found, how many candidates were verified, shown and approved, and the top candidates "
        "with their verdict. Read this before proposing another discovery, and to answer what "
        "discovery found. It approves nothing. Effect-free."
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

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadDiscoveryRunInput)
        assert self._service is not None
        try:
            run = await self._service.read_discovery_run(
                # The tenant is AMBIENT authority, never model-authored.
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                run_id=inputs.run_id,
                candidate_limit=inputs.candidate_limit,
            )
        except Arv2ReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        output = ReadDiscoveryRunOutput(
            run_id=run.run_id,
            status=run.status,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
            target_count=run.target_count,
            asked=run.asked,
            found=run.found,
            verified=run.verified,
            shown=run.shown,
            approved=run.approved,
            relaxed_requested=run.relaxed_requested,
            started_at=run.started_at,
            finished_at=run.finished_at,
            # ``by_alias`` is what turns ``pass_`` back into the schema's ``pass``.
            candidates=tuple(candidate.model_dump(by_alias=True) for candidate in run.candidates),
            candidate_total=run.candidate_total,
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())
