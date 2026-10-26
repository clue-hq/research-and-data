"""The onboarding run on the fleet (ARV2-ONBOARDING-PLAN.md §2–§4; O3).

One ``onboarding_run`` task = one run: fast recon (overview ∥ lineup ∥ reviews), catalog sync, the
synthesis turns (through a seam O4 supplies) — one ICP turn, then one persona turn per ICP it
registered — and the background per-product fan-out, personas and products sharing the one
``onboarding_max_parallel_runs`` cap. A task of kind ``personas`` is the narrow sibling of that
walk: one persona turn for one already-registered ICP document, and nothing else (see
:meth:`OnboardingRunWorkHandler._personas_only`).

Every provider call is R1's synchronous ``ProviderCaller`` run in ``asyncio.to_thread`` with ONE
caller per step, so a blocking HTTP poll loop never owns the event loop. Nothing is written to
disk: the step's sinks buffer its raw bodies and ledger rows, and the driver drains them after
the step onto the artifact store and ``provider_call_ledger``, stamped with the workspace and
this run's id as the job (lane 3 slice 1b, D1).

The failure law: a provider failure, timeout or empty answer is a **step outcome**, never an
exception — the step lands ``failed``/``empty`` with its reason, its document is closed without a
body, and the run keeps going. ``handle`` contains everything else, because the fleet plane knows
nothing about these rows: an exception that escaped would fail the task and leave the run row
stranded on ``running`` forever.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_api.arv2 import onboarding_store as default_store
from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.customer_domains import DomainCheck, check_domains
from clue_api.arv2.exa_client import (
    ExaAgentRun,
    ExaClient,
    ExaDeepResult,
    product_catalog_output_schema,
)
from clue_api.arv2.onboarding_documents import (
    CustomerRow,
    KnowledgeDocument,
    company_overview_document,
    crm_customer_rows,
    customer_reviews_document,
    existing_customers_document,
    product_catalog_document,
    product_research_document,
    render_markdown,
    slugify,
)
from clue_api.arv2.onboarding_lineage import REMOVED_BY_PERSON, CatalogProduct, ProductLink
from clue_api.arv2.onboarding_lineage import synchronize_catalog as default_synchronize
from clue_api.arv2.onboarding_reconcile import CatalogReconciler
from clue_api.arv2.onboarding_requests import (
    COMPANY_OVERVIEW_SYSTEM_PROMPT,
    CUSTOMER_REVIEWS_SYSTEM_PROMPT,
    EXISTING_CUSTOMERS_SYSTEM_PROMPT,
    PRODUCT_RESEARCH_SYSTEM_PROMPT,
    company_overview_output_schema,
    company_overview_query,
    customer_reviews_output_schema,
    customer_reviews_query,
    existing_customers_output_schema,
    existing_customers_query,
    product_research_output_schema,
    product_research_query,
)
from clue_api.arv2.provider_ledger import (
    BufferedLedger,
    BufferedRawSink,
    DrainReport,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.sinks import LedgerSink, RawSink
from clue_api.arv2.transport import HttpxTransport
from clue_config import Secrets, Settings
from clue_db import ConnFactory
from clue_fleet import FleetTaskKind
from clue_fleet.lease import WorkId
from clue_fleet.work_worker import WorkContext, WorkResult
from clue_obs import get_logger
from clue_spine import list_products

log = get_logger("clue_api.arv2.onboarding_driver")

__all__ = [
    "ONBOARDING_DEDUP_PREFIX",
    "SYNTHESIS_TURN_HARD_TIMEOUT_S",
    "ArtifactSink",
    "ClientEntityBinder",
    "CurrentDocumentReader",
    "DrainProviderCalls",
    "ExaAgentSurface",
    "ExaClientFactory",
    "IcpRef",
    "IcpSynthesisOutcome",
    "OnboardingRunWorkHandler",
    "SynthesisLauncher",
    "SynthesisOutcome",
    "build_onboarding_exa_client_factory",
    "build_onboarding_provider_caller",
    "onboarding_work_id",
]

#: What an enqueuer puts in front of the run id so an onboarding task's dedup key can never
#: collide with another kind's.
ONBOARDING_DEDUP_PREFIX = "onboarding-run:"

#: The one prompt that is the driver's own rather than a request template's: the lineup is two
#: passes of the SAME question (own domain, then the open web), so the instruction lives with the
#: step that runs both.
#:
#: The two page sentences (added 2026-09-09, validated in the Exa playground 2026-09-08) are what
#: the catalog identity ladder runs on. ``official_url`` is the model stage's evidence, so it has
#: to be the page the offering is actually presented on — and a homepage or listing URL repeated
#: across every entry would read as "these are all one offering", which is why omitting it is
#: named as the better answer. The name sentence asks for the page's own spelling because the
#: ladder's second rung matches spellings; a model paraphrase of a name is a near-miss that mints
#: a duplicate row. "A page may present several offerings" is deliberate: a shared page is
#: evidence, never a rule that two offerings on one page must be one product.
LINEUP_SYSTEM_PROMPT = (
    "Prefer pages on the company's own domain; list every distinct product page; keep "
    "integrations and partner programs separate from standalone products; never invent an "
    "offering; when unsure of a field, omit it. For each offering, give official_url as the page "
    "on the company's own domain where that offering is presented (a page may present several "
    "offerings), and give name exactly as that page writes it for the offering, keeping the "
    "page's own spelling, spacing and capitalisation. If an offering has no page of its own on "
    "the company's domain, omit official_url rather than citing the homepage or a listing page."
)

#: The re-run hint. The lineup is asked the same question on every run, so on run two it re-derives
#: names it already named — four live runs on one workspace spelled the same offerings differently
#: enough to grow the product rows from 19 to 28. Naming what is on file lets the model reuse a
#: spelling instead of inventing a near-miss. It rides the QUERY, never the system prompt or the
#: schema: the catalog contract fixes those.
_KNOWN_PRODUCTS_HINT = (
    "Known products already on file for this company (reuse these exact names when an offering is "
    "the same product; add only genuinely distinct offerings): "
)


async def _default_known_products(conn: AsyncConnection, brand_id: str) -> Sequence[str]:
    return sorted(product.name for product in await list_products(conn, brand_id))


#: The reason an ``empty`` step records when nothing failed and nothing was found. ``empty`` may
#: not carry a ``failure_code`` (the O1 CHECK is biconditional), so this rides ``failure_message``.
_NO_PRODUCTS = "no products established"
_NO_SYNTHESIS = "synthesis agent not composed (O4)"

#: Every ``failed`` step MUST name a code (the same CHECK, read the other way), so a launcher that
#: refused without one still lands a legal row.
_UNSPECIFIED = "unspecified"

#: The driver's own containment for a synthesis turn that never returns. A pre-existing execution
#: substrate defect — ``RecipeExecutor.execute`` spins forever when a governed tool call under the
#: recipe gate is refused — can hang a launcher call, and a hung call would strand the run on
#: ``running`` forever, which is exactly what the failure law exists to prevent. This is NOT an
#: agent cap: the profile has its own 1200 s turn timeout, and this sits well above it so a turn
#: that is merely slow is never cut short. Every ``launch_icps``/``launch_persona`` call is wrapped
#: in it; a trip lands that step ``failed`` with :data:`_TURN_HUNG` and the run keeps going.
SYNTHESIS_TURN_HARD_TIMEOUT_S = 1800.0

#: The code a timed-out turn lands. Distinct from any launcher-supplied code: it says the turn
#: never answered, not that it answered badly.
_TURN_HUNG = "turn_hung"


def onboarding_work_id(run_id: UUID) -> WorkId:
    """The run id IS the work id: one task per run, and the identity is checked on arrival."""
    return WorkId(run_id)


class ExaAgentSurface(Protocol):
    """The two Exa operations the onboarding lane uses, as the offline tests double them."""

    def agent_run(
        self,
        *,
        query: str,
        output_schema: Mapping[str, object],
        effort: str,
        system_prompt: str | None = None,
        label: str = "exa-agent",
        poll_interval_s: float = 4.0,
        timeout_s: float = 900.0,
    ) -> ExaAgentRun: ...

    def deep_reasoning(
        self,
        *,
        system_prompt: str,
        query: str,
        output_schema: Mapping[str, object],
        num_results: int = 20,
        additional_queries: Sequence[str] | None = None,
        include_domains: Sequence[str] | None = None,
        text_max_chars: int = 10000,
        highlights_query: str | None = None,
        highlights_max_chars: int = 2000,
        label: str = "exa-deep",
        timeout_s: float = 1200.0,
    ) -> ExaDeepResult: ...


class ExaClientFactory(Protocol):
    """One client per step, because one :class:`ProviderCaller` per step is R1's rule: a halt
    latched by one step's provider must not silently stop another step's calls. The step's sinks
    are the driver's (slice 1b): it buffers the step's raw bodies and ledger rows and drains them
    onto the artifact store and ``provider_call_ledger`` after the step's calls."""

    def __call__(
        self, *, run_id: UUID, step_label: str, raw: RawSink, ledger: LedgerSink
    ) -> ExaAgentSurface: ...


#: The drain the driver runs after each provider step — injectable so the offline tests record
#: every drain without a database, the way the store and the synchronizer are injected.
DrainProviderCalls = Callable[..., Awaitable[DrainReport]]


class CatalogRegenerator(Protocol):
    """Rebuilds ``product/catalog.md`` from the brand's product list (``product_management``)."""

    async def __call__(
        self, conn: AsyncConnection, *, workspace_id: str, brand_id: str
    ) -> object: ...


class CurrentDocumentReader(Protocol):
    """The body of the brand's current servable version of ``path``, or ``None`` when it has none.

    The customers step reads ``proof/customers.md`` through this to keep its CRM rows (R-4.5)."""

    async def __call__(
        self, conn: AsyncConnection, *, workspace_id: str, brand_id: str, path: str
    ) -> str | None: ...


class ArtifactSink(Protocol):
    async def persist_body(
        self, *, workspace_id: str, data: bytes, media_type: str
    ) -> ArtifactRef: ...


class ClientEntityBinder(Protocol):
    """Binds the workspace's client entity for the company being onboarded. Optional on purpose:
    the run's documents are brand-scoped and do not need one, so a lane composed without a binder
    still produces every artifact."""

    async def ensure(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        brand_id: str,
        company_domain: str,
        run_id: UUID,
    ) -> UUID | None: ...


@dataclass(frozen=True)
class SynthesisOutcome:
    """What one synthesis turn settled its step with. ``failure_code`` may be ``None`` even on
    ``failed`` — the driver substitutes :data:`_UNSPECIFIED` rather than write an illegal row.

    ``cost_usd`` is that ONE turn's cost. Each step lands its own; the store's ``finish_run`` sums
    the steps, so the driver never adds two turns together.
    """

    status: Literal["completed", "empty", "failed"]
    failure_code: str | None
    failure_message: str | None
    cost_usd: Decimal


@dataclass(frozen=True)
class IcpRef:
    """One ICP profile the ICP turn registered — the driver's whole view of it.

    Deliberately the driver's own type rather than O4's ``RegisteredIcp``: the lane may not import
    the synthesis wiring (it composes the agent substrate), so the composition root copies the
    fields across the seam in both directions.
    """

    document_id: UUID
    icp_key: str
    version: int
    path: str
    #: The ICP's scope: ``None`` for the brand's own profile, a project id for a project-local
    #: variant. The persona written for it is written in the same scope, so this rides the seam
    #: (and, for a personas run, the fleet payload) rather than being re-derived downstream.
    project_id: str | None = None


@dataclass(frozen=True)
class IcpSynthesisOutcome:
    """The ICP turn's outcome: a step outcome plus the profiles the persona turns fan out over."""

    status: Literal["completed", "empty", "failed"]
    failure_code: str | None
    failure_message: str | None
    cost_usd: Decimal
    icps: tuple[IcpRef, ...]


class SynthesisLauncher(Protocol):
    async def launch_icps(
        self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID
    ) -> IcpSynthesisOutcome: ...

    async def launch_persona(
        self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID, icp: IcpRef
    ) -> SynthesisOutcome: ...


def build_onboarding_provider_caller(*, raw: RawSink, ledger: LedgerSink) -> ProviderCaller:
    """One caller for one step, over the step's own sinks. Since slice 1b nothing is written to
    disk: the sinks buffer, and the driver drains them onto the artifact store and the ledger."""
    return ProviderCaller(
        transport=HttpxTransport(), raw_sink=raw, ledger=ledger, now=lambda: datetime.now(UTC)
    )


def build_customer_domain_caller(*, raw: RawSink, ledger: LedgerSink) -> ProviderCaller:
    """The customers step's public-web caller: the DNS-pinned transport media resolution uses, so a
    customer domain can never point the worker at a private address."""
    from clue_api.arv2.media_resolution import PublicMediaTransport

    return ProviderCaller(
        transport=PublicMediaTransport(),
        raw_sink=raw,
        ledger=ledger,
        now=lambda: datetime.now(UTC),
    )


def build_onboarding_exa_client_factory(secrets: Secrets) -> ExaClientFactory:
    """The production factory. A blank key is unset (``.env.example`` ships the empty line), so it
    fails here at composition rather than as a provider 401 in the middle of a run."""
    key = secrets.exa_api_key
    if key is None or not key.get_secret_value().strip():
        raise ValueError("CLUE_EXA_API_KEY is required for the onboarding lane")
    api_key = SecretStr(key.get_secret_value())

    def factory(
        *, run_id: UUID, step_label: str, raw: RawSink, ledger: LedgerSink
    ) -> ExaAgentSurface:
        del run_id, step_label  # the sinks are the step's identity now; the labels ride the rows
        return ExaClient(build_onboarding_provider_caller(raw=raw, ledger=ledger), api_key)

    return factory


@dataclass(frozen=True)
class _Scope:
    """Everything one run is about, read once off the task payload.

    ``kind`` is which run this is. ``full`` is the whole-brand walk this module was built for;
    ``personas`` is the narrow run that writes the personas of ONE already-existing ICP document
    — no recon, no catalog, no ICP turn — and ``persona_icp`` is that document. The two are welded
    the way the row's CHECK welds them: a personas payload without its ICP is invalid.
    ``customers`` researches only the seller's existing customers (``proof/customers.md``), for a
    brand onboarded before that step existed (spec 2026-10-16-discovery-excludes-seller-customers
    §4.4).
    """

    run_id: UUID
    workspace_id: str
    brand_id: str
    company_domain: str
    company_name: str
    kind: Literal["full", "personas", "customers", "repair"] = "full"
    persona_icp: IcpRef | None = None
    #: A ``repair`` run's planned steps, ``(kind, subject_ref)`` — spec 2026-10-25 §3.4 A.
    planned: tuple[tuple[str, str | None], ...] = ()


@dataclass(frozen=True)
class _StepOutcome:
    """One step's terminal facts, settled in a single place so no caller can forget half of them."""

    status: Literal["completed", "empty", "failed"]
    document: KnowledgeDocument | None
    provider_run_id: str | None
    raw_artifact_key: str | None
    cost_usd: Decimal
    searches: int
    failure_code: str | None = None
    failure_message: str | None = None


class OnboardingRunWorkHandler:
    """The whole run, as one fleet work handler."""

    kind = FleetTaskKind.ONBOARDING_RUN

    def __init__(
        self,
        *,
        settings: Settings,
        conn_factory: ConnFactory,
        artifacts: ArtifactSink,
        exa: ExaClientFactory,
        client_binder: ClientEntityBinder | None = None,
        synthesis: SynthesisLauncher | None = None,
        clock: Callable[[], date] = date.today,
        store: Any = default_store,
        synchronize_catalog: Callable[..., Any] = default_synchronize,
        known_products: Callable[[AsyncConnection, str], Awaitable[Sequence[str]]] | None = None,
        reconciler_factory: Callable[[RawSink, LedgerSink], CatalogReconciler] | None = None,
        drain: DrainProviderCalls = drain_provider_calls,
        catalog_regenerator: CatalogRegenerator | None = None,
        domain_caller: Callable[..., ProviderCaller] | None = None,
        domain_checker: Callable[
            [ProviderCaller, Sequence[Mapping[str, Any]]], Mapping[str, DomainCheck]
        ] = check_domains,
        current_document: CurrentDocumentReader | None = None,
    ) -> None:
        self._settings = settings
        self._conn_factory = conn_factory
        self._artifacts = artifacts
        self._exa = exa
        self._binder = client_binder
        self._synthesis = synthesis
        self._clock = clock
        # The store and the synchronizer are injected as callables rather than imported at each
        # call site so the offline tests can record every transition in order without a database.
        self._store = store
        self._sync = synchronize_catalog
        # Same reason as the store and the synchronizer: the offline driver tests must never reach
        # a database, and the lineup's re-run hint is a read.
        self._known_products = known_products or _default_known_products
        # A factory, not a reconciler: the model stage spends through a ``ProviderCaller`` built
        # over the catalog step's own buffered sinks, so its one call lands on the ledger with
        # this run's stamp (slice 1b). ``None`` is a composed lane without the model stage — the
        # ladder then stops after its deterministic rungs, which is what it did before the stage
        # existed.
        self._reconciler_factory = reconciler_factory
        # Injected like the store and the synchronizer, so the offline tests record every drain
        # without a database.
        self._drain_calls = drain
        # Spec 2026-10-15 §9: when a re-run's lineup meets products a person merged or removed,
        # the catalog it just published lists them again; this rebuilds it from the product list.
        # ``None`` (the offline tests, a lane without storage) leaves the published catalog as is.
        self._regenerate_catalog = catalog_regenerator
        # The customers step's domain check fetches public homepages (spec 2026-10-16 §4.2).
        # Injected like the store, so the offline tests never reach the network.
        self._domain_caller = domain_caller or build_customer_domain_caller
        self._check_domains = domain_checker
        # CRM integration (R-4.5): the customers step keeps the CRM rows of the version it
        # replaces. ``None`` (the offline tests, a lane without storage) carries nothing.
        self._current_document = current_document
        # The driver holds at most ONE connection at a time. Its row writes are small, ordered
        # facts about one run and the parallelism that matters is the provider calls (which run
        # off both the loop and this lock), so serializing them costs nothing — and it lets a
        # caller inject a single-connection factory (as the DB test does) without the fan-out
        # colliding on it. A worker drives one task at a time, so this is per-run in practice.
        self._db_lock = asyncio.Lock()

    # -- fleet entry -------------------------------------------------------------------------

    async def handle(self, context: WorkContext) -> WorkResult:
        if context.stop_requested.is_set() or context.lease_lost.is_set():
            return WorkResult(outcome="stopped", references={}, requeue=True)
        scope = self._scope(context.payload)
        if UUID(str(context.work_id)) != scope.run_id:
            raise ValueError("onboarding task work id disagrees with its run id")
        try:
            status = await self._run(scope)
        except Exception:
            # Containment: the fleet plane knows nothing about our rows, so an escaping exception
            # would strand the run on ``running``. Everything lands here instead.
            log.exception("onboarding.run_contained_failure", run_id=str(scope.run_id))
            try:
                async with self._connection() as conn:
                    await self._store.fail_run(conn, run_id=scope.run_id)
            except Exception:
                log.exception("onboarding.fail_run_failed", run_id=str(scope.run_id))
            return WorkResult(
                outcome="failed", references={"run_id": str(scope.run_id)}, requeue=False
            )
        return WorkResult(outcome=status, references={"run_id": str(scope.run_id)})

    @staticmethod
    def _scope(payload: Mapping[str, Any]) -> _Scope:
        try:
            named_kind = str(payload.get("kind") or "full")
            if named_kind not in ("full", "personas", "customers", "repair"):
                raise ValueError(f"unknown onboarding run kind {named_kind!r}")
            kind = cast(Literal["full", "personas", "customers", "repair"], named_kind)
            planned: tuple[tuple[str, str | None], ...] = ()
            if kind == "repair":
                planned = tuple(
                    (
                        str(step["kind"]),
                        None if step.get("subject_ref") is None else str(step["subject_ref"]),
                    )
                    for step in payload["planned_steps"]
                )
            icp: IcpRef | None = None
            if kind == "personas":
                # Required, not optional: a personas run's whole subject is this document, and a
                # task nobody can describe must be refused here — before a row is touched — rather
                # than discovered halfway through by an ``assert``.
                named = payload["icp"]
                icp = IcpRef(
                    document_id=UUID(str(named["document_id"])),
                    icp_key=str(named["icp_key"]),
                    version=int(named["version"]),
                    path=str(named["path"]),
                    project_id=(
                        None if named.get("project_id") is None else str(named["project_id"])
                    ),
                )
            return _Scope(
                run_id=UUID(str(payload["run_id"])),
                workspace_id=str(payload["workspace_id"]),
                brand_id=str(payload["brand_id"]),
                company_domain=str(payload["company_domain"]),
                company_name=str(payload.get("company_name") or payload["company_domain"]),
                kind=kind,
                persona_icp=icp,
                planned=planned,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid onboarding task payload") from error

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[AsyncConnection]:
        async with self._db_lock, self._conn_factory() as conn:
            yield conn

    def _stamp(self, scope: _Scope) -> LedgerStamp:
        """D1 (slice 1b): a run's provider spend is the workspace's, with the run id as the job,
        so ``make cost-report --job <run id>`` answers "what did this onboarding cost". No project:
        the whole-brand walk is brand-scoped, and a personas run makes no provider call here."""
        return LedgerStamp(workspace_id=scope.workspace_id, job_id=scope.run_id)

    async def _drain(
        self,
        scope: _Scope,
        raw: BufferedRawSink,
        ledger: BufferedLedger,
        *,
        step_label: str,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Land a step's buffered raw bodies and ledger rows: under the driver's own connection,
        or on ``conn`` when the caller already holds one (the catalog step). A drain that fails
        raises — the rows are the call's money, and losing them quietly is the one thing this
        lane must never do; ``handle``'s containment then fails the run loudly."""
        if conn is not None:
            report = await self._drain_calls(
                conn, raw=raw, ledger=ledger, artifacts=self._artifacts, stamp=self._stamp(scope)
            )
        else:
            async with self._connection() as own:
                report = await self._drain_calls(
                    own, raw=raw, ledger=ledger, artifacts=self._artifacts, stamp=self._stamp(scope)
                )
        log.info(
            "onboarding.ledger_drained",
            run_id=str(scope.run_id),
            step=step_label,
            rows=report.rows,
            artifacts=report.artifacts,
            cost_usd=str(report.cost_usd),
        )

    # -- the run -----------------------------------------------------------------------------

    async def _run(self, scope: _Scope) -> str:
        if scope.kind == "personas":
            return await self._personas_only(scope)
        if scope.kind == "customers":
            return await self._customers_only(scope)
        if scope.kind == "repair":
            return await self._repair_only(scope)
        async with self._connection() as conn:
            await self._store.mark_run_running(conn, run_id=scope.run_id)
            if self._binder is not None:
                await self._binder.ensure(
                    conn,
                    workspace_id=scope.workspace_id,
                    brand_id=scope.brand_id,
                    company_domain=scope.company_domain,
                    run_id=scope.run_id,
                )
        reviews_fast = self._settings.onboarding_reviews_phase == "fast"
        fast: list[Any] = [self._overview(scope), self._lineup(scope)]
        if reviews_fast:
            fast.append(self._reviews(scope, phase="fast"))
        results = await asyncio.gather(*fast)
        links: tuple[ProductLink, ...] = results[1]

        # The ICP turn reads what the fast lane published and does not wait for the per-product
        # reports, so it starts alongside the fan-out rather than after it.
        synthesis_task = asyncio.create_task(self._synthesis_step(scope))
        # An entry that reached its product through a merge already has the survivor's page, so
        # it is not researched again under its old name (spec 2026-10-15 §9).
        background = [
            self._product_research(scope, link)
            for link in _one_link_per_product([link for link in links if not link.redirected])
        ]
        if not reviews_fast:
            background.append(self._reviews(scope, phase="background"))
        background.append(self._customers(scope))
        semaphore = asyncio.Semaphore(self._settings.onboarding_max_parallel_runs)

        async def bounded(work: Any) -> None:
            async with semaphore:
                await work

        # Ordering ruling: the product fan-out is started FIRST (as tasks, so it runs while the
        # ICP turn does), then the ICP turn is awaited, then the persona turns are created. A
        # persona turn therefore begins the moment its ICP exists rather than after every product
        # report has landed — and both fan-outs queue on the one semaphore, so the cap still counts
        # them together. The ``finally`` keeps the original containment: whatever happens to the
        # turns, the product tasks are awaited before the run is settled, so none is left orphaned.
        products = [asyncio.create_task(bounded(work)) for work in background]
        try:
            icps = await synthesis_task
            await asyncio.gather(
                *(asyncio.create_task(bounded(self._persona_step(scope, icp))) for icp in icps)
            )
        finally:
            await asyncio.gather(*products)
        async with self._connection() as conn:
            return str(await self._store.finish_run(conn, run_id=scope.run_id))

    async def _customers_only(self, scope: _Scope) -> str:
        """A customers run: mark it running, research the existing customers, finish (§4.4)."""
        async with self._connection() as conn:
            await self._store.mark_run_running(conn, run_id=scope.run_id)
        await self._customers(scope)
        async with self._connection() as conn:
            return str(await self._store.finish_run(conn, run_id=scope.run_id))

    async def _repair_only(self, scope: _Scope) -> str:
        """A repair run: only the steps a workspace repair planned (spec 2026-10-25 §3.4 A).

        The same step methods as the full walk, so a repaired step lands exactly as it would have
        the first time — new document versions, the same ledger stamps, the same containment. The
        lineup re-runs its catalog sync and researches the products that have never been
        researched; a re-run ICP turn writes the personas of the ICPs it registers; a planned
        persona is written for the brand's current ICP of that key.
        """
        async with self._connection() as conn:
            await self._store.mark_run_running(conn, run_id=scope.run_id)
        planned = set(scope.planned)
        kinds = {kind for kind, _ in planned}
        recon: list[Any] = []
        if "overview" in kinds:
            recon.append(self._overview(scope))
        if "reviews" in kinds:
            recon.append(self._reviews(scope, phase="fast"))
        links: tuple[ProductLink, ...] = ()
        if "lineup" in kinds:
            links, *_ = await asyncio.gather(self._lineup(scope), *recon)
        else:
            await asyncio.gather(*recon)
        async with self._connection() as conn:
            researched = await self._store.researched_product_ids(
                conn, workspace_id=scope.workspace_id, brand_id=scope.brand_id
            )
            named = sorted(subject for kind, subject in planned
                           if kind == "product_research" and subject)
            planned_links = await self._store.product_links(
                conn, workspace_id=scope.workspace_id, product_ids=named
            )
            persona_keys = sorted(subject for kind, subject in planned
                                  if kind == "persona" and subject)
            persona_icps = await self._store.current_brand_icps(
                conn, workspace_id=scope.workspace_id, brand_id=scope.brand_id,
                icp_keys=persona_keys,
            )
        products = [
            link for link in _one_link_per_product([link for link in links if not link.redirected])
            if link.product_id not in researched
        ]
        known = {link.product_id for link in products}
        products += [link for link in planned_links if link.product_id not in known]
        semaphore = asyncio.Semaphore(self._settings.onboarding_max_parallel_runs)

        async def bounded(work: Any) -> None:
            async with semaphore:
                await work

        background = [self._product_research(scope, link) for link in products]
        if "customers" in kinds:
            background.append(self._customers(scope))
        tasks = [asyncio.create_task(bounded(work)) for work in background]
        try:
            icps: tuple[IcpRef, ...] = ()
            if "synthesis" in kinds:
                icps = await self._synthesis_step(scope)
            registered = {icp.icp_key for icp in icps}
            persona_work = [*icps, *(icp for icp in persona_icps if icp.icp_key not in registered)]
            await asyncio.gather(
                *(asyncio.create_task(bounded(self._persona_step(scope, icp)))
                  for icp in persona_work)
            )
        finally:
            await asyncio.gather(*tasks)
        async with self._connection() as conn:
            return str(await self._store.finish_run(conn, run_id=scope.run_id))

    async def _personas_only(self, scope: _Scope) -> str:
        """A personas run: mark it running, take the one persona step, finish.

        Everything the full walk does before this — binding the client entity, the fast recon, the
        catalog sync, the ICP turn — is about *establishing* a brand's knowledge. This run is asked
        for when that knowledge already exists and one confirmed profile now needs its buying
        committee written down, so re-running any of it would re-research a brand nobody asked
        about and re-version documents nobody asked to change.

        The step itself is :meth:`_persona_step` unchanged, with its own containment: a persona
        turn that fails, refuses or hangs lands its step ``failed`` and the run closes
        ``completed_with_gaps`` rather than escaping.
        """
        async with self._connection() as conn:
            await self._store.mark_run_running(conn, run_id=scope.run_id)
        # Guaranteed by ``_scope``, which refuses a personas payload that names no ICP before any
        # row is touched.
        assert scope.persona_icp is not None
        await self._persona_step(scope, scope.persona_icp)
        async with self._connection() as conn:
            return str(await self._store.finish_run(conn, run_id=scope.run_id))

    # -- steps -------------------------------------------------------------------------------

    def _step_id(self, scope: _Scope, kind: str, subject: str | None = None) -> UUID:
        return uuid5(NAMESPACE_URL, f"onboarding-step:{scope.run_id}:{kind}:{subject or ''}")

    def _document_id(self, scope: _Scope, path: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"onboarding-document:{scope.run_id}:{path}")

    async def _overview(self, scope: _Scope) -> None:
        await self._agent_step(
            scope,
            kind="overview",
            phase="fast",
            folder="company",
            path="company/overview.md",
            doc_kind="company-overview",
            query=company_overview_query(f"{scope.company_name} ({scope.company_domain})"),
            schema=company_overview_output_schema(),
            effort=self._settings.onboarding_overview_effort,
            system_prompt=COMPANY_OVERVIEW_SYSTEM_PROMPT,
            mapper=lambda run: company_overview_document(
                run, company_domain=scope.company_domain, as_of=self._clock()
            ),
        )

    async def _reviews(self, scope: _Scope, *, phase: str) -> None:
        await self._agent_step(
            scope,
            kind="reviews",
            phase=phase,
            folder="proof",
            path="proof/customer-reviews.md",
            doc_kind="customer-reviews",
            query=customer_reviews_query(scope.company_name, scope.company_domain),
            schema=customer_reviews_output_schema(),
            effort=self._settings.onboarding_reviews_effort,
            system_prompt=CUSTOMER_REVIEWS_SYSTEM_PROMPT,
            mapper=lambda run: customer_reviews_document(
                run, company_domain=scope.company_domain, as_of=self._clock()
            ),
        )

    async def _customers(self, scope: _Scope) -> None:
        """The seller's existing customers (spec 2026-10-16-discovery-excludes-seller-customers):
        one Exa Agent run, then one homepage check per domain it gave, into proof/customers.md."""

        async def finish(run: ExaAgentRun) -> KnowledgeDocument:
            data = run.structured if isinstance(run.structured, dict) else {}
            customers = [c for c in data.get("customers") or [] if isinstance(c, dict)]
            raw, ledger = BufferedRawSink(), BufferedLedger()
            try:
                caller = self._domain_caller(raw=raw, ledger=ledger)
                checks = await asyncio.to_thread(self._check_domains, caller, customers)
            finally:
                await self._drain(scope, raw, ledger, step_label="customers")
            return existing_customers_document(
                run,
                company_domain=scope.company_domain,
                as_of=self._clock(),
                checks=checks,
                carried_rows=await self._carried_crm_rows(scope),
            )

        await self._agent_step(
            scope,
            kind="customers",
            phase="background",
            folder="proof",
            path="proof/customers.md",
            doc_kind="existing-customers",
            query=existing_customers_query(scope.company_name, scope.company_domain),
            schema=existing_customers_output_schema(),
            effort=self._settings.onboarding_customers_effort,
            system_prompt=EXISTING_CUSTOMERS_SYSTEM_PROMPT,
            finish=finish,
        )

    async def _carried_crm_rows(self, scope: _Scope) -> list[CustomerRow]:
        """The CRM rows of the current ``proof/customers.md`` (R-4.5). A read that fails fails the
        step, so a refresh never publishes a version that silently dropped them."""
        if self._current_document is None:
            return []
        async with self._connection() as conn:
            body = await self._current_document(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                path="proof/customers.md",
            )
        return crm_customer_rows(body) if body else []

    async def _product_research(self, scope: _Scope, link: ProductLink) -> None:
        product_id = link.product_id or ""
        slug = slugify(link.name)
        await self._agent_step(
            scope,
            kind="product_research",
            phase="background",
            subject=product_id,
            folder="product",
            path=f"product/{slug}.md",
            doc_kind="product-research",
            query=product_research_query(
                product_name=link.name,
                company_name=scope.company_name,
                official_url=None,
                sibling_names=[],
            ),
            schema=product_research_output_schema(),
            effort=self._settings.onboarding_product_effort,
            system_prompt=PRODUCT_RESEARCH_SYSTEM_PROMPT,
            mapper=lambda run: product_research_document(
                run,
                product_id=product_id,
                product_name=link.name,
                product_slug=slug,
                as_of=self._clock(),
            ),
        )

    async def _agent_step(
        self,
        scope: _Scope,
        *,
        kind: str,
        phase: str,
        folder: str,
        path: str,
        doc_kind: str,
        query: str,
        schema: Mapping[str, object],
        effort: str,
        system_prompt: str,
        mapper: Callable[[ExaAgentRun], KnowledgeDocument] | None = None,
        subject: str | None = None,
        finish: Callable[[ExaAgentRun], Awaitable[KnowledgeDocument]] | None = None,
    ) -> None:
        """One Exa Agent step: open the step and its document, call, settle. Never raises.

        The open is inside the containment too. Its one known failure is the store refusing a
        second step of the same ``(run, kind, subject)`` — a driver defect (the 2026-09-29
        onboarding lost a finished run to a duplicate product launch this way), which is logged
        loudly and costs this step, never the run: no provider call is made, no row is touched.
        """
        step_id = self._step_id(scope, kind, subject)
        document_id = self._document_id(scope, path)
        label = f"{kind}:{subject}" if subject else kind
        try:
            async with self._connection() as conn:
                await self._store.start_step(
                    conn,
                    step_id=step_id,
                    run_id=scope.run_id,
                    workspace_id=scope.workspace_id,
                    kind=kind,
                    phase=phase,
                    subject_ref=subject,
                )
                await self._store.open_document(
                    conn,
                    document_id=document_id,
                    workspace_id=scope.workspace_id,
                    brand_id=scope.brand_id,
                    folder=folder,
                    path=path,
                    kind=doc_kind,
                    step_id=step_id,
                )
        except Exception:
            log.exception(
                "onboarding.step_open_failed",
                run_id=str(scope.run_id),
                workspace_id=scope.workspace_id,
                step=label,
                step_id=str(step_id),
            )
            return
        raw, ledger = BufferedRawSink(), BufferedLedger()
        client = self._exa(run_id=scope.run_id, step_label=label, raw=raw, ledger=ledger)
        try:
            run = await asyncio.to_thread(
                client.agent_run,
                query=query,
                output_schema=schema,
                effort=effort,
                system_prompt=system_prompt,
                label=label,
            )
        except Exception as error:
            # A provider halt or a transport failure is a step outcome, not a run failure.
            await self._settle(scope, step_id, document_id, _failed_step(error))
            return
        finally:
            # Whatever the call's outcome, its rows are money: land them (slice 1b).
            await self._drain(scope, raw, ledger, step_label=label)
        if run.status != "completed" or not isinstance(run.structured, dict):
            # A run that finished ``completed`` without a structured object did not answer the
            # schema, which is its own failure — reporting it as ``completed`` would name the
            # status as the reason and say nothing.
            unschematic = run.status == "completed"
            await self._settle(
                scope,
                step_id,
                document_id,
                _StepOutcome(
                    status="failed",
                    document=None,
                    provider_run_id=run.run_id,
                    raw_artifact_key=run.raw_refs[-1] if run.raw_refs else None,
                    cost_usd=run.cost_usd or Decimal(0),
                    searches=_searches(run),
                    failure_code=run.error_code
                    or ("unparseable_output" if unschematic else run.status),
                    failure_message=run.error_message
                    or ("the run returned no structured output" if unschematic else None),
                ),
            )
            return
        try:
            if finish is not None:
                document = await finish(run)
            else:
                assert mapper is not None, "an agent step needs a mapper or a finish"
                document = mapper(run)
        except Exception as error:
            # The document's own work (the customers step's domain check) failing is the step's
            # outcome, exactly as a provider failure is.
            await self._settle(scope, step_id, document_id, _failed_step(error))
            return
        await self._settle(
            scope,
            step_id,
            document_id,
            _StepOutcome(
                status="completed",
                document=document,
                provider_run_id=run.run_id,
                raw_artifact_key=run.raw_refs[-1] if run.raw_refs else None,
                cost_usd=run.cost_usd or Decimal(0),
                searches=_searches(run),
            ),
        )

    async def _lineup(self, scope: _Scope) -> tuple[ProductLink, ...]:
        """Two deep-reasoning passes of one question, merged into the catalog, then synchronized.

        The own-domain pass is the authority and the open-web pass is coverage; ``catalog_sync`` is
        its own step because minting product rows is a different kind of failure from failing to
        find products, and the page must be able to tell them apart.

        On a re-run the query also names the products already on file (:data:`_KNOWN_PRODUCTS_HINT`)
        so the model reuses a spelling rather than inventing a near-miss of it.
        """
        step_id = self._step_id(scope, "lineup")
        document_id = self._document_id(scope, "product/catalog.md")
        async with self._connection() as conn:
            await self._store.start_step(
                conn,
                step_id=step_id,
                run_id=scope.run_id,
                workspace_id=scope.workspace_id,
                kind="lineup",
                phase="fast",
            )
            await self._store.open_document(
                conn,
                document_id=document_id,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                folder="product",
                path="product/catalog.md",
                kind="product-catalog",
                step_id=step_id,
            )
            try:
                known: Sequence[str] = await self._known_products(conn, scope.brand_id)
            except Exception as error:
                # The hint is an optimization, not an input: a run that cannot read what is on file
                # asks the bare question rather than failing. (Losing it costs a re-run some name
                # drift; failing here would cost the whole run.)
                log.warning(
                    "onboarding.known_products_unavailable",
                    run_id=str(scope.run_id),
                    brand_id=scope.brand_id,
                    reason=str(error)[:200],
                )
                known = ()
        raw, ledger = BufferedRawSink(), BufferedLedger()
        client = self._exa(run_id=scope.run_id, step_label="lineup", raw=raw, ledger=ledger)
        query = f"Exhaustive list of products of {scope.company_domain}"
        if known:
            query = f"{query}\n\n{_KNOWN_PRODUCTS_HINT}{'; '.join(known)}"
        schema = product_catalog_output_schema()
        try:
            own = await asyncio.to_thread(
                client.deep_reasoning,
                system_prompt=LINEUP_SYSTEM_PROMPT,
                query=query,
                output_schema=schema,
                num_results=40,
                include_domains=[scope.company_domain],
                label="lineup:own-domain",
            )
            open_web = await asyncio.to_thread(
                client.deep_reasoning,
                system_prompt=LINEUP_SYSTEM_PROMPT,
                query=query,
                output_schema=schema,
                num_results=40,
                label="lineup:open",
            )
        except Exception as error:
            await self._settle(scope, step_id, document_id, _failed_step(error))
            return ()
        finally:
            await self._drain(scope, raw, ledger, step_label="lineup")
        merged = _merge_lineups(own, open_web)
        document = product_catalog_document(
            merged, company_domain=scope.company_domain, as_of=self._clock()
        )
        products = tuple(
            CatalogProduct(
                name=entry["name"],
                short_description=entry["short_description"],
                aliases=tuple(entry.get("aliases") or ()),
                # The mapper copies whatever the provider sent, so a non-string here is a provider
                # answer that ignored the schema. It becomes ``None``: the model stage reads a
                # page as evidence, and a number or an object is not one.
                official_url=(
                    entry["official_url"] if isinstance(entry.get("official_url"), str) else None
                ),
            )
            for entry in document.front_matter["products"]
        )
        cost = (own.cost_usd or Decimal(0)) + (open_web.cost_usd or Decimal(0))
        if not products:
            # An honestly empty catalog is still a document: it names what was searched.
            await self._settle(
                scope,
                step_id,
                document_id,
                _StepOutcome(
                    status="empty",
                    document=document,
                    provider_run_id=own.request_id,
                    raw_artifact_key=own.raw_ref,
                    cost_usd=cost,
                    searches=0,
                    failure_message=_NO_PRODUCTS,
                ),
            )
            return ()
        await self._settle(
            scope,
            step_id,
            document_id,
            _StepOutcome(
                status="completed",
                document=document,
                provider_run_id=own.request_id,
                raw_artifact_key=own.raw_ref,
                cost_usd=cost,
                searches=0,
            ),
        )
        return await self._catalog_sync(scope, document_id=document_id, products=products)

    async def _catalog_sync(
        self, scope: _Scope, *, document_id: UUID, products: Sequence[CatalogProduct]
    ) -> tuple[ProductLink, ...]:
        step_id = self._step_id(scope, "catalog_sync")
        async with self._connection() as conn:
            await self._store.start_step(
                conn,
                step_id=step_id,
                run_id=scope.run_id,
                workspace_id=scope.workspace_id,
                kind="catalog_sync",
                phase="fast",
            )
            try:
                # Inside the try with the sync itself: building one is cheap and cannot spend
                # (the provider caller is built lazily, per call), but if it ever did raise, the
                # failure law says this step lands ``failed`` with its reason — not that the run
                # dies in ``handle``'s containment.
                raw, ledger = BufferedRawSink(), BufferedLedger()
                reconciler = (
                    self._reconciler_factory(raw, ledger)
                    if self._reconciler_factory is not None
                    else None
                )
                try:
                    links = await self._sync(
                        conn,
                        workspace_id=scope.workspace_id,
                        brand_id=scope.brand_id,
                        document_id=document_id,
                        products=products,
                        reconciler=reconciler,
                    )
                finally:
                    # The step already holds the connection: drain on it (slice 1b).
                    await self._drain(scope, raw, ledger, step_label="catalog-reconcile", conn=conn)
            except Exception as error:
                await self._store.finish_step(
                    conn,
                    step_id=step_id,
                    status="failed",
                    failure_code=type(error).__name__,
                    failure_message=str(error)[:500],
                )
                return ()
            if self._regenerate_catalog is not None and any(
                link.redirected or link.resolution_state == REMOVED_BY_PERSON for link in links
            ):
                await self._regenerate_catalog(
                    conn, workspace_id=scope.workspace_id, brand_id=scope.brand_id
                )
            await self._store.finish_step(conn, step_id=step_id, status="completed")
        return tuple(links)

    async def _synthesis_step(self, scope: _Scope) -> tuple[IcpRef, ...]:
        """The ICP turn — the step O4 fills. Until it is composed the step is honestly ``empty``,
        never skipped: a run with no synthesis must show that on the page rather than look
        complete. Returns the ICPs the turn registered, which is the persona fan-out's work list;
        anything but ``completed`` returns none, so no persona turn is opened without a profile.

        The ``empty``-because-uncomposed case belongs to THIS step alone: with no launcher there is
        nothing to fan out over, so no persona step is opened to be empty in its own right.
        """
        step_id = self._step_id(scope, "synthesis")
        async with self._connection() as conn:
            await self._store.start_step(
                conn,
                step_id=step_id,
                run_id=scope.run_id,
                workspace_id=scope.workspace_id,
                kind="synthesis",
                phase="fast",
            )
        if self._synthesis is None:
            async with self._connection() as conn:
                await self._store.finish_step(
                    conn, step_id=step_id, status="empty", failure_message=_NO_SYNTHESIS
                )
            return ()
        try:
            outcome = await asyncio.wait_for(
                self._synthesis.launch_icps(
                    workspace_id=scope.workspace_id,
                    brand_id=scope.brand_id,
                    run_id=scope.run_id,
                    step_id=step_id,
                ),
                timeout=SYNTHESIS_TURN_HARD_TIMEOUT_S,
            )
        except TimeoutError:
            log.error(
                "onboarding.synthesis_turn_hung",
                run_id=str(scope.run_id),
                step_id=str(step_id),
                turn="icp",
                timeout_s=SYNTHESIS_TURN_HARD_TIMEOUT_S,
            )
            outcome = IcpSynthesisOutcome(
                status="failed",
                failure_code=_TURN_HUNG,
                failure_message=_hung_message("the ICP turn"),
                cost_usd=Decimal(0),
                icps=(),
            )
        except Exception as error:
            outcome = IcpSynthesisOutcome(
                status="failed",
                failure_code=type(error).__name__,
                failure_message=str(error)[:500],
                cost_usd=Decimal(0),
                icps=(),
            )
        await self._land_turn_step(
            step_id, outcome.status, outcome.failure_code, outcome.failure_message, outcome.cost_usd
        )
        if outcome.status != "completed":
            return ()
        # The work list must be unique by ICP key: a persona step's identity IS
        # ``(run, 'persona', icp_key)`` (the step id, and the O1 identity index), so two ICPs
        # arriving under one key would collide on the row rather than fan out — and that write
        # happens before the per-step containment, where it would fail the whole run.
        return _unique_by_key(outcome.icps, run_id=scope.run_id)

    async def _persona_step(self, scope: _Scope, icp: IcpRef) -> None:
        """One persona turn for one registered ICP: its own background step, keyed by the ICP key.

        Contained exactly like the ICP turn — one persona that fails, refuses or hangs takes only
        its own step down, and neither its siblings nor the ICP step that registered the profiles
        is walked back off ``completed``.
        """
        launcher = self._synthesis
        if launcher is None:  # unreachable: no launcher means no ICPs to fan out over
            return
        step_id = self._step_id(scope, "persona", icp.icp_key)
        async with self._connection() as conn:
            await self._store.start_step(
                conn,
                step_id=step_id,
                run_id=scope.run_id,
                workspace_id=scope.workspace_id,
                kind="persona",
                phase="background",
                subject_ref=icp.icp_key,
            )
        try:
            outcome = await asyncio.wait_for(
                launcher.launch_persona(
                    workspace_id=scope.workspace_id,
                    brand_id=scope.brand_id,
                    run_id=scope.run_id,
                    step_id=step_id,
                    icp=icp,
                ),
                timeout=SYNTHESIS_TURN_HARD_TIMEOUT_S,
            )
        except TimeoutError:
            log.error(
                "onboarding.synthesis_turn_hung",
                run_id=str(scope.run_id),
                step_id=str(step_id),
                turn="persona",
                icp_key=icp.icp_key,
                timeout_s=SYNTHESIS_TURN_HARD_TIMEOUT_S,
            )
            outcome = SynthesisOutcome(
                status="failed",
                failure_code=_TURN_HUNG,
                failure_message=_hung_message(f"the persona turn for {icp.icp_key}"),
                cost_usd=Decimal(0),
            )
        except Exception as error:
            outcome = SynthesisOutcome(
                status="failed",
                failure_code=type(error).__name__,
                failure_message=str(error)[:500],
                cost_usd=Decimal(0),
            )
        await self._land_turn_step(
            step_id, outcome.status, outcome.failure_code, outcome.failure_message, outcome.cost_usd
        )

    async def _land_turn_step(
        self,
        step_id: UUID,
        status: Literal["completed", "empty", "failed"],
        failure_code: str | None,
        failure_message: str | None,
        cost_usd: Decimal,
    ) -> None:
        """Settle a synthesis-family step (no document of its own: the launcher registers those).

        ``cost_usd`` is the one turn's own cost — ``finish_run`` sums the steps.
        """
        code = (failure_code or _UNSPECIFIED) if status == "failed" else None
        async with self._connection() as conn:
            await self._store.finish_step(
                conn,
                step_id=step_id,
                status=status,
                cost_usd=cost_usd,
                failure_code=code,
                failure_message=failure_message,
            )

    # -- settlement --------------------------------------------------------------------------

    async def _settle(
        self, scope: _Scope, step_id: UUID, document_id: UUID, outcome: _StepOutcome
    ) -> None:
        """Land a step and its document together: bytes first, then the two rows that cite them."""
        async with self._db_lock:
            ref: ArtifactRef | None = None
            if outcome.document is not None:
                ref = await self._artifacts.persist_body(
                    workspace_id=scope.workspace_id,
                    data=render_markdown(outcome.document).encode("utf-8"),
                    media_type="text/markdown",
                )
            async with self._conn_factory() as conn:
                if ref is not None:
                    # ``empty`` with a body is legal and meant: the catalog's "nothing found"
                    # render is a document worth serving, just not a served fact.
                    await self._store.publish_document(
                        conn,
                        document_id=document_id,
                        artifact_key=ref.artifact_key,
                        artifact_sha256=ref.sha256,
                        status="ready" if outcome.status == "completed" else outcome.status,
                    )
                else:
                    await self._store.fail_document(
                        conn,
                        document_id=document_id,
                        status="failed" if outcome.status == "failed" else "empty",
                    )
                code = (
                    (outcome.failure_code or _UNSPECIFIED) if outcome.status == "failed" else None
                )
                await self._store.finish_step(
                    conn,
                    step_id=step_id,
                    status=outcome.status,
                    provider_run_id=outcome.provider_run_id,
                    raw_artifact_key=outcome.raw_artifact_key,
                    cost_usd=outcome.cost_usd,
                    searches=outcome.searches,
                    failure_code=code,
                    failure_message=outcome.failure_message,
                )


def _unique_by_key(icps: Sequence[IcpRef], *, run_id: UUID) -> tuple[IcpRef, ...]:
    """The first ICP registered under each key wins; a repeat is dropped loudly."""
    kept: dict[str, IcpRef] = {}
    for icp in icps:
        if icp.icp_key in kept:
            log.warning(
                "onboarding.duplicate_icp_key",
                run_id=str(run_id),
                icp_key=icp.icp_key,
                kept_document_id=str(kept[icp.icp_key].document_id),
                dropped_document_id=str(icp.document_id),
            )
            continue
        kept[icp.icp_key] = icp
    return tuple(kept.values())


def _hung_message(what: str) -> str:
    return (
        f"{what} did not return within the driver's hard timeout of "
        f"{SYNTHESIS_TURN_HARD_TIMEOUT_S:g} s and was cancelled"
    )


def _searches(run: ExaAgentRun) -> int:
    value = run.usage.get("searches") if isinstance(run.usage, Mapping) else None
    return int(value) if isinstance(value, int) else 0


def _one_link_per_product(links: Sequence[ProductLink]) -> tuple[ProductLink, ...]:
    """The product fan-out's input: the first link per product, in lineup order.

    The lineup is a list of *entries* and the reconciler maps entries to products, so two entries
    can legitimately resolve to one product (the second is ``model_reused``). A product-research
    step is keyed on ``(run, kind, product_id)``, so launching one per entry opened the same step
    twice and the store refused the second — the 2026-09-29 onboarding (10 entries, 7 products)
    failed on its eighth launch after every real step had completed. Entries with no product
    (unresolved) are skipped, as before.
    """
    seen: set[str] = set()
    kept: list[ProductLink] = []
    for link in links:
        if link.product_id is None or link.product_id in seen:
            continue
        seen.add(link.product_id)
        kept.append(link)
    return tuple(kept)


def _failed_step(error: Exception) -> _StepOutcome:
    return _StepOutcome(
        status="failed",
        document=None,
        provider_run_id=None,
        raw_artifact_key=None,
        cost_usd=Decimal(0),
        searches=0,
        failure_code=type(error).__name__,
        failure_message=str(error)[:500],
    )


def _merge_lineups(own: ExaDeepResult, open_web: ExaDeepResult) -> ExaDeepResult:
    """Append the open-web pass's new names to the own-domain pass; own-domain wins on conflict.

    Only the own-domain pass's ``grounding`` survives, and the merge is shaped around that fact.
    Grounding field paths are indexed (``products[i]``) against the pass that produced them, and
    the catalog mapper attaches citations to merged entries BY INDEX — so **every own-domain entry
    keeps its original position, and none is ever collapsed**, not even a pair that normalizes to
    the same name. Dropping one own entry would shift every later own entry left by one and hand
    it the previous entry's citations, which is precisely the misattribution the single-pass
    grounding rule exists to prevent. (A same-named own pair is not a problem downstream: the
    catalog synchronizer resolves the second against the first as ``alias_reused``.)

    Open-web entries are filtered, not positioned: one is appended only when its normalized name
    is absent from the own pass and from the open-web entries already appended. They land after
    every own index, so they can never displace an own entry's citations — and they carry no
    per-entry sources of their own, which is honest, where a wrong citation would not be.
    """

    def entries(result: ExaDeepResult) -> list[dict[str, Any]]:
        parsed = result.output_object if isinstance(result.output_object, dict) else {}
        raw = parsed.get("products") or []
        return [p for p in raw if isinstance(p, dict) and isinstance(p.get("name"), str)]

    def key_of(entry: Mapping[str, Any]) -> str:
        return " ".join(str(entry["name"]).casefold().split())

    products = list(entries(own))
    seen = {key_of(entry) for entry in products}
    for entry in entries(open_web):
        key = key_of(entry)
        if key in seen:
            continue
        seen.add(key)
        products.append(entry)
    notes = [
        result.output_object.get("coverage_note")
        for result in (own, open_web)
        if isinstance(result.output_object, dict) and result.output_object.get("coverage_note")
    ]
    merged: dict[str, Any] = {
        "coverage_note": " | ".join(str(note) for note in notes) or None,
        "products": products,
    }
    return replace(own, output_object=merged)
