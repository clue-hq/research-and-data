"""An account the committee provider's index cannot match settles; it does not kill the job.

Live run ``dc86340f`` (2026-08-20 21:36:47 IST, "Greater Chicago Specialty Physicians LLC"):
``discover_buying_committee`` composed correctly — the buying-unit scope fix from ``8f6af4d5`` had
landed and input validation passed — then died inside committee input resolution with a raw

    SumbleCommitteePreparationError: Sumble organization snapshot has no exact matched organization
    -> execution_failed -> job requeued (worker_error:SumbleCommitteePreparationError)

Greater Chicago is a small Chicago physician group; Sumble's organization index simply has no exact
match for it. That is a fact about the provider's data, not a job-integrity violation — the same
species as the provider 402 that already folds terminally and lets an account settle with an honest
committee gap (proven live the same night: Specialdocs and HealthScribe both reached
``terminal/needs_review`` after a 402).

The ratified rule (``cd15398d``, ``2030de45``, ``b60824d4``): **model-input and world-fact failures
refuse recoverably; money and truth failures suspend.** This module pins the world-fact half for
the committee input path — the refusal is recoverable, the axis reaches a real terminal
disposition without a fabricated provider attempt, coverage and finalization close on it, and the
authority/integrity siblings on the very same path still suspend.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
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
from clue_agents.entity_research_contracts import EntityResearchAgentResult
from clue_agents.entity_research_runtime import (
    _ACTIVE_TOOL_EXECUTION,
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
)
from clue_api.account_entity_research import (
    AccountResearchExecutionGuard,
    AccountResearchFinalizationEngine,
    AccountResearchStateStore,
    committee_axis_unavailable_reasons,
    committee_axis_unavailable_source_keys,
    read_account_research_execution_completeness,
)
from clue_api.account_entity_research_composition import (
    AccountResearchDefinitionResolver,
    StaticAccountResearchProviderActions,
)
from clue_api.deep import DbAccountRunIO, deep_account_run_id
from clue_api.entity_research_runtime_wiring import DbEntityResearchAgentJournal
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    EntityResearchProviderCausationStore,
    EntityResearchResultStore,
    EntityResearchToolRequestStore,
    ExternalResearchResultLineageReader,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
)
from clue_api.sumble_account_gaps import SumbleAccountGapCoordinator, SumbleAccountGapStarter
from clue_api.sumble_committee_inputs import DurableSumbleCommitteeInputResolver
from clue_api.sumble_committee_preparation import (
    COMMITTEE_PROVIDER_IDENTITY_ABSENT,
    COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,
    SumbleCommitteePreparationError,
    SumbleCommitteeProviderIdentityUnavailable,
)
from clue_api.sumble_entity_research_tools import SumbleCommitteeSemanticResearchAction
from clue_api.trial.account_deep_fixture import (
    DEEP_FIELD_KEYS,
    seed_insight_health_account_deep_fixture,
)
from clue_api.trial.discovery_fixture import PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_config import Settings
from clue_core import new_operation_id
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    ResearchFinalizationOutcome,
)
from clue_fleet import DbEntityResearchJobStore
from clue_fleet.entity_research import EntityResearchExecutionFence
from clue_research.durable import create_account_deep_launch
from clue_research.resolvers.sumble import (
    ORGANIZATIONS_SOURCE_KEY,
    SumbleClient,
    SumbleCreditBudget,
)
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from clue_storage import FsStorage
from tests.agents.test_entity_research_runtime_r3 import Checkpointers
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.api.test_account_entity_research_fresh_skip_db import (
    _COMMITTEE_QUESTION,
    _HIRING,
    _MOVES,
    _PAIN,
    _launch_p2_job,
    _seed_p1_research,
)
from tests.api.test_account_entity_research_r5_db import (
    _FixtureAccountProviders,
    _FixtureLineageReader,
    _Models,
)
from tests.api.test_committee_scope_engine_composition_db import _Seed, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    rollback_conn,
)
from tests.profiling.conftest import (
    migrated_db as migrated_db,
)
from tests.profiling.conftest import (
    require_profiling_db as require_profiling_db,
)
from tests.stage0.conftest import rollback_conn as stage0_rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

#: A true Sumble no-match, verbatim in shape from ``tests/fixtures/clue_trial/sumble`` — zero
#: identified rows and ``matched_count: 0``, which is what the provider returns for an
#: organization it has never indexed. (Not the same as ``matched_count >= 1`` with no identifiable
#: row: that is provider/schema drift over a *charged* match and still raises, as it must.)
_UNMATCHED_ORGANIZATIONS = {
    "id": "greater-chicago-org-request",
    "credits_used": 0,
    "credits_remaining": 1000,
    "organizations": [
        {
            "input": {"url": "greater-chicago-specialty.example"},
            "attributes": {},
            "entities": [],
        }
    ],
    "matched_count": 0,
    "total": 0,
}


# --- 1. the world fact, on the real durable chain ------------------------------------------------


class _UnmatchedSumbleHttp:
    """Sumble, answering honestly that it has never heard of this organization."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        del kwargs
        self.calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("/organizations"):
            return dict(_UNMATCHED_ORGANIZATIONS)
        raise AssertionError(f"no dependent Sumble call may follow a no-match: {url}")


def test_an_unmatched_organization_is_a_world_fact_refusal_not_an_authority_breach(
    tmp_path: Path,
) -> None:
    """RED before the fix: the resolver raised the bare ``SumbleCommitteePreparationError``.

    The whole production chain is real — sealed discovery, the human-confirmed directive, the
    launch, the directive-pinned account run and a paid Sumble account-gap operation whose
    ``/organizations`` response is a genuine no-match. Only the provider's answer is a double, and
    it is the answer Greater Chicago actually got.
    """

    async def scenario() -> None:
        async with stage0_rollback_conn(seed=False) as conn:
            storage = FsStorage(tmp_path / "unmatched-artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn, pages=_pages(), storage=storage
            )
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                product_id=PRODUCT_ID,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(DEEP_FIELD_KEYS[0], *DEEP_FIELD_KEYS[2:]),
            )
            pin = account_spec.research_directive
            assert pin is not None
            await create_account_deep_launch(
                conn,
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                directive_id=pin.directive_id,
                account_entity_ids=(fixture.selected_account_id,),
                approved_budget_cap_cents=Decimal("300"),
                expected_estimated_cost_cents=Decimal("300"),
                created_by="human:unmatched-organization",
                source_operation_id=new_operation_id(),
                source_action_ref="turn:unmatched-organization-launch",
            )
            account_run_id = deep_account_run_id(
                fixture.project_run_id, fixture.selected_account_id
            )
            same_connection = conn_session_factory(conn)
            await DbAccountRunIO(session_factory=same_connection).ensure(
                account_run_id=account_run_id,
                project_run_id=fixture.project_run_id,
                entity_id=fixture.selected_account_id,
                tier="high",
                research_directive=pin,
                budget_cap_cents=Decimal("300"),
            )

            http = _UnmatchedSumbleHttp()

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            starter = SumbleAccountGapStarter(
                coordinator=SumbleAccountGapCoordinator(
                    api_key=SecretStr("fixture"),
                    storage=storage,
                    cents_per_credit=Decimal("0.5"),
                    conn_factory=same_connection,
                    client_factory=client_factory,
                ),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            await starter.start(
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                account_id=fixture.selected_account_id,
                field_expected_value_credits={DEEP_FIELD_KEYS[0]: Decimal("5")},
                provider_credit_cap=5,
                allow_unbounded_tech=False,
            )
            # The account's only organization evidence is the honest no-match, and nothing
            # dependent was ever asked for.
            assert http.calls == [ORGANIZATIONS_SOURCE_KEY.split("_")[-1]]

            resolver = DurableSumbleCommitteeInputResolver(
                settings=Settings(_env_file=None, sumble_cents_per_credit=Decimal("0.5")),
                storage=storage,
                conn_factory=same_connection,
            )
            with pytest.raises(SumbleCommitteeProviderIdentityUnavailable) as refused:
                await resolver.resolve(
                    account_entity_id=fixture.selected_account_id,
                    account_run_id=account_run_id,
                    project_run_id=fixture.project_run_id,
                    workspace_id=WORKSPACE_ID,
                    tier="high",
                )
            assert refused.value.code == COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED
            assert "no exact matched organization" in refused.value.detail
            # It is still a preparation error for every historical caller (the DEEP-path preparer
            # keeps suspending on it), so nothing outside the M8D tool changes behaviour.
            assert isinstance(refused.value, SumbleCommitteePreparationError)

    run_async(scenario())


# --- 2. the M8D tool: refuse recoverably, record the terminal attempt ----------------------------


@dataclass(frozen=True, slots=True)
class _Context:
    authorization: EntityResearchJobAuthorization


@dataclass(frozen=True, slots=True)
class _Call:
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _Active:
    """The authority the committee action reads before it ever touches a provider."""

    context: _Context
    call: _Call


class _RaisingInputs:
    """Committee input resolution that fails exactly the way the live account's did."""

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.calls = 0

    async def resolve(self) -> Any:
        self.calls += 1
        raise self._error


def _committee_action(
    seed: _Seed, *, error: BaseException, conn: AsyncConnection
) -> SumbleCommitteeSemanticResearchAction:
    del seed

    async def same_connection() -> AsyncIterator[AsyncConnection]:
        yield conn

    return SumbleCommitteeSemanticResearchAction(
        inputs=cast(Any, _RaisingInputs(error)),
        eligibility=cast(Any, object()),
        coordinator=cast(Any, object()),
        storage=cast(Any, object()),
        conn_factory=asynccontextmanager(same_connection),
        gateway=cast(Any, object()),
        role_model="unused",
    )


async def _execute_committee(
    action: SumbleCommitteeSemanticResearchAction,
    *,
    seed: _Seed,
    arguments: dict[str, Any] | None = None,
) -> list[str]:
    """Run the action under a governed execution, refusing any provider callback."""

    provider_touches: list[str] = []

    async def before_dispatch(operation: Any) -> Any:
        provider_touches.append("before_dispatch")
        raise AssertionError("no provider dispatch may be reserved for an unbuyable committee")

    async def settle_terminal(operation: Any) -> Any:
        provider_touches.append("settle_terminal")
        raise AssertionError("there is no provider operation to settle")

    token = _ACTIVE_TOOL_EXECUTION.set(
        cast(
            Any,
            _Active(
                context=_Context(authorization=seed.authorization),
                call=_Call(arguments=arguments or {"source_keys": [PEOPLE_SOURCE_KEY]}),
            ),
        )
    )
    try:
        await action.execute(
            seed.committee_request,
            before_dispatch=before_dispatch,
            settle_terminal=settle_terminal,
        )
    finally:
        _ACTIVE_TOOL_EXECUTION.reset(token)
    return provider_touches


async def _unavailable_rows(conn: AsyncConnection, *, job_id: UUID) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in (
            (
                await conn.execute(
                    text(
                        "SELECT tool_request_id, research_run_id, job_id, workspace_id, "
                        "account_entity_id, source_keys, reason_code, detail FROM "
                        "entity_research_account_committee_unavailable WHERE job_id=:job_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
    ]


def test_the_committee_tool_refuses_recoverably_and_records_a_zero_cost_terminal_attempt() -> None:
    """RED before the fix: the world-fact error escaped raw and the drive died.

    Nothing is reserved, dispatched or charged — the refusal happens before the first provider
    callback — so the durable record is the only honest evidence that the axis was attempted.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)
            action = _committee_action(
                seed,
                conn=conn,
                error=SumbleCommitteeProviderIdentityUnavailable(
                    COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,
                    "Sumble organization snapshot has no exact matched organization",
                ),
            )

            with pytest.raises(EntityResearchGovernedRejection) as refused:
                await _execute_committee(action, seed=seed)

            assert refused.value.code == COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED
            rendered = json.loads(refused.value.render())
            assert rendered["recoverable"] is True
            # The loop rule: the refusal names the next call, and it is never this one again.
            assert "assess_account_coverage" in rendered["detail"]
            assert "Do not call discover_buying_committee again" in rendered["detail"]

            rows = await _unavailable_rows(conn, job_id=seed.job_id)
            assert len(rows) == 1
            assert rows[0]["tool_request_id"] == seed.committee_request.tool_call_id
            assert rows[0]["research_run_id"] == seed.research_run_id
            assert rows[0]["workspace_id"] == seed.workspace_id
            assert rows[0]["account_entity_id"] == seed.account_id
            assert list(rows[0]["source_keys"]) == [PEOPLE_SOURCE_KEY]
            assert rows[0]["reason_code"] == COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED

            # Replay of the exact same tool call re-records nothing (checkpoint resume).
            with pytest.raises(EntityResearchGovernedRejection):
                await _execute_committee(action, seed=seed)
            assert len(await _unavailable_rows(conn, job_id=seed.job_id)) == 1

    run_async(scenario())


def test_the_absent_organization_identity_refuses_under_its_own_reason_code() -> None:
    """The sibling world fact — no organization response exists for the account at all."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)
            action = _committee_action(
                seed,
                conn=conn,
                error=SumbleCommitteeProviderIdentityUnavailable(
                    COMMITTEE_PROVIDER_IDENTITY_ABSENT,
                    "ready Sumble organization identity is absent from account and "
                    "sealed-discovery enrichment",
                ),
            )

            with pytest.raises(EntityResearchGovernedRejection) as refused:
                await _execute_committee(action, seed=seed)

            assert refused.value.code == COMMITTEE_PROVIDER_IDENTITY_ABSENT
            rows = await _unavailable_rows(conn, job_id=seed.job_id)
            assert [row["reason_code"] for row in rows] == [COMMITTEE_PROVIDER_IDENTITY_ABSENT]

    run_async(scenario())


def test_an_authority_failure_on_the_same_path_still_suspends_the_job() -> None:
    """The money/truth half of the ruling: only the world-fact species is converted.

    Non-vacuous by construction — this is the *same* call, the *same* code path and the *same*
    base exception class as the case above; only the species differs.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)
            action = _committee_action(
                seed,
                conn=conn,
                error=SumbleCommitteePreparationError(
                    "R6 account job authorization differs from its pinned directive"
                ),
            )

            with pytest.raises(SumbleCommitteePreparationError) as suspended:
                await _execute_committee(action, seed=seed)

            assert not isinstance(suspended.value, EntityResearchGovernedRejection)
            assert not isinstance(suspended.value, SumbleCommitteeProviderIdentityUnavailable)
            # An authority breach is not an attempt: nothing is written off as terminal.
            assert await _unavailable_rows(conn, job_id=seed.job_id) == []

    run_async(scenario())


# --- 3. the axis reaches a terminal disposition --------------------------------------------------


def test_the_recorded_attempt_makes_the_committee_axis_terminal_for_coverage() -> None:
    """RED before the fix: the committee axis stayed outstanding forever, so nothing could close."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)
            before = await read_account_research_execution_completeness(
                conn, authorization=seed.authorization
            )
            assert before.outstanding_committee_source_keys == (PEOPLE_SOURCE_KEY,)
            assert before.terminal_committee_source_keys == ()

            action = _committee_action(
                seed,
                conn=conn,
                error=SumbleCommitteeProviderIdentityUnavailable(
                    COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,
                    "Sumble organization snapshot has no exact matched organization",
                ),
            )
            with pytest.raises(EntityResearchGovernedRejection):
                await _execute_committee(action, seed=seed)

            after = await read_account_research_execution_completeness(
                conn, authorization=seed.authorization
            )
            assert after.outstanding_committee_source_keys == ()
            assert after.terminal_committee_source_keys == (PEOPLE_SOURCE_KEY,)
            assert "committee@" not in after.outstanding_summary()
            # The field axis is untouched: a committee refusal settles no field/source pair.
            assert after.terminal_field_source_pairs == before.terminal_field_source_pairs
            assert after.outstanding_field_source_pairs == before.outstanding_field_source_pairs

            assert await committee_axis_unavailable_source_keys(conn, job_id=seed.job_id) == {
                PEOPLE_SOURCE_KEY
            }
            assert await committee_axis_unavailable_reasons(conn, job_id=seed.job_id) == (
                COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,
            )

    run_async(scenario())


def test_the_coverage_ledger_says_which_world_fact_closed_the_committee_axis() -> None:
    """``committee_not_researched`` is true but mute; the ledger names the provider's own answer."""

    unmatched = AccountResearchStateStore._committee_coverage_status(  # noqa: SLF001
        result_count=0,
        member_count=0,
        scope_count=0,
        ambiguous_count=0,
        confirmed_empty_count=0,
        provider_unavailable_reasons=(COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,),
    )
    assert unmatched == ("needs_review", (COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,))
    # Nothing else moves: an unattempted committee still reports the original flag.
    assert AccountResearchStateStore._committee_coverage_status(  # noqa: SLF001
        result_count=0,
        member_count=0,
        scope_count=0,
        ambiguous_count=0,
        confirmed_empty_count=0,
    ) == ("needs_review", ("committee_not_researched",))


# --- 4. the account actually settles -------------------------------------------------------------


class _SettlingModel(BaseChatModel):
    """Read state, attempt the committee, accept the refusal, assess, finalize."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    account_id: UUID
    refusals: list[dict[str, Any]] = []
    _coverage: dict[str, Any] | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "committee-unmatched-scripted-account-agent"

    @property
    def coverage(self) -> dict[str, Any]:
        assert self._coverage is not None
        return self._coverage

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
            return cast(dict[str, Any], json.loads(content))
        if isinstance(content, dict):
            return cast(dict[str, Any], content)
        raise AssertionError(f"unexpected tool payload: {type(content)!r}")

    def _call(self, name: str, args: dict[str, Any]) -> ChatResult:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[{"name": name, "args": args, "id": f"cu-{name}-{len(args)}"}],
                    )
                )
            ]
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
        if last.name == "read_account_research_state":
            return self._call(
                "discover_buying_committee",
                {
                    "field_keys": [],
                    "source_keys": [PEOPLE_SOURCE_KEY],
                    "questions": [_COMMITTEE_QUESTION],
                },
            )
        if last.name == "discover_buying_committee":
            assert last.status == "error", "the committee call must refuse, never succeed"
            self.refusals.append(payload)
            return self._call(
                "assess_account_coverage",
                {
                    "result_refs": [],
                    "assessment_note": (
                        "The provider has no organization for this account; the committee is an "
                        "honest gap."
                    ),
                },
            )
        if last.name == "assess_account_coverage":
            assert last.status != "error", json.dumps(payload, sort_keys=True)
            self._coverage = payload
            return self._call(
                "finalize_account_research",
                {
                    "coverage_ledger_ref": payload["coverage_ledger_ref"],
                    "requested_outcome": "needs_review",
                },
            )
        return self._call("ResearchFinalizationProposal", payload)


def test_an_account_with_no_provider_organization_settles_with_an_honest_empty_committee(
    tmp_path: Path,
) -> None:
    """The whole point: the job survives the refusal and reaches a durable terminal receipt.

    RED before the fix, twice over: the raw error killed the drive at the committee call, and even
    if it had not, the committee axis could never go terminal, so ``assess_account_coverage``
    refused forever ("every authorized field/source and committee attempt is terminal").
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn, stale_culture=False)
            admitted = (_PAIN, _MOVES, _HIRING)
            envelope, connection = await _launch_p2_job(conn, fixture=fixture, admitted=admitted)
            authorization = envelope.jobs[0].authorization
            storage = FsStorage(tmp_path / f"cu-artifacts-{uuid4().hex[:8]}")
            jobs = DbEntityResearchJobStore(conn_factory=connection)
            stored = await jobs.get_job(authorization.job_id)
            assert stored is not None
            live_job = stored.model_copy(
                update={"active_worker_id": "cu-worker", "lease_generation": 1}
            )
            fence = EntityResearchExecutionFence(
                task_id=uuid4(), worker_id="cu-worker", lease_generation=1, task_attempt=1
            )
            committee_action = SumbleCommitteeSemanticResearchAction(
                inputs=cast(
                    Any,
                    _RaisingInputs(
                        SumbleCommitteeProviderIdentityUnavailable(
                            COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,
                            "Sumble organization snapshot has no exact matched organization",
                        )
                    ),
                ),
                eligibility=cast(Any, object()),
                coordinator=cast(Any, object()),
                storage=storage,
                conn_factory=connection,
                gateway=cast(Any, object()),
                role_model="unused",
            )
            lineage = _FixtureLineageReader()
            # Bound but unreachable: all three account fields are born complete from P1's fresh
            # neutral claims, so no field research is attempted. Only the committee is.
            unused = _FixtureAccountProviders(
                storage=storage,
                conn_factory=connection,
                contacts=(uuid4(), uuid4()),
                lineage=lineage,
            )
            resolver = AccountResearchDefinitionResolver(
                tools=GovernedEntityResearchToolFactory(
                    requests=EntityResearchToolRequestStore(
                        conn_factory=connection, storage=storage
                    ),
                    causation=EntityResearchProviderCausationStore(conn_factory=connection),
                    results=EntityResearchResultStore(
                        storage=storage,
                        conn_factory=connection,
                        lineage_readers={
                            ExternalResearchResultLineageReader.provider_kind: (
                                ExternalResearchResultLineageReader(conn_factory=connection)
                            ),
                            lineage.provider_kind: lineage,
                        },
                    ),
                ),
                state=AccountResearchStateStore(conn_factory=connection),
                provider_actions=StaticAccountResearchProviderActions(
                    {
                        authorization.job_id: {
                            "research_account_deep": ProviderActionBinding(
                                action=unused, version=1
                            ),
                            "enrich_account": ProviderActionBinding(action=unused, version=1),
                            "discover_buying_committee": ProviderActionBinding(
                                action=committee_action, version=1
                            ),
                        }
                    }
                ),
                model_policy=ModelPolicy(
                    model_id="cu-model",
                    timeout_s=10,
                    max_retries=0,
                    max_output_tokens=4096,
                    temperature=0,
                ),
                conn_factory=connection,
            )
            definition = await resolver.resolve(job=live_job, fence=fence)
            model = _SettlingModel(account_id=fixture.account_id, refusals=[])
            journal = DbEntityResearchAgentJournal(conn_factory=connection)
            outcome = await EntityResearchAgentRuntime(
                factory=EntityResearchAgentFactory(
                    models=_Models(model),
                    journal=journal,
                    guard=AccountResearchExecutionGuard(conn_factory=connection),
                ),
                checkpointers=Checkpointers(),
                journal=journal,
                finalizer=AccountResearchFinalizationEngine(conn_factory=connection),
            ).run(definition=definition)

            # The refusal reached the model as a recoverable governed rejection, not a crash.
            assert len(model.refusals) == 1
            assert model.refusals[0]["code"] == COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED
            assert model.refusals[0]["recoverable"] is True

            # And the account closed: honest empty committee, named world fact, durable receipt.
            assert isinstance(outcome, EntityResearchAgentResult)
            assert outcome.finalization_receipt is not None
            assert (
                outcome.finalization_receipt.proposal.outcome
                is ResearchFinalizationOutcome.NEEDS_REVIEW
            )
            assert outcome.finalization_receipt.verification.all_passed()
            coverage = model.coverage
            assert coverage["committee_status"] == "needs_review"
            assert coverage["committee_member_ids"] == []
            assert coverage["committee_result_refs"] == []
            assert COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED in coverage["review_flags"]
            assert set(coverage["completed_field_keys"]) >= set(admitted)

            completeness = await read_account_research_execution_completeness(
                conn, authorization=authorization
            )
            assert completeness.complete
            assert completeness.terminal_committee_source_keys == (PEOPLE_SOURCE_KEY,)
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_account_review_item "
                        "WHERE job_id=:job_id AND reason_code=:reason"
                    ),
                    {
                        "job_id": authorization.job_id,
                        "reason": COMMITTEE_PROVIDER_ORGANIZATION_UNMATCHED,
                    },
                )
            ).scalar_one() == 1

    run_async(scenario())
