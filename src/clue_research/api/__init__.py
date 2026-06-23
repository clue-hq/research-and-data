"""`clue_research.api` — the composition root / app layer (M5/M13 + the M8 deep-profiling wiring).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. ``api`` is the import-linter-exempt seam where the otherwise-independent milestone
packages are wired together (nothing imports ``api`` — Rule 5).

Shipped so far — the **deep-profiling composition root** (:mod:`clue_research.api.composition`):
loads the field packs + source manifests, constructs + registers the M8 account/committee/contact
:class:`~clue_research.core.execution.AspectWorker`\\s into the M7 ``WorkerRegistry``, and injects
the M9 governance seams (``verification.classify_binding`` behind M8.4's ``BindingClassifier``; the
``PreSpendGate`` before account/committee/contact spend). The FastAPI HTTP surface is still M5/M13.
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

__all__ = [
    "load_research_packs",
    "VerificationBindingClassifier",
    "production_binding_classifier",
    "build_pre_spend_gate",
    "build_profiling_workers",
    "register_profiling_workers",
    "build_worker_registry",
    "build_research_graph",
]
