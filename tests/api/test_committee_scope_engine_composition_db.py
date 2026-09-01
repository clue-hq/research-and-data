"""The engine composes the committee buying-unit scope it already knows (founder ruling 2026-08-20).

Live run ``dc86340f`` (2026-08-20): ``discover_buying_committee`` was called eight times across
three accounts and **seven died at the Pydantic input boundary** with
``{"location": ["buying_unit_scope", "evidence_refs"], "message": "Field required"}`` — no provider
call, no operation row, no spend. Greater Chicago Specialty Physicians burned its entire 900s
runtime budget on four of them and timed out. The scope demanded six values from the model, five of
which the engine already held: the scope id (this tool call), the account (the job is bound to
exactly one), the office (the account's own ``core.hq_location`` evidence), and the evidence
references (this job's own result index).

*The engine disposes, it never quizzes.* This module pins that: the exact seven-failure payload now
resolves, the one that got through resolves identically, every authority refusal still refuses, and
replay is byte-identical.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.account_entity_research import (
    AccountBuyingUnitScope,
    AccountBuyingUnitScopeRequest,
    DiscoverBuyingCommitteeInput,
)
from clue_agents.entity_research_contracts import EntityResearchRuntimeContext
from clue_api.account_entity_research import (
    AccountResearchAuthorityError,
    AccountResearchExecutionGuard,
)
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    semantic_validation_error,
)
from clue_api.sumble_entity_research_tools import (
    SumbleCommitteeSemanticResearchAction,
    resolve_account_buying_unit_scope,
)
from clue_core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchCommitteePlan,
    ResearchMode,
    ReuseScope,
    RunId,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    GovernedResearchToolRequest,
    ResearchRunKind,
    ResearchRunLifecycleContract,
    ResearchSubjectType,
)
from clue_fleet import (
    EntityResearchJobEnvelope,
    EntityResearchRunEnvelope,
    launch_entity_research_run,
)
from clue_research.claimstore import insert_claim, record_run_lineage
from clue_research.identity import insert_account_entity
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.fleet.entity_research_r2_helpers import lifecycle_fixture
from tests.profiling.conftest import (
    migrated_db as migrated_db,
)
from tests.profiling.conftest import (
    require_profiling_db as require_profiling_db,
)
from tests.profiling.conftest import (
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_HQ_FIELD = "core.hq_location"
#: The live Scottsdale account's own HQ claim value, verbatim from the dev database.
_HQ_VALUE = {
    "raw": "Scottsdale, United States",
    "city": "Scottsdale",
    "region": "Arizona",
    "country": "United States",
    "country_code": "US",
}


@dataclass(frozen=True, slots=True)
class _Seed:
    workspace_id: str
    account_id: UUID
    research_run_id: UUID
    job_id: UUID
    authorization: EntityResearchJobAuthorization
    hq_claim_ref: str | None
    prior_result_refs: tuple[str, ...]
    committee_request: GovernedResearchToolRequest


async def _seed(
    conn: AsyncConnection,
    *,
    hq_claim: bool = True,
    prior_results: int = 1,
) -> _Seed:
    """One launched account job with the durable state the engine composes a scope out of."""

    workspace_id = await seed_workspace(conn, f"cs-{uuid4().hex[:8]}")
    await load_client_knowledge_pack(conn)
    await seed_source_manifests(conn)
    account_id = UUID(
        str(
            await insert_account_entity(
                conn,
                canonical_name="HealthScribe",
                primary_domain=f"healthscribe-{uuid4().hex[:8]}.test",
                workspace_id=workspace_id,
            )
        )
    )
    lifecycle = _account_lifecycle(workspace_id=workspace_id, account_id=account_id)
    authorization = EntityResearchJobAuthorization(
        job_id=uuid4(),
        research_run_id=lifecycle.run_id,
        subject_type=ResearchSubjectType.ACCOUNT,
        subject_entity_id=account_id,
        parent_account_id=None,
        workspace_id=workspace_id,
        project_id=lifecycle.selection.project_id,
        product_id=lifecycle.selection.product_id,
        project_run_id=lifecycle.selection.project_run_id,
        selection=lifecycle.selection,
        agent_profile_ref="agent-profile:account-research:v2",
        agent_profile_sha256="c" * 64,
        checkpoint_thread_id=f"checkpoint:{lifecycle.run_id}:{account_id}",
        attempt_id=uuid4(),
        lease_id=uuid4(),
    )
    await launch_entity_research_run(
        conn,
        EntityResearchRunEnvelope(
            lifecycle=lifecycle,
            jobs=(
                EntityResearchJobEnvelope(
                    authorization=authorization,
                    priority=0,
                    budget_envelope_ref=f"budget:job:{authorization.job_id}",
                    budget_cap_cents=Decimal("4.00"),
                ),
            ),
            budget_cap_cents=Decimal("10.00"),
            concurrency_limit=1,
        ),
    )
    hq_claim_ref: str | None = None
    if hq_claim:
        run_id = RunId(uuid4())
        await record_run_lineage(
            conn,
            run_id=UUID(str(run_id)),
            workspace_id=workspace_id,
            project_id=lifecycle.selection.project_id,
            kind="entity_research",
        )
        collected_at = datetime.now(UTC)
        claim_id = await insert_claim(
            conn,
            Claim(
                entity_id=EntityId(account_id),
                entity_type=EntityType.ACCOUNT,
                field_key=_HQ_FIELD,
                value_json=_HQ_VALUE,
                source_url="https://healthscribe.test/about",
                source_key="exa_websets",
                source_tier=cast(Any, 2),
                extraction_method=ExtractionMethod.API,
                evidence_span="Headquarters: Scottsdale, Arizona.",
                confidence=cast(Any, 0.9),
                observed_at=collected_at,
                collected_at=collected_at,
                run_id=run_id,
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=workspace_id,
            ),
        )
        hq_claim_ref = f"claim:{claim_id}"
    result_refs = tuple(
        [
            await _plant_prior_result(conn, authorization=authorization, ordinal=index)
            for index in range(prior_results)
        ]
    )
    committee_request = await _committee_tool_request(conn, authorization=authorization)
    return _Seed(
        workspace_id=workspace_id,
        account_id=account_id,
        research_run_id=lifecycle.run_id,
        job_id=authorization.job_id,
        authorization=authorization,
        hq_claim_ref=hq_claim_ref,
        prior_result_refs=result_refs,
        committee_request=committee_request,
    )


def _account_lifecycle(*, workspace_id: str, account_id: UUID) -> ResearchRunLifecycleContract:
    payload = lifecycle_fixture(ResearchRunKind.ACCOUNT_RESEARCH).model_dump(mode="json")
    selection = cast(dict[str, Any], payload["selection"])
    selection["workspace_id"] = workspace_id
    selection["subjects"] = [
        {**selection["subjects"][0], "subject_entity_id": str(account_id)},
    ]
    return ResearchRunLifecycleContract.model_validate(payload)


async def _turn_and_event(
    conn: AsyncConnection,
    *,
    authorization: EntityResearchJobAuthorization,
    tool_name: str,
    raw_tool_call_id: str,
    field_keys: Sequence[str],
    source_keys: Sequence[str],
) -> tuple[UUID, UUID, UUID]:
    """One admitted R3 turn + ``tool_started`` event, the pair the R4 request trigger demands."""

    turn_id, execution_id, event_id = uuid4(), uuid4(), uuid4()
    selection = authorization.selection
    context = {
        "agent_execution_id": str(execution_id),
        "agent_turn_id": str(turn_id),
        "role": "account",
        "subject_type": "account",
        "subject_entity_id": str(authorization.subject_entity_id),
        "job_id": str(authorization.job_id),
        "research_run_id": str(authorization.research_run_id),
        "workspace_id": authorization.workspace_id,
        "project_id": authorization.project_id,
        "product_id": authorization.product_id,
        "project_run_id": str(authorization.project_run_id),
        "checkpoint_thread_id": authorization.checkpoint_thread_id,
        "tool_names": [tool_name],
        "admitted_field_keys": list(selection.admitted_field_keys),
        "admitted_source_keys": [
            *selection.admitted_source_keys,
            *selection.committee_source_keys,
        ],
        "field_source_authority": [
            {"field_key": item.field_key, "source_keys": list(item.source_keys)}
            for item in selection.field_source_authority
        ],
        "research_questions": list(selection.research_questions),
    }
    params = {
        "turn_id": turn_id,
        "execution_id": execution_id,
        "event_id": event_id,
        "job_id": authorization.job_id,
        "research_run_id": authorization.research_run_id,
        "account_id": authorization.subject_entity_id,
        "workspace_id": authorization.workspace_id,
        "project_id": authorization.project_id,
        "product_id": authorization.product_id,
        "project_run_id": authorization.project_run_id,
        "checkpoint_thread_id": authorization.checkpoint_thread_id,
        "context": json.dumps(context),
        "sha": "a" * 64,
        "tool_name": tool_name,
        "raw_tool_call_id": raw_tool_call_id,
    }
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_agent_turn
                (agent_turn_id, agent_execution_id, job_id, research_run_id, role, subject_type,
                 target_entity_id, workspace_id, project_id, product_id, project_run_id,
                 checkpoint_thread_id, context_json, context_sha256, resource_manifest_json,
                 resource_manifest_sha256, tool_manifest_json, tool_manifest_sha256,
                 system_prompt_sha256)
            VALUES
                (:turn_id, :execution_id, :job_id, :research_run_id, 'account', 'account',
                 :account_id, :workspace_id, :project_id, :product_id, :project_run_id,
                 :checkpoint_thread_id, CAST(:context AS jsonb), :sha, '{}'::jsonb, :sha,
                 '[]'::jsonb, :sha, :sha)
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_agent_event
                (event_id, agent_turn_id, agent_execution_id, event_kind, tool_call_id, tool_name,
                 tool_version, tool_input_sha256, payload_json)
            VALUES (:event_id, :turn_id, :execution_id, 'tool_started', :raw_tool_call_id,
                    :tool_name, 1, :sha, '{}'::jsonb)
            """
        ),
        params,
    )
    del field_keys, source_keys
    return turn_id, execution_id, event_id


async def _plant_prior_result(
    conn: AsyncConnection,
    *,
    authorization: EntityResearchJobAuthorization,
    ordinal: int,
) -> str:
    """One settled account result this job already holds — an ``result_refs`` entry in its state."""

    authority = authorization.selection.field_source_authority[ordinal]
    field_key, source_key = authority.field_key, authority.source_keys[0]
    turn_id, execution_id, event_id = await _turn_and_event(
        conn,
        authorization=authorization,
        tool_name="enrich_account",
        raw_tool_call_id=f"prior-{ordinal}",
        field_keys=(field_key,),
        source_keys=(source_key,),
    )
    request_id, result_id, observation_id = uuid4(), uuid4(), uuid4()
    operation_ref = f"provider-op:{result_id}"
    artifact_sha = hashlib.sha256(str(result_id).encode()).hexdigest()
    artifact_key = f"{authorization.workspace_id}/{artifact_sha}"
    params = {
        "turn_id": turn_id,
        "execution_id": execution_id,
        "event_id": event_id,
        "request_id": request_id,
        "result_id": result_id,
        "observation_id": observation_id,
        "operation_ref": operation_ref,
        "artifact_key": artifact_key,
        "artifact_sha": artifact_sha,
        "job_id": authorization.job_id,
        "research_run_id": authorization.research_run_id,
        "account_id": authorization.subject_entity_id,
        "workspace_id": authorization.workspace_id,
        "project_id": authorization.project_id,
        "product_id": authorization.product_id,
        "project_run_id": authorization.project_run_id,
        "sha": "a" * 64,
        "field_key": field_key,
        "source_key": source_key,
        "authority": json.dumps([{"field_key": field_key, "source_keys": [source_key]}]),
        "raw_tool_call_id": f"prior-{ordinal}",
        "idem": str(request_id),
    }
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes) VALUES (:artifact_key, :workspace_id, :artifact_sha, "
            "'application/json', 1)"
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_tool_request
                (tool_request_id, agent_turn_id, agent_execution_id, tool_event_id,
                 raw_tool_call_id, research_run_id, job_id, subject_type, target_entity_id,
                 workspace_id, project_id, product_id, project_run_id, tool_name, tool_version,
                 tool_input_sha256, field_plan_ref, source_plan_ref, field_keys, source_keys,
                 questions, budget_reservation_key, idempotency_key, field_source_authority)
            VALUES
                (:request_id, :turn_id, :execution_id, :event_id, :raw_tool_call_id,
                 :research_run_id, :job_id, 'account', :account_id, :workspace_id, :project_id,
                 :product_id, :project_run_id, 'enrich_account', 1, :sha, 'field-plan:1',
                 'source-plan:1', ARRAY[:field_key], ARRAY[:source_key], ARRAY[]::text[],
                 :idem, :idem, CAST(:authority AS jsonb))
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_provider_operation
                (operation_ref, provider_kind, workspace_id, project_id, project_run_id,
                 subject_type, target_entity_id, source_key, request_artifact_ref, reserved_at)
            VALUES (:operation_ref, 'sumble_account', :workspace_id, :project_id, :project_run_id,
                    'account', :account_id, :source_key, :artifact_key, now())
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_provider_observation
                (observation_id, tool_request_id, external_workspace_id, disposition,
                 provider_operation_ref)
            VALUES (:observation_id, :request_id, :workspace_id, 'caused', :operation_ref)
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_result
                (result_id, tool_request_id, provider_observation_id, workspace_id, subject_type,
                 target_entity_id, result_artifact_key, result_sha256, delivery,
                 requested_field_keys, provider_operation_ref, provider_snapshot_ref)
            VALUES (:result_id, :request_id, :observation_id, :workspace_id, 'account',
                    :account_id, :artifact_key, :sha, 'inline_complete', ARRAY[:field_key],
                    :operation_ref, 'snapshot:1')
            """
        ),
        params,
    )
    return f"research-result:{result_id}"


async def _committee_tool_request(
    conn: AsyncConnection, *, authorization: EntityResearchJobAuthorization
) -> GovernedResearchToolRequest:
    """The governed committee request the engine journals before the provider action runs."""

    turn_id, execution_id, event_id = await _turn_and_event(
        conn,
        authorization=authorization,
        tool_name="discover_buying_committee",
        raw_tool_call_id="committee-1",
        field_keys=(),
        source_keys=(PEOPLE_SOURCE_KEY,),
    )
    request_id = uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_tool_request
                (tool_request_id, agent_turn_id, agent_execution_id, tool_event_id,
                 raw_tool_call_id, research_run_id, job_id, subject_type, target_entity_id,
                 workspace_id, project_id, product_id, project_run_id, tool_name, tool_version,
                 tool_input_sha256, field_plan_ref, source_plan_ref, field_keys, source_keys,
                 questions, budget_reservation_key, idempotency_key, field_source_authority)
            VALUES
                (:request_id, :turn_id, :execution_id, :event_id, 'committee-1',
                 :research_run_id, :job_id, 'account', :account_id, :workspace_id, :project_id,
                 :product_id, :project_run_id, 'discover_buying_committee', 1, :sha,
                 'field-plan:committee', 'source-plan:committee', ARRAY[]::text[],
                 ARRAY[:source_key], ARRAY[]::text[], :idem, :idem,
                 '[]'::jsonb)
            """
        ),
        {
            "request_id": request_id,
            "turn_id": turn_id,
            "execution_id": execution_id,
            "event_id": event_id,
            "research_run_id": authorization.research_run_id,
            "job_id": authorization.job_id,
            "account_id": authorization.subject_entity_id,
            "workspace_id": authorization.workspace_id,
            "project_id": authorization.project_id,
            "product_id": authorization.product_id,
            "project_run_id": authorization.project_run_id,
            "sha": "a" * 64,
            "source_key": PEOPLE_SOURCE_KEY,
            "idem": str(request_id),
        },
    )
    return GovernedResearchToolRequest(
        research_run_id=authorization.research_run_id,
        job_id=authorization.job_id,
        subject_type=ResearchSubjectType.ACCOUNT,
        target_entity_id=authorization.subject_entity_id,
        agent_turn_id=turn_id,
        agent_execution_id=execution_id,
        tool_call_id=request_id,
        tool_name="discover_buying_committee",
        tool_version=1,
        tool_input_sha256="a" * 64,
        field_plan_ref="field-plan:committee",
        source_plan_ref="source-plan:committee",
        source_keys=(PEOPLE_SOURCE_KEY,),
        budget_reservation_key=str(request_id),
        idempotency_key=str(request_id),
    )


# --- the live payloads -------------------------------------------------------------------------
#: The exact arguments of the seven calls that died at the input boundary (job ``00e1a8d3``,
#: 2026-08-20 19:45:29). Copied verbatim from ``entity_research_agent_event.payload_json``.
_SEVEN_FAILURE_ARGUMENTS = {
    "questions": [],
    "field_keys": [],
    "source_keys": [PEOPLE_SOURCE_KEY],
    "follow_up_reason": None,
    "buying_unit_scope": {
        "region": "Arizona",
        "country": "United States",
        "locality": "Scottsdale",
        "scope_id": "8f3c1e2a-9b4d-4f6e-8a71-2c5d9e0b3f14",
        "match_policy": "company_wide",
        "office_label": "Scottsdale, Arizona headquarters",
        "business_unit": None,
        "facility_name": None,
        "target_functions": ["Clinical", "Operations", "Physician", "Executive Management"],
        "account_entity_id": "ec39ac20-673d-4fc7-8576-524a4a249a84",
    },
    "parent_operation_ref": None,
    "parent_observation_ref": None,
}
#: The eighth call, eleven seconds later: identical but for the evidence references it finally
#: guessed its way to. It passed validation and reached the provider (which answered 402).
_EIGHTH_ATTEMPT_ARGUMENTS = {
    **_SEVEN_FAILURE_ARGUMENTS,
    "buying_unit_scope": {
        **{
            key: value
            for key, value in _SEVEN_FAILURE_ARGUMENTS["buying_unit_scope"].items()
            if key not in {"business_unit", "facility_name"}
        },
        "evidence_refs": [
            "claim:31b404b5-4150-4a9b-b515-53f5d315372d",
            "claim:3b78ca38-18be-4eb5-9efc-8c146565642a",
            "research-result:255d9f35-0697-5e76-9e27-6ebdc1fdb7f2",
        ],
    },
}


def _arguments(*, account_id: UUID, scope: dict[str, Any] | None) -> dict[str, Any]:
    """The seven-failure argument shape, re-pointed at a fixture account."""

    payload: dict[str, Any] = {
        "questions": [],
        "field_keys": [],
        "source_keys": [PEOPLE_SOURCE_KEY],
        "follow_up_reason": None,
        "parent_operation_ref": None,
        "parent_observation_ref": None,
    }
    if scope is not None:
        payload["buying_unit_scope"] = {**scope, "account_entity_id": str(account_id)}
    return payload


def test_the_seven_failure_payload_no_longer_dies_at_the_input_boundary() -> None:
    """RED before Change 1: ``buying_unit_scope.evidence_refs`` — "Field required"."""

    parsed = DiscoverBuyingCommitteeInput.model_validate(_SEVEN_FAILURE_ARGUMENTS)
    scope = parsed.buying_unit_scope
    assert scope.evidence_refs == ()
    assert scope.locality == "Scottsdale"
    assert scope.target_functions == ("Clinical", "Operations", "Physician", "Executive Management")
    # And the shape the manual now teaches: nothing but the source key.
    minimal = DiscoverBuyingCommitteeInput.model_validate({"source_keys": [PEOPLE_SOURCE_KEY]})
    assert minimal.buying_unit_scope == AccountBuyingUnitScopeRequest()


def test_the_eighth_attempt_payload_still_validates_unchanged() -> None:
    """The one call that got through keeps working exactly as it did."""

    parsed = DiscoverBuyingCommitteeInput.model_validate(_EIGHTH_ATTEMPT_ARGUMENTS)
    scope = parsed.buying_unit_scope
    assert scope.evidence_refs == (
        "claim:31b404b5-4150-4a9b-b515-53f5d315372d",
        "claim:3b78ca38-18be-4eb5-9efc-8c146565642a",
        "research-result:255d9f35-0697-5e76-9e27-6ebdc1fdb7f2",
    )
    assert scope.office_label == "Scottsdale, Arizona headquarters"
    assert scope.match_policy == "company_wide"


def test_the_engine_composes_the_whole_scope_when_the_model_declares_nothing() -> None:
    """Account, office and evidence all come from durable state the engine already holds."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)
            resolved = await resolve_account_buying_unit_scope(
                conn,
                request=seed.committee_request,
                requested=AccountBuyingUnitScopeRequest(),
                workspace_id=seed.workspace_id,
            )
            assert resolved.account_entity_id == seed.account_id
            # The office is the account's own HQ-location evidence, and nothing beyond it.
            assert resolved.office_label == "Scottsdale, United States"
            assert (resolved.locality, resolved.region, resolved.country) == (
                "Scottsdale",
                "Arizona",
                "United States",
            )
            assert resolved.facility_name is None
            # ``business_unit`` still narrows admission, so the engine never asserts one.
            assert resolved.business_unit is None
            # The evidence is this job's own: the HQ claim behind the office, then its results.
            assert resolved.evidence_refs == (seed.hq_claim_ref, *seed.prior_result_refs)
            # A scope id derived from the call, so two calls can never share one.
            assert resolved.scope_id != seed.committee_request.tool_call_id
            again = await resolve_account_buying_unit_scope(
                conn,
                request=seed.committee_request,
                requested=AccountBuyingUnitScopeRequest(),
                workspace_id=seed.workspace_id,
            )
            assert again.scope_id == resolved.scope_id

    run_async(scenario())


def test_the_live_seven_failure_shape_resolves_and_keeps_every_declared_value() -> None:
    """The payload that died seven times now completes — and the engine overwrites nothing."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)
            declared = cast(dict[str, Any], _SEVEN_FAILURE_ARGUMENTS["buying_unit_scope"])
            parsed = DiscoverBuyingCommitteeInput.model_validate(
                _arguments(account_id=seed.account_id, scope=declared)
            )
            resolved = await resolve_account_buying_unit_scope(
                conn,
                request=seed.committee_request,
                requested=parsed.buying_unit_scope,
                workspace_id=seed.workspace_id,
            )
            assert resolved.office_label == "Scottsdale, Arizona headquarters"
            assert resolved.locality == "Scottsdale"
            assert resolved.target_functions == tuple(declared["target_functions"])
            assert resolved.evidence_refs == (seed.hq_claim_ref, *seed.prior_result_refs)
            assert resolved.account_entity_id == seed.account_id

    run_async(scenario())


def test_a_declared_office_is_never_overwritten_by_the_accounts_hq_evidence() -> None:
    """An agent that deliberately narrows to one site keeps that site, HQ claim or not."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)
            resolved = await resolve_account_buying_unit_scope(
                conn,
                request=seed.committee_request,
                requested=AccountBuyingUnitScopeRequest(
                    office_label="Fort Myers ambulatory campus",
                    locality="Fort Myers",
                    business_unit="Revenue Cycle",
                ),
                workspace_id=seed.workspace_id,
            )
            assert resolved.office_label == "Fort Myers ambulatory campus"
            assert resolved.locality == "Fort Myers"
            assert resolved.business_unit == "Revenue Cycle"
            # Not Arizona: no part of the declared office is replaced by the account's HQ claim.
            assert resolved.region is None
            assert resolved.country is None

    run_async(scenario())


def test_a_declared_evidence_reference_is_kept_and_the_engine_adds_nothing() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn, prior_results=2)
            chosen = seed.prior_result_refs[1]
            resolved = await resolve_account_buying_unit_scope(
                conn,
                request=seed.committee_request,
                requested=AccountBuyingUnitScopeRequest(evidence_refs=(chosen,)),
                workspace_id=seed.workspace_id,
            )
            assert resolved.evidence_refs == (chosen,)

    run_async(scenario())


def test_an_account_with_no_retained_evidence_records_the_gap_and_fabricates_nothing() -> None:
    """The honest answer when there is nothing to cite: an empty, durably recorded evidence set.

    Not a refusal (an account whose every field was borrowed still owes its committee attempt) and
    not an invented reference. The empty ``evidence_refs`` in the persisted ``scope_json`` is the
    audit trail, and it rides ``scope_sha256`` into the job's own state digest.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn, hq_claim=False, prior_results=0)

            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            resolved = await resolve_account_buying_unit_scope(
                conn,
                request=seed.committee_request,
                requested=AccountBuyingUnitScopeRequest(),
                workspace_id=seed.workspace_id,
            )
            assert resolved.evidence_refs == ()
            # No location is evidenced, so none is invented — the label names the account itself.
            assert resolved.office_label == "HealthScribe (company-wide)"
            assert (resolved.locality, resolved.region, resolved.country) == (None, None, None)
            await _committee_action(same_connection)._persist_scope(
                request=seed.committee_request,
                scope=resolved,
                workspace_id=seed.workspace_id,
            )
            stored = _stored_scope_json(
                (
                    await conn.execute(
                        text(
                            "SELECT scope_json FROM entity_research_account_committee_scope "
                            "WHERE tool_request_id=:tool_request_id"
                        ),
                        {"tool_request_id": seed.committee_request.tool_call_id},
                    )
                ).scalar_one()
            )
            assert stored["evidence_refs"] == []

    run_async(scenario())


def test_a_foreign_account_in_the_scope_is_preserved_so_the_authority_check_still_refuses() -> None:
    """The engine fills what was omitted; it never launders a wrong declaration into a right one."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)
            foreign = uuid4()
            resolved = await resolve_account_buying_unit_scope(
                conn,
                request=seed.committee_request,
                requested=AccountBuyingUnitScopeRequest(account_entity_id=foreign),
                workspace_id=seed.workspace_id,
            )
            assert resolved.account_entity_id == foreign
            assert resolved.account_entity_id != seed.committee_request.target_entity_id

    run_async(scenario())


def test_the_pre_tool_guard_refuses_a_foreign_account_and_admits_an_omitted_one() -> None:
    """The R5 execution guard keeps its authority pin while dropping its ceremony."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)

            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            guard = AccountResearchExecutionGuard(conn_factory=asynccontextmanager(same_connection))
            context = cast(
                EntityResearchRuntimeContext,
                type("_Ctx", (), {"authorization": seed.authorization})(),
            )

            def call(arguments: dict[str, Any]) -> Any:
                return type(
                    "_Call",
                    (),
                    {"tool_name": "discover_buying_committee", "arguments": arguments},
                )()

            with pytest.raises(AccountResearchAuthorityError) as foreign:
                await guard.authorize_tool(
                    context=context,
                    call=call(
                        _arguments(account_id=uuid4(), scope={"office_label": "Somewhere else"})
                    ),
                    journal_event_ref="event:1",
                )
            # The refusal names the account the agent must use, not just that it used a wrong one.
            assert str(seed.account_id) in str(foreign.value)
            # A declared, correct account still passes, and so does a wholly omitted scope.
            for arguments in (
                _arguments(account_id=seed.account_id, scope={"office_label": "HQ"}),
                _arguments(account_id=seed.account_id, scope={}),
                _arguments(account_id=seed.account_id, scope=None),
            ):
                await guard.authorize_tool(
                    context=context, call=call(arguments), journal_event_ref="event:1"
                )

    run_async(scenario())


def test_target_functions_are_still_bounded_by_the_confirmed_committee_plan() -> None:
    """Advisory does not mean invented: the plan check is untouched by the composition."""

    plan = ResearchCommitteePlan(functions=("Operations", "Finance"), candidate_cap=4)

    def scope(functions: tuple[str, ...]) -> AccountBuyingUnitScope:
        return AccountBuyingUnitScope(
            scope_id=uuid4(),
            account_entity_id=uuid4(),
            office_label="Boston office",
            locality="Boston",
            target_functions=functions,
        )

    with pytest.raises(EntityResearchGovernedRejection) as invented:
        SumbleCommitteeSemanticResearchAction._validate_scope_against_plan(
            scope(("Operations", "Marketing")), plan=plan
        )
    assert "Marketing" in str(invented.value)
    # An engine-composed scope declares no function at all, which widens nothing.
    SumbleCommitteeSemanticResearchAction._validate_scope_against_plan(scope(()), plan=plan)


def test_same_office_strict_still_requires_the_office_it_enforces() -> None:
    """The retired policy keeps its own precondition; ``company_wide`` never needed one."""

    with pytest.raises(ValidationError) as refused:
        AccountBuyingUnitScopeRequest(match_policy="same_office_strict")
    assert "same_office_strict" in str(refused.value)
    AccountBuyingUnitScopeRequest(match_policy="same_office_strict", locality="Fort Myers")
    AccountBuyingUnitScopeRequest(match_policy="company_wide")


def test_an_engine_composed_scope_persists_and_replays_with_a_stable_digest() -> None:
    """First write wins: the durable scope is the one the account job actually recorded."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)

            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            action = _committee_action(same_connection)
            resolved = await resolve_account_buying_unit_scope(
                conn,
                request=seed.committee_request,
                requested=AccountBuyingUnitScopeRequest(),
                workspace_id=seed.workspace_id,
            )
            await action._persist_scope(
                request=seed.committee_request,
                scope=resolved,
                workspace_id=seed.workspace_id,
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT scope_json, scope_sha256 FROM "
                            "entity_research_account_committee_scope "
                            "WHERE tool_request_id=:tool_request_id"
                        ),
                        {"tool_request_id": seed.committee_request.tool_call_id},
                    )
                )
                .mappings()
                .one()
            )
            digest = str(stored["scope_sha256"])
            # The account's evidence moves on — a newer, higher-tier HQ claim would compose a
            # different office and a different reference set. The recorded scope does not move.
            moved = datetime.now(UTC)
            await insert_claim(
                conn,
                Claim(
                    entity_id=EntityId(seed.account_id),
                    entity_type=EntityType.ACCOUNT,
                    field_key=_HQ_FIELD,
                    value_json={**_HQ_VALUE, "raw": "Phoenix, United States", "city": "Phoenix"},
                    source_url="https://healthscribe.test/contact",
                    source_key="sumble_organizations",
                    source_tier=cast(Any, 1),
                    extraction_method=ExtractionMethod.API,
                    evidence_span="Headquarters: Phoenix, Arizona.",
                    confidence=cast(Any, 0.95),
                    observed_at=moved,
                    collected_at=moved,
                    run_id=RunId(uuid4()),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                    workspace_id=seed.workspace_id,
                ),
            )
            replayed = await resolve_account_buying_unit_scope(
                conn,
                request=seed.committee_request,
                requested=AccountBuyingUnitScopeRequest(),
                workspace_id=seed.workspace_id,
            )
            assert replayed == resolved
            assert replayed.model_dump(mode="json") == _stored_scope_json(stored["scope_json"])
            await action._persist_scope(
                request=seed.committee_request,
                scope=replayed,
                workspace_id=seed.workspace_id,
            )
            assert (
                await conn.execute(
                    text(
                        "SELECT scope_sha256 FROM entity_research_account_committee_scope "
                        "WHERE tool_request_id=:tool_request_id"
                    ),
                    {"tool_request_id": seed.committee_request.tool_call_id},
                )
            ).scalar_one() == digest

    run_async(scenario())


def test_a_historical_scope_replays_byte_identically_under_what_it_recorded() -> None:
    """A strict, model-authored scope from before the composition is returned exactly as stored."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)
            historical = AccountBuyingUnitScope(
                scope_id=uuid4(),  # a model-invented id the engine would never derive
                account_entity_id=seed.account_id,
                office_label="Fort Myers, Florida headquarters",
                facility_name="6321 Daniels Parkway",
                locality="Fort Myers",
                region="Florida",
                country="United States",
                business_unit="Physician Enterprise",
                target_functions=("Clinical",),
                evidence_refs=(seed.prior_result_refs[0],),
                match_policy="same_office_strict",
            )
            payload = historical.model_dump(mode="json")
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
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
                    "scope_id": historical.scope_id,
                    "tool_request_id": seed.committee_request.tool_call_id,
                    "run_id": seed.research_run_id,
                    "job_id": seed.job_id,
                    "workspace_id": seed.workspace_id,
                    "account_id": seed.account_id,
                    "scope_json": json.dumps(payload),
                    "scope_sha": digest,
                },
            )
            replayed = await resolve_account_buying_unit_scope(
                conn,
                request=seed.committee_request,
                requested=AccountBuyingUnitScopeRequest(),
                workspace_id=seed.workspace_id,
            )
            assert replayed == historical
            assert replayed.model_dump(mode="json") == payload
            assert (
                hashlib.sha256(
                    json.dumps(
                        replayed.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                == digest
            )

    run_async(scenario())


def _stored_scope_json(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(value) if isinstance(value, str) else value)


def _committee_action(conn_factory: Any) -> SumbleCommitteeSemanticResearchAction:
    """The production action, constructed only far enough to exercise its scope persistence."""

    return SumbleCommitteeSemanticResearchAction(
        preflight=cast(Any, object()),
        coordinator=cast(Any, object()),
        storage=cast(Any, object()),
        conn_factory=asynccontextmanager(conn_factory),
        gateway=cast(Any, object()),
        role_model="unused",
    )


# --- Change 2: the schema the model actually reads ----------------------------------------------


def test_every_committee_tool_argument_carries_a_description_in_its_json_schema() -> None:
    """A field added without a ``description=`` fails the build, not a live account job.

    The knowledge that used to live in a Python ``#`` comment and one manual sentence never reached
    the model: the JSON schema is what it sees on every call. This guard keeps it that way.
    """

    schema = DiscoverBuyingCommitteeInput.model_json_schema()
    undocumented: list[str] = []
    for definition_name, definition in [
        ("DiscoverBuyingCommitteeInput", schema),
        *sorted(cast(dict[str, Any], schema.get("$defs", {})).items()),
    ]:
        for name, field in cast(dict[str, Any], definition.get("properties", {})).items():
            if not str(field.get("description", "")).strip():
                undocumented.append(f"{definition_name}.{name}")
    assert undocumented == []
    scope_schema = cast(dict[str, Any], schema["$defs"]["AccountBuyingUnitScopeRequest"])
    evidence = str(scope_schema["properties"]["evidence_refs"]["description"])
    assert "claim:<uuid>" in evidence
    assert "research-result:<uuid>" in evidence
    assert "read_account_research_state" in evidence
    assert "advisory" in str(scope_schema["properties"]["target_functions"]["description"]).lower()
    assert "at least one" in str(schema["properties"]["source_keys"]["description"]).lower()
    policy = str(scope_schema["properties"]["match_policy"]["description"])
    assert "company_wide" in policy and "same_office_strict" in policy


# --- Change 3: a refusal that carries its own repair --------------------------------------------


def test_a_still_possible_validation_failure_returns_the_exact_repair() -> None:
    """Naming the field was never enough: the refusal shows the format and where to get one."""

    with pytest.raises(ValidationError) as refused:
        DiscoverBuyingCommitteeInput.model_validate(
            {
                "source_keys": [PEOPLE_SOURCE_KEY],
                "buying_unit_scope": {"evidence_refs": ["the Q3 filing"]},
            }
        )
    rendered = json.loads(
        semantic_validation_error(refused.value, schema=DiscoverBuyingCommitteeInput)
    )
    assert rendered["error"] == "semantic_tool_input_validation_failed"
    detail = rendered["details"][0]
    assert detail["location"] == ["buying_unit_scope", "evidence_refs"]
    correction = str(detail["correction"])
    assert "buying_unit_scope.evidence_refs" in correction
    assert "claim:31b404b5-4150-4a9b-b515-53f5d315372d" in correction
    assert "research-result:255d9f35-0697-5e76-9e27-6ebdc1fdb7f2" in correction
    assert "read_account_research_state" in correction
    assert "drop the key" in correction.lower()


def test_a_whole_object_violation_still_names_the_one_always_legal_call() -> None:
    with pytest.raises(ValidationError) as refused:
        DiscoverBuyingCommitteeInput.model_validate(
            {
                "source_keys": [PEOPLE_SOURCE_KEY],
                "buying_unit_scope": {"match_policy": "same_office_strict"},
            }
        )
    rendered = json.loads(
        semantic_validation_error(refused.value, schema=DiscoverBuyingCommitteeInput)
    )
    correction = str(rendered["details"][0]["correction"])
    assert "buying_unit_scope" in correction
    assert "optional" in correction


def test_an_evidence_reference_outside_this_job_refuses_recoverably_instead_of_suspending() -> None:
    """A model-authored foreign reference is repairable input, not a job-killing integrity fault."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _seed(conn)

            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            action = _committee_action(same_connection)
            foreign = AccountBuyingUnitScope(
                scope_id=uuid4(),
                account_entity_id=seed.account_id,
                office_label="Scottsdale, United States",
                locality="Scottsdale",
                evidence_refs=(f"research-result:{uuid.uuid4()}",),
            )
            with pytest.raises(EntityResearchGovernedRejection) as refused:
                await action._persist_scope(
                    request=seed.committee_request,
                    scope=foreign,
                    workspace_id=seed.workspace_id,
                )
            assert refused.value.code == "committee_scope_evidence_outside_job"
            assert "read_account_research_state" in refused.value.detail
            assert "claim:<uuid>" in refused.value.detail

    run_async(scenario())
