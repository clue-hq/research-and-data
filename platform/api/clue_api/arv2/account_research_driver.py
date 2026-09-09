"""One ARV2 account-research job on the fleet: compose it, run the agent, land the receipt.

One ``arv2_account_research`` task is one account (master plan §5): its own lease, its own job row,
its own failure. An account that goes wrong takes only itself down, and the rest of the run keeps
moving — which is why the work id *is* the job id and the driver never touches its siblings.

Two laws shape everything below.

* **``handle`` contains every exception** (the O3 shape). The fleet plane knows nothing about
  ``arv2_research_job`` rows, so an escaping exception would fail the task and strand the job on
  ``in_progress`` forever. Instead every failure lands the job ``needs_review`` with a named
  ``failure_code`` — the composition failures (a missing account row, an ICP artifact whose digest
  is not the one the launch signed off on, a profile whose bytes have moved) are the ones a human
  can actually act on, so they are named rather than swallowed.
* **The job is pinned to what a human authorized.** The run row carries the ICP artifact and its
  sha, and the agent profile's sha; both are re-checked here before a single model call. Bytes
  that moved since the launch mean a *new* authorization, so the job refuses and asks to be
  relaunched rather than researching against something nobody approved.

The driver holds at most one database connection at a time (the O3 ``_db_lock``), and the agent's
tools are handed that same guarded factory — so a tool's claim write and the driver's own row
writes queue behind one lock instead of racing for connections, and a single-connection test
factory works unchanged. The composition connection is always closed *before* the agent runs, or
the first tool write would wait on a lock the driver is still holding.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.ports import AgentModelProvider
from clue_api.arv2 import account_research_store as default_store
from clue_api.arv2.account_research_agent import AgentOutcome, run_account_agent
from clue_api.arv2.account_research_catalog import (
    AccountContext,
    AccountResourceBundle,
    arv2_person_profile_sha256,
    build_system_prompt,
    load_account_resources,
)
from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.account_research_launch import (
    Arv2LaunchReceipt,
    enqueue_launched_jobs,
)
from clue_api.arv2.account_research_store import JobRow, RunRow
from clue_api.arv2.account_research_tools import (
    ProviderClients,
    ToolRuntime,
    build_account_tools,
)
from clue_api.arv2.ai_ark_client import AiArkClient
from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.committee_step import CommitteeStepResult, run_committee_step
from clue_api.arv2.exa_client import ExaClient
from clue_api.arv2.fleet_task import (
    ARV2_ACCOUNT_DEDUP_PREFIX,
    ARV2_ACCOUNT_TASK_PRIORITY,
    arv2_account_work_id,
)
from clue_api.arv2.gemini_media_client import GeminiMediaClient, MediaBudget
from clue_api.arv2.knowledge_frontmatter import document_identity, parse_front_matter
from clue_api.arv2.provider_ledger import (
    ArtifactSink,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.sinks import LedgerSink
from clue_api.arv2.structuring_client import FieldCatalog, StructuringClient, catalog_menu_text
from clue_config import GatewayConfig, Secrets, Settings
from clue_core import Claim, EntityId
from clue_db import ConnFactory, transaction
from clue_fleet import FleetTaskKind, WorkQueue
from clue_fleet.work_worker import WorkContext, WorkResult
from clue_obs import get_logger
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.identity import get_account
from clue_storage import ArtifactIntegrityError, StorageBackend, read_verified_artifact

log = get_logger("clue_api.arv2.account_research_driver")

__all__ = [
    "ARV2_ACCOUNT_DEDUP_PREFIX",
    "ARV2_ACCOUNT_TASK_PRIORITY",
    "Arv2AccountResearchWorkHandler",
    "arv2_account_work_id",
    "build_arv2_account_research_handler",
]

#: The env var holding the model id this lane runs on. It is read directly rather than through an
#: agent-registry role, because R2 composes its own loop (facts-agent.md) — there is no profile
#: version to bump when the model changes, which is exactly what the env-parity rule wants.
ARV2_ACCOUNT_MODEL_ENV = "ARV2_ACCOUNT_AGENT_MODEL"

#: How many already-established lines the model is shown. The block exists to stop the agent
#: re-researching what is already recorded; past a page of it, it stops being read and starts
#: being context budget.
_ESTABLISHED_LINE_CAP = 60

#: Characters of one claim's value the established block shows. The re-run's Zafran deep query
#: was 34k characters because a single AI Ark record or requisition list rode in whole; a line
#: exists to tell the agent *that* a field is known and roughly what it says, not to be the value.
_ESTABLISHED_VALUE_CHARS = 240


def format_established(claims: Sequence[Claim]) -> str:
    """The "already established" block: one compact line per live claim, newest first.

    Values are compact JSON (not Python ``repr``), cut at :data:`_ESTABLISHED_VALUE_CHARS` with
    an ellipsis; the source is the URL, else the source key. The block is a *prefix*, and by
    design the truncated remainder is not recoverable by any tool in this job:
    ``read_account_state(section="already_established")`` returns this same cut block, and
    ``section="claims"`` returns only *this run's* claims, while the block is prior runs'. The
    line exists to tell the agent the field is known, not what it says in full.
    """
    lines: list[str] = []
    for claim in claims[:_ESTABLISHED_LINE_CAP]:
        value = json.dumps(
            claim.value_json, ensure_ascii=False, default=str, separators=(", ", ": ")
        )
        if len(value) > _ESTABLISHED_VALUE_CHARS:
            value = value[:_ESTABLISHED_VALUE_CHARS] + "…"
        source = claim.source_url or claim.source_key or "no source"
        lines.append(f"- {claim.field_key}: {value} ({source})")
    return "\n".join(lines)


#: What the model is asked to do. The *how* is the profile, the prompt and the three skills; this
#: is only the job.
TASK_INSTRUCTION = (
    "Research this account in full: run the ladder, write every evidenced claim, run the audit, "
    "then finalize once."
)

#: The failure code a job records when its pinned profile bytes no longer match the catalog.
PROFILE_PIN_MISMATCH = "profile_pin_mismatch"

#: The failure code a job records when its task payload does not describe it.
INVALID_TASK_PAYLOAD = "invalid_task_payload"

#: What to do when a task names a job row that is not there *yet*. The launch commits its rows
#: before it offers the tasks, so this should never happen — but a task with no row is the one
#: failure that is silent and permanent (an unclaimable job reads as "already finished"), so the
#: driver waits it out rather than trusting the ordering. Twelve attempts five seconds apart is a
#: minute of patience, after which the row genuinely does not exist (a rolled-back launch) and the
#: task fails loudly; there is no row to flag, so the log is the whole report.
_JOB_ROW_RETRY_DELAY = timedelta(seconds=5)
_JOB_ROW_RETRY_ATTEMPTS = 12

#: Model call shape. The gateway's own timeout is the ceiling (the provider builder refuses a
#: larger one), retries and temperature are deliberately modest: this agent's job is evidence, not
#: prose variety.
_MODEL_MAX_RETRIES = 2
_MODEL_MAX_OUTPUT_TOKENS = 8192
_MODEL_TEMPERATURE = 0.2
_MODEL_ROLE = "arv2_account"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@runtime_checkable
class JobScopedClients(Protocol):
    """Clients that must be bound to one job's own media budget before they are used.

    The media ceiling is per job (it is the run's spend, not the worker's), but a client is built
    per provider hop — so the production client factory is rebound per job while a test double,
    which has no budget to enforce, is used as it is.
    """

    def for_job(self, *, media_budget: MediaBudget) -> ProviderClients: ...


@dataclass(frozen=True)
class _Scope:
    """What one task is about, read once off its payload."""

    job_id: UUID
    run_id: UUID
    workspace_id: str


@dataclass(frozen=True)
class _Composition:
    """Everything one job needs before the first model call, read in one connection."""

    job: JobRow
    run: RunRow
    bundle: AccountResourceBundle
    scope: JobScope
    catalog: FieldCatalog
    system_prompt: str


class _ProfilePinMismatch(RuntimeError):
    """The catalog's profile bytes are not the ones this job was authorized on."""


class _InvalidTaskPayload(RuntimeError):
    """The task payload does not describe the job it names."""


class Arv2AccountResearchWorkHandler:
    """One account research job, as one fleet work handler."""

    kind = FleetTaskKind.ARV2_ACCOUNT_RESEARCH

    def __init__(
        self,
        *,
        settings: Settings,
        conn_factory: ConnFactory,
        artifacts: ArtifactSink,
        storage: StorageBackend,
        clients: ProviderClients,
        model_provider: AgentModelProvider,
        model_id: str,
        writer: LenientClaimWriter,
        queue: WorkQueue | None = None,
        store: Any = default_store,
        catalog_root: Path | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._settings = settings
        self._conn_factory = conn_factory
        self._artifacts = artifacts
        self._storage = storage
        self._clients = clients
        self._models = model_provider
        self._model_id = model_id
        self._writer = writer
        #: Where the committee step's person jobs are offered, once the settling transaction has
        #: committed. ``None`` composes the handler without a fan-out: the rows are still written
        #: (they are what a later relaunch or a re-settle re-offers), and the log says so loudly.
        self._queue = queue
        # The store is injected as a module-shaped object so the offline tests can record every
        # transition in order without a database.
        self._store = store
        self._catalog_root = catalog_root
        self._clock = clock
        self._db_lock = asyncio.Lock()
        self._jobs = asyncio.Semaphore(settings.arv2_account_max_parallel_jobs)

    # -- fleet entry -------------------------------------------------------------------------

    async def handle(self, context: WorkContext) -> WorkResult:
        """Drive one job. Never raises: every ending is a :class:`WorkResult`."""
        scope = self._scope(context.payload)
        if scope is None:
            # Nothing names a job, so there is no row to flag. The task fails loudly and a human
            # reads the log; inventing an id to mark would be worse than the honest dead end.
            log.error("arv2.account_invalid_payload", payload=sorted(context.payload))
            return WorkResult(outcome="failed", references={}, requeue=False)
        if context.stop_requested.is_set() or context.lease_lost.is_set():
            await self._suspend(scope)
            return WorkResult(
                outcome="stopped", references={"job_id": str(scope.job_id)}, requeue=True
            )
        if UUID(str(context.work_id)) != scope.job_id:
            status = await self._contain(
                scope,
                code=INVALID_TASK_PAYLOAD,
                message=f"task work id {context.work_id} disagrees with job id {scope.job_id}",
            )
            return WorkResult(outcome=status, references={"job_id": str(scope.job_id)})
        ending: str | WorkResult
        try:
            ending = await self._run(scope, task_attempt=context.task_attempt)
        except asyncio.CancelledError:
            # The fleet CANCELS this task when the lease is lost, and ``CancelledError`` is a
            # ``BaseException`` — so without this clause the ``except Exception`` below never runs,
            # nothing parks the row, and the job stays ``in_progress`` forever (``begin_job``
            # claims only ``not_started``/``suspended``, so the redelivery cannot revive it). The
            # suspend is shielded because the task is already being cancelled: its own database
            # write must survive the cancellation that provoked it.
            await asyncio.shield(self._suspend(scope))
            raise
        except Exception as error:  # noqa: BLE001 — containment: the job row is the only report
            log.exception("arv2.account_job_contained_failure", job_id=str(scope.job_id))
            code = _failure_code(error)
            ending = await self._contain(scope, code=code, message=str(error))
        if isinstance(ending, WorkResult):
            # The one ending that is not a job status: the task arrived before (or without) its
            # row, so there is nothing to settle and the fleet is told what to do with the task.
            return ending
        return WorkResult(
            outcome=ending,
            references={"job_id": str(scope.job_id), "run_id": str(scope.run_id)},
        )

    @staticmethod
    def _scope(payload: Mapping[str, Any]) -> _Scope | None:
        try:
            return _Scope(
                job_id=UUID(str(payload["job_id"])),
                run_id=UUID(str(payload["run_id"])),
                workspace_id=str(payload["workspace_id"]),
            )
        except (KeyError, ValueError):
            return None

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[AsyncConnection]:
        async with self._db_lock, self._conn_factory() as conn:
            yield conn

    async def _suspend(self, scope: _Scope) -> None:
        """Park the job for requeue. A failure here is logged, never raised into the fleet."""
        try:
            async with self._connection() as conn:
                await self._store.suspend_job(conn, job_id=scope.job_id)
        except Exception:  # noqa: BLE001 — a stopped task must still return a result
            log.exception("arv2.account_suspend_failed", job_id=str(scope.job_id))

    async def _contain(self, scope: _Scope, *, code: str, message: str) -> str:
        """Land the job ``needs_review`` with a named reason, and refresh its run."""
        finalization = {
            "reason": code,
            "detail": message[:1_000],
            "profile_sha256": None,
            "model_id": self._model_id,
        }
        try:
            async with self._connection() as conn:
                await self._store.finish_job(
                    conn,
                    job_id=scope.job_id,
                    status="needs_review",
                    finalization=finalization,
                    failure_code=code,
                    failure_message=message[:1_000],
                    model_rounds=0,
                    tool_calls=0,
                    cost_usd=Decimal(0),
                    credits=Decimal(0),
                    media_seconds=0,
                )
                await self._store.refresh_run_status(conn, run_id=scope.run_id)
        except Exception:  # noqa: BLE001 — the fleet result is owed whatever the database does
            log.exception("arv2.account_contain_failed", job_id=str(scope.job_id))
        return "needs_review"

    async def _not_claimable(
        self, conn: AsyncConnection, scope: _Scope, *, task_attempt: int
    ) -> str | WorkResult:
        """``begin_job`` refused. Whether that is normal depends on the row *existing*.

        A row that is terminal (or in progress under another worker) is an ordinary redelivery:
        the fleet may deliver a task more than once, and re-running it would be the error. **No
        row at all** is the opposite — treating it as finished is how an authorized account is
        silently and permanently never researched — so the task is requeued while the launch's
        commit could still be landing, and fails loudly only once waiting has stopped being
        plausible.
        """
        row = await self._store.read_job(conn, job_id=scope.job_id)
        if row is not None:
            log.info("arv2.account_job_not_claimable", job_id=str(scope.job_id), status=row.status)
            return "completed"
        references: dict[str, Any] = {"job_id": str(scope.job_id), "run_id": str(scope.run_id)}
        if task_attempt <= _JOB_ROW_RETRY_ATTEMPTS:
            log.warning(
                "arv2.account_job_row_not_visible",
                job_id=str(scope.job_id),
                task_attempt=task_attempt,
            )
            return WorkResult(
                outcome="job_row_not_visible",
                references=references,
                requeue=True,
                requeue_after=_JOB_ROW_RETRY_DELAY,
            )
        log.error(
            "arv2.account_job_row_missing", job_id=str(scope.job_id), task_attempt=task_attempt
        )
        return WorkResult(outcome="failed", references=references, requeue=False)

    # -- the job -----------------------------------------------------------------------------

    async def _run(self, scope: _Scope, *, task_attempt: int) -> str | WorkResult:
        async with self._connection() as conn:
            job = await self._store.begin_job(conn, job_id=scope.job_id)
            if job is None:
                return await self._not_claimable(conn, scope, task_attempt=task_attempt)
            if job.run_id != scope.run_id:
                # The payload's run is checked against the row rather than trusted, because every
                # pin this job runs under is read from that run — researching under a run nobody
                # named would be researching under an authorization nobody gave.
                raise _InvalidTaskPayload(
                    f"task names run {scope.run_id}, but job {job.job_id} belongs to "
                    f"run {job.run_id}"
                )
            composition = await self._compose(conn, job)

        media_budget = MediaBudget(self._settings.arv2_media_seconds_ceiling)
        runtime = ToolRuntime(
            scope=composition.scope,
            settings=self._settings,
            clients=_clients_for_job(self._clients, media_budget),
            conn_factory=self._connection,
            artifacts=self._artifacts,
            writer=self._writer,
            catalog=composition.catalog,
            media_budget=media_budget,
            now=self._clock,
        )
        model = self._models.build(
            model_id=self._model_id,
            timeout_s=self._settings.gateway_timeout_s,
            max_retries=_MODEL_MAX_RETRIES,
            max_output_tokens=_MODEL_MAX_OUTPUT_TOKENS,
            temperature=_MODEL_TEMPERATURE,
            role=_MODEL_ROLE,
        )
        async with self._jobs:
            outcome = await run_account_agent(
                model=model,
                system_prompt=composition.system_prompt,
                tools=build_account_tools(runtime),
                runtime=runtime,
                max_model_rounds=self._settings.arv2_account_max_model_rounds,
                max_tool_calls_per_round=self._settings.arv2_account_max_tool_calls_per_round,
                max_runtime_s=float(self._settings.arv2_account_max_runtime_s),
                task_instruction=TASK_INSTRUCTION,
                # The row's own attempt counter, incremented by ``begin_job`` on every claim: it
                # keeps a re-driven job's model-spend rows distinct from its first attempt's.
                attempt=job.attempt,
            )
        return await self._settle(composition, runtime, outcome)

    async def _compose(self, conn: AsyncConnection, job: JobRow) -> _Composition:
        """Everything the agent runs on, read under the launch's pins."""
        run = await self._store.read_run(conn, run_id=job.run_id)
        if run is None:
            raise RuntimeError(f"run row {job.run_id} is missing for job {job.job_id}")
        account = await get_account(conn, EntityId(job.account_entity_id))
        if account is None:
            raise RuntimeError(f"account row {job.account_entity_id} is missing")

        icp, icp_gate_keys = await self._pinned_icp(conn, run)
        persona = await self._persona(conn, run)
        catalog = await self._store.read_account_catalog(conn)
        established = await self._already_established(conn, job, run)

        bundle = load_account_resources(self._catalog_root)
        if bundle.profile.sha256 != run.profile_sha256:
            raise _ProfilePinMismatch(
                "profile digest differs from the launch pin — relaunch: "
                f"catalog {bundle.profile.sha256}, run {run.profile_sha256}"
            )

        today = self._clock().date()
        scope = JobScope(
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            project_run_id=run.project_run_id,
            run_id=run.run_id,
            job_id=job.job_id,
            account_id=EntityId(job.account_entity_id),
            account_name=account.canonical_name,
            account_domain=account.primary_domain or "",
            icp_markdown=icp,
            persona_markdown=persona,
            already_established=established,
            effort=run.effort,
            committee_cap=run.committee_cap,
            today=today,
            icp_gate_keys=icp_gate_keys,
        )
        context = AccountContext(
            account_name=scope.account_name,
            account_domain=scope.account_domain,
            account_id=str(scope.account_id),
            workspace_id=scope.workspace_id,
            today=today,
            icp_markdown=icp,
            persona_markdown=persona,
            catalog_menu=catalog_menu_text(catalog),
            already_established=established,
            directive_text=run.directive_text,
            effort=run.effort,
            committee_cap=run.committee_cap,
            icp_gate_keys=icp_gate_keys,
            stop_policy={
                "max_model_rounds": self._settings.arv2_account_max_model_rounds,
                "max_tool_calls_per_round": (self._settings.arv2_account_max_tool_calls_per_round),
                "max_runtime_s": self._settings.arv2_account_max_runtime_s,
            },
        )
        return _Composition(
            job=job,
            run=run,
            bundle=bundle,
            scope=scope,
            catalog=catalog,
            system_prompt=build_system_prompt(bundle, context),
        )

    async def _pinned_icp(self, conn: AsyncConnection, run: RunRow) -> tuple[str, tuple[str, ...]]:
        """The ICP body the launch pinned and its hard-gate keys; refused when the bytes moved.

        The keys travel separately from the markdown because they are not context for the model to
        read — they are the engine's own list of the gates every fit verdict must key to.
        """
        record, body = await read_verified_artifact(
            conn,
            self._storage,
            storage_key=run.icp_artifact_key,
            workspace_id=run.workspace_id,
        )
        if record.content_sha256 != run.icp_artifact_sha256:
            raise ArtifactIntegrityError(
                "ICP artifact digest differs from the launch pin — relaunch: "
                f"stored {record.content_sha256}, run {run.icp_artifact_sha256}"
            )
        raw = body.decode("utf-8")
        try:
            front, markdown = parse_front_matter(raw)
        except ValueError:
            # A document with no front matter still researches; it simply keys no gates.
            return raw, ()
        return markdown, _hard_gate_keys(front)

    async def _persona(self, conn: AsyncConnection, run: RunRow) -> str:
        """The newest persona document written for this run's ICP, or an honest empty block."""
        documents = await self._store.read_persona_documents(
            conn, workspace_id=run.workspace_id, brand_id=run.brand_id
        )
        for document in documents:
            key = document.artifact_key
            if key is None:
                continue
            try:
                _, body = await read_verified_artifact(
                    conn, self._storage, storage_key=key, workspace_id=run.workspace_id
                )
                front, rest = parse_front_matter(body.decode("utf-8"))
            except Exception:  # noqa: BLE001 — an unreadable candidate is skipped, never fatal
                log.warning("arv2.account_persona_unreadable", document=str(document.document_id))
                continue
            _, icp_key = document_identity(front)
            if icp_key == run.icp_key:
                return rest
        log.info("arv2.account_persona_missing", icp_key=run.icp_key, brand_id=run.brand_id)
        return ""

    async def _already_established(self, conn: AsyncConnection, job: JobRow, run: RunRow) -> str:
        """What is already recorded about this account, so the agent researches the gaps.

        ``claims_for`` returns the live claims newest first, so the line cap keeps the freshest
        facts rather than an arbitrary slice of the account's history.
        """
        claims = await claims_for(
            conn,
            EntityId(job.account_entity_id),
            scope=WorkspaceScope.for_workspace(run.workspace_id),
        )
        return format_established(claims)

    # -- the receipt -------------------------------------------------------------------------

    async def _settle(
        self, composition: _Composition, runtime: ToolRuntime, outcome: AgentOutcome
    ) -> str:
        """Land the job's terminal row: the receipt, the ledger's spend, one activity event.

        An **account** job also fans its confirmed committee out here, inside the same transaction
        and after ``finish_job``: the members it resolved become contacts, their three claims and
        one person job each. That is deliberately not a second transaction — a committee written
        beside a job row that did not land, or a job row with a committee that did not, are both
        states nothing repairs — and the jobs are offered to the fleet only once this one commits.
        """
        claims = await runtime.job_claims()
        committee = CommitteeStepResult((), (), ())
        async with self._connection() as conn:
            # The loop's model rounds, onto the same ledger the tools' hops use, BEFORE the spend
            # is read — ``job_spend`` sums every ``result`` row, so the job's ``cost_usd`` is the
            # whole number only if the rounds are already there. No raw sink has anything to
            # drain: a model request and its answer are deliberately not captured, because the
            # prompt carries this job's entire context and the ledger is not where that belongs.
            await drain_provider_calls(
                conn,
                raw=BufferedRawSink(),
                ledger=runtime.model_ledger,
                artifacts=self._artifacts,
                stamp=LedgerStamp(
                    workspace_id=runtime.scope.workspace_id,
                    project_id=runtime.scope.project_id,
                    project_run_id=str(runtime.scope.project_run_id),
                    job_id=runtime.scope.job_id,
                ),
            )
            spend = await self._store.job_spend(conn, job_id=composition.job.job_id)
            link_audit = await self._store.job_link_audit(conn, job_id=composition.job.job_id)
            finalization = _receipt(
                outcome=outcome,
                runtime=runtime,
                bundle=composition.bundle,
                catalog=composition.catalog,
                claims=claims,
                link_audit=link_audit,
                model_id=self._model_id,
            )
            status = "needs_review" if outcome.reason == "model_error" else "completed"
            await self._store.finish_job(
                conn,
                job_id=composition.job.job_id,
                status=status,
                finalization=finalization,
                failure_code="model_error" if status == "needs_review" else None,
                failure_message=outcome.error if status == "needs_review" else None,
                model_rounds=outcome.model_rounds,
                tool_calls=outcome.tool_calls,
                cost_usd=spend.cost_usd,
                credits=spend.credits,
                media_seconds=spend.media_seconds,
            )
            if composition.job.subject_type == "account":
                committee = await self._fan_out_committee(conn, composition, runtime)
            await self._store.refresh_run_status(conn, run_id=composition.run.run_id)
            await self._record_activity(conn, composition, outcome=outcome, claims=len(claims))
        await self._offer_committee(composition, committee)
        log.info(
            "arv2.account_job_finished",
            job_id=str(composition.job.job_id),
            reason=outcome.reason,
            status=status,
            claims=len(claims),
            cost_usd=str(spend.cost_usd),
            committee_jobs=len(committee.jobs),
        )
        return status

    async def _fan_out_committee(
        self, conn: AsyncConnection, composition: _Composition, runtime: ToolRuntime
    ) -> CommitteeStepResult:
        """Run the committee step over what this job's finalization confirmed. Never raises.

        The candidates are the finalization's own, in the order the agent named them — the cap
        truncates the tail, so an order is part of the answer and the claim rows (written in one
        batch, read back by digest) do not carry one. A job that never finalized confirmed nobody.

        Any failure the step did not already contain per member is swallowed *here*: the account
        job's terminal row is already written in this transaction, and losing it to a committee
        problem would turn a finished account into one that must be researched again.
        """
        candidates = (runtime.finalization or {}).get("committee_candidates") or []
        if not candidates:
            return CommitteeStepResult((), (), ())
        try:
            return await run_committee_step(
                conn,
                job=composition.job,
                run=composition.run,
                scope=composition.scope,
                candidates=candidates,
                writer=self._writer,
                person_profile_sha256=arv2_person_profile_sha256(),
            )
        except Exception:  # noqa: BLE001 — containment: the terminal row outranks the fan-out
            log.exception("arv2.committee_step_failed", job_id=str(composition.job.job_id))
            return CommitteeStepResult((), (), ())

    async def _offer_committee(
        self, composition: _Composition, committee: CommitteeStepResult
    ) -> None:
        """Offer the committee's person jobs — **after** the settle committed. Never raises.

        Rows first, offer second (the launch's own rule): a task that reaches a worker before its
        job row exists reads "no such job" as "already done" and drops that person's research for
        good. A failed offer is the recoverable half — the rows are there, and re-settling or
        launching the same people re-offers them — so it is logged, not raised: raising here would
        reach ``handle``'s containment and overwrite the account job's completed row.
        """
        if not committee.jobs:
            return
        if self._queue is None:
            log.warning(
                "arv2.committee_jobs_not_enqueued",
                job_id=str(composition.job.job_id),
                run_id=str(composition.run.run_id),
                job_ids=[str(job.job_id) for job in committee.jobs],
                detail=(
                    "this worker composed the ARV2 research handler without a work queue, so the "
                    "committee's person jobs exist as rows nothing is driving; launch them again "
                    "from a worker that has one"
                ),
            )
            return
        receipt = Arv2LaunchReceipt(
            run_id=composition.run.run_id,
            job_ids=tuple(job.job_id for job in committee.jobs),
            replayed=False,
            project_run_id=composition.run.project_run_id,
            to_enqueue=committee.jobs,
        )
        try:
            await enqueue_launched_jobs(self._queue, receipt)
        except Exception:  # noqa: BLE001 — the job's terminal row must survive a queue outage
            log.exception("arv2.committee_jobs_enqueue_failed", job_id=str(composition.job.job_id))

    async def _record_activity(
        self,
        conn: AsyncConnection,
        composition: _Composition,
        *,
        outcome: AgentOutcome,
        claims: int,
    ) -> None:
        """One feed line per job, authored by Clue — what happened to this account, in one row."""
        await conn.execute(
            _ACTIVITY_SQL,
            {
                "workspace_id": composition.run.workspace_id,
                "account_id": composition.job.account_entity_id,
                "text": f"Account research {outcome.reason}: {claims} claims",
                "action": "account research",
                "occurred_at": self._clock(),
                "project_id": composition.run.project_id,
            },
        )


_ACTIVITY_SQL = text(
    """
    INSERT INTO account_activity_event
        (workspace_id, account_entity_id, kind, actor_kind, text, action, occurred_at,
         project_id, ref_json)
    VALUES (:workspace_id, :account_id, 'updated', 'clue', :text, :action, :occurred_at,
            :project_id, NULL)
    """
)


def _failure_code(error: BaseException) -> str:
    """The named reason a contained failure records. Unnamed failures record their class."""
    if isinstance(error, _ProfilePinMismatch):
        return PROFILE_PIN_MISMATCH
    if isinstance(error, _InvalidTaskPayload):
        return INVALID_TASK_PAYLOAD
    return type(error).__name__


def _receipt(
    *,
    outcome: AgentOutcome,
    runtime: ToolRuntime,
    bundle: AccountResourceBundle,
    catalog: FieldCatalog,
    claims: Sequence[Claim],
    link_audit: Mapping[str, int],
    model_id: str,
) -> dict[str, Any]:
    """The durable account of one job: what it decided, what it wrote, and what it ran on.

    The finalization the agent proposed is carried verbatim; everything else is *derived from the
    rows* (the claims it wrote, the audit annotations, the halt latches) rather than from what the
    model said it did.

    ``link_audit`` arrives keyed ``"<verdict>/<reason>"`` (from
    ``account_research_store.job_link_audit``) and is carried through unchanged: a receipt saying
    ``fetch_failed/page_unreachable: 4`` names a link problem, where a bare ``fetch_failed: 4``
    would leave the reader to guess at one.
    """
    finalization = runtime.finalization or {}
    by_field: dict[str, int] = {}
    for claim in claims:
        by_field[claim.field_key] = by_field.get(claim.field_key, 0) + 1
    registered = catalog.keys()
    proposed = sorted(
        {
            claim.field_key
            for claim in claims
            if claim.field_key not in registered
            or (claim.write_markers or {}).get("proposed_field") is True
        }
    )
    return {
        "reason": outcome.reason,
        "summary": finalization.get("summary", ""),
        "fit_verdicts": finalization.get("fit_verdicts", []),
        "gaps": finalization.get("gaps", []),
        "claims_written": len(claims),
        "by_field": dict(sorted(by_field.items())),
        "proposed_fields": proposed,
        "link_audit": dict(sorted(link_audit.items())),
        "halted_providers": dict(sorted(runtime.halted.items())),
        "profile_sha256": bundle.profile.sha256,
        "manifest_sha256": bundle.manifest_sha256(),
        "model_id": model_id,
        "model_spend": outcome.model_spend.as_receipt(),
        "error": outcome.error,
    }


def _hard_gate_keys(front: Mapping[str, Any]) -> tuple[str, ...]:
    """The keys of the ICP's ``hard_gates``, in the order the document names them.

    The synthesis skill writes ``hard_gates: [{key, rule, test}, …]``. Only the key is read here:
    the rule and the test are for the model (they are in the ICP body it already holds), while the
    key is what the finalization's verdicts are keyed to. Anything malformed is skipped rather than
    fatal — a job must not fail to start over a stray list entry — and an ICP with no gates keys
    nothing, which the tool reads as "any gate label is admitted".
    """
    gates = front.get("hard_gates")
    if not isinstance(gates, list):
        return ()
    keys: list[str] = []
    for gate in gates:
        key = gate.get("key") if isinstance(gate, Mapping) else None
        if isinstance(key, str) and key.strip() and key not in keys:
            keys.append(key)
    return tuple(keys)


def _clients_for_job(clients: ProviderClients, media_budget: MediaBudget) -> ProviderClients:
    return (
        clients.for_job(media_budget=media_budget)
        if isinstance(clients, JobScopedClients)
        else clients
    )


# -- production composition ------------------------------------------------------------------


class _LiveClients:
    """The four R1 clients, each built around the hop's own caller and this job's media budget."""

    def __init__(
        self,
        *,
        settings: Settings,
        exa_api_key: SecretStr,
        ai_ark_api_key: SecretStr,
        gemini_api_key: SecretStr,
        openrouter_api_key: SecretStr,
        openrouter_base_url: str,
        media_budget: MediaBudget | None = None,
    ) -> None:
        self._settings = settings
        self._exa_api_key = exa_api_key
        self._ai_ark_api_key = ai_ark_api_key
        self._gemini_api_key = gemini_api_key
        self._openrouter_api_key = openrouter_api_key
        self._openrouter_base_url = openrouter_base_url
        self._media_budget = media_budget or MediaBudget(settings.arv2_media_seconds_ceiling)

    def for_job(self, *, media_budget: MediaBudget) -> _LiveClients:
        """A copy bound to one job's ceiling, so two jobs never share a media reservation."""
        return _LiveClients(
            settings=self._settings,
            exa_api_key=self._exa_api_key,
            ai_ark_api_key=self._ai_ark_api_key,
            gemini_api_key=self._gemini_api_key,
            openrouter_api_key=self._openrouter_api_key,
            openrouter_base_url=self._openrouter_base_url,
            media_budget=media_budget,
        )

    def exa(self, caller: ProviderCaller) -> ExaClient:
        return ExaClient(caller, self._exa_api_key)

    def ai_ark(self, caller: ProviderCaller) -> AiArkClient:
        return AiArkClient(
            caller, self._ai_ark_api_key, min_gap_s=self._settings.arv2_ai_ark_min_gap_s
        )

    def media(self, caller: ProviderCaller, ledger: LedgerSink) -> GeminiMediaClient:
        return GeminiMediaClient(
            caller,
            openrouter_api_key=self._openrouter_api_key,
            openrouter_base_url=self._openrouter_base_url,
            gemini_api_key=self._gemini_api_key,
            short_model=self._settings.arv2_media_short_model,
            transcribe_model=self._settings.arv2_media_transcribe_model,
            embedding_model=self._settings.arv2_embedding_model,
            media_budget=self._media_budget,
            short_max_seconds=self._settings.arv2_media_short_max_seconds,
            ledger=ledger,
        )

    def structuring(self, caller: ProviderCaller) -> StructuringClient:
        return StructuringClient(
            caller,
            api_key=self._openrouter_api_key,
            base_url=self._openrouter_base_url,
            model=self._settings.arv2_structuring_model,
        )


def build_arv2_account_research_handler(
    settings: Settings,
    secrets: Secrets,
    *,
    storage: StorageBackend,
    artifacts: ArtifactSink,
    model_provider: AgentModelProvider,
    queue: WorkQueue | None = None,
    conn_factory: ConnFactory = transaction,
) -> Arv2AccountResearchWorkHandler | None:
    """Compose the lane on this worker, or refuse loudly and compose nothing.

    A worker missing a credential gets a named warning and **no handler**: the enqueued jobs then
    wait for a correctly-credentialed worker, which is the honest outcome. Failing the boot would
    take every other kind of work on this process down, and composing a keyless handler would
    fail each job at its first provider call — after it had already spent model rounds.

    The **artifact sink and the model provider are injected from outside the lane** (the fleet
    entrypoint passes the platform's own ``DurableAgentArtifactStore`` and agent model provider,
    exactly as it does for onboarding). ARV2 may not open a second write path into the artifact
    table — the production store owns the tombstone/erasure guards a DSAR erasure relies on — and
    it may not reach the vendor SDK behind ``clue_gateway``. What stays here is what belongs to the
    lane: which credentials a job needs, which model id it runs on, and the refusal when either is
    missing.
    """
    if not settings.arv2_account_research_enabled:
        return None
    keys = {
        "CLUE_EXA_API_KEY": secrets.exa_api_key,
        "CLUE_OPENROUTER_API_KEY": secrets.openrouter_api_key,
        "CLUE_AI_ARK_API_KEY": secrets.ai_ark_api_key,
        "CLUE_GEMINI_API_KEY": secrets.gemini_api_key,
    }
    missing = [name for name, value in keys.items() if not _present(value)]
    model_id = os.environ.get(ARV2_ACCOUNT_MODEL_ENV, "").strip()
    if not model_id:
        missing.append(ARV2_ACCOUNT_MODEL_ENV)
    if missing:
        log.warning(
            "arv2.account_handler_not_composed",
            missing=missing,
            detail=(
                "CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED is on but this worker is missing "
                f"{', '.join(missing)}; account research jobs stay queued until a worker with "
                "the full configuration drains them"
            ),
        )
        return None

    return Arv2AccountResearchWorkHandler(
        settings=settings,
        conn_factory=conn_factory,
        artifacts=artifacts,
        storage=storage,
        clients=_LiveClients(
            settings=settings,
            exa_api_key=_secret(keys["CLUE_EXA_API_KEY"]),
            ai_ark_api_key=_secret(keys["CLUE_AI_ARK_API_KEY"]),
            gemini_api_key=_secret(keys["CLUE_GEMINI_API_KEY"]),
            openrouter_api_key=_secret(keys["CLUE_OPENROUTER_API_KEY"]),
            # The OpenRouter URL is gateway policy, read from the config's own default rather than
            # spelled again here: the two ARV2 clients that speak to OpenRouter directly (media,
            # structuring) must reach the same endpoint the gateway does.
            openrouter_base_url=GatewayConfig().base_url,
        ),
        model_provider=model_provider,
        model_id=model_id,
        writer=LenientClaimWriter(lenient=settings.claim_write_lenient),
        # The worker's own queue, so a committee resolved on this worker is offered through exactly
        # the machinery that will drain it. Composing without one still writes the person job rows
        # and says so (``arv2.committee_jobs_not_enqueued``).
        queue=queue,
    )


def _present(value: SecretStr | None) -> bool:
    """A blank line in ``.env`` is unset, never an empty credential (the env-parity rule)."""
    return value is not None and bool(value.get_secret_value().strip())


def _secret(value: SecretStr | None) -> SecretStr:
    if value is None:  # pragma: no cover - guarded by the missing-key refusal above
        raise ValueError("credential is unset")
    return SecretStr(value.get_secret_value())
