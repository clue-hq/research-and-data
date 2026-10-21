"""`clue_api` — the composition root / app layer (M5/M13 + the M8 deep-profiling wiring).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. ``api`` is the import-linter-exempt seam where the otherwise-independent milestone
packages are wired together (nothing imports ``api`` — Rule 5).

Shipped so far:

* the **deep-profiling composition root** (:mod:`clue_api.composition`): loads the field
  packs + source manifests, constructs + registers the M8 account/committee/contact
  :class:`~clue_core.execution.AspectWorker`\\s into the M7 ``WorkerRegistry``, and injects
  the M9 governance seams (``verification.classify_binding`` behind M8.4's ``BindingClassifier``;
  the
  ``PreSpendGate`` before account/committee/contact spend).
* the **M11 synthesis wiring** (:mod:`clue_api.synthesis_wiring`): binds the Exa Deep /
  Parallel Task tier-4 resolvers behind the shared ``Resolver`` seam.
* the **M10 compliance wiring** (:mod:`clue_api.compliance_wiring`): registers the
  ``contact.jurisdiction`` + shorter personal-data retention TTL field pack (the use-gate /
  retention-sweep runtime seams land with the ``ProjectPhase.VERIFICATION`` handler).
* the **M12 narrative wiring** (:mod:`clue_api.narrative_wiring`): the
``account.value_narrative``
  field pack, the Client-Knowledge retriever stub, and the M12.2 handoff assembler construction.
* the **VERIFICATION composition root** (:mod:`clue_api.verification`): the
  ``ProjectPhase.VERIFICATION`` phase handler that drives the frozen ``VERIFICATION_GATE_ORDER``
  (corroboration → faithfulness → use-gate last) over the deep-produced claims and records per-field
  verification-health — the integration keystone that makes tier-4 ``current_value`` non-empty.
* the **M12.3 output/handoff boundary** — the FastAPI read API
  (:mod:`clue_api.handoff_app`) and its wiring (:mod:`clue_api.handoff_wiring`):
  the
  durable-backed readiness reader, the :class:`~clue_research.narrative.HandoffService`, and the
  ``ProjectPhase.HANDOFF`` phase handler that drives the durable emit/notify path. This is the
  terminal seam of the subsystem (overview §3).
* the **M13 Review/Feedback/Observability wiring** — the ``ProjectPhase.REVIEW`` handler
  (:mod:`clue_api.review`), the M13.2 disposition substrate
  (:mod:`clue_api.disposition_wiring`), the M13.4 read-only observability surface
  (:mod:`clue_api.observability_wiring`), and the integration join
  (:mod:`clue_api.review_feedback_wiring`): binds M13.2's concrete disposition emitter into
  the M13.1 review surface and cascades M10.5 erasure/objection into disposition tombstoning.
"""

from __future__ import annotations

from clue_api.account_research_turn_wiring import (
    DbCompiledContextCardReader,
    PreparedAccountResearchTurnRunner,
    account_research_context_policy,
    build_account_research_context,
)
from clue_api.account_research_wiring import (
    AccountResearchAgentRuntime,
    AccountResearchStepPinProvider,
    AccountResearchTurnRunner,
    GovernedAccountProfiler,
    build_account_research_execution,
)
from clue_api.agent_execution_wiring import (
    AgentExecutionCrashHook,
    C5AgentExecutionAdapter,
    DbAgentDelegationRuntime,
    DbAgentPlanJournal,
    FreshWakeChildRunner,
    postgres_agent_checkpointer,
)
from clue_api.agent_platform_wiring import (
    AgentCanaryAssessment,
    AgentCanarySample,
    AgentCanaryThresholds,
    AgentOwner,
    AgentOwnershipRouter,
    AgentPlatformComponents,
    AgentRouteDecision,
    AgentRuntimeNotComposed,
    AgentRuntimeSurface,
    DbAgentOwnershipRouter,
    RoutedAccountProfiler,
    build_agent_context_assembler,
    build_agent_platform_components,
    evaluate_agent_canary,
    run_owned_agent_surface,
)
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_runtime_wiring import (
    AgentFinalizationAuthority,
    DurableAgentModelCallHandler,
    DurableDeepAgentTurnRunner,
    GovernedAgentToolFactory,
    ModelFinalizeRequest,
)
from clue_api.backtest_wiring import (
    LabeledDatasetBacktestGate,
    build_backtest_gate,
)
from clue_api.compliance_wiring import register_compliance_wiring
from clue_api.composition import (
    VerificationBindingClassifier,
    build_pre_spend_gate,
    build_profiling_workers,
    build_research_graph,
    build_worker_registry,
    load_research_packs,
    production_binding_classifier,
    register_profiling_workers,
)
from clue_api.contact_content_handoff import (
    ContactContentHandoffService,
    build_contact_content_handoff_service,
)
from clue_api.contact_eligibility import (
    ContactEligibilityResolver,
    GovernedCommitteeContact,
    GovernedCommitteeViewReader,
    GovernedContactClaim,
    ProductionHandoffCommitteeReader,
    build_contact_eligibility_resolver,
    build_governed_committee_view_reader,
    build_production_handoff_committee_reader,
)
from clue_api.discovery_seal import (
    DbSealedDiscoveryAccountManifestReader,
    DurableDiscoveryPhaseHandler,
    build_discovery_batch_manifest,
)
from clue_api.disposition_wiring import (
    build_disposition_store,
    build_review_disposition_emitter,
)
from clue_api.execution_tools import (
    AdvanceProjectPhaseInput,
    ExecutionControlServices,
    PinExecutionAsRecipeInput,
    execution_control_tools,
    register_execution_control_tools,
)
from clue_api.execution_wiring import (
    ExecutionRunEventWriter,
    StorageExecutionParameterStore,
    StorageParameterArtifactStore,
    build_tool_invoker,
)
from clue_api.fleet_wiring import (
    build_account_lock_factory,
    build_fleet_deep_scheduler,
    build_fleet_run_driver,
    build_fleet_worker,
    build_multi_work_worker,
    enqueue_run_drive,
    lazy_account_lock_factory,
    register_boot_handlers,
    tier_priority_from_rubric,
)
from clue_api.handoff_app import (
    HANDOFF_SCHEMA_HEADER,
    create_handoff_app,
    create_handoff_router,
    handoff_lifespan,
    header_workspace_resolver,
    read_conn_dependency,
)
from clue_api.handoff_retention import (
    RetentionSweepHandoffHandler,
    build_retention_sweeping_handoff_handler,
    register_retention_sweeping_handoff_handler,
)
from clue_api.handoff_wiring import (
    DurableHandoffReadinessReader,
    HandoffPhaseHandler,
    build_handoff_phase_handler,
    build_handoff_readiness_reader,
    build_handoff_service,
    register_handoff_phase_handler,
)
from clue_api.head_of_abm_wiring import (
    HeadOfAbmStage0Runtime,
    build_head_of_abm_stage0_execution,
)
from clue_api.learning_wiring import build_learning_loop
from clue_api.narrative_wiring import (
    build_client_knowledge_retriever,
    build_handoff_assembler,
    register_narrative_wiring,
)
from clue_api.observability_wiring import (
    BudgetCapsPreRunEstimator,
    BudgetEngineBurnDownReader,
    CheckpointCoverageReportReader,
    ClaimScanVerificationHealthReader,
    DurableCampaignStateReader,
    build_campaign_state_reader,
    build_cost_burndown_reader,
    build_coverage_report_reader,
    build_observability_surface,
    build_pre_run_estimator,
    build_verification_health_reader,
)
from clue_api.phase_c_wiring import (
    IngestionProposalSink,
    ProductionIngestionClaimConstructionRoute,
    ProductionIngestionClaimErasureRoute,
    ProductionIngestionContactClaimRoute,
    Stage0ScrapeBinder,
    build_ingestion_engine,
    build_stage0_scrape_binder,
    register_generic_web_wiring,
)
from clue_api.phase_wiring import (
    build_discovery_handler,
    build_icp_confirmed_handler,
    build_reverse_profiling_handler,
    build_scoring_handler,
    build_tier_checkpoint_handler,
    register_discovery_handler,
    register_icp_confirmed_handler,
    register_reverse_profiling_handler,
    register_scoring_handler,
    register_tier_checkpoint_handler,
    snapshot_bound,
)
from clue_api.projections_app import (
    PROJECTIONS_SCHEMA_HEADER,
    create_projections_app,
    create_projections_router,
)
from clue_api.recipe_wiring import (
    STAGE0_POLICY_VERSION,
    SYSTEM_RECIPE_FILENAMES,
    VersionedPinResource,
    build_recipe_lifecycle,
    build_recipe_pin_registry,
    load_system_recipe_definitions,
    seed_system_recipes,
    system_recipe_asset_root,
)
from clue_api.review import (
    DbVerificationAnnotationReader,
    NoopReviewDispositionEmitter,
    ProjectRunResumeHook,
    ReviewPhaseHandler,
    build_review_account_resolver,
    build_review_phase_handler,
    build_review_surface,
    register_review_phase_handler,
)
from clue_api.review_feedback_wiring import (
    ContactDispositionTombstoner,
    TombstoneCascadingDataSubjectRights,
    build_dsar_with_disposition_cascade,
    build_reviewed_phase_handler,
    register_reviewed_phase_handler,
)
from clue_api.run_composition import (
    ClientInputProvider,
    ComposedRun,
    ComposingRunDriver,
    CompositionUnavailable,
    SpecLoader,
    build_platform_gateway,
)
from clue_api.run_events_wiring import (
    DbRunEventEmitter,
    NullRunEventEmitter,
    RunEventEmitter,
    build_run_event_emitter,
)
from clue_api.specialist_wiring import (
    DbSpecialistExecutionJournal,
    FreshWakeSpecialistRunner,
    SpecialistExecutionAdapter,
    SpecialistExecutionFactory,
    SpecialistSpendReader,
    SpecialistWorkspaceProvider,
)
from clue_api.storage_wiring import (
    DEFAULT_ORPHAN_SWEEP_GRACE,
    SnapshotBindingPhaseHandler,
    bind_snapshots_around_deep,
    build_data_subject_rights,
    build_storage_backend,
    run_orphan_blob_sweep,
)
from clue_api.stream_tokens import consume_stream_token, mint_stream_token
from clue_api.synthesis_wiring import register_synthesis_wiring
from clue_api.toolbelt_wiring import (
    GatewayRequired,
    build_toolbelt,
)
from clue_api.verification import (
    VerificationPhaseHandler,
    build_verification_phase_handler,
    register_verification_phase_handler,
)

__all__ = [
    # C6.8 production composition, routing, canaries, and cleanup
    "AgentCanaryAssessment",
    "AgentCanarySample",
    "AgentCanaryThresholds",
    "AgentOwner",
    "AgentOwnershipRouter",
    "AgentPlatformComponents",
    "AgentRouteDecision",
    "AgentRuntimeNotComposed",
    "AgentRuntimeSurface",
    "DbAgentOwnershipRouter",
    "RoutedAccountProfiler",
    "build_agent_context_assembler",
    "build_agent_platform_components",
    "build_agent_profile_registry",
    "evaluate_agent_canary",
    "run_owned_agent_surface",
    # C6.4 governed agent plan/runtime/finalization composition
    "AgentExecutionCrashHook",
    "C5AgentExecutionAdapter",
    "DbAgentDelegationRuntime",
    "DbAgentPlanJournal",
    "FreshWakeChildRunner",
    "postgres_agent_checkpointer",
    "AgentFinalizationAuthority",
    "DurableAgentModelCallHandler",
    "DurableDeepAgentTurnRunner",
    "GovernedAgentToolFactory",
    "ModelFinalizeRequest",
    # C6.6 fresh-wake specialists
    "DbSpecialistExecutionJournal",
    "FreshWakeSpecialistRunner",
    "SpecialistExecutionAdapter",
    "SpecialistExecutionFactory",
    "SpecialistSpendReader",
    "SpecialistWorkspaceProvider",
    # C6.5 Head-of-ABM Stage-0 vertical
    "HeadOfAbmStage0Runtime",
    "build_head_of_abm_stage0_execution",
    # C6.7 governed per-account research unit
    "AccountResearchAgentRuntime",
    "AccountResearchStepPinProvider",
    "AccountResearchTurnRunner",
    "GovernedAccountProfiler",
    "build_account_research_execution",
    "DbCompiledContextCardReader",
    "PreparedAccountResearchTurnRunner",
    "account_research_context_policy",
    "build_account_research_context",
    "load_research_packs",
    "VerificationBindingClassifier",
    "production_binding_classifier",
    "build_pre_spend_gate",
    "build_profiling_workers",
    "register_profiling_workers",
    "build_worker_registry",
    "build_research_graph",
    # M11 synthesis wiring
    "register_synthesis_wiring",
    # M10 compliance wiring
    "register_compliance_wiring",
    # VERIFICATION phase handler (integration keystone)
    "VerificationPhaseHandler",
    "build_verification_phase_handler",
    "register_verification_phase_handler",
    # HANDOFF retention/objection tombstone-before-merge-read sweep (M10.5 × M12)
    "RetentionSweepHandoffHandler",
    "build_retention_sweeping_handoff_handler",
    "register_retention_sweeping_handoff_handler",
    # M12 narrative wiring
    "register_narrative_wiring",
    "build_client_knowledge_retriever",
    "build_handoff_assembler",
    # C7.6 shared governed contact/committee eligibility
    "ContactEligibilityResolver",
    "GovernedCommitteeContact",
    "GovernedContactClaim",
    "GovernedCommitteeViewReader",
    "ProductionHandoffCommitteeReader",
    "build_contact_eligibility_resolver",
    "build_governed_committee_view_reader",
    "build_production_handoff_committee_reader",
    # M8C C7 reference-only research-to-content bridge
    "ContactContentHandoffService",
    "build_contact_content_handoff_service",
    # M12.3 handoff API + emit wiring
    "create_handoff_app",
    "create_handoff_router",
    "handoff_lifespan",
    "header_workspace_resolver",
    "read_conn_dependency",
    "HANDOFF_SCHEMA_HEADER",
    "DurableHandoffReadinessReader",
    "build_handoff_readiness_reader",
    "build_handoff_service",
    "HandoffPhaseHandler",
    "build_handoff_phase_handler",
    "register_handoff_phase_handler",
    # M13.4 observability surface wiring
    "DurableCampaignStateReader",
    "BudgetEngineBurnDownReader",
    "BudgetCapsPreRunEstimator",
    "ClaimScanVerificationHealthReader",
    "CheckpointCoverageReportReader",
    "build_campaign_state_reader",
    "build_cost_burndown_reader",
    "build_pre_run_estimator",
    "build_verification_health_reader",
    "build_coverage_report_reader",
    "build_observability_surface",
    # M13.1 review-surface wiring
    "ReviewPhaseHandler",
    "DbVerificationAnnotationReader",
    "ProjectRunResumeHook",
    "NoopReviewDispositionEmitter",
    "build_review_account_resolver",
    "build_review_surface",
    "build_review_phase_handler",
    "register_review_phase_handler",
    # M13.2 disposition-capture wiring
    "build_disposition_store",
    "build_review_disposition_emitter",
    # M13 integration join (review↔disposition emitter; M10.5→disposition tombstone cascade)
    "build_reviewed_phase_handler",
    "register_reviewed_phase_handler",
    "ContactDispositionTombstoner",
    "TombstoneCascadingDataSubjectRights",
    "build_dsar_with_disposition_cascade",
    # M13.3 learning-loop wiring (backtest gate + the loop)
    "LabeledDatasetBacktestGate",
    "build_backtest_gate",
    "build_learning_loop",
    # B2 storage wiring (one backend, per-run snapshot binding, erasure + orphan-sweep paths)
    "build_storage_backend",
    "SnapshotBindingPhaseHandler",
    "bind_snapshots_around_deep",
    "build_data_subject_rights",
    "run_orphan_blob_sweep",
    "DEFAULT_ORPHAN_SWEEP_GRACE",
    # B1 fleet wiring (boot handlers, single-flight lock factory, scheduler/driver/worker, resume)
    "register_boot_handlers",
    "build_account_lock_factory",
    "lazy_account_lock_factory",
    "tier_priority_from_rubric",
    "build_fleet_deep_scheduler",
    "build_fleet_run_driver",
    "build_fleet_worker",
    "build_multi_work_worker",
    "enqueue_run_drive",
    # B4 slice 1: M5/M6 phase registration surfaces (phase_wiring)
    "build_reverse_profiling_handler",
    "register_reverse_profiling_handler",
    "build_icp_confirmed_handler",
    "register_icp_confirmed_handler",
    "build_discovery_handler",
    "register_discovery_handler",
    "build_scoring_handler",
    "register_scoring_handler",
    "build_tier_checkpoint_handler",
    "register_tier_checkpoint_handler",
    "snapshot_bound",
    # M6A D5: immutable discovery batch seal and scoring membership barrier
    "DurableDiscoveryPhaseHandler",
    "DbSealedDiscoveryAccountManifestReader",
    "build_discovery_batch_manifest",
    # Phase C1-C3 integration wiring
    "IngestionProposalSink",
    "ProductionIngestionClaimErasureRoute",
    "ProductionIngestionClaimConstructionRoute",
    "ProductionIngestionContactClaimRoute",
    "Stage0ScrapeBinder",
    "build_ingestion_engine",
    "build_stage0_scrape_binder",
    "register_generic_web_wiring",
    # B4 slice 1: the fleet run-start composition (ComposingRunDriver)
    "ComposingRunDriver",
    "ComposedRun",
    "CompositionUnavailable",
    "SpecLoader",
    "build_platform_gateway",
    "ClientInputProvider",
    # B4 slice 2: the concrete toolbelt over the existing capabilities (toolbelt_wiring)
    "build_toolbelt",
    "GatewayRequired",
    # C5.1: mandatory parameter snapshot + execution journal invocation composition
    "ExecutionRunEventWriter",
    "StorageExecutionParameterStore",
    "StorageParameterArtifactStore",
    "build_tool_invoker",
    # C5.3: graph execution controls and multi-kind fleet composition
    "AdvanceProjectPhaseInput",
    "ExecutionControlServices",
    "PinExecutionAsRecipeInput",
    "execution_control_tools",
    "register_execution_control_tools",
    # C5.2: exact compatibility adapters + immutable system-recipe seed
    "STAGE0_POLICY_VERSION",
    "SYSTEM_RECIPE_FILENAMES",
    "VersionedPinResource",
    "build_recipe_lifecycle",
    "build_recipe_pin_registry",
    "load_system_recipe_definitions",
    "seed_system_recipes",
    "system_recipe_asset_root",
    # B4 slice 3: the read-side HTTP surface (projections + tool route + manifest ops + SSE)
    "create_projections_app",
    "create_projections_router",
    "PROJECTIONS_SCHEMA_HEADER",
    # B4 slice 3: the run_event SSE emitter (drive-path write) + stream-token store
    "RunEventEmitter",
    "DbRunEventEmitter",
    "NullRunEventEmitter",
    "build_run_event_emitter",
    "mint_stream_token",
    "consume_stream_token",
]
