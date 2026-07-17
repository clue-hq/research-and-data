"""`clue_research.api` — the composition root / app layer (M5/M13 + the M8 deep-profiling wiring).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. ``api`` is the import-linter-exempt seam where the otherwise-independent milestone
packages are wired together (nothing imports ``api`` — Rule 5).

Shipped so far:

* the **deep-profiling composition root** (:mod:`clue_research.api.composition`): loads the field
  packs + source manifests, constructs + registers the M8 account/committee/contact
  :class:`~clue_core.execution.AspectWorker`\\s into the M7 ``WorkerRegistry``, and injects
  the M9 governance seams (``verification.classify_binding`` behind M8.4's ``BindingClassifier``;
  the
  ``PreSpendGate`` before account/committee/contact spend).
* the **M11 synthesis wiring** (:mod:`clue_research.api.synthesis_wiring`): binds the Exa Deep /
  Parallel Task tier-4 resolvers behind the shared ``Resolver`` seam.
* the **M10 compliance wiring** (:mod:`clue_research.api.compliance_wiring`): registers the
  ``contact.jurisdiction`` + shorter personal-data retention TTL field pack (the use-gate /
  retention-sweep runtime seams land with the ``CampaignPhase.VERIFICATION`` handler).
* the **M12 narrative wiring** (:mod:`clue_research.api.narrative_wiring`): the
``account.value_narrative``
  field pack, the Client-Knowledge retriever stub, and the M12.2 handoff assembler construction.
* the **VERIFICATION composition root** (:mod:`clue_research.api.verification`): the
  ``CampaignPhase.VERIFICATION`` phase handler that drives the frozen ``VERIFICATION_GATE_ORDER``
  (corroboration → faithfulness → use-gate last) over the deep-produced claims and records per-field
  verification-health — the integration keystone that makes tier-4 ``current_value`` non-empty.
* the **M12.3 output/handoff boundary** — the FastAPI read API
  (:mod:`clue_research.api.handoff_app`) and its wiring (:mod:`clue_research.api.handoff_wiring`):
  the
  durable-backed readiness reader, the :class:`~clue_research.narrative.HandoffService`, and the
  ``CampaignPhase.HANDOFF`` phase handler that drives the durable emit/notify path. This is the
  terminal seam of the subsystem (overview §3).
* the **M13 Review/Feedback/Observability wiring** — the ``CampaignPhase.REVIEW`` handler
  (:mod:`clue_research.api.review`), the M13.2 disposition substrate
  (:mod:`clue_research.api.disposition_wiring`), the M13.4 read-only observability surface
  (:mod:`clue_research.api.observability_wiring`), and the integration join
  (:mod:`clue_research.api.review_feedback_wiring`): binds M13.2's concrete disposition emitter into
  the M13.1 review surface and cascades M10.5 erasure/objection into disposition tombstoning.
"""

from __future__ import annotations

from clue_research.api.backtest_wiring import (
    LabeledDatasetBacktestGate,
    build_backtest_gate,
)
from clue_research.api.compliance_wiring import register_compliance_wiring
from clue_research.api.composition import (
    VerificationBindingClassifier,
    build_pre_spend_gate,
    build_profiling_workers,
    build_research_graph,
    build_worker_registry,
    load_research_packs,
    production_binding_classifier,
    register_profiling_workers,
)
from clue_research.api.disposition_wiring import (
    build_disposition_store,
    build_review_disposition_emitter,
)
from clue_research.api.handoff_app import (
    HANDOFF_SCHEMA_HEADER,
    create_handoff_app,
    create_handoff_router,
    handoff_lifespan,
    header_workspace_resolver,
    read_conn_dependency,
)
from clue_research.api.handoff_retention import (
    RetentionSweepHandoffHandler,
    build_retention_sweeping_handoff_handler,
    register_retention_sweeping_handoff_handler,
)
from clue_research.api.handoff_wiring import (
    DurableHandoffReadinessReader,
    HandoffPhaseHandler,
    build_handoff_phase_handler,
    build_handoff_readiness_reader,
    build_handoff_service,
    register_handoff_phase_handler,
)
from clue_research.api.learning_wiring import build_learning_loop
from clue_research.api.narrative_wiring import (
    build_client_knowledge_retriever,
    build_handoff_assembler,
    register_narrative_wiring,
)
from clue_research.api.observability_wiring import (
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
from clue_research.api.review import (
    CampaignRunResumeHook,
    DbVerificationAnnotationReader,
    NoopReviewDispositionEmitter,
    ReviewPhaseHandler,
    build_review_account_resolver,
    build_review_phase_handler,
    build_review_surface,
    register_review_phase_handler,
)
from clue_research.api.review_feedback_wiring import (
    ContactDispositionTombstoner,
    TombstoneCascadingDataSubjectRights,
    build_dsar_with_disposition_cascade,
    build_reviewed_phase_handler,
    register_reviewed_phase_handler,
)
from clue_research.api.synthesis_wiring import register_synthesis_wiring
from clue_research.api.verification import (
    VerificationPhaseHandler,
    build_verification_phase_handler,
    register_verification_phase_handler,
)

__all__ = [
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
    "CampaignRunResumeHook",
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
]
