"""FI-2 §6.1 — the account runtime's fresh-skip, on the canonical two-project fixture.

P1 researched acme under one ICP; P2 now launches its own research on the same account. What P2
must *not* re-buy is the account's world-facts (``project_neutral`` fields whose current claim is
fresh, evidence-backed and conflict-free): those are born complete, cite P1's claims in the
coverage ledger, and reach a clean finalization without a result of their own. What P2 must always
research itself is everything else — a stale fact, a conflicted fact, and every
``project_relative`` field, whose fresh value is *P1's* answer and never P2's.

The species is always read through the registry (``core.resolve_research_scope``), never
hardcoded, and every claim read goes through the canonical merge under ``WorkspaceScope`` — never
a raw ``claim.workspace_id`` filter.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
from langchain_core.tools import ToolException
from pydantic import ConfigDict, PrivateAttr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.account_entity_research import (
    AccountResearchStateProjection,
    AssessAccountCoverageInput,
)
from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import EntityResearchAgentResult, canonical_sha256
from clue_agents.entity_research_runtime import (
    _ACTIVE_TOOL_EXECUTION,
    ActiveEntityResearchToolExecution,
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
    current_entity_research_tool_execution,
)
from clue_api.account_entity_research import (
    AccountResearchAuthorityError,
    AccountResearchExecutionGuard,
    AccountResearchFinalizationEngine,
    AccountResearchStateStore,
    account_engine_tool_bindings,
)
from clue_api.account_entity_research_composition import (
    AccountResearchDefinitionResolver,
    StaticAccountResearchProviderActions,
    account_research_profile_sha256,
)
from clue_api.entity_research_runtime_wiring import DbEntityResearchAgentJournal
from clue_api.entity_research_tools import (
    EntityResearchProviderCausationStore,
    EntityResearchResultStore,
    EntityResearchToolRequestStore,
    ExternalResearchResultLineageReader,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
    ProviderOperationReservation,
    ProviderResearchProjectionDraft,
    semantic_validation_error,
)
from clue_core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    FieldKey,
    PassKind,
    ResearchMode,
    ResearchScope,
    ReuseScope,
    RunId,
    serialize_value_json,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    EntityResearchSelection,
    FieldSourceAuthority,
    ResearchFinalizationOutcome,
    ResearchRunKind,
    ResearchRunLifecycleContract,
)
from clue_fleet import DbEntityResearchJobStore, EntityResearchRunEnvelope
from clue_fleet.entity_research import EntityResearchExecutionFence
from clue_research.claimstore import insert_claim, record_run_lineage, register_field
from clue_research.durable.discovery import capture_discovery_artifact
from clue_research.identity import insert_account_entity
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from clue_spine import create_brand, create_product
from clue_storage import FsStorage
from tests._workspace import seed_workspace
from tests.agents.test_entity_research_runtime_r3 import Checkpointers
from tests.api.test_account_entity_research_r5_db import (
    _FixtureAccountProviders,
    _FixtureLineageReader,
    _Models,
    _NestedConnFactory,
)
from tests.db.conftest import run_async
from tests.fleet.entity_research_r2_helpers import run_envelope
from tests.profiling.conftest import (
    migrated_db as migrated_db,
)
from tests.profiling.conftest import (
    require_profiling_db as require_profiling_db,
)
from tests.profiling.conftest import (
    rollback_conn,
)

# Core-pack fields, with their ratified species (FI-2 §5.2) and TTLs:
_PAIN = "account.operational_pain"  # neutral, 90d
_MOVES = "account.strategic_moves"  # neutral, 90d
_CULTURE = "account.resonance.culture"  # neutral, 60d
_HIRING = "account.hiring_velocity_eng"  # neutral, 30d
_FIT = "account.scoring.fit"  # RELATIVE — definitionally per ICP/product
_FUNDING = "account.recent_funding"  # neutral, 90d
_QUESTION = "Where is administrative work creating avoidable burden?"
_COMMITTEE_QUESTION = "Who participates in this product buying decision at the same office?"


@dataclass(frozen=True, slots=True)
class _Fixture:
    workspace_id: str
    account_id: UUID
    product_id: str
    p1_project_id: str
    p1_claim_ids: dict[str, UUID]


async def _p1_claim(
    conn: AsyncConnection,
    *,
    fixture_workspace: str,
    account_id: UUID,
    field_key: str,
    value: Any,
    run_id: RunId,
    age: timedelta,
    evidence_span: str | None = "P1 evidence: the account's own public record.",
    source_tier: int = 1,
    source_key: str = "sumble_jobs",
) -> UUID:
    """One claim P1's research already wrote about this account."""

    collected_at = datetime.now(UTC) - age
    claim = Claim(
        entity_id=EntityId(account_id),
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=value,
        source_url="https://example.test/p1-evidence",
        source_key=source_key,
        source_tier=cast(Any, source_tier),
        extraction_method=(
            ExtractionMethod.LLM_SYNTHESIS if source_tier == 4 else ExtractionMethod.API
        ),
        evidence_span=evidence_span,
        confidence=cast(Any, 0.9),
        observed_at=collected_at,
        collected_at=collected_at,
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=fixture_workspace,
    )
    return UUID(str(await insert_claim(conn, claim)))


async def _seed_p1_research(
    conn: AsyncConnection,
    *,
    conflicted_hiring: bool = False,
    stale_culture: bool = True,
) -> _Fixture:
    """P1 discovers acme under ICP-A and researches it; P2's job arrives later."""

    workspace_id = await seed_workspace(conn, "fi2-s3-t2")
    await load_client_knowledge_pack(conn)
    await seed_source_manifests(conn)
    brand = await create_brand(conn, workspace_id=workspace_id, name=f"Brand {uuid4().hex[:6]}")
    product = await create_product(
        conn,
        brand_id=brand.brand_id,
        workspace_id=workspace_id,
        name=f"Product {uuid4().hex[:6]}",
    )
    account_id = UUID(
        str(
            await insert_account_entity(
                conn,
                canonical_name="Acme Referral Health",
                primary_domain=f"acme-{uuid4().hex[:8]}.test",
                workspace_id=workspace_id,
            )
        )
    )
    p1_project_id = f"project-one-{uuid4().hex[:8]}"
    p1_run = RunId(uuid4())
    await record_run_lineage(
        conn,
        run_id=UUID(str(p1_run)),
        workspace_id=workspace_id,
        project_id=p1_project_id,
        kind="entity_research",
    )
    claims: dict[str, UUID] = {}
    claims[_PAIN] = await _p1_claim(
        conn,
        fixture_workspace=workspace_id,
        account_id=account_id,
        field_key=_PAIN,
        value="Referral intake depends on repeated manual fax reconciliation.",
        run_id=p1_run,
        age=timedelta(days=3),
    )
    claims[_MOVES] = await _p1_claim(
        conn,
        fixture_workspace=workspace_id,
        account_id=account_id,
        field_key=_MOVES,
        value="The practice is expanding its centralized referral program.",
        run_id=p1_run,
        age=timedelta(days=5),
    )
    if stale_culture:
        # 200d against a 60d TTL: known, but past its shelf life — P2 refreshes it for everyone.
        claims[_CULTURE] = await _p1_claim(
            conn,
            fixture_workspace=workspace_id,
            account_id=account_id,
            field_key=_CULTURE,
            value="Clinicians describe a pragmatic, checklist-driven culture.",
            run_id=p1_run,
            age=timedelta(days=200),
        )
    claims[_HIRING] = await _p1_claim(
        conn,
        fixture_workspace=workspace_id,
        account_id=account_id,
        field_key=_HIRING,
        value=4,
        run_id=p1_run,
        age=timedelta(days=2),
    )
    if conflicted_hiring:
        # A second authoritative source disagreeing is an open conflict: never born complete.
        claims[f"{_HIRING}:contender"] = await _p1_claim(
            conn,
            fixture_workspace=workspace_id,
            account_id=account_id,
            field_key=_HIRING,
            value=11,
            run_id=p1_run,
            age=timedelta(days=1),
            source_key="crm_import",
        )
    claims[_FIT] = await _p1_claim(
        conn,
        fixture_workspace=workspace_id,
        account_id=account_id,
        field_key=_FIT,
        value={"value": 0.82},
        run_id=p1_run,
        age=timedelta(days=1),
    )
    return _Fixture(
        workspace_id=workspace_id,
        account_id=account_id,
        product_id=product.product_id,
        p1_project_id=p1_project_id,
        p1_claim_ids=claims,
    )


def _p2_envelope(
    *,
    fixture: _Fixture,
    admitted: Sequence[str],
    profile_sha256: str,
) -> EntityResearchRunEnvelope:
    """A second project's account-research run over the account P1 already researched."""

    base = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
    original = base.lifecycle.selection
    selection = EntityResearchSelection.model_validate(
        original.model_copy(
            update={
                "workspace_id": fixture.workspace_id,
                "project_id": f"project-two-{uuid4().hex[:8]}",
                "product_id": fixture.product_id,
                "subjects": (
                    original.subjects[0].model_copy(
                        update={"subject_entity_id": fixture.account_id}
                    ),
                ),
                "admitted_field_keys": tuple(admitted),
                "admitted_source_keys": ("exa_deep", "sumble_jobs", "sumble_people"),
                "field_source_authority": tuple(
                    FieldSourceAuthority(field_key=key, source_keys=("sumble_jobs", "exa_deep"))
                    for key in admitted
                ),
                "committee_source_keys": ("sumble_people",),
                "research_questions": (_QUESTION, _COMMITTEE_QUESTION),
            }
        ).model_dump(mode="python")
    )
    lifecycle = ResearchRunLifecycleContract.model_validate(
        base.lifecycle.model_copy(update={"selection": selection}).model_dump(mode="python")
    )
    original_job = base.jobs[0]
    authorization = EntityResearchJobAuthorization.model_validate(
        original_job.authorization.model_copy(
            update={
                "subject_entity_id": fixture.account_id,
                "workspace_id": selection.workspace_id,
                "project_id": selection.project_id,
                "product_id": selection.product_id,
                "project_run_id": selection.project_run_id,
                "selection": selection,
                "agent_profile_ref": "agent-profile:account-research:v2",
                "agent_profile_sha256": profile_sha256,
            }
        ).model_dump(mode="python")
    )
    return EntityResearchRunEnvelope.model_validate(
        base.model_copy(
            update={
                "lifecycle": lifecycle,
                "jobs": (
                    original_job.model_copy(
                        update={"authorization": authorization, "budget_cap_cents": Decimal("10")}
                    ),
                ),
                "budget_cap_cents": Decimal("10"),
            }
        ).model_dump(mode="python")
    )


@dataclass(frozen=True, slots=True)
class _ContextOnly:
    """The only part of a runtime context ``state`` reads."""

    authorization: EntityResearchJobAuthorization


@dataclass(frozen=True, slots=True)
class _AuthorityOnly:
    """The only part of a governed execution ``state`` reads: its context's job authorization."""

    context: _ContextOnly


def _active(authorization: EntityResearchJobAuthorization) -> ActiveEntityResearchToolExecution:
    """A first-plan read outside a model turn: ``state(active)`` needs the authorization, no more.

    The full-runtime tests below exercise the real ``ActiveEntityResearchToolExecution``; these
    state-level cases only need the authority the engine hands a tool.
    """

    return cast(
        ActiveEntityResearchToolExecution,
        _AuthorityOnly(context=_ContextOnly(authorization=authorization)),
    )


async def _launch_p2_job(
    conn: AsyncConnection,
    *,
    fixture: _Fixture,
    admitted: Sequence[str],
) -> tuple[EntityResearchRunEnvelope, _NestedConnFactory]:
    connection = _NestedConnFactory(conn)
    envelope = _p2_envelope(
        fixture=fixture,
        admitted=admitted,
        profile_sha256=account_research_profile_sha256(),
    )
    await DbEntityResearchJobStore(conn_factory=connection).launch(envelope)
    return envelope, connection


def test_fi2_61_p2_is_born_complete_only_on_p1s_fresh_neutral_facts(
    require_profiling_db: None,
) -> None:
    """The first plan: fresh neutral facts are complete before a cent is spent; nothing else is."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn, conflicted_hiring=True)
            admitted = (_PAIN, _MOVES, _CULTURE, _HIRING, _FIT)
            envelope, connection = await _launch_p2_job(conn, fixture=fixture, admitted=admitted)
            authorization = envelope.jobs[0].authorization
            store = AccountResearchStateStore(conn_factory=connection)

            state = await store.state(_active(authorization))

            assert isinstance(state, AccountResearchStateProjection)
            # Fresh + evidence-backed + conflict-free + neutral ⇒ born complete.
            assert set(state.completed_field_keys) == {_PAIN, _MOVES}
            # Stale, conflicted, and project-relative are all P2's own work.
            assert set(state.unresolved_field_keys) == {_CULTURE, _HIRING, _FIT}
            existing = {item.field_key: item for item in state.existing_claims}
            assert set(existing) == set(admitted)
            assert existing[_PAIN].claim_ref == f"claim:{fixture.p1_claim_ids[_PAIN]}"
            assert existing[_PAIN].research_scope == "project_neutral"
            assert existing[_CULTURE].freshness_state == "stale"
            assert existing[_HIRING].conflict is True
            assert existing[_FIT].research_scope == "project_relative"
            # A fresh relative claim is P1's answer, never P2's — species, not freshness, decides.
            assert existing[_FIT].freshness_state == "fresh"
            assert existing[_FIT].born_complete is False

    run_async(scenario())


def test_fi2_61_missing_evidence_or_another_workspace_is_never_born_complete(
    require_profiling_db: None,
) -> None:
    """Two negative cases the skip must not swallow: no evidence span, and another tenant's fact."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn, stale_culture=False)
            span_less_run = RunId(uuid4())
            await record_run_lineage(
                conn,
                run_id=UUID(str(span_less_run)),
                workspace_id=fixture.workspace_id,
                project_id=fixture.p1_project_id,
                kind="entity_research",
            )
            await _p1_claim(
                conn,
                fixture_workspace=fixture.workspace_id,
                account_id=fixture.account_id,
                field_key=_CULTURE,
                value="Culture asserted without a span.",
                run_id=span_less_run,
                age=timedelta(days=1),
                evidence_span=None,
            )
            other_workspace = await seed_workspace(conn, "fi2-s3-t2-other")
            await _p1_claim(
                conn,
                fixture_workspace=other_workspace,
                account_id=fixture.account_id,
                field_key=_FUNDING,
                value={"amount_usd": 12_000_000, "round": "series-b"},
                run_id=span_less_run,
                age=timedelta(days=1),
            )
            admitted = (_PAIN, _CULTURE, _FUNDING)
            envelope, connection = await _launch_p2_job(conn, fixture=fixture, admitted=admitted)
            store = AccountResearchStateStore(conn_factory=connection)

            state = await store.state(_active(envelope.jobs[0].authorization))

            assert set(state.completed_field_keys) == {_PAIN}
            assert set(state.unresolved_field_keys) == {_CULTURE, _FUNDING}
            existing = {item.field_key: item for item in state.existing_claims}
            assert existing[_CULTURE].evidence_span is None
            # The other workspace's claim is invisible here: the merge is scoped, never leaked.
            assert _FUNDING not in existing

    run_async(scenario())


class _EmptyCommitteeProviders(_FixtureAccountProviders):
    """Committee provider that accepts a *claim* as its office evidence, as production does.

    ``SumbleCommitteeSemanticResearchAction._persist_scope`` admits ``claim:`` references that
    belong to the account itself, which is exactly what an all-born-complete job has to offer: it
    ran no provider call of its own, so its only durable account evidence is the claim already on
    file. The discovery is a grounded empty one — this fixture is about the account-field
    economics, not about committee membership.
    """

    async def _committee(
        self,
        *,
        request: Any,
        operation: ProviderOperationReservation,
        snapshot_ref: str,
        provider_request_id: str,
    ) -> tuple[ProviderResearchProjectionDraft, str, str]:
        del provider_request_id
        active = current_entity_research_tool_execution()
        scope = active.call.arguments["buying_unit_scope"]
        assert str(scope["evidence_refs"][0]).startswith("claim:")
        async with self._conn_factory() as conn:
            claim_id = UUID(str(scope["evidence_refs"][0]).removeprefix("claim:"))
            owned = (
                await conn.execute(
                    text("SELECT 1 FROM claim WHERE id=:id AND entity_id=:account_id"),
                    {"id": claim_id, "account_id": request.target_entity_id},
                )
            ).scalar_one_or_none()
            assert owned == 1
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_account_committee_scope
                        (scope_id, tool_request_id, research_run_id, job_id, workspace_id,
                         account_entity_id, scope_json, scope_sha256)
                    VALUES (:scope_id, :tool_request_id, :run_id, :job_id, :workspace_id,
                            :account_id, CAST(:scope_json AS jsonb), :scope_sha)
                    """
                ),
                {
                    "scope_id": UUID(str(scope["scope_id"])),
                    "tool_request_id": request.tool_call_id,
                    "run_id": request.research_run_id,
                    "job_id": request.job_id,
                    "workspace_id": operation.workspace_id,
                    "account_id": request.target_entity_id,
                    "scope_json": serialize_value_json(scope),
                    "scope_sha": canonical_sha256(scope),
                },
            )
            raw_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.workspace_id,
                content=json.dumps({"people": []}, sort_keys=True).encode(),
                media_type="application/json",
                source_key=operation.source_key,
            )
            normalized_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.workspace_id,
                content=json.dumps({"office": "Boston", "contacts": []}, sort_keys=True).encode(),
                media_type="application/json",
                source_key=operation.source_key,
            )
        return (
            ProviderResearchProjectionDraft(
                operation=operation,
                snapshot_ref=snapshot_ref,
                confirmed_empty_discovery=True,
            ),
            raw_key,
            normalized_key,
        )


class _ScriptedModel(BaseChatModel):
    """A test mind that reads state, runs exactly the planned calls, then assesses and finalizes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    plan: list[dict[str, Any]]
    #: Deliberately request the opposite finalization outcome from the one the coverage derives.
    #: The engine owns the outcome, so the proposal must carry the derived value regardless —
    #: the live GraphRecursionError loop started as a refusal of exactly this mismatch.
    request_wrong_outcome: bool = False
    _result_refs: list[str] = PrivateAttr(default_factory=list)
    _next: int = PrivateAttr(default=0)
    _observed_state: dict[str, Any] | None = PrivateAttr(default=None)
    _observed_coverage: dict[str, Any] | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "fi2-s3-t2-scripted-account-agent"

    @property
    def observed_state(self) -> dict[str, Any]:
        assert self._observed_state is not None
        return self._observed_state

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
            return cast(dict[str, Any], json.loads(content))
        if isinstance(content, dict):
            return cast(dict[str, Any], content)
        raise AssertionError(f"unexpected tool payload: {type(content)!r}")

    def _call(self, name: str, args: dict[str, Any]) -> ChatResult:
        message = AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": f"fi2-{name}-{self._next}"}],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

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
            self._observed_state = payload
        elif last.name == "assess_account_coverage":
            if last.status == "error":
                raise RuntimeError(
                    "script observed governed assessment refusal: "
                    + json.dumps(payload, sort_keys=True)
                )
            self._observed_coverage = payload
            derived_needs_review = (
                payload["unresolved_field_keys"]
                or payload["review_flags"]
                or payload["committee_status"] != "complete"
            )
            if self.request_wrong_outcome:
                outcome = "completed" if derived_needs_review else "needs_review"
            else:
                outcome = "needs_review" if derived_needs_review else "completed"
            return self._call(
                "finalize_account_research",
                {
                    "coverage_ledger_ref": payload["coverage_ledger_ref"],
                    "requested_outcome": outcome,
                },
            )
        elif last.name == "finalize_account_research":
            return self._call("ResearchFinalizationProposal", payload)
        else:
            self._result_refs.extend(item["result_ref"] for item in payload["results"])
        if self._next < len(self.plan):
            planned = self.plan[self._next]
            self._next += 1
            return self._call(str(planned["name"]), cast(dict[str, Any], planned["args"]))
        return self._call(
            "assess_account_coverage",
            {
                "result_refs": self._result_refs,
                "assessment_note": (
                    "The account's fresh facts were already on file; only the gaps were bought."
                ),
            },
        )


async def _run_p2_agent(
    conn: AsyncConnection,
    *,
    fixture: _Fixture,
    admitted: Sequence[str],
    plan: list[dict[str, Any]],
    tmp_path: Path,
    request_wrong_outcome: bool = False,
) -> tuple[Any, _ScriptedModel, _EmptyCommitteeProviders, EntityResearchJobAuthorization]:
    storage = FsStorage(tmp_path / f"fi2-artifacts-{uuid4().hex[:8]}")
    envelope, connection = await _launch_p2_job(conn, fixture=fixture, admitted=admitted)
    authorization = envelope.jobs[0].authorization
    jobs = DbEntityResearchJobStore(conn_factory=connection)
    stored = await jobs.get_job(authorization.job_id)
    assert stored is not None
    live_job = stored.model_copy(
        update={"active_worker_id": "fi2-s3-t2-worker", "lease_generation": 1}
    )
    fence = EntityResearchExecutionFence(
        task_id=uuid4(),
        worker_id="fi2-s3-t2-worker",
        lease_generation=1,
        task_attempt=1,
    )
    lineage = _FixtureLineageReader()
    providers = _EmptyCommitteeProviders(
        storage=storage,
        conn_factory=connection,
        contacts=(uuid4(), uuid4()),
        lineage=lineage,
    )
    result_store = EntityResearchResultStore(
        storage=storage,
        conn_factory=connection,
        lineage_readers={
            ExternalResearchResultLineageReader.provider_kind: (
                ExternalResearchResultLineageReader(conn_factory=connection)
            ),
            lineage.provider_kind: lineage,
        },
    )
    tool_factory = GovernedEntityResearchToolFactory(
        requests=EntityResearchToolRequestStore(conn_factory=connection, storage=storage),
        causation=EntityResearchProviderCausationStore(conn_factory=connection),
        results=result_store,
    )
    resolver = AccountResearchDefinitionResolver(
        tools=tool_factory,
        state=AccountResearchStateStore(conn_factory=connection),
        provider_actions=StaticAccountResearchProviderActions(
            {
                authorization.job_id: {
                    # Bound but never called in these scenarios: the point of §6.1 is that the
                    # deep-research action is not *reached* for a field already answered.
                    "research_account_deep": ProviderActionBinding(action=providers, version=1),
                    "enrich_account": ProviderActionBinding(action=providers, version=1),
                    "discover_buying_committee": ProviderActionBinding(action=providers, version=1),
                }
            }
        ),
        model_policy=ModelPolicy(
            model_id="fi2-s3-t2-model",
            timeout_s=10,
            max_retries=0,
            max_output_tokens=4096,
            temperature=0,
        ),
        conn_factory=connection,
    )
    definition = await resolver.resolve(job=live_job, fence=fence)
    model = _ScriptedModel(plan=plan, request_wrong_outcome=request_wrong_outcome)
    journal = DbEntityResearchAgentJournal(conn_factory=connection)
    runtime = EntityResearchAgentRuntime(
        factory=EntityResearchAgentFactory(
            models=_Models(model),
            journal=journal,
            guard=AccountResearchExecutionGuard(conn_factory=connection),
        ),
        checkpointers=Checkpointers(),
        journal=journal,
        finalizer=AccountResearchFinalizationEngine(conn_factory=connection),
    )
    outcome = await runtime.run(definition=definition)
    return outcome, model, providers, authorization


def _committee_call(*, account_id: UUID, evidence_claim_id: UUID) -> dict[str, Any]:
    return {
        "name": "discover_buying_committee",
        "args": {
            "field_keys": [],
            "source_keys": ["sumble_people"],
            "questions": [_COMMITTEE_QUESTION],
            "buying_unit_scope": {
                "scope_id": str(uuid4()),
                "account_entity_id": str(account_id),
                "office_label": "Boston gastroenterology practice",
                "locality": "Boston",
                "region": "Massachusetts",
                "target_functions": ["Operations"],
                "evidence_refs": [f"claim:{evidence_claim_id}"],
                "match_policy": "same_office_strict",
            },
        },
    }


def test_fi2_61_a_committee_authorized_job_cannot_finalize_without_attempting_it(
    tmp_path: Path,
    require_profiling_db: None,
) -> None:
    """All-known Account fields do not excuse no-work committee settlement.

    The three Account fields need no provider work because each is already evidence-backed. But
    the selection explicitly authorizes Sumble People committee discovery. Omitting that call is
    now an incomplete execution, so assessment writes no coverage and no receipt can be minted.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn, stale_culture=False)
            admitted = (_PAIN, _MOVES, _HIRING)
            with pytest.raises(
                RuntimeError,
                match="every authorized field/source and committee attempt is terminal",
            ):
                await _run_p2_agent(
                    conn,
                    fixture=fixture,
                    admitted=admitted,
                    plan=[],
                    tmp_path=tmp_path,
                )

            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_account_coverage "
                        "WHERE workspace_id=:workspace_id"
                    ),
                    {"workspace_id": fixture.workspace_id},
                )
            ).scalar_one() == 0
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_provider_operation "
                        "WHERE workspace_id=:workspace_id"
                    ),
                    {"workspace_id": fixture.workspace_id},
                )
            ).scalar_one() == 0

    run_async(scenario())


def test_account_only_scope_does_not_create_a_false_committee_review_flag() -> None:
    status, flags = AccountResearchStateStore._committee_coverage_status(
        committee_requested=False,
        result_count=0,
        member_count=0,
        scope_count=0,
        ambiguous_count=0,
        confirmed_empty_count=0,
    )

    assert status == "complete"
    assert flags == ()


def test_fi2_61_an_empty_close_is_refused_over_a_field_that_was_not_borrowed(
    monkeypatch: pytest.MonkeyPatch,
    require_profiling_db: None,
) -> None:
    """The zero-result close is not a free pass: it holds only for a wholly borrowed account.

    Today the state read cannot produce a completed field that is neither researched nor borrowed,
    so this forges exactly that state to prove the close path refuses it on its own — dropping the
    input's ``min_length`` must not become "an empty citation closes anything".
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn, stale_culture=False)
            # Nothing is on file for `_FUNDING`, so no claim can stand in for researching it.
            envelope, connection = await _launch_p2_job(
                conn, fixture=fixture, admitted=(_PAIN, _FUNDING)
            )
            authorization = envelope.jobs[0].authorization
            store = AccountResearchStateStore(conn_factory=connection)
            honest = await store.state(_active(authorization))
            assert set(honest.unresolved_field_keys) == {_FUNDING}
            forged = honest.model_copy(
                update={
                    "completed_field_keys": (_PAIN, _FUNDING),
                    "unresolved_field_keys": (),
                }
            )

            async def _forged_state(
                _self: AccountResearchStateStore,
                active: ActiveEntityResearchToolExecution | None = None,
            ) -> AccountResearchStateProjection:
                del active
                return forged

            monkeypatch.setattr(AccountResearchStateStore, "state", _forged_state)
            token = _ACTIVE_TOOL_EXECUTION.set(_active(authorization))
            try:
                with pytest.raises(
                    # ``sumble_jobs`` is named in this fixture's synthetic authority for every
                    # field, but its pinned action can only ask for hiring velocity, so the
                    # completeness reader no longer holds the unrequestable pairs outstanding
                    # (``source_can_request``). The requestable half of the same field is.
                    AccountResearchAuthorityError,
                    match=r"account\.recent_funding@exa_deep",
                ):
                    await store.assess(
                        AssessAccountCoverageInput(
                            result_refs=(), assessment_note="nothing left to research"
                        )
                    )
            finally:
                _ACTIVE_TOOL_EXECUTION.reset(token)

    run_async(scenario())


def test_fi2_61_engine_tools_degrade_a_malformed_argument_to_a_repairable_message() -> None:
    """An argument-schema violation is model repair, never an uncaught exception mid-run.

    Both layers are covered: LangChain's own ``args_schema`` validation is bound to the shared
    handler, and the in-body ``model_validate`` (where these tools actually parse) raises a
    ``ToolException`` carrying the same bounded, value-free feedback.
    """

    bindings = account_engine_tool_bindings(AccountResearchStateStore(conn_factory=cast(Any, None)))
    for name in (
        "read_account_research_state",
        "inspect_account_evidence",
        "assess_account_coverage",
        "finalize_account_research",
    ):
        assert bindings[name].tool.handle_validation_error is semantic_validation_error

    async def scenario() -> None:
        coroutine = bindings["assess_account_coverage"].tool.coroutine
        assert coroutine is not None
        with pytest.raises(ToolException) as raised:
            await coroutine(result_refs=["r"], assessment_note="")
        assert "semantic_tool_input_validation_failed" in str(raised.value)

    run_async(scenario())


def test_fi2_61_an_all_born_complete_job_spends_nothing_and_finalizes_completed(
    tmp_path: Path,
    require_profiling_db: None,
) -> None:
    """The same economics with a committee call: no account-axis spend, ``COMPLETED`` receipt.

    The committee scope cites the account's own claim as its office evidence — production's Sumble
    scope validation admits that (`sumble_entity_research_tools._persist_scope`), and the governed
    prompt explicitly permits that durable claim reference when the current run skips fresh
    fields. This test keeps the ``COMPLETED`` outcome under test.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn, stale_culture=False)
            admitted = (_PAIN, _MOVES, _HIRING)
            outcome, model, providers, authorization = await _run_p2_agent(
                conn,
                fixture=fixture,
                admitted=admitted,
                plan=[
                    _committee_call(
                        account_id=fixture.account_id,
                        evidence_claim_id=fixture.p1_claim_ids[_PAIN],
                    )
                ],
                tmp_path=tmp_path,
            )

            assert isinstance(outcome, EntityResearchAgentResult)
            receipt = outcome.finalization_receipt
            assert receipt is not None
            assert receipt.proposal.outcome is ResearchFinalizationOutcome.COMPLETED
            assert receipt.verification.all_passed()
            assert set(receipt.proposal.completed_field_keys) == set(admitted)
            assert receipt.proposal.unresolved_field_keys == ()
            # The account axis bought nothing: the only provider call was the committee.
            assert providers.calls == ["discover_buying_committee"]
            assert set(model.observed_state["completed_field_keys"]) == set(admitted)
            coverage = model.observed_coverage
            assert set(coverage["claim_refs"]) == {
                f"claim:{fixture.p1_claim_ids[key]}" for key in admitted
            }
            assert set(coverage["skipped_field_reasons"]) == {
                f"{key}:existing_claim_fresh" for key in admitted
            }
            spent = (
                await conn.execute(
                    text("SELECT spent_cents FROM entity_research_job WHERE job_id=:job_id"),
                    {"job_id": authorization.job_id},
                )
            ).scalar_one()
            # Only the committee call's cost — no field research was reserved or settled.
            assert Decimal(spent) == Decimal("1.25")

    run_async(scenario())


def test_fi2_61_a_wrong_requested_outcome_is_normalized_to_the_engine_derived_one(
    tmp_path: Path,
    require_profiling_db: None,
) -> None:
    """The finalization outcome is engine-owned; a model's wrong request cannot wedge the job.

    Live (job 2dd04bc4): the agent requested ``completed`` while the persisted coverage derived
    ``needs_review``, the mismatch was refused, and the model looped back into re-buying
    terminally-unproductive fields until the graph recursion cap suspended the job. The refusal is
    gone: the proposal carries the derived outcome and the tool result is the correction the
    model reads.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn, stale_culture=False)
            admitted = (_PAIN, _MOVES, _HIRING)
            outcome, model, providers, _authorization = await _run_p2_agent(
                conn,
                fixture=fixture,
                admitted=admitted,
                plan=[
                    _committee_call(
                        account_id=fixture.account_id,
                        evidence_claim_id=fixture.p1_claim_ids[_PAIN],
                    )
                ],
                tmp_path=tmp_path,
                request_wrong_outcome=True,
            )

            assert isinstance(outcome, EntityResearchAgentResult)
            receipt = outcome.finalization_receipt
            assert receipt is not None
            # The model asked for needs_review; the engine derived (and proposed) COMPLETED.
            assert receipt.proposal.outcome is ResearchFinalizationOutcome.COMPLETED
            assert receipt.verification.all_passed()
            assert providers.calls == ["discover_buying_committee"]
            assert model.observed_coverage["unresolved_field_keys"] == []

    run_async(scenario())


def test_fi2_61_stale_conflicted_and_relative_fields_cannot_settle_unattempted(
    tmp_path: Path,
    require_profiling_db: None,
) -> None:
    """Known-but-unusable claims do not substitute for terminal provider attempts."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn, conflicted_hiring=True)
            admitted = (_PAIN, _MOVES, _CULTURE, _HIRING, _FIT)
            with pytest.raises(
                # See the note above: only the requestable half of this fixture's synthetic
                # ``(sumble_jobs, exa_deep)`` authority can be outstanding.
                RuntimeError,
                match=r"account\.resonance\.culture@exa_deep",
            ):
                await _run_p2_agent(
                    conn,
                    fixture=fixture,
                    admitted=admitted,
                    plan=[
                        {
                            "name": "enrich_account",
                            "args": {
                                "field_keys": [_MOVES],
                                "source_keys": ["sumble_jobs"],
                                "questions": [_QUESTION],
                            },
                        },
                        _committee_call(
                            account_id=fixture.account_id,
                            evidence_claim_id=fixture.p1_claim_ids[_PAIN],
                        ),
                    ],
                    tmp_path=tmp_path,
                )

            # The attempted redundant refresh and committee result remain durable, but no
            # coverage/finalization row may claim the other three fields were researched.
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_account_coverage "
                        "WHERE workspace_id=:workspace_id"
                    ),
                    {"workspace_id": fixture.workspace_id},
                )
            ).scalar_one() == 0

    run_async(scenario())


def test_fi2_61_p1s_lens_is_untouched_by_p2s_run(
    require_profiling_db: None,
) -> None:
    """The skip is a read: P1's claims stay live, unsuperseded, and attributed to P1."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn)
            envelope, connection = await _launch_p2_job(
                conn, fixture=fixture, admitted=(_PAIN, _MOVES)
            )
            store = AccountResearchStateStore(conn_factory=connection)
            await store.state(_active(envelope.jobs[0].authorization))
            live = (
                await conn.execute(
                    text("SELECT count(*) FROM claim WHERE id=ANY(:ids) AND superseded_by IS NULL"),
                    {
                        "ids": [
                            fixture.p1_claim_ids[_PAIN],
                            fixture.p1_claim_ids[_MOVES],
                        ]
                    },
                )
            ).scalar_one()
            assert live == 2

    run_async(scenario())


@pytest.mark.usefixtures("require_profiling_db")
def test_fi2_61_species_comes_from_the_registry_not_a_hardcoded_list() -> None:
    """A field declared relative in the registry is relative here, whatever its key looks like."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_p1_research(conn, stale_culture=False)
            declared = "account.narrative_angle"
            await register_field(
                conn,
                FieldDef(
                    field_key=FieldKey(declared),
                    value_type="str",
                    pass_kind=PassKind.DEEP,
                    freshness_ttl=timedelta(days=90),
                    research_scope=ResearchScope.PROJECT_RELATIVE,
                ),
                value_schema={"type": "string"},
                description="A declared-relative account field (registry data, not a key rule).",
            )
            await _p1_claim(
                conn,
                fixture_workspace=fixture.workspace_id,
                account_id=fixture.account_id,
                field_key=declared,
                value="P1's angle on this account.",
                run_id=RunId(uuid4()),
                age=timedelta(days=1),
            )
            envelope, connection = await _launch_p2_job(
                conn, fixture=fixture, admitted=(_PAIN, declared)
            )
            store = AccountResearchStateStore(conn_factory=connection)
            state = await store.state(_active(envelope.jobs[0].authorization))
            assert set(state.completed_field_keys) == {_PAIN}
            assert set(state.unresolved_field_keys) == {declared}

    run_async(scenario())
