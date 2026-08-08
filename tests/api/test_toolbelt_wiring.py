"""The concrete toolbelt — the out-of-order matrix (the step-2 de-risk) + the B1 workspace guard.

On a fresh workspace with only its required project context, every registered tool either raises
``PreconditionFailed`` with its documented ``reason_code`` — asserted as the **exact** reason tuple
(N3) — or succeeds with a real result: ``reverse_profile`` / ``estimate_project`` are
prerequisite-free, while ``start_project_run`` consumes the seeded project. Never a silent-empty
success (pre-mortem #2).
The matrix asserts the **full** registered tool list is covered, so a new tool without a matrix
entry fails the test.

The matrix binds a **real** :class:`~clue_research.durable.ProjectRun` machine over the savepoint
conn factory (S6/S7 — the Db stores thread the injected factory; the registry is an explicit empty
one), so ``start_project_run``'s success is the real ``ProjectRun.start`` path, and the B1
cross-workspace cases prove a run from another workspace refuses ``run_not_found`` (fail-closed, no
existence leak).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import (
    ContactResearchPolicyPin,
    ContactResearchSelection,
    ContactResearchSelectionBody,
    ContactResearchTarget,
    EntityType,
    ExtractionMethod,
    ICPCreatedFrom,
    ProjectRunId,
    ResearchDirectivePin,
    ResearchMode,
    discovery_claim,
    new_contact_research_selection_id,
    new_operation_id,
)
from clue_research.claimstore import insert_claim
from clue_research.discovery_scoring.phases import project_discovery_run_id
from clue_research.icp import (
    ScoringRubric,
    TierBand,
    TierCutoffs,
    create_icp_spec,
    rubric_to_slot,
)
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_research.stage0 import ICPProposal
from clue_toolbelt import PreconditionFailed, ToolContext, ToolResult, invoke_tool
from tests._workspace import seed_project, seed_workspace
from tests.api.conftest import require_profiling_db as require_profiling_db  # noqa: F401
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn, seed_packs

TTL = 86400.0
_UUID = lambda: str(uuid4())  # noqa: E731


def _matrix_contact_selection() -> ContactResearchSelection:
    account_id = uuid4()
    directive_id = uuid4()
    policy = ContactResearchPolicyPin()
    body = ContactResearchSelectionBody(
        workspace_id="matrix",
        project_id="project_missing",
        project_run_id=uuid4(),
        account_entity_id=account_id,
        research_directive=ResearchDirectivePin(
            directive_id=directive_id,
            directive_ref=f"research-directive:{directive_id}:v1",
            version=1,
            canonical_json_sha256="0" * 64,
            account_id=account_id,
        ),
        targets=(
            ContactResearchTarget(
                contact_entity_id=uuid4(),
                committee_claim_ids=(uuid4(),),
                strong_identity_claim_ids=(uuid4(),),
                field_keys=("contact.current_title",),
            ),
        ),
        policy=policy,
        source_profile_ref="source-profile:matrix",
        jurisdiction_policy_ref="jurisdiction:matrix",
        use_policy_ref="use:matrix",
        retention_policy_ref="retention:matrix",
        budget_reservation_ref="budget:matrix",
        approved_by="human:matrix",
        approved_at=datetime.now(UTC),
    )
    return ContactResearchSelection.from_body(
        body,
        effective_policy=policy,
        selection_id=new_contact_research_selection_id(),
    )


# tool -> ("precondition", exact reason tuple) | ("success", a required reference key)
_MATRIX: dict[str, tuple[str, object]] = {
    "reverse_profile": ("success", "client_entity_id"),
    "synthesize_icps": ("precondition", ("no_client_kb",)),
    "confirm_icp": ("precondition", ("no_client_kb",)),
    "import_accounts": ("precondition", ("no_active_icp",)),
    "discover_accounts": ("precondition", ("run_not_found",)),
    "score_accounts": ("precondition", ("run_not_found",)),
    "enrich_selected_accounts": (
        "precondition",
        ("entity_research_agent_not_composed",),
    ),
    "enrich_account_gaps": (
        "precondition",
        ("entity_research_agent_not_composed",),
    ),
    "submit_tier_checkpoint": ("precondition", ("run_not_found",)),
    "submit_project_checkpoint": ("precondition", ("run_not_found",)),
    "launch_account_deep": (
        "precondition",
        ("entity_research_agent_not_composed",),
    ),
    # M8D R10: the promoted entity-research launch/read tools refuse fail-closed when the fleet
    # services are not composed (this matrix builds the toolbelt without them).
    "launch_account_research": (
        "precondition",
        ("entity_research_agent_not_composed",),
    ),
    "launch_contact_research": (
        "precondition",
        ("entity_research_agent_not_composed",),
    ),
    "read_account_research_run": (
        "precondition",
        ("entity_research_agent_not_composed",),
    ),
    "read_contact_research_run": (
        "precondition",
        ("entity_research_agent_not_composed",),
    ),
    "run_deep_account": ("precondition", ("entity_research_agent_not_composed",)),
    "resolve_committee": ("precondition", ("entity_research_agent_not_composed",)),
    "profile_contact": ("precondition", ("entity_research_agent_not_composed",)),
    "run_verification": ("precondition", ("run_not_found",)),
    "compose_handoff": ("precondition", ("run_not_found",)),
    "compose_contact_content_handoff": (
        "precondition",
        ("contact_content_handoff_not_composed",),
    ),
    "approve_contact_research_selection": (
        "precondition",
        ("entity_research_agent_not_composed",),
    ),
    "compose_dossier": ("precondition", ("research_view_feature_disabled",)),
    "get_research_view": ("precondition", ("research_view_feature_disabled",)),
    "recheck_research_view": ("precondition", ("research_view_feature_disabled",)),
    # PC-C8 §7: `build_toolbelt(storage=None)` composes no evidence reader, so the statement tool
    # refuses fail-closed rather than serving quote-less rows; the readiness tool needs no reader
    # and refuses on scope, which is the guard that actually matters for it.
    "inspect_statement_history": ("precondition", ("statement_evidence_not_configured",)),
    "inspect_readiness_history": ("precondition", ("stage0_project_not_found",)),
    "estimate_project": ("success", "estimated_cost_cents"),
    "start_project_run": ("success", "project_run_id"),
    "pause_run": ("precondition", ("run_not_found",)),
    "resume_run": ("precondition", ("run_not_found",)),
    "adjust_budget": ("precondition", ("run_not_found",)),
    "research_account_gaps": (
        "precondition",
        ("entity_research_agent_not_composed",),
    ),
    "propose_field": ("precondition", ("proposal_scope_not_found",)),
    "decide_field_proposal": ("precondition", ("proposal_not_found",)),
    "propose_source": ("precondition", ("proposal_scope_not_found",)),
    "decide_source_proposal": ("precondition", ("proposal_not_found",)),
    "submit_ingestion": ("precondition", ("ingestion_artifact_not_found",)),
    "retry_ingestion": ("precondition", ("ingestion_not_found",)),
    "submit_onboarding_input": ("precondition", ("artifact_not_found",)),
    "start_recon": ("precondition", ("onboarding_input_not_found",)),
    "record_interview_answer": ("precondition", ("onboarding_input_not_found",)),
    "confirm_project_product": ("precondition", ("project_product_not_found",)),
    "evaluate_stage0_readiness": ("precondition", ("stage0_scope_not_found",)),
    "override_stage0_readiness": ("precondition", ("readiness_not_found",)),
    "start_confirmed_project_run": (
        "precondition",
        ("confirmed_stage0_context_not_found",),
    ),
    "draft_account_research_directive": (
        "precondition",
        ("memory_write_not_configured",),
    ),
    "confirm_account_research_directive": (
        "precondition",
        ("research_directive_not_found",),
    ),
}


def _bodies() -> dict[str, dict[str, object]]:
    return {
        "reverse_profile": {"name": "Acme Robotics", "website": "https://acme.example"},
        "synthesize_icps": {"client_entity_id": _UUID()},
        "confirm_icp": {
            "client_entity_id": _UUID(),
            "proposal": ICPProposal(icp_key="matrix").model_dump(mode="json"),
        },
        "import_accounts": {"client_entity_id": _UUID(), "icp_key": "matrix", "rows": []},
        "discover_accounts": {"project_run_id": _UUID()},
        "score_accounts": {"project_run_id": _UUID()},
        "enrich_selected_accounts": {
            "project_run_id": _UUID(),
            "account_entity_ids": [_UUID()],
            "field_keys": ["core.company_linkedin_url"],
        },
        "enrich_account_gaps": {
            "project_run_id": _UUID(),
            "account_entity_id": _UUID(),
            "field_expected_value_credits": {"core.employee_count": "2"},
            "provider_credit_cap": 2,
        },
        "submit_tier_checkpoint": {"project_run_id": _UUID()},
        "submit_project_checkpoint": {"project_run_id": _UUID()},
        "launch_account_deep": {
            "project_run_id": _UUID(),
            "research_directive_id": _UUID(),
            "account_entity_ids": [_UUID()],
            "approved_budget_cap_cents": "1",
            "expected_estimated_cost_cents": "1",
        },
        "launch_account_research": {
            "project_run_id": _UUID(),
            "research_directive_id": _UUID(),
            "account_entity_ids": [_UUID()],
            "approved_budget_cap_cents": "1",
            "expected_estimated_cost_cents": "1",
        },
        "launch_contact_research": {
            "selection_id": _UUID(),
            "selection_sha256": "0" * 64,
            "approved_budget_cap_cents": "1",
            "expected_estimated_cost_cents": "1",
            "confirmed_at": "2026-08-06T00:00:00+00:00",
        },
        "read_account_research_run": {"research_run_id": _UUID()},
        "read_contact_research_run": {"research_run_id": _UUID()},
        "run_deep_account": {"account_entity_id": _UUID(), "icp_key": "matrix", "tier": "top"},
        "resolve_committee": {"account_entity_id": _UUID()},
        "profile_contact": {
            "project_run_id": _UUID(),
            "contact_entity_id": _UUID(),
            "account_entity_id": _UUID(),
        },
        "run_verification": {"project_run_id": _UUID()},
        "compose_handoff": {"project_run_id": _UUID()},
        "compose_contact_content_handoff": {
            "project_id": "project_missing",
            "project_run_id": _UUID(),
            "account_entity_id": _UUID(),
        },
        # M8D R10: the name default is the R7 entity-research approver (@2); the M8C selection
        # tool remains version-addressable as @1 for its historical surface.
        "approve_contact_research_selection": {
            "request": {
                "workspace_id": "ws-matrix",
                "project_run_id": _UUID(),
                "account_run_id": _UUID(),
                "account_entity_id": _UUID(),
                "targets": [
                    {
                        "contact_entity_id": _UUID(),
                        "selection_basis": "committee_member",
                        "strong_identity_claim_ids": [_UUID()],
                        "association_evidence_claim_ids": [_UUID()],
                        "committee_claim_ids": [_UUID()],
                        "field_keys": ["contact.current_title"],
                        "field_source_authority": [
                            {
                                "field_key": "contact.current_title",
                                "source_keys": ["exa_deep"],
                            }
                        ],
                        "directional_question_ids": ["q-matrix-1"],
                        "budget_cap_cents": "10",
                    }
                ],
            },
            "approved_at": "2026-08-06T00:00:00+00:00",
        },
        "compose_dossier": {
            "project_id": "project_missing",
            "project_run_id": _UUID(),
            "subject_entity_id": _UUID(),
        },
        "get_research_view": {
            "project_id": "project_missing",
            "project_run_id": _UUID(),
            "subject_entity_id": _UUID(),
        },
        "recheck_research_view": {
            "project_id": "project_missing",
            "subject_entity_id": _UUID(),
            "snapshot_id": _UUID(),
        },
        "inspect_statement_history": {"project_id": "project_missing"},
        "inspect_readiness_history": {"project_id": "project_missing"},
        "estimate_project": {},
        "start_project_run": {
            "project_id": "prj_replaced_by_test",
            "icp_key": "matrix",
            "icp_version": 1,
        },
        "pause_run": {"project_run_id": _UUID()},
        "resume_run": {"project_run_id": _UUID()},
        "adjust_budget": {"project_run_id": _UUID(), "budget_cap_cents": 1000},
        "research_account_gaps": {
            "project_run_id": _UUID(),
            "account_entity_id": _UUID(),
            "tier": "top",
            "gap_fields": ["account.strategic_moves"],
        },
        "propose_field": {
            "brand_id": "brand_missing",
            "scope": {},
            "payload": {
                "field_def": {
                    "field_key": "account.proposed_signal",
                    "value_type": "str",
                    "pass_kind": "deep",
                },
                "rationale": "matrix proposal",
            },
        },
        "decide_field_proposal": {
            "field_proposal_id": _UUID(),
            "decision": "reject",
            "reason": "matrix decision",
        },
        "propose_source": {
            "brand_id": "brand_missing",
            "scope": {},
            "payload": {
                "manifest": {
                    "source_key": "matrix_source",
                    "modality": "text",
                    "entity_scope": "account",
                    "yields": ["account"],
                },
                "discovery_url": "https://source.example",
                "discovery_domain": "source.example",
                "capability_description": "matrix source",
                "rationale": "matrix proposal",
            },
        },
        "decide_source_proposal": {
            "source_proposal_id": _UUID(),
            "decision": "reject",
            "reason": "matrix decision",
        },
        "submit_ingestion": {
            "artifact_key": "missing-artifact",
            "brand_id": "brand_missing",
            "declared_context": {},
        },
        "retry_ingestion": {"ingestion_job_id": _UUID()},
        "submit_onboarding_input": {
            "brand_id": "brand_missing",
            "kind": "website",
            "artifact_key": "missing-artifact",
            "content_sha256": "0" * 64,
        },
        "start_recon": {
            "brand_id": "brand_missing",
            "name": "Acme",
            "website": "https://acme.example",
            "onboarding_input_ids": [_UUID()],
        },
        "record_interview_answer": {
            "brand_id": "brand_missing",
            "onboarding_input_id": _UUID(),
            "artifact_key": "missing-artifact",
            "answer": "hello",
            "client_entity_id": _UUID(),
            "statements": [],
        },
        "confirm_project_product": {
            "project_id": "project_missing",
            "product_id": "product_missing",
        },
        "evaluate_stage0_readiness": {
            "brand_id": "brand_missing",
            "gate": "icp_synthesis",
            "metrics": {},
        },
        "override_stage0_readiness": {
            "readiness_decision_id": _UUID(),
            "gate": "icp_synthesis",
            "reason": "matrix",
        },
        "start_confirmed_project_run": {
            "project_id": "project_missing",
            "client_entity_id": _UUID(),
            "client_kb_version": 1,
            "product_id": "product_missing",
            "product_context_version_id": _UUID(),
            "readiness_decision_id": _UUID(),
            "icp_key": "matrix",
            "icp_version": 1,
        },
        "draft_account_research_directive": {
            "project_id": "project_missing",
            "product_id": "product_missing",
            "icp_key": "matrix",
            "icp_version": 1,
            "body": {
                "account_scope": {"explicit_account_ids": [_UUID()]},
                "field_keys": ["account.strategic_moves"],
                "committee_plan": {},
                "source_policy": {"allowed_source_keys": ["exa_deep"]},
                "privacy_policy": {},
                "effort_policy": {
                    "tier": "top",
                    "max_depth": 1,
                    "max_fanout": 2,
                    "budget_cap_cents": "100",
                    "budget_envelope_ref": "budget:matrix",
                    "recursion_policy_ref": "recursion:matrix",
                    "freshness_policy_ref": "freshness:matrix",
                },
            },
            "user_instruction": "Research the named account.",
            "source_turn_ref": "turn:matrix",
        },
        "confirm_account_research_directive": {
            "directive_id": _UUID(),
            "expected_sha256": "0" * 64,
        },
    }


def test_out_of_order_matrix(require_profiling_db: None) -> None:  # noqa: F811
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            await seed_packs(conn)  # core + deep + committee; stage-0 packs load below
            from clue_api.composition import load_research_packs

            await load_research_packs(conn)  # client-KB / ICP / import packs (idempotent)
            cf = conn_session_factory(conn)
            # S6/S7: NO injected run_machine — the default is a REAL ProjectRun over Db stores
            # threaded with the savepoint factory + an explicit empty PhaseHandlerRegistry, so
            # start_project_run below is the real ProjectRun.start path (rolled back with the test).
            registry = build_toolbelt(
                storage=None,
                gateway=None,  # spend tools are blocked by preconditions; invoke never reached
                conn_factory=cf,
            )
            ws = await seed_workspace(conn, f"ws_{uuid4().hex[:8]}")
            project = await seed_project(conn, ws)
            ctx = ToolContext(
                workspace_id=ws,
                actor="human",
                principal_kind="human",
                actor_id="human:matrix",
                membership_id="wsm_matrix",
                action_ref="turn:matrix-confirm",
                conn_factory=cf,
                operation_id=new_operation_id(),
            )
            bodies = _bodies()
            bodies["start_project_run"]["project_id"] = project.project_id

            # Coverage: every registered tool has a matrix entry (a new tool without one fails).
            assert set(registry.names()) == set(_MATRIX), (
                f"matrix/registry drift: {set(registry.names()) ^ set(_MATRIX)}"
            )

            for name in registry.names():
                kind, expected = _MATRIX[name]
                if kind == "success":
                    result = await invoke_tool(
                        registry, name, bodies[name], ctx, idempotency_ttl_s=TTL
                    )
                    assert isinstance(result, ToolResult)
                    assert isinstance(expected, str)
                    assert expected in result.references, f"{name}: missing ref {expected!r}"
                else:
                    with pytest.raises(PreconditionFailed) as ei:
                        await invoke_tool(registry, name, bodies[name], ctx, idempotency_ttl_s=TTL)
                    # N3: the EXACT reason tuple, not membership.
                    assert ei.value.reason_codes == expected, (
                        f"{name}: expected {expected!r}, got {ei.value.reason_codes}"
                    )

    run_async(scenario())


def test_cross_workspace_run_access_refuses_run_not_found(  # noqa: F811
    require_profiling_db: None,
) -> None:
    """B1 (the proven cross-tenant mutation): a run started in ws_A refuses every run-scoped tool
    invoked from ws_B with ``run_not_found`` — fail-closed, indistinguishable from a non-existent
    run (no existence leak) — while the same tools from ws_A see the run."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            await seed_packs(conn)
            from clue_api.composition import load_research_packs

            await load_research_packs(conn)
            cf = conn_session_factory(conn)
            registry = build_toolbelt(storage=None, gateway=None, conn_factory=cf)
            project_a = await seed_project(conn, "ws_A")
            await seed_project(conn, "ws_B")
            ctx_a = ToolContext(
                workspace_id="ws_A",
                actor="human",
                conn_factory=cf,
                operation_id=new_operation_id(),
            )
            ctx_b = ToolContext(
                workspace_id="ws_B",
                actor="human",
                conn_factory=cf,
                operation_id=new_operation_id(),
            )

            start_body = {
                "project_id": project_a.project_id,
                "icp_key": "matrix",
                "icp_version": 1,
            }
            start_tool = registry.get("start_project_run")
            foreign_failures = await start_tool.preconditions(
                start_tool.input_model(**start_body), ctx_b
            )
            assert tuple(f.reason_code for f in foreign_failures) == ("project_not_found",)

            started = await invoke_tool(
                registry,
                "start_project_run",
                start_body,
                ctx_a,
                idempotency_ttl_s=TTL,
            )
            run_id = started.references["project_run_id"]
            assert run_id == str(ctx_a.operation_id)
            replayed_start = await invoke_tool(
                registry,
                "start_project_run",
                start_body,
                ctx_a,
                idempotency_ttl_s=TTL,
            )
            assert replayed_start.references["project_run_id"] == run_id

            # From ws_B every run-scoped mutation refuses run_not_found (the exact tuple).
            cases: dict[str, dict[str, object]] = {
                "pause_run": {"project_run_id": run_id},
                "adjust_budget": {"project_run_id": run_id, "budget_cap_cents": 500},
                "submit_tier_checkpoint": {"project_run_id": run_id},
                "score_accounts": {"project_run_id": run_id},
                "discover_accounts": {"project_run_id": run_id},
                "run_verification": {"project_run_id": run_id},
                "compose_handoff": {"project_run_id": run_id},
                "resume_run": {"project_run_id": run_id},
            }
            for name, body in cases.items():
                with pytest.raises(PreconditionFailed) as ei:
                    await invoke_tool(registry, name, body, ctx_b, idempotency_ttl_s=TTL)
                assert ei.value.reason_codes == ("run_not_found",), (
                    f"{name}: expected run_not_found from another workspace, "
                    f"got {ei.value.reason_codes}"
                )

            # Control: the OWNING workspace is not refused run_not_found — pause_run succeeds, and
            # score_accounts refuses on the owning run's actual phase, proving the ws_B refusals
            # above were scope-driven, not absence-driven.
            paused = await invoke_tool(
                registry, "pause_run", {"project_run_id": run_id}, ctx_a, idempotency_ttl_s=TTL
            )
            assert paused.references["status"] == "paused"
            with pytest.raises(PreconditionFailed) as ei:
                await invoke_tool(
                    registry,
                    "score_accounts",
                    {"project_run_id": run_id},
                    ctx_a,
                    idempotency_ttl_s=TTL,
                )
            assert ei.value.reason_codes == ("project_phase_not_scoring",)

    run_async(scenario())


def test_score_accounts_refuses_discovery_even_when_admitted_accounts_exist(
    require_profiling_db: None,
) -> None:
    """Regression for the D5 crash window: seal/membership alone never authorizes scoring."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            await seed_packs(conn)
            from clue_api.composition import load_research_packs

            await load_research_packs(conn)
            cf = conn_session_factory(conn)
            registry = build_toolbelt(storage=None, gateway=None, conn_factory=cf)
            workspace_id = await seed_workspace(conn, f"ws_phase_{uuid4().hex[:8]}")
            project = await seed_project(conn, workspace_id)
            ctx = ToolContext(
                workspace_id=workspace_id,
                actor="human",
                conn_factory=cf,
                operation_id=new_operation_id(),
            )
            started = await invoke_tool(
                registry,
                "start_project_run",
                {
                    "project_id": project.project_id,
                    "icp_key": "matrix",
                    "icp_version": 1,
                },
                ctx,
                idempotency_ttl_s=TTL,
            )
            run_id = ProjectRunId(UUID(started.references["project_run_id"]))
            await conn.execute(
                text(
                    "UPDATE project_run SET phase = 'discovery', status = 'active' WHERE id = :id"
                ),
                {"id": run_id},
            )
            account_id = await insert_account_entity(
                conn,
                canonical_name="Already admitted",
                primary_domain="admitted.example",
                workspace_id=workspace_id,
            )
            await insert_claim(
                conn,
                discovery_claim(
                    entity_id=account_id,
                    entity_type=EntityType.ACCOUNT,
                    field_key="core.discovery_provenance",
                    value_json={
                        "matched_channel": "exa_websets",
                        "matched_signal": "admitted",
                        "discovery_confidence": 0.9,
                    },
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    confidence=0.9,
                    run_id=project_discovery_run_id(
                        project_run_id=run_id,
                        icp_key="matrix",
                        icp_version=1,
                    ),
                    research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                    found_via="exa_websets",
                    matched_signal="admitted",
                    discovery_confidence=0.9,
                    source_url="https://admitted.example",
                ),
            )

            tool = registry.get("score_accounts")
            inputs = tool.input_model(project_run_id=str(run_id))
            failures = await tool.preconditions(inputs, ctx)
            assert tuple(value.reason_code for value in failures) == ("project_phase_not_scoring",)
            with pytest.raises(PreconditionFailed) as exc:
                await tool.invoke(inputs, ctx)
            assert exc.value.reason_codes == ("project_phase_not_scoring",)

    run_async(scenario())


def test_quarantined_account_tools_never_reach_legacy_workspace_scope(  # noqa: F811
    require_profiling_db: None,
) -> None:
    """R1 quarantine runs before every retired account/contact research precondition.

    New calls must not regain the legacy entity loaders simply because the supplied identity is
    valid. Exact selection/locality enforcement belongs to the replacement entity-agent launch;
    until it is composed, both valid and foreign ids fail with the same loud quarantine reason.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            await seed_packs(conn)
            from clue_api.composition import load_research_packs

            await load_research_packs(conn)
            cf = conn_session_factory(conn)
            registry = build_toolbelt(storage=None, gateway=None, conn_factory=cf)
            ws_a = await seed_workspace(conn, "ws_scope_a")
            ws_b = await seed_workspace(conn, "ws_scope_b")
            ctx = ToolContext(
                workspace_id=ws_a,
                actor="human",
                conn_factory=cf,
                operation_id=new_operation_id(),
            )

            # An active ICP under ws_a with a rubric carrying the "high" tier band, so
            # run_deep_account's earlier preconditions (resolvable spec + known tier) pass and it
            # actually reaches the account guard.
            rubric = ScoringRubric(
                tier_cutoffs=TierCutoffs(
                    bands=(TierBand(tier="high", min_fit=0.4, min_intent=0.5),)
                )
            )
            await create_icp_spec(
                conn,
                workspace_id=ws_a,
                icp_key="seg",
                created_from=ICPCreatedFrom.SYNTHESIS,
                scoring_rubric=rubric_to_slot(rubric),
                activate=True,
            )

            acc_a = await insert_account_entity(
                conn, canonical_name="In-WS", primary_domain="a.example", workspace_id=ws_a
            )
            acc_b = await insert_account_entity(
                conn, canonical_name="Other-WS", primary_domain="b.example", workspace_id=ws_b
            )
            # A contact under the in-workspace account so profile_contact's accepted case fully
            # passes (its account guard runs before the contact check).
            contact_a = await insert_contact_entity(
                conn, account_entity_id=acc_a, full_name="Jo Doe"
            )

            def body(name: str, account_id: str) -> dict[str, object]:
                return {
                    "run_deep_account": {
                        "account_entity_id": account_id,
                        "icp_key": "seg",
                        "tier": "high",
                    },
                    "resolve_committee": {"account_entity_id": account_id},
                    "profile_contact": {
                        "contact_entity_id": str(contact_a),
                        "account_entity_id": account_id,
                        "tier": "high",
                    },
                }[name]

            async def codes(name: str, account_id: str) -> tuple[str, ...]:
                tool = registry.get(name, "1") if name == "profile_contact" else registry.get(name)
                failures = await tool.preconditions(tool.input_model(**body(name, account_id)), ctx)
                return tuple(f.reason_code for f in failures)

            for name in ("run_deep_account", "resolve_committee", "profile_contact"):
                assert await codes(name, str(acc_a)) == ("entity_research_agent_not_composed",), (
                    name
                )
                assert await codes(name, str(acc_b)) == ("entity_research_agent_not_composed",), (
                    name
                )

    run_async(scenario())


def test_quarantined_profile_contact_never_reaches_legacy_contact_scope(  # noqa: F811
    require_profiling_db: None,
) -> None:
    """R1 prevents valid or cross-account contacts from entering the retired research path."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            await seed_packs(conn)
            from clue_api.composition import load_research_packs

            await load_research_packs(conn)
            cf = conn_session_factory(conn)
            registry = build_toolbelt(storage=None, gateway=None, conn_factory=cf)
            ws_a = await seed_workspace(conn, "ws_pc_a")
            ws_b = await seed_workspace(conn, "ws_pc_b")
            ctx = ToolContext(
                workspace_id=ws_a,
                actor="human",
                conn_factory=cf,
                operation_id=new_operation_id(),
            )

            acc_a = await insert_account_entity(
                conn, canonical_name="In-WS", primary_domain="pca.example", workspace_id=ws_a
            )
            acc_b = await insert_account_entity(
                conn, canonical_name="Other-WS", primary_domain="pcb.example", workspace_id=ws_b
            )
            # A contact under the in-workspace account (accepted) and one under the
            # foreign-workspace account (must be refused when profiled against acc_a).
            contact_a = await insert_contact_entity(
                conn, account_entity_id=acc_a, full_name="Jo Doe"
            )
            contact_b = await insert_contact_entity(
                conn, account_entity_id=acc_b, full_name="Kai Roe"
            )

            tool = registry.get("profile_contact", "1")

            async def codes(contact_id: str, account_id: str) -> tuple[str, ...]:
                failures = await tool.preconditions(
                    tool.input_model(
                        contact_entity_id=contact_id,
                        account_entity_id=account_id,
                        tier="high",
                    ),
                    ctx,
                )
                return tuple(f.reason_code for f in failures)

            assert await codes(str(contact_a), str(acc_a)) == (
                "entity_research_agent_not_composed",
            )
            assert await codes(str(contact_b), str(acc_a)) == (
                "entity_research_agent_not_composed",
            )

    run_async(scenario())


def test_build_toolbelt_registers_the_full_set() -> None:
    """Registry construction is DB-free (preconditions/invoke touch the DB, construction does not),
    so the full set is assertable without a database."""
    registry = build_toolbelt(storage=None, gateway=None)
    assert set(registry.names()) == set(_MATRIX)
    # 35 → 37 names with PC-C8's two read-only inspection tools, then 38 with E1's explicit
    # targeted-enrichment boundary, 39 with S1's explicit Sumble gap boundary, and 41 with A2's
    # draft/human-confirm direction tools; proposal writes, research_account_gaps, and the A2
    # tools retain @1 replay contracts alongside their current @2 contracts; O2 adds the exact-set
    # account-deep launch boundary; M8D R10 adds the promoted separately confirmed
    # launch_account_research / launch_contact_research and their two run-read tools (44 → 48).
    assert len(registry.names()) == 48
    # C6 keeps profile_contact@1 for immutable historical pins and elects the governed,
    # project-run-scoped profile_contact@2 as the name-only default.
    assert len(registry) == 55
    assert registry.descriptor("profile_contact").version == "2"
    assert registry.descriptor("profile_contact", "1").version == "1"
    assert {
        item.address for item in registry.all_descriptors() if item.name == "research_account_gaps"
    } == {
        "research_account_gaps@1",
        "research_account_gaps@2",
    }
    assert registry.descriptor("draft_account_research_directive").version == "2"
    assert registry.descriptor("confirm_account_research_directive").version == "2"


def test_duplicate_tool_registration_is_impossible_by_construction() -> None:
    # build_toolbelt registers each tool type exactly once; a second build is an independent
    # registry (no shared mutable state), so two builds never collide.
    a = build_toolbelt(storage=None, gateway=None)
    b = build_toolbelt(storage=None, gateway=None)
    assert a is not b
    assert a.names() == b.names()
