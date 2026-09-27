"""One ARV2 discovery run on the fleet: the long list, the verifier, the candidate accounts.

This is spec §2–§4 executed in order, once per ``arv2_discovery`` task:

1. **Claim the run** (``begin_discovery_run``). A run another worker is driving, or one that has
   already landed, is not this task's to run — the task completes without spending a cent.
2. **Read the program.** The document THIS RUN was pinned to — ``run.icp_artifact_key``, checked
   against ``run.icp_artifact_sha256`` — is re-read at the start of every attempt and compiled
   into the brief (§2: *the ICP document is the program*), so a resumed run asks exactly the
   questions the first attempt asked even if a human has since repinned the project onto a newer
   ICP. Reading the project's *current* pin instead would grade one run's candidates against two
   different documents; the digest that no longer matches refuses by name instead.
3. **The strict pass** — one webset with the full criteria, polled to ``idle`` under a wall clock,
   then read once. Skipped entirely when the human asked for a relaxed pass on a run that already
   bought its long list: a second webset would be a second bill for the same companies.
4. **The verifier, per candidate** — first the company's own website (Websets gave ``probook.com``
   for a company whose site is ``probook.ai``, and everything downstream keys on the verified
   domain), then one Answer call per hard gate, each graded by
   :func:`~clue_api.arv2.discovery_verifier.apply_guards`. The fit is ``passes / gates`` with an
   unclear counted as half, and it is written as an ``account.scoring.fit`` claim on a new
   ``candidate`` account.
5. **The relaxed pass**, only when the run came up short of the number the human asked for and the
   run allows it: a second search on the *same* webset, excluding the strict search's results, with
   the criterion the strict search's own success rates proved was starving it dropped.
6. **The receipt** — asked, found, analyzed, Exa's recall estimate, the guard counts, the money.
   A short list is information, never padded (§4).

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

**No spend on a company we already have, or already showed.** A verified domain that is already an
account of this workspace is ``duplicate_of_existing``; one an earlier run of this project showed
and the human did not tick is ``not_chosen_before`` (ruling 1′: unapproved is not rejected). Both
are recorded as candidates and cost exactly the one website answer that identified them — never a
gate.
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
from clue_api.arv2.discovery_brief import DiscoveryBrief, compile_brief
from clue_api.arv2.discovery_launch import read_icp_document
from clue_api.arv2.discovery_store import CandidateRow, DiscoveryRunRow, Disposition, Pass
from clue_api.arv2.discovery_verifier import (
    OUTPUT_SCHEMA,
    WEBSITE_SCHEMA,
    GateVerdict,
    apply_guards,
    disposition,
    fit_score,
    gate_question,
    system_prompt,
    website_question,
)
from clue_api.arv2.errors import Arv2Error, ProviderHalted
from clue_api.arv2.exa_client import ExaAnswerResult, ExaClient
from clue_api.arv2.exa_websets_client import (
    ExaWebsetsClient,
    WebsetItem,
    WebsetSearchView,
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
    "Arv2DiscoveryWorkHandler",
    "arv2_discovery_work_id",
    "build_arv2_discovery_handler",
    "revenue_band",
]

#: The failure a wall-clock overrun records. Named, because "the webset never went idle" and "the
#: provider refused to sell" are different problems with different fixes.
WEBSET_WALL_EXCEEDED = "webset_wall_exceeded"

#: The failure a halted provider records.
PROVIDER_HALTED = "provider_halted"

#: The failure a task whose work id disagrees with its payload records.
INVALID_TASK_PAYLOAD = "invalid_task_payload"

#: The failure a webset whose strict search cannot be named records.
WEBSET_SEARCH_AMBIGUOUS = "webset_search_ambiguous"

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

#: Every live account domain of one workspace: the always-on local dedupe (§2), read once per run.
_WORKSPACE_DOMAINS = text(
    """
    SELECT primary_domain FROM account_entity
    WHERE workspace_id = :workspace_id AND merged_into IS NULL AND primary_domain IS NOT NULL
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


class _WallExceeded(Arv2Error):
    """The webset did not reach ``idle`` inside the run's wall clock."""


class _SearchAmbiguous(Arv2Error):
    """The webset carries more than one search and nothing says which is the strict one.

    Only reachable on a run whose ``strict_search_id`` was never recorded (an attempt that died
    between ``create`` and ``record_webset``) and whose webset has since grown a second search.
    Guessing by array position is what this refusal exists to prevent: the wrong guess excludes
    the wrong search when widening, mislabels every candidate's pass, and drops a criterion using
    another search's success rates. A human relaunches; nothing is bought.
    """

    code = WEBSET_SEARCH_AMBIGUOUS


@dataclass
class _RunState:
    """What one attempt has learned so far — the numbers its receipt is made of."""

    run: DiscoveryRunRow
    brief: DiscoveryBrief
    today: date
    deadline: datetime
    #: Workspace accounts (the local dedupe set) and the domains this run has already looked at.
    existing: set[str]
    unapproved: frozenset[str]
    seen: set[str] = field(default_factory=set)
    #: The human who owns and created every account this run lands (founder ruling 2026-09-11:
    #: creator is owner) — the run's requester when that id is a real platform user, else
    #: ``None``. A deepagent-launched run records the fleet's service principal as its requester,
    #: which is nobody's owner and no FK target, so it is resolved once here rather than trusted.
    owner_user_id: str | None = None
    webset_id: str | None = None
    #: The webset's status as Exa last reported it. Anything but ``idle`` means Exa may still be
    #: finding — and charging for — companies, which is what :meth:`_stop_webset` is for.
    webset_status: str | None = None
    #: This run cancelled its webset because it stopped reading before Exa was done, and how many
    #: rows the read after the cancel put on the ledger that no earlier read had.
    webset_stopped: bool = False
    rows_priced_at_stop: int = 0
    strict_search_id: str | None = None
    #: Set once the widening search has been bought — the relaxed pass then READS it rather than
    #: buying a second one (which would exclude only the strict search and re-charge for the first
    #: widening's results).
    relaxed_search_id: str | None = None
    #: Every webset row this run has already been charged for. A webset is read again on every
    #: resume and again after a widening search, and each read returns every row, so without this
    #: the strict pass's rows are priced onto the ledger two or three times — on the exact number
    #: §8's exit gate divides by.
    priced_item_ids: set[str] = field(default_factory=set)
    strict_rates: tuple[tuple[str, float | None], ...] = ()
    asked: int | None = None
    recall_estimate: int | None = None
    analyzed: int = 0
    found_strict: int = 0
    found_relaxed: int = 0
    shown: int = 0
    duplicates: int = 0
    not_chosen_before: int = 0
    unresolvable: int = 0
    guards: dict[str, int] = field(default_factory=dict)
    #: One entry per company that was on the list and could not be finished, with the named reason.
    candidate_failures: list[dict[str, str]] = field(default_factory=list)
    criteria_relaxed: tuple[str, ...] | None = None
    cost_usd: Decimal = Decimal(0)
    #: The one cap on verification hops in flight (Task 3): candidates verify in a pool and a
    #: candidate's gates are asked together, all under this semaphore. Built in ``_compose``.
    hops: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    #: Item ids this attempt has handed to the pool — claimed when a task is taken, never when it
    #: finishes, so a re-listed item on the next tick is not verified twice.
    claimed: set[str] = field(default_factory=set)

    def count_guard(self, guard: str) -> None:
        self.guards[guard] = self.guards.get(guard, 0) + 1


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
    ) -> None:
        self._settings = settings
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
        """Claim, compile, discover, verify, land. Raises only into ``handle``'s containment."""
        async with self._connection() as conn:
            run = await self._store.begin_discovery_run(conn, run_id=run_id)
        if run is None:
            # An ordinary redelivery: another worker is driving this run, or it already landed.
            log.info("arv2.discovery_not_claimable", run_id=str(run_id), workspace=workspace_id)
            return "completed"

        state = await self._compose(run)
        status, failure = "completed", None
        try:
            if run.webset_id:
                # A webset this run already paid for is never bought twice — not on a plain
                # resume (a lost lease, a stop, a worker restart), and not on a relaxed request.
                await self._resume_webset(state, verify=not run.relaxed_requested)
            else:
                await self._strict_pass(state)
            await self._relaxed_pass(state)
        except _WallExceeded as exceeded:
            status, failure = "needs_review", (WEBSET_WALL_EXCEEDED, str(exceeded))
        except ProviderHalted as halted:
            log.warning(
                "arv2.discovery_provider_halted",
                run_id=str(run_id),
                provider=halted.provider,
                reason=halted.reason_code,
            )
            status, failure = "needs_review", (PROVIDER_HALTED, str(halted))
        except Exception:
            # ``handle`` contains this and lands the run; the webset must stop first.
            await self._stop_webset(state)
            raise
        if failure is not None:
            await self._stop_webset(state)
        if status == "completed" and state.candidate_failures:
            # Every other candidate landed and every counter is kept; the run still asks for a
            # human, because a company that was on the list and has no verdict is not a finished
            # run — it is a finished run minus a company, and the receipt names which.
            status = "needs_review"
        await self._land(state, status=status, failure=failure)
        return status

    async def _compose(self, run: DiscoveryRunRow) -> _RunState:
        """Re-read the program and everything this attempt must not spend twice on."""
        now = self._clock()
        async with self._connection() as conn:
            # The RUN's pinned bytes, not the project's current pin: a project repinned while this
            # run was queued or suspended must not silently change the gates half-way through it.
            icp = await read_icp_document(
                conn,
                self._storage,
                workspace_id=run.workspace_id,
                artifact_key=run.icp_artifact_key,
                artifact_sha256=run.icp_artifact_sha256,
            )
            brief = compile_brief(icp.front, icp.body, criteria_gate_keys=run.criteria_gate_keys)
            existing = await self._workspace_domains(conn, run.workspace_id)
            unapproved = await self._store.unapproved_domains(
                conn,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                before_run_id=run.run_id,
            )
            already = await self._store.list_candidates(conn, run_id=run.run_id)
            owner_user_id = await self._owner_user(conn, run.requested_by_user_id)
        state = _RunState(
            run=run,
            brief=brief,
            today=now.date(),
            deadline=now + timedelta(seconds=self._settings.arv2_discovery_wall_s),
            existing=existing,
            unapproved=frozenset(unapproved),
            owner_user_id=owner_user_id,
            webset_id=run.webset_id,
            strict_search_id=run.strict_search_id,
            relaxed_search_id=run.relaxed_search_id,
            asked=run.asked,
            recall_estimate=run.recall_estimate,
            found_strict=run.found_strict or 0,
            found_relaxed=run.found_relaxed or 0,
            hops=asyncio.Semaphore(self._settings.arv2_discovery_verify_concurrency),
        )
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
        # Every row an earlier attempt read was priced then; the raw Websets item is kept whole on
        # the candidate's snapshot, so its id is recoverable and this attempt does not buy it again.
        for candidate in already:
            item_id = _snapshot_item_id(candidate)
            if item_id:
                state.priced_item_ids.add(item_id)
        return state

    # -- step one: the long list ---------------------------------------------------------------

    async def _strict_pass(self, state: _RunState) -> None:
        """Buy one webset with the full criteria, wait for it, and verify everything it found."""
        run = state.run
        title = f"ARV2 discovery {run.project_id} {run.icp_key}@{run.icp_version}"
        view = await self._hop(
            state,
            lambda caller: self._clients.websets(caller).create(
                query=state.brief.query,
                count=run.strict_count,
                criteria=state.brief.criteria,
                external_id=f"arv2-discovery:{run.run_id}",
                title=title,
            ),
        )
        state.webset_id = view.webset_id
        state.asked = run.strict_count
        self._read_searches(state, view)
        async with self._connection() as conn:
            await self._store.record_webset(
                conn,
                run_id=run.run_id,
                webset_id=view.webset_id,
                asked=run.strict_count,
                recall_estimate=state.recall_estimate,
                # The create response names the one search this webset has, so the strict id is
                # durable from the first write — a resumed attempt never has to guess it.
                strict_search_id=state.strict_search_id,
            )
        await self._watch_and_verify(state, view.webset_id, pass_="strict")

    async def _resume_webset(self, state: _RunState, *, verify: bool) -> None:
        """Pick a recorded webset back up instead of buying a second one.

        Two callers, one rule — ``webset_id`` set means *never create*:

        * ``verify=False`` is the human's relaxed request on a run that already finished. Only the
          free read: the webset's searches are what the relaxed pass excludes and what its criteria
          choice is made from, and every candidate the strict pass produced is already recorded.
        * ``verify=True`` is a plain resume — the attempt that bought this webset was suspended,
          stopped or lost its lease part-way through verifying it. The list is polled and read
          again and every company this run has not already *finished* verifying is verified now.
          A candidate left ``pending`` is re-verified on purpose: its verdicts never landed, so
          skipping it would strand a company with no verdict and no account (see :meth:`_compose`).
        """
        webset_id = str(state.webset_id)
        if not verify:
            view = await self._hop(
                state, lambda caller: self._clients.websets(caller).get(webset_id)
            )
            self._read_searches(state, view)
            log.info(
                "arv2.discovery_relaxed_resume",
                run_id=str(state.run.run_id),
                webset_id=webset_id,
                already=state.shown,
            )
            return
        log.info(
            "arv2.discovery_resume",
            run_id=str(state.run.run_id),
            webset_id=webset_id,
            already=len(state.seen),
        )
        await self._watch_and_verify(state, webset_id, pass_="resume")

    @staticmethod
    def _is_strict_item(state: _RunState, item: WebsetItem) -> bool:
        """Did the strict search find this item? An item Exa did not attribute counts as strict —
        the strict search is the only one a run is guaranteed to have made."""
        if item.search_id is None or state.strict_search_id is None:
            return True
        return item.search_id == state.strict_search_id

    async def _read_items(self, state: _RunState, webset_id: str) -> tuple[WebsetItem, ...]:
        """The billed read of the long list. ``all_green`` is Exa's *bill*, never a verdict.

        A webset is read again on every resume and again after the widening search, and each read
        returns the WHOLE webset — so the rows this run has already been charged for are named to
        the client and priced at zero. The bill for one row is paid once per run, which is what
        makes the receipt's ``cost_usd`` (and §8's cost-per-approved-account) mean what it says.
        """
        priced = frozenset(state.priced_item_ids)
        result = await self._hop(
            state,
            lambda caller: self._clients.websets(caller).items(webset_id, priced_item_ids=priced),
        )
        state.priced_item_ids.update(result.priced_item_ids)
        log.info(
            "arv2.discovery_items",
            run_id=str(state.run.run_id),
            items=len(result.items),
            credits_est=result.credits_est,
            newly_priced=len(result.priced_item_ids),
        )
        return result.items

    async def _watch_and_verify(
        self, state: _RunState, webset_id: str, *, pass_: Literal["strict", "relaxed", "resume"]
    ) -> None:
        """Poll the webset to ``idle`` and verify every new item on every tick (spec §2).

        Each tick lists the webset (a row is priced once per run, so re-listing costs nothing),
        hands every unclaimed item to a task, records the counters, and sleeps. On ``idle`` one
        last list catches stragglers, and the pool is drained before returning. ``pass_`` decides
        the candidate's recorded pass: a resume labels each item by the search that found it.

        A company is claimed **at dispatch**, by item id and by registrable domain: two rows of one
        company — the same row re-listed on the next tick, or the strict row the widened webset
        returns again — must never be two verifications, which would be two bills and two accounts.

        Containment is per task (``_verify_contained``); ``ProviderHalted`` and the wall clock
        are not contained — the first of either cancels the pool and re-raises, so ``_run`` lands
        the run ``needs_review`` exactly as it does today.
        """
        tasks: set[asyncio.Task[None]] = set()

        def _label(item: WebsetItem) -> Pass:
            if pass_ == "resume":
                return "strict" if self._is_strict_item(state, item) else "relaxed"
            return pass_

        async def _tick(final: bool) -> None:
            items = await self._read_items(state, webset_id)
            self._count_found(state, items)
            for item in items:
                domain = registrable_domain(item.url) or ""
                if item.item_id in state.claimed:
                    continue
                if domain and domain in state.seen:
                    continue
                state.claimed.add(item.item_id)
                if domain:
                    state.seen.add(domain)
                tasks.add(
                    asyncio.create_task(self._verify_contained(state, item, pass_=_label(item)))
                )
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
                if self._clock() > state.deadline:
                    raise _WallExceeded(
                        f"webset {webset_id} did not reach idle within "
                        f"{self._settings.arv2_discovery_wall_s}s"
                    )
                view = await self._hop(
                    state, lambda caller: self._clients.websets(caller).get(webset_id)
                )
                self._read_searches(state, view)
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

    def _count_found(self, state: _RunState, items: Sequence[WebsetItem]) -> None:
        """What the list HOLDS, not what this attempt happened to verify — and monotonic, so a read
        that lists fewer rows than the one before it cannot walk a counter backwards."""
        strict = [item for item in items if self._is_strict_item(state, item)]
        state.found_strict = max(state.found_strict, len(strict))
        state.found_relaxed = max(state.found_relaxed, len(items) - len(strict))

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
            self._count_found(state, items)
        except Exception:  # noqa: BLE001 — as above
            log.exception("arv2.discovery_webset_final_read_failed", run_id=str(state.run.run_id))
        log.info(
            "arv2.discovery_webset_stopped",
            run_id=str(state.run.run_id),
            webset_id=webset_id,
            cancelled=state.webset_stopped,
            rows_priced_at_stop=state.rows_priced_at_stop,
        )

    def _read_searches(self, state: _RunState, view: WebsetView) -> None:
        """Keep the webset's status, and the strict search's id, rates and counters, from the view
        that last reported them."""
        state.webset_status = view.status
        if not view.searches:
            return
        strict = _strict_search(view, state.strict_search_id)
        if strict is not None:
            state.strict_search_id = strict.search_id
            if strict.criteria_success_rates:
                state.strict_rates = strict.criteria_success_rates
            if strict.recall_estimate is not None:
                state.recall_estimate = strict.recall_estimate
        state.analyzed = sum(search.analyzed or 0 for search in view.searches)

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
        fit = fit_score(verdicts)
        outcome = disposition(verdicts)
        logo = await self._resolve_logo(state, item=item, verified=verified)
        async with self._connection() as conn:
            account_id = await insert_account_entity(
                conn,
                canonical_name=item.name,
                primary_domain=verified,
                workspace_id=run.workspace_id,
                status=AccountStatus.CANDIDATE,
                # Founder ruling 2026-09-11: the creator is the owner by default — the human who
                # launched the discovery made these accounts exist and owns them until an
                # ownership mechanism says otherwise. Only a real platform user is stamped: a run
                # the deepagent launched on the fleet records the service principal as its
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
        state.existing.add(verified)
        if outcome in _SHOWN:
            state.shown += 1
        log.info(
            "arv2.discovery_candidate_verified",
            run_id=str(run.run_id),
            domain=verified,
            disposition=outcome,
            fit=fit,
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
        """What this company is *before* a gate is asked, or ``None`` when it is worth verifying."""
        if verified in state.existing:
            state.duplicates += 1
            return "duplicate_of_existing"
        if verified in state.unapproved:
            state.not_chosen_before += 1
            return "not_chosen_before"
        return None

    async def _verify_gates(
        self, state: _RunState, company_name: str, verified: str
    ) -> tuple[GateVerdict, ...]:
        """Every hard gate the document states — asked together, then guarded in document order.

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
                citations=result.citations,
                company_domain=verified,
                company_name=company_name,
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
        fit: float,
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
        company's own site and carries no span rather than borrowing an unrelated one.
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

    # -- step three: the relaxed pass ----------------------------------------------------------

    async def _relaxed_pass(self, state: _RunState) -> None:
        """A second search on the same webset when the run is short — §4's honest widening.

        The dropped criterion is the one the strict search's own success rates say was starving it,
        never a guess. Every company it returns is verified on **all** the gates, exactly like a
        strict one, so it lands with an honestly weaker score rather than a hidden one.

        **The widening is bought once.** ``relaxed_search_id`` set on the run row means this run
        already paid for its second search, so a redelivered task (a lost lease, a repeated relaxed
        request) polls and reads it instead of calling ``add_search`` again — a second call would
        exclude only the *strict* search, so Exa would re-find and re-charge for everything the
        first widening returned, once per retry.
        """
        run = state.run
        if state.shown >= run.target_count:
            return
        if not (run.relaxed_enabled or run.relaxed_requested):
            log.info(
                "arv2.discovery_relaxed_skipped",
                run_id=str(run.run_id),
                shown=state.shown,
                target=run.target_count,
            )
            return
        if state.webset_id is None:
            log.info("arv2.discovery_relaxed_unavailable", run_id=str(run.run_id))
            return
        webset_id = state.webset_id
        if state.relaxed_search_id is None:
            if state.strict_search_id is None:
                log.info("arv2.discovery_relaxed_unavailable", run_id=str(run.run_id))
                return
            await self._buy_relaxed_search(state, webset_id, state.strict_search_id)
        else:
            log.info(
                "arv2.discovery_relaxed_already_bought",
                run_id=str(run.run_id),
                webset_id=webset_id,
                relaxed_search_id=state.relaxed_search_id,
            )
        await self._watch_and_verify(state, webset_id, pass_="relaxed")

    async def _buy_relaxed_search(
        self, state: _RunState, webset_id: str, strict_search_id: str
    ) -> None:
        """Add the widening search to this webset and record its id before reading a single row."""
        run = state.run
        criteria = relaxed_criteria(state.brief.criteria, state.strict_rates)
        state.criteria_relaxed = criteria
        shortfall = run.target_count - state.shown
        view = await self._hop(
            state,
            lambda caller: self._clients.websets(caller).add_search(
                webset_id,
                query=state.brief.query,
                count=shortfall,
                criteria=criteria,
                exclude_search_ids=[strict_search_id],
            ),
        )
        # The webset is searching again, so it is no longer ``idle`` until a poll says it is.
        state.webset_status = view.status
        relaxed_search_id = _relaxed_search_id(view, strict_search_id)
        if relaxed_search_id is None:
            # The purchase happened; only its id is missing, so the read below still runs. What is
            # lost is the "bought already" fact, which is stated rather than hidden.
            log.warning(
                "arv2.discovery_relaxed_search_unnamed",
                run_id=str(run.run_id),
                webset_id=webset_id,
            )
            return
        state.relaxed_search_id = relaxed_search_id
        async with self._connection() as conn:
            await self._store.record_relaxed_search(
                conn, run_id=run.run_id, relaxed_search_id=relaxed_search_id
            )

    # -- landing ---------------------------------------------------------------------------------

    async def _land(
        self, state: _RunState, *, status: str, failure: tuple[str, str] | None
    ) -> None:
        """Write the run's terminal row: the §4 counters and the receipt behind them."""
        receipt: dict[str, JsonValue] = {
            "asked": state.asked,
            "recall_estimate": state.recall_estimate,
            "shown": state.shown,
            "target_count": state.run.target_count,
            "criteria": list(state.brief.criteria),
            # ``criteria_relaxed`` is what THIS attempt sent, so it is null on an attempt that
            # found the widening already bought and only read it. ``relaxed_search_id`` is what
            # says a widening happened at all, so the pair is never silent about one.
            "criteria_relaxed": (
                list(state.criteria_relaxed) if state.criteria_relaxed is not None else None
            ),
            "relaxed_search_id": state.relaxed_search_id,
            "guards": dict(state.guards),
            "cost_usd": str(state.cost_usd),
            # States the assumption behind the number above: a webset row is priced once per run,
            # not once per read, so a resumed or widened run does not over-report its own spend.
            "credits_priced_once": True,
            # The run ended before its webset did, so it cancelled it (see ``_stop_webset``), and
            # this many rows reached the ledger only through the read after the cancel.
            "webset_stopped": state.webset_stopped,
            "rows_priced_at_stop": state.rows_priced_at_stop,
            "duplicates": state.duplicates,
            "not_chosen_before": state.not_chosen_before,
            "unresolvable_domain": state.unresolvable,
            "candidate_failures": [dict(failure) for failure in state.candidate_failures],
        }
        if failure is not None:
            receipt["failure"], receipt["message"] = failure[0], failure[1][:1_000]
        async with self._connection() as conn:
            await self._store.finish_discovery_run(
                conn,
                run_id=state.run.run_id,
                status=status,
                found_strict=state.found_strict,
                found_relaxed=state.found_relaxed,
                analyzed=state.analyzed,
                receipt=receipt,
            )
        log.info(
            "arv2.discovery_run_finished",
            run_id=str(state.run.run_id),
            status=status,
            shown=state.shown,
            target=state.run.target_count,
            cost_usd=str(state.cost_usd),
            candidate_failures=len(state.candidate_failures),
        )

    async def _suspend(self, run_id: UUID) -> None:
        """Park the run for requeue. A failure here is logged, never raised into the fleet."""
        try:
            async with self._connection() as conn:
                await self._store.suspend_discovery_run(conn, run_id=run_id)
        except Exception:  # noqa: BLE001 — a stopped task must still return a result
            log.exception("arv2.discovery_suspend_failed", run_id=str(run_id))

    async def _contain(self, run_id: UUID, *, code: str, message: str) -> None:
        """Land a failed run ``needs_review`` with a named reason. Never raises."""
        try:
            async with self._connection() as conn:
                await self._store.finish_discovery_run(
                    conn,
                    run_id=run_id,
                    status="needs_review",
                    found_strict=0,
                    found_relaxed=0,
                    analyzed=0,
                    receipt={"failure": code, "message": message[:1_000]},
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

    async def _workspace_domains(self, conn: AsyncConnection, workspace_id: str) -> set[str]:
        """Every live account domain of the workspace — the local dedupe set, read once per run."""
        rows = await conn.execute(_WORKSPACE_DOMAINS, {"workspace_id": workspace_id})
        domains: set[str] = set()
        for row in rows:
            raw = str(row[0] or "")
            folded = registrable_domain(raw) or raw.strip().lower()
            if folded:
                domains.add(folded)
        return domains


def relaxed_criteria(
    criteria: Sequence[str], rates: Sequence[tuple[str, float | None]]
) -> tuple[str, ...]:
    """The criteria minus the one the strict search satisfied least often.

    A criterion Exa reported no rate for counts as the lowest (it is the one we know least about,
    and a criterion nobody satisfied often reports nothing); ties drop the *last* one, so the
    dropped criterion is deterministic rather than dependent on dict ordering.
    """
    if not criteria:
        return ()
    lookup = dict(rates)
    worst_index, worst = 0, None
    for index, criterion in enumerate(criteria):
        rate = lookup.get(criterion)
        score = float("-inf") if rate is None else float(rate)
        if worst is None or score <= worst:
            worst, worst_index = score, index
    return tuple(criterion for index, criterion in enumerate(criteria) if index != worst_index)


def _strict_search(view: WebsetView, known: str | None) -> WebsetSearchView | None:
    """The run's strict search, looked up by id — never by array position once the id is known.

    The id is durable from the moment the webset was created (``record_webset``), so a view that
    lists the relaxed search first cannot repoint what the exclusion excludes, what
    ``_is_strict_item`` labels, or whose success rates choose the dropped criterion.

    With no known id, one search is unambiguous — it is the strict one, because it is the only one
    a run is guaranteed to have made. Two are not, and the guess is refused
    (:class:`_SearchAmbiguous`) rather than made.
    """
    if known is not None:
        for search in view.searches:
            if search.search_id == known:
                return search
        return None
    if len(view.searches) > 1:
        raise _SearchAmbiguous(
            f"webset {view.webset_id} carries {len(view.searches)} searches and this run recorded "
            "no strict search id; which search is the strict one cannot be guessed"
        )
    return view.searches[0]


def _relaxed_search_id(view: WebsetView, strict_search_id: str) -> str | None:
    """The id of the search ``add_search`` just created: the one that is not the strict one.

    ``POST /websets/{id}/searches`` answers with the bare search it made, but a re-read of the
    whole webset answers with every search, and both shapes arrive here as ``view.searches`` — so
    the relaxed search is identified by *not being* the strict one rather than by position.
    """
    for search in view.searches:
        if search.search_id and search.search_id != strict_search_id:
            return search.search_id
    return None


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
) -> Arv2DiscoveryWorkHandler | None:
    """Compose the lane on this worker, or refuse loudly and compose nothing.

    A worker missing the Exa credential gets a named warning and **no handler**: the enqueued runs
    then wait for a correctly-credentialed worker, which is the honest outcome. Composing a keyless
    handler would fail each run at its first provider call — after it had already claimed the row.
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
    )
