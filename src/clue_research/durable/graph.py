"""The per-account orchestrator-worker graph (M7.1) — LangGraph + ``AsyncPostgresSaver``.

Every Pass-B account is researched by **one constrained orchestrator-worker graph**, not a
mega-agent (substrate §5b). The graph has four node boundaries:

``plan`` → ``fan_out`` (one ``aspect_worker`` per planned aspect, in parallel) → ``collect`` →
``handoff``

* **plan** (the lead): reads the active deep-pass schema + the account's ``current_value``,
  computes the gap-field set, builds a typed
  :class:`~clue_research.durable.planning.ResearchPlan`, and **persists it to
  ``account_run.plan_json`` before any worker spawns** (so a crash leaves consistent state). It
  never holds claim bodies — only the plan and, transiently, the merge view it re-plans on.
* **fan_out**: the lead dispatches one ``aspect_worker`` per aspect via LangGraph's ``Send`` (a
  parallel super-step). Each worker does its IO through the M4 resolver surface and the claim store,
  writes typed claims, and returns a :class:`~clue_research.core.WorkerResult` of **claim-id
  references only** — never blobs. Workers share no state but the store; one worker failing is
  isolated (its aspect is marked ``FAILED``; siblings continue).
* **collect**: merges the workers' reference sets into ``account_run.references_index`` and the
  accumulated cost — ids only, so the lead's context is independent of claim count.
* **handoff**: the ``score_handoff`` boundary M8/M9 attach scoring/verification to (a pass-through
  in M7.1, which owns only the skeleton).

The graph engine (LangGraph) and the checkpoint backend (``AsyncPostgresSaver`` in prod, an
in-memory saver in tests) sit **behind** :class:`AccountResearchGraph` and the
:class:`AccountRunStore` seam — swapping either, or later folding this graph into a Temporal
activity, does not change ``run`` or the :class:`~clue_research.core.AspectWorker` contract
(conventions §2).

The worker *bodies* (mode M2/M3/M4 logic, resolver calls) are M8's; M7.1 ships the graph skeleton,
the worker→store→reference contract, checkpoint-resume, and the account-run persistence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated, Any, Protocol, runtime_checkable
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict

from clue_research.core import (
    AspectContext,
    CampaignRunId,
    ClaimId,
    CostCents,
    EntityId,
    RunId,
    WorkerResult,
    WorkerStatus,
    new_run_id,
)
from clue_research.db import database_url, transaction
from clue_research.durable.account_run import (
    ReferencesIndex,
    ensure_account_run,
    save_plan,
    save_references,
    set_status,
)
from clue_research.durable.enums import AccountRunStatus
from clue_research.durable.planning import ResearchPlan, build_plan, compute_gap_fields
from clue_research.durable.spans import (
    ATTR_ASPECT,
    ATTR_ASPECT_COUNT,
    ATTR_CLAIM_REF_COUNT,
    ATTR_DEPTH,
    ATTR_GAP_FIELD_COUNT,
    ATTR_TIER,
    ATTR_WORKER_STATUS,
    graph_node_span,
)
from clue_research.durable.workers import WorkerRegistry, default_worker_registry
from clue_research.obs import (
    ATTR_CAMPAIGN_RUN_ID,
    ATTR_ENTITY_ID,
    apply_attributes,
    traced_step,
)

# --- the account-run persistence seam ---------------------------------------


@runtime_checkable
class AccountRunStore(Protocol):
    """The persistence seam the graph writes its execution cursor through (M7.1).

    Abstracting persistence keeps the graph orchestration testable on an in-memory saver without a
    Postgres ``account_run`` table, and keeps the durable backend swappable (conventions §2). The
    production implementation is :class:`DbAccountRunStore`."""

    async def begin(
        self,
        *,
        account_run_id: RunId,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId,
        tier: str,
        tenant_id: str | None,
        field_keys: Sequence[str] | None,
    ) -> ResearchPlan:
        """Ensure the run row exists (idempotent on re-entry), compute the gap-fields, build the
        plan, persist it, advance the run to ``RUNNING``, and return the plan — the lead's entire
        pre-fan-out job, so the plan is durable before any worker spawns."""
        ...

    async def complete(
        self,
        *,
        account_run_id: RunId,
        references_index: ReferencesIndex,
        cost_cents: CostCents,
        status: AccountRunStatus,
    ) -> None:
        """Fold the collected aspect→claim-id references and accumulated cost in; set terminal
        status."""
        ...

    async def fail(self, *, account_run_id: RunId, status: AccountRunStatus) -> None:
        """Mark the run terminally failed / budget-exceeded.

        Not called by :meth:`AccountResearchGraph.run` itself: a worker error is *isolated*
        (the aspect is marked failed, the run still completes via :meth:`complete`), and a
        graph-level crash is *resumable* (not terminal), so ``run`` lets it propagate to the
        campaign layer rather than stamping the run ``FAILED`` prematurely. The M7.3 campaign
        scheduler (or an operator) calls this to record a genuinely terminal failure."""
        ...


class DbAccountRunStore:
    """The Postgres :class:`AccountRunStore` — the production persistence path (M7.1).

    Each method runs in its own ``db.transaction()`` (so ``begin``'s ensure-row + plan-persist
    commit atomically, the M7.1 "plan committed before any spawn" guarantee). Gap detection uses the
    tenant-scoped merge view: ``for_tenant(client_id)`` when a tenant is given (so the run sees this
    client's private claims — resonance/facets are tenant-private), else the public base."""

    async def begin(
        self,
        *,
        account_run_id: RunId,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId,
        tier: str,
        tenant_id: str | None,
        field_keys: Sequence[str] | None,
    ) -> ResearchPlan:
        from clue_research.claimstore.tenancy import TenantScope

        scope = (
            TenantScope.for_tenant(tenant_id)
            if tenant_id is not None
            else TenantScope.public_only()
        )
        async with transaction() as conn:
            await ensure_account_run(
                conn,
                account_run_id=account_run_id,
                campaign_run_id=campaign_run_id,
                entity_id=entity_id,
                tier=tier,
            )
            gaps = await compute_gap_fields(conn, entity_id, scope=scope, field_keys=field_keys)
            plan = build_plan(gaps, tier=tier)
            await save_plan(
                conn,
                account_run_id,
                plan_json=plan.model_dump(mode="json"),
                status=AccountRunStatus.RUNNING,
            )
        return plan

    async def complete(
        self,
        *,
        account_run_id: RunId,
        references_index: ReferencesIndex,
        cost_cents: CostCents,
        status: AccountRunStatus,
    ) -> None:
        async with transaction() as conn:
            await save_references(
                conn,
                account_run_id,
                references_index=references_index,
                cost_cents=cost_cents,
                status=status,
            )

    async def fail(self, *, account_run_id: RunId, status: AccountRunStatus) -> None:
        async with transaction() as conn:
            await set_status(conn, account_run_id, status)


# --- the graph result -------------------------------------------------------


class AccountRunResult(BaseModel):
    """What :meth:`AccountResearchGraph.run` returns — *references only* (M7.1).

    The orchestrator's output carries the aspect→claim-id index and the run's cost/status, never a
    claim body. Downstream (M8 scoring, M12 handoff) reads the actual values from the claim store by
    these ids — the lead's payload size is independent of how much was found (substrate §5b)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_run_id: RunId
    entity_id: EntityId
    tier: str
    status: AccountRunStatus
    references_index: ReferencesIndex = {}
    cost_cents: CostCents = Decimal(0)

    @property
    def claim_refs(self) -> tuple[ClaimId, ...]:
        """All collected claim ids, flattened across aspects (the references the lead holds)."""
        return tuple(ClaimId(UUID(cid)) for cids in self.references_index.values() for cid in cids)


# --- the LangGraph state ----------------------------------------------------
# Channels are kept JSON/msgpack-serializable (ids as strings, cost as a string) so the same state
# round-trips through both the in-memory saver and ``AsyncPostgresSaver`` (substrate §12).


def _accumulate(left: list[Any], right: list[Any]) -> list[Any]:
    """Reducer for ``aspect_results``: each parallel ``aspect_worker`` appends its one result."""
    return [*left, *right]


class _GraphState(TypedDict, total=False):
    # inputs (set once at run start)
    entity_id: str
    campaign_run_id: str
    account_run_id: str
    tier: str
    tenant_id: str | None
    field_keys: list[str] | None
    # per-aspect Send payload (set on each parallel ``aspect_worker`` invocation, not the main run)
    aspect_spec: dict[str, Any]
    # produced as the graph advances
    plan: dict[str, Any]
    # reducer-accumulated: each parallel ``aspect_worker`` Send appends its one result, so the
    # concurrent fan-out writes merge instead of clobbering one another (LangGraph channel reducer).
    aspect_results: Annotated[list[dict[str, Any]], _accumulate]
    references_index: dict[str, list[str]]
    cost_cents: str
    status: str


def _terminal_status(statuses: Sequence[WorkerStatus]) -> AccountRunStatus:
    """Roll per-aspect worker outcomes into the run's terminal status.

    A budget stop dominates (the run hit its cost cap — a governed outcome). If *every* aspect
    failed the run is ``FAILED``; otherwise it is ``DONE`` even with some failed aspects — a failing
    worker does not fail the run, it just leaves its aspect empty (substrate §5b / M7.1 AC)."""
    if any(s is WorkerStatus.BUDGET_EXCEEDED for s in statuses):
        return AccountRunStatus.BUDGET_EXCEEDED
    if statuses and all(s is WorkerStatus.FAILED for s in statuses):
        return AccountRunStatus.FAILED
    return AccountRunStatus.DONE


class AccountResearchGraph:
    """The per-account orchestrator-worker graph (M7.1).

    Construct once with an :class:`AccountRunStore` and a :class:`WorkerRegistry`; call :meth:`run`
    per account with a checkpointer. The graph definition is built once and compiled per run with
    the supplied checkpointer, so the checkpoint backend is a runtime choice, not baked in."""

    def __init__(
        self,
        *,
        store: AccountRunStore | None = None,
        workers: WorkerRegistry | None = None,
    ) -> None:
        self._store: AccountRunStore = store if store is not None else DbAccountRunStore()
        self._workers = workers if workers is not None else default_worker_registry()
        self._builder = self._build()

    # -- graph definition --

    def _build(self) -> StateGraph[_GraphState]:
        builder: StateGraph[_GraphState] = StateGraph(_GraphState)
        builder.add_node("plan", self._plan_node)
        builder.add_node("aspect_worker", self._aspect_worker_node)
        builder.add_node("collect", self._collect_node)
        builder.add_node("handoff", self._handoff_node)
        builder.add_edge(START, "plan")
        builder.add_conditional_edges("plan", self._dispatch, ["aspect_worker", "collect"])
        builder.add_edge("aspect_worker", "collect")
        builder.add_edge("collect", "handoff")
        builder.add_edge("handoff", END)
        return builder

    # -- nodes --

    async def _plan_node(self, state: _GraphState) -> dict[str, Any]:
        field_keys = state.get("field_keys")
        with traced_step(
            graph_node_span("plan"),
            **{
                ATTR_CAMPAIGN_RUN_ID: state["campaign_run_id"],
                ATTR_ENTITY_ID: state["entity_id"],
                ATTR_TIER: state["tier"],
            },
        ) as span:
            plan = await self._store.begin(
                account_run_id=RunId(UUID(state["account_run_id"])),
                campaign_run_id=CampaignRunId(UUID(state["campaign_run_id"])),
                entity_id=EntityId(UUID(state["entity_id"])),
                tier=state["tier"],
                tenant_id=state.get("tenant_id"),
                field_keys=tuple(field_keys) if field_keys else None,
            )
            apply_attributes(
                span,
                {
                    ATTR_GAP_FIELD_COUNT: plan.gap_field_count,
                    ATTR_ASPECT_COUNT: len(plan.aspects),
                },
            )
        return {"plan": plan.model_dump(mode="json"), "status": AccountRunStatus.RUNNING.value}

    def _dispatch(self, state: _GraphState) -> list[Send] | str:
        """Fan out: one ``Send`` per planned aspect (a parallel super-step). With no aspects (every
        gap already filled), route straight to ``collect`` so the run still finalizes."""
        plan = state.get("plan") or {}
        aspects: list[dict[str, Any]] = plan.get("aspects", [])
        if not aspects:
            return "collect"
        return [
            Send(
                "aspect_worker",
                {
                    "aspect_spec": aspect,
                    "entity_id": state["entity_id"],
                    "campaign_run_id": state["campaign_run_id"],
                    "account_run_id": state["account_run_id"],
                    "tier": state["tier"],
                },
            )
            for aspect in aspects
        ]

    async def _aspect_worker_node(self, state: _GraphState) -> dict[str, Any]:
        # On a ``Send``, this node's input *is* the per-aspect payload (see ``_dispatch``), carrying
        # ``aspect_spec`` plus the shared run ids — a partial ``_GraphState``.
        spec = state["aspect_spec"]
        aspect = spec["aspect"]
        envelope = spec.get("budget_envelope_cents")
        ctx = AspectContext(
            entity_id=EntityId(UUID(state["entity_id"])),
            campaign_run_id=CampaignRunId(UUID(state["campaign_run_id"])),
            run_id=RunId(UUID(state["account_run_id"])),
            tier=state["tier"],
            aspect=aspect,
            field_keys=tuple(spec.get("field_keys", ())),
            budget_envelope_cents=Decimal(str(envelope)) if envelope is not None else None,
            depth=spec.get("depth", 0),
        )
        worker = self._workers.get(aspect)
        with traced_step(
            graph_node_span("fan_out"),
            **{
                ATTR_CAMPAIGN_RUN_ID: state["campaign_run_id"],
                ATTR_ENTITY_ID: state["entity_id"],
                ATTR_ASPECT: aspect,
                ATTR_DEPTH: ctx.depth,
            },
        ) as span:
            if worker is None:
                result = WorkerResult(
                    aspect=aspect,
                    status=WorkerStatus.FAILED,
                    detail={"reason": "no worker registered for aspect"},
                )
            else:
                try:
                    result = await worker.research(ctx)
                except Exception as exc:  # noqa: BLE001
                    # Isolate a failing worker: its aspect is marked FAILED, siblings continue
                    # (M7.1 AC). Only ``Exception`` is caught — a true cancellation/kill
                    # propagates so the run aborts and resumes from the last checkpoint.
                    result = WorkerResult(
                        aspect=aspect,
                        status=WorkerStatus.FAILED,
                        detail={"error": type(exc).__name__},
                    )
            apply_attributes(
                span,
                {
                    ATTR_WORKER_STATUS: result.status.value,
                    ATTR_CLAIM_REF_COUNT: len(result.claim_refs),
                },
            )
        return {"aspect_results": [result.model_dump(mode="json")]}

    async def _collect_node(self, state: _GraphState) -> dict[str, Any]:
        results = [WorkerResult.model_validate(r) for r in state.get("aspect_results", [])]
        references_index: ReferencesIndex = {}
        cost = Decimal(0)
        for result in results:
            references_index.setdefault(result.aspect, []).extend(
                str(ref) for ref in result.claim_refs
            )
            cost += result.cost_cents
        status = _terminal_status([r.status for r in results])
        with traced_step(
            graph_node_span("collect"),
            **{
                ATTR_CAMPAIGN_RUN_ID: state["campaign_run_id"],
                ATTR_ENTITY_ID: state["entity_id"],
            },
        ) as span:
            await self._store.complete(
                account_run_id=RunId(UUID(state["account_run_id"])),
                references_index=references_index,
                cost_cents=cost,
                status=status,
            )
            apply_attributes(
                span,
                {ATTR_CLAIM_REF_COUNT: sum(len(v) for v in references_index.values())},
            )
        return {
            "references_index": references_index,
            "cost_cents": str(cost),
            "status": status.value,
        }

    async def _handoff_node(self, state: _GraphState) -> dict[str, Any]:
        """The ``score_handoff`` boundary (M7.1): the node M8 scoring / M9 verification attach to.
        A pass-through here — M7.1 owns the skeleton, not the phase bodies — emitting just the span
        so the boundary is observable."""
        with traced_step(
            graph_node_span("handoff"),
            **{
                ATTR_CAMPAIGN_RUN_ID: state["campaign_run_id"],
                ATTR_ENTITY_ID: state["entity_id"],
            },
        ):
            return {}

    # -- entrypoint --

    async def run(
        self,
        entity_id: EntityId,
        *,
        tier: str,
        campaign_run_id: CampaignRunId,
        checkpointer: BaseCheckpointSaver[Any],
        account_run_id: RunId | None = None,
        tenant_id: str | None = None,
        field_keys: Sequence[str] | None = None,
    ) -> AccountRunResult:
        """Research one account and return its references (M7.1).

        ``account_run_id`` is the resume key: it is the LangGraph ``thread_id`` *and* the
        ``claim.run_id`` every worker stamps; minted fresh when omitted. Re-invoking with the same
        id and ``checkpointer`` is **resume-correct**: if a prior call crashed mid-run it continues
        from the last checkpoint (re-seeding *no* inputs, so the lead never re-plans); if a prior
        call already finished it returns the checkpointed result without re-running a single node.
        Per-step dedup of an interrupted fan-out super-step is layered on by M7.4's ledger."""
        run_id = account_run_id if account_run_id is not None else new_run_id()
        graph = self._builder.compile(checkpointer=checkpointer)
        config: RunnableConfig = {"configurable": {"thread_id": str(run_id)}}
        initial: _GraphState = {
            "entity_id": str(entity_id),
            "campaign_run_id": str(campaign_run_id),
            "account_run_id": str(run_id),
            "tier": tier,
            "tenant_id": tenant_id,
            "field_keys": list(field_keys) if field_keys is not None else None,
            "aspect_results": [],
        }
        snapshot = await graph.aget_state(config)
        final: dict[str, Any]
        if snapshot.created_at is None:
            # No checkpoint for this thread → a fresh run from the seeded inputs.
            final = await graph.ainvoke(initial, config=config)
        elif snapshot.next:
            # A prior run checkpointed but did not finish (pending tasks remain) → resume with no
            # new input so the already-committed plan is not recomputed (M7.1 resume guarantee).
            final = await graph.ainvoke(None, config=config)
        else:
            # The thread already reached the end → return its result; re-run nothing.
            final = dict(snapshot.values)
        return AccountRunResult(
            account_run_id=run_id,
            entity_id=entity_id,
            tier=tier,
            status=AccountRunStatus(final.get("status", AccountRunStatus.DONE.value)),
            references_index=final.get("references_index", {}),
            cost_cents=Decimal(final.get("cost_cents", "0")),
        )


# --- checkpointer wiring ----------------------------------------------------


def _psycopg_dsn(sqlalchemy_dsn: str) -> str:
    """Translate the SQLAlchemy ``+asyncpg`` DSN to the plain ``postgresql://`` DSN psycopg (which
    ``AsyncPostgresSaver`` uses) expects — same database, different driver."""
    return sqlalchemy_dsn.replace("+asyncpg", "", 1)


@asynccontextmanager
async def postgres_checkpointer(
    dsn: str | None = None,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Yield a set-up ``AsyncPostgresSaver`` over the project database (the prod checkpointer).

    ``setup()`` creates LangGraph's own checkpoint tables idempotently — they are framework-managed
    (not Alembic, like any library's internal schema); the M7 Alembic migrations own only the domain
    tables (``account_run`` …). Tests use an in-memory saver instead and never touch this path."""
    conn_string = _psycopg_dsn(dsn if dsn is not None else database_url())
    async with AsyncPostgresSaver.from_conn_string(conn_string) as saver:
        await saver.setup()
        yield saver
