"""One ARV2 discovery run on the fleet: rounds of the agent's brief, the verifier, the accounts.

This is spec 2026-09-30 §4 (``docs/superpowers/specs/2026-09-30-agent-authored-account-discovery-
design.md``) executed once per ``arv2_discovery`` task:

1. **Claim the run** (``begin_discovery_run``). A run another worker is driving, or one that has
   already landed, is not this task's to run — the task completes without spending a cent.
2. **Read the brief** the Head of ABM wrote and the launch stored whole on the run (query,
   criteria, gates with their roles, and the source). A run launched without one is refused by
   name (``brief_missing``). The ICP document the run was pinned to is still re-read and checked
   against ``run.icp_artifact_sha256``, so a run whose pinned bytes moved is refused rather than
   scored against a different document than the fit claims name.
3. **Rounds with the same brief.** Round 1 asks the brief's source for ``target_count``
   companies; while the run has shown fewer than asked, the next round asks again with the SAME
   brief for the shortfall, excluding every company seen so far — a webset excludes the websets
   before it (this run's and every earlier discovery run's of the project), a ``/search`` asks
   for one more result per domain already known and skips those in code. The run ends on the
   first of *filled*, *dry* (a round found nothing new), *round cap*
   (``1 + arv2_discovery_max_topups`` searches), *wall clock* (per search) and *stopped* (a
   human pressed Stop: the current webset is cancelled and read once more, and every company
   already verified is kept).
4. **The verifier, per candidate** — first the company's own website (Websets gave ``probook.com``
   for a company whose site is ``probook.ai``, and everything downstream keys on the verified
   domain), then one Answer call per gate of the brief, each graded by
   :func:`~clue_api.arv2.discovery_verifier.apply_guards`. Code applies the gate's role
   (:func:`~clue_api.arv2.discovery_request.apply_roles`): a failed ``must`` or a passed
   ``must_not`` **excludes** the company — kept on the run with the gate that excluded it, never
   added to the project, never counted toward the target; otherwise it joins the project with a
   fit over its ``must`` and ``prefer`` gates, written as an ``account.scoring.fit`` claim.
5. **The receipt and the summary.** The receipt keeps every number behind the run; the summary is
   what the Head of ABM is told (:func:`summary_message`). The end block writes both, and either
   hands the summary to the launching thread's wake turn (:class:`DiscoveryWake`) — the run stays
   held until that turn finishes — or, for a run with no launching thread, releases the run's
   project lock at once. Every ending runs that block, a contained failure included.

Two laws shape the code below.

* **The money law.** Every provider call goes through a fresh
  :class:`~clue_api.arv2.calls.ProviderCaller` over buffered sinks, run off the event loop, and is
  drained onto the ledger under this run's stamp in a ``finally`` that is **shielded from
  cancellation** — a call that happened is money truth even when the task is being killed, and
  even when the provider refused to sell.
* **``handle`` never raises.** The fleet plane knows nothing about ``arv2_discovery_run`` rows, so
  an escaping exception would leave the run ``in_progress`` for ever (``begin_discovery_run``
  claims only ``not_started``/``suspended``, so no redelivery could revive it). Every failure lands
  the run ``needs_review`` with a named reason on its receipt, and the candidates already verified
  are kept — they were paid for.

**No gate is asked about a company this project already has, or already found.** A verified domain
already among this project's accounts is ``duplicate_of_existing``; one an earlier discovery run
of this project found is ``found_before``. Both are recorded as candidates and cost exactly the one
website answer that identified them. A company that is an account of the workspace but not of this
project IS verified against this project's ICP and joins this project on its existing account row
(founder ruling 2026-09-28).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue, SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2 import discovery_store as default_store
from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_api.arv2.discovery_brief import DiscoveryBrief
from clue_api.arv2.discovery_launch import Arv2DiscoveryRefused, read_icp_document
from clue_api.arv2.discovery_request import DiscoveryBrief2, apply_roles, verifier_gates
from clue_api.arv2.discovery_store import (
    CandidateRow,
    DiscoveryRunRow,
    Disposition,
    Pass,
    SearchKind,
    SearchRow,
)
from clue_api.arv2.discovery_verifier import (
    OUTPUT_SCHEMA,
    WEBSITE_SCHEMA,
    GateVerdict,
    apply_guards,
    gate_question,
    system_prompt,
    website_question,
)
from clue_api.arv2.errors import Arv2Error, ProviderHalted
from clue_api.arv2.exa_client import ExaAnswerResult, ExaClient, ExaHit
from clue_api.arv2.exa_websets_client import (
    ExaWebsetsClient,
    WebsetItem,
    WebsetItemsResult,
    WebsetView,
)
from clue_api.arv2.fleet_task import arv2_discovery_work_id
from clue_api.arv2.logo_resolution import websets_mark_url
from clue_api.arv2.provider_ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.transport import HttpxTransport, Transport
from clue_config import Secrets, Settings
from clue_core import AccountStatus, EntityId, EntityType, ExtractionMethod, ResearchMode, RunId
from clue_db import ConnFactory, transaction
from clue_fleet import FleetTaskKind
from clue_fleet.work_worker import WorkContext, WorkResult
from clue_obs import get_logger
from clue_research.identity import insert_account_entity
from clue_research.identity.normalize import registrable_domain
from clue_research.membership import ensure_project_accounts
from clue_storage import StorageBackend

log = get_logger("clue_api.arv2.discovery_driver")

__all__ = [
    "DiscoveryClients",
    "DiscoveryWake",
    "Arv2DiscoveryWorkHandler",
    "arv2_discovery_work_id",
    "build_arv2_discovery_handler",
    "build_summary",
    "revenue_band",
    "summary_message",
]

#: The failure a wall-clock overrun records. Named, because "the webset never went idle" and "the
#: provider refused to sell" are different problems with different fixes.
WEBSET_WALL_EXCEEDED = "webset_wall_exceeded"

#: The failure a halted provider records.
PROVIDER_HALTED = "provider_halted"

#: The failure a task whose work id disagrees with its payload records.
INVALID_TASK_PAYLOAD = "invalid_task_payload"

#: The failure a Websets call Exa refused (a non-2xx other than a refusal to sell) records.
WEBSET_REFUSED = "websets_request_refused"

#: The failure a ``/search`` call Exa answered with a non-2xx records — named for the same reason
#: as :data:`WEBSET_REFUSED`: a refused search must never read as a dry one.
SEARCH_REFUSED = "search_request_refused"

#: The failure a run launched without the agent's brief records.
BRIEF_MISSING = "brief_missing"

#: Why a run ended (spec 2026-09-30 §4). ``failed`` is a run a failure ended.
EndReason = Literal["filled", "dry", "round_cap", "wall_clock", "stopped", "failed"]

#: The most a ``/search`` round asks Exa for — the endpoint's own ceiling on ``numResults``.
_SEARCH_MAX_RESULTS = 100

#: The candidate id is derived from ``(run, domain)``, so a resumed run re-addresses the row it
#: already wrote instead of racing its own ``ON CONFLICT`` for a second id.
_CANDIDATE_NS = uuid5(NAMESPACE_URL, "arv2-discovery:candidate")

#: The claim source keys: which instrument produced the value.
_ANSWER_SOURCE = "exa_answer"
_WEBSETS_SOURCE = "exa_websets"

#: Is this requester a human the accounts table can name as owner? (ruling 10′)
_IS_PLATFORM_USER = text("SELECT 1 FROM platform_user WHERE user_id = :user_id")

#: ``core.revenue_band``'s closed vocabulary, as ``(upper_bound_exclusive, label)`` walked in
#: order; the last band is open-ended. Spelled here rather than imported because the registry's
#: copy lives in ``clue_research.discovery_scoring``, which this lane may not import (Global
#: Constraint 7) — the enum is pinned against the field's ``value_schema`` by the DB test.
_REVENUE_BANDS: tuple[tuple[int | None, str], ...] = (
    (1_000_000, "under_1m"),
    (10_000_000, "1m_10m"),
    (50_000_000, "10m_50m"),
    (100_000_000, "50m_100m"),
    (500_000_000, "100m_500m"),
    (1_000_000_000, "500m_1b"),
    (None, "1b_plus"),
)

#: The dispositions that mean "the human is being shown this company" — what §4's *shown* counts.
_SHOWN: frozenset[str] = frozenset({"pass", "partial", "unclear"})

#: Every live account of one workspace by domain, oldest first: a company found here that is not
#: yet in this project joins it on this row instead of getting a second account.
_WORKSPACE_ACCOUNTS = text(
    """
    SELECT primary_domain, id FROM account_entity
    WHERE workspace_id = :workspace_id AND merged_into IS NULL AND primary_domain IS NOT NULL
    ORDER BY created_at, id
    """
)

#: The domains of this project's accounts — the companies a run never spends a gate on.
_PROJECT_DOMAINS = text(
    """
    SELECT a.primary_domain FROM project_account p
    JOIN account_entity a ON a.id = p.account_entity_id AND a.workspace_id = p.workspace_id
    WHERE p.workspace_id = :workspace_id AND p.project_id = :project_id
      AND a.primary_domain IS NOT NULL
    """
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def revenue_band(revenue_annual: int | float | Decimal) -> str:
    """The ``core.revenue_band`` label for an annual revenue in dollars. Arithmetic, not a model."""
    amount = Decimal(str(revenue_annual))
    for ceiling, label in _REVENUE_BANDS:
        if ceiling is None or amount < ceiling:
            return label
    return _REVENUE_BANDS[-1][1]  # pragma: no cover - the open band already returned


class DiscoveryClients(Protocol):
    """The two instruments a discovery run uses, each built around one hop's caller."""

    def exa(self, caller: ProviderCaller) -> ExaClient: ...

    def websets(self, caller: ProviderCaller) -> ExaWebsetsClient: ...


class DiscoveryWake(Protocol):
    """Queue the turn that tells the launching thread its discovery run ended (spec §4, §6.3).

    Called inside the transaction that ends the run, after the run's summary is written and
    before it is released. It returns the queued turn's id — the run then stays held until that
    turn finishes — or ``None`` when no turn was queued, and the run is released at once.
    """

    async def queue(
        self,
        conn: AsyncConnection,
        run: DiscoveryRunRow,
        summary: Mapping[str, Any],
        message: str,
    ) -> UUID | None: ...


class _WallExceeded(Arv2Error):
    """The webset did not reach ``idle`` inside the run's wall clock."""


class _WebsetRefused(Arv2Error):
    """Exa answered a Websets call with a non-2xx that is not a refusal to sell.

    Named rather than read as an empty answer: the old widening search was refused with a 400 on
    every run for weeks and read as a search that found nobody.
    """

    code = WEBSET_REFUSED


class _SearchRefused(Arv2Error):
    """Exa answered a ``/search`` round with a non-2xx."""

    code = SEARCH_REFUSED


class _Stopped(Arv2Error):
    """A human asked this run to stop while a webset round was being read."""


@dataclass
class _RunState:
    """What one attempt has learned so far — the numbers its receipt is made of."""

    run: DiscoveryRunRow
    #: The brief the Head of ABM wrote, as the run stored it: the source, and each gate's role.
    brief2: DiscoveryBrief2
    #: The same brief in the verifier's shape: the query, the criteria, and the gates it asks.
    brief: DiscoveryBrief
    today: date
    #: The current search's wall clock (the limit applies per search, founder ruling 2026-09-28).
    deadline: datetime
    #: This project's accounts by domain: no gate is spent on them (``duplicate_of_existing``).
    project_domains: set[str]
    #: Every company an earlier discovery run of this project found (``found_before``).
    found_before: frozenset[str]
    #: Every live account of the workspace by domain: a company found here that is not in this
    #: project is verified against this project's ICP and joins it on this account.
    workspace_accounts: dict[str, UUID]
    #: Every webset an earlier discovery run of this project bought — each search skips them all.
    prior_websets: tuple[str, ...]
    seen: set[str] = field(default_factory=set)
    #: The human who owns and created every account this run lands (founder ruling 2026-09-11:
    #: creator is owner) — the run's requester when that id is a real platform user, else
    #: ``None``. A deepagent-launched run records the fleet's service principal as its requester,
    #: which is nobody's owner and no FK target, so it is resolved once here rather than trusted.
    owner_user_id: str | None = None
    #: This run's searches by ordinal, as recorded.
    searches: dict[int, SearchRow] = field(default_factory=dict)
    #: The webset the current search is reading, and its status as Exa last reported it. Anything
    #: but ``idle`` means Exa may still be finding — and charging for — companies, which is what
    #: :meth:`Arv2DiscoveryWorkHandler._stop_webset` is for.
    webset_id: str | None = None
    webset_status: str | None = None
    #: This run cancelled a webset because it stopped reading before Exa was done, and how many
    #: rows the read after the cancel put on the ledger that no earlier read had.
    webset_stopped: bool = False
    rows_priced_at_stop: int = 0
    #: Every webset row this run has already been charged for. A webset is read on every poll and
    #: again on every resume, and each read returns every row, so without this a row would be
    #: priced onto the ledger many times — on the exact number §8's exit gate divides by.
    priced_item_ids: set[str] = field(default_factory=set)
    #: The per-criterion success rates of the last webset this run read (Exa reports 0–100), for
    #: the summary: a criterion almost nothing satisfies is what starves a search.
    criteria_rates: tuple[tuple[str, float | None], ...] = ()
    recall_estimate: int | None = None
    #: What each search's webset holds and how many companies Exa analyzed for it, by ordinal.
    found_by_search: dict[int, int] = field(default_factory=dict)
    analyzed_by_search: dict[int, int] = field(default_factory=dict)
    shown: int = 0
    duplicates: int = 0
    found_before_count: int = 0
    #: Companies another project already had that this run verified and added to this project.
    from_other_projects: int = 0
    unresolvable: int = 0
    #: The companies a gate's role excluded, by the gate that excluded them, in the order verified.
    excluded: dict[str, list[str]] = field(default_factory=dict)
    #: Companies shown with an ``unclear`` disposition.
    unclear_count: int = 0
    #: Why the run ended, once something has decided it (``None`` while it is still running).
    end_reason: EndReason | None = None
    guards: dict[str, int] = field(default_factory=dict)
    #: One entry per company that was on the list and could not be finished, with the named reason.
    candidate_failures: list[dict[str, str]] = field(default_factory=list)
    cost_usd: Decimal = Decimal(0)
    #: The one cap on verification hops in flight (Task 3): candidates verify in a pool and a
    #: candidate's gates are asked together, all under this semaphore. Built in ``_compose``.
    hops: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    #: Item ids this attempt has handed to the pool — claimed when a task is taken, never when it
    #: finishes, so a re-listed item on the next tick is not verified twice.
    claimed: set[str] = field(default_factory=set)

    def count_guard(self, guard: str) -> None:
        self.guards[guard] = self.guards.get(guard, 0) + 1

    @property
    def found_strict(self) -> int:
        return sum(
            found
            for ordinal, found in self.found_by_search.items()
            if self.searches[ordinal].kind != "relaxed"
        )

    @property
    def found_relaxed(self) -> int:
        return sum(
            found
            for ordinal, found in self.found_by_search.items()
            if self.searches[ordinal].kind == "relaxed"
        )

    @property
    def analyzed(self) -> int:
        return sum(self.analyzed_by_search.values())


class Arv2DiscoveryWorkHandler:
    """One discovery run, as one fleet work handler."""

    kind = FleetTaskKind.ARV2_DISCOVERY

    def __init__(
        self,
        *,
        settings: Settings,
        conn_factory: ConnFactory,
        storage: StorageBackend,
        artifacts: ArtifactSink,
        clients: DiscoveryClients,
        writer: LenientClaimWriter,
        store: Any = default_store,
        transport_factory: Callable[[], Transport] = HttpxTransport,
        clock: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wake: DiscoveryWake | None = None,
    ) -> None:
        self._settings = settings
        # ``None`` means no launching thread is ever woken: every run releases its lock as it ends.
        self._wake = wake
        self._conn_factory = conn_factory
        self._storage = storage
        self._artifacts = artifacts
        self._clients = clients
        self._writer = writer
        # The store is injected as a module-shaped object so the offline tests can record every
        # transition in order without a database.
        self._store = store
        self._transport_factory = transport_factory
        self._clock = clock
        self._sleep = sleep

    # -- fleet entry ---------------------------------------------------------------------------

    async def handle(self, context: WorkContext) -> WorkResult:
        """Drive one run. Never raises: every ending is a :class:`WorkResult`."""
        scope = _scope(context.payload)
        if scope is None:
            # Nothing names a run, so there is no row to flag. The task fails loudly and a human
            # reads the log; inventing an id to mark would be worse than the honest dead end.
            log.error("arv2.discovery_invalid_payload", payload=sorted(context.payload))
            return WorkResult(outcome="failed", references={}, requeue=False)
        run_id, workspace_id = scope
        if context.stop_requested.is_set() or context.lease_lost.is_set():
            await self._suspend(run_id)
            return WorkResult(outcome="stopped", references={"run_id": str(run_id)}, requeue=True)
        if UUID(str(context.work_id)) != run_id:
            # The work id IS the run id (``arv2_discovery_work_id``). A task whose two ids disagree
            # names two runs, and driving either of them would spend real money against a request
            # nobody can reconstruct — so it flags the run it can address and runs nothing.
            await self._contain(
                run_id,
                code=INVALID_TASK_PAYLOAD,
                message=f"task work id {context.work_id} disagrees with run id {run_id}",
            )
            return WorkResult(outcome="needs_review", references={"run_id": str(run_id)})
        try:
            outcome = await self._run(run_id, workspace_id)
        except asyncio.CancelledError:
            # The fleet CANCELS this task when the lease is lost, and ``CancelledError`` is a
            # ``BaseException`` — so without this clause the ``except Exception`` below never runs
            # and the run stays ``in_progress`` for ever. The suspend is shielded because the task
            # is already being cancelled: its own write must survive the cancellation.
            await asyncio.shield(self._suspend(run_id))
            raise
        except Exception as error:  # noqa: BLE001 — containment: the run row is the only report
            log.exception("arv2.discovery_contained_failure", run_id=str(run_id))
            await self._contain(run_id, code=_failure_code(error), message=str(error))
            outcome = "needs_review"
        return WorkResult(outcome=outcome, references={"run_id": str(run_id)})

    # -- the run -------------------------------------------------------------------------------

    async def _run(self, run_id: UUID, workspace_id: str) -> str:
        """Claim, read the brief, run the rounds, verify, land. Raises into ``handle``'s
        containment only for a failure before the run's state exists (a refused brief or pin)."""
        async with self._connection() as conn:
            run = await self._store.begin_discovery_run(conn, run_id=run_id)
        if run is None:
            # An ordinary redelivery: another worker is driving this run, or it already landed.
            log.info("arv2.discovery_not_claimable", run_id=str(run_id), workspace=workspace_id)
            return "completed"

        state = await self._compose(run)
        status, failure = "completed", None
        try:
            await self._search(state)
        except _Stopped:
            # A human pressed Stop mid-round: Exa stops finding (and billing), what it had already
            # found reaches the ledger, and every company already verified is kept.
            await self._stop_webset(state)
            state.end_reason = "stopped"
        except _WallExceeded as exceeded:
            status, failure = "needs_review", (WEBSET_WALL_EXCEEDED, str(exceeded))
            state.end_reason = "wall_clock"
        except ProviderHalted as halted:
            log.warning(
                "arv2.discovery_provider_halted",
                run_id=str(run_id),
                provider=halted.provider,
                reason=halted.reason_code,
            )
            status, failure = "needs_review", (PROVIDER_HALTED, str(halted))
            state.end_reason = "failed"
        except Exception as error:  # noqa: BLE001 — containment: the run row is the only report
            # Landed here rather than in ``handle`` so the receipt keeps every counter, the summary
            # names what was verified before the failure, and the end block still runs.
            log.exception("arv2.discovery_contained_failure", run_id=str(run_id))
            status, failure = "needs_review", (_failure_code(error), str(error))
            state.end_reason = "failed"
        if failure is not None:
            await self._stop_webset(state)
        if state.end_reason == "stopped":
            status = "stopped"
        elif status == "completed" and state.candidate_failures:
            # Every other candidate landed and every counter is kept; the run still asks for a
            # human, because a company that was on the list and has no verdict is not a finished
            # run — it is a finished run minus a company, and the receipt names which.
            status = "needs_review"
        try:
            await self._land(state, status=status, failure=failure)
        except Exception as error:  # noqa: BLE001 — containment, with the counters it had
            log.exception("arv2.discovery_land_failed", run_id=str(run_id))
            state.end_reason = "failed"
            code = _failure_code(error)
            await self._contain(
                run_id, code=code, message=str(error), summary=build_summary(state, failure=code)
            )
            return "needs_review"
        return status

    async def _compose(self, run: DiscoveryRunRow) -> _RunState:
        """Read the brief, re-check the pin, and read everything this attempt must not spend twice
        on."""
        if run.brief is None:
            raise Arv2DiscoveryRefused(
                BRIEF_MISSING, "this run was launched without an agent brief"
            )
        brief2 = DiscoveryBrief2.model_validate(run.brief)
        now = self._clock()
        async with self._connection() as conn:
            # The RUN's pinned bytes, not the project's current pin. The brief is the agent's, but
            # it was written against this document and the fit claims name it by key and sha, so
            # a run whose pinned bytes moved is refused by name rather than scored against another.
            await read_icp_document(
                conn,
                self._storage,
                workspace_id=run.workspace_id,
                artifact_key=run.icp_artifact_key,
                artifact_sha256=run.icp_artifact_sha256,
            )
            workspace_accounts = await self._workspace_accounts(conn, run.workspace_id)
            project_domains = await self._project_domains(conn, run)
            found_before = await self._store.project_found_domains(
                conn,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                before_run_id=run.run_id,
            )
            prior_websets = await self._store.project_webset_ids(
                conn,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                before_run_id=run.run_id,
            )
            searches = await self._store.list_searches(conn, run_id=run.run_id)
            already = await self._store.list_candidates(conn, run_id=run.run_id)
            owner_user_id = await self._owner_user(conn, run.requested_by_user_id)
        state = _RunState(
            run=run,
            brief2=brief2,
            brief=DiscoveryBrief(
                query=brief2.query,
                criteria=tuple(brief2.criteria),
                criteria_gate_keys=(),
                gates=verifier_gates(brief2),
                exclusions=(),
            ),
            today=now.date(),
            deadline=now + timedelta(seconds=self._settings.arv2_discovery_wall_s),
            project_domains=project_domains,
            found_before=frozenset(found_before),
            workspace_accounts=workspace_accounts,
            prior_websets=tuple(prior_websets),
            owner_user_id=owner_user_id,
            searches={search.ordinal: search for search in searches},
            recall_estimate=run.recall_estimate,
            hops=asyncio.Semaphore(self._settings.arv2_discovery_verify_concurrency),
        )
        for search in searches:
            if search.found is not None:
                state.found_by_search[search.ordinal] = search.found
            if search.analyzed is not None:
                state.analyzed_by_search[search.ordinal] = search.analyzed
        # What an earlier attempt of this run already verified is neither re-asked nor re-billed.
        # A candidate still ``pending`` is the exception: an attempt that died between writing the
        # row and recording its verdicts bought nothing that survives, so skipping it would strand
        # a company on the list for ever with no verdict and no account.
        for candidate in already:
            if candidate.disposition == "pending":
                continue
            state.seen.add(candidate.domain)
            websets_domain = candidate.provider_snapshot.get("websets_domain")
            if isinstance(websets_domain, str) and websets_domain:
                state.seen.add(websets_domain)
            if candidate.disposition in _SHOWN:
                state.shown += 1
            if candidate.disposition == "unclear":
                state.unclear_count += 1
            if candidate.disposition == "excluded" and candidate.excluded_by_gate:
                state.excluded.setdefault(candidate.excluded_by_gate, []).append(candidate.name)
        # Every row an earlier attempt read was priced then; the raw Websets item is kept whole on
        # the candidate's snapshot, so its id is recoverable and this attempt does not buy it again.
        for candidate in already:
            item_id = _snapshot_item_id(candidate)
            if item_id:
                state.priced_item_ids.add(item_id)
        return state

    # -- step one: the rounds --------------------------------------------------------------------

    async def _search(self, state: _RunState) -> None:
        """Run rounds of the same brief until the run is filled, dry, capped or stopped.

        Round 1 asks for ``target_count``; every later round asks for the shortfall, excluding
        every company seen so far (spec §4). A round this run already finished is skipped; one it
        started — bought, or only recorded — is picked back up rather than bought again (see
        :meth:`_run_search`). Stop is read before every new round, and between the polls of a
        webset round (:meth:`_watch_and_verify`).
        """
        run = state.run
        last = 1 + self._settings.arv2_discovery_max_topups
        for ordinal in range(1, last + 1):
            search = state.searches.get(ordinal)
            if search is not None and search.finished_at is not None:
                continue
            resumed = search is not None
            if search is None:
                if state.shown >= run.target_count:
                    return
                if await self._stop_requested(state):
                    state.end_reason = "stopped"
                    return
                search = await self._open_search(state, ordinal, "round", state.brief.criteria)
            before = len(state.seen)
            if search.source == "search":
                await self._run_search_round(state, search)
            else:
                await self._run_search(state, search)
            # Nothing new: the same brief asked again would find nothing more. A resumed round's
            # companies were counted as seen by the attempt that read them, so it is dry only when
            # its search found nothing at all.
            if len(state.seen) == before and not (resumed and state.found_by_search.get(ordinal)):
                if state.shown < run.target_count:
                    state.end_reason = "dry"
                return
        if state.shown < run.target_count:
            state.end_reason = "round_cap"

    async def _stop_requested(self, state: _RunState) -> bool:
        """Whether a human pressed Stop on this run (a free read, made between steps)."""
        async with self._connection() as conn:
            return bool(await self._store.stop_requested(conn, run_id=state.run.run_id))

    async def _open_search(
        self, state: _RunState, ordinal: int, kind: SearchKind, criteria: tuple[str, ...]
    ) -> SearchRow:
        """Record the next round — before anything is bought — asking only for the shortfall.

        A webset round skips every webset this project's earlier discovery runs bought and every
        webset this run has bought so far, so no company is found, or charged for, a second time.
        """
        run = state.run
        own = tuple(
            search.webset_id
            for _, search in sorted(state.searches.items())
            if search.webset_id is not None
        )
        row = SearchRow(
            run_id=run.run_id,
            ordinal=ordinal,
            kind=kind,
            external_id=f"arv2-discovery:{run.run_id}:{ordinal}",
            asked=run.target_count - state.shown,
            criteria=tuple(criteria),
            exclude_webset_ids=tuple(dict.fromkeys(state.prior_websets + own)),
            source=state.brief2.source,
        )
        async with self._connection() as conn:
            held: SearchRow = await self._store.create_search(conn, row)
        state.searches[ordinal] = held
        log.info(
            "arv2.discovery_search_opened",
            run_id=str(run.run_id),
            ordinal=ordinal,
            kind=kind,
            source=held.source,
            asked=held.asked,
            excluded_websets=len(held.exclude_webset_ids),
        )
        return held

    async def _run_search_round(self, state: _RunState, search: SearchRow) -> None:
        """One ``/search`` round: ask Exa for companies with the brief's query, verify the new ones.

        It asks for twice the shortfall (a search result is a page, not a company, and some do not
        survive the verifier) plus one result for every domain already known — this run's, this
        project's accounts, and every company an earlier discovery of the project found — and
        skips the known ones here. It does not send them as ``excludeDomains``: with the company
        category, Exa answers any ``excludeDomains`` at all with zero results (live 2026-10-01 —
        even a list holding only ``example.com``), which ended every search round dry. Asking for
        more instead also moves a later round past the same query's earlier answers.
        """
        run = state.run
        known = state.seen | state.project_domains | state.found_before
        query = state.brief.query
        result = await self._hop(
            state,
            lambda caller: self._clients.exa(caller).search(
                query,
                category="company",
                num_results=min(_SEARCH_MAX_RESULTS, 2 * search.asked + len(known)),
                label=f"discovery-search-{search.ordinal}",
            ),
        )
        if not 200 <= result.status < 300:
            raise _SearchRefused(f"exa search refused round {search.ordinal}: http {result.status}")
        items = [_item_from_hit(hit) for hit in result.results if hit.url]
        state.found_by_search[search.ordinal] = len(items)
        # Verification is the spend, so a round verifies at most twice its shortfall. The padding
        # above only makes room for the known domains Exa still returns; without this bound a
        # three-company ask verified all 42 new results live (2026-10-01) and added 31.
        budget = 2 * search.asked
        tasks: set[asyncio.Task[None]] = set()
        for item in items:
            if len(tasks) >= budget:
                break
            domain = registrable_domain(item.url) or ""
            if not domain or domain in known or domain in state.seen:
                continue
            state.seen.add(domain)
            tasks.add(asyncio.create_task(self._verify_contained(state, item, pass_="strict")))
        await self._drain_pool(tasks)
        async with self._connection() as conn:
            await self._store.record_discovery_progress(
                conn,
                run_id=run.run_id,
                found_strict=state.found_strict,
                found_relaxed=state.found_relaxed,
                analyzed=state.analyzed,
            )
            await self._store.finish_search(
                conn,
                run_id=run.run_id,
                ordinal=search.ordinal,
                found=len(items),
                analyzed=None,
                recall_estimate=None,
            )
        state.searches[search.ordinal] = replace(
            search, found=len(items), finished_at=self._clock()
        )

    async def _run_search(self, state: _RunState, search: SearchRow) -> None:
        """Buy this search's webset if nobody has yet, verify everything it finds, then close it.

        A row with no ``webset_id`` is either a search never created or one whose create answered
        after the attempt died: the webset is looked up by ``external_id`` first, so only the
        former is bought. The wall clock is this search's own (founder ruling 2026-09-28).
        """
        run = state.run
        state.deadline = self._clock() + timedelta(seconds=self._settings.arv2_discovery_wall_s)
        if search.webset_id is None:
            external_id = search.external_id
            view = await self._hop(
                state, lambda caller: self._clients.websets(caller).find(external_id)
            )
            if view is None:
                title = (
                    f"ARV2 discovery {run.project_id} {run.icp_key}@{run.icp_version} "
                    f"search {search.ordinal}"
                )
                view = await self._hop(
                    state,
                    lambda caller: self._clients.websets(caller).create(
                        query=state.brief.query,
                        count=search.asked,
                        criteria=search.criteria,
                        external_id=external_id,
                        title=title,
                        exclude_webset_ids=search.exclude_webset_ids,
                        # The pool-size estimate is asked once, of the first search: it is what
                        # tells "Exa ran out" apart from "our checks removed some".
                        recall=search.ordinal == 1,
                    ),
                )
            self._require(view)
            search = replace(search, webset_id=view.webset_id)
            state.searches[search.ordinal] = search
            self._read_view(state, search, view)
            async with self._connection() as conn:
                await self._store.record_search_webset(
                    conn,
                    run_id=run.run_id,
                    ordinal=search.ordinal,
                    webset_id=view.webset_id,
                    recall_estimate=state.recall_estimate if search.ordinal == 1 else None,
                )
        else:
            log.info(
                "arv2.discovery_search_resumed",
                run_id=str(run.run_id),
                ordinal=search.ordinal,
                webset_id=search.webset_id,
            )
        state.webset_id = search.webset_id
        await self._watch_and_verify(state, search)
        async with self._connection() as conn:
            await self._store.finish_search(
                conn,
                run_id=run.run_id,
                ordinal=search.ordinal,
                found=state.found_by_search.get(search.ordinal, 0),
                analyzed=state.analyzed_by_search.get(search.ordinal),
                recall_estimate=state.recall_estimate if search.ordinal == 1 else None,
            )
        state.searches[search.ordinal] = replace(
            search,
            found=state.found_by_search.get(search.ordinal, 0),
            finished_at=self._clock(),
        )

    @staticmethod
    def _require(view: WebsetView) -> None:
        """A view Exa answered with a non-2xx describes nothing; say so by name."""
        if view.error is not None:
            raise _WebsetRefused(f"exa websets refused webset {view.webset_id}: {view.error}")

    async def _read_items(self, state: _RunState, webset_id: str) -> tuple[WebsetItem, ...]:
        """The billed read of one webset. ``all_green`` is Exa's *bill*, never a verdict.

        A webset is read on every poll and again on every resume, and each read returns the WHOLE
        webset — so the rows this run has already been charged for are named to the client and
        priced at zero. The bill for one row is paid once per run, which is what makes the
        receipt's ``cost_usd`` (and §8's cost-per-approved-account) mean what it says.
        """
        priced = frozenset(state.priced_item_ids)
        result: WebsetItemsResult = await self._hop(
            state,
            lambda caller: self._clients.websets(caller).items(webset_id, priced_item_ids=priced),
        )
        state.priced_item_ids.update(result.priced_item_ids)
        if result.error is not None:
            raise _WebsetRefused(f"exa websets refused the items of {webset_id}: {result.error}")
        log.info(
            "arv2.discovery_items",
            run_id=str(state.run.run_id),
            webset_id=webset_id,
            items=len(result.items),
            credits_est=result.credits_est,
            newly_priced=len(result.priced_item_ids),
        )
        return result.items

    async def _watch_and_verify(self, state: _RunState, search: SearchRow) -> None:
        """Poll one search's webset to ``idle`` and verify every new item on every tick (spec §2).

        Each tick lists the webset (a row is priced once per run, so re-listing costs nothing),
        hands every unclaimed item to a task, records the counters, and sleeps. On ``idle`` one
        last list catches stragglers, and the pool is drained before returning.

        A company is claimed **at dispatch**, by item id and by registrable domain: two rows of one
        company must never be two verifications, which would be two bills and two accounts.

        A human's Stop is read before every poll: the tasks in flight are drained and
        :class:`_Stopped` is raised, so ``_run`` cancels the webset and lands the run ``stopped``.

        Containment is per task (``_verify_contained``); ``ProviderHalted``, a refused Websets call
        and the wall clock are not contained — the first of them cancels the pool and re-raises, so
        ``_run`` lands the run ``needs_review``.
        """
        webset_id = str(search.webset_id)
        pass_: Pass = "relaxed" if search.kind == "relaxed" else "strict"
        tasks: set[asyncio.Task[None]] = set()

        async def _tick(final: bool) -> None:
            items = await self._read_items(state, webset_id)
            self._count_found(state, search, items)
            for item in items:
                domain = registrable_domain(item.url) or ""
                if item.item_id in state.claimed:
                    continue
                if domain and domain in state.seen:
                    continue
                state.claimed.add(item.item_id)
                if domain:
                    state.seen.add(domain)
                tasks.add(asyncio.create_task(self._verify_contained(state, item, pass_=pass_)))
            async with self._connection() as conn:
                await self._store.record_discovery_progress(
                    conn,
                    run_id=state.run.run_id,
                    found_strict=state.found_strict,
                    found_relaxed=state.found_relaxed,
                    analyzed=state.analyzed,
                )
            if final:
                await self._drain_pool(tasks)
            else:
                await self._reap(tasks)

        try:
            while True:
                if await self._stop_requested(state):
                    # Every verification already in flight was paid for as it started: let it land,
                    # dispatch nothing more, and let ``_run`` cancel the webset.
                    await self._drain_pool(tasks)
                    raise _Stopped(f"a human stopped the run while webset {webset_id} was read")
                if self._clock() > state.deadline:
                    raise _WallExceeded(
                        f"webset {webset_id} did not reach idle within "
                        f"{self._settings.arv2_discovery_wall_s}s"
                    )
                view = await self._hop(
                    state, lambda caller: self._clients.websets(caller).get(webset_id)
                )
                self._require(view)
                self._read_view(state, search, view)
                if view.status == "idle":
                    await _tick(final=True)
                    return
                await _tick(final=False)
                await self._sleep(self._settings.arv2_discovery_poll_interval_s)
        except BaseException:
            await _abort(tasks)
            raise

    @staticmethod
    async def _reap(tasks: set[asyncio.Task[None]]) -> None:
        """Surface a finished task's uncontained exception now, not at the end of the run.

        Every finished task's failure is READ before the first one is raised: two candidates
        halting on the same tick is two exceptions, and an exception nobody retrieved makes asyncio
        log "Task exception was never retrieved" when the task is collected — noise in a run whose
        real story is already named on its receipt.
        """
        done = {task for task in tasks if task.done()}
        tasks.difference_update(done)
        failures = [task.exception() for task in done if not task.cancelled()]
        first = next((error for error in failures if error is not None), None)
        if first is not None:
            raise first

    @staticmethod
    async def _drain_pool(tasks: set[asyncio.Task[None]]) -> None:
        """Wait for every task; the first uncontained exception cancels the rest and propagates."""
        if not tasks:
            return
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            if not task.cancelled() and task.exception() is not None:
                await _abort(tasks)
                raise task.exception()  # type: ignore[misc]
        await asyncio.gather(*tasks)
        tasks.clear()

    def _count_found(
        self, state: _RunState, search: SearchRow, items: Sequence[WebsetItem]
    ) -> None:
        """What the search's webset HOLDS, not what this attempt happened to verify — and
        monotonic, so a read that lists fewer rows than the one before cannot walk it backwards."""
        state.found_by_search[search.ordinal] = max(
            state.found_by_search.get(search.ordinal, 0), len(items)
        )

    async def _stop_webset(self, state: _RunState) -> None:
        """Cancel a webset this run stopped reading before Exa was done, then read it once more.

        Exa charges for a company when it finds it; the ledger prices a company when this run
        reads it. A run that ends early — a provider halt, the wall clock, an uncontained error —
        would otherwise leave its webset finding (and billing) up to ``count`` companies nobody
        ever reads: run ``ee79d837`` stopped at 7 of 35 and Exa went on to find all 35. The cancel
        stops the finding; the read puts on the ledger every row Exa had already found.

        A webset already ``idle`` has nothing to stop, and its last read priced every row. A
        suspended run is not stopped either: its resume reads the same webset. Never raises — the
        run is already ending, and a failure here is logged rather than replacing its reason.
        """
        if state.webset_id is None or state.webset_status == "idle":
            return
        webset_id = state.webset_id
        try:
            view = await self._hop(
                state, lambda caller: self._clients.websets(caller).cancel(webset_id)
            )
            state.webset_status = view.status
            state.webset_stopped = True
        except Exception:  # noqa: BLE001 — the run's own failure stays the reason on its receipt
            log.exception("arv2.discovery_webset_cancel_failed", run_id=str(state.run.run_id))
        try:
            already = len(state.priced_item_ids)
            items = await self._read_items(state, webset_id)
            state.rows_priced_at_stop += len(state.priced_item_ids) - already
            current = next(
                (search for search in state.searches.values() if search.webset_id == webset_id),
                None,
            )
            if current is not None:
                self._count_found(state, current, items)
        except Exception:  # noqa: BLE001 — as above
            log.exception("arv2.discovery_webset_final_read_failed", run_id=str(state.run.run_id))
        log.info(
            "arv2.discovery_webset_stopped",
            run_id=str(state.run.run_id),
            webset_id=webset_id,
            cancelled=state.webset_stopped,
            rows_priced_at_stop=state.rows_priced_at_stop,
        )

    def _read_view(self, state: _RunState, search: SearchRow, view: WebsetView) -> None:
        """Keep what a poll of the current round's webset reports: its status, how many companies
        Exa analyzed, the criteria's success rates (the summary names the last round's), and — for
        round 1 — the pool-size estimate. Each webset holds exactly one search."""
        state.webset_status = view.status
        if not view.searches:
            return
        reported = view.searches[0]
        if reported.analyzed is not None:
            state.analyzed_by_search[search.ordinal] = reported.analyzed
        if reported.criteria_success_rates:
            state.criteria_rates = reported.criteria_success_rates
        if search.ordinal == 1 and reported.recall_estimate is not None:
            state.recall_estimate = reported.recall_estimate

    # -- step two: the verifier ----------------------------------------------------------------

    async def _verify_contained(self, state: _RunState, item: WebsetItem, *, pass_: Pass) -> None:
        """One candidate, whose own failure is its own — never the whole run's.

        A strong-key clash on the account write, a claim the gate refuses, an item shaped in a way
        nothing anticipated: one company going wrong must not strand the others, which have already
        been paid for and would otherwise be re-bought by the next attempt. The failure is logged,
        named on the receipt, and the loop moves on; the candidate row stays as it is (``pending``,
        so a later attempt re-verifies it — see :meth:`_compose`). ``ProviderHalted`` and the wall
        clock are deliberately NOT contained here: both mean the *run* cannot continue.
        ``CancelledError`` is a ``BaseException`` and passes through untouched.
        """
        try:
            await self._verify_candidate(state, item, pass_=pass_)
        except (ProviderHalted, _WallExceeded):
            raise
        except Exception as error:  # noqa: BLE001 — containment: one company, not the run
            # The long list's domain, because the verified one may not have been reached.
            domain = registrable_domain(item.url) or item.url
            log.exception(
                "arv2.discovery_candidate_failed", run_id=str(state.run.run_id), domain=domain
            )
            state.candidate_failures.append({"domain": domain, "code": _failure_code(error)})

    async def _verify_candidate(self, state: _RunState, item: WebsetItem, *, pass_: Pass) -> None:
        """One company: its website, the dedupes, every gate, the account and its claims."""
        run = state.run
        websets_domain = registrable_domain(item.url)
        verified, evidence_url = await self._verify_website(state, item, websets_domain)
        if verified is None:
            state.unresolvable += 1
            log.info(
                "arv2.discovery_unresolvable_domain",
                run_id=str(run.run_id),
                name=item.name,
                url=item.url,
            )
            return
        if verified != websets_domain and verified in state.seen:
            # Another in-flight task already owns this company — nothing left to buy. The long
            # list's domain was claimed at dispatch, so this can only be a row whose *verified*
            # domain turned out to belong to a company the run has already taken.
            return
        state.seen.add(verified)
        if websets_domain is not None:
            state.seen.add(websets_domain)
        snapshot: dict[str, JsonValue] = {
            "websets_domain": websets_domain,
            "verified_domain": verified,
            "evidence_url": evidence_url,
            "item": dict(item.raw),
        }
        row = CandidateRow(
            candidate_id=uuid5(_CANDIDATE_NS, f"{run.run_id}:{verified}"),
            run_id=run.run_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            pass_=pass_,
            domain=verified,
            websets_url=item.url,
            name=item.name,
            provider_snapshot=snapshot,
        )

        refusal = self._pre_spend_disposition(state, verified)
        if refusal is not None:
            async with self._connection() as conn:
                await self._store.upsert_candidate(conn, _replace_disposition(row, refusal))
            log.info(
                "arv2.discovery_candidate_skipped",
                run_id=str(run.run_id),
                domain=verified,
                disposition=refusal,
            )
            return

        async with self._connection() as conn:
            candidate_id = await self._store.upsert_candidate(conn, row)
        verdicts = await self._verify_gates(state, item.name, verified)
        for verdict in verdicts:
            state.count_guard(verdict.guard)
        roles = apply_roles(state.brief2, verdicts)
        if roles.excluded_by is not None:
            # A failed ``must`` or a passed ``must_not``: kept on the run with the gate that decided
            # it and the verdicts behind it, never an account, never counted toward the target.
            # Written through ``record_verdicts`` because the row already exists ``pending``.
            async with self._connection() as conn:
                await self._store.record_verdicts(
                    conn,
                    candidate_id=candidate_id,
                    verdicts=[verdict.as_json() for verdict in verdicts],
                    fit=None,
                    disposition="excluded",
                    excluded_by_gate=roles.excluded_by,
                    account_entity_id=None,
                )
            state.excluded.setdefault(roles.excluded_by, []).append(item.name)
            log.info(
                "arv2.discovery_candidate_excluded",
                run_id=str(run.run_id),
                domain=verified,
                gate=roles.excluded_by,
            )
            return
        fit = roles.fit
        outcome: Disposition = roles.shown_disposition  # type: ignore[assignment]
        logo = await self._resolve_logo(state, item=item, verified=verified)
        # An account of the workspace that is not in this project (founder ruling 2026-09-28) is
        # checked against THIS project's ICP like any other company, and joins this project on its
        # own row — a second account for one domain would split its research in two.
        existing_account = state.workspace_accounts.get(verified)
        async with self._connection() as conn:
            if existing_account is not None:
                account_id = EntityId(existing_account)
            else:
                account_id = await insert_account_entity(
                    conn,
                    canonical_name=item.name,
                    primary_domain=verified,
                    workspace_id=run.workspace_id,
                    status=AccountStatus.CANDIDATE,
                    # Founder ruling 2026-09-11: the creator is the owner by default — the human
                    # who launched the discovery made these accounts exist and owns them until an
                    # ownership mechanism says otherwise. Only a real platform user is stamped: a
                    # run the deepagent launched on the fleet records the service principal as its
                    # requester, and that id is no owner (and no FK target).
                    owner_user_id=state.owner_user_id,
                    created_by_user_id=state.owner_user_id,
                )
            await self._write_claims(
                conn,
                state,
                item=item,
                account_id=account_id,
                verdicts=verdicts,
                fit=fit,
                pass_=pass_,
                verified=verified,
                logo=logo,
            )
            await self._store.record_verdicts(
                conn,
                candidate_id=candidate_id,
                verdicts=[verdict.as_json() for verdict in verdicts],
                fit=fit,
                disposition=outcome,
                account_entity_id=UUID(str(account_id)),
            )
            # Founder ruling 2026-09-11 (supersedes 6′): a discovered account belongs to the
            # project that launched the discovery, by default and from the moment it is verified —
            # pass, partial and unclear alike, the human reads the verdicts on the table. Adding it
            # to any OTHER project stays an explicit human action ("Add to project"). Same
            # transaction as the account row and its claims, so a candidate is never an account
            # without a project, nor a member without its verdicts.
            await ensure_project_accounts(
                conn,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                account_entity_ids=[UUID(str(account_id))],
                added_via="discovered",
            )
        state.project_domains.add(verified)
        state.workspace_accounts[verified] = UUID(str(account_id))
        if existing_account is not None:
            state.from_other_projects += 1
        if outcome in _SHOWN:
            state.shown += 1
        if outcome == "unclear":
            state.unclear_count += 1
        log.info(
            "arv2.discovery_candidate_verified",
            run_id=str(run.run_id),
            domain=verified,
            disposition=outcome,
            fit=fit,
            from_other_project=existing_account is not None,
        )

    async def _verify_website(
        self, state: _RunState, item: WebsetItem, websets_domain: str | None
    ) -> tuple[str | None, str]:
        """The company's own domain, per its announcement or LinkedIn page — the long list's is a
        guess, and every dedupe and right-company guard downstream keys on this answer."""
        result = await self._answer(
            state,
            query=website_question(item.name, item.url),
            output_schema=WEBSITE_SCHEMA,
            label=f"discovery-website-{websets_domain or item.name}",
        )
        answered, evidence_url = None, ""
        if isinstance(result.answer, Mapping):
            answered = registrable_domain(str(result.answer.get("website_domain") or ""))
            evidence_url = str(result.answer.get("evidence_url") or "")
        return answered or websets_domain, evidence_url

    def _pre_spend_disposition(self, state: _RunState, verified: str) -> Disposition | None:
        """What this company is *before* a gate is asked, or ``None`` when it is worth verifying.

        Already one of this project's accounts, or found by an earlier discovery run of this
        project: nothing to ask. An account of ANOTHER project is worth verifying — against this
        project's ICP — and is not refused here.
        """
        if verified in state.project_domains:
            state.duplicates += 1
            return "duplicate_of_existing"
        if verified in state.found_before:
            state.found_before_count += 1
            return "found_before"
        return None

    async def _verify_gates(
        self, state: _RunState, company_name: str, verified: str
    ) -> tuple[GateVerdict, ...]:
        """Every gate of the brief — asked together, then guarded in the brief's order.

        The verdicts are assembled only once every answer is back, so parallel questions change
        nothing about what is decided; the semaphore on ``_answer`` decides how many are in flight.

        When one gate fails, the siblings are cancelled and awaited before the failure leaves this
        method (ruling R8). Letting them run on would put their cost on the ledger after the run
        had already landed — a receipt that under-reports what was spent — and would leave a second
        failure unobserved. ``_hop`` makes that cancellation safe: a cancelled ask still pays.
        """
        tasks = [
            asyncio.create_task(
                self._answer(
                    state,
                    query=gate_question(company_name, f"https://{verified}", gate),
                    output_schema=OUTPUT_SCHEMA,
                    label=f"discovery-{gate.key}-{verified}",
                )
            )
            for gate in state.brief.gates
        ]
        try:
            answers = await asyncio.gather(*tasks)
        except BaseException:
            await _abort(tasks)
            raise
        return tuple(
            apply_guards(
                gate=gate,
                answer=result.answer,
                today=state.today,
            )
            for gate, result in zip(state.brief.gates, answers, strict=True)
        )

    async def _answer(
        self,
        state: _RunState,
        *,
        query: str,
        output_schema: Mapping[str, object],
        label: str,
    ) -> ExaAnswerResult:
        """One ``/answer`` hop under this run's system prompt and configured model.

        Every Answer hop this run makes — the website ask and each gate — passes through here, so
        ``state.hops`` is the run's single cap on how many of them are in flight (Task 3).
        """
        prompt = system_prompt(state.today)
        model = self._settings.arv2_discovery_answer_model
        async with state.hops:
            return await self._hop(
                state,
                lambda caller: self._clients.exa(caller).answer(
                    query,
                    system_prompt=prompt,
                    output_schema=output_schema,
                    model=model,
                    label=label,
                ),
            )

    async def _owner_user(self, conn: AsyncConnection, requested_by: str) -> str | None:
        """The run's requester when it is a platform user, else ``None`` (see ``_RunState``)."""
        row = await conn.execute(_IS_PLATFORM_USER, {"user_id": requested_by})
        return requested_by if row.first() is not None else None

    async def _write_claims(
        self,
        conn: AsyncConnection,
        state: _RunState,
        *,
        item: WebsetItem,
        account_id: EntityId,
        verdicts: Sequence[GateVerdict],
        fit: float | None,
        pass_: Pass,
        verified: str,
        logo: tuple[str, str] | None = None,
    ) -> None:
        """The fit the gates produced, the two long-list facts worth keeping, and the mark.

        ``logo`` is ``(url, source_key)`` from :meth:`_resolve_logo`, or ``None`` when Websets
        returned no LinkedIn mark — then no ``core.logo_url`` claim is written and the reads fall
        back to Brandfetch's Logo API URL for the domain (or the placeholder).

        The fit claim cites the first *passing* verdict's page and quote, because that is the
        evidence a reader of the score should land on; a fit with no passing gate cites the
        company's own site and carries no span rather than borrowing an unrelated one. A brief
        whose every gate is a ``must_not`` scores nothing (``fit`` is ``None``): no fit is written.
        """
        run = state.run
        supporting = next((v for v in verdicts if v.verdict == "pass"), None)
        markers: dict[str, JsonValue] = {
            "discovery_run_id": str(run.run_id),
            "pass": pass_,
            "gates": {verdict.gate_key: verdict.verdict for verdict in verdicts},
            # The document the score was scored against, by key and by bytes: a fit is only
            # readable next to the gates that produced it, and those move with the ICP version.
            "icp_artifact_key": run.icp_artifact_key,
            "icp_artifact_sha256": run.icp_artifact_sha256,
        }
        if fit is not None:
            await self._writer.write(
                conn,
                self._draft(
                    run,
                    account_id=account_id,
                    field_key="account.scoring.fit",
                    value_json={"value": fit},
                    source_key=_ANSWER_SOURCE,
                    source_url=(
                        supporting.evidence_url if supporting is not None else f"https://{verified}"
                    ),
                    evidence_span=supporting.evidence_quote if supporting is not None else None,
                    confidence=fit,
                    markers=markers,
                ),
            )
        if isinstance(item.employees, int) and not isinstance(item.employees, bool):
            await self._writer.write(
                conn,
                self._draft(
                    run,
                    account_id=account_id,
                    field_key="core.employee_count",
                    value_json=item.employees,
                    source_key=_WEBSETS_SOURCE,
                    source_url=item.url,
                    markers={"discovery_run_id": str(run.run_id)},
                ),
            )
        if item.revenue_annual is not None:
            await self._writer.write(
                conn,
                self._draft(
                    run,
                    account_id=account_id,
                    field_key="core.revenue_band",
                    value_json=revenue_band(item.revenue_annual),
                    source_key=_WEBSETS_SOURCE,
                    source_url=item.url,
                    markers={"discovery_run_id": str(run.run_id)},
                ),
            )
        if logo is not None:
            logo_url, logo_source = logo
            await self._writer.write(
                conn,
                self._draft(
                    run,
                    account_id=account_id,
                    field_key="core.logo_url",
                    value_json=logo_url,
                    source_key=logo_source,
                    source_url=logo_url,
                    markers={"discovery_run_id": str(run.run_id), "logo_kind": "mark"},
                ),
            )

    async def _resolve_logo(
        self, state: _RunState, *, item: WebsetItem, verified: str
    ) -> tuple[str, str] | None:
        """The account's stored mark: Websets' LinkedIn company mark, else nothing.

        Founder rulings 2026-09-11, on the proof of concept's numbers (``logo_resolution``): the
        mark only, and Brandfetch through its Logo API only — which is an embed-only CDN the
        platform never fetches, so a company without a LinkedIn mark stores no logo here and the
        reads hand the browser Brandfetch's URL for its domain at display time.
        """
        del state, verified
        mark = websets_mark_url(item.logo_url)
        return None if mark is None else (mark, _WEBSETS_SOURCE)

    def _draft(
        self,
        run: DiscoveryRunRow,
        *,
        account_id: EntityId,
        field_key: str,
        value_json: JsonValue,
        source_key: str,
        source_url: str,
        evidence_span: str | None = None,
        confidence: float = 0.5,
        markers: Mapping[str, JsonValue],
    ) -> ClaimDraft:
        """One account claim of this run, in the lane's one write shape."""
        return ClaimDraft(
            entity_id=EntityId(UUID(str(account_id))),
            entity_type=EntityType.ACCOUNT,
            field_key=field_key,
            value_json=value_json,
            extraction_method=ExtractionMethod.API,
            run_id=RunId(run.run_id),
            research_mode=ResearchMode.ACCOUNT_DISCOVERY,
            workspace_id=run.workspace_id,
            source_url=source_url,
            source_key=source_key,
            evidence_span=evidence_span,
            confidence=confidence,
            markers=dict(markers),
        )

    # -- landing ---------------------------------------------------------------------------------

    async def _land(
        self, state: _RunState, *, status: str, failure: tuple[str, str] | None
    ) -> None:
        """Write the run's terminal row — the §4 counters and the receipt behind them — and end it
        through :meth:`_end`, in one transaction."""
        run = state.run
        if state.end_reason is None:
            state.end_reason = "filled" if state.shown >= run.target_count else "dry"
        receipt: dict[str, JsonValue] = {
            "asked": sum(search.asked for search in state.searches.values()) or None,
            "recall_estimate": state.recall_estimate,
            "shown": state.shown,
            "target_count": run.target_count,
            "source": state.brief2.source,
            "criteria": list(state.brief.criteria),
            "end_reason": state.end_reason,
            # Every search this run made, in order: what it asked for, what it sent, what it found.
            "searches": [
                {
                    "ordinal": search.ordinal,
                    "kind": search.kind,
                    "source": search.source,
                    "asked": search.asked,
                    "criteria": list(search.criteria),
                    "excluded_websets": len(search.exclude_webset_ids),
                    "webset_id": search.webset_id,
                    "found": state.found_by_search.get(search.ordinal),
                }
                for _, search in sorted(state.searches.items())
            ],
            "guards": dict(state.guards),
            "cost_usd": str(state.cost_usd),
            # States the assumption behind the number above: a webset row is priced once per run,
            # not once per read, so a resumed run does not over-report its own spend.
            "credits_priced_once": True,
            # The run ended before a webset did, so it cancelled it (see ``_stop_webset``), and
            # this many rows reached the ledger only through the read after the cancel.
            "webset_stopped": state.webset_stopped,
            "rows_priced_at_stop": state.rows_priced_at_stop,
            "duplicates": state.duplicates,
            "found_before": state.found_before_count,
            "from_other_projects": state.from_other_projects,
            "unresolvable_domain": state.unresolvable,
            "excluded": {gate: len(names) for gate, names in state.excluded.items()},
            "candidate_failures": [dict(failure) for failure in state.candidate_failures],
        }
        if failure is not None:
            receipt["failure"], receipt["message"] = failure[0], failure[1][:1_000]
        summary = build_summary(state, failure=None if failure is None else failure[0])
        async with self._connection() as conn:
            await self._store.finish_discovery_run(
                conn,
                run_id=run.run_id,
                status=status,
                found_strict=state.found_strict,
                found_relaxed=state.found_relaxed,
                analyzed=state.analyzed,
                receipt=receipt,
            )
            await self._end(conn, run, status=status, end_reason=state.end_reason, summary=summary)
        log.info(
            "arv2.discovery_run_finished",
            run_id=str(run.run_id),
            status=status,
            end_reason=state.end_reason,
            shown=state.shown,
            target=run.target_count,
            cost_usd=str(state.cost_usd),
            candidate_failures=len(state.candidate_failures),
        )

    async def _end(
        self,
        conn: AsyncConnection,
        run: DiscoveryRunRow,
        *,
        status: str,
        end_reason: str,
        summary: Mapping[str, Any],
    ) -> None:
        """The one end block every ending runs (spec §4, §5): write why the run ended and its
        summary, then either hand the summary to the launching thread's wake turn — the run stays
        held until that turn finishes — or release the run's project lock now.

        A run with no launching thread (or a worker composed without a wake) releases at once. So
        does a run whose wake queued nothing or failed: a lock nobody will ever release would block
        every later discovery of the project. The wake runs in a savepoint so its failure cannot
        take the run's own ending down with it.
        """
        wake = self._wake
        threaded = run.launched_thread_id is not None and wake is not None
        await self._store.end_discovery_run(
            conn,
            run_id=run.run_id,
            status=status,
            end_reason=end_reason,
            summary=summary,
            release=not threaded,
        )
        if wake is None or not threaded:
            return
        wake_turn: UUID | None = None
        try:
            async with conn.begin_nested():
                wake_turn = await wake.queue(
                    conn, run, summary, summary_message(run.run_id, summary)
                )
        except Exception:  # noqa: BLE001 — the run still ends, and is released below
            log.exception("arv2.discovery_wake_failed", run_id=str(run.run_id))
        if wake_turn is None:
            await self._store.end_discovery_run(
                conn,
                run_id=run.run_id,
                status=status,
                end_reason=end_reason,
                summary=summary,
                release=True,
            )
        else:
            await self._store.record_wake_turn(conn, run_id=run.run_id, wake_turn_id=wake_turn)

    async def _suspend(self, run_id: UUID) -> None:
        """Park the run for requeue. A failure here is logged, never raised into the fleet."""
        try:
            async with self._connection() as conn:
                await self._store.suspend_discovery_run(conn, run_id=run_id)
        except Exception:  # noqa: BLE001 — a stopped task must still return a result
            log.exception("arv2.discovery_suspend_failed", run_id=str(run_id))

    async def _contain(
        self,
        run_id: UUID,
        *,
        code: str,
        message: str,
        summary: Mapping[str, Any] | None = None,
    ) -> None:
        """Land a failed run ``needs_review`` with a named reason, and end it. Never raises.

        Without a ``summary`` this is the ending of a run that failed before it had any state — a
        task whose ids disagree, a refused brief or ICP pin — so nothing was verified or spent,
        and the summary says so. (A failure after the rounds began is landed by ``_run`` with its
        real counters; only a failure of that landing itself comes here, with its summary.) The
        run still goes through :meth:`_end`: it wakes the launching thread and is released.
        """
        try:
            async with self._connection() as conn:
                run = await self._store.read_discovery_run(conn, run_id=run_id)
                await self._store.finish_discovery_run(
                    conn,
                    run_id=run_id,
                    status="needs_review",
                    found_strict=0,
                    found_relaxed=0,
                    analyzed=0,
                    receipt={"failure": code, "message": message[:1_000], "end_reason": "failed"},
                )
                if run is not None and run.released_at is None and run.wake_turn_id is None:
                    await self._end(
                        conn,
                        run,
                        status="needs_review",
                        end_reason="failed",
                        summary=summary if summary is not None else _failure_summary(run, code),
                    )
        except Exception:  # noqa: BLE001 — the log is the last report left
            log.exception("arv2.discovery_contain_failed", run_id=str(run_id))

    # -- the one path to a provider --------------------------------------------------------------

    async def _hop[T](self, state: _RunState, fn: Callable[[ProviderCaller], T]) -> T:
        """Run one synchronous provider call off the loop, then land its money trail.

        The drain is shielded because a cancelled drain would lose the raw bodies and ledger rows
        of a call that already happened — the one thing money truth cannot tolerate.

        Cancellation gets the same treatment, and needs more than a shield (ruling R8): a thread
        cannot be interrupted, so a cancelled ``to_thread`` returns to the loop while the call it
        carries is still on the wire and fills ``raw``/``ledger`` afterwards — the drain would
        land an empty trail for a call that was bought. So the call is shielded, and on
        cancellation it is awaited to completion BEFORE the drain runs and the cancellation is let
        through. A sibling gate cancelled because another gate failed therefore still pays its own
        bill onto the receipt.
        """
        raw, ledger = BufferedRawSink(), BufferedLedger()
        caller = ProviderCaller(
            transport=self._transport_factory(), raw_sink=raw, ledger=ledger, now=self._clock
        )
        call = asyncio.ensure_future(asyncio.to_thread(fn, caller))
        try:
            return await asyncio.shield(call)
        except asyncio.CancelledError:
            # Wait for the thread that cannot be interrupted, so its raw body and ledger row are
            # in the buffers the drain below lands, then let the cancellation through. (A second
            # cancellation during this wait is the one residual: the drain then lands what is
            # buffered so far.)
            await asyncio.shield(asyncio.gather(call, return_exceptions=True))
            raise
        finally:
            await asyncio.shield(self._drain(state, raw, ledger))

    async def _drain(self, state: _RunState, raw: BufferedRawSink, ledger: BufferedLedger) -> None:
        run = state.run
        async with self._connection() as conn:
            report = await drain_provider_calls(
                conn,
                raw=raw,
                ledger=ledger,
                artifacts=self._artifacts,
                stamp=LedgerStamp(
                    workspace_id=run.workspace_id,
                    project_id=run.project_id,
                    project_run_id=str(run.project_run_id),
                    job_id=run.run_id,
                ),
            )
        state.cost_usd += report.cost_usd

    # -- plumbing ----------------------------------------------------------------------------------

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[AsyncConnection]:
        """A pooled connection per caller. Since 2026-09-12 candidates verify concurrently, each in
        its own transaction; the engine hands every task its own connection, so nothing here is
        shared between them."""
        async with self._conn_factory() as conn:
            yield conn

    async def _workspace_accounts(
        self, conn: AsyncConnection, workspace_id: str
    ) -> dict[str, UUID]:
        """Every live account of the workspace by folded domain, read once per run. When two
        accounts share a domain the oldest is the one a found company joins."""
        rows = await conn.execute(_WORKSPACE_ACCOUNTS, {"workspace_id": workspace_id})
        accounts: dict[str, UUID] = {}
        for row in rows:
            folded = _fold(row[0])
            if folded and folded not in accounts:
                accounts[folded] = UUID(str(row[1]))
        return accounts

    async def _project_domains(self, conn: AsyncConnection, run: DiscoveryRunRow) -> set[str]:
        """The folded domains of this project's accounts, read once per run."""
        rows = await conn.execute(
            _PROJECT_DOMAINS, {"workspace_id": run.workspace_id, "project_id": run.project_id}
        )
        return {folded for row in rows if (folded := _fold(row[0]))}


def _fold(domain: object) -> str:
    raw = str(domain or "")
    return registrable_domain(raw) or raw.strip().lower()


def build_summary(state: _RunState, *, failure: str | None = None) -> dict[str, Any]:
    """What the Head of ABM is told when the run ends (spec §4 "The summary"), built by code.

    ``excluded_by`` lists each gate that excluded companies, most first, with its role and one
    example; ``criteria_rates`` are the last webset's (Exa reports 0–100); ``spend_usd`` is this
    run's ledger total as a string, like the receipt's.
    """
    roles = {gate.key: gate.role for gate in state.brief2.gates}
    summary: dict[str, Any] = {
        "asked": state.run.target_count,
        "added": state.shown,
        "excluded": sum(len(names) for names in state.excluded.values()),
        "unclear": state.unclear_count,
        "excluded_by": [
            {"gate": gate, "role": roles.get(gate), "count": len(names), "example": names[0]}
            for gate, names in sorted(state.excluded.items(), key=lambda kv: -len(kv[1]))
        ],
        "criteria_rates": [
            {"criterion": criterion, "rate": rate} for criterion, rate in state.criteria_rates
        ],
        "searches": len(state.searches),
        "end_reason": state.end_reason,
        "spend_usd": str(state.cost_usd),
    }
    if failure is not None:
        summary["failure"] = failure
    return summary


def _failure_summary(run: DiscoveryRunRow, failure: str) -> dict[str, Any]:
    """The summary of a run that failed before it had any state: nothing verified, nothing spent."""
    return {
        "asked": run.target_count,
        "added": 0,
        "excluded": 0,
        "unclear": 0,
        "excluded_by": [],
        "criteria_rates": [],
        "searches": 0,
        "end_reason": "failed",
        "spend_usd": "0",
        "failure": failure,
    }


def summary_message(run_id: UUID, summary: Mapping[str, Any]) -> str:
    """The wake turn's message (spec §6.3): the summary, as the Head of ABM reads it."""
    reason = str(summary["end_reason"])
    ended = reason.replace("_", " ")
    if reason == "round_cap":
        ended = f"round cap ({summary['searches']} searches)"
    elif reason == "failed" and summary.get("failure"):
        # Not in spec §6.3's list: a failed run names its failure, so the agent can say why.
        ended = f"failed ({summary['failure']})"
    lines = [
        f"Discovery finished (run {run_id}). Asked for {summary['asked']}, added "
        f"{summary['added']}, excluded {summary['excluded']}, unclear {summary['unclear']}.",
        f"Ended: {ended}.",
    ]
    if summary["excluded_by"]:
        lines.append(
            "Excluded by: "
            + "; ".join(
                f"{entry['gate']} ({entry['role']}) {entry['count']} — e.g. {entry['example']}"
                for entry in summary["excluded_by"]
            )
            + "."
        )
    rates = [entry for entry in summary["criteria_rates"] if entry["rate"] is not None]
    if rates:
        lines.append(
            "Criteria pass rates, last search: "
            + "; ".join(f'"{entry["criterion"]}" {round(float(entry["rate"]))}%' for entry in rates)
            + "."
        )
    lines.append(f"Spend: ${Decimal(str(summary['spend_usd'])):.2f}.")
    return "\n".join(lines)


def _item_from_hit(hit: ExaHit) -> WebsetItem:
    """A ``/search`` result in the verifier's shape. A search result carries none of the company
    facts a webset row does, so the account gets no employee count, revenue band or mark from it."""
    url = str(hit.url)
    return WebsetItem(
        item_id=f"search:{url}",
        search_id=None,
        url=url,
        name=hit.title or url,
        description=(hit.text or "")[:400],
        hq_city=None,
        hq_state=None,
        hq_country_code=None,
        employees=None,
        revenue_annual=None,
        funding_total=None,
        evaluations=(),
        raw={"url": url, "title": hit.title},
    )


def _snapshot_item_id(candidate: CandidateRow) -> str | None:
    """The Websets item id inside a recorded candidate's provider snapshot, if it kept one.

    The raw item is stored whole under ``item``, so a resumed attempt can tell which webset rows a
    previous attempt already paid for without a second column.
    """
    item = candidate.provider_snapshot.get("item")
    if not isinstance(item, Mapping):
        return None
    item_id = item.get("id")
    return item_id if isinstance(item_id, str) and item_id else None


def _replace_disposition(row: CandidateRow, value: Disposition) -> CandidateRow:
    return replace(row, disposition=value)


async def _abort(tasks: Iterable[asyncio.Task[Any]]) -> None:
    """Cancel every task that is still running and wait for all of them to finish.

    The waiting is the point (ruling R8): a cancelled hop still drains its own call, so returning
    before the siblings are done would let their money land after the run had landed, and would
    leave a second failure's exception unretrieved. Shared with Task 4's candidate pool.
    """
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _failure_code(error: BaseException) -> str:
    """The named reason a contained failure records.

    A typed lane refusal already *has* a machine-readable name (``project_icp_not_pinned``,
    ``icp_digest_mismatch``) and a human who has learned that word should read it on the run's
    receipt rather than a Python class name. Everything else records its class.
    """
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    return type(error).__name__


def _scope(payload: Mapping[str, Any]) -> tuple[UUID, str] | None:
    try:
        return UUID(str(payload["run_id"])), str(payload["workspace_id"])
    except (KeyError, ValueError):
        return None


# =================================================================================================
# composition
# =================================================================================================


@dataclass(frozen=True)
class _LiveClients:
    """The production instruments: one Exa key, two clients, one caller per hop."""

    settings: Settings
    exa_api_key: SecretStr

    def exa(self, caller: ProviderCaller) -> ExaClient:
        return ExaClient(caller, api_key=self.exa_api_key)

    def websets(self, caller: ProviderCaller) -> ExaWebsetsClient:
        return ExaWebsetsClient(
            caller,
            api_key=self.exa_api_key,
            usd_per_credit=self.settings.arv2_discovery_websets_usd_per_credit,
        )


def build_arv2_discovery_handler(
    settings: Settings,
    secrets: Secrets,
    *,
    storage: StorageBackend,
    artifacts: ArtifactSink,
    conn_factory: ConnFactory = transaction,
    wake: DiscoveryWake | None = None,
) -> Arv2DiscoveryWorkHandler | None:
    """Compose the lane on this worker, or refuse loudly and compose nothing.

    A worker missing the Exa credential gets a named warning and **no handler**: the enqueued runs
    then wait for a correctly-credentialed worker, which is the honest outcome. Composing a keyless
    handler would fail each run at its first provider call — after it had already claimed the row.

    ``wake`` queues the launching thread's turn when a run ends; without one every run releases
    its project lock as it ends.
    """
    if not settings.arv2_discovery_enabled:
        return None
    key = secrets.exa_api_key
    if key is None or not key.get_secret_value().strip():
        log.warning(
            "arv2.discovery_handler_not_composed",
            missing=["CLUE_EXA_API_KEY"],
            detail=(
                "CLUE_ARV2_DISCOVERY_ENABLED is on but this worker has no CLUE_EXA_API_KEY; "
                "discovery runs stay queued until a worker with the full configuration drains them"
            ),
        )
        return None
    return Arv2DiscoveryWorkHandler(
        settings=settings,
        conn_factory=conn_factory,
        storage=storage,
        artifacts=artifacts,
        clients=_LiveClients(settings=settings, exa_api_key=SecretStr(key.get_secret_value())),
        writer=LenientClaimWriter(lenient=settings.claim_write_lenient),
        wake=wake,
    )
