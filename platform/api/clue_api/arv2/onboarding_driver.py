"""The onboarding run on the fleet (ARV2-ONBOARDING-PLAN.md §2–§4; O3).

One ``onboarding_run`` task = one run: fast recon (overview ∥ lineup ∥ reviews), catalog sync, the
synthesis turn (through a seam O4 supplies), then the background per-product fan-out under
``onboarding_max_parallel_runs``. Every provider call is R1's synchronous ``ProviderCaller`` run in
``asyncio.to_thread`` with ONE caller per step, so a blocking HTTP poll loop never owns the event
loop.

The failure law: a provider failure, timeout or empty answer is a **step outcome**, never an
exception — the step lands ``failed``/``empty`` with its reason, its document is closed without a
body, and the run keeps going. ``handle`` contains everything else, because the fleet plane knows
nothing about these rows: an exception that escaped would fail the task and leave the run row
stranded on ``running`` forever.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_api.arv2 import onboarding_store as default_store
from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.exa_client import (
    ExaAgentRun,
    ExaClient,
    ExaDeepResult,
    product_catalog_output_schema,
)
from clue_api.arv2.onboarding_documents import (
    KnowledgeDocument,
    company_overview_document,
    customer_reviews_document,
    product_catalog_document,
    product_research_document,
    render_markdown,
    slugify,
)
from clue_api.arv2.onboarding_lineage import CatalogProduct, ProductLink
from clue_api.arv2.onboarding_lineage import synchronize_catalog as default_synchronize
from clue_api.arv2.onboarding_requests import (
    COMPANY_OVERVIEW_SYSTEM_PROMPT,
    CUSTOMER_REVIEWS_SYSTEM_PROMPT,
    PRODUCT_RESEARCH_SYSTEM_PROMPT,
    company_overview_output_schema,
    company_overview_query,
    customer_reviews_output_schema,
    customer_reviews_query,
    product_research_output_schema,
    product_research_query,
)
from clue_api.arv2.sinks import FileRawSink, JsonlLedger
from clue_api.arv2.transport import HttpxTransport
from clue_config import Secrets, Settings
from clue_db import ConnFactory
from clue_fleet import FleetTaskKind
from clue_fleet.lease import WorkId
from clue_fleet.work_worker import WorkContext, WorkResult
from clue_obs import get_logger

log = get_logger("clue_api.arv2.onboarding_driver")

__all__ = [
    "ONBOARDING_DEDUP_PREFIX",
    "ArtifactSink",
    "ClientEntityBinder",
    "ExaAgentSurface",
    "ExaClientFactory",
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
LINEUP_SYSTEM_PROMPT = (
    "Prefer pages on the company's own domain; list every distinct product page; keep "
    "integrations and partner programs separate from standalone products; never invent an "
    "offering; when unsure of a field, omit it."
)

#: The reason an ``empty`` step records when nothing failed and nothing was found. ``empty`` may
#: not carry a ``failure_code`` (the O1 CHECK is biconditional), so this rides ``failure_message``.
_NO_PRODUCTS = "no products established"
_NO_SYNTHESIS = "synthesis agent not composed (O4)"

#: Every ``failed`` step MUST name a code (the same CHECK, read the other way), so a launcher that
#: refused without one still lands a legal row.
_UNSPECIFIED = "unspecified"


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
    latched by one step's provider must not silently stop another step's calls."""

    def __call__(self, *, run_id: UUID, step_label: str) -> ExaAgentSurface: ...


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
    """What the synthesis turn settled its step with. ``failure_code`` may be ``None`` even on
    ``failed`` — the driver substitutes :data:`_UNSPECIFIED` rather than write an illegal row."""

    status: Literal["completed", "empty", "failed"]
    failure_code: str | None
    failure_message: str | None
    cost_usd: Decimal


class SynthesisLauncher(Protocol):
    async def launch(
        self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID
    ) -> SynthesisOutcome: ...


def build_onboarding_provider_caller(
    settings: Settings, *, run_id: UUID, step_label: str
) -> ProviderCaller:
    """One caller for one step, writing its raw records and ledger under the step's own folder.

    The folder is per-step so "what did this step cost, and what came back" is answerable without
    de-interleaving one shared ledger across a fan-out.
    """
    root = Path(settings.arv2_raw_root) / "onboarding" / str(run_id) / step_label.replace(":", "_")
    root.mkdir(parents=True, exist_ok=True)
    return ProviderCaller(
        transport=HttpxTransport(),
        raw_sink=FileRawSink(root / "raw"),
        ledger=JsonlLedger(root / "ledger.jsonl"),
        now=lambda: datetime.now(UTC),
    )


def build_onboarding_exa_client_factory(settings: Settings, secrets: Secrets) -> ExaClientFactory:
    """The production factory. A blank key is unset (``.env.example`` ships the empty line), so it
    fails here at composition rather than as a provider 401 in the middle of a run."""
    key = secrets.exa_api_key
    if key is None or not key.get_secret_value().strip():
        raise ValueError("CLUE_EXA_API_KEY is required for the onboarding lane")
    api_key = SecretStr(key.get_secret_value())

    def factory(*, run_id: UUID, step_label: str) -> ExaAgentSurface:
        caller = build_onboarding_provider_caller(settings, run_id=run_id, step_label=step_label)
        return ExaClient(caller, api_key)

    return factory


@dataclass(frozen=True)
class _Scope:
    """Everything one run is about, read once off the task payload."""

    run_id: UUID
    workspace_id: str
    brand_id: str
    company_domain: str
    company_name: str


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
            return _Scope(
                run_id=UUID(str(payload["run_id"])),
                workspace_id=str(payload["workspace_id"]),
                brand_id=str(payload["brand_id"]),
                company_domain=str(payload["company_domain"]),
                company_name=str(payload.get("company_name") or payload["company_domain"]),
            )
        except (KeyError, ValueError) as error:
            raise ValueError("invalid onboarding task payload") from error

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[AsyncConnection]:
        async with self._db_lock, self._conn_factory() as conn:
            yield conn

    # -- the run -----------------------------------------------------------------------------

    async def _run(self, scope: _Scope) -> str:
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

        # The synthesis turn reads what the fast lane published and does not wait for the
        # per-product reports, so it starts alongside the fan-out rather than after it.
        synthesis_task = asyncio.create_task(self._synthesis_step(scope))
        background = [
            self._product_research(scope, link) for link in links if link.product_id is not None
        ]
        if not reviews_fast:
            background.append(self._reviews(scope, phase="background"))
        semaphore = asyncio.Semaphore(self._settings.onboarding_max_parallel_runs)

        async def bounded(work: Any) -> None:
            async with semaphore:
                await work

        try:
            await asyncio.gather(*(bounded(work) for work in background))
        finally:
            await synthesis_task
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
        mapper: Callable[[ExaAgentRun], KnowledgeDocument],
        subject: str | None = None,
    ) -> None:
        """One Exa Agent step: open the step and its document, call, settle. Never raises."""
        step_id = self._step_id(scope, kind, subject)
        document_id = self._document_id(scope, path)
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
        label = f"{kind}:{subject}" if subject else kind
        client = self._exa(run_id=scope.run_id, step_label=label)
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
        await self._settle(
            scope,
            step_id,
            document_id,
            _StepOutcome(
                status="completed",
                document=mapper(run),
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
        client = self._exa(run_id=scope.run_id, step_label="lineup")
        query = f"Exhaustive list of products of {scope.company_domain}"
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
        merged = _merge_lineups(own, open_web)
        document = product_catalog_document(
            merged, company_domain=scope.company_domain, as_of=self._clock()
        )
        products = tuple(
            CatalogProduct(
                name=entry["name"],
                short_description=entry["short_description"],
                aliases=tuple(entry.get("aliases") or ()),
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
                links = await self._sync(
                    conn,
                    workspace_id=scope.workspace_id,
                    brand_id=scope.brand_id,
                    document_id=document_id,
                    products=products,
                )
            except Exception as error:
                await self._store.finish_step(
                    conn,
                    step_id=step_id,
                    status="failed",
                    failure_code=type(error).__name__,
                    failure_message=str(error)[:500],
                )
                return ()
            await self._store.finish_step(conn, step_id=step_id, status="completed")
        return tuple(links)

    async def _synthesis_step(self, scope: _Scope) -> None:
        """The step O4 fills. Until it is composed the step is honestly ``empty``, never skipped —
        a run with no synthesis must show that on the page rather than look complete."""
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
            return
        try:
            outcome = await self._synthesis.launch(
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                run_id=scope.run_id,
                step_id=step_id,
            )
        except Exception as error:
            outcome = SynthesisOutcome(
                status="failed",
                failure_code=type(error).__name__,
                failure_message=str(error)[:500],
                cost_usd=Decimal(0),
            )
        code = (outcome.failure_code or _UNSPECIFIED) if outcome.status == "failed" else None
        async with self._connection() as conn:
            await self._store.finish_step(
                conn,
                step_id=step_id,
                status=outcome.status,
                cost_usd=outcome.cost_usd,
                failure_code=code,
                failure_message=outcome.failure_message,
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


def _searches(run: ExaAgentRun) -> int:
    value = run.usage.get("searches") if isinstance(run.usage, Mapping) else None
    return int(value) if isinstance(value, int) else 0


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
    """Union the two passes by normalized name; the own-domain pass wins on conflict.

    Only the own-domain pass's ``grounding`` survives. Grounding field paths are indexed
    (``products[i]``) against the pass that produced them, and the merged list has its own
    ordering — carrying the open-web paths through would attach that pass's citations to whatever
    entry happened to land at the same index. So open-web-only entries reach the catalog with no
    per-entry sources, which is honest; a wrong citation would not be.
    """

    def entries(result: ExaDeepResult) -> list[dict[str, Any]]:
        parsed = result.output_object if isinstance(result.output_object, dict) else {}
        raw = parsed.get("products") or []
        return [p for p in raw if isinstance(p, dict) and isinstance(p.get("name"), str)]

    seen: dict[str, dict[str, Any]] = {}
    for entry in entries(own) + entries(open_web):
        key = " ".join(str(entry["name"]).casefold().split())
        seen.setdefault(key, entry)
    notes = [
        result.output_object.get("coverage_note")
        for result in (own, open_web)
        if isinstance(result.output_object, dict) and result.output_object.get("coverage_note")
    ]
    merged: dict[str, Any] = {
        "coverage_note": " | ".join(str(note) for note in notes) or None,
        "products": list(seen.values()),
    }
    return replace(own, output_object=merged)
