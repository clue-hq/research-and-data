"""DB-backed tests for M5.2 — ICP synthesis (``synthesize_icps``).

Covers: the deterministic floor returns ≥1 proposal with all six Doc B §3 elements, each justified
by **real** Client-KB claim ids (no fabrication); project-scoped interview statements are a
first-class second evidence species (a statements-only client still gets a *grounded* proposal that
cites real statement ids); with neither species the result is the typed ``floor_only`` not-ready
outcome instead of a generic proposal wearing a grounded label; the LLM path is config-bounded
(off-set field/pack names are dropped) and can split into multiple ICPs (D5); any LLM/parse failure
degrades to the floor (the config is always the floor — the no-LLM path still completes).
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityType, OnboardingInputKind
from clue_core.proposals import ProposalStatus
from clue_research.proposals import ProposalScope, get_field_proposal
from clue_research.stage0 import (
    NO_CLIENT_KB_CLAIMS,
    NO_PROJECT_STATEMENTS,
    ClientInput,
    ClientKnowledgeBaseRef,
    ICPSynthesisStatus,
    InterviewRoute,
    InterviewStatement,
    ProjectStatement,
    read_client_kb_claims,
    read_statements,
    reverse_profile,
    route_interview_answer,
    submit_onboarding_input,
    synthesize_icps,
    synthesize_icps_with_proposals,
)
from clue_research.stage0.fields import (
    CLIENT_CUSTOMER,
    CLIENT_DELIVERED_VALUE,
    CLIENT_DIFFERENTIATOR,
    CLIENT_ICP_EVIDENCE,
    CLIENT_PRODUCT,
    CLIENT_VALUE_PROP,
)
from clue_research.stage0.icp_types import ICPProposal
from clue_spine import create_brand, create_product, create_project
from clue_storage import artifact_key as make_artifact_key
from clue_storage import record_artifact
from tests.stage0._fakes import FakeGateway, build_client_kb
from tests.stage0.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db")

_CLIENT = "tenant-synth"

# A client whose own prose ("data infrastructure") matches the data_infra starter pack.
_ASSERTED: dict[str, JsonValue] = {
    CLIENT_VALUE_PROP: "We sell a data infrastructure platform",
    CLIENT_PRODUCT: "data infrastructure platform for analytics teams",
    CLIENT_DIFFERENTIATOR: "the fastest query engine",
    CLIENT_DELIVERED_VALUE: "customers buy us for migration speed",
    CLIENT_ICP_EVIDENCE: {"industries": ["data_infra"], "sizes": ["mid-market"], "geos": ["US"]},
    CLIENT_CUSTOMER: [{"name": "BigCo", "domain": "bigco.example"}],
}


def _all_justifying(proposal: ICPProposal) -> set[object]:
    """Every claim id cited across the proposal's six elements."""
    ids: set[object] = set(proposal.justifying_claim_ids)
    ids |= set(proposal.firmographic.justifying_claim_ids)
    ids |= set(proposal.source_profile.justifying_claim_ids)
    for t in proposal.technographic:
        ids |= set(t.justifying_claim_ids)
    for s in proposal.candidate_signals:
        ids |= set(s.justifying_claim_ids)
    for w in proposal.rubric.weights:
        ids |= set(w.justifying_claim_ids)
    for seed in proposal.seed_accounts:
        ids |= set(seed.justifying_claim_ids)
    return ids


def _all_justifying_statements(proposal: ICPProposal) -> set[object]:
    """Every statement id cited across the proposal's elements."""
    ids: set[object] = set(proposal.justifying_statement_ids)
    ids |= set(proposal.firmographic.justifying_statement_ids)
    ids |= set(proposal.source_profile.justifying_statement_ids)
    for t in proposal.technographic:
        ids |= set(t.justifying_statement_ids)
    for s in proposal.candidate_signals:
        ids |= set(s.justifying_statement_ids)
    for w in proposal.rubric.weights:
        ids |= set(w.justifying_statement_ids)
    return ids


async def _empty_client_kb(conn: AsyncConnection, suffix: str) -> ClientKnowledgeBaseRef:
    """A versioned Client KB with **zero** claims (no materials, zero budget, no source tier)."""
    result = await reverse_profile(
        conn,
        ClientInput(name=f"Silent Co {suffix}", website=f"https://silent-{suffix}.example"),
        workspace_id=_CLIENT,
        budget_cap_cents=Decimal(0),
        max_source_tier=0,
    )
    return result.ref


async def _record_project_statement(
    conn: AsyncConnection,
    *,
    suffix: str,
    client_entity_id: object,
    answer: str,
) -> tuple[str, ProjectStatement]:
    """Route one real ``project_state`` interview statement and return (project_id, evidence)."""
    brand = await create_brand(conn, workspace_id=_CLIENT, name=f"Statement brand {suffix}")
    product = await create_product(
        conn, workspace_id=_CLIENT, brand_id=brand.brand_id, name=f"Statement product {suffix}"
    )
    project = await create_project(
        conn,
        workspace_id=_CLIENT,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        name=f"Statement project {suffix}",
    )
    digest = hashlib.sha256(answer.encode()).hexdigest()
    key = make_artifact_key(_CLIENT, digest)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=_CLIENT,
        content_sha256=digest,
        media_type="text/plain",
        size_bytes=len(answer),
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=_CLIENT,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=project.project_id,
        client_entity_id=client_entity_id,  # type: ignore[arg-type]
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=key,
        content_sha256=digest,
        actor="human",
    )
    routed = await route_interview_answer(
        conn,
        workspace_id=_CLIENT,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=project.project_id,
        client_entity_id=client_entity_id,  # type: ignore[arg-type]
        onboarding_input_id=captured.onboarding_input_id,
        artifact_key=key,
        answer=answer,
        statements=(
            InterviewStatement(
                route=InterviewRoute.PROJECT_STATE,
                route_key="target_segment",
                quote_start=0,
                quote_end=len(answer),
                entity_id=client_entity_id,  # type: ignore[arg-type]
                entity_type=EntityType.ACCOUNT,
            ),
        ),
        actor="human",
    )
    (statement_id,) = routed.statement_ids
    return project.project_id, ProjectStatement(
        statement_id=statement_id,
        route_key="target_segment",
        quote=answer,
    )


def test_project_statements_alone_ground_a_proposal_citing_statement_ids() -> None:
    """The trial's failure mode: everything the client said lives in ``project_state`` statements
    and nothing reached the Client KB. Synthesis must still be grounded — on the statements."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await _empty_client_kb(conn, "statements")
            kb = await read_client_kb_claims(
                conn, ref.client_entity_id, workspace_id=_CLIENT, version=ref.client_kb_version
            )
            assert kb == {}  # the defect's precondition: no versioned client claims at all

            answer = "We target neurosurgery practices in the US that run their own imaging."
            project_id, statement = await _record_project_statement(
                conn,
                suffix="alone",
                client_entity_id=ref.client_entity_id,
                answer=answer,
            )
            # the statement id is durable and queryable at the synthesis seam
            rows = await read_statements(conn, workspace_id=_CLIENT, project_id=project_id)
            assert [row.id for row in rows] == [statement.statement_id]

            result = await synthesize_icps(
                conn, ref, workspace_id=_CLIENT, project_statements=(statement,)
            )

            assert result.status is ICPSynthesisStatus.GROUNDED
            assert result.reason_codes == (NO_CLIENT_KB_CLAIMS,)
            (proposal,) = result.proposals
            assert proposal.justifying_claim_ids == ()  # honest: there are no client claims
            assert _all_justifying_statements(proposal) == {statement.statement_id}
            assert proposal.label == "Primary ICP (synthesized)"
            assert proposal.firmographic.field_keys  # still a complete, confirmable proposal
            assert proposal.rubric.weights
            # lineage is reference-only — the client's words are never copied into the proposal
            assert "neurosurgery" not in proposal.model_dump_json()

    run_async(_run())


def test_statements_reach_the_bounded_synthesis_prompt() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await _empty_client_kb(conn, "prompt")
            answer = "We only sell to neurosurgery practices."
            _, statement = await _record_project_statement(
                conn,
                suffix="prompt",
                client_entity_id=ref.client_entity_id,
                answer=answer,
            )
            gateway = FakeGateway("not json at all")
            await synthesize_icps(
                conn,
                ref,
                workspace_id=_CLIENT,
                project_statements=(statement,),
                gateway=gateway,
                synthesis_model="fake/model",
            )

            (_, messages) = gateway.calls[0]
            user = messages[-1].content
            assert answer in user
            assert str(statement.statement_id) in user

    run_async(_run())


def test_zero_evidence_returns_the_typed_not_ready_outcome() -> None:
    """No claims and no statements: the floor exists but is explicitly labelled ungrounded and the
    result says so, so a caller cannot present it as a normal numbered proposal."""

    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await _empty_client_kb(conn, "nothing")

            result = await synthesize_icps(conn, ref, workspace_id=_CLIENT)

            assert result.status is ICPSynthesisStatus.FLOOR_ONLY
            assert result.reason_codes == (NO_CLIENT_KB_CLAIMS, NO_PROJECT_STATEMENTS)
            (floor,) = result.proposals  # the ≥1-complete-proposal contract still holds
            assert floor.label == "Ungrounded baseline (no evidence)"
            assert floor.rationale is not None and "cites no evidence" in floor.rationale
            assert _all_justifying(floor) == set()
            assert _all_justifying_statements(floor) == set()

    run_async(_run())


def test_floor_proposal_has_all_six_elements() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await build_client_kb(
                conn, workspace_id=_CLIENT, suffix="floor", asserted=_ASSERTED
            )
            result = await synthesize_icps(conn, ref, workspace_id=_CLIENT)

            assert result.status is ICPSynthesisStatus.GROUNDED
            assert result.reason_codes == (NO_PROJECT_STATEMENTS,)
            assert len(result.proposals) >= 1
            p = result.proposals[0]
            # all six elements: 1 firmographic, 2 technographic (matched to data_infra from the
            # client prose), 3 two-tier signals, 4 seeds (M5.4's → empty), 5 source, 6 rubric
            assert p.firmographic.field_keys
            assert p.firmographic.industry == "data_infra"
            assert any(t.pack_key == "data_infra" for t in p.technographic)
            assert p.candidate_signals
            assert p.seed_accounts == ()
            assert p.source_profile.packs == ("data_infra",)
            assert p.rubric.weights

    run_async(_run())


def test_floor_justifying_ids_are_real_client_claims() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await build_client_kb(
                conn, workspace_id=_CLIENT, suffix="just", asserted=_ASSERTED
            )
            kb = await read_client_kb_claims(
                conn, ref.client_entity_id, workspace_id=_CLIENT, version=ref.client_kb_version
            )
            real_ids = {claim.id for claim in kb.values()}
            assert real_ids  # the KB is non-empty

            (proposal,) = (await synthesize_icps(conn, ref, workspace_id=_CLIENT)).proposals
            cited = _all_justifying(proposal)
            assert cited  # every proposal cites its evidence
            # no element is justified by an invented id — every citation is a real client claim
            assert cited <= real_ids

    run_async(_run())


def _two_icp_json() -> str:
    """An LLM response naming two ICPs, with off-set names sprinkled in to prove the hard guard."""
    return json.dumps(
        {
            "icps": [
                {
                    "icp_key": "enterprise",
                    "label": "Enterprise data infra",
                    "firmographic": {"industry": "data infra", "size_band": "enterprise"},
                    "firmographic_field_keys": ["core.employee_count", "core.bogus_field"],
                    "enabled_packs": ["data_infra", "nonexistent_pack"],
                    "technographic_field_keys": ["data_infra.migration_signal", "core.work_email"],
                    "candidate_signals": [
                        {
                            "signal_class": "funding",
                            "proxy_field_keys": ["account.recent_funding"],
                            "narrative_field_keys": ["account.operational_pain"],
                        }
                    ],
                    "rubric": {
                        "fit": [
                            {"field_key": "core.employee_count", "weight": 2.0},
                            {"field_key": "account.scoring.fit", "weight": 1.0},
                        ],
                        "intent": [{"field_key": "account.recent_funding", "weight": 3.0}],
                        "fit_threshold": 0.6,
                        "intent_threshold": 0.4,
                    },
                },
                {
                    "icp_key": "midmarket",
                    "label": "Mid-market",
                    "firmographic": {"industry": "data infra", "size_band": "mid-market"},
                    "firmographic_field_keys": ["core.employee_count"],
                    "enabled_packs": ["data_infra"],
                    "technographic_field_keys": ["data_infra.migration_signal"],
                    "candidate_signals": [
                        {"signal_class": "hiring", "proxy_field_keys": ["core.primary_tech_stack"]}
                    ],
                    "rubric": {
                        "fit": [{"field_key": "core.employee_count", "weight": 1.0}],
                        "intent": [],
                        "fit_threshold": 0.5,
                        "intent_threshold": 0.3,
                    },
                },
            ]
        }
    )


def test_llm_multi_icp_split_and_config_bounding() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await build_client_kb(
                conn, workspace_id=_CLIENT, suffix="multi", asserted=_ASSERTED
            )
            gateway = FakeGateway(_two_icp_json())
            proposals = (
                await synthesize_icps(
                    conn, ref, workspace_id=_CLIENT, gateway=gateway, synthesis_model="fake/model"
                )
            ).proposals

            assert len(proposals) == 2  # the LLM split into two ICPs (D5)
            assert {p.icp_key for p in proposals} == {"enterprise", "midmarket"}
            assert len(gateway.calls) == 1
            assert gateway.calls[0][0] == "fake/model"

            enterprise = next(p for p in proposals if p.icp_key == "enterprise")
            # the hard config guard: off-set field/pack names are dropped, never proposed
            assert "core.bogus_field" not in enterprise.firmographic.field_keys
            assert "core.employee_count" in enterprise.firmographic.field_keys
            assert enterprise.source_profile.packs == ("data_infra",)  # nonexistent_pack dropped
            techno_keys = {t.field_key for t in enterprise.technographic}
            assert "data_infra.migration_signal" in techno_keys
            assert "core.work_email" not in techno_keys  # not a data_infra pack field → dropped
            rubric_keys = {w.field_key for w in enterprise.rubric.weights}
            assert "account.scoring.fit" not in rubric_keys  # a score OUTPUT, not a scoring input
            assert "core.employee_count" in rubric_keys

    run_async(_run())


def test_out_of_registry_icp_concept_becomes_durable_proposal_ref() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await build_client_kb(
                conn, workspace_id=_CLIENT, suffix="open-schema", asserted=_ASSERTED
            )
            brand = await create_brand(conn, workspace_id=_CLIENT, name="Synthesis brand")
            scope = ProposalScope(workspace_id=_CLIENT, brand_id=brand.brand_id)
            response = json.dumps(
                {
                    "icps": [
                        {
                            "icp_key": "open_schema",
                            "firmographic_field_keys": [
                                "core.employee_count",
                                "account.partner_ecosystem_maturity",
                            ],
                            "new_field_concepts": [
                                {
                                    "field_key": "account.partner_ecosystem_maturity",
                                    "value_type": "str",
                                    "pass_kind": "scoring",
                                    "description": "Strength of the account partner ecosystem.",
                                    "rationale": "The client sells through alliance partners.",
                                },
                                {
                                    "field_key": "new_vertical.unsafe_signal",
                                    "value_type": "str",
                                    "pass_kind": "deep",
                                    "rationale": "A pack field without a declared reuse scope.",
                                },
                            ],
                        }
                    ]
                }
            )
            result = await synthesize_icps_with_proposals(
                conn,
                ref,
                workspace_id=_CLIENT,
                proposal_scope=scope,
                proposed_by_actor="agent",
                proposed_by_ref="thread:stage0",
                gateway=FakeGateway(response),
                synthesis_model="fake/model",
            )

            assert len(result.proposals) == 1
            assert (
                "account.partner_ecosystem_maturity"
                not in result.proposals[0].firmographic.field_keys
            )
            assert len(result.field_proposal_refs) == 2
            proposal_ref = next(
                ref for ref in result.field_proposal_refs if ref.status is ProposalStatus.PROPOSED
            )
            assert proposal_ref.field_key == "account.partner_ecosystem_maturity"
            stored = await get_field_proposal(conn, proposal_ref.proposal_id, workspace_id=_CLIENT)
            assert stored is not None
            assert stored.payload.description == "Strength of the account partner ecosystem."
            assert stored.payload.evidence_refs

            rejected_ref = next(
                ref for ref in result.field_proposal_refs if ref.status is ProposalStatus.REJECTED
            )
            rejected = await get_field_proposal(
                conn, rejected_ref.proposal_id, workspace_id=_CLIENT
            )
            assert rejected is not None
            assert rejected.decision_reason is not None
            assert "reuse_scope" in rejected.decision_reason
            assert rejected.payload.field_def.validation == {
                "rejected_input": {
                    "field_key": "new_vertical.unsafe_signal",
                    "value_type": "str",
                    "pass_kind": "deep",
                    "rationale": "A pack field without a declared reuse scope.",
                }
            }

            repeated = await synthesize_icps_with_proposals(
                conn,
                ref,
                workspace_id=_CLIENT,
                proposal_scope=scope,
                proposed_by_actor="agent",
                gateway=FakeGateway(response),
                synthesis_model="fake/model",
            )
            assert repeated.field_proposal_refs == result.field_proposal_refs

    run_async(_run())


def test_llm_failure_degrades_to_floor() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_CLIENT) as conn:
            ref = await build_client_kb(
                conn, workspace_id=_CLIENT, suffix="fail", asserted=_ASSERTED
            )

            # a raising gateway → the deterministic floor stands (never propagates the failure)
            raising = await synthesize_icps(
                conn,
                ref,
                workspace_id=_CLIENT,
                gateway=FakeGateway(raise_exc=True),
                synthesis_model="fake/model",
            )
            assert [p.icp_key for p in raising.proposals] == ["primary"]
            # a floor over a real Client KB is still grounded — it cites real claim ids
            assert raising.status is ICPSynthesisStatus.GROUNDED

            # unparseable output → floor
            garbage = await synthesize_icps(
                conn,
                ref,
                workspace_id=_CLIENT,
                gateway=FakeGateway("not json at all"),
                synthesis_model="fake/model",
            )
            assert [p.icp_key for p in garbage.proposals] == ["primary"]

            # a gateway with no model id is not used at all → floor
            no_model = await synthesize_icps(
                conn, ref, workspace_id=_CLIENT, gateway=FakeGateway(_two_icp_json())
            )
            assert [p.icp_key for p in no_model.proposals] == ["primary"]

    run_async(_run())
