"""The scripted end-to-end proof harness for comprehensive Account research.

The founder's ratified success criterion, made mechanical: **five Accounts end to end, three times
consecutively, with zero manual database intervention.** This module is that proof with fake
provider transports; the live-provider run is a separate exercise.

What "end to end" means here, precisely:

* **Discovery is real and sealed.** Each cycle seeds a fresh project run whose first-generation
  discovery batch holds five distinct accounts, materialized and sealed through the production
  durable API (:mod:`tests.integration.comprehensive_harness_support`).
* **The launch is the real receipt-pinning launcher.** One human-confirmed 21-field comprehensive
  directive with committee discovery, launched for all five explicitly selected accounts through
  :class:`~clue_api.account_research_fleet_launch.AccountResearchFleetLauncher`.
* **The execution path is the production composition.**
  :func:`~clue_api.account_research_fleet_composition.build_account_research_fleet_composition`
  over :class:`~clue_api.entity_research_provider_wiring.ProductionAccountResearchProviderActions`
  — the same objects the fleet worker composes — driven through the real fleet task/lease
  substrate and the real ``AccountResearchFleetWorkHandler``.
* **Faking happens only at the provider transport seam** (and at the model, which has no
  deterministic real form): Exa Deep's HTTP acquisition transport and the two Sumble clients'
  ``http`` fetchers are replaced with the doubles in
  :mod:`tests.integration.comprehensive_harness_providers`. Every preflight, eligibility,
  reservation, parser, validator, normalizer, claim writer, coverage ledger and finalization check
  in between is production code.

**The adversity mix is the point.** A harness where everything works proves only the happy path.
Of the five accounts each cycle:

* ``sierra`` gets one Exa bundle answered with truncated structured-output alias keys — the live
  defect that used to strand an account forever. It must settle those fields as honest gaps after a
  terminal dispatched attempt, never as a fabricated value and never as an unattempted field.
* ``willamette`` gets an HTTP 422 on Sumble Jobs. ``account.hiring_velocity_eng`` must reach a
  terminal dispatched attempt and settle as an honest gap; the tool must convert the rejection into
  a governed refusal rather than a job-integrity crash.
* ``front-range`` gets a genuinely empty Sumble committee. It must settle as
  ``confirmed_empty_discovery`` — an honest zero-member committee *after* the authorized source was
  really attempted, which is exactly what §5.3 of the settlement plan demands.

Assertions per account per cycle: the job reaches a terminal settled state, the full 21-field
disposition matrix is closed under the shared execution-completeness reader, the committee axis is
terminal, no provider operation is left pending, and spend counters are recorded for settled work.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from functools import partial
from math import ceil
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import ConfigDict, PrivateAttr, SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ModelPolicy
from clue_api import entity_research_provider_wiring, sumble_account_gaps
from clue_api.account_entity_research import (
    born_complete_account_field_keys,
    read_account_research_execution_completeness,
)
from clue_api.account_research_fleet import (
    AccountResearchFleetService,
    AccountResearchFleetState,
)
from clue_api.account_research_fleet_composition import (
    build_account_research_fleet_composition,
)
from clue_api.account_research_fleet_launch import AccountResearchFleetLaunchRequest
from clue_api.comprehensive_research_contract import (
    COMPREHENSIVE_ACCOUNT_FIELD_SOURCES,
    COMPREHENSIVE_ACCOUNT_FIELDS,
)
from clue_api.entity_research_provider_wiring import (
    ProductionAccountResearchProviderActions,
)
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_config import GatewayConfig, Secrets, Settings
from clue_core import (
    Completion,
    LLMGateway,
    Message,
    ProjectRunId,
    ResearchQuestion,
)
from clue_core.entity_research import ResearchFinalizationOutcome
from clue_fleet import (
    DbEntityResearchJobStore,
    FleetTaskKind,
    LeaseGeneration,
    WorkId,
    acquire_work_lease,
    claim_next_task,
    release_work_lease,
)
from clue_fleet.work_worker import WorkContext, WorkResult
from clue_research.resolvers.exa import SOURCE_KEY as EXA_DEEP_SOURCE_KEY
from clue_research.resolvers.exa.deep_contract import EXA_OUTPUT_MAX_FIELDS
from clue_research.resolvers.sumble import SumbleClient
from clue_research.resolvers.sumble.committee_transport import SumbleV9CommitteeClient
from clue_research.verification.pre_spend import PreSpendGateImpl
from clue_storage import FsStorage
from tests.agents.test_entity_research_runtime_r3 import Checkpointers
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.db.conftest import run_async
from tests.integration.comprehensive_harness_providers import (
    HarnessExaTransport,
    HarnessSumbleHttp,
    organization_id_for,
)
from tests.integration.comprehensive_harness_support import (
    ACCOUNT_PROFILES,
    SeededCycle,
    seed_cycle,
)
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_integration_db")

#: How many consecutive green cycles the founder's criterion demands.
CYCLES = 3

#: The account whose Exa batch contains one bundle answered with corrupted alias keys.
TRUNCATED_EXA_SLUG = "sierra"
#: The account whose Sumble Jobs call is refused with a deterministic HTTP 422.
REJECTED_JOBS_SLUG = "willamette"
#: The account whose Sumble committee genuinely enumerates nobody.
EMPTY_COMMITTEE_SLUG = "front-range"

#: The bundle cost the shipped scripted Exa transport reports — the honest recorded price.
RECORDED_BUNDLE_COST_DOLLARS = 0.07

#: What one fake Exa Deep bundle reports as its provider cost, in dollars.
#:
#: This was pinned at 1c while the Exa atomic reservation was sized by the alias count alone: the
#: real packer emits more bundles than that estimate, so at the recorded price the settled cost
#: exceeded the reservation and every account suspended. The reservation is now sized from the
#: same packer, so the harness runs at the recorded price and the cost path is proved honestly.
HARNESS_BUNDLE_COST_DOLLARS = RECORDED_BUNDLE_COST_DOLLARS

#: What the retired alias-only heuristic would have reserved for, in bundles. Read off the §3.1
#: ownership table rather than hardcoded, so it moves with the contract. The real packer splits on
#: Exa's nested-property budget too, so it always exceeds this for the comprehensive profile —
#: which is exactly the gap that used to suspend every account.
_ALIAS_ONLY_BUNDLE_ESTIMATE = max(
    1,
    ceil(
        len(
            tuple(
                field_key
                for field_key, sources in COMPREHENSIVE_ACCOUNT_FIELD_SOURCES.items()
                if EXA_DEEP_SOURCE_KEY in sources
            )
        )
        / EXA_OUTPUT_MAX_FIELDS
    ),
)

#: The confirmed directive's committee plan functions. A ``discover_buying_committee`` call's
#: ``buying_unit_scope.target_functions`` must be a subset of these, so the two are stated once.
COMMITTEE_PLAN_FUNCTIONS: tuple[str, ...] = ("Operations",)

_COMMITTEE_QUESTION = "Which exact people form this account's buying committee?"
_PAIN_QUESTION = "Where is administrative work creating avoidable burden?"
_MOVES_QUESTION = "What strategic operational changes are visible?"

_DEEP_ICP_FIELDS = (
    "account.hiring_velocity_eng",
    "core.primary_tech_stack",
    "account.operational_pain",
    "account.strategic_moves",
    "core.industry",
)


class _NestedConnFactory:
    """Isolate each composed service call while the outer test owns final rollback."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncConnection]:
        async with self._conn.begin_nested():
            yield self._conn


class _InertGateway:
    """Committee discovery runs ``role_inference='agent_deferred'`` and never calls a model.

    The production composition still requires an :class:`~clue_core.LLMGateway` to construct the
    committee action, so this double exists to be constructible and unused; it fails loudly rather
    than silently answering, so a future code change that starts calling it cannot pass unnoticed.
    """

    def complete(self, *, model: str, messages: Sequence[Message], **options: Any) -> Completion:
        del model, messages, options
        raise AssertionError("the harness composes no model-backed provider path")


@dataclass
class _ModelProvider:
    """The ``AgentModelProvider`` seam, pointed at the plan compiled for the job being driven."""

    current: BaseChatModel | None = None

    def build(self, **_kwargs: object) -> BaseChatModel:
        assert self.current is not None
        return self.current


class _HarnessModel(BaseChatModel):
    """A scripted account-research mind: read state, run the plan, assess, finalize.

    Two behaviours separate it from the single-account scripted models already in the suite. It
    tolerates a **governed refusal** (the Sumble 422 path returns an error tool message) by moving
    on to the next planned call instead of exploding — which is exactly what a real agent must do
    when a provider deterministically rejects one field. And it carries a committee call whose
    ``buying_unit_scope`` is built from the account's own geography and an evidence ref taken from
    a preceding result, because the engine refuses an invented scope.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    plan: list[dict[str, Any]]
    account_id: UUID
    locality: str
    region: str
    committee_functions: list[str]
    _result_refs: list[str] = PrivateAttr(default_factory=list)
    _evidence_refs: list[str] = PrivateAttr(default_factory=list)
    _next: int = PrivateAttr(default=0)
    _observed_coverage: dict[str, Any] | None = PrivateAttr(default=None)
    _next_call_index: int = PrivateAttr(default=0)
    _refusals: list[str] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "comprehensive-harness-account-agent"

    @property
    def refusals(self) -> tuple[str, ...]:
        return tuple(self._refusals)

    @property
    def observed_coverage(self) -> dict[str, Any]:
        assert self._observed_coverage is not None
        return self._observed_coverage

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        del tools, tool_choice, kwargs
        return self

    @staticmethod
    def _payload(message: ToolMessage) -> dict[str, Any]:
        content = message.content
        if isinstance(content, str):
            try:
                return cast(dict[str, Any], json.loads(content))
            except json.JSONDecodeError:
                return {"error": content}
        if isinstance(content, dict):
            return cast(dict[str, Any], content)
        return {"error": repr(content)}

    def _call(self, name: str, args: dict[str, Any]) -> ChatResult:
        self._next_call_index += 1
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": name,
                                "args": args,
                                "id": f"harness-{name}-{self._next_call_index}",
                            }
                        ],
                    )
                )
            ]
        )

    def _harvest(self, payload: Mapping[str, Any]) -> None:
        for item in cast(Sequence[Mapping[str, Any]], payload.get("results", ())):
            ref = item.get("result_ref")
            if isinstance(ref, str):
                self._result_refs.append(ref)
            for entry in cast(Sequence[Mapping[str, Any]], item.get("fields", ())):
                for evidence in cast(Sequence[Mapping[str, Any]], entry.get("evidence", ())):
                    value = evidence.get("evidence_ref")
                    if isinstance(value, str):
                        self._evidence_refs.append(value)

    def _advance(self) -> ChatResult:
        while self._next < len(self.plan):
            planned = self.plan[self._next]
            self._next += 1
            name = str(planned["name"])
            args = dict(cast(Mapping[str, Any], planned["args"]))
            if name == "discover_buying_committee":
                if not self._evidence_refs:
                    # Nothing was bought, so there is no grounded scope evidence to cite; the
                    # engine would refuse an invented one. Skip rather than fabricate.
                    continue
                args = {
                    **args,
                    "buying_unit_scope": {
                        "scope_id": str(uuid4()),
                        "account_entity_id": str(self.account_id),
                        "office_label": f"{self.locality} gastroenterology practice",
                        "locality": self.locality,
                        "region": self.region,
                        "target_functions": list(self.committee_functions),
                        "evidence_refs": [self._evidence_refs[0]],
                        "match_policy": "same_office_strict",
                    },
                }
            return self._call(name, args)
        return self._call(
            "assess_account_coverage",
            {
                "result_refs": sorted(set(self._result_refs)),
                "assessment_note": (
                    "Every authorized field/source pair and the committee source were attempted; "
                    "what stayed empty is reported as an honest gap."
                ),
            },
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        tools = [message for message in messages if isinstance(message, ToolMessage)]
        if not tools:
            return self._call("read_account_research_state", {})
        last = tools[-1]
        payload = self._payload(last)
        if last.status == "error":
            if last.name in {"assess_account_coverage", "finalize_account_research"}:
                raise AssertionError(
                    f"governed refusal of {last.name}: {json.dumps(payload, sort_keys=True)}"
                )
            # A deterministic provider rejection is repairable, not fatal: record it and continue
            # with the rest of the plan, which is what the settlement contract expects an agent to
            # do when one source refuses one field.
            self._refusals.append(f"{last.name}:{json.dumps(payload, sort_keys=True)[:200]}")
            return self._advance()
        if last.name == "read_account_research_state":
            return self._advance()
        if last.name == "assess_account_coverage":
            self._observed_coverage = dict(payload)
            outcome = (
                "needs_review"
                if payload.get("unresolved_field_keys")
                or payload.get("review_flags")
                or payload.get("committee_status") != "complete"
                else "completed"
            )
            return self._call(
                "finalize_account_research",
                {
                    "coverage_ledger_ref": payload["coverage_ledger_ref"],
                    "requested_outcome": outcome,
                },
            )
        if last.name == "finalize_account_research":
            return self._call("ResearchFinalizationProposal", dict(payload))
        self._harvest(payload)
        return self._advance()


@dataclass
class _AccountOutcome:
    """Everything the per-account assertions read about one driven job."""

    slug: str
    account_id: UUID
    job_id: UUID
    work_result: WorkResult
    job_state: str
    finalization_outcome: str | None
    completed: frozenset[str]
    unresolved: frozenset[str]
    committee_status: str | None
    spend_cents: Decimal
    refusals: tuple[str, ...] = ()
    terminal_pairs: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    committee_results: int = 0
    committee_confirmed_empty: int = 0
    corrupted_exa_fields: frozenset[str] = field(default_factory=frozenset)


def _acquisition_plan(*, selection: Any, borrowed: frozenset[str]) -> list[dict[str, Any]]:
    """The tool calls one governed agent would make, derived from the launched authority.

    Read off ``selection.field_source_authority`` rather than hardcoded, so a change to the §3.1
    ownership table moves this harness instead of silently diverging from it. The R5 guard states
    the rules it satisfies: ``research_account_deep`` uses Exa Deep alone and its first call must
    carry every Exa-primary field net of the borrowed set, and ``enrich_account`` is independent of
    Exa Deep and takes exactly one source per call.
    """

    authority = {
        item.field_key: tuple(item.source_keys) for item in selection.field_source_authority
    }
    structured: dict[str, list[str]] = {}
    exa_primary: list[str] = []
    for field_key in selection.admitted_field_keys:
        if field_key in borrowed:
            continue
        sources = authority[field_key]
        if not sources:
            # An empty authority authorizes nothing; the field is exhausted by construction.
            continue
        if sources[0] == EXA_DEEP_SOURCE_KEY:
            exa_primary.append(field_key)
        else:
            structured.setdefault(sources[0], []).append(field_key)
    calls: list[dict[str, Any]] = [
        {
            "name": "enrich_account",
            "args": {
                "field_keys": sorted(field_keys),
                "source_keys": [source_key],
                "questions": [_PAIN_QUESTION],
            },
        }
        for source_key, field_keys in sorted(structured.items())
    ]
    if exa_primary:
        calls.append(
            {
                "name": "research_account_deep",
                "args": {
                    "field_keys": sorted(exa_primary),
                    "source_keys": [EXA_DEEP_SOURCE_KEY],
                    "questions": [_PAIN_QUESTION, _MOVES_QUESTION],
                },
            }
        )
    calls.append(
        {
            "name": "discover_buying_committee",
            "args": {
                "field_keys": [],
                "source_keys": ["sumble_people"],
                "questions": [_COMMITTEE_QUESTION],
            },
        }
    )
    return calls


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        exa_account_deep_acquisition_enabled=True,
        sumble_account_gap_enrichment_enabled=True,
        sumble_committee_acquisition_enabled=True,
        sumble_committee_poll_after_s=1,
    )


def _secrets() -> Secrets:
    return Secrets(
        _env_file=None,
        exa_api_key=SecretStr("harness-exa"),
        sumble_api_key=SecretStr("harness-sumble"),
    )


async def _job_rows(conn: AsyncConnection, *, research_run_id: UUID) -> Sequence[Mapping[str, Any]]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT job.job_id, job.subject_entity_id, job.state::text AS state, "
                    "job.finalization_outcome::text AS finalization_outcome, "
                    "job.spent_cents FROM entity_research_job job "
                    "WHERE job.research_run_id=:run_id AND job.subject_type='account' "
                    "ORDER BY job.job_id"
                ),
                {"run_id": research_run_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def _coverage(conn: AsyncConnection, *, job_id: UUID) -> Mapping[str, Any]:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT completed_field_keys, unresolved_field_keys, unresolved_reasons, "
                    "coverage_json FROM entity_research_account_coverage WHERE job_id=:job_id"
                ),
                {"job_id": job_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def _committee_results(conn: AsyncConnection, *, job_id: UUID) -> Mapping[str, int]:
    """How the committee axis actually settled: results, confirmed-empty results, and members."""

    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT
                      count(*) AS results,
                      count(*) FILTER (WHERE result.confirmed_empty_discovery) AS confirmed_empty
                    FROM entity_research_result result
                    JOIN entity_research_tool_request request_row
                      ON request_row.tool_request_id=result.tool_request_id
                    WHERE request_row.job_id=:job_id
                      AND request_row.tool_name='discover_buying_committee'
                    """
                ),
                {"job_id": job_id},
            )
        )
        .mappings()
        .one()
    )
    return {key: int(value) for key, value in row.items()}


async def _pending_operations(conn: AsyncConnection, *, job_id: UUID) -> int:
    return cast(
        int,
        (
            await conn.execute(
                text(
                    """
                    SELECT count(*) FROM entity_research_provider_operation operation
                    JOIN entity_research_provider_observation observation
                      ON observation.provider_operation_ref=operation.operation_ref
                    JOIN entity_research_tool_request request_row
                      ON request_row.tool_request_id=observation.tool_request_id
                    WHERE request_row.job_id=:job_id
                      AND NOT EXISTS (
                          SELECT 1 FROM entity_research_result result
                          WHERE result.provider_operation_ref=operation.operation_ref
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM entity_research_provider_settlement_fold fold
                          WHERE fold.provider_operation_ref=operation.operation_ref
                      )
                    """
                ),
                {"job_id": job_id},
            )
        ).scalar_one(),
    )


async def _drive_cycle(
    conn: AsyncConnection,
    *,
    cycle_index: int,
    tmp_path: Path,
    fixture: Any,
    bundle_cost_dollars: float = HARNESS_BUNDLE_COST_DOLLARS,
    predecessor_id: Any = None,
) -> tuple[SeededCycle, dict[str, _AccountOutcome], HarnessExaTransport, HarnessSumbleHttp]:
    """Seed, launch and drive one whole five-account cycle through the production composition."""

    storage = FsStorage(tmp_path / f"harness-cycle-{cycle_index}")
    connection = _NestedConnFactory(conn)
    cycle = await seed_cycle(
        conn,
        storage,
        fixture=fixture,
        cycle=cycle_index,
        predecessor_id=predecessor_id,
        questions=(
            ResearchQuestion(
                question_id="qualitative-burden",
                text=_PAIN_QUESTION,
                target_field_key="account.operational_pain",
            ),
            ResearchQuestion(
                question_id="strategic-change",
                text=_MOVES_QUESTION,
                target_field_key="account.strategic_moves",
            ),
            # A semantic tool may only carry questions the confirmed directive already authorizes,
            # so the committee question has to be part of the directive rather than invented at
            # call time. It targets the operational-pain row because that is the account fact the
            # committee is being resolved in service of.
            ResearchQuestion(
                question_id="buying-committee",
                text=_COMMITTEE_QUESTION,
                target_field_key="account.operational_pain",
            ),
        ),
    )

    domains = {account.slug: account.primary_domain for account in cycle.accounts}
    names = {account.slug: account.canonical_name for account in cycle.accounts}
    organization_ids = {
        account.slug: organization_id_for(cycle_index * 100 + index)
        for index, account in enumerate(cycle.accounts)
    }
    profile_by_slug = {str(profile["slug"]): profile for profile in ACCOUNT_PROFILES}
    exa = HarnessExaTransport(
        domains=domains,
        truncating_domains=(domains[TRUNCATED_EXA_SLUG],),
        cost_dollars=bundle_cost_dollars,
    )
    sumble = HarnessSumbleHttp(
        domains=domains,
        organization_ids=organization_ids,
        names=names,
        localities={
            slug: (str(profile["city"]), str(profile["region"]))
            for slug, profile in profile_by_slug.items()
        },
        run_token=f"c{cycle_index}",
        rejecting_jobs_slugs=(REJECTED_JOBS_SLUG,),
        empty_committee_slugs=(EMPTY_COMMITTEE_SLUG,),
    )

    models = _ModelProvider()
    composition = build_account_research_fleet_composition(
        storage=storage,
        models=cast(Any, models),
        provider_actions=ProductionAccountResearchProviderActions(
            settings=_settings(),
            secrets=_secrets(),
            storage=storage,
            pre_spend_gate=PreSpendGateImpl(conn_factory=connection),
            gateway=cast(LLMGateway, _InertGateway()),
            gateway_config=GatewayConfig(),
            conn_factory=connection,
        ),
        model_policy=ModelPolicy(
            model_id="comprehensive-harness-model",
            timeout_s=60,
            max_retries=0,
            max_output_tokens=8192,
            temperature=0,
        ),
        conn_factory=connection,
        checkpointers=Checkpointers(),
    )
    projection = await composition.launcher.launch(
        AccountResearchFleetLaunchRequest(
            workspace_id=cycle.workspace_id,
            project_run_id=UUID(str(cycle.project_run_id)),
            research_directive_id=UUID(str(cycle.directive_id)),
            account_entity_ids=cycle.account_ids,
            approved_budget_cap_cents=Decimal("10000"),
            expected_estimated_cost_cents=Decimal("10000"),
            concurrency_limit=4,
        ),
        actor="human:account-owner",
        source_action_ref=f"turn:comprehensive-harness-cycle-{cycle_index}",
        source_operation_id=uuid4(),
    )
    assert projection.selected_accounts == len(cycle.accounts)
    assert projection.queued_accounts == len(cycle.accounts)

    slug_by_account = {UUID(str(account.account_id)): account.slug for account in cycle.accounts}
    jobs = DbEntityResearchJobStore(conn_factory=connection)
    outcomes: dict[str, _AccountOutcome] = {}
    for launched in projection.jobs:
        slug = slug_by_account[launched.account_entity_id]
        profile = profile_by_slug[slug]
        stored = await jobs.get_job(launched.job_id)
        assert stored is not None
        selection = stored.authorization.selection
        borrowed = await born_complete_account_field_keys(
            conn,
            workspace_id=cycle.workspace_id,
            account_entity_id=launched.account_entity_id,
            field_keys=selection.admitted_field_keys,
        )
        models.current = _HarnessModel(
            plan=_acquisition_plan(selection=selection, borrowed=borrowed),
            account_id=launched.account_entity_id,
            locality=str(profile["city"]),
            region=str(profile["region"]),
            committee_functions=list(COMMITTEE_PLAN_FUNCTIONS),
        )
        with _patched_transports(exa=exa, sumble=sumble):
            result = await _handle_job(
                conn,
                job_id=launched.job_id,
                handler=composition.handler,
                worker_id=f"harness-{slug}",
            )
        if result.outcome == "supervisor_suspended":
            # The supervisor swallows the driving exception, so name the failure here rather than
            # letting it surface later as a missing coverage row.
            raise AssertionError(
                f"account {slug!r} was supervisor_suspended: {dict(result.references)}"
            )
        model = models.current
        assert isinstance(model, _HarnessModel)
        outcomes[slug] = _AccountOutcome(
            slug=slug,
            account_id=launched.account_entity_id,
            job_id=launched.job_id,
            work_result=result,
            job_state="",
            finalization_outcome=None,
            completed=frozenset(),
            unresolved=frozenset(),
            committee_status=None,
            spend_cents=Decimal(0),
            refusals=model.refusals,
        )

    for row in await _job_rows(conn, research_run_id=projection.research_run_id):
        slug = slug_by_account[UUID(str(row["subject_entity_id"]))]
        coverage = await _coverage(conn, job_id=UUID(str(row["job_id"])))
        stored_job = await jobs.get_job(UUID(str(row["job_id"])))
        assert stored_job is not None
        completeness = await read_account_research_execution_completeness(
            conn, authorization=stored_job.authorization
        )
        committee = await _committee_results(conn, job_id=UUID(str(row["job_id"])))
        previous = outcomes[slug]
        outcomes[slug] = _AccountOutcome(
            slug=slug,
            account_id=previous.account_id,
            job_id=previous.job_id,
            work_result=previous.work_result,
            job_state=str(row["state"]),
            finalization_outcome=(
                str(row["finalization_outcome"])
                if row["finalization_outcome"] is not None
                else None
            ),
            completed=frozenset(str(value) for value in coverage["completed_field_keys"]),
            unresolved=frozenset(str(value) for value in coverage["unresolved_field_keys"]),
            committee_status=cast(
                str | None,
                cast(Mapping[str, Any], coverage["coverage_json"]).get("committee_status"),
            ),
            spend_cents=Decimal(str(row["spent_cents"] or 0)),
            refusals=previous.refusals,
            terminal_pairs=frozenset(completeness.terminal_field_source_pairs),
            committee_results=committee["results"],
            committee_confirmed_empty=committee["confirmed_empty"],
            corrupted_exa_fields=exa.corrupted_field_keys.get(slug, frozenset()),
        )
        assert completeness.complete, (
            slug,
            completeness.outstanding_field_source_pairs,
            completeness.outstanding_non_acquisition_fields,
            completeness.outstanding_committee_source_keys,
        )
        assert await _pending_operations(conn, job_id=previous.job_id) == 0

    fleet = await AccountResearchFleetService(conn_factory=connection).read(
        projection.research_run_id, workspace_id=cycle.workspace_id
    )
    assert fleet is not None
    assert fleet.fleet_state is AccountResearchFleetState.TERMINAL
    return cycle, outcomes, exa, sumble


@contextmanager
def _patched_transports(*, exa: HarnessExaTransport, sumble: HarnessSumbleHttp) -> Iterator[None]:
    """Replace exactly the three provider transport constructors, and nothing else.

    Each shipped client already exposes its I/O as an injectable seam — Exa's acquisition
    coordinator takes a transport object, both Sumble clients take an ``http`` fetcher — but the
    production composition constructs them itself, with no injection point of its own. Rebinding
    the three constructor names for the duration of one driven job is therefore the narrowest
    possible substitution: everything the composition builds *around* them is untouched.
    """

    replacements: tuple[tuple[ModuleType, str, Any], ...] = (
        (
            entity_research_provider_wiring,
            "ExaDeepHttpAcquisitionTransport",
            lambda **_kwargs: exa,
        ),
        (
            entity_research_provider_wiring,
            "SumbleV9CommitteeClient",
            partial(SumbleV9CommitteeClient, http=sumble),
        ),
        (sumble_account_gaps, "SumbleClient", partial(SumbleClient, http=sumble)),
    )
    originals = [(module, name, getattr(module, name)) for module, name, _ in replacements]
    for module, name, replacement in replacements:
        setattr(module, name, replacement)
    try:
        yield
    finally:
        for module, name, original in originals:
            setattr(module, name, original)


async def _handle_job(
    conn: AsyncConnection,
    *,
    job_id: UUID,
    handler: Any,
    worker_id: str,
) -> WorkResult:
    """Claim the real fleet task and lease, then run the production work handler."""

    task = await claim_next_task(
        conn,
        kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
        worker_id=worker_id,
        project_run_id=ProjectRunId(job_id),
    )
    assert task is not None
    lease = await acquire_work_lease(
        conn,
        work_id=WorkId(job_id),
        worker_id=worker_id,
        ttl=timedelta(seconds=300),
    )
    assert lease is not None
    try:
        return cast(
            WorkResult,
            await handler.handle(
                WorkContext(
                    task_id=task.task_id,
                    work_id=WorkId(job_id),
                    worker_id=worker_id,
                    lease_generation=LeaseGeneration(lease.generation),
                    payload={"job_id": str(job_id)},
                    stop_requested=asyncio.Event(),
                    lease_lost=asyncio.Event(),
                )
            ),
        )
    finally:
        await release_work_lease(
            conn,
            work_id=WorkId(job_id),
            worker_id=worker_id,
            generation=LeaseGeneration(lease.generation),
        )


def _assert_cycle(cycle: SeededCycle, outcomes: Mapping[str, _AccountOutcome]) -> None:
    """Every account settled honestly, and the nominated adversity really happened."""

    assert set(outcomes) == {account.slug for account in cycle.accounts}
    for slug, outcome in sorted(outcomes.items()):
        assert outcome.work_result.outcome != "supervisor_suspended", (slug, outcome.work_result)
        assert outcome.job_state == "terminal", (slug, outcome.job_state)
        assert outcome.finalization_outcome in {
            ResearchFinalizationOutcome.COMPLETED.value,
            ResearchFinalizationOutcome.NEEDS_REVIEW.value,
        }, (slug, outcome.finalization_outcome)
        # The whole 21-field matrix is closed: every row is completed or unresolved, none vanished.
        assert outcome.completed | outcome.unresolved == set(COMPREHENSIVE_ACCOUNT_FIELDS), slug
        assert not outcome.completed & outcome.unresolved, slug
        # Real paid work settled, so a spend counter exists for it. A silent zero here would mean
        # the run closed without any provider settlement being folded into the job.
        assert outcome.spend_cents > 0, (slug, outcome.spend_cents)
        # The committee axis is terminal for every account: a durable result exists (an honest
        # zero-member one counts) for the one authorized committee source.
        assert outcome.committee_results >= 1, (slug, outcome.committee_results)
        assert outcome.committee_status in {"complete", "partial", "needs_review"}, slug

    truncated = outcomes[TRUNCATED_EXA_SLUG]
    assert truncated.corrupted_exa_fields, "the truncating transport never fired on its account"
    # The unusable bundle's rows are honest gaps, never fabricated values — and every one of them
    # still reached a terminal dispatched attempt, which is what lets the account settle at all.
    assert truncated.corrupted_exa_fields <= truncated.unresolved
    assert not truncated.corrupted_exa_fields & truncated.completed
    assert {
        (field_key, EXA_DEEP_SOURCE_KEY) for field_key in truncated.corrupted_exa_fields
    } <= truncated.terminal_pairs
    assert truncated.finalization_outcome == ResearchFinalizationOutcome.NEEDS_REVIEW.value

    rejected = outcomes[REJECTED_JOBS_SLUG]
    assert "account.hiring_velocity_eng" in rejected.unresolved
    assert ("account.hiring_velocity_eng", "sumble_jobs") in rejected.terminal_pairs
    assert rejected.refusals, "the Sumble 422 must reach the agent as a governed refusal"
    assert any("provider_rejected" in item for item in rejected.refusals)

    empty = outcomes[EMPTY_COMMITTEE_SLUG]
    # §5.3: a zero-member committee is honest only after the authorized source was really
    # attempted, and it is recorded as a confirmed-empty enumeration rather than a missing result.
    assert empty.committee_confirmed_empty >= 1, empty.committee_results
    for slug in (TRUNCATED_EXA_SLUG, REJECTED_JOBS_SLUG):
        assert outcomes[slug].committee_confirmed_empty == 0, slug


def test_the_comprehensive_exa_reservation_covers_its_own_bundle_plan(
    tmp_path: Path,
) -> None:
    """The Exa atomic reservation is sized from the plan the action really compiles.

    ``ProductionAccountResearchProviderActions.resolve`` used to reserve
    ``exa_deep.cost_cents * ceil(len(exa_fields) / EXA_OUTPUT_MAX_FIELDS)`` for the whole
    ``research_account_deep`` call, i.e. it assumed the plan splits only on Exa's **8-alias** cap.
    ``pack_exa_deep_field_bundles`` splits whenever ``compile_exa_deep_request`` raises, and Exa's
    schema contract also caps the **total nested property count at 10**
    (``deep_contract.validate_exa_output_schema``). Several comprehensive rows are object-valued,
    so the outstanding Exa-owned §3.1 rows really compile into more bundles than the alias count
    predicts. The reservation covered half the plan, ``DbEntityResearchToolBatchCoordinator``
    refused the settlement, and the supervisor suspended every account — deterministic on replay.

    Sizing the reservation with that same packer fixes it, and this drives a whole cycle at the
    recorded provider price to prove it: more bundles than the old estimate allowed for, all of
    them settled, and every account closing honestly instead of suspending.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=FsStorage(tmp_path / "reservation-stage0"),
                deep_field_keys=_DEEP_ICP_FIELDS,
            )
            cycle, outcomes, _exa, _sumble = await _drive_cycle(
                conn,
                cycle_index=91,
                tmp_path=tmp_path,
                fixture=fixture,
                bundle_cost_dollars=RECORDED_BUNDLE_COST_DOLLARS,
            )
            _assert_cycle(cycle, outcomes)

            # The defect only bites when the real plan outgrows the alias-count estimate, so the
            # pin asserts that it does. Otherwise this cycle could pass on a profile that happens
            # to fit two bundles and guard nothing.
            for slug, outcome in sorted(outcomes.items()):
                bundles = int(
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT count(DISTINCT operation.operation_ref)
                                FROM entity_research_provider_operation operation
                                JOIN entity_research_provider_observation observation
                                  ON observation.provider_operation_ref=operation.operation_ref
                                JOIN entity_research_tool_request request_row
                                  ON request_row.tool_request_id=observation.tool_request_id
                                WHERE request_row.job_id=:job_id
                                  AND operation.source_key=:source_key
                                """
                            ),
                            {"job_id": outcome.job_id, "source_key": EXA_DEEP_SOURCE_KEY},
                        )
                    ).scalar_one()
                )
                assert bundles > _ALIAS_ONLY_BUNDLE_ESTIMATE, (
                    slug,
                    bundles,
                    _ALIAS_ONLY_BUNDLE_ESTIMATE,
                )

    run_async(scenario())


def test_five_accounts_settle_three_consecutive_times(tmp_path: Path) -> None:
    """Three full green cycles in one session, with no manual state repair between them."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=FsStorage(tmp_path / "harness-stage0"),
                deep_field_keys=_DEEP_ICP_FIELDS,
            )
            seen: list[frozenset[UUID]] = []
            predecessor: Any = None
            for index in range(1, CYCLES + 1):
                cycle, outcomes, exa, sumble = await _drive_cycle(
                    conn,
                    cycle_index=index,
                    tmp_path=tmp_path,
                    fixture=fixture,
                    predecessor_id=predecessor,
                )
                predecessor = cycle.directive_id
                _assert_cycle(cycle, outcomes)
                assert exa.corrupted_field_keys, "the truncating transport never fired"
                assert sumble.calls, "the Sumble transport was never reached"
                seen.append(frozenset(cycle.account_ids))
            # Three genuinely separate launches, not one run asserted three times.
            assert len({tuple(sorted(value)) for value in seen}) == CYCLES

    run_async(scenario())
