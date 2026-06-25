"""`clue_research.api` — the composition root / app layer (M5/M13 + the M8 deep-profiling wiring).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. ``api`` is the import-linter-exempt seam where the otherwise-independent milestone
packages are wired together (nothing imports ``api`` — Rule 5).

Shipped so far:

* the **deep-profiling composition root** (:mod:`clue_research.api.composition`): loads the field
  packs + source manifests, constructs + registers the M8 account/committee/contact
  :class:`~clue_research.core.execution.AspectWorker`\\s into the M7 ``WorkerRegistry``, and injects
  the M9 governance seams (``verification.classify_binding`` behind M8.4's ``BindingClassifier``;
  the
  ``PreSpendGate`` before account/committee/contact spend).
* the **M12 narrative wiring** (:mod:`clue_research.api.narrative_wiring`): the
``account.value_narrative``
  field pack, the Client-Knowledge retriever stub, and the M12.2 handoff assembler construction.
* the **M12.3 output/handoff boundary** — the FastAPI read API
  (:mod:`clue_research.api.handoff_app`) and its wiring (:mod:`clue_research.api.handoff_wiring`):
  the
  durable-backed readiness reader, the :class:`~clue_research.narrative.HandoffService`, and the
  ``CampaignPhase.HANDOFF`` phase handler that drives the durable emit/notify path. This is the
  terminal seam of the subsystem (overview §3).
"""

from __future__ import annotations

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
from clue_research.api.handoff_app import (
    HANDOFF_SCHEMA_HEADER,
    create_handoff_app,
    create_handoff_router,
    handoff_lifespan,
    header_tenant_resolver,
    read_conn_dependency,
)
from clue_research.api.handoff_wiring import (
    DurableHandoffReadinessReader,
    HandoffPhaseHandler,
    build_handoff_phase_handler,
    build_handoff_readiness_reader,
    build_handoff_service,
    register_handoff_phase_handler,
)
from clue_research.api.narrative_wiring import (
    build_client_knowledge_retriever,
    build_handoff_assembler,
    register_narrative_wiring,
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
    # M12 narrative wiring
    "register_narrative_wiring",
    "build_client_knowledge_retriever",
    "build_handoff_assembler",
    # M12.3 handoff API + emit wiring
    "create_handoff_app",
    "create_handoff_router",
    "handoff_lifespan",
    "header_tenant_resolver",
    "read_conn_dependency",
    "HANDOFF_SCHEMA_HEADER",
    "DurableHandoffReadinessReader",
    "build_handoff_readiness_reader",
    "build_handoff_service",
    "HandoffPhaseHandler",
    "build_handoff_phase_handler",
    "register_handoff_phase_handler",
]
