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

from uuid import uuid4

import pytest

from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import ICPCreatedFrom
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


# tool -> ("precondition", exact reason tuple) | ("success", a required reference key)
_MATRIX: dict[str, tuple[str, object]] = {
    "reverse_profile": ("success", "client_entity_id"),
    "synthesize_icps": ("precondition", ("no_client_kb",)),
    "confirm_icp": ("precondition", ("no_client_kb",)),
    "import_accounts": ("precondition", ("no_active_icp",)),
    "discover_accounts": ("precondition", ("run_not_found",)),
    "score_accounts": ("precondition", ("run_not_found",)),
    "submit_tier_checkpoint": ("precondition", ("run_not_found",)),
    "run_deep_account": ("precondition", ("no_active_icp",)),
    "resolve_committee": ("precondition", ("account_not_found",)),
    "profile_contact": ("precondition", ("account_not_found",)),
    "run_verification": ("precondition", ("run_not_found",)),
    "compose_handoff": ("precondition", ("run_not_found",)),
    "estimate_project": ("success", "estimated_cost_cents"),
    "start_project_run": ("success", "project_run_id"),
    "pause_run": ("precondition", ("run_not_found",)),
    "resume_run": ("precondition", ("run_not_found",)),
    "adjust_budget": ("precondition", ("run_not_found",)),
    "research_account_gaps": ("precondition", ("run_not_found",)),
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
        "submit_tier_checkpoint": {"project_run_id": _UUID()},
        "run_deep_account": {"account_entity_id": _UUID(), "icp_key": "matrix", "tier": "top"},
        "resolve_committee": {"account_entity_id": _UUID()},
        "profile_contact": {
            "contact_entity_id": _UUID(),
            "account_entity_id": _UUID(),
            "tier": "top",
        },
        "run_verification": {"project_run_id": _UUID()},
        "compose_handoff": {"project_run_id": _UUID()},
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
            "scope": {"brand_id": "brand_missing"},
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
            "scope": {"brand_id": "brand_missing"},
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
            "declared_context": {"brand_id": "brand_missing"},
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
            ctx = ToolContext(workspace_id=ws, actor="human", conn_factory=cf)
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
            ctx_a = ToolContext(workspace_id="ws_A", actor="human", conn_factory=cf)
            ctx_b = ToolContext(workspace_id="ws_B", actor="human", conn_factory=cf)

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
            # score_accounts refuses on its real next precondition (discovery_not_run), proving the
            # ws_B refusals above were scope-driven, not absence-driven.
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
            assert ei.value.reason_codes == ("discovery_not_run",)

    run_async(scenario())


def test_account_tools_fail_closed_on_workspace_scope(  # noqa: F811
    require_profiling_db: None,
) -> None:
    """[B3×research] slice 4 — the account guard is fail-closed, not a warning. The three
    account-scoped spend tools (``run_deep_account`` / ``resolve_committee`` / ``profile_contact``)
    load the account through ``_load_account``, so an account in another workspace refuses
    ``account_not_found``, indistinguishable from a truly-absent id (no existence leak), while an
    in-workspace account passes the guard."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            await seed_packs(conn)
            from clue_api.composition import load_research_packs

            await load_research_packs(conn)
            cf = conn_session_factory(conn)
            registry = build_toolbelt(storage=None, gateway=None, conn_factory=cf)
            ws_a = await seed_workspace(conn, "ws_scope_a")
            ws_b = await seed_workspace(conn, "ws_scope_b")
            ctx = ToolContext(workspace_id=ws_a, actor="human", conn_factory=cf)

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
                tool = registry.get(name)
                failures = await tool.preconditions(tool.input_model(**body(name, account_id)), ctx)
                return tuple(f.reason_code for f in failures)

            for name in ("run_deep_account", "resolve_committee", "profile_contact"):
                # In-workspace → the account guard passes (no account_not_found refusal).
                assert "account_not_found" not in await codes(name, str(acc_a)), name
                # Cross-workspace → refused exactly as an unknown id (no existence leak).
                assert await codes(name, str(acc_b)) == ("account_not_found",), name

    run_async(scenario())


def test_profile_contact_refuses_cross_account_contact(  # noqa: F811
    require_profiling_db: None,
) -> None:
    """[B3×research] slice 4 — ``profile_contact`` profiles a committee member *of* the loaded
    in-workspace account, so the contact must belong to that account. A contact under a *different*
    account (and/or a different workspace) is refused ``contact_not_found`` — the same shape a
    truly-absent id gets (no existence leak), even though the caller holds a valid in-workspace
    account id. The happy path (contact under the in-workspace account) still passes cleanly."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            await seed_packs(conn)
            from clue_api.composition import load_research_packs

            await load_research_packs(conn)
            cf = conn_session_factory(conn)
            registry = build_toolbelt(storage=None, gateway=None, conn_factory=cf)
            ws_a = await seed_workspace(conn, "ws_pc_a")
            ws_b = await seed_workspace(conn, "ws_pc_b")
            ctx = ToolContext(workspace_id=ws_a, actor="human", conn_factory=cf)

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

            tool = registry.get("profile_contact")

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

            # Happy path: contact under the in-workspace account → the contact guard passes.
            assert "contact_not_found" not in await codes(str(contact_a), str(acc_a))
            # A contact belonging to a *different* account/workspace, profiled against the
            # in-workspace account → refused exactly as an unknown contact (no existence leak).
            assert await codes(str(contact_b), str(acc_a)) == ("contact_not_found",)

    run_async(scenario())


def test_build_toolbelt_registers_the_full_set() -> None:
    """Registry construction is DB-free (preconditions/invoke touch the DB, construction does not),
    so the full set is assertable without a database."""
    registry = build_toolbelt(storage=None, gateway=None)
    assert set(registry.names()) == set(_MATRIX)
    assert len(registry) == 31


def test_duplicate_tool_registration_is_impossible_by_construction() -> None:
    # build_toolbelt registers each tool type exactly once; a second build is an independent
    # registry (no shared mutable state), so two builds never collide.
    a = build_toolbelt(storage=None, gateway=None)
    b = build_toolbelt(storage=None, gateway=None)
    assert a is not b
    assert a.names() == b.names()
