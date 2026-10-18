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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

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
    "synthesize_icps": ("precondition", ("stage0_scope_not_found",)),
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
    "launch_selected_account_research": (
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
    "list_client_knowledge": ("precondition", ("client_knowledge_unavailable",)),
    "inspect_client_claim": ("precondition", ("client_knowledge_unavailable",)),
    "list_product_knowledge": ("precondition", ("product_knowledge_unavailable",)),
    "inspect_product_claim": ("precondition", ("product_knowledge_unavailable",)),
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
    # FI Lane D D0 / REQ-21. The thread tools are prerequisite-free *given* their subject, so their
    # out-of-order case is a subject that does not exist in this workspace — which must be a typed
    # refusal, never a 500 and never a silent write into somebody else's tenant.
    "create_thread": ("precondition", ("project_not_found",)),
    "rename_thread": ("precondition", ("thread_not_found",)),
    "rename_project": ("precondition", ("project_not_found",)),
    # Projects directory (2026-09-19). Same shape: the subject that does not exist in this
    # workspace — a brand for the creator, a project for the three mutators.
    "create_project": ("precondition", ("brand_not_found",)),
    "update_project_details": ("precondition", ("project_not_found",)),
    "set_project_pinned": ("precondition", ("project_not_found",)),
    "set_project_archived": ("precondition", ("project_not_found",)),
    "set_thread_pinned": ("precondition", ("thread_not_found",)),
    "archive_thread": ("precondition", ("thread_not_found",)),
    # FI Lane D D4 / §3-P5(a). The gate tool's first prerequisite is the *turn* it would address the
    # gate to: a ref naming no turn of this workspace proves no addressee, so it refuses rather than
    # presenting a gate nobody is entitled to answer.
    # The thread-wedge guard (adversarial-review fix): under the hermetic env the design
    # runtime is off, and a leg opened on such a deployment is a thread nothing can serve —
    # so the runtime refusal outranks the storage one.
    "finish_design_leg": ("precondition", ("design_leg_runtime_not_configured",)),
    "open_design_leg": ("precondition", ("design_leg_runtime_not_configured",)),
    "open_directive_confirmation_gate": ("precondition", ("gate_turn_not_found",)),
    # ARV2 onboarding O6: the default ICP gate is `@2`, whose subject is a brand-knowledge document
    # named by `icp_key`. It resolves the presenting turn before anything else, so with a random
    # turn ref the first fail-closed boundary is the turn lookup — the same one the directive
    # gate hits. (`@1` resolved the execution-bound Stage-0 scope first; it stays registered,
    # non-default, for replay.)
    "open_icp_confirmation_gate": ("precondition", ("gate_turn_not_found",)),
    # Automatic project targeting (head-of-abm@v61, base): the matrix composes no turn, so the
    # turn the body names is its first fail-closed boundary.
    "configure_project_targeting": ("precondition", ("targeting_turn_unavailable",)),
    # Product management (head-of-abm@v71): the matrix composes no storage, so the missing
    # document storage is the first fail-closed boundary after the input is complete.
    "manage_products": ("precondition", ("products_storage_unavailable",)),
    "open_discovery_configuration_gate": (
        "precondition",
        ("stage0_turn_scope_not_found",),
    ),
    "open_product_selection_gate": (
        "precondition",
        ("product_selection_scope_unavailable",),
    ),
    # ARV2 onboarding O6: the set-valued sibling derives everything from the presenting turn, so an
    # unresolvable turn ref is its first fail-closed boundary (it reads no Client-KB scope at all).
    "open_product_set_selection_gate": (
        "precondition",
        ("product_set_turn_not_found",),
    ),
    "submit_onboarding_input": ("precondition", ("artifact_not_found",)),
    "start_recon": ("precondition", ("onboarding_input_not_found",)),
    "record_interview_answer": ("precondition", ("onboarding_input_not_found",)),
    "confirm_project_product": ("precondition", ("project_product_not_found",)),
    "evaluate_stage0_readiness": ("precondition", ("stage0_scope_not_found",)),
    # ARV2 O4: the default composition is handed no provider credentials (`build_toolbelt`'s
    # `secrets` defaults to None, fail-closed), so this SPEND tool's Exa path is never reached here.
    "exa_search_evidence": ("precondition", ("exa_not_configured",)),
    # web_search@1: no credentials are handed to the default composition, so the SPEND tool's Exa
    # path is never reached here.
    "web_search": ("precondition", ("exa_not_configured",)),
    # ARV2 R2/R3 (seam 1): the two account tools and R3's on-demand person launch register in
    # EVERY process — the C6 authority audit is a strict set equality — but this matrix composes
    # no `Arv2LaunchService`, so each refuses on composition before it reads a row.
    "launch_arv2_account_research": (
        "precondition",
        ("arv2_account_research_not_composed",),
    ),
    "launch_arv2_person_research": (
        "precondition",
        ("arv2_account_research_not_composed",),
    ),
    "read_arv2_account_research_run": (
        "precondition",
        ("arv2_account_research_not_composed",),
    ),
    # ARV2 R4: the discovery launch registers in every process for the same reason and, with
    # no ``Arv2DiscoveryService`` composed here, refuses before it reads a row.
    "launch_arv2_discovery": (
        "precondition",
        ("arv2_discovery_not_composed",),
    ),
    # ICP authoring registers in every process for the same reason as its ARV2 neighbours and,
    # with no ``IcpAuthoringService`` composed here, refuses before it reads a row.
    "author_icp_document": ("precondition", ("icp_authoring_not_composed",)),
    # Its sibling: the matrix composes no persona-request service, so the request refuses before
    # it reads the project's pin.
    "request_persona_synthesis": ("precondition", ("persona_synthesis_not_composed",)),
    # The project plan writes through storage the matrix does not compose, so the tool refuses
    # before it resolves the presenting turn.
    "write_project_document": ("precondition", ("project_documents_not_composed",)),
    # The three ARV2 reads register in every process too; with no ``Arv2ReadService`` composed
    # here each refuses before it touches a row.
    "read_project_accounts": ("precondition", ("arv2_reads_not_composed",)),
    "read_account_research": ("precondition", ("arv2_reads_not_composed",)),
    "read_discovery_run": ("precondition", ("arv2_reads_not_composed",)),
    # Its ungranted fourth sibling refuses on the same uncomposed service, before it resolves the
    # entity id it was handed.
    "read_claims": ("precondition", ("arv2_reads_not_composed",)),
    "read_cited_claims": ("precondition", ("arv2_reads_not_composed",)),
    # The gallery read needs no service, so its first fail-closed boundary is the project: the
    # matrix's context carries no execution, and the project is ambient rather than a body field.
    "read_artifact": ("precondition", ("project_not_found",)),
    # The sandbox is registered everywhere and composed only where turns are driven, so the
    # matrix — which passes no ``sandbox_workspaces`` — refuses at its first boundary,
    # whatever ``CLUE_SANDBOX_ENABLED`` says on the machine running this.
    "run_python": ("precondition", ("sandbox_unavailable",)),
    "override_stage0_readiness": ("precondition", ("readiness_not_found",)),
    # The matrix composes no durable discovery execution router, and the tool checks for it
    # before it reads the Stage-0 turn scope, so the router is its first fail-closed boundary
    # here. (Old lane; ungranted on every model surface since head-of-abm@v44.)
    "start_confirmed_project_run": (
        "precondition",
        ("confirmed_discovery_router_unavailable",),
    ),
    "draft_account_research_directive": (
        "precondition",
        ("memory_write_not_configured",),
    ),
    "confirm_account_research_directive": (
        "precondition",
        ("research_directive_not_found",),
    ),
    # Lane E E1: this matrix builds the toolbelt without the prose synthesizers, so the governed
    # synthesis surface refuses fail-closed on composition before it reads anything.
    "synthesize_entity_prose": ("precondition", ("prose_synthesis_not_composed",)),
    # Lane E E3: same posture for the positioning surface — the tool registers everywhere so the
    # name set (and the C6 authority check over it) is identical in every process, and an
    # uncomposed one refuses on composition before it reads a job.
    "synthesize_value_narrative": ("precondition", ("value_narrative_not_composed",)),
    # Part II D6 — the design subsystem's governed write path. The envelopes are registered in
    # EVERY process (the C6 authority audit is a strict set equality, so a registry whose shape
    # follows `design_runtime_enabled` would break composition the moment the switch flipped),
    # but a platform build without a design runtime composes no design host, so each one refuses
    # this single reason code before touching a row. Their real preconditions
    # (`design_document_not_found`, `design_publish_slug_taken`, `design_account_exists`, …) are
    # exercised against a live design host in the design API's own suite.
    "design_apply_edits": ("precondition", ("design_runtime_not_configured",)),
    "design_apply_operations": ("precondition", ("design_runtime_not_configured",)),
    "design_apply_web_operations": ("precondition", ("design_runtime_not_configured",)),
    "design_attach_brand_kit": ("precondition", ("design_runtime_not_configured",)),
    "design_compile_component": ("precondition", ("design_runtime_not_configured",)),
    "design_create_document": ("precondition", ("design_runtime_not_configured",)),
    "design_create_snapshot": ("precondition", ("design_runtime_not_configured",)),
    "design_create_web_account": ("precondition", ("design_runtime_not_configured",)),
    "design_create_web_template": ("precondition", ("design_runtime_not_configured",)),
    "design_delete_web_account": ("precondition", ("design_runtime_not_configured",)),
    "design_derive_web_document": ("precondition", ("design_runtime_not_configured",)),
    "design_finalize_document": ("precondition", ("design_runtime_not_configured",)),
    "design_persist_preflight": ("precondition", ("design_runtime_not_configured",)),
    "design_publish_web": ("precondition", ("design_runtime_not_configured",)),
    "design_publish_site": ("precondition", ("design_runtime_not_configured",)),
    "design_record_diagnostics": ("precondition", ("design_runtime_not_configured",)),
    "design_redo_document": ("precondition", ("design_runtime_not_configured",)),
    "design_redo_web_document": ("precondition", ("design_runtime_not_configured",)),
    "design_write_site": ("precondition", ("design_runtime_not_configured",)),
    "design_undo_site": ("precondition", ("design_runtime_not_configured",)),
    "design_redo_site": ("precondition", ("design_runtime_not_configured",)),
    "design_record_site_section": ("precondition", ("design_runtime_not_configured",)),
    "design_replace_scene": ("precondition", ("design_runtime_not_configured",)),
    "design_rollback_web_publish": ("precondition", ("design_runtime_not_configured",)),
    "design_set_agent_instructions": ("precondition", ("design_runtime_not_configured",)),
    "design_set_layout_managed_editing": (
        "precondition",
        ("design_runtime_not_configured",),
    ),
    "design_set_web_noindex": ("precondition", ("design_runtime_not_configured",)),
    "design_rename_document": ("precondition", ("design_runtime_not_configured",)),
    "design_set_document_archived": ("precondition", ("design_runtime_not_configured",)),
    "design_start_agent_turn": ("precondition", ("design_runtime_not_configured",)),
    "design_start_web_turn": ("precondition", ("design_runtime_not_configured",)),
    "design_undo_document": ("precondition", ("design_runtime_not_configured",)),
    "design_undo_web_document": ("precondition", ("design_runtime_not_configured",)),
    "design_unpublish_web": ("precondition", ("design_runtime_not_configured",)),
    "design_update_web_account": ("precondition", ("design_runtime_not_configured",)),
    "design_write_component_source": ("precondition", ("design_runtime_not_configured",)),
    "design_advance_instance_batch": ("precondition", ("design_runtime_not_configured",)),
    "design_advance_web_batch": ("precondition", ("design_runtime_not_configured",)),
    "design_create_brand_compatibility_report": (
        "precondition",
        ("design_runtime_not_configured",),
    ),
    "design_create_brand_kit": ("precondition", ("design_runtime_not_configured",)),
    "design_create_instance_batch": ("precondition", ("design_runtime_not_configured",)),
    "design_create_web_batch": ("precondition", ("design_runtime_not_configured",)),
    "design_delete_asset": ("precondition", ("design_runtime_not_configured",)),
    "design_delete_binding_set": ("precondition", ("design_runtime_not_configured",)),
    "design_derive_instance": ("precondition", ("design_runtime_not_configured",)),
    "design_ingest_ad_assets": ("precondition", ("design_runtime_not_configured",)),
    "design_enrich_assets": ("precondition", ("design_runtime_not_configured",)),
    "design_ingest_assets": ("precondition", ("design_runtime_not_configured",)),
    "design_ingest_pdf": ("precondition", ("design_runtime_not_configured",)),
    "design_ingest_website": ("precondition", ("design_runtime_not_configured",)),
    "design_link_ad_pregenerated_assets": (
        "precondition",
        ("design_runtime_not_configured",),
    ),
    "design_publish_ad_dna_card": ("precondition", ("design_runtime_not_configured",)),
    "design_record_ad_creatives": ("precondition", ("design_runtime_not_configured",)),
    "design_publish_brand_kit_version": ("precondition", ("design_runtime_not_configured",)),
    "design_register_asset_record": ("precondition", ("design_runtime_not_configured",)),
    "design_register_captured_assets": ("precondition", ("design_runtime_not_configured",)),
    "design_register_generated_asset": ("precondition", ("design_runtime_not_configured",)),
    "design_register_qr_asset": ("precondition", ("design_runtime_not_configured",)),
    "design_set_asset_description": ("precondition", ("design_runtime_not_configured",)),
    "design_set_asset_status": ("precondition", ("design_runtime_not_configured",)),
    "design_set_brand_kit_approval": ("precondition", ("design_runtime_not_configured",)),
    "design_upsert_binding_set": ("precondition", ("design_runtime_not_configured",)),
}


def _bodies() -> dict[str, dict[str, object]]:
    return {
        "reverse_profile": {"name": "Acme Robotics", "website": "https://acme.example"},
        # The current @2 synthesis contract accepts no model-authored scope; the execution binding
        # supplies it. Keeping this empty is itself an authority-boundary assertion.
        "synthesize_icps": {},
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
        "launch_selected_account_research": {
            "project_run_id": _UUID(),
            "research_directive_id": _UUID(),
            "account_entity_ids": [_UUID()],
            "source_turn_ref": f"turn-action:{_UUID()}",
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
        "list_client_knowledge": {
            "client_entity_id": _UUID(),
            "client_kb_version": 1,
        },
        "inspect_client_claim": {
            "client_entity_id": _UUID(),
            "client_kb_version": 1,
            "claim_id": _UUID(),
        },
        "list_product_knowledge": {
            "client_entity_id": _UUID(),
            "product_id": "product_missing",
            "product_kb_version": 1,
            "limit": 1,
        },
        "inspect_product_claim": {
            "client_entity_id": _UUID(),
            "product_id": "product_missing",
            "product_kb_version": 1,
            "claim_id": _UUID(),
        },
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
        "create_thread": {"project_id": "prj_absent_from_this_workspace"},
        "rename_thread": {"thread_id": "thr_absent", "title": "renamed"},
        "rename_project": {"project_id": "project_missing", "title": "renamed"},
        "create_project": {
            "project_id": "prj_new",
            "brand_id": "brand_missing",
            "title": "t",
            "description": "",
        },
        "update_project_details": {
            "project_id": "project_missing",
            "title": "t",
            "description": "",
        },
        "set_project_pinned": {"project_id": "project_missing", "pinned": True},
        "set_project_archived": {"project_id": "project_missing", "archived": True},
        "set_thread_pinned": {"thread_id": "thr_absent", "pinned": True},
        "archive_thread": {"thread_id": "thr_absent"},
        "finish_design_leg": {
            "source_turn_ref": f"turn-action:{_UUID()}",
            "reason": "abandoned",
            "summary": "matrix probe",
        },
        "open_design_leg": {
            "source_turn_ref": f"turn-action:{_UUID()}",
            "brief": "matrix probe",
        },
        "open_directive_confirmation_gate": {
            "project_run_id": _UUID(),
            "research_directive_id": _UUID(),
            "account_entity_ids": [_UUID()],
            "source_turn_ref": f"turn-action:{_UUID()}",
        },
        "open_icp_confirmation_gate": {
            "icp_key": "matrix",
            "source_turn_ref": f"turn-action:{_UUID()}",
        },
        "configure_project_targeting": {
            "icp_key": "matrix",
            "source_turn_ref": f"turn-action:{_UUID()}",
        },
        "manage_products": {
            "action": "remove",
            "product_id": "prd_matrix",
            "source_turn_ref": f"turn-action:{_UUID()}",
        },
        "open_product_selection_gate": {
            "source_turn_ref": f"turn-action:{_UUID()}",
        },
        "open_product_set_selection_gate": {
            "source_turn_ref": f"turn-action:{_UUID()}",
        },
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
        # The current @2 readiness contract accepts only the gate. Scope and metrics are trusted
        # backend inputs, so stale v1 fields must not be smuggled into this audit fixture.
        "evaluate_stage0_readiness": {"gate": "icp_synthesis"},
        "exa_search_evidence": {"query": "how practice managers describe referral fax pain"},
        "web_search": {"query": "acme summit 2026"},
        # ARV2 R2/R3 seam 1. The workspace and the requesting human are AMBIENT authority, so
        # neither launch body carries them; the account launch names the exact account set and the
        # pinned ICP artifact it was signed off against, and R3's person launch names contacts that
        # already exist plus the committee seat each one is given.
        "launch_arv2_account_research": {
            "project_id": "prj_matrix",
            "account_entity_ids": (_UUID(),),
            "icp_artifact_key": "icp/matrix.md",
            "icp_artifact_sha256": "0" * 64,
            "product_selection_version": 1,
        },
        "launch_arv2_person_research": {
            "project_id": "prj_matrix",
            "contact_entity_ids": (_UUID(),),
        },
        # ARV2 R4: the workspace and the requesting human are AMBIENT here too. The name-only
        # alias is `@2` (2026-09-30), whose body carries the brief the Head of ABM wrote.
        "launch_arv2_discovery": {
            "project_id": "prj_matrix",
            "target_count": 20,
            "source": "websets",
            "query": "Companies of <kind> that run <activity>.",
            "criteria": ["The company runs <activity>."],
            "gates": [
                {"key": "is_buyer", "rule": "Runs it.", "test": "Its site.", "role": "must"},
                {"key": "sells_it", "rule": "Sells it.", "test": "Its pages.", "role": "must_not"},
            ],
        },
        "author_icp_document": {
            "icp_key": "matrix",
            "document": "---\nkind: icp-definition\nicp_key: matrix\n---\n\nBody.\n",
            "scope": "project",
            "source_turn_ref": f"turn-action:{_UUID()}",
        },
        "request_persona_synthesis": {
            "icp_key": "matrix",
            "source_turn_ref": f"turn-action:{_UUID()}",
        },
        "write_project_document": {
            "document": "plan",
            "body": "# Plan\n\nOutcome.\n",
            "expected_version": 1,
            "source_turn_ref": f"turn-action:{_UUID()}",
        },
        "read_project_accounts": {"project_id": "prj_matrix"},
        "read_account_research": {"account_entity_id": _UUID()},
        "read_discovery_run": {"project_id": "prj_matrix"},
        "read_claims": {"entity_id": _UUID()},
        "read_cited_claims": {"entity_id": _UUID(), "claim_ids": [_UUID()]},
        "read_artifact": {"artifact_id": "doc_matrix"},
        "run_python": {"code": "print(1)"},
        "read_arv2_account_research_run": {"run_id": _UUID()},
        "override_stage0_readiness": {
            "readiness_decision_id": _UUID(),
            "gate": "icp_synthesis",
            "reason": "matrix",
        },
        # The current @2 run-entry contract has no model-authored lineage fields.
        "start_confirmed_project_run": {},
        "open_discovery_configuration_gate": {
            "requested_account_count": 10,
            "search_intent": "Find companies matching the approved ICP",
            "must_have_criteria": ["Industry: healthcare"],
            "exclusion_criteria": [],
            "source_turn_ref": "turn-action:00000000-0000-4000-8000-000000000000",
        },
        "draft_account_research_directive": {
            "project_id": "project_missing",
            "product_id": "product_missing",
            "icp_key": "matrix",
            "icp_version": 1,
            # The promoted @4 contract renames v2's ``body`` to ``directive`` and declares the
            # field breadth; an explicit field list is the ``custom`` request.
            "profile": "custom",
            "directive": {
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
        "synthesize_entity_prose": {"job_id": _UUID(), "field_key": "account.summary"},
        "synthesize_value_narrative": {"job_id": _UUID()},
        "design_publish_web": {
            "document_id": "doc_matrix",
            "slug": "matrix-page",
        },
        "design_publish_site": {"document_id": "doc_matrix", "slug": "matrix-site"},
        "design_unpublish_web": {"slug": "matrix-page"},
        "design_rollback_web_publish": {"slug": "matrix-page"},
        "design_create_web_account": {"account_id": "acc_matrix", "name": "Matrix Co"},
        "design_update_web_account": {
            "account_id": "acc_matrix",
            "patch": {"name": "Matrix Co."},
        },
        "design_delete_web_account": {"account_id": "acc_matrix"},
        "design_write_component_source": {
            "account_id": "acc_matrix",
            "slug": "hero",
            "expected_version": 0,
            "files": {"hero.tsx": "export default () => null;"},
            "provenance": {"kind": "custom_component_source_write"},
        },
        "design_compile_component": {
            "account_id": "acc_matrix",
            "slug": "hero",
            "source_version": 1,
        },
        # Round B — scene documents, history, diagnostics.
        "design_create_document": {
            "document_id": "doc_matrix",
            "scene": {"meta": {"id": "doc_matrix", "title": "Matrix"}},
        },
        "design_set_agent_instructions": {
            "document_id": "doc_matrix",
            "instructions": "Keep it on brand.",
        },
        "design_set_layout_managed_editing": {
            "document_id": "doc_matrix",
            "enabled": True,
        },
        # `enabled` has no default by ruling R-F1: a caller who does not name a value cannot
        # reach the tool at all, so the matrix body names it too.
        "design_set_web_noindex": {
            "document_id": "doc_matrix",
            "enabled": True,
        },
        "design_rename_document": {"document_id": "doc_matrix", "title": "Renamed"},
        "design_set_document_archived": {"document_id": "doc_matrix", "enabled": True},
        "design_replace_scene": {
            "document_id": "doc_matrix",
            "scene": {"meta": {"id": "doc_matrix", "title": "Matrix"}},
        },
        "design_apply_operations": {
            "document_id": "doc_matrix",
            "scene": {"meta": {"id": "doc_matrix", "title": "Matrix"}},
            "operations": [{"kind": "set_text", "id": "n1", "content": "hi"}],
            "source": "editor",
            "actor_kind": "human",
        },
        "design_apply_edits": {
            "document_id": "doc_matrix",
            "scene": {"meta": {"id": "doc_matrix", "title": "Matrix"}},
            "operations": [{"kind": "set_text", "id": "n1", "content": "hi"}],
            "source": "editor",
            "actor_kind": "human",
        },
        "design_undo_document": {
            "document_id": "doc_matrix",
            "scene": {"meta": {"id": "doc_matrix", "title": "Matrix"}},
            "operations": [{"kind": "set_text", "id": "n1", "content": "was"}],
            "envelope": {"intent": "undo:b1", "reverts_batch_id": "b1"},
        },
        "design_redo_document": {
            "document_id": "doc_matrix",
            "scene": {"meta": {"id": "doc_matrix", "title": "Matrix"}},
            "operations": [{"kind": "set_text", "id": "n1", "content": "hi"}],
            "envelope": {"intent": "redo:b1", "reapplies_batch_id": "b1"},
        },
        "design_create_snapshot": {
            "document_id": "doc_matrix",
            "snapshot_id": "snap_matrix",
            "reason": "matrix",
        },
        "design_persist_preflight": {
            "document_id": "doc_matrix",
            "scene": {"meta": {"id": "doc_matrix", "title": "Matrix"}},
            "actor_id": "preflight",
        },
        "design_attach_brand_kit": {
            "document_id": "doc_matrix",
            "scene": {"meta": {"id": "doc_matrix", "title": "Matrix"}},
            "operations": [{"kind": "update_document_brand"}],
            "actor_kind": "human",
            "effective_brand": {"source": "brand_kit_library", "brand_kit": {"id": "bk_1"}},
        },
        "design_finalize_document": {
            "document_id": "doc_matrix",
            "template_revision_id": "tmpl_matrix",
            "scene": {"meta": {"id": "doc_matrix", "title": "Matrix"}},
            "actor_kind": "human",
        },
        "design_record_diagnostics": {
            "document_id": "doc_matrix",
            "kind": "export",
            "diagnostics": [],
        },
        # Round B — website-mode documents.
        "design_create_web_template": {
            "document_id": "doc_matrix_tpl",
            "web_doc": {"id": "doc_matrix_tpl", "title": "Matrix template"},
        },
        "design_derive_web_document": {
            "document_id": "doc_matrix_derived",
            "web_doc": {"id": "doc_matrix_derived", "title": "Matrix — Acme"},
            "template_document_id": "doc_matrix_tpl",
            "template_doc_version": 1,
        },
        "design_apply_web_operations": {
            "document_id": "doc_matrix",
            "web_doc": {"id": "doc_matrix", "title": "Matrix"},
            "operations": [{"kind": "set_text", "page_id": "home", "id": "n1"}],
            "expected_base_version": 1,
        },
        "design_undo_web_document": {
            "document_id": "doc_matrix",
            "web_doc": {"id": "doc_matrix", "title": "Matrix"},
            "operations": [{"kind": "set_text", "page_id": "home", "id": "n1"}],
            "batch_id": "b1",
            "expected_base_version": 1,
        },
        "design_redo_web_document": {
            "document_id": "doc_matrix",
            "web_doc": {"id": "doc_matrix", "title": "Matrix"},
            "operations": [{"kind": "set_text", "page_id": "home", "id": "n1"}],
            "batch_id": "b1",
            "expected_base_version": 1,
        },
        # Wave 2 Lane A — Puck site documents.
        "design_write_site": {
            "document_id": "doc_matrix",
            "site": {"id": "doc_matrix", "title": "Matrix"},
            "expected_base_version": 1,
        },
        "design_undo_site": {"document_id": "doc_matrix", "expected_base_version": 1},
        "design_redo_site": {"document_id": "doc_matrix", "expected_base_version": 1},
        "design_record_site_section": {
            "name": "StepsBand",
            "source": "x",
            "module_js": "x",
            "css": "",
        },
        # Round B — turn enqueues.
        "design_start_agent_turn": {
            "run_id": "run_matrix",
            "work_id": _UUID(),
            "document_id": "doc_matrix",
            "envelope": {"kind": "agent_turn", "run_id": "run_matrix"},
        },
        "design_start_web_turn": {
            "run_id": "run_matrix_web",
            "work_id": _UUID(),
            "document_id": "doc_matrix",
            "envelope": {"kind": "web_turn", "run_id": "run_matrix_web"},
        },
        # Round C — brand kits.
        "design_create_brand_kit": {
            "brand_kit": {"id": "bk_matrix", "version": 1, "name": "Matrix"},
            "brand_summary": {},
            "source": "manual",
        },
        "design_publish_brand_kit_version": {
            "brand_kit": {"id": "bk_matrix", "version": 2, "name": "Matrix"},
            "brand_summary": {},
            "source": "manual",
            "expected_base_version": 1,
        },
        "design_set_brand_kit_approval": {
            "brand_kit_id": "bk_matrix",
            "approval_status": "approved",
        },
        "design_create_brand_compatibility_report": {
            "report_id": "brand_report_matrix",
            "from_brand_kit": {"id": "bk_matrix", "version": 1},
            "to_brand_kit": {"id": "bk_matrix", "version": 2},
            "report": {},
        },
        # Round C — ingestion enqueues.
        "design_ingest_website": {
            "job_id": "ingest_matrix",
            "work_id": _UUID(),
            "request": {"url": "https://matrix.example"},
            "envelope": {"kind": "ingestion", "job_id": "ingest_matrix"},
        },
        "design_ingest_pdf": {
            "job_id": "ingest_matrix_pdf",
            "work_id": _UUID(),
            "request": {"staged_digest": "0" * 64},
            "envelope": {"kind": "ingestion", "job_id": "ingest_matrix_pdf"},
        },
        "design_ingest_assets": {
            "job_id": "ingest_matrix_assets",
            "work_id": _UUID(),
            "request": {"files": []},
            "envelope": {"kind": "ingestion", "job_id": "ingest_matrix_assets"},
        },
        # Brand Ad Assets v1 W2 — the ad-assets lane (design-side flag LUMEN_BRAND_AD_ASSETS
        # gates its route; the envelopes are registered here like every other design tool).
        "design_ingest_ad_assets": {
            "job_id": "ingest_matrix_ad_assets",
            "work_id": _UUID(),
            "request": {"company_domain": "matrix.example"},
            "envelope": {"kind": "ingestion", "job_id": "ingest_matrix_ad_assets"},
        },
        "design_enrich_assets": {
            "job_id": "ingest_matrix_enrich",
            "work_id": _UUID(),
            "request": {"company_domain": "matrix.example"},
            "envelope": {"kind": "ingestion", "job_id": "ingest_matrix_enrich"},
        },
        "design_record_ad_creatives": {
            "creatives": [
                {
                    "creative_id": "adcre_matrix",
                    "harvest_job_id": "ingest_matrix_ad_assets",
                    "provider": "matrix",
                    "ad_id": "1",
                    "creative_url": "https://matrix.example/creative.png",
                    "asset_id": "asset_ad_matrix",
                    "fetched_at": "2026-08-26T00:00:00+00:00",
                }
            ]
        },
        "design_publish_ad_dna_card": {
            "card_id": "adna_matrix",
            "brand_kit_id": "bk_matrix",
            "brand_kit_version": 1,
            "card": {
                "prose": "Every ad is one flat green field with a heavy headline on it.",
                "style_groups": [{"name": "Matrix", "creative_ids": ["adcre_matrix"]}],
            },
        },
        "design_link_ad_pregenerated_assets": {
            "card_id": "adna_matrix",
            "card_version": 1,
            "links": [
                {
                    "asset_id": "asset_gen_matrix",
                    "visual_system": "Matrix",
                    "prompt": "an abstract ground",
                }
            ],
        },
        # Round C — the asset registry.
        "design_register_asset_record": {"record": {"id": "asset_matrix"}},
        "design_register_qr_asset": {"record": {"id": "asset_qr_matrix"}},
        "design_register_generated_asset": {
            "record": {"id": "asset_gen_matrix"},
            "generation_key": "a" * 64,
        },
        "design_register_captured_assets": {"records": [{"id": "asset_ing_matrix"}]},
        "design_set_asset_status": {"asset_id": "asset_matrix", "status": "archived"},
        "design_delete_asset": {"asset_id": "asset_matrix"},
        "design_set_asset_description": {"asset_id": "asset_matrix", "title": "Matrix"},
        # Round C — personalization and both batch families.
        "design_upsert_binding_set": {
            "binding": {
                "binding_set_id": "bind_matrix",
                "template_revision_id": "rev_matrix",
            },
            "status": "valid",
        },
        "design_delete_binding_set": {"binding_set_id": "bind_matrix"},
        "design_derive_instance": {
            "instance": {
                "instance_id": "inst_matrix",
                "template_revision_id": "rev_matrix",
                "binding_set_id": "bind_matrix",
            }
        },
        "design_create_instance_batch": {"batch": {"batch_id": "batch_matrix"}},
        "design_advance_instance_batch": {
            "batch_id": "batch_matrix",
            "expected_cursor": 0,
            "cursor": 5,
            "status": "running",
            "counts": {},
            "manifest": [],
        },
        "design_create_web_batch": {"batch": {"batch_id": "wbatch_matrix"}},
        "design_advance_web_batch": {
            "batch_id": "wbatch_matrix",
            "expected_cursor": 0,
            "cursor": 5,
            "status": "partial",
            "manifest": [],
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
    # launch_account_research / launch_contact_research and their two run-read tools (44 → 48);
    # FI Lane D D0 adds REQ-21's four thread-shell tools (48 → 52), each with exactly one version,
    # and D4 adds the one gate-presenting tool (52 → 53); Lane E E1 adds the governed
    # on-completion prose synthesis surface, and E3 the governed value-narrative positioning
    # surface beside it (53 → 55 in the merged tree). The combined tree retains the Stage-0 ICP
    # gate and selected-Account launch and adds S4's two Client-KB readers plus S5's two Product-KB
    # readers and human-selection gate (55 → 62). Slice 5 retains synthesis @2 for replay and
    # promotes presentation-bearing @3, so the address inventory grows by one without adding a
    # new tool name.
    # The part-iii merge registers the 49 design_* write envelopes and the two design-leg tools
    # in every composition (63 + 51 = 114). Brand Ad Assets v1 W2 adds the ad-assets lane's
    # four design_* envelopes — one ingestion enqueue and three lane writes (114 → 118).
    # Track R (2026-09-09): the design subsystem's `design_set_web_noindex` (ruling R-F1) and
    # the ARV2 lane's three seam-1 envelopes — `launch_arv2_account_research`,
    # `read_arv2_account_research_run` (R2) and `launch_arv2_person_research` (R3) — register
    # in every process alongside the rest (118 -> 123). ARV2 onboarding O6 registers the
    # set-valued product gate `open_product_set_selection_gate` (123 -> 124).
    # ARV2 Track R, R4 registers `launch_arv2_discovery@1`, ungranted (124 -> 125).
    # Human project-label rename adds one governed tool (125 -> 126).
    # ICP authoring registers `author_icp_document@1`, ungranted (126 -> 127), and its sibling
    # `request_persona_synthesis@1` the same way (127 -> 128).
    # The project plan's `write_project_document@1` registers ungranted (128 -> 129), and the
    # three ARV2 reads register on the same terms (129 -> 132). The general claims query
    # `read_claims@1` joins them the same way (132 -> 133): a new NAME, holding the name-only
    # alias because it is the only version of itself, and granted to nobody until a reviewed
    # profile version pins it. The gallery read `read_artifact@1` is the next such name
    # (133 -> 134), composed on nothing but the ambient connection factory.
    # Artifacts page (2026-09-15): design_rename_document and design_set_document_archived,
    # ungranted (134 -> 136 / 154 -> 156).
    # The code sandbox adds `run_python@1`, granted to head-of-abm@v58.
    # The project directory adds four human-only tools: create_project,
    # update_project_details, set_project_pinned and set_project_archived.
    # Together these additions yield 141 names and 161 versioned addresses.
    # Automatic targeting (base) and design_enrich_assets registered without moving these counts;
    # measured off the merged tree: 143 names / 165 addresses before web_search@1, which makes
    # 144 / 166 (2026-09-22).
    # Wave 2 Lane A: three site writes (+3 names, +3 addresses), then the site publish (+1, +1)
    # `read_cited_claims@1` (2026-10-11, Lane B) is a new name at one address (+1), ungranted
    # until the design profile bump.
    # Wave 2 Lane B: design_record_site_section (+1 name, +1 address)
    # Product management (2026-10-15, main): manage_products (+1 name, +1 address).
    assert len(registry.names()) == 151
    # C6 keeps profile_contact@1 for immutable historical pins and elects the governed,
    # project-run-scoped profile_contact@2 as the name-only default.
    # S4-D likewise retains both historical @1 Client-KB readers and registers strict @2 as
    # defaults. Corrected @2 contracts retain their immutable @1 versions, so the combined address
    # inventory is larger than the name inventory without rewriting any historical contract.
    # The part-iii merge adds the design write envelopes and leg tools to the address
    # inventory as well (77 + 52 = 129). Brand Ad Assets v1 W2 adds four more, each at @1
    # only — the lane is new, so it has no historical contract to retain (129 → 133).
    # Slice B wave 2 registers draft_account_research_directive@4 — the comprehensive-profile
    # directive contract — beside its replayable @1/@2/@3 predecessors.
    # The Slice B live-gate repair then registers draft_account_research_directive@5 — @4's
    # advertised input schema made ``directive.field_keys`` required, so a schema-honouring model
    # could never draft the comprehensive profile the steering skill asks for; @5 makes the key
    # omittable and inherits @4's expansion/ambiguity semantics unchanged, beside its replayable
    # @1/@2/@3/@4 predecessors (still no new name).
    # The ARV2-R0 merge unions both lines' registrations; 136 is measured off the merged tree,
    # not derived from either side's arithmetic.
    # The four names Track R and the noindex ruling added each register at @1 only — they are
    # new, so they retain no historical contract (136 -> 140).
    # ARV2 onboarding O6 adds the set-valued product gate at @1 and the artifact-ref ICP gate
    # at @2 beside its replayable @1 (140 -> 142).
    # ARV2 Track R, R4 registers `launch_arv2_discovery@1`, ungranted, at @1 only (142 -> 143).
    # The project rename tool has one version and no agent grant (143 -> 144).
    # ICP authoring's `author_icp_document@1` is new, so it retains no historical contract
    # (144 -> 145), and `request_persona_synthesis@1` likewise (145 -> 146).
    # `write_project_document@1` is new, so it retains no historical contract (146 -> 147), and
    # neither do the three ARV2 reads (147 -> 150).
    # The paged reads add two ADDRESSES and no name (150 -> 152): `read_account_research@2` takes
    # a `limit` and `read_discovery_run@2` takes `offset`/`limit`, and a changed input schema at
    # the same address is exactly what a profile's digest pin exists to catch — so the paging
    # arrived beside the frozen `@1`s. `head-of-abm@v56` pins the `@2`s, so the name-only alias
    # moved to them with the grant; the `@1`s stay registered, aliasless, for replay.
    # `read_claims@1` is a new name at one address (152 -> 153), and `read_artifact@1` is the
    # next (153 -> 154).
    # Artifacts page (2026-09-15): design_rename_document and design_set_document_archived,
    # ungranted (134 -> 136 / 154 -> 156).
    # The code sandbox adds `run_python@1`, granted to head-of-abm@v58.
    # The project directory adds four human-only tools: create_project,
    # update_project_details, set_project_pinned and set_project_archived.
    # Together these additions yield 141 names and 161 versioned addresses.
    # Agent-authored discovery (2026-09-30) registers `launch_arv2_discovery@2` beside the retired
    # `@1`, which stays for replay: one more address, no new name (166 -> 167).
    # And `read_discovery_run@3` (summary, end reason, exclusions) beside `@2` (167 -> 168).
    # And `read_account_research@3` (insights and the buying committee, for Design) beside `@2`
    # (168 -> 169).
    # Wave 2 Lane A: three site writes (+3 names, +3 addresses), then the site publish (+1, +1)
    # `read_cited_claims@1` (2026-10-11, Lane B) is a new name at one address (+1), ungranted
    # until the design profile bump.
    # Wave 2 Lane B: design_record_site_section (+1 name, +1 address)
    # Product management (2026-10-15, main): manage_products@1 (+1).
    # `launch_arv2_discovery@3` (2026-10-16, research-streaming: the brief's exclude list) (+1).
    assert len(registry) == 177
    assert registry.descriptor("draft_account_research_directive").version == "5"
    assert registry.descriptor("synthesize_icps").version == "3"
    assert registry.descriptor("synthesize_icps", "2").version == "2"
    assert registry.descriptor("start_confirmed_project_run").version == "3"
    assert registry.descriptor("start_confirmed_project_run", "1").version == "1"
    assert registry.descriptor("start_confirmed_project_run", "2").version == "2"
    # launch_account_research / launch_contact_research and their two run-read tools (44 → 48).
    # Part II D6 Round A adds the design subsystem's eight governed write tools (publishes ×3,
    # personalization accounts ×3, custom components ×2) — registered in every process, live only
    # where a design runtime is composed (48 -> 56). Round B adds twenty more: the scene
    # document/history/diagnostics plane ×13, website-mode documents ×5 and the two turn
    # enqueues (56 -> 76). Round C adds the last twenty-one: brand kits x4, ingestion
    # enqueues x3, the asset registry x7, personalization + both batch families x7
    # (76 -> 97). FI Lane D D0 adds REQ-21's four thread-shell tools, each with exactly one
    # version, and D4 adds the one gate-presenting tool (97 -> 102 at the integration merge).
    # PD-part3 P3.4 adds `open_design_leg` — the head-of-abm's delegation entry onto the design
    # leg (102 -> 103) — and P3.5 adds `finish_design_leg`, the DESIGN-granted leg-level exit
    # (103 -> 104). The part-iii integration merge unions this branch's own additions since the
    # common base (104 + 10 = 114 names). Brand Ad Assets v1 W2 adds the ad-assets lane's four
    # envelopes: one ingestion enqueue and three lane writes (114 -> 118).
    # Track R (2026-09-09): the design subsystem's `design_set_web_noindex` (ruling R-F1) and
    # the ARV2 lane's three seam-1 envelopes — `launch_arv2_account_research`,
    # `read_arv2_account_research_run` (R2) and `launch_arv2_person_research` (R3) — register
    # in every process alongside the rest (118 -> 123). ARV2 onboarding O6 registers the
    # set-valued product gate `open_product_set_selection_gate` (123 -> 124).
    # ARV2 Track R, R4 registers `launch_arv2_discovery@1`, ungranted (124 -> 125).
    # Human project-label rename adds one governed tool (125 -> 126).
    # ICP authoring registers `author_icp_document@1`, ungranted (126 -> 127), and its sibling
    # `request_persona_synthesis@1` the same way (127 -> 128).
    # The project plan's `write_project_document@1` registers ungranted (128 -> 129), and the
    # three ARV2 reads register on the same terms (129 -> 132). The general claims query
    # `read_claims@1` joins them the same way (132 -> 133): a new NAME, holding the name-only
    # alias because it is the only version of itself, and granted to nobody until a reviewed
    # profile version pins it. The gallery read `read_artifact@1` is the next such name
    # (133 -> 134), composed on nothing but the ambient connection factory.
    # Artifacts page (2026-09-15): design_rename_document and design_set_document_archived,
    # ungranted (134 -> 136 / 154 -> 156).
    # The code sandbox adds `run_python@1`, granted to head-of-abm@v58.
    # The project directory adds four human-only tools: create_project,
    # update_project_details, set_project_pinned and set_project_archived.
    # Together these additions yield 141 names and 161 versioned addresses.
    # Automatic targeting (base) and design_enrich_assets registered without moving these counts;
    # measured off the merged tree: 143 names / 165 addresses before web_search@1, which makes
    # 144 / 166 (2026-09-22).
    # Wave 2 Lane A: three site writes (+3 names, +3 addresses), then the site publish (+1, +1)
    # `read_cited_claims@1` (2026-10-11, Lane B) is a new name at one address (+1), ungranted
    # until the design profile bump.
    # Wave 2 Lane B: design_record_site_section (+1 name, +1 address)
    # Product management (2026-10-15, main): manage_products (+1 name, +1 address).
    assert len(registry.names()) == 151
    # C6 keeps profile_contact@1 for immutable historical pins and elects the governed,
    # project-run-scoped profile_contact@2 as the name-only default. Slice B wave 2's
    # draft_account_research_directive@4 and the live-gate repair's @5 each add an address and
    # no name. 136 is measured off the merged tree (see the note at the first count above).
    # The four names Track R and the noindex ruling added each register at @1 only — they are
    # new, so they retain no historical contract (136 -> 140).
    # ARV2 onboarding O6 adds the set-valued product gate at @1 and the artifact-ref ICP gate
    # at @2 beside its replayable @1 (140 -> 142).
    # ARV2 Track R, R4 registers `launch_arv2_discovery@1`, ungranted, at @1 only (142 -> 143).
    # The project rename tool has one version and no agent grant (143 -> 144).
    # ICP authoring's `author_icp_document@1` is new, so it retains no historical contract
    # (144 -> 145), and `request_persona_synthesis@1` likewise (145 -> 146).
    # `write_project_document@1` is new, so it retains no historical contract (146 -> 147), and
    # neither do the three ARV2 reads (147 -> 150).
    # The paged reads add two ADDRESSES and no name (150 -> 152): `read_account_research@2` takes
    # a `limit` and `read_discovery_run@2` takes `offset`/`limit`, and a changed input schema at
    # the same address is exactly what a profile's digest pin exists to catch — so the paging
    # arrived beside the frozen `@1`s. `head-of-abm@v56` pins the `@2`s, so the name-only alias
    # moved to them with the grant; the `@1`s stay registered, aliasless, for replay.
    # `read_claims@1` is a new name at one address (152 -> 153), and `read_artifact@1` is the
    # next (153 -> 154).
    # Artifacts page (2026-09-15): design_rename_document and design_set_document_archived,
    # ungranted (134 -> 136 / 154 -> 156).
    # The code sandbox adds `run_python@1`, granted to head-of-abm@v58.
    # The project directory adds four human-only tools: create_project,
    # update_project_details, set_project_pinned and set_project_archived.
    # Together these additions yield 141 names and 161 versioned addresses.
    # Agent-authored discovery (2026-09-30) registers `launch_arv2_discovery@2` beside the retired
    # `@1`, which stays for replay: one more address, no new name (166 -> 167).
    # And `read_discovery_run@3` (summary, end reason, exclusions) beside `@2` (167 -> 168).
    # And `read_account_research@3` (insights and the buying committee, for Design) beside `@2`
    # (168 -> 169).
    # Wave 2 Lane A: three site writes (+3 names, +3 addresses), then the site publish (+1, +1)
    # `read_cited_claims@1` (2026-10-11, Lane B) is a new name at one address (+1), ungranted
    # until the design profile bump.
    # Wave 2 Lane B: design_record_site_section (+1 name, +1 address)
    # Product management (2026-10-15, main): manage_products@1 (+1).
    # `launch_arv2_discovery@3` (2026-10-16, research-streaming: the brief's exclude list) (+1).
    assert len(registry) == 177
    assert registry.descriptor("profile_contact").version == "2"
    assert registry.descriptor("profile_contact", "1").version == "1"
    assert {
        item.address for item in registry.all_descriptors() if item.name == "research_account_gaps"
    } == {
        "research_account_gaps@1",
        "research_account_gaps@2",
    }
    # Slice 5 promoted presentation-bearing draft @3 as the default; Slice B wave 2 promoted the
    # comprehensive-profile @4, and the live-gate repair promoted the satisfiable-schema @5.
    # Confirm stays @2.
    assert registry.descriptor("draft_account_research_directive").version == "5"
    assert registry.descriptor("confirm_account_research_directive").version == "2"
    # The alias never disagrees with the promoted profile's pin: `head-of-abm@v56` pins the paged
    # `@2` of both reads, so an unversioned caller gets `@2` and the frozen `@1`s stay resolvable
    # only by exact address.
    assert registry.descriptor("read_account_research").version == "2"
    assert registry.descriptor("read_account_research", "1").version == "1"
    # Agent-authored discovery (2026-09-30): `read_discovery_run@3` owns the name-only alias, as
    # `launch_arv2_discovery@2` does; `@2` stays resolvable by exact address for replay, and
    # `head-of-abm@v70` grants `@3`.
    assert registry.descriptor("read_discovery_run").version == "3"
    assert registry.descriptor("read_discovery_run", "2").version == "2"
    assert registry.descriptor("read_discovery_run", "1").version == "1"


def test_default_composition_gives_start_recon_an_autonomous_progress_factory() -> None:
    """FI-4 slice 3: the production composition is the ONLY thing that turns on autonomous
    per-field progress commits, and without them the onboarding screen shows nothing for the
    whole fast lane (its own transaction stays uncommitted until the lane ends). An injected
    factory must still fall back to the lane connection — a second checkout would deadlock a
    single-connection harness — so both directions are pinned here."""
    default_tool = build_toolbelt(storage=None, gateway=None).get("start_recon")
    assert default_tool._field_progress_factory is not None  # type: ignore[attr-defined]

    @asynccontextmanager
    async def injected() -> AsyncIterator[AsyncConnection]:  # pragma: no cover - never entered
        raise AssertionError("the composition must not open a connection")
        yield

    injected_tool = build_toolbelt(storage=None, gateway=None, conn_factory=injected).get(
        "start_recon"
    )
    assert injected_tool._field_progress_factory is None  # type: ignore[attr-defined]


def test_duplicate_tool_registration_is_impossible_by_construction() -> None:
    # build_toolbelt registers each tool type exactly once; a second build is an independent
    # registry (no shared mutable state), so two builds never collide.
    a = build_toolbelt(storage=None, gateway=None)
    b = build_toolbelt(storage=None, gateway=None)
    assert a is not b
    assert a.names() == b.names()
